"""The job: one folder per episode video, steps run in order, a stop for review before the paid render.

<root>/<date>_<TICKER>/        (named after the plan; "pending_<time>" until then)
  job.json        status, steps, messages
  script.md       the spoken script as given
  audio.mp3       the voice
  words.json      step 1     plan.json   step 2     data.json + checks.json   step 3
  charts/         step 4 (scene_NN.png, the templates and plan.js / data.js used to draw them)
  edit.json, captions.srt, uploads.json    step 5-6
  <slug>.mp4      the video
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import shutil
import threading
import traceback

from . import align, charts, data, plan as planner, render, timeline
from .util import StepError, now, read_json, script_text, write_json

STEPS = ["align", "plan", "data", "charts", "timeline", "upload", "render"]
LOCK = threading.Lock()


def _state(job):
    return read_json(job / "job.json", {})


def _set(job, **kw):
    with LOCK:
        s = _state(job)
        s.update(kw)
        s["updated"] = now()
        write_json(job / "job.json", s)
        return s


def _step(job, name, status, msg=""):
    with LOCK:
        s = _state(job)
        s.setdefault("steps", {})[name] = {"status": status, "at": now(), "msg": msg}
        s["step"] = name
        s["updated"] = now()
        write_json(job / "job.json", s)


def create(root: pathlib.Path, script_raw: str, audio: bytes, name: str = "") -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    job = root / ("pending_" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    job.mkdir()
    (job / "script.md").write_text(script_raw, encoding="utf-8")
    (job / "audio.mp3").write_bytes(audio)
    write_json(job / "job.json", {"id": job.name, "created": now(), "status": "queued", "source": name, "steps": {}, "checks": []})
    return job


def _rename(job: pathlib.Path, p: dict) -> pathlib.Path:
    if not job.name.startswith("pending_"):
        return job
    base = f"{p.get('date') or dt.date.today().isoformat()}_{re.sub(r'[^A-Za-z0-9]', '', p.get('ticker') or 'EP')[:12]}"
    new = job.parent / base
    k = 2
    while new.exists():
        new = job.parent / f"{base}_{k}"
        k += 1
    job.rename(new)
    _set(new, id=new.name)
    return new


def prepare(job: pathlib.Path, keys: dict, digest: dict | None = None, note: str = "") -> pathlib.Path:
    """Steps 1-4, then stop for review. Returns the (possibly renamed) job folder."""
    try:
        _set(job, status="running", error=None)
        script = script_text((job / "script.md").read_text(encoding="utf-8"))
        if not (job / "words.json").exists():
            _step(job, "align", "running")
            a = align.run((job / "audio.mp3").read_bytes(), script, keys)
            write_json(job / "words.json", a)
            _step(job, "align", "done", f"{a['matched']} of {a['total']} words matched · {a['duration']:.0f} s")
        a = read_json(job / "words.json")
        if (_state(job).get("steps", {}).get("align") or {}).get("status") != "done":
            _step(job, "align", "done", f"{a['matched']} of {a['total']} words matched · {a['duration']:.0f} s")
        _step(job, "plan", "running")
        p = planner.run(script, keys, digest, note=note, previous=read_json(job / "plan.json") if note else None)
        write_json(job / "plan.json", p)
        _step(job, "plan", "done", f"{len(p['scenes'])} scenes")
        job = _rename(job, p)
        _step(job, "data", "running")
        d, checks = data.run(p, script, keys, digest)
        write_json(job / "plan.json", p)  # data may add sources
        write_json(job / "data.json", d)
        write_json(job / "checks.json", checks)
        _step(job, "data", "done", f"{len(d['prices'])} price series · {len(checks)} check(s)")
        _step(job, "charts", "running")
        outs = charts.render(job, p, d)
        times = timeline.scene_times(p, a["words"], a["duration"])
        _step(job, "charts", "done", f"{len(outs)} images")
        _set(job, status="review", checks=checks, slug=p["slug"], title=p.get("title"),
             scenes=[{"n": i + 1, "type": s["type"], "kicker": s.get("kicker") or s.get("title") or s["type"], "anchor": s.get("anchor"),
                      "start": t[0], "end": t[1], "image": f"charts/scene_{i + 1:02d}.png"} for i, (s, t) in enumerate(zip(p["scenes"], times))])
    except Exception as e:
        _fail(job, e)
    return job


def finish(job: pathlib.Path, keys: dict, progress=None) -> pathlib.Path | None:
    """Steps 5-6 after review: timeline, upload, render, download."""
    try:
        _set(job, status="rendering", error=None)
        p, a = read_json(job / "plan.json"), read_json(job / "words.json")
        imgs = [job / "charts" / f"scene_{i + 1:02d}.png" for i in range(len(p["scenes"]))]
        _step(job, "upload", "running")
        cache = job / "uploads.json"
        voice = render.upload(job / "audio.mp3", keys, cache)
        urls = [render.upload(f, keys, cache) for f in imgs]
        _step(job, "upload", "done", f"{len(urls) + 1} files")
        _step(job, "timeline", "running")
        edit, times, caps = timeline.build(p, a, urls, voice)
        write_json(job / "edit.json", edit)
        (job / "captions.srt").write_text(timeline.srt(caps), encoding="utf-8")
        _step(job, "timeline", "done", f"{len(times)} scenes · {len(caps)} captions")
        _step(job, "render", "running", f"Shotstack {keys.get('shotstack_env', 'stage')}")
        out = job / f"{p['slug']}.mp4"
        rid = render.render(edit, keys, out, progress=lambda m: _step(job, "render", "running", m))
        _step(job, "render", "done", f"render {rid}")
        _set(job, status="done", video=out.name)
        return out
    except Exception as e:
        _fail(job, e)
        return None


def _fail(job, e):
    msg = str(e) if isinstance(e, StepError) else f"{type(e).__name__}: {e}"
    s = _state(job)
    if s.get("step"):
        _step(job, s["step"], "error", msg)
    _set(job, status="error", error=msg, trace=traceback.format_exc()[-2000:])


def jobs(root: pathlib.Path) -> list:
    out = []
    for d in sorted(root.glob("*/job.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        s = read_json(d, {})
        s["folder"] = d.parent.name
        out.append(s)
    return out


def remove_render(job: pathlib.Path):
    for f in ("edit.json", "captions.srt"):
        (job / f).unlink(missing_ok=True)
    shutil.rmtree(job / "_tmp", ignore_errors=True)
