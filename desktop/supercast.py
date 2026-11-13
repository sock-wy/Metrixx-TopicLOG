"""Supercast: find the MP3s in Topic Log Data/audio that are not on Supercast yet, and upload them.

Supercast's API (https://api.supercast.com/api/v1, podcast token from Settings > API) can only READ episodes
(checked Nov 13 2026: every create / update path is 404). So:
  - Check  = API: list the channel's episodes, compare with the MP3s on disk.
  - Upload = a browser window that Topic Log opens (Playwright with the installed Chrome or Edge, its own profile
             in the support folder): Episodes > New Episode > title + audio > Save as draft (or Publish).
             The first time, log in to Supercast in that window; the login is kept.
A record of what Topic Log uploaded: Topic Log Data/supercast/uploaded.json. Screenshots of a failed step go
next to it (debug_*.png), so the selectors can be fixed when Supercast changes its pages.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import threading
import time
import traceback
import urllib.error
import urllib.request

API = "https://api.supercast.com/api/v1"
NAME = re.compile(r"^(?P<base>mycast_(?P<date>\d{4}-\d{2}-\d{2})_(?P<topic>.+?))_v(?P<v>\d+)$", re.I)

state = {"running": False, "log": [], "last": None, "error": None, "started": None}
_lock = threading.Lock()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _say(msg):
    state["log"].append(f"{dt.datetime.now().strftime('%H:%M:%S')}  {msg}")
    state["log"] = state["log"][-200:]


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())


# ---------------------------------------------------------------- API (read only)
def api_get(path, token, params=""):
    req = urllib.request.Request(f"{API}/{path}{params}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                                                    "User-Agent": "TopicLog"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("Supercast says the token is not valid (401). Make a new one in Supercast: Settings > API.") from None
        raise RuntimeError(f"Supercast API {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None


def remote_episodes(token):
    """All episodes of the token's channel (pages of 100 until a page repeats or comes back short)."""
    out, seen = [], set()
    for page in range(1, 30):
        got = api_get("episodes", token, f"?per_page=100&page={page}") or []
        new = [e for e in got if e.get("id") not in seen]
        if not new:
            break
        out += new
        seen.update(e.get("id") for e in new)
        if len(got) < 100:
            break
    return out


# ---------------------------------------------------------------- local files
def _record(root):
    p = root / "supercast" / "uploaded.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_record(root, rec):
    d = root / "supercast"
    d.mkdir(parents=True, exist_ok=True)
    (d / "uploaded.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


def _script_info(scripts_dir, stem):
    """Title (the '# ' heading) and a short description (first paragraph of the script) from the exported script."""
    for ext in (".md", ".txt"):
        f = scripts_dir / (stem + ext)
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="replace")
            title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "")
            body = text.split("## Script", 1)[1] if "## Script" in text else text
            paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not p.strip().startswith("#")]
            desc = re.sub(r"[*_`>#]", "", paras[0])[:600] if paras else ""
            return title, desc
    return "", ""


def default_title(stem):
    """Supercast's own style for an untitled upload: 'mycast_2026-10-29_dash_v1' -> 'Mycast 2026 10 29 Dash V1'."""
    return " ".join(w.capitalize() for w in re.split(r"[_\-\s]+", stem) if w)


def check(root: pathlib.Path, token: str) -> dict:
    """Every MP3 in Topic Log Data/audio with its Supercast status."""
    remote = remote_episodes(token) if token else []
    by_title = {}
    for e in remote:
        by_title.setdefault(_norm(e.get("title")), e)
    rec = _record(root)
    try:  # list it directly: glob hides a refused folder (macOS asks each app for Desktop access)
        names = os.listdir(root / "audio")
    except PermissionError:
        raise RuntimeError("macOS did not let Topic Log read the Desktop. System Settings > Privacy & Security > Files and Folders > "
                           "Topic Log: turn on Desktop Folder (or add Topic Log under Full Disk Access), then Check again.") from None
    except FileNotFoundError:
        names = []
    files = sorted((root / "audio" / n for n in names if n.lower().endswith(".mp3")), key=lambda f: f.stat().st_mtime, reverse=True)
    newest = {}
    for f in files:
        m = NAME.match(f.stem)
        if m:
            k = m["base"].lower()
            newest[k] = max(newest.get(k, 0), int(m["v"]))
    rows = []
    for f in files:
        m = NAME.match(f.stem)
        title, desc = _script_info(root / "scripts", f.stem)
        names = [title, default_title(f.stem), f.stem]
        hit = next((by_title[_norm(n)] for n in names if n and _norm(n) in by_title), None)
        r = rec.get(f.name) or {}
        if hit:
            status = "published" if hit.get("state") == "published" else (hit.get("state") or "on supercast")
        elif r.get("status") == "uploaded":
            status = "uploaded"  # Topic Log saved it; the API may list it a moment later
        elif r.get("status") == "skip":
            status = "skipped"
        elif m and int(m["v"]) < newest.get(m["base"].lower(), 0):
            status = "older version"
        else:
            status = "pending"
        day = m["date"] if m else dt.date.fromtimestamp(f.stat().st_mtime).isoformat()
        rows.append({"file": f.name, "title": title or default_title(f.stem), "description": desc, "date": day,
                     "size_mb": round(f.stat().st_size / 1e6, 1), "status": status,
                     "remote": {k: hit.get(k) for k in ("id", "title", "state", "published_at")} if hit else None,
                     "uploaded_at": r.get("at")})
    return {"files": rows, "remote_count": len(remote), "checked": _now(),
            "pending": sum(r["status"] == "pending" for r in rows), "folder": str(root / "audio")}


def mark(root, names, status):
    rec = _record(root)
    for n in names:
        if status:
            rec[n] = {**rec.get(n, {}), "status": status, "at": _now()}
        else:
            rec.pop(n, None)
    _save_record(root, rec)


# ---------------------------------------------------------------- browser upload
def _first(page, tries, timeout=4000):
    """The first locator from `tries` (callables page -> locator) that is visible."""
    for t in tries:
        try:
            loc = t(page).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def _debug(root, page, what):
    d = root / "supercast"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"debug_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}_{re.sub(r'[^a-z]+', '-', what.lower())[:30]}.png"
    try:
        page.screenshot(path=str(f), full_page=True)
        return f
    except Exception:
        return None


def _launch(p, profile):
    errs = []
    for ch in ("chrome", "msedge", None):
        try:
            kw = {"channel": ch} if ch else {}
            return p.chromium.launch_persistent_context(str(profile), headless=False, viewport=None, args=["--start-maximized"],
                                                        chromium_sandbox=not (hasattr(os, "geteuid") and os.geteuid() == 0), **kw)
        except Exception as e:
            errs.append(f"{ch or 'bundled'}: {str(e).splitlines()[0][:120]}")
    raise RuntimeError("Could not open a browser. Install Google Chrome (Mac) or Microsoft Edge (Windows). " + " | ".join(errs))


EPISODES = {}  # the Episodes page URL as Supercast's own menu links it (found after login)


def _episodes_link(page, timeout=3000):
    return _first(page, [lambda p: p.get_by_role("link", name=re.compile(r"^\s*episodes\s*$", re.I)),
                         lambda p: p.locator("a[href*='episodes']").filter(has_text=re.compile(r"^\s*episodes\s*$", re.I))], timeout)


def _login(page, base, wait_s=600):
    """Open the dashboard and wait until Supercast's menu (with Episodes) shows, i.e. we are logged in."""
    page.goto(base, wait_until="domcontentloaded")
    link = _episodes_link(page, 6000)
    if not link:
        _say("Log in to Supercast in the browser window (only needed once). Waiting up to 10 minutes…")
        deadline = time.time() + wait_s
        while time.time() < deadline and not link:
            time.sleep(2)
            link = _episodes_link(page, 1500)
            if not link and "/dashboard" not in page.url and re.search(r"supercast\.com/?$|/(channels|podcasts)\b", page.url):
                try:
                    page.goto(base, wait_until="domcontentloaded")  # logged in but landed elsewhere
                except Exception:
                    pass
        if not link:
            raise RuntimeError("Not logged in to Supercast after 10 minutes (no Episodes menu found).")
        _say("Logged in.")
    link.click()
    page.wait_for_load_state("domcontentloaded")
    EPISODES["url"] = page.url
    _say(f"  Episodes page: {page.url}")


def _one(page, base, root, f: pathlib.Path, title, desc, mode, email):
    import re as _re
    page.goto(EPISODES.get("url") or f"{base}/episodes", wait_until="domcontentloaded")
    new = _first(page, [lambda p: p.get_by_role("link", name=_re.compile(r"new episode", _re.I)),
                        lambda p: p.get_by_role("button", name=_re.compile(r"new episode", _re.I)),
                        lambda p: p.get_by_text(_re.compile(r"^\s*new episode\s*$", _re.I))], 8000)
    if new:
        new.click()
    else:
        raise RuntimeError(f"No 'New Episode' button on the Episodes page (screenshot: {_debug(root, page, 'no new episode')}).")
    page.wait_for_load_state("domcontentloaded")
    t = _first(page, [lambda p: p.get_by_label(_re.compile(r"^\s*title", _re.I)),
                      lambda p: p.locator("input[name*='title' i]"),
                      lambda p: p.get_by_placeholder(_re.compile(r"title", _re.I))], 10000)
    if not t:
        raise RuntimeError(f"No Title field on the New Episode page (screenshot: {_debug(root, page, 'no title field')}).")
    t.fill(title)
    if desc:
        d = _first(page, [lambda p: p.get_by_label(_re.compile(r"description|summary|show notes", _re.I)),
                          lambda p: p.locator("textarea[name*='description' i], textarea[name*='summary' i]"),
                          lambda p: p.locator("trix-editor, [contenteditable='true']")], 3000)
        if d:
            try:
                d.fill(desc)
            except Exception:
                try:
                    d.click()
                    page.keyboard.type(desc)
                except Exception:
                    pass
    inputs = page.locator("input[type=file]")
    pick = None
    for i in range(inputs.count()):
        acc = (inputs.nth(i).get_attribute("accept") or "").lower()
        if any(k in acc for k in ("audio", "mp3", "mpeg")):
            pick = inputs.nth(i)
            break
    if pick is None and inputs.count():
        pick = inputs.first
    if pick is None:
        raise RuntimeError(f"No audio upload field (screenshot: {_debug(root, page, 'no audio field')}).")
    pick.set_input_files(str(f))
    _say(f"  uploading {f.name} ({f.stat().st_size / 1e6:.1f} MB)…")
    time.sleep(3)
    deadline = time.time() + 20 * 60
    while time.time() < deadline:  # wait for the upload to finish: no "uploading" / percentage text left on the page
        try:
            txt = page.locator("body").inner_text(timeout=5000).lower()
        except Exception:
            txt = ""
        if not re.search(r"uploading|processing|\b\d{1,2}(\.\d)?\s?%", txt):
            break
        time.sleep(3)
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    if mode == "publish":
        b = _first(page, [lambda p: p.get_by_role("button", name=_re.compile(r"publish\s*/\s*schedule", _re.I)),
                          lambda p: p.get_by_role("button", name=_re.compile(r"^\s*publish", _re.I))], 8000)
        if not b:
            raise RuntimeError(f"No 'Publish / Schedule' button (screenshot: {_debug(root, page, 'no publish button')}).")
        b.click()
        box = _first(page, [lambda p: p.get_by_label(_re.compile(r"email subscribers", _re.I))], 4000)
        if box:
            try:
                box.set_checked(bool(email))
            except Exception:
                pass
        go = _first(page, [lambda p: p.get_by_role("button", name=_re.compile(r"publish episode", _re.I))], 8000)
        if not go:
            raise RuntimeError(f"No 'Publish Episode' button (screenshot: {_debug(root, page, 'no publish episode')}).")
        go.click()
    else:
        b = _first(page, [lambda p: p.get_by_role("button", name=_re.compile(r"save as draft", _re.I)),
                          lambda p: p.get_by_text(_re.compile(r"^\s*save as draft\s*$", _re.I)),
                          lambda p: p.get_by_role("button", name=_re.compile(r"^\s*save", _re.I))], 8000)
        if not b:
            raise RuntimeError(f"No 'Save as draft' button (screenshot: {_debug(root, page, 'no draft button')}).")
        b.click()
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(2)
    err = _first(page, [lambda p: p.locator(".alert-danger, .error, [role=alert]").filter(has_text=_re.compile(r"error|can't|cannot|required|invalid", _re.I))], 1500)
    if err:
        raise RuntimeError(f"Supercast showed an error: {err.inner_text()[:200]} (screenshot: {_debug(root, page, 'error after save')}).")


def upload(root: pathlib.Path, sup: pathlib.Path, settings: dict, names: list, keep_open_on_error=True):
    """Upload the given MP3 file names (in Topic Log Data/audio) through the browser. Runs in a thread."""
    token, site = settings.get("supercast_token"), (settings.get("supercast_site") or "").strip()
    mode, email = settings.get("supercast_mode") or "draft", bool(settings.get("supercast_email"))
    site = re.sub(r"^https?://", "", site).split(".supercast")[0].strip("/")
    if not site:
        raise RuntimeError("Set the Supercast site first (the part before .supercast.com, e.g. metrixxjocelyn).")
    base = os.environ.get("TOPICLOG_SC_BASE") or f"https://{site}.supercast.com/dashboard"  # env: a test page
    info = {r["file"]: r for r in check(root, token)["files"]}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        raise RuntimeError("The browser helper (playwright) is not installed. Mac: quit and open Topic Log again (it installs it "
                           "on start, needs internet once).") from None
    done, failed = [], []
    with sync_playwright() as p:
        ctx = _launch(p, sup / "supercast-browser")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _login(page, base)
            for n in names:
                f = root / "audio" / pathlib.Path(n).name
                if not f.exists():
                    _say(f"✗ {n}: file not found")
                    failed.append(n)
                    continue
                r = info.get(f.name) or {}
                title = r.get("title") or default_title(f.stem)
                _say(f"→ {title}  ({'draft' if mode != 'publish' else 'publish now'})")
                try:
                    _one(page, base, root, f, title, r.get("description") or "", mode, email)
                    rec = _record(root)
                    rec[f.name] = {"status": "uploaded", "at": _now(), "title": title, "mode": mode}
                    _save_record(root, rec)
                    done.append(n)
                    _say(f"✓ {title}")
                except Exception as e:
                    failed.append(n)
                    _say(f"✗ {title}: {e}")
            if token and done:
                time.sleep(3)
                titles = {_norm(e.get("title")) for e in remote_episodes(token)}
                for n in done:
                    t = (info.get(n) or {}).get("title") or default_title(pathlib.Path(n).stem)
                    _say(("  on Supercast: " if _norm(t) in titles else "  not listed by the API yet: ") + t)
        finally:
            if failed and keep_open_on_error:
                _say("The browser stays open so you can finish by hand; close it when done.")
                try:
                    page.wait_for_event("close", timeout=30 * 60 * 1000)
                except Exception:
                    pass
            try:
                ctx.close()
            except Exception:
                pass
    return done, failed


def run_async(root, sup, settings, names, auto=False):
    """Start an upload in the background; False if one is already running."""
    with _lock:
        if state["running"]:
            return False
        state.update(running=True, error=None, started=_now(), log=[])

    def go():
        try:
            _say(f"{'Scheduled upload' if auto else 'Upload'}: {len(names)} file(s)")
            done, failed = upload(root, sup, settings, names, keep_open_on_error=not auto)
            state["last"] = {"at": _now(), "done": done, "failed": failed, "auto": auto}
            _say(f"Finished: {len(done)} uploaded, {len(failed)} failed.")
        except Exception as e:
            state["error"] = str(e)
            state["last"] = {"at": _now(), "done": [], "failed": names, "auto": auto, "error": str(e)}
            _say(f"Stopped: {e}")
            (sup / "last_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            state["running"] = False
    threading.Thread(target=go, daemon=True).start()
    return True


def due(settings, now_ct: dt.datetime) -> bool:
    """Scheduled upload: on, the time has come today (Chicago), and it has not run today."""
    t = settings.get("supercast_time") or ""
    if not settings.get("supercast_on") or not re.fullmatch(r"\d{1,2}:\d{2}", t):
        return False
    h, m = map(int, t.split(":"))
    if (now_ct.hour, now_ct.minute) < (h, m):
        return False
    return settings.get("supercast_last_auto") != now_ct.date().isoformat()


def auto_names(root, token, days=2):
    """What a scheduled upload sends: pending MP3s dated within the last `days` days (older ones need a click)."""
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    return [r["file"] for r in check(root, token)["files"] if r["status"] == "pending" and r["date"] >= cut]
