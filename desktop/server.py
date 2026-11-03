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
DATASETS = ["topic_log", "score_history", "daily_log", "runs", "adanos_daily", "symbol_appendix", "market_data",
            "us_stocks", "earnings_calendar", "us_movers", "polymarket", "crypto_spot", "events",
            "kalshi_perps", "venue_appendix", "sectors", "news", "briefing", "claude_digest"]
DEFAULT_SETTINGS = {"interval_min": 0, "adanos_key": ""}
INTERVAL_V = 3  # v3 (Nov 3): fixed pull times 07:00 and 16:15 ET by default; older saved intervals move to it once
# interval_min 0 = pull at these New York times every day (a pull missed while the computer slept runs on wake)
PULL_TIMES_ET = ((7, 0), (16, 15))

VERSION = "0.9"
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
            saved.update(interval_min=DEFAULT_SETTINGS["interval_min"], interval_v=INTERVAL_V)
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


DESKTOP_DIR = pathlib.Path.home() / "Desktop" / "TopicLog"


def copy_daily(row):
    """Copy the day's Topic Log (topic_log_YYYY-MM-DD.json) to ~/Desktop/TopicLog/daily/ when that folder exists."""
    name = (row or {}).get("daily_file")
    src = DATA / "daily" / name if name else None
    if not (src and src.exists() and DESKTOP_DIR.is_dir()):
        return
    try:
        (DESKTOP_DIR / "daily").mkdir(exist_ok=True)
        shutil.copy(src, DESKTOP_DIR / "daily" / name)
    except Exception as e:  # e.g. macOS asked for Desktop access and it was refused
        (SUP / "last_error.txt").write_text(f"daily copy: {type(e).__name__}: {e}")


def pull():
    if not lock.acquire(blocking=False):
        return
    state.update(running=True, error=None)
    try:
        from dashboard import pipeline
        s = load_settings()
        row = pipeline.run(DATA, DATA, adanos_key=s.get("adanos_key") or None)
        copy_daily(row)
        state.update(last_ok=dt.datetime.now(dt.timezone.utc).isoformat(), summary=row)
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        (SUP / "last_error.txt").write_text(traceback.format_exc())
    finally:
        state["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
        state["running"] = False
        lock.release()


def _et():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def slot_times(now=None):
    """(last scheduled slot at or before now, next slot after now), as aware datetimes."""
    et = _et()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(et)
    slots = [dt.datetime.combine(now.date() + dt.timedelta(days=d), dt.time(h, m), tzinfo=et)
             for d in (-1, 0, 1) for h, m in PULL_TIMES_ET]
    return max(x for x in slots if x <= now), min(x for x in slots if x > now)


def due_in(ref, interval_min, now=None):
    """Seconds until the next pull (0 = pull now). ref = ISO time of the last pull, or None."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not ref:
        return 0
    last = dt.datetime.fromisoformat(ref)
    if not interval_min:  # fixed times
        prev, nxt = slot_times(now)
        return 0 if last < prev else (nxt - now).total_seconds()
    return max(0, max(15, int(interval_min)) * 60 - (now - last).total_seconds())


def scheduler():
    last = last_run_from_disk()
    if last:
        state["last_ok"] = state["last_run"] = last.get("run_ts")
    while True:
        s = load_settings()
        due = due_in(state["last_run"], s.get("interval_min"))
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
                return self._json({"id": episode.new(body.get("topic") or None)})
            if rest == "keys":
                episode.save_keys(body)
                return self._json(episode.keys_status())
            eid, _, act = rest.partition("/")
            if act == "save":
                episode.edit(eid, body.get("title"), body.get("script"))
            elif act == "regen":
                episode.regenerate(eid, body.get("note") or "")
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
                    subprocess.Popen(["explorer", "/select,", str(p)] if WINDOWS else ["open", "-R", str(p)])
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
            return self._ep_get(self.path.split("?")[0][len("/api/ep/"):])
        if self.path.startswith("/api/status"):
            s = load_settings()
            return self._json({**state, "interval_min": s["interval_min"], "has_key": bool(s.get("adanos_key")),
                               "data_dir": str(DATA)})
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/api/ep/"):
            return self._ep_post(self.path[len("/api/ep/"):], body)
        if self.path == "/api/refresh":
            wake.set()
            return self._json({"ok": True})
        if self.path == "/api/settings":
            s = load_settings()
            if "interval_min" in body:
                v = int(body["interval_min"])
                s["interval_min"] = 0 if v <= 0 else max(15, v)
            s["interval_v"] = INTERVAL_V
            if body.get("adanos_key"):
                s["adanos_key"] = str(body["adanos_key"]).strip()
            save_settings(s)
            wake.set() if body.get("refresh") else None
            return self._json({"ok": True})
        if self.path == "/api/save":  # "Export JSON for Claude": save to Downloads and copy to the clipboard
            name = pathlib.Path(str(body.get("name") or "topiclog.json")).name
            text = str(body.get("text") or "")
            folder = pathlib.Path.home() / "Downloads"
            folder = folder if folder.is_dir() else SUP
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
    threading.Thread(target=scheduler, daemon=True).start()
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
