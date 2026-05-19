# Vector Rendering Parity with Raster

This document is a systematic audit of features present in the Mapnik raster pipeline
(`mapnik/styles-otm/`, `mapnik/symbols-otm/`) that are absent or incomplete in the vector
pipeline (`vector/tilemaker/process-otm.lua`, `vector/maplibregljs/otm_layers.json`).

Items are grouped by where the work sits: tile data (LUA), style (otm_layers.json), or both.
Each item is marked with an estimated complexity: **low** (a few lines), **medium** (a new
layer or sprite asset), or **high** (requires server-side pre-computation or significant
design work).

---

## Part 1 — Tile data pipeline gaps

These require changes to `process-otm.lua` before any style work can happen.

### ✓ 1.1 `archaeological_site` tag mismatch (bug) — low

**Done in `ec470a9`.**  Fixed: now uses `Find("site_type") == "tumulus"` instead of
`Find("archaeological_site") == "tumulus"`.

### ✓ 1.2 `man_made=mineshaft` / `man_made=adit` — low

**Done in `ec470a9`.**  Writes `type=mineshaft` at z13; sets `lifecycle=disused` when
`disused=yes` or `abandoned=yes`.

### ✓ 1.3 `historic=memorial` / `historic=monument` — low

**Done in `ec470a9`.**  Both map to `type=monument` at z14, excluding `memorial:type=stolperstein`.

### ✓ 1.4 `historic=wayside_shrine` — low

**Done in `ec470a9`.**  Matched alongside `wayside_cross`; reuses the same sprite icon.

### ✓ 1.5 `man_made=tower` (generic fallthrough) — low

**Done in `ec470a9`.**  Added after communication and observation tower checks; yields
`type=tower` at z13.

### ✓ 1.6 `power=generator` (non-wind, non-solar) — low

**Done in `ec470a9`.**  Writes `type=power_station` at z13, excluding
`generator:source=wind` and `generator:source=solar`.

### ✓ 1.7 Landcover: missing types in `process_land` — low/medium

**Done in `ec470a9`.**

| OSM tag | Action |
|---|---|
| `landuse=military` | Added to `process_land` (z9) and `process_sites` (z9) |
| `leisure=nature_reserve` | Added to `process_sites` (z8) |
| `natural=tidalflat` | Added to `process_land` (z11) |
| `wetland=reedbed` | Added to `process_land` (z11) |
| `landuse=hop_garden` | Added to `process_land` (z13) as `hop_garden` |

### ✓ 1.8 `leaf_type` attribute on forest polygons — low

**Done in `ec470a9`.**  `Attribute("leaf_type", leaf_type)` now written on forest land features.

### ✓ 1.9 Saddle `direction` attribute — low

**Done in `ec470a9`.**  `direction` tag read from `Find("direction")` and stored on saddle POIs.

### ✓ 1.10 Chapel distinction — low

**Done in `ec470a9`.**  Chapel block added before the church check, matching
`building=chapel/wayside_chapel` or `historic=wayside_chapel`; yields `type=chapel` at z14.

### ✓ 1.11 Peak isolation/density filtering — high

**Done in `6cd0499`, `4210610`, `37e710b`.**  `compute_isolation.py` (Python port of
`isolation.c`) computes per-peak isolation from OSM PBF + optional DEM GeoTIFF and writes
a CSV that `process-otm.lua` loads at init time.  Peak minzoom is set proportionally to
isolation: well-separated peaks appear from z8; dense clusters defer to z12.

### 1.12 `natural=tree_row` — medium *(new, not yet implemented)*

**Raster:** `barriers.xml:33` renders a `LinePatternSymbolizer` using `tree_row.png` for
`natural=tree_row` WAYs longer than 300m (and all tree rows at higher zoom).
**Vector:** not in `process-otm.lua` at all; tree rows are dropped silently.

Needs: a new branch in `process_barriers` (or a new call in `node_way_relation`) writing to
a line layer, plus `tree_row.png` added to the vector sprite.

### 1.13 Aerialway station nodes — medium *(new, not yet implemented)*

**Raster:** `aerialways.xml` renders gondola/cabin icons (`aerialway.png`,
`aerialway_gondola.png`, `aerialway_goods.png`) at node positions along cable car lines.
**Vector:** `process_aerialways()` only processes WAYs (the lines); aerialway nodes are
ignored entirely.

---

## Part 2 — Style layer gaps

These require changes to `otm_layers.json` (and in most cases, confirming sprite assets exist
in `otm_sprite`).

### ✓ 2.1 Peak and saddle elevation labels — low

**Done in `61acbb6` (initial), `58725bf` (integer fix).**  `poi-texts` uses
`["to-string", ["round", ["to-number", ["get","ele"], 0]]]` to display elevation below the
name for peaks, volcanoes, summit crosses, and saddles.

### ✓ 2.2 Landcover fill patterns — medium

**Done in `8df4b89`, `da917d9` (scree).**  `landcover-pattern` and `forest-pattern` layers
added, with all raster-matched sprite assets:
`fell`, `scrub`, `meadow`/`grass`/`grassland`, `vineyard`, `orchard`, `bare_rock`, `scree`,
`quarry`, `allotments`, `hop_garden`, `sand`/`beach`, `military`, `tidalflat`, `bog`,
`string_bog`, `swamp`, `wet_meadow`, `marsh`, `wetland`, `reedbed`,
`forest`, `forest-coniferous`, `forest-deciduous` (via `["case"]` on `leaf_type`).
Forest edge line pattern (`forest-outline`) added as a separate `forest-edge` layer at z14.

### ✓ 2.3 Missing POI symbol layers — medium

**Done in `8df4b89` and sprite rebuilds.**  All the following are now in the sprite and
rendered via the existing `poi-symbols` `coalesce` layer:
`monument`, `tower`, `chapel`, `mineshaft`, `mineshaft_disused`, `power_station`, `spring`,
`shelter`, `hospital`.

Remaining icons that have no source artwork in `mapnik/symbols-otm/`:
`drinking_water`, `fuel`, `pharmacy`, `information` — these would need new icons designed
from scratch.

### 2.4 Viewpoint directional symbols — high *(deferred)*

**Raster:** `symbols-viewpoint.xml` selects from seven sector-arc SVGs and rotates them
using PostGIS-computed `firstrotation`/`secondrotation` columns.
**Vector:** viewpoint renders as a generic icon with no direction or arc.

Requires: reading and parsing `direction` tag in Lua, interpreting numeric/range/compass
notation, separate sprite icons per arc width (already in `mapnik/symbols-otm/`), and
`icon-rotate` in the style.  Worth doing as standalone work.

### ✓ 2.5 Nature reserve and military area boundaries — medium

**Done in `ec470a9` (tile data) + `d086bf7` (style).**  `nature-reserve` line layer
(green stroke, 5px, 0.5 opacity) and `military-border` line layer added to `otm_layers.json`.

### ✓ 2.6 Intermittent waterway styling — low

**Done in `61acbb6`.**  `water_lines` layer uses:
```json
"line-dasharray": ["case", ["boolean", ["get","intermittent"], false],
    ["literal",[4,4]], ["literal",[1,0]]]
```

### 2.7 Sport pitch overlays — low *(not yet implemented)*

**Raster:** `symbols-sport.xml` renders pitch markings (football, rugby, basketball, tennis,
athletics) over `leisure=pitch` polygons from z16.
**Vector:** pitches are a flat fill; no markings.

Needs: `sport` attribute written in `process_land` for pitches, then a symbol layer using
the existing SVG assets in `mapnik/symbols-otm/`.

### ✓ 2.8 Saddle directional symbol — medium

**Done in `2f0bfa1` (sprite) + `d086bf7` (style).**  `icon-rotate: ["to-number",
["get","direction"], 0]` applied to saddle icons; `direction` attribute stored in tile data
(§1.9).  Note: only simple numeric `direction` values rotate correctly; range notation
(`45-135`) is not parsed.

### ✓ 2.9 Glacier styling — low

**Done in `61acbb6`.**  Separate `glaciers` fill layer added (`#d0f8ff`, opacity 0.5),
with the main `water-poly` layer filtered to `["!=", ["get","type"], "glacier"]`.

### ✓ 2.10 Oneway arrows on roads — medium

**Done in `8df4b89`.**  `oneway-arrows` symbol layer added at z14+, using
`symbol-placement: line` and `symbol-spacing: 100`.

---

## Part 3 — Audit methodology

### 3.1 Per Mapnik style file checklist

- [x] `aerialways.xml` — aerialway lines ✓ (station nodes: §1.13)
- [x] `areas.xml` — military, nature reserve: implemented (§1.7, §2.5) ✓
- [x] `barriers.xml` — walls, fences, hedges ✓ (tree rows: §1.12)
- [x] `basemap-relief.xml` — hillshade ✓
- [x] `basemap-sea.xml` — ocean ✓
- [x] `borders.xml` — boundaries ✓
- [x] `bridges-*.xml` — bridge rendering ✓
- [x] `buildings.xml` — buildings ✓
- [x] `cliffs.xml` — cliff teeth ✓
- [x] `contours.xml` — contours (client-side) ✓
- [x] `ferry-routes.xml` — ferries ✓
- [x] `glaciers.xml` — distinct fill implemented (§2.9) ✓
- [x] `hillshade.xml` — hillshade ✓
- [x] `housenumbers-*.xml` — addresses ✓
- [x] `landuse-*.xml` — patterns implemented (§2.2) ✓
- [x] `powerlines.xml` — power lines ✓
- [x] `powertowers.xml` — power towers ✓
- [x] `railways-*.xml` — railways ✓
- [x] `roads-*.xml` — roads ✓
- [x] `symbols-1.xml` — castle, church, chapel (§1.10) ✓
- [x] `symbols-2.xml` — towers, springs, etc.: all gaps fixed (§1.2–1.6) ✓
- [x] `symbols-peaks.xml` — isolation filtering implemented (§1.11) ✓
- [x] `symbols-saddle.xml` — direction + ele implemented (§1.9, §2.1, §2.8) ✓
- [ ] `symbols-sport.xml` — sport pitches: not yet implemented (§2.7)
- [ ] `symbols-viewpoint.xml` — directional arc deferred (§2.4)
- [x] `text-peaks.xml` — elevation labels implemented (§2.1) ✓
- [x] `tunnels-*.xml` — tunnels ✓
- [x] `water-*.xml` — water areas ✓
- [x] `waterway-lines*.xml` — rivers/streams ✓
- [x] `waterway-arrows.xml` — intermittent styling implemented (§2.6) ✓

### 3.2 Unrepresented Mapnik icon assets

**Zoom-variant switching** — Mapnik uses smaller icons at lower zoom (e.g. `church_z13.png`
vs `church.png`). Vector uses a single icon per type. Not a functional gap; 19 PNG variants
intentionally not mirrored.

**Raster-only overlays** — `forest_2.png`, `forest-coniferous_2.png`, `forest-deciduous_2.png`
are drawn at 0.1 opacity on top of hillshade in the raster pipeline. Not applicable to vector.

**Missing functional icons** — `tree_row.png` (§1.12), `aerialway.png` /
`aerialway_gondola.png` / `aerialway_goods.png` (§1.13).

**No source artwork** — `drinking_water`, `fuel`, `pharmacy`, `information` have no
equivalent in `mapnik/symbols-otm/`; new icons would need to be created.

### 3.3 Zoom level calibration

| OTM zoom | Scale denominator (approx) |
|---|---|
| z12 | 1:250,000 |
| z13 | 1:125,000 |
| z14 | 1:70,000 |
| z15 | 1:35,000 |
| z16 | 1:17,500 |

---

## Part 4 — Features that cannot be directly replicated

### 4.1 Peak isolation (`otm_isolation`)

**Partially mitigated.**  `compute_isolation.py` replicates `isolation.c` in Python and
produces a CSV loaded by Tilemaker at run time.  DEM-based refinement (pass 2) is also
supported via `--dem` flag.

### 4.2 Viewpoint arc angles

Computed by PostGIS from `direction` tag strings.  Tracked as §2.4 (deferred).

### 4.3 Saddle direction normalisation

Partially implemented (§2.8).  Numeric `direction` values rotate correctly; compass words
and range notation are not yet normalised.

---

## Summary

### Completed

| Item | Section | Done in |
|---|---|---|
| `archaeological_site` tag bug | §1.1 | `ec470a9` |
| mineshaft/adit tile data | §1.2 | `ec470a9` |
| memorial/monument tile data | §1.3 | `ec470a9` |
| wayside_shrine tile data | §1.4 | `ec470a9` |
| generic tower tile data | §1.5 | `ec470a9` |
| power=generator tile data | §1.6 | `ec470a9` |
| military, tidalflat, reedbed, hop_garden, nature_reserve | §1.7 | `ec470a9` |
| leaf_type on forest | §1.8 | `ec470a9` |
| saddle direction attribute | §1.9 | `ec470a9` |
| chapel distinction | §1.10 | `ec470a9` |
| peak isolation filtering | §1.11 | `6cd0499`–`4210610` |
| peak/saddle elevation labels | §2.1 | `61acbb6`, `58725bf` |
| landcover fill patterns (incl. scree) | §2.2 | `8df4b89`, `da917d9` |
| POI sprite assets (monument, tower, chapel, etc.) | §2.3 | `8df4b89` |
| nature reserve + military borders | §2.5 | `ec470a9`, `d086bf7` |
| intermittent waterway dashes | §2.6 | `61acbb6` |
| saddle direction rotation | §2.8 | `2f0bfa1`, `d086bf7` |
| glacier distinct fill | §2.9 | `61acbb6` |
| oneway arrows | §2.10 | `8df4b89` |

### Remaining

| Item | Section | Complexity |
|---|---|---|
| `natural=tree_row` line pattern | §1.12 | medium |
| Aerialway station nodes | §1.13 | medium |
| Sport pitch overlays | §2.7 | low |
| Viewpoint directional arc | §2.4 | high |
