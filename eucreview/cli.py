"""Command line: `demo` builds everything from the fictional service, `review` runs on your own ticket export."""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from . import report, simulate
from .checks import Config, run_all
from .model import load, parse_date


def run(data: Path, out: Path, title: str, c: Config, as_of: date | None = None, period: tuple[date, date] | None = None) -> dict:
    d = load(data, as_of, period)
    findings = run_all(d, c)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, findings, title, c), encoding="utf-8")
    (out / "service-review.md").write_text(report.review_md(d, findings, c), encoding="utf-8")
    report.write_findings(findings, out / "findings.csv")
    report.write_actions(findings, out / "actions.csv")
    report.write_scorecard(d, out / "scorecard.csv")
    report.write_breaches(d, out / "breaches.csv")
    report.write_ageing(d, out / "ageing.csv")
    report.write_escalations(d, out / "escalations.csv")
    return report.summary(d, findings, c)


def _date(value: str) -> date:
    d = parse_date(value)
    if not d:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {value}")
    return d


def _period(value: str) -> tuple[date, date]:
    """YYYY-MM for a calendar month, or YYYY-MM-DD:YYYY-MM-DD."""
    if ":" in value:
        a, b = value.split(":", 1)
        return _date(a), _date(b)
    try:
        y, m = (int(x) for x in value.split("-"))
        start = date(y, m, 1)
        return start, date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a period (YYYY-MM or YYYY-MM-DD:YYYY-MM-DD): {value}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eucreview", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="write the fictional service to sample_data/ and build the outputs")
    d.add_argument("--data", type=Path, default=Path("sample_data"))
    d.add_argument("--out", type=Path, default=Path("output"))

    r = sub.add_parser("review", help="build the outputs from your own ticket export")
    r.add_argument("data", type=Path, help="folder with tickets.csv (and settings.json)")
    r.add_argument("--out", type=Path, default=Path("output"))
    r.add_argument("--title", default="EUC service review")
    r.add_argument("--period", type=_period, help="YYYY-MM, or YYYY-MM-DD:YYYY-MM-DD (default: settings.json, or the last full month)")
    r.add_argument("--as-of", type=_date, help="review date, YYYY-MM-DD (default: settings.json or the last date in the export)")
    r.add_argument("--late-window-share", type=float, default=Config.late_window_share_max,
                   help="%% of compliant tickets resolved in the last 10%% of the window before it is a finding")
    r.add_argument("--pending-share", type=float, default=Config.pending_share_max,
                   help="%% of a ticket's life in pending before it is counted as clock-stopped")
    r.add_argument("--instant-close-min", type=int, default=Config.instant_close_min)
    a = p.parse_args(argv)

    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out, "EUC service review · Northwind Traders with Litware · September 2026", Config())
    else:
        c = Config(late_window_share_max=a.late_window_share, pending_share_max=a.pending_share, instant_close_min=a.instant_close_min)
        try:
            sm = run(a.data, a.out, a.title, c, a.as_of, a.period)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    fmt = lambda v, suf="%": "–" if v is None else f"{v:g}{suf}"  # noqa: E731
    print(f"{sm['tickets']} tickets · SLA metrics on target {sm['metrics_ok']}/{sm['metrics']} · {sm['open']} open ({sm['old']} old) · "
          f"escalated {fmt(sm['escalation_pct'])} · reopen {fmt(sm['reopen_pct'])} · FCR {fmt(sm['fcr_pct'])} · "
          f"CSAT {fmt(sm['csat_avg'], '')} · credits {sm['credit_pct']:g}% ({sm['currency']}{sm['credit_amount']:,.0f}) · "
          f"{sm['critical']} critical, {sm['warning']} warnings · outputs in {a.out}/")
    return 0
