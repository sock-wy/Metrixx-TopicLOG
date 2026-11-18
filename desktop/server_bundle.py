"""Assemble the Topic Log app folder for the server image (the same files desktop/build.sh puts in the Mac app).
Usage: python server_bundle.py <repo root> <app dir>"""
import pathlib
import shutil
import sys
import urllib.request

root, a = map(pathlib.Path, sys.argv[1:3])
for d in ("web", "dashboard", "scoring", "config", "mp4gen/templates"):
    (a / d).mkdir(parents=True, exist_ok=True)
for f in ("server.py", "episode.py", "supercast.py", "episode_prompt.md", "episode_prompt_teaching.md"):
    shutil.copy(root / "desktop" / f, a)
for f in (root / "desktop" / "web").iterdir():
    shutil.copy(f, a / "web")
for f in ("__init__.py", "pipeline.py", "sources.py", "symbols.py", "registry.py", "archive.py", "briefing.py", "digest.py", "daily.py",
          "rankhist.py", "report.py", "providers.py", "adanos_universe.json", "catalysts.yaml"):
    shutil.copy(root / "dashboard" / f, a / "dashboard")
shutil.copy(root / "dashboard" / "backfill" / "rank_seed.json", a)
for f in list((root / "mp4gen").glob("*.py")) + [root / "mp4gen" / "plan_prompt.md"]:
    shutil.copy(f, a / "mp4gen")
for f in (root / "mp4gen" / "templates").iterdir():
    shutil.copy(f, a / "mp4gen" / "templates")
for f in ("__init__.py", "scoring.py"):
    shutil.copy(root / "scoring" / f, a / "scoring")
shutil.copy(root / "config" / "weights_w0.yaml", a / "config")
urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js", a / "web" / "d3.min.js")
page = (root / "dashboard" / "page" / "index.html").read_text(encoding="utf-8")
shell = (root / "desktop" / "web" / "shell.html").read_text(encoding="utf-8")
(a / "web" / "index.html").write_text(shell.replace("{{PAGE}}", page), encoding="utf-8")
print("bundled", a)
