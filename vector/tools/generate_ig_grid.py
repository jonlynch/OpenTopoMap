#!/usr/bin/env python3
"""Generate Irish Grid (EPSG:29902) shapefiles for tilemaker ingestion.

Outputs four shapefiles into vector/data/ig-grid-4326/:
  ig_grid_lines_100km.shp  — 100 km grid lines (LineString, EPSG:4326)
  ig_grid_lines_10km.shp   — 10 km grid lines (not also 100 km)
  ig_grid_lines_1km.shp    — 1 km grid lines (not also 10/100 km)
  ig_grid_labels.shp       — 100 km square letter labels (Point, EPSG:4326)

All output is clipped to the Ireland zone (Republic + Northern Ireland) so there
is no overlap with the BNG grid. Run from anywhere — output path is resolved
relative to this script's location.

Requires: fiona, pyproj, shapely
"""

import math
import os

import fiona
from fiona.crs import CRS
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import unary_union

E_MIN, E_MAX = 0, 500000
N_MIN, N_MAX = 0, 500000
SEGMENT_M = 2000

_LETTERS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'

# Shared boundary polygon (WGS84) that separates Ireland from Great Britain.
# BNG lines use .difference(IRELAND_ZONE); IG lines use .intersection(IRELAND_ZONE).
# Vertices chosen so that:
#   Isle of Man  (-4.5°W, 54.1–54.4°N)  → east of boundary → GB
#   Mull of Kintyre (-5.78°W, 55.3°N)   → east of boundary → GB
#   Fair Head NI    (-6.07°W, 55.2°N)   → west of boundary → Ireland
#   Pembrokeshire   (-5.05°W, 52°N)     → east of boundary → GB
IRELAND_ZONE = Polygon([
    (-10.7, 51.0),
    (-5.5,  51.0),   # SE, Celtic Sea (west of Cornwall/Pembrokeshire)
    (-5.5,  53.5),   # E Irish Sea (west of Anglesey -4.3°W)
    (-5.3,  54.3),   # step east: captures Ards Peninsula (-5.43°W); IoM (-4.5°W) stays in GB
    (-5.3,  54.7),   # hold east: Donaghadee NI (-5.53°W) in Ireland; Portpatrick (-5.12°W) in GB
    (-5.9,  55.2),   # step west for North Channel: Kintyre (-5.78°W) in GB; Fair Head NI (-6.07°W) in Ireland
    (-5.9,  55.45),  # N limit: above Malin Head (55.37°N), below Islay (55.6°N)
    (-10.7, 55.45),  # NW
    (-10.7, 51.0),   # close
])


def _letter(E, N):
    """Single Irish Grid square letter for the 100 km square containing (E, N).

    Grid layout (N ascending = rows A→V, E ascending = cols left→right):
      A B C D E   ← N 400–500 km
      F G H J K
      L M N O P
      Q R S T U
      V W X Y Z   ← N 0–100 km
    """
    col = int(E // 100000)
    row = int(N // 100000)
    return _LETTERS[(4 - row) * 5 + col]


def _subdivide(x0, y0, x1, y1):
    """Yield (x, y) points subdivided every SEGMENT_M metres along the line."""
    dx, dy = x1 - x0, y1 - y0
    length = math.sqrt(dx * dx + dy * dy)
    n = max(1, int(length / SEGMENT_M))
    for i in range(n + 1):
        t = i / n
        yield x0 + t * dx, y0 + t * dy


def _to_wgs84(ig_pts, transformer):
    """Convert iterable of (E, N) Irish Grid points to [(lon, lat)] WGS84 list."""
    result = []
    for e, n in ig_pts:
        lon, lat = transformer.transform(e, n)
        result.append((lon, lat))
    return result


def _write_clipped_line(writer, coords, tier, lbl):
    """Clip a WGS84 LineString to IRELAND_ZONE and write surviving segments."""
    raw = LineString(coords)
    clipped = raw.intersection(IRELAND_ZONE)
    if clipped.is_empty:
        return 0
    geoms = (
        [clipped] if isinstance(clipped, LineString)
        else list(clipped.geoms) if isinstance(clipped, MultiLineString)
        else [g for g in clipped.geoms if isinstance(g, LineString)]
    )
    written = 0
    for geom in geoms:
        if geom.is_empty or len(geom.coords) < 2:
            continue
        writer.write({
            'geometry': {'type': 'LineString', 'coordinates': list(geom.coords)},
            'properties': {'tier': tier, 'label': lbl},
        })
        written += 1
    return written


def main():
    out_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ig-grid-4326')
    )
    os.makedirs(out_dir, exist_ok=True)

    transformer = Transformer.from_crs('EPSG:29902', 'EPSG:4326', always_xy=True)
    crs = CRS.from_epsg(4326)

    line_schema = {'geometry': 'LineString', 'properties': {'tier': 'str', 'label': 'str'}}
    label_schema = {'geometry': 'Point', 'properties': {'label': 'str'}}

    paths = {
        '100km': os.path.join(out_dir, 'ig_grid_lines_100km.shp'),
        '10km':  os.path.join(out_dir, 'ig_grid_lines_10km.shp'),
        '1km':   os.path.join(out_dir, 'ig_grid_lines_1km.shp'),
    }

    def tier_and_label_for(coord):
        if coord % 100000 == 0:
            return '100km', '00'
        if coord % 10000 == 0:
            km = (coord // 1000) % 100
            return '10km', str(km).zfill(2)
        km = (coord // 1000) % 100
        return '1km', str(km).zfill(2)

    counts = {'100km': 0, '10km': 0, '1km': 0}

    with fiona.open(paths['100km'], 'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f100, \
         fiona.open(paths['10km'],  'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f10, \
         fiona.open(paths['1km'],   'w', driver='ESRI Shapefile', schema=line_schema, crs=crs) as f1:

        writers = {'100km': f100, '10km': f10, '1km': f1}

        for e in range(E_MIN, E_MAX + 1, 1000):
            tier, lbl = tier_and_label_for(e)
            coords = _to_wgs84(_subdivide(e, N_MIN, e, N_MAX), transformer)
            counts[tier] += _write_clipped_line(writers[tier], coords, tier, lbl)

        for n in range(N_MIN, N_MAX + 1, 1000):
            tier, lbl = tier_and_label_for(n)
            coords = _to_wgs84(_subdivide(E_MIN, n, E_MAX, n), transformer)
            counts[tier] += _write_clipped_line(writers[tier], coords, tier, lbl)

    label_path = os.path.join(out_dir, 'ig_grid_labels.shp')
    label_count = 0
    with fiona.open(label_path, 'w', driver='ESRI Shapefile', schema=label_schema, crs=crs) as flbl:
        for e in range(E_MIN, E_MAX, 100000):
            for n in range(N_MIN, N_MAX, 100000):
                lon, lat = transformer.transform(e + 2000, n + 2000)
                if not IRELAND_ZONE.contains(Point(lon, lat)):
                    continue
                lbl = _letter(e, n)
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
