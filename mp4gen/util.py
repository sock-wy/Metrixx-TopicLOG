"""Shared helpers: HTTP without extra packages, keys, script parsing."""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import uuid
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) TopicLog/1.2"


class StepError(RuntimeError):
    pass


def http(method, url, headers=None, body=None, timeout=120, raw=False):
    """JSON in, JSON out (or bytes with raw=True). Raises StepError with the server's message."""
    h = {"User-Agent": UA, **(headers or {})}
    data = None
    if body is not None and not isinstance(body, (bytes, bytearray)):
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = bytes(body)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            return b if raw else (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        msg = e.read()[:600].decode("utf-8", "replace")
        raise StepError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise StepError(f"{method} {url.split('?')[0]} -> {e.reason}") from None


def multipart(fields: dict, files: dict):
    """fields: name -> str; files: name -> (filename, bytes, content type). Returns (body, content type)."""
    b = "----mp4gen" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{b}\r\n".encode(), f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(), str(v).encode(), b"\r\n"]
    for k, (fn, data, ct) in files.items():
        out += [f"--{b}\r\n".encode(), f'Content-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'.encode(),
                f"Content-Type: {ct}\r\n\r\n".encode(), data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def load_keys(*paths) -> dict:
    """keys.json files (first wins per key), then environment variables, then ~/.shotstack/credentials.json."""
    k = {}
    for p in paths:
        try:
            for a, v in json.loads(pathlib.Path(p).read_text(encoding="utf-8-sig")).items():
                if v not in (None, "") and a not in k:
                    k[a] = v
        except Exception:
            pass
    env = {"ANTHROPIC_API_KEY": "anthropic_api_key", "ELEVENLABS_API_KEY": "elevenlabs_api_key",
           "SHOTSTACK_API_KEY": "shotstack_api_key", "SHOTSTACK_ENV": "shotstack_env"}
    for e, a in env.items():
        if os.environ.get(e) and not k.get(a):
            k[a] = os.environ[e]
    if not k.get("shotstack_api_key"):
        try:
            c = json.loads((pathlib.Path.home() / ".shotstack" / "credentials.json").read_text())
            if c.get("v1"):
                k["shotstack_api_key"] = c["v1"]
                k["shotstack_env"] = k.get("shotstack_env") or "v1"
        except Exception:
            pass
    k.setdefault("shotstack_env", "stage")
    k.setdefault("claude_model", "claude-sonnet-5-5")
    return k


def script_text(raw: str) -> str:
    """The spoken script from a .md / .txt: the '## Script' section if there is one, else the whole text,
    without markdown headings, bullets or emphasis."""
    m = re.search(r"^##\s*Script\s*$(.*?)(?=^##\s|\Z)", raw, re.S | re.M | re.I)
    t = m.group(1) if m else raw
    lines = []
    for ln in t.replace("\r\n", "\n").split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        ln = re.sub(r"^\s*[-*]\s+", "", ln)
        ln = re.sub(r"[*_`]+", "", ln)
        lines.append(ln.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def paragraphs(script: str) -> list:
    return [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def read_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")
