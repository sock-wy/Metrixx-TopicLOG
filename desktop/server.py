"""Topic Log desktop app: a local server that pulls the data on a timer and serves the dashboard.

Data and settings live in ~/Library/Application Support/TopicLog/ (macOS) or %APPDATA%/TopicLog/ (Windows).
The window is a native pywebview window when available, otherwise a Chrome / Edge app window, otherwise the
default browser. On Windows the app is one TopicLog.exe (PyInstaller, desktop/windows/); an Adanos key can sit
next to it in settings.default.json.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP = pathlib.Path(__file__).resolve().parent  # inside TopicLog.exe this is the unpacked bundle
sys.path.insert(0, str(APP))
WINDOWS = sys.platform == "win32"
EXE_DIR = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP
if WINDOWS:
    SUP = pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / "AppData" / "Roaming") / "TopicLog"
else:
    SUP = pathlib.Path.home() / "Library" / "Application Support" / "TopicLog"
DATA = SUP / "data"
SETTINGS = SUP / "settings.json"
WEB = APP / "web"


def _edition():
    """"customer" when an edition.json saying so sits in the app folder or next to the .exe; else "beta"."""
    for d in (APP, EXE_DIR):
        try:
            e = json.loads((pathlib.Path(d) / "edition.json").read_text()).get("edition")
            if e:
                return str(e)
        except Exception:
            pass
    return "beta"


EDITION = _edition()
DATASETS = ["topic_log", "score_history", "daily_log", "runs", "adanos_daily", "symbol_appendix", "market_data",
            "us_stocks", "earnings_calendar", "us_movers", "polymarket", "crypto_spot", "events",
            "kalshi_perps", "venue_appendix", "sectors", "news", "briefing", "claude_digest", "rank_changes"]
# Pull schedule (v1.0, Nov 8): times of day in Chicago time, set in the app (Schedule…). 15:15 CT (= 16:15 ET) is the
# pick of record and cannot be removed. A changed schedule starts from the next time; a time missed while the
# computer slept runs on wake.
TZ_NAME = "America/Chicago"
PICK_SLOT = "15:15"
DEFAULT_SCHEDULE = [{"t": "06:00", "on": True}, {"t": PICK_SLOT, "on": True}]
MAX_SLOTS, MIN_GAP_MIN = 6, 30
DEFAULT_SETTINGS = {"adanos_key": "", "schedule": DEFAULT_SCHEDULE, "weekdays_only": False, "schedule_set_at": None}
INTERVAL_V = 4  # v4: the schedule replaces the interval menu; older settings move to the default schedule once

VERSION = "1.1"

DATA.mkdir(parents=True, exist_ok=True)
_ver = SUP / "version"
_old = _ver.read_text().strip() if _ver.exists() else None


def _last_ts(folder):
    try:
        return json.loads((folder / "runs.json").read_text())[-1].get("run_ts") or ""
    except Exception:
        return ""


if (APP / "seed").exists() and (not any(DATA.glob("*.json")) or _last_ts(APP / "seed") > _last_ts(DATA)):
    # first start, or the pull shipped with the app is newer than the data on this Mac: begin from it.
    # Never replace newer local data (and its history) on an update.
    for p in (APP / "seed").glob("*.json"):
        shutil.copy(p, DATA / p.name)
_ver.write_text(VERSION)

import episode  # noqa: E402  (MYCAST episodes: draft -> approve -> MP3)
episode.init(SUP, DATA, APP, EXE_DIR)


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    for f in (APP / "settings.default.json", EXE_DIR / "settings.default.json"):
        try:  # defaults shipped with the app (the Adanos key the user provided); on Windows, next to the .exe
            s.update(json.loads(f.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    try:
        saved = json.loads(SETTINGS.read_text())
        if saved.get("interval_v", 1) < INTERVAL_V:
            saved.pop("interval_min", None)
            saved.update(schedule=DEFAULT_SCHEDULE, interval_v=INTERVAL_V)
            save_settings(saved)
        s.update({k: v for k, v in saved.items() if v not in (None, "")})
    except Exception:
        pass
    return s


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=1))
    try:
        os.chmod(SETTINGS, 0o600)
    except OSError:
        pass


state = {"running": False, "last_run": None, "last_ok": None, "error": None, "next_run": None, "summary": None}
lock = threading.Lock()
wake = threading.Event()


def last_run_from_disk():
    try:
        runs = json.loads((DATA / "runs.json").read_text())
        return runs[-1]
    except Exception:
        return None


# ------------------------------------------------------------------ the data folder on the Desktop
def _desktop():
    home = pathlib.Path.home()
    for d in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if d.is_dir():
            return d
    return home


OUT = _desktop() / "Topic Log Data"  # everything Topic Log produces, by kind; never inside the app's folder
SUBDIRS = ("daily", "rank_history", "digests", "audio", "scripts", "exports")
OLD_DESKTOP = _desktop() / "TopicLog"  # v0.9 copied the daily files to ~/Desktop/TopicLog/daily/


def out_dir(kind):
    d = OUT / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


episode.OUT_DIR = out_dir  # episodes put MP3s in Topic Log Data/audio and scripts in Topic Log Data/scripts


def _note(msg):
    try:
        with open(SUP / "last_error.txt", "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def _stamp(run_ts):
    from dashboard import rankhist
    return rankhist.to_ct(run_ts).replace(" ", "_").replace(":", "") + "CT"


def save_outputs(row):
    """After a pull: the day's Topic Log, this pull's full ranking and its digest go to the data folder."""
    try:
        from dashboard import rankhist
        name = (row or {}).get("daily_file")
        if name and (DATA / "daily" / name).exists():
            shutil.copy(DATA / "daily" / name, out_dir("daily") / name)
        rows = json.loads((DATA / "topic_log.json").read_text())
        run_ts = rows[0]["run_ts"] if rows else (row or {}).get("run_ts")
        if run_ts:
            snap = rankhist.snapshot(run_ts, rows)
            (out_dir("rank_history") / f"rank_{_stamp(run_ts)}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
            if (DATA / "claude_digest.json").exists():
                shutil.copy(DATA / "claude_digest.json", out_dir("digests") / f"claude_digest_{_stamp(run_ts)}.json")
    except Exception as e:  # e.g. macOS asked for Desktop access and it was refused
        _note(f"data folder: {type(e).__name__}: {e}")


def _copy_missing(src_files, dest):
    n = 0
    for f in src_files:
        if f.is_file() and not (dest / f.name).exists():
            shutil.copy2(f, dest / f.name)
            n += 1
    return n


def migrate():
    """Every start: fill the data folder with what is already on this computer, and backfill the rank history.

    Copies (never moves or deletes) the daily files, episode MP3s and scripts; rebuilds rank_history.json from
    the history shipped with the app (archive since Oct 23) plus this computer's own 10-day score history."""
    try:
        from dashboard import rankhist
        _copy_missing(list((DATA / "daily").glob("*.json")) + list((OLD_DESKTOP / "daily").glob("*.json")), out_dir("daily"))
        _copy_missing(list((SUP / "episodes").glob("*/*.mp3")), out_dir("audio"))
        hist = []
        try:
            hist = json.loads((DATA / "rank_history.json").read_text())
        except Exception:
            pass
        for f in (APP / "rank_seed.json", APP / "dashboard" / "rank_seed.json"):
            if f.exists():
                hist = rankhist.merge(hist, json.loads(f.read_text()))
                break
        try:
            names = {r["topic"]: (r.get("name"), r.get("asset_class")) for r in hist}
            names.update({r["topic"]: (r.get("name"), r.get("asset_class")) for r in json.loads((DATA / "topic_log.json").read_text())})
            hist = rankhist.merge(hist, rankhist.from_score_history(json.loads((DATA / "score_history.json").read_text()), names))
        except Exception:
            pass
        if hist:
            (DATA / "rank_history.json").write_text(json.dumps(hist, separators=(",", ":")))
            (DATA / "rank_changes.json").write_text(json.dumps([rankhist.analyze(hist)], separators=(",", ":"), default=str))
            have = {p.name for p in out_dir("rank_history").glob("*.json")}
            by = {}
            for h in hist:
                by.setdefault(h["run_ts"], []).append(h)
            for ts, rows in by.items():
                name = f"rank_{_stamp(ts)}.json"
                if name not in have:  # backfilled pulls: the top 50 that was kept
                    snap = rankhist.snapshot(ts, rows)
                    snap["notes"] = "Backfilled from the rank history: top 50 only. " + snap["notes"]
                    (out_dir("rank_history") / name).write_text(json.dumps(snap, indent=1), encoding="utf-8")
        readme = OUT / "README.txt"
        if not readme.exists():
            readme.write_text(README_DATA, encoding="utf-8")
    except Exception as e:
        _note(f"migrate: {type(e).__name__}: {e}")


README_DATA = """Topic Log Data
==============
Everything the Topic Log app produces, written here automatically. Safe to read, copy or back up.
The app only adds files here; it never deletes. You can move this folder's files elsewhere,
but keep the folder name "Topic Log Data" on the Desktop so the app keeps writing to it.

daily/         One file per New York trading day: topic_log_YYYY-MM-DD.json (ranks, prices, sentiment, news).
rank_history/  One file per pull: rank_YYYY-MM-DD_HHMMCT.json, the full ranking with ranks overall and
               within each category. Files marked "Backfilled" (pulls before this folder existed) hold the top 50.
digests/       claude_digest_<time>CT.json for each pull, and every "Export JSON for Claude".
audio/         MYCAST episode MP3s.
scripts/       Episode scripts exported from the Episode tab (.md / .txt).
exports/       Ranking reports (PDF and Excel) from the Export buttons.

Times in file names are Chicago time (CT). Not investment advice.
"""


def pull():
    if not lock.acquire(blocking=False):
        return
    state.update(running=True, error=None)
    try:
        from dashboard import pipeline
        s = load_settings()
        row = pipeline.run(DATA, DATA, adanos_key=s.get("adanos_key") or None)
        save_outputs(row)
        state.update(last_ok=dt.datetime.now(dt.timezone.utc).isoformat(), summary=row)
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        (SUP / "last_error.txt").write_text(traceback.format_exc())
    finally:
        state["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
        state["running"] = False
        lock.release()


def _tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TZ_NAME)


def _hm(t):
    h, m = str(t).strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(t)
    return h, m


def clean_schedule(items):
    """Validate a schedule from the app: HH:MM times, the pick slot always present and on, sorted, gaps >= 30 min."""
    out, seen = [], set()
    for it in items or []:
        h, m = _hm(it.get("t") if isinstance(it, dict) else it)
        t = f"{h:02d}:{m:02d}"
        if t in seen:
            continue
        seen.add(t)
        out.append({"t": t, "on": True if t == PICK_SLOT else bool(it.get("on", True)) if isinstance(it, dict) else True})
    if PICK_SLOT not in seen:
        out.append({"t": PICK_SLOT, "on": True})
    out.sort(key=lambda x: x["t"])
    if len(out) > MAX_SLOTS:
        raise ValueError(f"At most {MAX_SLOTS} pull times a day.")
    on = [x for x in out if x["on"]]
    mins = [int(x["t"][:2]) * 60 + int(x["t"][3:]) for x in on]
    for a, b, x in zip(mins, mins[1:] + [mins[0] + 1440], on):
        if len(mins) > 1 and b - a < MIN_GAP_MIN:
            raise ValueError(f"Pull times must be at least {MIN_GAP_MIN} minutes apart ({x['t']}).")
    return out


def slot_times(now=None, s=None):
    """(last scheduled pull at or before now, next one after now), as aware datetimes in Chicago time."""
    s = s or load_settings()
    tz = _tz()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    try:
        sched = clean_schedule(s.get("schedule"))
    except Exception:
        sched = DEFAULT_SCHEDULE
    times = [_hm(x["t"]) for x in sched if x["on"]]
    slots = []
    for d in range(-8, 9):
        day = now.date() + dt.timedelta(days=d)
        if s.get("weekdays_only") and day.weekday() >= 5:
            continue
        slots += [dt.datetime.combine(day, dt.time(h, m), tzinfo=tz) for h, m in times]
    return max(x for x in slots if x <= now), min(x for x in slots if x > now)


def due_in(ref, s, now=None):
    """Seconds until the next pull (0 = pull now). ref = ISO time of the last pull, or None (never pulled: now).

    The last scheduled time is pulled only if it came after both the last pull and the moment the schedule was
    saved, so saving a schedule never starts a pull: it starts from the next time."""
    now = now or dt.datetime.now(dt.timezone.utc)
    prev, nxt = slot_times(now, s)
    marks = [dt.datetime.fromisoformat(x) for x in (ref, s.get("schedule_set_at")) if x]
    if not ref or prev > max(marks):
        return 0
    return (nxt - now).total_seconds()


def scheduler():
    last = last_run_from_disk()
    if last:
        state["last_ok"] = state["last_run"] = last.get("run_ts")
    while True:
        s = load_settings()
        due = due_in(state["last_run"], s)
        state["next_run"] = dt.datetime.fromtimestamp(time.time() + due, dt.timezone.utc).isoformat()
        if due > 0:
            # wake at least once a minute so a slot passed during sleep, or a settings change, is noticed
            if wake.wait(timeout=min(due, 60)):
                wake.clear()
                pull()
            continue
        pull()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _ep_get(self, rest):
        try:
            if rest == "list":
                return self._json({"episodes": episode.listing(), "candidates": episode.candidates(), "keys": episode.keys_status()})
            if rest == "keys":
                return self._json(episode.keys_status())
            eid, _, what = rest.partition("/")
            if what == "audio.mp3":
                p = episode.audio_path(eid)
                if not p or not p.exists():
                    return self._json({"error": "no audio"}, 404)
                b = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            ep = episode.load(eid)
            ep.pop("messages", None)
            return self._json(episode.view(ep))
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 400)

    def _ep_post(self, rest, body):
        try:
            if rest == "new":
                return self._json({"id": episode.new(body.get("topic") or None, body.get("style") or "market")})
            if rest == "paste":  # a script written elsewhere (e.g. Jim's): no Claude draft, straight to review -> audio
                eid = episode.new_pasted(body.get("title"), body.get("script"), body.get("topic") or None)
                ep = episode.load(eid)
                ep.pop("messages", None)
                return self._json(episode.view(ep))
            if rest == "keys":
                episode.save_keys(body)
                return self._json(episode.keys_status())
            eid, _, act = rest.partition("/")
            if act == "save":
                episode.edit(eid, body.get("title"), body.get("script"))
            elif act == "regen":
                episode.regenerate(eid, body.get("note") or "", body.get("style"))
            elif act == "restore":
                episode.restore(eid, body.get("n"))
            elif act == "approve":
                episode.edit(eid, body.get("title"), body.get("script")) if body.get("script") else None
                episode.set_status(eid, "approved")
            elif act == "unapprove":
                episode.set_status(eid, "draft")
            elif act == "discard":
                episode.set_status(eid, "discarded")
            elif act == "audio":
                episode.make_audio(eid)
            elif act == "export":
                path, _ = episode.export(eid, body.get("format") or "md")
                return self._json({"path": path})
            elif act == "reveal":
                p = episode.audio_path(eid)
                if p and p.exists():
                    reveal(p)
            else:
                return self._json({"error": "unknown action"}, 404)
            ep = episode.load(eid)
            ep.pop("messages", None)
            return self._json(episode.view(ep))
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 400)

    def do_GET(self):
        if self.path.startswith("/api/data/"):
            name = self.path.split("/")[-1].split("?")[0]
            if name not in DATASETS:
                return self._json({"error": "unknown dataset"}, 404)
            p = DATA / f"{name}.json"
            b = p.read_bytes() if p.exists() else b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if self.path.startswith("/api/ep/"):
            if EDITION == "customer":
                return self._json({"error": "not in this edition"}, 404)
            return self._ep_get(self.path.split("?")[0][len("/api/ep/"):])
        if self.path.split("?")[0] in ("/", "/index.html") and EDITION == "customer":
            b = (WEB / "index.html").read_text(encoding="utf-8").replace('<html lang="en">', '<html lang="en" data-edition="customer">', 1).replace("<title>Topic Log</title>", "<title>Topic Log Pro</title>", 1).replace('<span class="name">Topic Log</span>', '<span class="name">Topic Log Pro</span>', 1).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if self.path.startswith("/api/status"):
            s = load_settings()
            try:
                nxt = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=due_in(state["last_run"], s))
            except Exception:
                nxt = None
            return self._json({**state, "next_run": nxt.isoformat() if nxt else state["next_run"],
                               "schedule": clean_schedule(s.get("schedule")), "weekdays_only": bool(s.get("weekdays_only")),
                               "pick_slot": PICK_SLOT, "tz": TZ_NAME, "max_slots": MAX_SLOTS, "min_gap": MIN_GAP_MIN,
                               "has_key": bool(s.get("adanos_key")), "data_dir": str(DATA), "out_dir": str(OUT),
                               "version": VERSION, "edition": EDITION})
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/api/ep/"):
            if EDITION == "customer":
                return self._json({"error": "not in this edition"}, 404)
            return self._ep_post(self.path[len("/api/ep/"):], body)
        if self.path == "/api/refresh":
            wake.set()
            return self._json({"ok": True})
        if self.path == "/api/settings":
            s = load_settings()
            s["interval_v"] = INTERVAL_V
            if body.get("adanos_key"):
                s["adanos_key"] = str(body["adanos_key"]).strip()
            save_settings(s)
            wake.set() if body.get("refresh") else None
            return self._json({"ok": True})
        if self.path == "/api/schedule":  # Schedule…: new pull times; they start from the next time, no pull now
            s = load_settings()
            try:
                s["schedule"] = clean_schedule(body.get("schedule"))
            except Exception as e:
                return self._json({"error": str(e) if isinstance(e, ValueError) and " " in str(e) else f"Not a time: {e}. Use HH:MM, e.g. 06:30."}, 400)
            s["weekdays_only"] = bool(body.get("weekdays_only"))
            s["schedule_set_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            s["interval_v"] = INTERVAL_V
            save_settings(s)
            return self._json({"ok": True, "schedule": s["schedule"]})
        if self.path == "/api/export":  # ranking + rank changes as PDF or Excel, into Topic Log Data/exports/
            try:
                from dashboard import report
                path = report.export(DATA, out_dir("exports"), "xlsx" if body.get("format") == "xlsx" else "pdf")
            except Exception as e:
                return self._json({"error": f"{e}"}, 400)
            reveal(path)
            return self._json({"path": str(path)})
        if self.path == "/api/open-folder":
            reveal(out_dir(body.get("kind")) if body.get("kind") in SUBDIRS else OUT, inside=True)
            return self._json({"ok": True, "path": str(OUT)})
        if self.path == "/api/save":  # "Export JSON for Claude": save to Topic Log Data/digests and copy to the clipboard
            name = pathlib.Path(str(body.get("name") or "topiclog.json")).name
            text = str(body.get("text") or "")
            try:
                folder = out_dir("digests")
            except Exception:
                folder = SUP
            (folder / name).write_text(text, encoding="utf-8")
            copied = False
            try:
                cmd = ["clip"] if WINDOWS else ["pbcopy"] if sys.platform == "darwin" else None
                if cmd:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=10)
                    copied = True
            except Exception:
                pass
            return self._json({"path": str(folder / name), "copied": copied})
        if self.path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return
        self._json({"error": "not found"}, 404)


def reveal(path, inside=False):
    """Show a file (or open a folder) in Finder / Explorer."""
    try:
        path = pathlib.Path(path)
        if inside or path.is_dir():
            subprocess.Popen(["explorer", str(path)] if WINDOWS else ["open", str(path)])
        else:
            subprocess.Popen(["explorer", "/select,", str(path)] if WINDOWS else ["open", "-R", str(path)])
    except Exception:
        pass


def free_port(start=8765):
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise SystemExit("no free port")


def main():
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: (migrate(), scheduler()), daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    (SUP / "port").write_text(str(port))
    try:
        import webview  # pywebview: a real app window
        webview.create_window("Topic Log", url, width=1520, height=960, min_size=(900, 600))
        webview.start()
        os._exit(0)
    except Exception:
        pass
    if WINDOWS:
        edges = [pathlib.Path(os.environ.get(v, "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                 for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        edge = next((e for e in edges if e.is_file()), None)
        if edge:
            subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={SUP / 'edge'}", "--window-size=1520,960"])
        else:
            webbrowser.open(url)
    elif os.path.exists(chrome := "/Applications/Google Chrome.app"):
        subprocess.Popen(["open", "-na", chrome, "--args", f"--app={url}", f"--user-data-dir={SUP / 'chrome'}",
                          "--window-size=1520,960"])
    else:
        webbrowser.open(url)
    while True:  # keep serving until Quit is pressed in the page
        time.sleep(3600)


if __name__ == "__main__":
    main()
