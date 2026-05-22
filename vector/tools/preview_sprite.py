#!/usr/bin/env python3
"""
Preview a sprite PNG as a tiled pattern.

Usage:
    python3 tools/preview_sprite.py <sprite.png> [output.png]

Output (saved to file — no display required):
  Top-left   : raw sprite pixels magnified 6×
  Top-right  : 4×4 tile repeat showing the seamless pattern
  Bottom row : R / G / B / A channels separately (also magnified)
"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


def tile(arr, nx=4, ny=4):
    """Repeat arr nx times horizontally, ny times vertically."""
    return np.tile(arr, (ny, nx, 1))


def channel_image(arr, ch, colour):
    """Return an RGBA image highlighting one channel in the given colour."""
    h, w = arr.shape[:2]
    out = np.zeros((h, w, 4), dtype=np.uint8)
    r, g, b = [int(c * 255) for c in mcolors.to_rgb(colour)]
    v = arr[:, :, ch]
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = v  # use channel value as alpha
    # Composite over white so it's legible
    white = np.ones((h, w, 4), dtype=np.uint8) * 255
    alpha = out[:, :, 3:4].astype(float) / 255
    comp = (out[:, :, :3].astype(float) * alpha +
            white[:, :, :3].astype(float) * (1 - alpha)).astype(np.uint8)
    result = np.dstack([comp, np.full((h, w), 255, dtype=np.uint8)])
    return result


def composite_over_checker(arr, sq=8):
    """Composite RGBA arr over a grey/white checkerboard."""
    h, w = arr.shape[:2]
    checker = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            light = ((x // sq) + (y // sq)) % 2 == 0
            checker[y, x] = 220 if light else 180
    alpha = arr[:, :, 3:4].astype(float) / 255
    rgb = arr[:, :, :3].astype(float)
    comp = (rgb * alpha + checker.astype(float) * (1 - alpha)).astype(np.uint8)
    return comp


def magnify(arr, scale):
    img = Image.fromarray(arr)
    w, h = img.size
    return np.array(img.resize((w * scale, h * scale), Image.NEAREST))


def main():
    if len(sys.argv) < 2:
        print("Usage: preview_sprite.py <sprite.png> [output.png]")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".png", "_preview.png")

    img = Image.open(src).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]

    MAG = max(1, 288 // max(h, w))   # magnify so raw sprite is ~288px wide

    raw_comp   = composite_over_checker(arr)
    raw_mag    = magnify(raw_comp, MAG)

    tiled_arr  = tile(arr, 4, 4)
    tiled_comp = composite_over_checker(tiled_arr)

    ch_r = channel_image(arr, 0, "#e05050")[:, :, :3]
    ch_g = channel_image(arr, 1, "#50b050")[:, :, :3]
    ch_b = channel_image(arr, 2, "#5080e0")[:, :, :3]
    ch_a = magnify(
        np.dstack([arr[:, :, 3]] * 3).astype(np.uint8), MAG)

    ch_r_m = magnify(ch_r, MAG)
    ch_g_m = magnify(ch_g, MAG)
    ch_b_m = magnify(ch_b, MAG)

    fig = plt.figure(figsize=(14, 8), facecolor="#1a1a1a")
    fig.suptitle(src, color="white", fontsize=10)

    axes_spec = [
        (0.02, 0.35, 0.25, 0.60, "Sprite (×{})".format(MAG)),
        (0.30, 0.35, 0.65, 0.60, "4×4 tile repeat"),
        (0.02, 0.02, 0.22, 0.28, "R channel"),
        (0.26, 0.02, 0.22, 0.28, "G channel"),
        (0.50, 0.02, 0.22, 0.28, "B channel"),
        (0.74, 0.02, 0.22, 0.28, "Alpha"),
    ]
    images = [raw_mag, tiled_comp, ch_r_m, ch_g_m, ch_b_m, ch_a]

    for (left, bottom, width, height, title), im in zip(axes_spec, images):
        ax = fig.add_axes([left, bottom, width, height])
        ax.imshow(im)
        ax.set_title(title, color="white", fontsize=8)
        ax.axis("off")

    # Stats box
    non_transp = arr[arr[:, :, 3] > 10]
    stat_lines = [
        f"Size: {w}×{h}",
        f"Visible px: {len(non_transp)} / {w*h}",
        f"Min alpha: {arr[:,:,3].min()}",
        f"Max alpha: {arr[:,:,3].max()}",
    ]
    if len(non_transp):
        stat_lines += [
            f"R range: {non_transp[:,0].min()}–{non_transp[:,0].max()}",
            f"G range: {non_transp[:,1].min()}–{non_transp[:,1].max()}",
            f"B range: {non_transp[:,2].min()}–{non_transp[:,2].max()}",
        ]
    fig.text(0.78, 0.65, "\n".join(stat_lines),
             color="white", fontsize=7.5, family="monospace",
             va="top", ha="left")

    fig.savefig(dst, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Preview saved → {dst}")


if __name__ == "__main__":
    main()
