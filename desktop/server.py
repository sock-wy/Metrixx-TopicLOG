"""Topic Log desktop app: a local server that pulls the data on a timer and serves the dashboard.

Data and settings live in ~/Library/Application Support/TopicLog/. The window is a native
pywebview window when available, otherwise a Chrome app window, otherwise the default browser.
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

APP = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
SUP = pathlib.Path.home() / "Library" / "Application Support" / "TopicLog"
DATA = SUP / "data"
SETTINGS = SUP / "settings.json"
WEB = APP / "web"
DATASETS = ["topic_log", "score_history", "daily_log", "runs", "adanos_daily", "symbol_appendix", "market_data",
            "us_stocks", "earnings_calendar", "us_movers", "polymarket", "crypto_spot", "events",
            "kalshi_perps", "venue_appendix", "sectors", "news", "briefing"]
DEFAULT_SETTINGS = {"interval_min": 480, "adanos_key": ""}
INTERVAL_V = 2  # v2: three pulls a day by default (Oct 26); older saved intervals move to 8 hours once

VERSION = "0.6"
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


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:  # defaults shipped inside the app (the Adanos key the user provided)
        s.update(json.loads((APP / "settings.default.json").read_text()))
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
    os.chmod(SETTINGS, 0o600)


state = {"running": False, "last_run": None, "last_ok": None, "error": None, "next_run": None, "summary": None}
lock = threading.Lock()
wake = threading.Event()


def last_run_from_disk():
    try:
        runs = json.loads((DATA / "runs.json").read_text())
        return runs[-1]
    except Exception:
        return None


def pull():
    if not lock.acquire(blocking=False):
        return
    state.update(running=True, error=None)
    try:
        from dashboard import pipeline
        s = load_settings()
        row = pipeline.run(DATA, DATA, adanos_key=s.get("adanos_key") or None)
        state.update(last_ok=dt.datetime.now(dt.timezone.utc).isoformat(), summary=row)
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        (SUP / "last_error.txt").write_text(traceback.format_exc())
    finally:
        state["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
        state["running"] = False
        lock.release()


def scheduler():
    last = last_run_from_disk()
    if last:
        state["last_ok"] = state["last_run"] = last.get("run_ts")
    while True:
        s = load_settings()
        interval = max(15, int(s.get("interval_min") or 480)) * 60
        ref = state["last_run"]
        due = 0 if not ref else max(0, interval - (time.time() - dt.datetime.fromisoformat(ref).timestamp()))
        state["next_run"] = dt.datetime.fromtimestamp(time.time() + due, dt.timezone.utc).isoformat()
        if wake.wait(timeout=due):
            wake.clear()
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
        if self.path.startswith("/api/status"):
            s = load_settings()
            return self._json({**state, "interval_min": s["interval_min"], "has_key": bool(s.get("adanos_key")),
                               "data_dir": str(DATA)})
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/refresh":
            wake.set()
            return self._json({"ok": True})
        if self.path == "/api/settings":
            s = load_settings()
            if "interval_min" in body:
                s["interval_min"] = max(15, int(body["interval_min"]))
            s["interval_v"] = INTERVAL_V
            if body.get("adanos_key"):
                s["adanos_key"] = str(body["adanos_key"]).strip()
            save_settings(s)
            wake.set() if body.get("refresh") else None
            return self._json({"ok": True})
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
    chrome = "/Applications/Google Chrome.app"
    if os.path.exists(chrome):
        subprocess.Popen(["open", "-na", chrome, "--args", f"--app={url}", f"--user-data-dir={SUP / 'chrome'}",
                          "--window-size=1520,960"])
    else:
        webbrowser.open(url)
    while True:  # keep serving until Quit is pressed in the page
        time.sleep(3600)


if __name__ == "__main__":
    main()
