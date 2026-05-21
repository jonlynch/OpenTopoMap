#!/usr/bin/env python3
"""
compute_saddle_directions.py — ridge-axis bearing for OSM saddle nodes from DEM.

Ports mapnik/tools/saddledirection.c to Python, using a remote PMTiles DEM
archive (with on-disk tile caching) instead of a local GeoTIFF.

For each natural=saddle/col/notch node, samples N=60 elevations on a circle
of radius 100 m around the saddle, computes the ridge axis via the
(front+back)−(left+right) kernel, and writes a CSV that process-otm.lua
loads at tile-build time.

Output: CSV with columns  osm_id,direction  (direction in [0, 179]).
Saddles outside DEM coverage or hitting NODATA are silently omitted so that
Lua falls back to any OSM direction tag.

Usage:
  python3 compute_saddle_directions.py \\
      --pbf osm/region-renumbered.osm.pbf \\
      --output data/saddle_directions.csv

Requirements:
  pip install pmtiles Pillow numpy
  apt install osmium-tool
"""

import argparse
import csv
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import requests

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Direction algorithm constants (mirrors saddledirection.c defaults)
# ---------------------------------------------------------------------------

DEFAULT_STEPS  = 60   # must be divisible by 4
DEFAULT_RADIUS = 200  # metres
DEFAULT_ZOOM   = 13   # ~11 m/pixel at Cumbria's latitude

EARTH_CIRCUMFERENCE = 40_000_000  # metres (matches saddledirection.c)


# ---------------------------------------------------------------------------
# PMTiles HTTP source
# ---------------------------------------------------------------------------

def http_source(url):
    """
    Returns a pmtiles Source callable: (offset, length) -> bytes.

    Uses a requests.Session for connection pooling — the pmtiles Reader
    makes many small range requests, and without connection reuse each one
    incurs a fresh TCP+TLS handshake, which can trigger timeouts.
    """
    import time

    session = requests.Session()

    def get_bytes(offset, length):
        end = offset + length - 1
        headers = {"Range": f"bytes={offset}-{end}"}
        last_err = None
        for attempt in (1, 2):
            try:
                resp = session.get(url, headers=headers, timeout=60)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as e:
                last_err = e
                if attempt == 1:
                    print(f"  Network error on attempt 1, retrying in 2 s: {e}", file=sys.stderr)
                    time.sleep(2)
        raise last_err
    return get_bytes


# ---------------------------------------------------------------------------
# DEM tile cache
# ---------------------------------------------------------------------------

def cache_path(cache_dir, z, x, y):
    return os.path.join(cache_dir, str(z), str(x), f"{y}.npy")


def load_tile(reader, z, x, y, cache_dir, no_cache):
    """
    Return a float32 numpy array (256×256, metres) for tile (z, x, y).

    Checks cache_dir first (unless --no-cache). On cache miss, fetches the
    WebP tile from the PMTiles archive, decodes it via Pillow, converts RGB
    to elevation using *elevation_decode*, and persists the result as .npy.
    """
    cpath = cache_path(cache_dir, z, x, y)

    if not no_cache and os.path.exists(cpath):
        return np.load(cpath)

    blob = reader.get(z, x, y)
    if blob is None:
        return None

    img = Image.open(io.BytesIO(blob))
    arr = np.array(img).astype(np.float32)

    if not no_cache:
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        np.save(cpath, arr)

    return arr


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def lonlat_to_pixel(z, lon, lat):
    """
    Convert (lon, lat) to web Mercator pixel coordinates at zoom z.
    Returns (px_x, px_y) as floats.
    """
    n = 1 << z
    px_x = (lon + 180.0) / 360.0 * n * 256.0
    lat_rad = math.radians(lat)
    px_y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return px_x, px_y


def pixel_to_tile(px):
    """Return tile index and intra-tile offset from pixel coordinate."""
    tile = int(math.floor(px / 256.0))
    offset = px - tile * 256.0
    return tile, offset


def metres_per_degree(lat_deg):
    m_per_deg_lat = EARTH_CIRCUMFERENCE / 360.0
    m_per_deg_lon = EARTH_CIRCUMFERENCE / 360.0 * math.cos(math.radians(lat_deg))
    return m_per_deg_lon, m_per_deg_lat


# ---------------------------------------------------------------------------
# Elevation decoding detection
# ---------------------------------------------------------------------------

def detect_elevation_encoding(reader):
    """
    Determine the RGB→elevation formula by sampling a z0 tile (which should
    always exist in a global archive).

    Returns one of "terrain_rgb", "terrarium".
    Falls back to "terrain_rgb" if detection is inconclusive.
    """
    try:
        blob = reader.get(0, 0, 0)
        if blob is None:
            return "terrain_rgb"
        img = Image.open(io.BytesIO(blob))
        arr = np.array(img)
        if arr.ndim < 3 or arr.shape[2] < 3:
            return "terrain_rgb"

        # Sample a few non-zero pixels
        r, g, b = arr[..., 0].astype(np.float32), arr[..., 1].astype(np.float32), arr[..., 2].astype(np.float32)
        mask = (r > 0) | (g > 0) | (b > 0)
        if mask.sum() < 10:
            return "terrain_rgb"

        r_s = r[mask][:100]; g_s = g[mask][:100]; b_s = b[mask][:100]

        tb = -10000 + (r_s * 65536 + g_s * 256 + b_s) * 0.1
        tr = (r_s * 256 + g_s + b_s / 256) - 32768

        # Terrain-RGB typical range: -10000 to 9000 — values should be bounded
        tb_in_range = ((tb > -500) & (tb < 9000)).mean()
        tr_in_range = ((tr > -500) & (tr < 9000)).mean()

        if tr_in_range > tb_in_range:
            return "terrarium"
        return "terrain_rgb"
    except Exception:
        return "terrain_rgb"


def decode_elevation(rgb_pixel, encoding):
    """
    Convert a 3-channel RGB value to elevation in metres.
    rgb_pixel is a tuple or array (R, G, B).
    """
    r, g, b = float(rgb_pixel[0]), float(rgb_pixel[1]), float(rgb_pixel[2])
    if encoding == "terrarium":
        return (r * 256.0 + g + b / 256.0) - 32768.0
    else:
        return -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1


# ---------------------------------------------------------------------------
# Elevation sampling
# ---------------------------------------------------------------------------

def sample_circle(z, lon, lat, radius_m, steps, reader, cache_dir, no_cache, encoding):
    """
    Sample elevations on a circle of radius_m metres around (lon, lat).

    Returns a numpy array of length *steps* with elevation in metres, or
    None if any sample hits NODATA (black tile / missing tile).
    """
    px_c, py_c = lonlat_to_pixel(z, lon, lat)
    lat_rad = math.radians(lat)
    metres_per_px = EARTH_CIRCUMFERENCE / (256.0 * (1 << z)) * math.cos(lat_rad)

    # Buffer of tiles we've already loaded
    tile_cache = {}

    def get_elevation(px, py):
        tx, off_x = pixel_to_tile(px)
        ty, off_y = pixel_to_tile(py)

        key = (tx, ty)
        if key not in tile_cache:
            tile_cache[key] = load_tile(reader, z, tx, ty, cache_dir, no_cache)

        tile = tile_cache[key]
        if tile is None:
            return None

        # Bilinear interpolation within tile.
        # Tile images may be 256 or 512 px wide — scale offsets accordingly.
        tile_h, tile_w = tile.shape[:2]
        scale = tile_w / 256.0
        off_x_scaled = off_x * scale
        off_y_scaled = off_y * scale

        ix = int(math.floor(off_x_scaled))
        iy = int(math.floor(off_y_scaled))
        dx = off_x_scaled - ix
        dy = off_y_scaled - iy

        # Clamp to valid range (need ix+1 and iy+1 access)
        ix = max(0, min(tile_w - 2, ix))
        iy = max(0, min(tile_h - 2, iy))

        # Check for black/NODATA (all-zero RGB)
        try:
            ul = decode_elevation(tile[iy, ix, :3], encoding)
            ur = decode_elevation(tile[iy, ix + 1, :3], encoding)
            ll = decode_elevation(tile[iy + 1, ix, :3], encoding)
            lr = decode_elevation(tile[iy + 1, ix + 1, :3], encoding)
        except IndexError:
            return None

        # NODATA check: elevation encodings map black (0,0,0) to extreme values
        if any(abs(v) > 32000 for v in (ul, ur, ll, lr)):
            return None

        # Bilinear interpolation (matches saddledirection.c's interpolate_height)
        denom = 1.0 * 1.0  # dx * dy are in pixel units, each cell is 1×1
        h = (ll * (1.0 - dx) * dy + lr * dx * dy +
             ul * (1.0 - dx) * (1.0 - dy) + ur * dx * (1.0 - dy))
        return h

    h = np.zeros(steps, dtype=np.float64)

    for i in range(steps):
        angle_rad = i * (360.0 / steps) * math.pi / 180.0
        dx_m = radius_m * math.sin(angle_rad)
        dy_m = radius_m * math.cos(angle_rad)
        dx_px = dx_m / metres_per_px
        dy_px = dy_m / metres_per_px

        val = get_elevation(px_c + dx_px, py_c - dy_px)  # y-axis inverted in pixel space
        if val is None or abs(val) > 32000:
            return None
        h[i] = val

    return h


# ---------------------------------------------------------------------------
# Direction kernel (port of saddledirection.c's interpolate_direction)
# ---------------------------------------------------------------------------

def compute_direction(h, steps):
    """
    Compute ridge-axis bearing from elevation samples on a circle.

    h: array of length `steps` with elevation in metres
    steps: number of angular samples (must be divisible by 4)

    Returns bearing in [0, 179], matching the C tool's output.
    """
    half = steps // 2
    quarter = steps // 4

    dh = np.zeros(steps, dtype=np.float64)
    dh_min = 1e100
    min_step = 0

    for i in range(half):
        if i < quarter:
            base = h[i] + h[(i + half) % steps] - h[(i + quarter) % steps] - h[(i + 3 * quarter) % steps]
            if steps <= 24:
                dh[i] = base
            else:
                # 3-point smoothing kernel [1, 0.33, 0.14] — from saddledirection.c
                next_i = (i + 1) % steps
                next_i2 = (i + 2) % steps
                base1 = (h[next_i] + h[(next_i + half) % steps] -
                         h[(next_i + quarter) % steps] - h[(next_i + 3 * quarter) % steps])
                base2 = (h[next_i2] + h[(next_i2 + half) % steps] -
                         h[(next_i2 + quarter) % steps] - h[(next_i2 + 3 * quarter) % steps])
                dh[i] = base + 0.33 * base1 + 0.14 * base2

            dh[i + quarter] = -dh[i]

        if dh[i] < dh_min:
            dh_min = dh[i]
            min_step = i

    direction = (min_step * 360 // steps + 360) % 180
    return direction


# ---------------------------------------------------------------------------
# Saddle extraction from PBF via osmium
# ---------------------------------------------------------------------------

def extract_saddles(pbf_path):
    """
    Return list of saddle dicts: {id (int), lon, lat}.
    Uses osmium command-line tools (matching compute_isolation.py pattern).
    """
    print(f"Extracting saddles from {pbf_path} ...", file=sys.stderr)

    tmp_pbf = tempfile.mktemp(suffix=".osm.pbf")
    tmp_seq = tempfile.mktemp(suffix=".geojsonseq")

    try:
        subprocess.run(
            ["osmium", "tags-filter", pbf_path,
             "n/natural=saddle", "n/natural=col", "n/natural=notch",
             "-o", tmp_pbf, "--overwrite"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["osmium", "export", tmp_pbf,
             "--geometry=point",
             "--attributes=id",
             "--output-format=geojsonseq",
             "-o", tmp_seq, "--overwrite"],
            check=True, capture_output=True,
        )

        saddles = []
        with open(tmp_seq) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    feat = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if feat.get("geometry", {}).get("type") != "Point":
                    continue

                lon, lat = feat["geometry"]["coordinates"][:2]
                props = feat.get("properties", {})
                raw_id = props.get("@id")
                try:
                    osm_id = int(raw_id)
                except (ValueError, TypeError):
                    continue

                saddles.append({"id": osm_id, "lon": lon, "lat": lat})

        print(f"  Found {len(saddles)} saddle/col/notch nodes.", file=sys.stderr)
        return saddles

    finally:
        for p in (tmp_pbf, tmp_seq):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pbf", required=True, help="Input OSM PBF file (renumbered)")
    parser.add_argument("--output", required=True, help="Output CSV path (osm_id,direction)")
    parser.add_argument("--pmtiles-url",
                        default="https://pbcc.blob.core.windows.net/pbcc-pmtiles/DTM.pmtiles",
                        help="PMTiles archive URL")
    parser.add_argument("--zoom", type=int, default=DEFAULT_ZOOM,
                        help=f"Zoom level for DEM sampling (default: {DEFAULT_ZOOM})")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS,
                        help=f"Sampling circle radius in metres (default: {DEFAULT_RADIUS})")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS,
                        help=f"Angular samples on the circle (default: {DEFAULT_STEPS}, must be divisible by 4)")
    parser.add_argument("--cache-dir", default="data/dem_cache",
                        help="Tile cache directory (default: data/dem_cache)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip cache — always refetch tiles from network")
    args = parser.parse_args()

    if args.steps % 4 != 0:
        print(f"Error: --steps must be divisible by 4 (got {args.steps}).", file=sys.stderr)
        sys.exit(1)

    # Extract saddles from PBF
    saddles = extract_saddles(args.pbf)
    if not saddles:
        print("No saddles found — check PBF path.", file=sys.stderr)
        sys.exit(1)

    # Initialise PMTiles reader
    print(f"Opening PMTiles archive at {args.pmtiles_url} ...", file=sys.stderr)
    try:
        from pmtiles.reader import Reader
        source = http_source(args.pmtiles_url)
        reader = Reader(source)
        # Smoke test: read the header
        _ = reader.header()
    except ImportError:
        print("Error: pmtiles package not installed.", file=sys.stderr)
        print("  Install with: pip install pmtiles", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error opening PMTiles archive: {e}", file=sys.stderr)
        sys.exit(1)

    # Detect elevation encoding
    encoding = detect_elevation_encoding(reader)
    print(f"  Detected elevation encoding: {encoding}", file=sys.stderr)

    # Set up cache directory
    os.makedirs(args.cache_dir, exist_ok=True)

    # Process each saddle
    results = []
    n_ok = 0
    n_fail = 0

    for i, s in enumerate(saddles):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Processing saddle {i + 1}/{len(saddles)} ...", file=sys.stderr)

        try:
            h = sample_circle(args.zoom, s["lon"], s["lat"],
                              args.radius, args.steps,
                              reader, args.cache_dir, args.no_cache, encoding)
        except (requests.RequestException, OSError) as e:
            print(f"Fatal network error fetching DEM tile: {e}", file=sys.stderr)
            print("Aborting — partial CSV has NOT been written.", file=sys.stderr)
            sys.exit(1)

        if h is None:
            n_fail += 1
            continue

        direction = compute_direction(h, args.steps)
        results.append((s["id"], direction))
        n_ok += 1

    # Write CSV
    output_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "direction"])
        for osm_id, direction in results:
            w.writerow([osm_id, direction])

    print(f"Wrote {len(results)} rows to {args.output}", file=sys.stderr)
    print(f"  {n_ok} OK, {n_fail} omitted (NODATA / outside DEM coverage)", file=sys.stderr)


if __name__ == "__main__":
    main()
