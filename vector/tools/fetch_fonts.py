#!/usr/bin/env python3
"""Download Roboto glyph PBFs from fonts.undpgeohub.org and vendor them locally.

Roboto is Apache 2.0 licensed; redistribution and self-hosting are permitted.
Ranges 0–1023 cover all Latin characters needed for British Isles map labels
(Basic Latin, Latin-1 Supplement, Latin Extended-A/B, IPA, diacritics).
"""
import os
import sys
import time
import urllib.request
import urllib.error

FONTS = ["Roboto Regular", "Roboto Italic", "Roboto Bold"]
BASE_URL = "https://fonts.undpgeohub.org/fonts"
# Ranges 0–1023 in steps of 256 (4 files per font covers all Latin scripts)
RANGES = [(start, start + 255) for start in range(0, 1024, 256)]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "maplibregljs", "fonts")


def fetch(url: str, dest: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def main():
    total = ok = 0
    for font in FONTS:
        font_dir = os.path.join(OUTPUT_DIR, font)
        os.makedirs(font_dir, exist_ok=True)
        for lo, hi in RANGES:
            filename = f"{lo}-{hi}.pbf"
            dest = os.path.join(font_dir, filename)
            if os.path.exists(dest):
                print(f"  skip  {font}/{filename} (exists)")
                ok += 1
                total += 1
                continue
            url = f"{BASE_URL}/{urllib.parse.quote(font)}/{filename}"
            print(f"  fetch {font}/{filename} ...", end=" ", flush=True)
            if fetch(url, dest):
                size = os.path.getsize(dest)
                print(f"{size // 1024} KB")
                ok += 1
            else:
                print("404 (skipped)")
            total += 1
            time.sleep(0.05)  # be polite

    print(f"\n{ok}/{total} ranges fetched to {os.path.abspath(OUTPUT_DIR)}")


import urllib.parse
if __name__ == "__main__":
    main()
