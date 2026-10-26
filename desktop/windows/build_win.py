"""Build TopicLog.exe (Windows) with PyInstaller: python desktop/windows/build_win.py

Runs on GitHub's Windows runner (.github/workflows/windows-app.yml). The .exe carries no Adanos key: the key goes
in a settings.default.json next to the .exe ({"interval_min": 480, "adanos_key": "..."}), or into the app's
"Adanos key..." button. Output: desktop/dist/win/TopicLog.exe
"""
from __future__ import annotations

import os
import pathlib
import shutil
import urllib.request

import PyInstaller.__main__

ROOT = pathlib.Path(__file__).resolve().parents[2]
WIN = ROOT / "desktop" / "windows"
STAGE = ROOT / "desktop" / "dist" / "win_stage"
OUT = ROOT / "desktop" / "dist" / "win"

shutil.rmtree(STAGE, ignore_errors=True)
for d in ("web", "dashboard", "scoring", "config"):
    (STAGE / d).mkdir(parents=True)
shutil.copy(ROOT / "desktop" / "server.py", STAGE)
shutil.copy(WIN / "launcher.py", STAGE)
for f in (ROOT / "desktop" / "web").iterdir():
    shutil.copy(f, STAGE / "web")
for f in ("__init__.py", "pipeline.py", "sources.py", "symbols.py", "registry.py", "archive.py", "briefing.py",
          "adanos_universe.json", "catalysts.yaml"):
    shutil.copy(ROOT / "dashboard" / f, STAGE / "dashboard")
for f in ("__init__.py", "scoring.py"):
    shutil.copy(ROOT / "scoring" / f, STAGE / "scoring")
shutil.copy(ROOT / "config" / "weights_w0.yaml", STAGE / "config")
urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js", STAGE / "web" / "d3.min.js")
page = (ROOT / "dashboard" / "page" / "index.html").read_text(encoding="utf-8")
shell = (ROOT / "desktop" / "web" / "shell.html").read_text(encoding="utf-8")
(STAGE / "web" / "index.html").write_text(shell.replace("{{PAGE}}", page), encoding="utf-8")

sep = os.pathsep
PyInstaller.__main__.run([
    str(STAGE / "launcher.py"),
    "--name", "TopicLog", "--onefile", "--windowed", "--noconfirm", "--clean",
    "--icon", str(WIN / "AppIcon.ico"),
    "--paths", str(STAGE),
    "--distpath", str(OUT), "--workpath", str(ROOT / "desktop" / "dist" / "win_build"), "--specpath", str(ROOT / "desktop" / "dist"),
    "--add-data", f"{STAGE / 'web'}{sep}web",
    "--add-data", f"{STAGE / 'config'}{sep}config",
    "--add-data", f"{STAGE / 'dashboard' / 'adanos_universe.json'}{sep}dashboard",
    "--add-data", f"{STAGE / 'dashboard' / 'catalysts.yaml'}{sep}dashboard",
    *[a for m in ("server", "dashboard.pipeline", "dashboard.sources", "dashboard.symbols", "dashboard.registry",
                  "dashboard.archive", "dashboard.briefing", "scoring.scoring", "yaml", "webview")
      for a in ("--hidden-import", m)],
    "--collect-data", "tzdata",
])
print("built", OUT / "TopicLog.exe")
