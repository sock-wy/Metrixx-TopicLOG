"""MYCAST episodes in the Topic Log app: digest -> Claude draft (with web search) -> review -> ElevenLabs MP3.

Flow (same as the mydesk-bot, without Rocket.Chat): draft -> edit / regenerate -> approve -> make audio.
Keys live in keys.json in the support folder (mode 600), never in the repo or the app bundle.
Each episode is a folder under <support>/episodes/<id>/ with episode.json (all versions) and, once made, the MP3.
The writing instructions are episode_prompt.md: the copy in the support folder wins, so it can be edited
without a rebuild; otherwise the one shipped with the app is used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import threading
import traceback
import urllib.error
import urllib.request

SUP = DATA = APP = EXE_DIR = None
OUT_DIR = None  # set by server.py: kind -> folder in ~/Desktop/Topic Log Data/
EPI = KEYS = None
KEY_FIELDS = ("anthropic_api_key", "elevenlabs_api_key", "elevenlabs_voice_id")
DEFAULT_KEYS = {"anthropic_api_key": "", "elevenlabs_api_key": "", "elevenlabs_voice_id": "",
                "claude_model": "claude-sonnet-5-5", "elevenlabs_model": "eleven_multilingual_v2"}
CLAUDE_MODEL = "claude-sonnet-5-5"  # scripts are always written with Sonnet (Nov 3), whatever an older keys.json says
_lock = threading.Lock()
_busy = {}  # episode id -> "drafting" | "audio"


def init(sup, data, app, exe_dir):
    global SUP, DATA, APP, EXE_DIR, EPI, KEYS
    SUP, DATA, APP, EXE_DIR = sup, data, app, exe_dir
    EPI = SUP / "episodes"
    EPI.mkdir(parents=True, exist_ok=True)
    KEYS = SUP / "keys.json"
    # every start: a keys.json placed next to the app fills any key the support folder does not have yet
    # (keys saved with Episode keys… are kept; then they live in the support folder)
    near = [EXE_DIR, APP] + ([APP.parents[3]] if len(APP.parents) > 3 else [])  # .exe folder; folder holding Topic Log.app
    for f in [d / "keys.json" for d in near]:
        try:
            k = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        have = load_keys()
        missing = {a: b for a, b in k.items() if a in KEY_FIELDS and not have.get(a)}
        if missing or not KEYS.exists():
            save_keys(missing)
        break


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ keys
def load_keys():
    k = dict(DEFAULT_KEYS)
    try:
        k.update({a: b for a, b in json.loads(KEYS.read_text(encoding="utf-8-sig")).items() if b not in (None, "")})
    except Exception:
        pass
    k["claude_model"] = CLAUDE_MODEL
    return k


def save_keys(new):
    k = load_keys()
    for f in (*KEY_FIELDS, "claude_model", "elevenlabs_model"):
        v = new.get(f)
        if isinstance(v, str) and v.strip():
            k[f] = v.strip()
    KEYS.write_text(json.dumps(k, indent=1))
    try:
        os.chmod(KEYS, 0o600)
    except OSError:
        pass


def keys_status():
    k = load_keys()
    return {f: bool(k.get(f)) for f in KEY_FIELDS} | {"claude_model": k["claude_model"], "elevenlabs_model": k["elevenlabs_model"],
                                                      "path": str(KEYS)}


# ------------------------------------------------------------------ storage
def _path(eid):
    if not re.fullmatch(r"[0-9A-Za-z_-]{6,64}", eid or ""):
        raise ValueError("bad episode id")
    return EPI / eid


def load(eid):
    return json.loads((_path(eid) / "episode.json").read_text(encoding="utf-8"))


def save(ep):
    p = _path(ep["id"])
    p.mkdir(parents=True, exist_ok=True)
    ep["updated"] = now()
    tmp = p / "episode.json.tmp"
    tmp.write_text(json.dumps(ep, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p / "episode.json")


def view(ep):
    out = dict(ep)
    out["busy"] = _busy.get(ep["id"])
    out["has_audio"] = bool(ep.get("audio")) and (_path(ep["id"]) / ep["audio"]["file"]).exists()
    return out


def listing():
    out = []
    for f in sorted(EPI.glob("*/episode.json"), reverse=True):
        try:
            ep = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        cur = ep["versions"][-1] if ep.get("versions") else {}
        out.append({"id": ep["id"], "created": ep.get("created"), "date": ep.get("date"), "topic": ep.get("topic"),
                    "title": cur.get("title") or ep.get("topic"), "status": ep.get("status"), "busy": _busy.get(ep["id"]),
                    "versions": len(ep.get("versions", [])), "has_audio": bool(ep.get("audio"))})
    return out


def digest():
    try:
        d = json.loads((DATA / "claude_digest.json").read_text(encoding="utf-8"))
        return d[0] if isinstance(d, list) else d
    except Exception:
        return None


def candidates():
    d = digest()
    if not d:
        return {"run": None, "top": []}
    return {"run": d.get("run"), "top": [{"rank": t.get("rank"), "topic": t.get("topic"), "name": t.get("name"),
                                          "score": t.get("score"), "catalyst": t.get("catalyst")} for t in d.get("top", [])]}


# ------------------------------------------------------------------ Claude
def prompt_text():
    for f in (SUP / "episode_prompt.md", APP / "episode_prompt.md"):
        if f.exists():
            return f.read_text(encoding="utf-8")
    raise RuntimeError("episode_prompt.md is missing")


def _post(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:400]
        try:
            msg = json.loads(msg).get("error", {}).get("message") or json.loads(msg).get("detail", {}).get("message") or msg
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {msg}") from None


def _claude(messages, keys):
    if not keys.get("anthropic_api_key"):
        raise RuntimeError("No Anthropic key. Set it with Keys… in the app bar.")
    body = {"model": keys["claude_model"], "max_tokens": 8000, "system": prompt_text(), "messages": messages,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]}
    headers = {"Content-Type": "application/json", "x-api-key": keys["anthropic_api_key"], "anthropic-version": "2023-06-01"}
    for _ in range(3):  # a long search turn can pause; continue it
        data = json.loads(_post("https://api.anthropic.com/v1/messages", headers, body, timeout=300))
        if data.get("stop_reason") != "pause_turn":
            return data
        body["messages"] = messages + [{"role": "assistant", "content": data["content"]}]
    return data


def _parse(data):
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    urls = []
    for b in data.get("content", []):
        for c in b.get("citations") or []:
            if c.get("url") and c["url"] not in [u["url"] for u in urls]:
                urls.append({"title": c.get("title") or c["url"], "url": c["url"]})
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("Claude did not return the expected JSON. Try Regenerate.")
    out = json.loads(m.group(0))
    out["script"] = re.sub(r"\n{3,}", "\n\n", str(out.get("script", "")).strip())
    seen = {s.get("url") for s in out.get("sources") or []}
    out["sources"] = (out.get("sources") or []) + [u for u in urls if u["url"] not in seen]
    out["searches"] = sum(1 for b in data.get("content", []) if b.get("type") == "server_tool_use")
    out["usage"] = data.get("usage")
    return out


def _first_message(ep, d):
    pick = (f"Cover this topic: {ep['topic']}." if ep.get("topic")
            else "Pick the topic yourself (rank 1 unless a top-3 topic has a clearly stronger story).")
    return (f"Episode date: {ep['date']} (US Eastern).\n{pick}\n"
            f"Digest from the pull of {(d.get('run') or {}).get('run_et')} ET:\n\n" + json.dumps(d, ensure_ascii=False))


def _version_from(out, source, note=None):
    return {"n": None, "at": now(), "source": source, "note": note, "title": out.get("title"), "script": out.get("script", ""),
            "why": out.get("why"), "frame": out.get("frame"), "sources": out.get("sources"), "checks": out.get("checks"),
            "topic": out.get("topic"), "name": out.get("name"), "searches": out.get("searches"), "usage": out.get("usage")}


def _add_version(ep, v):
    v["n"] = len(ep["versions"]) + 1
    ep["versions"].append(v)
    if v.get("topic"):
        ep["topic"], ep["name"] = v["topic"], v.get("name") or ep.get("name")


def _run(eid, fn):
    def work():
        try:
            fn()
        except Exception as e:
            with _lock:
                ep = load(eid)
                ep["error"] = f"{type(e).__name__}: {e}"
                ep.setdefault("log", []).append({"at": now(), "error": ep["error"], "trace": traceback.format_exc()[-1500:]})
                save(ep)
        finally:
            _busy.pop(eid, None)
    threading.Thread(target=work, daemon=True).start()


def new(topic=None):
    d = digest()
    if not d:
        raise RuntimeError("No digest yet. Pull first (the digest comes with every pull).")
    try:
        from zoneinfo import ZoneInfo
        et = dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # no tz database (some Windows Pythons): UTC-5 is close enough for a date
        et = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))
    eid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-" + re.sub(r"[^A-Za-z0-9]", "", topic)[:12] if topic else "")
    name = next((t.get("name") for t in d.get("top", []) if t.get("topic") == topic), None)
    ep = {"id": eid, "created": now(), "date": et.strftime("%Y-%m-%d"), "topic": topic, "name": name,
          "run": d.get("run"), "status": "draft", "versions": [], "messages": None, "error": None}
    save(ep)
    _busy[eid] = "drafting"

    def go():
        keys = load_keys()
        msgs = [{"role": "user", "content": _first_message(ep, d)}]
        data = _claude(msgs, keys)
        out = _parse(data)
        with _lock:
            e = load(eid)
            _add_version(e, _version_from(out, "claude"))
            e["messages"] = msgs[:1] + [{"role": "assistant", "content": json.dumps({k: out.get(k) for k in (
                "topic", "name", "why", "title", "script", "frame", "sources", "checks")}, ensure_ascii=False)}]
            e["error"] = None
            save(e)
    _run(eid, go)
    return eid


def new_pasted(title, script, topic=None):
    """An episode from a script written elsewhere (Jim's own): no Claude draft. Review, approve, then make audio."""
    script = re.sub(r"\n{3,}", "\n\n", (script or "").replace("\r\n", "\n").strip())
    if len(script) < 40:
        raise RuntimeError("Paste the full script first.")
    topic = (topic or "").strip().upper() or None
    try:
        from zoneinfo import ZoneInfo
        et = dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))
    eid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-own" + ("-" + re.sub(r"[^A-Za-z0-9]", "", topic)[:12] if topic else "")
    d = digest() or {}
    name = next((t.get("name") for t in d.get("top", []) if t.get("topic") == topic), None)
    ep = {"id": eid, "created": now(), "date": et.strftime("%Y-%m-%d"), "topic": topic, "name": name, "run": d.get("run"),
          "status": "draft", "versions": [], "messages": None, "error": None, "own_script": True}
    _add_version(ep, {"n": None, "at": now(), "source": "pasted", "note": "pasted script", "title": (title or "").strip() or None,
                      "script": script, "why": None, "frame": None, "sources": None, "checks": None, "topic": topic, "name": name,
                      "searches": None, "usage": None})
    save(ep)
    return eid


def regenerate(eid, note):
    ep = load(eid)
    if _busy.get(eid):
        raise RuntimeError("Busy; wait for the current step.")
    if not ep.get("messages"):
        raise RuntimeError("No draft to revise yet.")
    cur = ep["versions"][-1]
    _busy[eid] = "drafting"

    def go():
        keys = load_keys()
        prev = json.dumps({k: cur.get(k) for k in ("topic", "name", "why", "title", "script", "frame", "sources", "checks")},
                          ensure_ascii=False)
        msgs = ep["messages"][:1] + [{"role": "assistant", "content": prev},
                                     {"role": "user", "content": "Revision note: " + (note or "Write a fresh take; keep the facts.") +
                                      "\nReturn the full JSON object again."}]
        out = _parse(_claude(msgs, keys))
        with _lock:
            e = load(eid)
            _add_version(e, _version_from(out, "claude", note))
            e["messages"] = msgs[:1] + [{"role": "assistant", "content": json.dumps({k: out.get(k) for k in (
                "topic", "name", "why", "title", "script", "frame", "sources", "checks")}, ensure_ascii=False)}]
            e["status"], e["error"] = "draft", None
            save(e)
    _run(eid, go)


def edit(eid, title, script):
    with _lock:
        ep = load(eid)
        cur = ep["versions"][-1] if ep["versions"] else {}
        script = re.sub(r"\n{3,}", "\n\n", (script or "").replace("\r\n", "\n").strip())
        if script == cur.get("script") and (title or "") == (cur.get("title") or ""):
            return ep
        v = {**cur, "at": now(), "source": "edit", "note": None, "title": title, "script": script, "usage": None, "searches": None}
        _add_version(ep, v)
        if ep["status"] == "approved":
            ep["status"] = "draft"  # an edit after approval needs a new approval
        save(ep)
        return ep


def restore(eid, n):
    with _lock:
        ep = load(eid)
        old = next(v for v in ep["versions"] if v["n"] == int(n))
        _add_version(ep, {**old, "at": now(), "source": "restore", "note": f"restored v{old['n']}"})
        ep["status"] = "draft"
        save(ep)
        return ep


def set_status(eid, status):
    with _lock:
        ep = load(eid)
        if status == "approved":
            if not ep["versions"]:
                raise RuntimeError("Nothing to approve yet.")
            ep["approved_version"] = ep["versions"][-1]["n"]
            ep["approved_at"] = now()
        ep["status"] = status
        save(ep)
        return ep


# ------------------------------------------------------------------ ElevenLabs
def _chunks(text, limit=4500):
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > limit and cur:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def make_audio(eid):
    ep = load(eid)
    if ep["status"] not in ("approved", "audio"):
        raise RuntimeError("Approve the script first.")
    if _busy.get(eid):
        raise RuntimeError("Busy; wait for the current step.")
    keys = load_keys()
    if not (keys.get("elevenlabs_api_key") and keys.get("elevenlabs_voice_id")):
        raise RuntimeError("No ElevenLabs key or voice ID. Set them with Keys… in the app bar.")
    v = next(x for x in ep["versions"] if x["n"] == ep["approved_version"])
    _busy[eid] = "audio"

    def go():
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{keys['elevenlabs_voice_id']}"
        headers = {"xi-api-key": keys["elevenlabs_api_key"], "Content-Type": "application/json", "Accept": "audio/mpeg"}
        parts = _chunks(v["script"])
        audio = b""
        for i, part in enumerate(parts):
            body = {"text": part, "model_id": keys["elevenlabs_model"], "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
            if i:
                body["previous_text"] = parts[i - 1][-500:]
            if i < len(parts) - 1:
                body["next_text"] = parts[i + 1][:500]
            audio += _post(url, headers, body, timeout=300)
        topic = re.sub(r"[^A-Za-z0-9]", "", ep.get("topic") or "episode")
        fname = f"mycast_{ep['date']}_{topic}_v{v['n']}.mp3"
        (_path(eid) / fname).write_bytes(audio)
        copied = None
        try:
            dest = _out("audio")
            shutil.copy(_path(eid) / fname, dest / fname)
            copied = str(dest / fname)
        except Exception:
            pass
        with _lock:
            e = load(eid)
            e["audio"] = {"file": fname, "version": v["n"], "at": now(), "bytes": len(audio), "chars": len(v["script"]),
                          "downloads": copied}
            e["status"], e["error"] = "audio", None
            save(e)
    _run(eid, go)


def audio_path(eid):
    ep = load(eid)
    return _path(eid) / ep["audio"]["file"] if ep.get("audio") else None


# ------------------------------------------------------------------ export
def export(eid, fmt):
    ep = load(eid)
    v = ep["versions"][-1]
    topic = re.sub(r"[^A-Za-z0-9]", "", ep.get("topic") or "episode")
    if fmt == "txt":
        name, text = f"mycast_{ep['date']}_{topic}_v{v['n']}.txt", v["script"] + "\n"
    else:
        f = v.get("frame") or {}
        lines = [f"# {v.get('title') or topic}", "", f"{ep['date']} · {ep.get('name') or topic} ({topic}) · version {v['n']} · {ep['status']}",
                 f"Topic Log pull: {(ep.get('run') or {}).get('run_et')} ET", ""]
        if v.get("why"):
            lines += ["## Why this topic", "", v["why"], ""]
        lines += ["## Script", "", v["script"], ""]
        if f:
            lines += ["## Audio frame fields", "", f"- Tags: {', '.join(f.get('tags') or [])}", f"- Headline: {f.get('headline', '')}",
                      f"- Deck: {f.get('deck', '')}"] + [f"- Beat {i + 1}: {b}" for i, b in enumerate(f.get("beats") or [])]
            lines += [f"- Probability: {p.get('venue', '')} · {p.get('label', '')} · {p.get('prob', '')} · {p.get('note', '')}"
                      for p in f.get("probabilities") or []] + [f"- Net Read: {f.get('netread', '')}", ""]
        if v.get("checks"):
            lines += ["## Check before recording", ""] + [f"- {c}" for c in v["checks"]] + [""]
        if v.get("sources"):
            lines += ["## Sources", ""] + [f"- [{s.get('title') or s.get('url')}]({s.get('url')})" for s in v["sources"]] + [""]
        name, text = f"mycast_{ep['date']}_{topic}_v{v['n']}.md", "\n".join(lines)
    try:
        folder = _out("scripts")
    except Exception:
        folder = SUP
    (folder / name).write_text(text, encoding="utf-8")
    return str(folder / name), text


def _out(kind):
    if OUT_DIR:
        return OUT_DIR(kind)
    d = pathlib.Path.home() / "Downloads"
    if not d.is_dir():
        raise RuntimeError("no output folder")
    return d
