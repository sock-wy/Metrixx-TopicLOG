"""Command line:  python3 -m mp4gen <script.md> <audio.mp3> [--out DIR] [--keys keys.json] [--digest claude_digest.json] [--yes]

Runs steps 1-4, prints the scenes and checks, and asks before the Shotstack render (--yes skips the question)."""
import argparse
import json
import pathlib

from . import pipeline
from .util import load_keys, read_json


def main():
    ap = argparse.ArgumentParser(prog="mp4gen")
    ap.add_argument("script")
    ap.add_argument("audio")
    ap.add_argument("--out", default=str(pathlib.Path.home() / "Desktop" / "Topic Log Data" / "episodes"))
    ap.add_argument("--keys", action="append", default=[])
    ap.add_argument("--digest")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    keys = load_keys(*a.keys)
    digest = read_json(a.digest) if a.digest else None
    job = pipeline.create(pathlib.Path(a.out), pathlib.Path(a.script).read_text(encoding="utf-8"), pathlib.Path(a.audio).read_bytes(),
                          pathlib.Path(a.script).name)
    job = pipeline.prepare(job, keys, digest)
    s = read_json(job / "job.json")
    print(json.dumps({k: s.get(k) for k in ("status", "error", "steps")}, indent=1))
    if s["status"] != "review":
        return 1
    for sc in s["scenes"]:
        print(f"{sc['n']:>2} {sc['start']:7.1f}-{sc['end']:7.1f}s  {sc['type']:8} {sc['kicker']}")
    for c in s.get("checks", []):
        print(f"  [{c['level']}] {c['msg']}")
    print("images:", job / "charts")
    if not a.yes and input("Render on Shotstack now? [y/N] ").strip().lower() != "y":
        return 0
    out = pipeline.finish(job, keys, progress=print)
    print("video:", out or read_json(job / "job.json").get("error"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
