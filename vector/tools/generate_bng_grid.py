#!/usr/bin/env python3
"""Generate OSGB British National Grid shapefiles for tilemaker ingestion.

Outputs four shapefiles into vector/data/bng-grid-4326/:
  bng_grid_lines_100km.shp  — 100 km grid lines (LineString, EPSG:4326)
  bng_grid_lines_10km.shp   — 10 km grid lines (not also 100 km)
  bng_grid_lines_1km.shp    — 1 km grid lines (not also 10/100 km)
  bng_grid_labels.shp       — 100 km square letter-pair labels (Point, EPSG:4326)

Run from anywhere — output path is resolved relative to this script's location.
"""

import math
import os

import fiona
from fiona.crs import CRS
from pyproj import Transformer

E_MIN, E_MAX = 0, 700000
N_MIN, N_MAX = 0, 1300000
SEGMENT_M = 2000  # max segment length in OSGB36 metres before subdivision

_LETTERS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'


def _letters(E, N):
    """Two-letter BNG square code for the 100 km square containing (E, N)."""
    c5 = int(E // 500000)
    r5 = int(N // 500000)
    l1 = _LETTERS[(3 - r5) * 5 + (c5 + 2)]
    c1 = int((E % 500000) // 100000)
    r1 = 4 - int((N % 500000) // 100000)
    l2 = _LETTERS[r1 * 5 + c1]
    return l1 + l2


def _subdivide(x0, y0, x1, y1):
    """Yield (x, y) points subdivided every SEGMENT_M metres along the line."""
    dx, dy = x1 - x0, y1 - y0
    length = math.sqrt(dx * dx + dy * dy)
    n = max(1, int(length / SEGMENT_M))
    for i in range(n + 1):
        t = i / n
        yield x0 + t * dx, y0 + t * dy


def _to_wgs84(bng_pts, transformer):
    """Convert iterable of (E, N) BNG points to [(lon, lat)] WGS84 list."""
    result = []
    for e, n in bng_pts:
        lon, lat = transformer.transform(e, n)
        result.append((lon, lat))
    return result


def main():
    out_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'bng-grid-4326')
    )
    os.makedirs(out_dir, exist_ok=True)

    transformer = Transformer.from_crs('EPSG:27700', 'EPSG:4326', always_xy=True)
    crs = CRS.from_epsg(4326)

    line_schema = {'geometry': 'LineString', 'properties': {'tier': 'str', 'label': 'str'}}
    label_schema = {'geometry': 'Point', 'properties': {'label': 'str'}}

    paths = {
        '100km': os.path.join(out_dir, 'bng_grid_lines_100km.shp'),
        '10km':  os.path.join(out_dir, 'bng_grid_lines_10km.shp'),
        '1km':   os.path.join(out_dir, 'bng_grid_lines_1km.shp'),
    }

    def tier_and_label_for(coord, axis):
        if coord % 100000 == 0:
            return '100km', '00'
        if coord % 10000 == 0:
            km = (coord // 1000) % 100
            return '10km', str(km).zfill(2)
        km = (coord // 1000) % 100
        lbl = str(km).zfill(2) if axis == 'e' else str(km).zfill(2)
        return '1km', lbl

    counts = {'100km': 0, '10km': 0, '1km': 0}

    with fiona.open(paths['100km'], 'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f100, \
         fiona.open(paths['10km'],  'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f10, \
         fiona.open(paths['1km'],   'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f1:

        writers = {'100km': f100, '10km': f10, '1km': f1}

        # Vertical lines: constant easting, full N extent
        for e in range(E_MIN, E_MAX + 1, 1000):
            tier, lbl = tier_and_label_for(e, 'e')
            coords = _to_wgs84(_subdivide(e, N_MIN, e, N_MAX), transformer)
            writers[tier].write({
                'geometry': {'type': 'LineString', 'coordinates': coords},
                'properties': {'tier': tier, 'label': lbl},
            })
            counts[tier] += 1

        # Horizontal lines: constant northing, full E extent
        for n in range(N_MIN, N_MAX + 1, 1000):
            tier, lbl = tier_and_label_for(n, 'n')
            coords = _to_wgs84(_subdivide(E_MIN, n, E_MAX, n), transformer)
            writers[tier].write({
                'geometry': {'type': 'LineString', 'coordinates': coords},
                'properties': {'tier': tier, 'label': lbl},
            })
            counts[tier] += 1

    label_path = os.path.join(out_dir, 'bng_grid_labels.shp')
    label_count = 0
    with fiona.open(label_path, 'w', driver='ESRI Shapefile', schema=label_schema, crs=crs) as flbl:
        for e in range(E_MIN, E_MAX, 100000):
            for n in range(N_MIN, N_MAX, 100000):
                lbl = _letters(e, n)
                lon, lat = transformer.transform(e + 2000, n + 2000)
                flbl.write({
                    'geometry': {'type': 'Point', 'coordinates': (lon, lat)},
                    'properties': {'label': lbl},
                })
                label_count += 1

    print(f'Written to {out_dir}')
    print(f'  Lines 100km: {counts["100km"]:>5}')
    print(f'  Lines  10km: {counts["10km"]:>5}')
    print(f'  Lines   1km: {counts["1km"]:>5}')
    print(f'  Labels:      {label_count:>5}')


if __name__ == '__main__':
    main()
