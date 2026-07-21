#!/usr/bin/env python3
"""Render the AskAmerica icon SVGs to PNG previews + the shipped favicon set."""
import os
import sys

import cairosvg
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))

VARIANTS = {
    "split":   "icon.svg",         # dark tile, blue/red split hook, white star
    "alt":     "icon-alt.svg",     # blue tile, red hook, white star
    "nored":   "icon-nored.svg",   # blue tile, white hook, white star
    "splitbg": "icon-splitbg.svg", # blue/red split tile, white hook + white star
}

# ── previews: each variant at 16 / 32 / 64 / 180 so they can be eyeballed ──
PREVIEW_SIZES = [16, 32, 64, 180]
os.makedirs(os.path.join(HERE, "preview"), exist_ok=True)
for name, svg in VARIANTS.items():
    src = os.path.join(HERE, svg)
    for sz in PREVIEW_SIZES:
        out = os.path.join(HERE, "preview", "%s-%d.png" % (name, sz))
        cairosvg.svg2png(url=src, write_to=out, output_width=sz, output_height=sz)
    print("rendered preview:", name)


def build_favicon_set(svg_name):
    """Produce the shipped set from the chosen variant."""
    src = os.path.join(HERE, svg_name)
    # PNG favicons + apple-touch
    targets = {"favicon-16.png": 16, "favicon-32.png": 32, "apple-touch-icon.png": 180}
    for fname, sz in targets.items():
        cairosvg.svg2png(url=src, write_to=os.path.join(HERE, fname),
                         output_width=sz, output_height=sz)
    # multi-size .ico from the 32px render (Pillow downsamples to 16 internally)
    png32 = Image.open(os.path.join(HERE, "favicon-32.png")).convert("RGBA")
    png32.save(os.path.join(HERE, "favicon.ico"), format="ICO",
               sizes=[(16, 16), (32, 32), (48, 48)])
    print("built favicon set from:", svg_name)


if __name__ == "__main__":
    chosen = sys.argv[1] if len(sys.argv) > 1 else None
    if chosen:
        build_favicon_set(VARIANTS[chosen])
