"""Topic Log scoring: hard gates, demand_score and priority tiers.

Implements playbook/README.md chapters 3-5. Every number comes from the config YAML
(config/weights_wN.yaml); nothing is hard-coded here.

Input: one dict per candidate ticker for one day, with these keys (None = missing):
    ticker, buzz_delta_1d, trade_count_pct_change_1d, mkt_volume_delta_1d,
    mkt_oi_delta_1d, mkt_prob_delta_1d, mkt_prob_range_1d, sentiment_delta_1d,
    avg_spread, zero_trade_market_pct, sources_available, days_since_covered,
    catalyst_in_trading_days, has_market_evidence, unique_traders, mkt_ladder_depth
Output: the surviving rows with component percentiles, quality, cooldown,
demand_score, tier and rank; gated rows carry data_quality_flag.
"""
from __future__ import annotations

import yaml

COMPONENTS = [
    "attention_shift",
    "activity_shift",
    "money_flow",
    "money_stock",
    "market_move",
    "sentiment_shift",
]


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _component_inputs(r):
    """Raw input per component, exactly as defined in config `components.*.input`."""
    pd, rng = r.get("mkt_prob_delta_1d"), r.get("mkt_prob_range_1d")
    if pd is None and rng is None:
        mm = None
    else:
        mm = max(abs(pd or 0.0), (rng or 0.0) / 2)
    sd = r.get("sentiment_delta_1d")
    return {
        "attention_shift": r.get("buzz_delta_1d"),
        "activity_shift": r.get("trade_count_pct_change_1d"),
        "money_flow": r.get("mkt_volume_delta_1d"),
        "money_stock": r.get("mkt_oi_delta_1d"),
        "market_move": mm,
        "sentiment_shift": None if sd is None else abs(sd),
    }


def pctrank(values):
    """Percentile within the pool: average rank / (n-1), ties averaged, None stays None.
    A single non-missing value gets 0.5 (matches playbook/index.html)."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    n = len(idx)
    if n == 0:
        return out
    if n == 1:
        out[idx[0]] = 0.5
        return out
    idx.sort(key=lambda i: values[i])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[idx[j + 1]] == values[idx[i]]:
            j += 1
        p = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[idx[k]] = p
        i = j + 1
    return out


def gate(r, cfg):
    g = cfg["gates"]
    if not r.get("has_market_evidence", True):
        return "G2"
    z, s = r.get("zero_trade_market_pct"), r.get("avg_spread")
    if z is not None and z > g["G3_liquidity_floor"]["max_zero_trade_market_pct"]:
        return "G3"
    if s is not None and s > g["G3_liquidity_floor"]["max_avg_spread"]:
        return "G3"
    d = r.get("days_since_covered")
    if d is not None and d <= g["G4_cooldown"]["window_days"]:
        return "G4"
    return None


def quality(r, cfg):
    q = cfg["quality"]
    s = r.get("avg_spread")
    z = r.get("zero_trade_market_pct")
    spread_f = 1.0
    if s is not None:
        spread_f = 1 - max(0.0, s - q["spread"]["free_below"]) / q["spread"]["slope_divisor"]
        spread_f = min(1.0, max(q["spread"]["floor"], spread_f))
    zero_f = 1.0 if z is None else 1 - q["zero_trade"]["penalty"] * z
    src = r.get("sources_available") or 1
    source_f = 1.0 if src >= q["sources"]["min_for_full_credit"] else q["sources"]["single_source_factor"]
    return spread_f * zero_f * source_f


def cooldown(r, cfg):
    n = cfg["gates"]["G4_cooldown"]["window_days"]
    d = r.get("days_since_covered")
    c = cfg["cooldown"]
    if d is not None and n < d <= n + c["soft_band_days"]:
        return c["soft_band_multiplier"]
    return 1.0


def tier(p, r, cfg):
    t = cfg["tiers"]
    cat = r.get("catalyst_in_trading_days")
    t1 = t["T1"]
    if cat is not None and cat <= t1["catalyst_within_trading_days"] and (
        (p.get("market_move") or 0) >= t1["any_of"]["market_move_pct_min"]
        or (p.get("money_flow") or 0) >= t1["any_of"]["money_flow_pct_min"]
    ):
        return "T1"
    t2 = t["T2"]["all_of"]
    if (p.get("money_flow") or 0) >= t2["money_flow_pct_min"] and (
        p.get("attention_shift") or 0
    ) >= t2["attention_shift_pct_min"]:
        return "T2"
    if (p.get("attention_shift") or 0) >= t["T3"]["all_of"]["attention_shift_pct_min"]:
        return "T3"
    return "T4"


def score_day(rows, cfg, weights=None, use_tiers=True):
    """Score one day's pool. Returns (ranked survivors, gated rows)."""
    weights = weights or {k: cfg["components"][k]["weight"] for k in COMPONENTS}
    gated, live = [], []
    for r in rows:
        g = gate(r, cfg)
        (gated if g else live).append(dict(r, data_quality_flag=g))
    raw_inputs = [_component_inputs(r) for r in live]
    for k in COMPONENTS:
        ranks = pctrank([x[k] for x in raw_inputs])
        for r, p in zip(live, ranks):
            r.setdefault("pct", {})[k] = p
    for r in live:
        num = den = 0.0
        for k in COMPONENTS:
            v, w = r["pct"][k], weights[k]
            if v is not None and w > 0:
                num += w * v
                den += w
        r["raw_score"] = num / den if den else 0.0
        r["quality"] = quality(r, cfg)
        r["cooldown"] = cooldown(r, cfg)
        r["demand_score"] = r["raw_score"] * r["quality"] * r["cooldown"]
        r["tier"] = tier(r["pct"], r, cfg) if use_tiers else "T4"
        r["weights_version"] = cfg["version"]
    live.sort(
        key=lambda r: (
            r["tier"],
            -r["demand_score"],
            -(r.get("sources_available") or 0),
            -(r.get("unique_traders") or 0),
            -(r.get("mkt_ladder_depth") or 0),
        )
    )
    for i, r in enumerate(live, 1):
        r["rank"] = i
    return live, gated
