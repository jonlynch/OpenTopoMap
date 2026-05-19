#!/usr/bin/env python3
"""
compute_isolation.py — topographic isolation for OSM peak nodes.

Replicates mapnik/tools/isolation.c in Python, producing a CSV that
process-otm.lua loads at tile-generation time so peak labels appear at
zoom levels matching the raster pipeline's isolation-based filtering.

Two-pass algorithm (matching isolation.c):
  Pass 1 — peak-to-peak:
    Sort all peaks by latitude.  For each pair where one is higher than
    the other, record the distance as an initial isolation upper bound.
    This tightens the DEM search window in pass 2.
  Pass 2 — DEM scan (requires --dem):
    For each peak, load DEM pixels within its current isolation radius
    and find the nearest pixel that exceeds the peak elevation by at
    least MINDIFF metres.

Output: CSV with columns  osm_id,isolation  (isolation in metres, integer).
Designed to be loaded by the Lua init_function() at tilemaker run time.

Usage:
  python3 compute_isolation.py \\
      --pbf  osm/cumbria-latest.osm.pbf \\
      --dem  /path/to/dem.tif \\
      --output data/peak_isolation.csv

  Without --dem, only pass 1 runs (faster, less accurate for dense ranges).
  The DEM must be a single-band int16 GeoTIFF in EPSG:4326.

Requirements:
  pip install rasterio numpy
  apt install osmium-tool
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

# Mirror constants from isolation.c
MINDIFF  = 20       # metres: DEM pixel must exceed peak elevation by this much
MINISO   = 100      # metres: ignore higher ground closer than this
EARTH_C  = 40_000_000  # metres: circumference used in isolation.c (40 Mm, not 40.075)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metres_per_degree(lat_deg):
    """Returns (m_per_deg_lon, m_per_deg_lat) at the given latitude."""
    m_per_deg_lat = EARTH_C / 360
    m_per_deg_lon = EARTH_C / 360 * math.cos(math.radians(lat_deg))
    return m_per_deg_lon, m_per_deg_lat


def peak_distance(a, b):
    """Approximate planar distance in metres between two peak dicts, using
    isolation.c's formula (cosine correction at peak a's latitude)."""
    m_lon, m_lat = metres_per_degree(a['lat'])
    dx = (b['lon'] - a['lon']) * m_lon
    dy = (b['lat'] - a['lat']) * m_lat
    return math.sqrt(dx * dx + dy * dy)


def parse_ele(s):
    """Sanitise an ele string to float metres, returning None on failure.
    Mirrors isolation.c checkele(): handles 'm' suffix, 'ft' conversion,
    comma-as-decimal, and rejects impossible values."""
    if not s:
        return None
    s = str(s).strip().replace(',', '.')
    suffix = ''
    for sfx in (' m', 'm', ' ft', 'ft'):
        if s.endswith(sfx):
            suffix = sfx.strip()
            s = s[:-len(sfx)].strip()
            break
    try:
        v = float(s)
    except ValueError:
        return None
    if suffix == 'ft':
        v *= 0.3048
    if v > 9000 or v < -12000:
        return None
    return v


# ---------------------------------------------------------------------------
# Step 1: extract peaks from PBF via osmium
# ---------------------------------------------------------------------------

def extract_peaks(pbf_path):
    """
    Return a list of peak dicts: {id (int), lon, lat, ele (float|None)}.
    Uses osmium command-line tools.
    """
    print(f'Extracting peaks from {pbf_path} ...', file=sys.stderr)

    tmp_pbf   = tempfile.mktemp(suffix='.osm.pbf')
    tmp_seq   = tempfile.mktemp(suffix='.geojsonseq')

    try:
        subprocess.run(
            ['osmium', 'tags-filter', pbf_path,
             'n/natural=peak', 'n/natural=volcano',
             '-o', tmp_pbf, '--overwrite'],
            check=True, capture_output=True,
        )
        subprocess.run(
            ['osmium', 'export', tmp_pbf,
             '--geometry=point',
             '--attributes=id',
             '--output-format=geojsonseq',
             '-o', tmp_seq, '--overwrite'],
            check=True, capture_output=True,
        )

        peaks = []
        with open(tmp_seq) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    feat = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if feat.get('geometry', {}).get('type') != 'Point':
                    continue

                lon, lat = feat['geometry']['coordinates'][:2]
                props    = feat.get('properties', {})

                raw_id = props.get('@id')
                try:
                    osm_id = int(raw_id)
                except (ValueError, TypeError):
                    continue

                ele = parse_ele(props.get('ele', ''))

                peaks.append({'id': osm_id, 'lon': lon, 'lat': lat, 'ele': ele})

        print(f'  Found {len(peaks)} peak/volcano nodes.', file=sys.stderr)
        return peaks

    finally:
        for p in (tmp_pbf, tmp_seq):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Pass 1: peak-to-peak isolation
# ---------------------------------------------------------------------------

def isolation_pass1(peaks, radius):
    """
    Set each peak's isolation to the distance to its nearest higher OSM peak.
    Mirrors get_isolation_by_ele() in isolation.c.

    Peaks must be sorted by latitude (ascending) before calling.
    Returns nothing — mutates peak['isolation'] in place.
    """
    n = len(peaks)
    m_lat = EARTH_C / 360  # metres per degree of latitude (constant)

    for i in range(n):
        pi = peaks[i]
        for j in range(i + 1, n):
            pj = peaks[j]
            dy = (pj['lat'] - pi['lat']) * m_lat
            if dy >= pi['isolation'] and dy >= pj['isolation']:
                # All remaining j are even further north — stop
                break
            d = peak_distance(pi, pj)
            if d >= radius:
                continue
            # Update the lower peak if the other is higher
            if pi['ele'] is not None and pj['ele'] is not None:
                if pi['ele'] > pj['ele'] and d < pj['isolation']:
                    pj['isolation'] = d
                if pj['ele'] > pi['ele'] and d < pi['isolation']:
                    pi['isolation'] = d


# ---------------------------------------------------------------------------
# Pass 2: DEM-based refinement
# ---------------------------------------------------------------------------

def isolation_pass2(peaks, dem_path):
    """
    Refine each peak's isolation by scanning actual DEM terrain within the
    current isolation radius.  Mirrors get_isolation_by_DEM() in isolation.c.
    Mutates peak['isolation'] in place.
    """
    try:
        import rasterio
        from rasterio.transform import rowcol as rc
    except ImportError:
        print('rasterio not installed — skipping pass 2 (DEM scan).', file=sys.stderr)
        print('Install with: pip install rasterio', file=sys.stderr)
        return

    print(f'Opening DEM {dem_path} ...', file=sys.stderr)
    with rasterio.open(dem_path) as src:
        transform = src.transform
        dem       = src.read(1).astype(np.float32)
        nodata    = src.nodata
        nrows, ncols = dem.shape

        if nodata is not None:
            dem[dem == nodata] = np.nan

        pix_lon = abs(float(transform.a))   # degrees per pixel (x)
        pix_lat = abs(float(transform.e))   # degrees per pixel (y)

        for peak in peaks:
            lon, lat = peak['lon'], peak['lat']
            ele      = peak['ele']
            r        = max(peak['isolation'], MINISO)

            # Peak elevation: prefer OSM tag, fall back to DEM value
            try:
                row0, col0 = [int(v) for v in rc(transform, lon, lat)]
            except Exception:
                continue
            if not (0 <= row0 < nrows and 0 <= col0 < ncols):
                continue
            if ele is None:
                v = float(dem[row0, col0])
                ele = v if not math.isnan(v) else None
            if ele is None:
                continue

            threshold = ele + MINDIFF
            m_lon, m_lat = metres_per_degree(lat)

            # Pixel radius covering the search circle
            px_lon = r / (pix_lon * m_lon) + 1
            px_lat = r / (pix_lat * m_lat) + 1
            pr     = int(max(px_lon, px_lat)) + 1

            r0 = max(0, row0 - pr);  r1 = min(nrows, row0 + pr + 1)
            c0 = max(0, col0 - pr);  c1 = min(ncols, col0 + pr + 1)

            sub = dem[r0:r1, c0:c1]
            if sub.size == 0:
                continue

            rows_g, cols_g = np.mgrid[r0:r1, c0:c1]

            # Vectorised distance computation (planar approx — matches isolation.c)
            dx = (cols_g - col0) * pix_lon * m_lon
            dy = (rows_g - row0) * pix_lat * m_lat
            dist = np.sqrt(dx * dx + dy * dy)

            # Pixels higher than threshold and within the search radius
            mask = (sub > threshold) & (dist > MINISO) & (dist < peak['isolation'])
            if not np.any(mask):
                continue

            min_dist = float(np.nanmin(dist[mask]))
            if min_dist < peak['isolation']:
                peak['isolation'] = min_dist


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--pbf',    required=True, help='Input OSM PBF file')
    parser.add_argument('--dem',    default=None,  help='DEM GeoTIFF (EPSG:4326, int16). '
                                                        'If omitted, only pass 1 runs.')
    parser.add_argument('--output', required=True, help='Output CSV path (osm_id,isolation)')
    parser.add_argument('--radius', type=float, default=100_000,
                        help='Maximum search radius in metres (default: 100000)')
    args = parser.parse_args()

    peaks = extract_peaks(args.pbf)
    if not peaks:
        print('No peaks found — check PBF path.', file=sys.stderr)
        sys.exit(1)

    # Initialise isolation to max radius
    for p in peaks:
        p['isolation'] = args.radius

    # Pass 1: sort by latitude (ascending) to enable early exit in the inner loop
    peaks.sort(key=lambda p: p['lat'])
    print('Running pass 1 (peak-to-peak) ...', file=sys.stderr)
    isolation_pass1(peaks, args.radius)

    p1_bounded = sum(1 for p in peaks if p['isolation'] < args.radius)
    print(f'  {p1_bounded}/{len(peaks)} peaks have a tighter bound after pass 1.',
          file=sys.stderr)

    # Pass 2: DEM scan (optional)
    if args.dem:
        print('Running pass 2 (DEM scan) ...', file=sys.stderr)
        isolation_pass2(peaks, args.dem)
    else:
        print('No --dem supplied — skipping pass 2.', file=sys.stderr)

    # Write CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['osm_id', 'isolation'])
        for p in peaks:
            w.writerow([p['id'], int(p['isolation'])])

    print(f'Wrote {len(peaks)} rows to {args.output}', file=sys.stderr)


if __name__ == '__main__':
    main()
