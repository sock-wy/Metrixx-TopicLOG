"""Step 1: when is every word of the script spoken? ElevenLabs forced alignment (audio + text -> word times)."""
from __future__ import annotations

import difflib
import re

from .util import StepError, http, multipart, paragraphs

URL = "https://api.elevenlabs.io/v1/forced-alignment"


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def run(audio: bytes, script: str, keys: dict) -> dict:
    if not keys.get("elevenlabs_api_key"):
        raise StepError("No ElevenLabs key: set it with Episode keys… in the app bar.")
    body, ct = multipart({"text": script}, {"file": ("audio.mp3", audio, "audio/mpeg")})
    try:
        r = http("POST", URL, {"xi-api-key": keys["elevenlabs_api_key"], "Content-Type": ct}, body, timeout=600)
    except StepError as e:
        if "forced_alignment" in str(e):
            raise StepError("The ElevenLabs key is missing the Forced Alignment permission. In ElevenLabs: Developers > API keys > "
                            "edit this key > turn on Forced Alignment (or make a key with it), then Retry.") from None
        raise
    spoken = [w for w in r.get("words", []) if w.get("text", "").strip()]
    if not spoken:
        raise StepError("ElevenLabs returned no word timings.")
    return words_on_script(script, spoken)


def words_on_script(script: str, spoken: list) -> dict:
    """Every script word with its paragraph and start/end time; words the aligner skipped get interpolated times."""
    paras = paragraphs(script)
    W = [{"t": t, "p": pi} for pi, p in enumerate(paras) for t in p.split()]
    S = [{"t": w["text"].strip(), "s": float(w["start"]), "e": float(w["end"])} for w in spoken]
    sm = difflib.SequenceMatcher(None, [_norm(w["t"]) for w in W], [_norm(w["t"]) for w in S], autojunk=False)
    for m in sm.get_matching_blocks():
        for k in range(m.size):
            W[m.a + k]["s"], W[m.a + k]["e"] = S[m.b + k]["s"], S[m.b + k]["e"]
    matched = sum("s" in w for w in W)
    i, n, end = 0, len(W), S[-1]["e"]
    while i < n:
        if "s" in W[i]:
            i += 1
            continue
        j = i
        while j < n and "s" not in W[j]:
            j += 1
        t0 = W[i - 1]["e"] if i else 0.0
        t1 = W[j]["s"] if j < n else end
        for k in range(i, j):
            W[k]["s"] = round(t0 + (t1 - t0) * (k - i) / (j - i), 3)
            W[k]["e"] = round(t0 + (t1 - t0) * (k - i + 1) / (j - i), 3)
        i = j
    return {"words": W, "paragraphs": paras, "duration": round(max(end, W[-1]["e"]) + 0.6, 2),
            "matched": matched, "total": n}


def find(words: list, phrase: str, after: float = 0.0):
    """Start time of the first place at or after `after` where the phrase is spoken (loose match), else None."""
    want = [_norm(x) for x in str(phrase or "").split() if _norm(x)][:8]
    if not want:
        return None
    toks = [_norm(w["t"]) for w in words]
    for k in range(len(words) - len(want) + 1):
        if words[k]["s"] + 1e-6 < after:
            continue
        if all(want[j] == toks[k + j] or (len(want[j]) > 3 and toks[k + j].startswith(want[j])) for j in range(len(want))):
            return words[k]["s"]
    # fall back to the longest matching prefix of the phrase
    for L in range(len(want) - 1, 1, -1):
        r = find(words, " ".join(want[:L]), after)
        if r is not None:
            return r
    return None
