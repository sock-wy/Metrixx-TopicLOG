"""Summarise every parquet file under data/ into data/CATALOG.md (rows, columns, time range, keys)."""
import pathlib
import pandas as pd

D = pathlib.Path(__file__).resolve().parents[2] / "data" / "backfill"
KEYS = ["topic", "symbol", "event", "market", "market_id", "series"]
lines = ["# Backfill catalog", "",
         "| File | Rows | Size | From | To | Distinct | Columns |", "|---|---|---|---|---|---|---|"]
for p in sorted(D.rglob("*.parquet")):
    df = pd.read_parquet(p)
    ts = next((c for c in ("ts", "close_time") if c in df.columns), None)
    lo = hi = ""
    if ts is not None and len(df):
        t = pd.to_datetime(df[ts], utc=True, errors="coerce")
        lo, hi = f"{t.min():%Y-%m-%d %H:%M}", f"{t.max():%Y-%m-%d %H:%M}"
    dist = ", ".join(f"{k} {df[k].nunique()}" for k in KEYS if k in df.columns)
    lines.append(f"| {p.relative_to(D)} | {len(df):,} | {p.stat().st_size/1e6:.1f} MB | {lo} | {hi} | {dist} | {', '.join(df.columns)} |")
(D / "CATALOG.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
