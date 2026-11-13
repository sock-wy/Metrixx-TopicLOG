"""Step 4: one PNG per scene (templates/scene.html, ApexCharts + DXcharts), and a contact sheet to review.

Renderer: Playwright when installed, else Chrome / Edge in headless mode (no extra package needed)."""
from __future__ import annotations

import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile

from .util import StepError

TPL = pathlib.Path(__file__).with_name("templates")
BROWSERS = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Chromium.app/Contents/MacOS/Chromium", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    "Windows": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "Linux": ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"],
}


def prepare(job: pathlib.Path, plan: dict, data: dict) -> pathlib.Path:
    d = job / "charts"
    d.mkdir(exist_ok=True)
    for f in TPL.iterdir():
        shutil.copy(f, d / f.name)
    (d / "plan.js").write_text("const PLAN = " + json.dumps(plan, ensure_ascii=False) + ";\n", encoding="utf-8")
    (d / "data.js").write_text("const DATA = " + json.dumps(data) + ";\n", encoding="utf-8")
    return d


def _browser():
    for p in BROWSERS.get(platform.system(), []):
        if os.path.exists(p):
            return p
    for n in ("google-chrome", "chromium", "chrome", "msedge"):
        if shutil.which(n):
            return shutil.which(n)
    return None


def render(job: pathlib.Path, plan: dict, data: dict, only=None) -> list:
    d = prepare(job, plan, data)
    idx = [i for i in range(len(plan["scenes"])) if only is None or i in only]
    outs = [d / f"scene_{i + 1:02d}.png" for i in range(len(plan["scenes"]))]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1920, "height": 1080})
            for i in idx:
                pg.goto((d / "scene.html").resolve().as_uri() + f"?n={i}")
                pg.wait_for_timeout(1200)
                pg.screenshot(path=str(outs[i]))
            b.close()
    except ImportError:
        exe = _browser()
        if not exe:
            raise StepError("No renderer: install Google Chrome or Microsoft Edge (or the playwright package).")
        with tempfile.TemporaryDirectory() as prof:
            for i in idx:
                url = (d / "scene.html").resolve().as_uri() + f"?n={i}"
                cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                       "--window-size=1920,1080", "--virtual-time-budget=4000", "--allow-file-access-from-files",
                       f"--user-data-dir={prof}", f"--screenshot={outs[i]}", url]
                subprocess.run(cmd, check=False, capture_output=True, timeout=120)
                if not outs[i].exists():
                    raise StepError(f"The browser did not draw scene {i + 1}.")
    contact(job, outs)
    return outs


def contact(job: pathlib.Path, outs: list):
    """A contact sheet of every scene, 3 per row, for the review step (needs Pillow; skipped without it)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    ims = [o for o in outs if o.exists()]
    if not ims:
        return None
    W, H, cols = 640, 360, 3
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (W + 12) + 12, rows * (H + 40) + 12), (10, 11, 14))
    dr = ImageDraw.Draw(sheet)
    for k, f in enumerate(ims):
        x, y = 12 + (k % cols) * (W + 12), 12 + (k // cols) * (H + 40)
        sheet.paste(Image.open(f).convert("RGB").resize((W, H)), (x, y + 28))
        dr.text((x, y + 6), f"{k + 1}", fill=(232, 184, 75))
    p = job / "contact.png"
    sheet.save(p)
    return p
