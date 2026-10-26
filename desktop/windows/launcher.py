"""Entry point of TopicLog.exe (Windows).

    TopicLog.exe                      start the app (server, scheduler, window)
    TopicLog.exe --selftest OUT.json  check the bundle and run one real pull without an Adanos key (used by CI)
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import traceback


def selftest(out: str) -> None:
    res: dict = {}
    try:
        import server  # creates the data folder under %APPDATA%

        base = server.APP
        res["web"] = (base / "web" / "index.html").is_file()
        res["d3"] = (base / "web" / "d3.min.js").is_file()
        res["config"] = (base / "config" / "weights_w0.yaml").is_file()
        res["universe"] = (base / "dashboard" / "adanos_universe.json").is_file()
        import zoneinfo

        zoneinfo.ZoneInfo("America/New_York")
        res["tz"] = True
        try:
            import webview  # noqa: F401

            res["webview"] = True
        except Exception as e:  # the app falls back to an Edge app window
            res["webview"] = repr(e)
        from dashboard import pipeline

        d = pathlib.Path(tempfile.mkdtemp())
        row = pipeline.run(d, d, adanos_key=None)
        res["pull"] = {k: row.get(k) for k in ("run_et", "topics", "scored", "gated", "pick_top", "kalshi", "prices",
                                               "polymarket_status", "us_stocks_status", "perps_rows")}
        res["files"] = sorted(p.name for p in d.glob("*.json"))
        dg = d / "claude_digest.json"
        res["digest"] = dg.is_file() and dg.stat().st_size > 1000
        res["ok"] = all(res[k] is True for k in ("web", "d3", "config", "universe", "tz", "digest")) and bool(row.get("topics"))
    except Exception:
        res["ok"] = False
        res["error"] = traceback.format_exc()
    pathlib.Path(out).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    else:
        import server

        server.main()
