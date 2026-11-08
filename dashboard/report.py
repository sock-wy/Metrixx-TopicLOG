"""PDF and Excel exports of the ranking: overall, by category, and how the ranking changed.

export(data_dir, out_dir, fmt) reads topic_log.json and rank_changes.json from data_dir and writes
topiclog_ranking_<YYYY-MM-DD_HHMM>CT.pdf or .xlsx to out_dir. Needs openpyxl (Excel) and reportlab (PDF).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from . import rankhist

DISCLAIMER = ("Topic Log ranks topics by public attention, prediction-market and price data. It describes what is "
              "being watched, not what to trade. Not investment advice.")


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _pct(v):
    return None if v is None else round(v * 100, 2)


def tables(data_dir: pathlib.Path) -> dict:
    rows = _load(data_dir / "topic_log.json", [])
    ch = (_load(data_dir / "rank_changes.json", [{}]) or [{}])[0] or {}
    run_ts = rows[0]["run_ts"] if rows else None
    top = sorted((r for r in rows if r.get("pick_rank")), key=lambda r: r["pick_rank"])
    overall = [[r["pick_rank"], r["topic"], r.get("name"), rankhist.CATEGORIES.get(r.get("asset_class"), r.get("asset_class")),
                r.get("pick_score"), r.get("pick_tier"), r.get("price"), _pct(r.get("chg_24h"))] for r in top[:50]]
    cat = [[c["category"], c["category_rank"], c["rank"], c["topic"], c["name"], c["score"], c["tier"], c["price"], _pct(c["chg_24h"])]
           for c in rankhist.by_category(rows)]

    def diff(d):
        if not d:
            return [], [], []
        return ([[e["rank"], e["topic"], e["name"], e["category"], e["prev_rank"]] for e in d["entered"]],
                [[e["prev_rank"], e["topic"], e["name"], e["category"], e["rank"]] for e in d["dropped"]],
                [[m["topic"], m["name"], m["category"], m["prev_rank"], m["rank"], m["change"]] for m in d["movers"]])
    pp, pd = ch.get("vs_prev_pull"), ch.get("vs_prev_day")
    return {
        "run_ts": run_ts, "run_ct": rankhist.to_ct(run_ts) if run_ts else "", "run_et": rankhist.to_et(run_ts) if run_ts else "",
        "changes": ch,
        "sheets": [
            ("Overall", ["Rank", "Topic", "Name", "Category", "Score", "Tier", "Price", "24h %"], overall),
            ("By category", ["Category", "Rank in category", "Overall rank", "Topic", "Name", "Score", "Tier", "Price", "24h %"], cat),
            ("Vs previous pull", None, diff(pp), pp),
            ("Vs previous day", None, diff(pd), pd),
            ("Drivers, vs day before", DRV_HEAD, _drv(ch.get("drivers_day"))),
            ("Drivers, vs pull before", DRV_HEAD, _drv(ch.get("drivers_pull"))),
            ("Four angles, vs day before", ANG_HEAD, _ang(ch.get("angles_day"))),
            ("Four angles, vs pull before", ANG_HEAD, _ang(ch.get("angles_pull"))),
            ("Top-10 streaks", ["Topic", "Name", "Category", "Rank now", "Current streak (days)", "Longest streak", "Days in top 10", "Days tracked"],
             [[s["topic"], s["name"], s["category"], s["rank_now"], s["current_streak"], s["longest_streak"], s["days_in_top"], s["days"]]
              for s in ch.get("streaks", [])]),
            ("Daily picks", ["Date", "Pull (ET)", "Pick of record", "Topic", "Name", "Category", "Score", "Rank next day"],
             [[p["date"], p["run_et"], "yes" if p["of_record"] else "no (last pull of day)", p["topic"], p["name"], p["category"], p["score"],
               p["next_day_rank"] if p["next_day_rank"] is not None else ("out of top 50" if p["has_next"] else "")]
              for p in ch.get("picks", [])]),
        ],
    }


DRV_HEAD = ["Topic", "Name", "Category", "Rank before", "Rank now", "Places", "Driven by", "Attention (pts)", "Price & volume (pts)", "Money (pts)"]
ANG_HEAD = ["Angle", "Direction", "Topic", "Name", "Before", "After", "Change", "Rank now"]
ANG_LABEL = {"attention": "Attention (x normal)", "money": "Money (OI x normal)", "price": "Price (sigma)", "sentiment": "Sentiment (-1 to 1)"}


def _drv(rows):
    return [[r["topic"], r["name"], r["category"], r["prev_rank"], r["rank"], r["places"], r["main"],
             *[round(r["by_angle"].get(k, 0) * 100, 1) for k in ("attention", "price", "money")]] for r in rows or []]


def _ang(a):
    out = []
    for k in ("attention", "money", "price", "sentiment"):
        for d, lab in (("up", "rose"), ("down", "fell")):
            for x in ((a or {}).get("angles", {}).get(k, {}).get(d) or []):
                out.append([ANG_LABEL[k], lab, x["topic"], x["name"], x["before"], x["after"], x["change"], x["rank"]])
    return out


DIFF_HEAD = (["Rank now", "Topic", "Name", "Category", "Rank before"], ["Rank before", "Topic", "Name", "Category", "Rank now"],
             ["Topic", "Name", "Category", "Rank before", "Rank now", "Places gained"])
DIFF_TITLE = ("Entered the top 10", "Left the top 10", "Biggest moves (top 20)")


def _xlsx(t, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "About"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1D1F24")
    for r in (["Topic Log ranking export"], [f"Pull: {t['run_ct']} CT ({t['run_et']} ET)"],
              [f"History: {t['changes'].get('pulls', 0)} pulls over {t['changes'].get('days', 0)} days, "
               f"{t['changes'].get('first_et', '')} to {t['changes'].get('last_et', '')} ET"],
              ["Ranking of record: pick_rank (w2). Rank changes compare the top 10."], [], [DISCLAIMER]):
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 110

    def table(ws, header, rows, start=1):
        for j, h in enumerate(header, 1):
            c = ws.cell(row=start, column=j, value=h)
            c.font, c.fill, c.alignment = head, fill, Alignment(wrap_text=True)
        for i, r in enumerate(rows, start + 1):
            for j, v in enumerate(r, 1):
                ws.cell(row=i, column=j, value=v)
        return start + len(rows) + 2

    for sheet in t["sheets"]:
        ws = wb.create_sheet(sheet[0][:31])
        if sheet[1] is None:  # a diff: three blocks
            d = sheet[3] or {}
            ws.append([f"{d.get('from_et', '–')} ET → {d.get('to_et', '–')} ET" + (f" · top-10 turnover {d['turnover']:.0%}" if d.get("turnover") is not None else "")])
            ws["A1"].font = Font(bold=True)
            row = 3
            for title, h, rows in zip(DIFF_TITLE, DIFF_HEAD, sheet[2] or ([], [], [])):
                ws.cell(row=row, column=1, value=title).font = Font(bold=True)
                row = table(ws, h, rows or [["none"]], row + 1)
        else:
            table(ws, sheet[1], sheet[2])
            ws.freeze_panes = "A2"
        for j in range(1, 11):
            ws.column_dimensions[get_column_letter(j)].width = 26 if j in (2, 3) else 14
    wb.save(path)


def _pdf(t, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=7.5, leading=9.5)
    cell = ss["BodyText"].clone("cell", fontSize=7, leading=8.5)
    headc = cell.clone("headc", textColor=colors.white, fontName="Helvetica-Bold")

    def tbl(header, rows, widths=None):
        if not rows:
            return Paragraph("None.", small)
        def num(v):
            return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.4g}"
        fmt = lambda v, st=cell: Paragraph("" if v is None else (num(v) if isinstance(v, float) else str(v)), st)
        tb = Table([[fmt(h, headc) for h in header]] + [[fmt(v) for v in r] for r in rows], colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d1f24")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return tb

    def foot(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(0.5 * inch, 0.35 * inch, DISCLAIMER)
        c.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.55 * inch, title="Topic Log ranking")
    ch = t["changes"]
    s = [Paragraph("Topic Log ranking", ss["Title"]),
         Paragraph(f"Pull of {t['run_ct']} CT ({t['run_et']} ET). History: {ch.get('pulls', 0)} pulls over {ch.get('days', 0)} days "
                   f"({ch.get('first_et', '')} to {ch.get('last_et', '')} ET).", small), Spacer(1, 6)]
    sheets = {x[0]: x for x in t["sheets"]}
    o = sheets["Overall"]
    s += [Paragraph("Overall, top 25", ss["Heading2"]), tbl(o[1], o[2][:25])]
    s += [PageBreak(), Paragraph("By category (top 10 in each)", ss["Heading2"])]
    c = sheets["By category"]
    s.append(tbl(c[1], c[2]))
    for name in ("Vs previous pull", "Vs previous day"):
        d = sheets[name]
        meta = d[3] or {}
        s += [PageBreak(), Paragraph(f"Rank changes: {name.lower()}", ss["Heading2"]),
              Paragraph(f"{meta.get('from_et', '–')} ET → {meta.get('to_et', '–')} ET"
                        + (f" · top-10 turnover {meta['turnover']:.0%}" if meta.get("turnover") is not None else ""), small)]
        for title, h, rows in zip(DIFF_TITLE, DIFF_HEAD, d[2] or ([], [], [])):
            s += [Paragraph(title, ss["Heading4"]), tbl(h, rows)]
    s.append(PageBreak())
    for name in ("Drivers, vs day before", "Four angles, vs day before", "Daily picks"):
        x = sheets[name]
        s += [Paragraph(name, ss["Heading2"]), tbl(x[1], x[2][:30]), Spacer(1, 8)]
    doc.build(s, onFirstPage=foot, onLaterPages=foot)


def export(data_dir: pathlib.Path, out_dir: pathlib.Path, fmt: str) -> pathlib.Path:
    t = tables(data_dir)
    if not t["run_ts"]:
        raise RuntimeError("No pull yet: nothing to export.")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = t["run_ct"].replace(" ", "_").replace(":", "")
    path = out_dir / f"topiclog_ranking_{stamp}CT.{'xlsx' if fmt == 'xlsx' else 'pdf'}"
    try:
        (_xlsx if fmt == "xlsx" else _pdf)(t, path)
    except ImportError as e:
        raise RuntimeError(f"Export needs {'openpyxl' if fmt == 'xlsx' else 'reportlab'}; reopen the app once online to install it ({e}).")
    return path
