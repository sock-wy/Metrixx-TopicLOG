"""Fill the Kalshi perps columns on 2_topic_log (WO-TOPICLOG-ALERTS-01, step 4).

    python -m workbook.fill_perps --workbook TOPICLOG_MERGED_v0_5.xlsm --date 2026-10-13
    python -m workbook.fill_perps --workbook ... --date 2026-10-13 --tickers GOLD SILVER BTC --create
    python -m workbook.fill_perps --workbook ... --dry-run

Default: every ticker that already has a row for --date gets its three perp columns filled.
--create also appends a (ticker, date) row for --tickers that have none yet.
--asof defaults to now (UTC); for a 15:00 ET pick, pass that time so nothing later is used.
A copy of the workbook is saved as <name>.bak<ext> before writing. Close the file in Excel first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

from scoring import perp_fields
from workbook.sheet import Sheet, SheetError, open_book, save_book

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHEET = "2_topic_log"


def run(workbook, date, asof, cfg, tickers=None, create=False, dry_run=False, fetch=None, log=print):
    wb = open_book(workbook)
    if SHEET not in wb.sheetnames:
        raise SheetError(f"no {SHEET} tab in {workbook}")
    sh = Sheet(wb[SHEET])
    present = sorted({t for _, t, d in sh.rows() if d == date})
    todo = list(dict.fromkeys((tickers or []) + ([] if tickers else present)))
    report = []
    for tk in todo:
        if tk not in present and not create:
            log(f"{tk}: no row for {date}; skipped (use --create)")
            continue
        vals = perp_fields.compute(tk, asof, cfg, fetch=fetch)
        cells = {k: vals[k] for k in perp_fields.FIELDS}
        if not dry_run:
            action, row, _ = sh.upsert(tk, date, cells)
        else:
            action, row = "dry-run", sh.find(tk, date)
        report.append((tk, vals.get("perp_ticker"), action, row, cells))
        shown = ", ".join(f"{k}={'' if v is None else round(v, 6)}" for k, v in cells.items())
        log(f"{tk:8s} {str(vals.get('perp_ticker') or '-'):16s} {action:8s} row {row}: {shown}")
    if not dry_run and report:
        save_book(wb, workbook)
        log(f"saved {workbook}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--date", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    ap.add_argument("--asof", type=lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00")),
                    default=dt.datetime.now(dt.timezone.utc))
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config" / "perps.yaml"))
    a = ap.parse_args(argv)
    if a.asof.tzinfo is None:
        ap.error("--asof needs a time zone, e.g. 2026-10-13T19:00:00Z")
    try:
        run(a.workbook, a.date, a.asof, perp_fields.load_config(a.config), a.tickers, a.create, a.dry_run)
    except SheetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
