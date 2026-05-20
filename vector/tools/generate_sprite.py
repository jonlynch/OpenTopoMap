#!/usr/bin/env python3
"""
Usage:
  python generate_sprite.py input_folder output_sprite.png --padding 0 --json atlas.json \\
      [--overrides-2x folder_of_2x_pngs]

Automatically determines column count to make the sheet roughly square.
Uses ImageMagick (convert, montage, identify) for the @1x sprite.

After building @1x, always generates @2x alongside it:
  - Without --overrides-2x: each icon is pixel-doubled (Pillow NEAREST, fast).
  - With --overrides-2x: builds a fresh @2x sprite from proper 2x sources —
    SVG-rendered PNGs from the overrides folder, falling back to 2x pixel-upscaled
    PNGs from input_folder for everything else. This gives crisp vector-quality
    icons on retina displays for any icon that has an SVG source.

JSON atlas format:
{
  "name_without_ext": {"x":0,"y":0,"width":W,"height":H,"pixelRatio":1},
  ...
}
"""
import json, os, shutil, subprocess, sys
from math import ceil
from pathlib import Path
import argparse


def run(cmd):
    subprocess.check_call(cmd, shell=True)


def list_pngs(folder):
    p = Path(folder)
    files = sorted([x for x in p.iterdir() if x.suffix.lower() == '.png'])
    if not files:
        raise SystemExit(f"No PNGs found in {folder}")
    return files


def get_size(path):
    out = subprocess.check_output(
        f'identify -format "%w %h" "{path}"', shell=True
    ).decode().strip()
    w, h = out.split()
    return int(w), int(h)


def choose_columns(sizes, padding):
    n = len(sizes)
    best = None
    for cols in range(1, n + 1):
        rows = ceil(n / cols)
        col_widths  = [0] * cols
        row_heights = [0] * rows
        for idx, (w, h) in enumerate(sizes):
            c = idx % cols
            r = idx // cols
            if w > col_widths[c]:  col_widths[c]  = w
            if h > row_heights[r]: row_heights[r] = h
        total_w = sum(col_widths)  + padding * (cols + 1)
        total_h = sum(row_heights) + padding * (rows + 1)
        score = total_w * total_h + abs(total_w - total_h)
        if best is None or score < best[0]:
            best = (score, cols, col_widths, row_heights)
    return best[1], best[2], best[3]


def build(input_folder, output_file, cols=None, padding=0, json_out=None):
    files = list_pngs(input_folder)
    tmp = Path(input_folder) / "_tmp_trim"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    originals = []
    trimmed   = []
    for i, f in enumerate(files):
        dest = tmp / f"f{i:04d}.png"
        run(f'convert "{f}" "{dest}"')
        originals.append(f.name)
        trimmed.append(dest)

    sizes = [get_size(str(p)) for p in trimmed]
    n     = len(trimmed)

    if cols is None:
        cols, col_widths, row_heights = choose_columns(sizes, padding)
    else:
        rows = ceil(n / cols)
        col_widths  = [0] * cols
        row_heights = [0] * rows
        for idx, (w, h) in enumerate(sizes):
            c = idx % cols; r = idx // cols
            col_widths[c]  = max(col_widths[c], w)
            row_heights[r] = max(row_heights[r], h)

    rows      = ceil(n / cols)
    file_list = " ".join(f'"{str(p)}"' for p in trimmed)
    geom      = f"+{padding}+{padding}"
    run(f'montage {file_list} -background none -gravity northwest '
        f'-geometry {geom} -tile {cols}x{rows} "{output_file}"')

    atlas = None
    if json_out:
        col_x, row_y = [], []
        x = 0
        for cw in col_widths:
            col_x.append(x + padding)
            x += cw + padding
        y = 0
        for rh in row_heights:
            row_y.append(y + padding)
            y += rh + padding

        atlas = {}
        for idx, trim_path in enumerate(trimmed):
            r = idx // cols; c = idx % cols
            w, h = sizes[idx]
            name = Path(originals[idx]).stem
            atlas[name] = {
                "x": col_x[c], "y": row_y[r],
                "width": w, "height": h,
                "pixelRatio": 1,
            }
        with open(json_out, "w") as jf:
            json.dump(atlas, jf, indent=2)

    shutil.rmtree(tmp)
    return atlas


def write_2x(output_file, atlas, json_out, input_folder=None, overrides_2x=None):
    """
    Generate @2x PNG and JSON alongside the @1x outputs.

    Without overrides_2x: pixel-doubles the @1x PNG with Pillow NEAREST (fast).
    With overrides_2x:    builds a fresh @2x sprite — SVG-rendered PNGs from
                          overrides_2x take priority; everything else is 2x
                          pixel-upscaled from input_folder.
    """
    from PIL import Image

    out_path = Path(output_file)
    x2_png   = out_path.with_name(out_path.stem + "@2x" + out_path.suffix)
    x2_json  = Path(json_out).with_name(
        Path(json_out).stem + "@2x" + Path(json_out).suffix
    )

    if overrides_2x and input_folder:
        # Build a real 2x source set and run montage on it
        tmp_2x = Path(input_folder) / "_tmp_2x"
        if tmp_2x.exists():
            shutil.rmtree(tmp_2x)
        tmp_2x.mkdir()

        # 1. Upscale all @1x sources 2x
        for f in list_pngs(input_folder):
            img = Image.open(str(f)).convert("RGBA")
            w, h = img.size
            img.resize((w * 2, h * 2), Image.NEAREST).save(str(tmp_2x / f.name))

        # 2. Override with high-res SVG-rendered versions
        for f in sorted(Path(overrides_2x).iterdir()):
            if f.suffix.lower() == '.png':
                shutil.copy(str(f), str(tmp_2x / f.name))
                print(f"  @2x override: {f.name}")

        # 3. Build the @2x sprite via montage (same layout logic as @1x)
        atlas_2x = build(str(tmp_2x), str(x2_png), json_out=str(x2_json))

        shutil.rmtree(tmp_2x)

        # Fix pixelRatio: build() always writes 1, update to 2
        for entry in atlas_2x.values():
            entry["pixelRatio"] = 2
        with open(str(x2_json), "w") as f:
            json.dump(atlas_2x, f, indent=2)

    else:
        # Simple pixel-double of the @1x sprite
        src = Image.open(output_file).convert("RGBA")
        w, h = src.size
        src.resize((w * 2, h * 2), Image.NEAREST).save(str(x2_png))

        x2_atlas = {
            name: {
                "x":          entry["x"] * 2,
                "y":          entry["y"] * 2,
                "width":      entry["width"] * 2,
                "height":     entry["height"] * 2,
                "pixelRatio": 2,
            }
            for name, entry in atlas.items()
        }
        with open(str(x2_json), "w") as f:
            json.dump(x2_atlas, f, indent=2)

    return x2_png, x2_json


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_folder")
    ap.add_argument("output_sprite")
    ap.add_argument("--cols",         type=int, default=None)
    ap.add_argument("--padding",      type=int, default=0)
    ap.add_argument("--json",         dest="json_out", default=None)
    ap.add_argument("--overrides-2x", dest="overrides_2x", default=None,
                    help="Folder of 2x-resolution PNG overrides (SVG-rendered icons). "
                         "Requires --json. Overrides take priority over pixel-upscaled fallbacks.")
    args = ap.parse_args()

    atlas = build(args.input_folder, args.output_sprite,
                  cols=args.cols, padding=args.padding, json_out=args.json_out)

    if atlas and args.json_out:
        x2_png, x2_json = write_2x(
            args.output_sprite, atlas, args.json_out,
            input_folder=args.input_folder,
            overrides_2x=args.overrides_2x,
        )
        print("Wrote", args.output_sprite, args.json_out)
        print("Wrote", x2_png, x2_json)
    else:
        print("Wrote", args.output_sprite, args.json_out or "")


if __name__ == "__main__":
    main()
