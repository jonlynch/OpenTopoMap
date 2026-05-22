#!/usr/bin/env bash
#
# rebuild.sh — download an OSM PBF extract, renumber, regenerate lookup CSVs,
#              rebuild vector tiles, and restart the tile server.
#
# Usage:
#   ./rebuild.sh <pbf-url> [--skip-download] [--dev] [--no-server-restart]
#
# By default produces PMTiles (suitable for static / CDN serving).
# Pass --dev to produce MBTiles and restart the local tilemaker-server instead.
#
# Examples:
#   ./rebuild.sh https://download.geofabrik.de/europe/united-kingdom/england/cumbria-latest.osm.pbf
#   ./rebuild.sh https://download.geofabrik.de/europe/great-britain-latest.osm.pbf --dev
#
# Requirements:
#   osmium, tilemaker, python3 (pmtiles, Pillow, numpy),
#   /home/jonlynch/tilemaker/build/tilemaker-server
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SERVER_BIN="${TILEMAKER_SERVER:-/home/jonlynch/tilemaker/build/tilemaker-server}"
SERVER_PORT="${TILEMAKER_SERVER_PORT:-8080}"
SKIP_DOWNLOAD=false
DEV_MODE=false
RESTART_SERVER=false

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
URL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-download)     SKIP_DOWNLOAD=true; shift ;;
        --dev)               DEV_MODE=true; RESTART_SERVER=true; shift ;;
        --no-server-restart) RESTART_SERVER=false; shift ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *)  URL="$1"; shift ;;
    esac
done

if [[ -z "$URL" ]]; then
    echo "Usage: $0 <pbf-url> [--skip-download] [--dev] [--no-server-restart]" >&2
    exit 1
fi

# Derive filename and region name from URL
PBF_FILE="osm/$(basename "$URL")"
REGION_NAME="$(basename "$PBF_FILE" .osm.pbf)"
RENUMBERED="osm/${REGION_NAME}-renumbered.osm.pbf"

# ---------------------------------------------------------------------------
# Step 1: Download
# ---------------------------------------------------------------------------
if $SKIP_DOWNLOAD && [[ -f "$PBF_FILE" ]]; then
    echo "=== Skipping download ($PBF_FILE exists) ==="
else
    echo "=== Downloading $URL → $PBF_FILE ==="
    mkdir -p osm
    curl -L -o "$PBF_FILE" "$URL"
    echo "Download complete."
fi

# ---------------------------------------------------------------------------
# Step 2: Renumber
# ---------------------------------------------------------------------------
echo "=== Renumbering $PBF_FILE → $RENUMBERED ==="
osmium renumber "$PBF_FILE" -o "$RENUMBERED" -O
echo "Renumber complete."

# ---------------------------------------------------------------------------
# Step 3: Regenerate lookup CSVs
# ---------------------------------------------------------------------------
echo "=== Regenerating peak isolation CSV ==="
python3 tools/compute_isolation.py \
    --pbf "$RENUMBERED" \
    --output data/peak_isolation.csv

echo "=== Regenerating saddle direction CSV ==="
python3 tools/compute_saddle_directions.py \
    --pbf "$RENUMBERED" \
    --output data/saddle_directions.csv

# ---------------------------------------------------------------------------
# Step 4: Build vector tiles
# ---------------------------------------------------------------------------
if $DEV_MODE; then
    OUTPUT="tiles/${REGION_NAME}.mbtiles"
else
    OUTPUT="tiles/${REGION_NAME}.pmtiles"
fi
echo "=== Building tiles → $OUTPUT ==="
tilemaker \
    --config tilemaker/tilemaker-config-otm.json \
    --process tilemaker/process-otm.lua \
    --input "$RENUMBERED" \
    --output "$OUTPUT" \
    --compact \
    --threads 1
echo "Build complete."

# ---------------------------------------------------------------------------
# Step 5: Restart tile server
# ---------------------------------------------------------------------------
if $RESTART_SERVER; then
    echo "=== Restarting tile server ==="
    # Kill any existing server on the port
    kill "$(lsof -ti:"$SERVER_PORT")" 2>/dev/null || true
    sleep 1

    # Determine which mbtiles to serve — prefer the one we just built
    MBTILES_TO_SERVE="$OUTPUT"
    if [[ ! -f "$MBTILES_TO_SERVE" ]]; then
        MBTILES_TO_SERVE="$(ls tiles/*.mbtiles 2>/dev/null | head -1)"
    fi

    if [[ -z "$MBTILES_TO_SERVE" ]]; then
        echo "No mbtiles found to serve." >&2
        exit 1
    fi

    "$SERVER_BIN" "$MBTILES_TO_SERVE" --port "$SERVER_PORT" &>/dev/null &
    echo "Server started (PID $!) serving $MBTILES_TO_SERVE on port $SERVER_PORT"
else
    echo "=== Skipping server restart ==="
fi

echo "=== Done ==="
