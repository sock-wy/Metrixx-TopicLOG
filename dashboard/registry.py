"""Automatic topic assignment for anything that arrives as free text or a ticker.

Every item from every source must end up under a topic, without manual work:
  1. a ticker we know (US stocks from the Nasdaq screener, crypto from the exchanges)  -> that ticker's topic
  2. a phrase that names a known topic (macro terms, indices, commodities, crypto, private
     companies, large US companies by name)                                              -> that topic
  3. nothing matched                                                                      -> a new topic made from the item itself

Topics created at run time are registered in symbols.EXTRA so topic_info() can describe them.
"""
from __future__ import annotations

import re

from .symbols import ALIASES, CRYPTO, ETF_TOPIC, EXTRA, TOPICS

# company names that are ordinary words: never matched by name, only by ticker
STOP_NAMES = {
    "target", "block", "snap", "visa", "gap", "match", "clear", "dave", "chewy", "shell", "ford", "oracle", "booking",
    "general", "american", "first", "united", "southern", "public", "global", "international", "national", "the",
    "news", "fox", "domino", "carnival", "progressive", "eagle", "harmony", "summit", "core", "life", "power", "energy",
    "trade", "trust", "bank", "capital", "union", "pioneer", "premier", "liberty", "frontier", "pinnacle", "spirit",
    "vital", "ally", "aflac", "cboe", "nasdaq", "dow", "intuit", "unity", "rocket", "lumen", "edison", "exelon", "ameren",
}
SUFFIX = re.compile(r"(,|\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|Ltd\.?|Limited|plc|PLC|Holdings?|Group|N\.V\.|S\.A\.|"
                    r"Common Stock|Class [A-C]|Ordinary Shares|American Depositary|Platforms|Technologies|Technology|Systems|Incorporated)\b).*$")
MACRO_TAGS = {"Fed Rates", "Economy", "Economic Policy", "Macro Indicators", "US CPI", "Fed", "Inflation", "Recession", "Tariffs"}


def clean_name(name: str) -> str:
    n = SUFFIX.sub("", (name or "").strip())
    return n.strip(" .,&")


class Registry:
    def __init__(self, us_stocks=(), crypto_symbols=(), crypto_names=None):
        self.tickers = {}      # ticker -> topic
        self.names = {}        # ticker -> company name
        self.phrases = []      # (phrase, topic, case_sensitive, class hint)
        for t, (name, ac, yh, ad) in TOPICS.items():
            if ac == "equity":
                self.tickers[t] = t
        for r in us_stocks:
            sym = (r.get("symbol") or "").strip().upper()
            if sym and "^" not in sym and "/" not in sym:
                self.tickers.setdefault(sym, sym)
                self.names[sym] = clean_name(r.get("name"))
        self.tickers.update(ETF_TOPIC)
        self.crypto = {c.upper() for c in crypto_symbols} | set(CRYPTO)
        for topic, words in ALIASES.items():
            for w in words:
                self.phrases.append((w, topic, w[:1].isupper() or w.isupper(), None))
        for sym, nm in (crypto_names or {}).items():
            if nm and len(nm) >= 4 and nm.lower() not in STOP_NAMES:
                self.phrases.append((nm, sym.upper(), True, "crypto"))
        big = sorted([r for r in us_stocks if r.get("market_cap")], key=lambda r: -r["market_cap"])[:1500]
        for r in big:
            nm = clean_name(r.get("name"))
            if len(nm) >= 4 and nm.lower() not in STOP_NAMES and nm.split()[0].lower() not in STOP_NAMES:
                self.phrases.append((nm, r["symbol"].strip().upper(), True, "equity"))
        self.phrases.sort(key=lambda x: -len(x[0]))  # longest phrase wins
        self._re = [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(p) + r"(?![A-Za-z0-9])", 0 if cs else re.I), t, c)
                    for p, t, cs, c in self.phrases]

    def match(self, text: str):
        """(topic, method, class hint) for free text, or (None, None, None)."""
        if not text:
            return None, None, None
        for m in re.finditer(r"\$([A-Z]{1,5})\b|\(([A-Z]{1,5})\)", text):
            t = m.group(1) or m.group(2)
            if t in self.tickers:
                tt = self.tickers[t]
                return tt, "ticker", (None if tt in TOPICS else "equity")
            if t in self.crypto:
                return t, "ticker", "crypto"
        best = None
        for rx, topic, cls in self._re:
            mm = rx.search(text)
            if mm and (best is None or mm.start() < best[0]):
                best = (mm.start(), topic, cls)
        if best:
            return best[1], "name", best[2]
        return None, None, None

    def assign(self, text: str, tags=(), new_id: str = "", fallback_class: str = "theme"):
        """Topic for an item; creates a new topic from the item itself when nothing matches."""
        topic, how, cls_hint = self.match(text)
        if topic:
            ensure(topic, cls_hint, self.names.get(topic))
            return topic, how
        cls = fallback_class
        tags = set(tags or ())
        if tags & MACRO_TAGS:
            cls = "macro"
        elif {"Crypto", "Crypto Prices"} & tags:
            cls = "crypto"
        elif "Commodities" in tags:
            cls = "commodity"
        EXTRA[new_id] = (text[:90], cls, None, None)
        return new_id, "new"


def ensure(topic: str, cls_hint: str | None = None, name: str | None = None):
    """Make sure a topic id that came from a ticker is described (equity or crypto)."""
    if topic in TOPICS or topic in EXTRA:
        return
    if cls_hint == "crypto":
        EXTRA[topic] = (name or topic, "crypto", f"{topic}-USD", ("crypto", topic))
    else:
        EXTRA[topic] = (name or topic, "equity", topic.replace(".", "-"), ("stocks", topic))
