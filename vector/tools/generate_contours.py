#!/usr/bin/env python3
"""
generate_contours.py — produce contour shapefiles from Mapterhorn DEM tiles.

Fetches Terrarium-encoded terrain RGB tiles from the Mapterhorn tile endpoint,
assembles them into a GDAL VRT, runs gdal_contour at multiple intervals, and
post-processes the output to add index/minor level attributes.

The resulting shapefiles are consumed by tilemaker (via source + source_columns)
to bake contour lines directly into the vector tiles.

Usage:
  python3 generate_contours.py \\
      --pbf osm/region-renumbered.osm.pbf \\
      --output-dir data/contours

Requirements:
  pip install requests Pillow numpy fiona shapely
  apt install gdal-bin osmium-tool
"""

import argparse
import io
import math
import os
import shutil
import subprocess
import sys
import time
import glob

import fiona
import fiona.crs
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from PIL import Image
import requests
from shapely.geometry import mapping, shape


TILE_SIZE = 512
EARTH_CIRCUMFERENCE = 40_000_000

INTERVALS = {
    10: {"level_mod": 100},
    20: {"level_mod": 100},
    50: {"level_mod": 500},
}


# ---------------------------------------------------------------------------
# Bbox extraction
# ---------------------------------------------------------------------------

def extract_bbox(pbf_path):
    result = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.boxes", pbf_path],
        capture_output=True, text=True, check=True,
    )
    raw = result.stdout.strip()
    if not raw or raw == "(none)":
        print(f"Error: PBF has no bounding box in header: {pbf_path}", file=sys.stderr)
        sys.exit(1)
    parts = raw.strip("()").split(",")
    return tuple(float(p) for p in parts)


def buffer_bbox(bbox, buf=0.05):
    return (bbox[0] - buf, bbox[1] - buf, bbox[2] + buf, bbox[3] + buf)


# ---------------------------------------------------------------------------
# Tile coordinate maths
# ---------------------------------------------------------------------------

def lon_to_tile_x(lon, z):
    return int(math.floor((lon + 180.0) / 360.0 * (1 << z)))


def lat_to_tile_y(lat, z):
    lat_rad = math.radians(lat)
    n = 1 << z
    return int(math.floor((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n))


def tile_bounds(z, x, y):
    n = 1 << z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def tiles_for_bbox(bbox, z):
    min_lon, min_lat, max_lon, max_lat = bbox
    x_min = lon_to_tile_x(min_lon, z)
    x_max = lon_to_tile_x(max_lon, z)
    y_min = lat_to_tile_y(max_lat, z)
    y_max = lat_to_tile_y(min_lat, z)
    tiles = []
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tiles.append((z, x, y))
    return tiles


# ---------------------------------------------------------------------------
# Tile fetching
# ---------------------------------------------------------------------------

def fetch_tile(session, url_template, z, x, y, cache_dir):
    cache_file = os.path.join(cache_dir, str(z), str(x), f"{y}.webp")
    if os.path.exists(cache_file):
        return cache_file

    url = url_template.format(z=z, x=x, y=y)
    last_err = None
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "wb") as f:
                f.write(resp.content)
            return cache_file
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    print(f"  Warning: failed to fetch tile {z}/{x}/{y} after 3 attempts: {last_err}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Terrarium decoding → GeoTIFF
# ---------------------------------------------------------------------------

def decode_terrarium_to_geotiff(webp_path, geotiff_path, bounds):
    img = Image.open(webp_path)
    arr = np.array(img).astype(np.float32)

    if arr.ndim < 3 or arr.shape[2] < 3:
        return False

    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    elevation = (r * 256.0 + g + b / 256.0) - 32768.0

    height, width = elevation.shape
    lon_min, lat_min, lon_max, lat_max = bounds

    os.makedirs(os.path.dirname(geotiff_path), exist_ok=True)

    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)

    with rasterio.open(
        geotiff_path, "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-32768.0,
        compress="lzw",
        tiled=True,
    ) as dst:
        dst.write(elevation, 1)

    return True


# ---------------------------------------------------------------------------
# VRT assembly + contour generation
# ---------------------------------------------------------------------------

def build_vrt(geotiff_dir, output_vrt):
    tifs = sorted(glob.glob(os.path.join(geotiff_dir, "**", "*.tif"), recursive=True))
    if not tifs:
        print("Error: no GeoTIFFs found to build VRT.", file=sys.stderr)
        sys.exit(1)

    file_list = output_vrt + ".txt"
    with open(file_list, "w") as f:
        for t in tifs:
            f.write(os.path.abspath(t) + "\n")

    subprocess.run(
        ["gdalbuildvrt", "-q", "-input_file_list", file_list, output_vrt],
        check=True, capture_output=True,
    )
    os.unlink(file_list)
    print(f"  Built VRT from {len(tifs)} GeoTIFFs", file=sys.stderr)


def run_gdal_contour(vrt_path, interval, output_shp):
    os.makedirs(os.path.dirname(output_shp), exist_ok=True)

    for ext in (".shp", ".shx", ".dbf", ".prj"):
        p = output_shp.replace(".shp", ext)
        if os.path.exists(p):
            os.unlink(p)

    subprocess.run([
        "gdal_contour",
        "-a", "ele",
        "-i", str(interval),
        "-f", "ESRI Shapefile",
        vrt_path,
        output_shp,
    ], check=True)


# ---------------------------------------------------------------------------
# Post-processing: add level attribute, filter ele=0 / negative
# ---------------------------------------------------------------------------

def postprocess_shapefile(raw_shp, output_shp, level_mod):
    schema = {
        "geometry": "LineString",
        "properties": {
            "ele": "int",
            "level": "int",
        },
    }

    count = 0
    skipped = 0
    with fiona.open(raw_shp, "r") as src:
        with fiona.open(output_shp, "w", driver="ESRI Shapefile",
                        schema=schema, crs="EPSG:4326") as dst:
            for feat in src:
                ele_raw = feat["properties"].get("ele")
                if ele_raw is None:
                    skipped += 1
                    continue

                ele = int(round(float(ele_raw)))
                if ele <= 0:
                    skipped += 1
                    continue

                geom = shape(feat["geometry"])
                if geom.is_empty or geom.length == 0:
                    skipped += 1
                    continue

                # Reverse line direction so labels read uphill (cartographic convention)
                geom = geom.reverse()

                level = 1 if ele % level_mod == 0 else 0

                dst.write({
                    "geometry": mapping(geom),
                    "properties": {
                        "ele": ele,
                        "level": level,
                    },
                })
                count += 1

    return count, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pbf", required=True,
                        help="Input OSM PBF file (used to extract bounding box)")
    parser.add_argument("--output-dir", default="data/contours",
                        help="Output directory for contour shapefiles (default: data/contours)")
    parser.add_argument("--dem-zoom", type=int, default=12,
                        help="Zoom level for DEM tiles (default: 12, ~19m/px at 50°N)")
    parser.add_argument("--dem-url",
                        default="https://tiles.mapterhorn.com/{z}/{x}/{y}.webp",
                        help="DEM tile URL template")
    parser.add_argument("--cache-dir", default="data/dem_cache",
                        help="Tile cache directory (default: data/dem_cache)")
    parser.add_argument("--geotiff-dir", default="data/dem_geotiffs",
                        help="Intermediate GeoTIFF directory (default: data/dem_geotiffs)")
    parser.add_argument("--buffer", type=float, default=0.05,
                        help="Bbox buffer in degrees (default: 0.05)")
    parser.add_argument("--keep-geotiffs", action="store_true",
                        help="Keep intermediate GeoTIFFs after contour generation")
    parser.add_argument("--intervals", default="10,20,50",
                        help="Comma-separated contour intervals in metres (default: 10,20,50)")
    args = parser.parse_args()

    intervals = [int(x) for x in args.intervals.split(",")]
    for iv in intervals:
        if iv not in INTERVALS:
            print(f"Error: unsupported interval {iv}m. Supported: {list(INTERVALS.keys())}", file=sys.stderr)
            sys.exit(1)

    # Step 1: Extract bbox from PBF
    print(f"=== Extracting bbox from {args.pbf} ===", file=sys.stderr)
    bbox = extract_bbox(args.pbf)
    print(f"  PBF bbox: {bbox}", file=sys.stderr)
    bbox = buffer_bbox(bbox, args.buffer)
    print(f"  Buffered bbox: {bbox}", file=sys.stderr)

    # Step 2: Compute tile list
    tiles = tiles_for_bbox(bbox, args.dem_zoom)
    print(f"  {len(tiles)} DEM tiles at z{args.dem_zoom}", file=sys.stderr)

    # Step 3: Fetch tiles and decode to GeoTIFFs
    print(f"=== Fetching DEM tiles ===", file=sys.stderr)
    session = requests.Session()
    session.headers.update({"User-Agent": "OpenTopoMap/generate_contours"})

    os.makedirs(args.cache_dir, exist_ok=True)
    os.makedirs(args.geotiff_dir, exist_ok=True)

    n_cached = 0
    n_fetched = 0
    n_failed = 0
    n_decoded = 0

    for i, (z, x, y) in enumerate(tiles):
        if (i + 1) % 100 == 0 or i == 0:
            print(f"  Tile {i + 1}/{len(tiles)} (cached: {n_cached}, fetched: {n_fetched}, failed: {n_failed})", file=sys.stderr)

        geotiff_path = os.path.join(args.geotiff_dir, str(z), str(x), f"{y}.tif")
        if os.path.exists(geotiff_path):
            n_cached += 1
            continue

        cache_file = os.path.join(args.cache_dir, str(z), str(x), f"{y}.webp")
        already_cached = os.path.exists(cache_file)

        webp_path = fetch_tile(session, args.dem_url, z, x, y, args.cache_dir)
        if webp_path is None:
            n_failed += 1
            continue

        if already_cached:
            n_cached += 1
        else:
            n_fetched += 1

        bounds = tile_bounds(z, x, y)
        if decode_terrarium_to_geotiff(webp_path, geotiff_path, bounds):
            n_decoded += 1

    print(f"  Done: {n_decoded} GeoTIFFs decoded, {n_cached} cache hits, {n_fetched} fetched, {n_failed} failed", file=sys.stderr)

    # Step 4: Build VRT
    print(f"=== Building VRT ===", file=sys.stderr)
    vrt_path = os.path.join(args.output_dir, "dem_mosaic.vrt")
    os.makedirs(args.output_dir, exist_ok=True)
    build_vrt(args.geotiff_dir, vrt_path)

    # Step 5: Generate contours at each interval
    for interval in sorted(intervals):
        print(f"=== Generating {interval}m contours ===", file=sys.stderr)
        raw_shp = os.path.join(args.output_dir, f"contours_{interval}m_raw.shp")
        final_shp = os.path.join(args.output_dir, f"contours_{interval}m.shp")

        run_gdal_contour(vrt_path, interval, raw_shp)

        level_mod = INTERVALS[interval]["level_mod"]
        count, skipped = postprocess_shapefile(raw_shp, final_shp, level_mod)
        print(f"  {count} contour lines written, {skipped} filtered (ele<=0 or empty)", file=sys.stderr)

        for ext in (".shp", ".shx", ".dbf", ".prj"):
            p = raw_shp.replace(".shp", ext)
            if os.path.exists(p):
                os.unlink(p)

    # Step 6: Clean up intermediate GeoTIFFs
    if not args.keep_geotiffs:
        print(f"=== Cleaning up intermediate GeoTIFFs ===", file=sys.stderr)
        shutil.rmtree(args.geotiff_dir, ignore_errors=True)

    # Clean up VRT
    if os.path.exists(vrt_path):
        os.unlink(vrt_path)

    print(f"=== Done — shapefiles in {args.output_dir}/ ===", file=sys.stderr)
    for interval in sorted(intervals):
        shp = os.path.join(args.output_dir, f"contours_{interval}m.shp")
        if os.path.exists(shp):
            with fiona.open(shp) as src:
                print(f"  contours_{interval}m.shp: {len(src)} features", file=sys.stderr)


if __name__ == "__main__":
    main()
