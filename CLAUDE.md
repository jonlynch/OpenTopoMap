# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

OpenTopoMap is a topographic map generated from OpenStreetMap and SRTM elevation data. It produces raster tiles (Mapnik, legacy), vector tiles (Tilemaker, current), and Garmin GPS maps (mkgmap). The web frontend at opentopomap.org consumes the vector tiles.

## Build and development commands

### Web frontend (www/v2/)

```bash
cd www/v2
npm install          # install dependencies
npm start            # dev server with live reload on port 9000
npm run build        # production build to dist/
```

### Vector tile generation (vector/)

Vector tiles are produced with [Tilemaker](https://github.com/shortbread-tiles/shortbread-tilemaker):

All commands below must be run from the `vector/` directory.

**Step 1 — Renumber the OSM extract** (must be done whenever the extract is updated):

```bash
cd vector
osmium renumber osm/region-latest.osm.pbf -o osm/region-renumbered.osm.pbf -O
```

**Step 2 — Regenerate peak isolation CSV** (must be re-run after every renumber):

```bash
python3 tools/compute_isolation.py \
    --pbf osm/region-renumbered.osm.pbf \
    --output data/peak_isolation.csv
```

> The CSV contains renumbered node IDs. The tilemaker build must consume the **same renumbered
> PBF**; using the original extract causes all isolation lookups to miss silently, degrading
> every peak to elevation-only zoom ordering.

**Step 2.5 — Regenerate saddle direction CSV** (must be re-run after every renumber):

```bash
python3 tools/compute_saddle_directions.py \
    --pbf osm/region-renumbered.osm.pbf \
    --output data/saddle_directions.csv
```

> The CSV contains renumbered node IDs. The tilemaker build must consume the **same renumbered
> PBF**. Internet access and `pip install pmtiles Pillow` are required — the default DEM source
> is `https://pbcc.blob.core.windows.net/pbcc-pmtiles/DTM.pmtiles` (global z0–z13 PMTiles).
> The tile cache lives under `vector/data/dem_cache/` (clear it to force a refetch). If no
> saddles fall inside DEM coverage the script writes an empty CSV with just the header row.

**Step 3 — Generate BNG and Irish Grid shapefiles** (one-off; re-run if absent or boundary changes):

```bash
python3 tools/generate_bng_grid.py
python3 tools/generate_ig_grid.py
```

Both scripts require `shapely` (`pip install shapely`). The two grids share a common Irish Sea boundary polygon so there is no overlap: BNG covers Great Britain (including the Isle of Man) and IG covers Ireland (Republic + Northern Ireland). Output directories are `data/bng-grid-4326/` and `data/ig-grid-4326/` respectively. Irish Grid square labels use the single-letter format (e.g. `L`), matching the `L1234567890` reference convention.

**Step 4 — Build vector tiles**:

```bash
tilemaker --config tilemaker/tilemaker-config-otm.json \
          --process tilemaker/process-otm.lua \
          --input osm/region-renumbered.osm.pbf \
          --output tiles/region.mbtiles \
          --threads 1
```

> **Memory**: `--threads 1` avoids OOM kills on systems with limited swap. Multi-threaded builds
> spike memory in the final write phase as each thread holds its own copy of the shapefile index.

**Other tools**:

```bash
# Generate sprite sheets (produces @1x and @2x PNG + JSON)
python3 tools/generate_sprite.py \
    maplibregljs/otm_symbols \
    maplibregljs/otm_sprite.png \
    --json maplibregljs/otm_sprite.json \
    --overrides-2x maplibregljs/otm_symbols_2x
```

To add a new icon:
1. Drop a PNG into `vector/maplibregljs/otm_symbols/` (name must match the `type` attribute value in tiles)
2. If the icon has an SVG source, render it at 2× into `vector/maplibregljs/otm_symbols_2x/` with `cairosvg <file.svg> -o otm_symbols_2x/<name>.png --scale 2`
3. Re-run the sprite generation command above

### Raster tile rendering (mapnik/, legacy)

The raster pipeline requires PostgreSQL/PostGIS with osm2pgsql imports, plus DEM-derived hillshade and contour GeoTIFFs generated via GDAL. The main style is `mapnik/opentopomap.xml`. Render via renderd (mod_tile) or:

```bash
python3 mapnik/mapnik_render_tile.py
```

### Garmin maps (garmin/)

Uses mkgmap + splitter Java tools. See `garmin/README.md` for the full pipeline script.

## Architecture

### Four largely independent subsystems

1. **vector/** — Tilemaker-based vector tile generation, this is the active rendering pipeline. `tilemaker/tilemaker-config-otm.json` defines layers (streets at low/med/high zoom, water polygons, land use, POIs, boundaries, buildings, BNG grid, etc.) with per-layer zoom ranges and simplify thresholds. `tilemaker/process-otm.lua` (~1450 lines) is the OSM data processing script that classifies features, assigns zoom levels, and sets vector tile attributes. It is a modified Shortbread schema. The OSGB British National Grid is baked into the tiles as two source-layers — `bng_lines` (LineString, tiers 100km/10km/1km) and `bng_labels` (Point, 100km square letter pairs) — generated from shapefiles in `data/bng-grid-4326/` by `tools/generate_bng_grid.py` (requires `pyproj`, `fiona`).

2. **mapnik/** — Legacy raster tile renderer. ~70 XML style files in `styles-otm/` define rendering rules for Mapnik. The C tools (`tools/saddledirection.c`, `tools/isolation.c`) compute saddle directions and peak isolation from raster DEMs. SQL scripts populate auxiliary PostGIS columns. `osm2pgsql/` contains the import styles. Setup guides cover Ubuntu 16.04/18.04; this subsystem is being phased out in favour of vector tiles.

3. **www/v2/** — Current web frontend. Webpack 5 bundles a Leaflet-based SPA. Key modules in `src/`:
   - `otm-layers.js` — tile layer definitions (OTM, OSM base layers; Lonvia hiking/cycling routes; QTH graticule)
   - `otm-search.js` — location search via Leaflet Geosearch
   - `otm-track.js` — GPX/KML/GeoJSON file loading
   - `otm-elevation.js` — elevation profile via leaflet-elevation
   - `otm-ui-*.js` — UI controls, info dropdown, language picker, messages
   - `otm-marker.js`, `otm-locate.js` — marker placement and geolocation
   - `otm-load-localization.js` — dynamic language loading (en, de, fr, it, es)
   - `otm-context.js` — global context object for shared state

   Localization JSON files live in `www/v2/localization/`. Language-specific link URLs (about, imprint, credits, Garmin) are in each language file. `www/v1/` is the older static HTML frontend.

4. **garmin/** — mkgmap-based Garmin .img generation from OSM extracts. Contains style rules (`style/opentopomap/`, `style/contours/`), TYP files for visual styling, and shell scripts for downloading bounds/sea data and driving the build.

### Data flow

OSM planet/region extract (.osm.pbf) → [osm2pgsql for raster OR Tilemaker for vector] → tiles served to web frontend. SRTM elevation data (HGT) → GDAL processing (merge, reproject, hillshade, colour relief, contours) → GeoTIFFs consumed by Mapnik styles or served as DEM COGs for the vector frontend.

## Key technical details

- Tilemaker's `write_to` field in the config merges multiple zoom-range layers into a single output layer (e.g. `streets_low`, `streets_med`, `streets` all write to the `streets` layer)
- Vector tile layers and attributes use `type` not `kind` (renamed in commit b165f58)
- The vector tile LUA script implements zoom-by-area and zoom-by-length calculations to dynamically assign minzoom based on feature size
- The web frontend expects a `lang.json` listing available languages and a default fallback; each language has its own JSON file
- Saddle direction and peak isolation computations rely on raw DEM GeoTIFFs (`raw.tif`) being available
- `data/peak_isolation.csv` is generated from a **renumbered** PBF; the tilemaker build must use the same renumbered PBF or all isolation lookups will silently miss (peaks fall back to elevation-only zoom ordering)
- The root `package-lock.json` is an empty placeholder — the real npm project is `www/v2/`
