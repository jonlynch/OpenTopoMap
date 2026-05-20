#!/usr/bin/env python3
"""Generate terrain/coastal pattern sprites (tidalflat, sand, beach, dune)
for the OpenTopoMap vector tile MapLibre style.

Draws natively at 1x and 2x — no NEAREST upscaling.
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT_1X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols")
OUT_2X = Path("/home/jonlynch/OpenTopoMap/vector/maplibregljs/otm_symbols_2x")


def new_canvas(size, bg):
    """Return a fresh RGBA canvas filled with `bg` (an (r,g,b,a) tuple)."""
    img = Image.new("RGBA", (size, size), bg)
    return img


def save(img, directory, name):
    path = directory / name
    img.save(path, "PNG")
    print(f"saved {path}")


def draw_tidalflat(scale):
    size = 20 * scale
    img = new_canvas(size, (182, 206, 222, 120))
    draw = ImageDraw.Draw(img)
    line_colour = (60, 100, 160, 140)
    if scale == 1:
        ys = [4, 9, 14, 19]
    else:
        ys = [8, 18, 28, 38]
    for y in ys:
        draw.line([(0, y), (size - 1, y)], fill=line_colour, width=1)
    return img


def draw_sand(scale):
    size = 20 * scale
    img = new_canvas(size, (255, 244, 152, 255))
    draw = ImageDraw.Draw(img)
    dot_colour = (168, 135, 44, 185)
    rows_1x = [
        ([2, 7, 12, 17], 3),
        ([4, 9, 14, 19], 8),
        ([2, 7, 12, 17], 13),
        ([4, 9, 14], 18),
    ]
    if scale == 1:
        radius = 1
        rows = rows_1x
    else:
        radius = 2
        rows = [([x * 2 for x in xs], y * 2) for xs, y in rows_1x]
    for xs, y in rows:
        for x in xs:
            draw.ellipse(
                [(x - radius, y - radius), (x + radius, y + radius)],
                fill=dot_colour,
            )
    return img


def draw_beach(scale):
    size = 20 * scale
    img = new_canvas(size, (255, 224, 102, 255))
    draw = ImageDraw.Draw(img)
    arc_colour = (148, 110, 32, 215)
    positions_1x = [(5, 5), (14, 5), (2, 12), (10, 12), (18, 12), (6, 18), (15, 18)]
    if scale == 1:
        positions = positions_1x
        dx, dy = 3, 2
    else:
        positions = [(x * 2, y * 2) for x, y in positions_1x]
        dx, dy = 6, 4
    for cx, cy in positions:
        bbox = [(cx - dx, cy - dy), (cx + dx, cy + dy)]
        draw.arc(bbox, start=200, end=340, fill=arc_colour, width=1)
    return img


def draw_dune(scale):
    size = 20 * scale
    img = new_canvas(size, (255, 244, 152, 255))
    draw = ImageDraw.Draw(img)
    arc_colour = (135, 95, 26, 230)
    positions_1x = [(5, 5), (15, 5), (5, 14), (15, 14)]
    if scale == 1:
        positions = positions_1x
        dx, dy = 4, 3
        width = 2
    else:
        positions = [(x * 2, y * 2) for x, y in positions_1x]
        dx, dy = 8, 6
        width = 3
    for cx, cy in positions:
        bbox = [(cx - dx, cy - dy), (cx + dx, cy + dy)]
        draw.arc(bbox, start=195, end=345, fill=arc_colour, width=width)
    return img


def main():
    OUT_1X.mkdir(parents=True, exist_ok=True)
    OUT_2X.mkdir(parents=True, exist_ok=True)

    sprites = {
        "tidalflat.png": draw_tidalflat,
        "sand.png": draw_sand,
        "beach.png": draw_beach,
        "dune.png": draw_dune,
    }

    for name, fn in sprites.items():
        save(fn(1), OUT_1X, name)
        save(fn(2), OUT_2X, name)


if __name__ == "__main__":
    main()
