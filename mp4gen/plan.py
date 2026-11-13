"""Step 2: Claude plans the scenes (types, numbers, the phrase each scene starts at)."""
from __future__ import annotations

import json
import pathlib
import re

from .util import StepError, http

PROMPT = pathlib.Path(__file__).with_name("plan_prompt.md")
TYPES = {"title", "cards", "bars", "range", "price", "list", "quote", "signoff"}


def run(script: str, keys: dict, digest: dict | None = None, note: str = "", previous: dict | None = None) -> dict:
    if not keys.get("anthropic_api_key"):
        raise StepError("No Anthropic key: set it with Episode keys… in the app bar.")
    user = "SCRIPT\n\n" + script
    if digest:
        slim = {k: digest.get(k) for k in ("run", "top", "briefing") if k in digest}
        user += "\n\nTOPIC LOG DIGEST (JSON)\n" + json.dumps(slim, ensure_ascii=False)[:60000]
    if previous:
        user += "\n\nPREVIOUS PLAN (revise it)\n" + json.dumps(previous, ensure_ascii=False)
    if note:
        user += "\n\nCHANGES REQUESTED BY THE PRODUCER\n" + note
    body = {"model": keys.get("claude_model") or "claude-sonnet-5-5", "max_tokens": 8000,
            "system": PROMPT.read_text(encoding="utf-8"), "messages": [{"role": "user", "content": user}]}
    r = http("POST", "https://api.anthropic.com/v1/messages",
             {"x-api-key": keys["anthropic_api_key"], "anthropic-version": "2023-06-01"}, body, timeout=300)
    text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise StepError("Claude did not return a plan.")
    try:
        plan = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise StepError(f"The plan is not valid JSON ({e}).") from None
    return check(plan)


def check(plan: dict) -> dict:
    sc = [s for s in plan.get("scenes", []) if isinstance(s, dict) and s.get("type") in TYPES]
    if len(sc) < 3:
        raise StepError("The plan has fewer than three usable scenes.")
    if sc[0]["type"] != "title":
        sc.insert(0, {"type": "title", "anchor": "", "ticker": plan.get("ticker", ""), "title": plan.get("title", "")})
    plan["scenes"] = sc
    plan.setdefault("slug", "mycast_" + (plan.get("date") or "episode") + "_" + re.sub(r"[^A-Za-z0-9]", "", plan.get("ticker") or "X"))
    plan["slug"] = re.sub(r"[^A-Za-z0-9_.-]", "_", plan["slug"])
    return plan
