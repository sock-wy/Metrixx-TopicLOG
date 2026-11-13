"""Step 6: upload the files to Shotstack (Ingest API), render the edit, download the MP4.
shotstack_env: "stage" (sandbox key, free, watermarked) or "v1" (production key, uses credits)."""
from __future__ import annotations

import pathlib
import time
import urllib.request

from .util import StepError, http, read_json, write_json

API = "https://api.shotstack.io"


def _h(keys):
    if not keys.get("shotstack_api_key"):
        raise StepError("No Shotstack key: set it with Episode keys… in the app bar.")
    return {"x-api-key": keys["shotstack_api_key"], "Accept": "application/json"}


def upload(path: pathlib.Path, keys: dict, cache: pathlib.Path) -> str:
    """Upload once per file (cached by name + size); returns the hosted URL."""
    env = keys.get("shotstack_env", "stage")
    done = read_json(cache, {})
    tag = f"{env}:{path.name}:{path.stat().st_size}"
    if tag in done:
        return done[tag]
    up = http("POST", f"{API}/ingest/{env}/upload", _h(keys), {})["data"]
    urllib.request.urlopen(urllib.request.Request(up["attributes"]["url"], data=path.read_bytes(), method="PUT"), timeout=600).read()
    for _ in range(100):
        a = http("GET", f"{API}/ingest/{env}/sources/{up['id']}", _h(keys))["data"]["attributes"]
        if a.get("status") == "ready":
            done[tag] = a["source"]
            write_json(cache, done)
            return a["source"]
        if a.get("status") == "failed":
            raise StepError(f"Shotstack could not take {path.name}.")
        time.sleep(3)
    raise StepError(f"Upload of {path.name} timed out.")


def render(edit: dict, keys: dict, out: pathlib.Path, progress=lambda s: None) -> str:
    env = keys.get("shotstack_env", "stage")
    r = http("POST", f"{API}/edit/{env}/render", _h(keys), edit)
    rid = r["response"]["id"]
    progress(f"render {rid} queued")
    for _ in range(360):
        s = http("GET", f"{API}/edit/{env}/render/{rid}", _h(keys))["response"]
        progress(f"render {s['status']}")
        if s["status"] == "done":
            urllib.request.urlretrieve(s["url"], out)
            return rid
        if s["status"] == "failed":
            raise StepError("Shotstack render failed: " + str(s.get("error")))
        time.sleep(5)
    raise StepError("The render took longer than 30 minutes.")
