#!/usr/bin/env python3
"""
Step 2 of the video export: Plotly figure JSON -> PNG (or SVG) with Kaleido.

    python visuals/export_png.py [--in visuals/out/figures] [--out visuals/out/png]
                                 [--format png] [--scale 1]

Size comes from each figure's layout (THEME.width x THEME.height in
templates/cards/metrixx-cards.js), so every card lands on the same frame size
for Shotstack.

Kaleido 1.x drives a headless Chrome. If none is found, either run
`plotly_get_chrome` once, or point BROWSER_PATH at an existing Chrome/Chromium.
"""
import argparse
import json
import sys
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=str(HERE / "out" / "figures"))
    ap.add_argument("--out", dest="dst", default=str(HERE / "out" / "png"))
    ap.add_argument("--format", default="png", choices=["png", "svg", "jpeg", "webp", "pdf"])
    ap.add_argument("--scale", type=float, default=1.0, help="2 = double resolution")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    files = sorted(src.glob("*.json"))
    if not files:
        print(f"No figure JSON in {src}. Run: node visuals/build_figures.js", file=sys.stderr)
        return 1
    dst.mkdir(parents=True, exist_ok=True)

    figs, paths, widths, heights = [], [], [], []
    for f in files:
        spec = json.loads(f.read_text())
        figs.append(go.Figure(data=spec["data"], layout=spec["layout"]))
        paths.append(dst / f"{f.stem}.{args.format}")
        # Kaleido ignores layout size unless passed explicitly
        widths.append(spec["layout"].get("width"))
        heights.append(spec["layout"].get("height"))

    # One Chrome session for the whole batch
    pio.write_images(figs, paths, format=args.format, scale=args.scale, width=widths, height=heights)
    for p in paths:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
