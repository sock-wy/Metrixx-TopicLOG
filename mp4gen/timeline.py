"""Step 5: the Shotstack timeline. Each scene image starts when its anchor phrase is spoken and lasts until the next;
captions follow the voice word by word (the spoken disclaimer is shown on the sign-off scene instead)."""
from __future__ import annotations

from . import align

INTER = "UcCo3FwrK3iLTfvlaQc78lA2"
FONTS = [{"src": "https://fonts.gstatic.com/s/inter/v20/UcCo3FwrK3iLTfvlaQc78lA2.ttf"}]
BG = "#14161D"


def scene_times(plan: dict, words: list, duration: float) -> list:
    """[(start, end)] per scene, in order; a missing anchor falls back to an even split between its neighbours."""
    n = len(plan["scenes"])
    st = [None] * n
    st[0] = 0.0
    last = 0.0
    for i, s in enumerate(plan["scenes"][1:], 1):
        t = align.find(words, s.get("anchor", ""), after=last + 0.5)
        if t is not None:
            st[i] = t
            last = t
    known = [i for i in range(n) if st[i] is not None]
    for i in range(n):
        if st[i] is None:
            a = max(k for k in known if k < i)
            b = min([k for k in known if k > i] or [None], key=lambda x: x if x is not None else 1e9)
            tb = st[b] if b is not None else duration - 4
            st[i] = st[a] + (tb - st[a]) * (i - a) / ((b if b is not None else n) - a)
    return [(round(st[i], 2), round(st[i + 1] if i + 1 < n else duration, 2)) for i in range(n)]


def captions(words: list, until: float) -> list:
    W = [w for w in words if w["s"] < until]
    chunks, cur = [], []
    for k, x in enumerate(W):
        cur.append(x)
        line = " ".join(c["t"] for c in cur)
        nx = W[k + 1] if k + 1 < len(W) else None
        sent, comma = x["t"][-1] in ".?!", x["t"][-1] in ",:;"
        if nx is None or nx["p"] != x["p"] or (sent and len(line) >= 18) or (comma and len(line) >= 48) or len(line) >= 72:
            chunks.append(cur)
            cur = []
    caps = []
    for k, c in enumerate(chunks):
        s, e = c[0]["s"], c[-1]["e"] + 0.15
        if k + 1 < len(chunks):
            nx = chunks[k + 1][0]["s"]
            e = nx if nx - e < 1.0 else max(e, s + 0.9)
        caps.append((round(s, 2), round(e, 2), " ".join(x["t"] for x in c)))
    return caps


def srt(caps):
    f = lambda v: f"{int(v // 3600):02}:{int(v % 3600 // 60):02}:{int(v % 60):02},{int(round((v % 1) * 1000)) % 1000:03}"
    return "".join(f"{k + 1}\n{f(s)} --> {f(e)}\n{c}\n\n" for k, (s, e, c) in enumerate(caps))


def build(plan: dict, aligned: dict, image_urls: list, voice_url: str) -> tuple[dict, list, list]:
    words, dur = aligned["words"], aligned["duration"]
    times = scene_times(plan, words, dur)
    signoff = next((t[0] for s, t in zip(plan["scenes"], times) if s["type"] == "signoff"), dur)
    scenes = [{"asset": {"type": "image", "src": u}, "start": a, "length": round(max(b - a, 0.5), 2), "fit": "cover",
               "transition": {"in": "fade", "out": "fade"} if k else {"out": "fade"}}
              for k, (u, (a, b)) in enumerate(zip(image_urls, times))]
    caps = captions(words, signoff)
    capclips = [{"asset": {"type": "rich-text", "text": c, "font": {"family": INTER, "size": 40, "weight": "600", "color": "#FFFFFF"},
                           "style": {"lineHeight": 1.2}, "align": {"horizontal": "center", "vertical": "middle"},
                           "background": {"color": "#000000", "opacity": 0.55, "borderRadius": 10}},
                 "start": s, "length": round(e - s - 0.01, 2), "width": 1560, "height": 110, "position": "topLeft",
                 "offset": {"x": round(180 / 1920, 4), "y": round(-868 / 1080, 4)}} for s, e, c in caps]
    footer = {"asset": {"type": "rich-text", "text": "MYCAST · metrixx.ai · Education only, not investment advice",
                        "font": {"family": INTER, "size": 24, "weight": "500", "color": "#FFFFFF", "opacity": 0.8},
                        "align": {"horizontal": "left", "vertical": "middle"}},
              "start": 0, "length": dur, "width": 1680, "height": 40, "position": "topLeft",
              "offset": {"x": round(120 / 1920, 4), "y": round(-1000 / 1080, 4)}}
    edit = {"timeline": {"background": BG, "fonts": FONTS,
                         "tracks": [{"clips": capclips}, {"clips": [footer]}, {"clips": scenes},
                                    {"clips": [{"asset": {"type": "audio", "src": voice_url, "volume": 1}, "start": 0, "length": dur}]}]},
            "output": {"format": "mp4", "size": {"width": 1920, "height": 1080}, "fps": 25}}
    return edit, times, caps
