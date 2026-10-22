"""Outputs: report.html, service-review.md, scorecard.csv, breaches.csv, ageing.csv, escalations.csv, actions.csv, findings.csv."""
from __future__ import annotations

import csv
import html
from pathlib import Path

from .checks import (AREAS, BUCKETS, CRITICAL, INFO, WARNING, Config, Finding, ageing, ageing_by_team, area_status, breaches,
                     coverage, credit_total, credits, escalations, ola_by_team, quality, scorecard, sla_rows)
from .model import Data

e = html.escape


def _p(v: float | None, suffix: str = "%") -> str:
    return "–" if v is None else f"{v:g}{suffix}"


def summary(d: Data, findings: list[Finding], c: Config | None = None) -> dict:
    c = c or Config()
    rows = sla_rows(d)
    card = scorecard(d, rows)
    inc = [r for r in card if r["type"] == "incident"]
    req = [r for r in card if r["type"] == "request"]
    q = quality(d, c)
    ag = ageing(d)
    esc = escalations(d)
    prov_rows = [r for r in rows if r["provider"]]
    from_prov = [r for r in esc if r["from_org"] in ("provider", "offshore") and r["to_org"] == "internal"]
    cp, ca = credit_total(d)
    met_metrics = sum((r["resp_pct"] is None or r["resp_pct"] >= r["target"].pct) and (r["res_pct"] is None or r["res_pct"] >= r["target"].pct)
                      for r in card)
    return {"tickets": len(d.in_period), "incidents": sum(r["n"] for r in inc), "requests": sum(r["n"] for r in req),
            "metrics_ok": met_metrics, "metrics": len(card), "resolved": q["resolved"],
            "open": len(ag), "old": sum(r["age"] > d.settings.backlog_max_days for r in ag), "stale": sum(r["stale"] for r in ag),
            "escalated": len(from_prov), "escalation_pct": round(100 * len(from_prov) / len(prov_rows), 1) if prov_rows else None,
            "reopen_pct": q["reopen_pct"], "fcr_pct": q["fcr_pct"], "csat_avg": q["csat_avg"],
            "credit_pct": cp, "credit_amount": ca, "currency": d.settings.currency,
            "critical": sum(f.severity == CRITICAL for f in findings), "warning": sum(f.severity == WARNING for f in findings),
            "info": sum(f.severity == INFO for f in findings)}


# ---------------------------------------------------------------- CSV

def write_findings(findings: list[Finding], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["severity", "area", "code", "subject", "owner", "ref", "amount", "detail", "next_step", "tickets"])
        for f in findings:
            w.writerow([f.severity, f.area, f.code, f.subject, f.owner, f.ref, f"{f.cost:.2f}" if f.cost else "", f.detail, f.fix,
                        " ".join(f.tickets)])


def write_actions(findings: list[Finding], path: Path) -> int:
    """One row per action, worst first, with the owner (provider, internal team or service owner) and a 'done' column."""
    rows = [f for f in findings if f.severity != INFO]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "severity", "area", "owner", "subject", "action", "why", "due", "done"])
        for i, f in enumerate(rows, 1):
            w.writerow([i, f.severity, f.area, f.owner, f.subject, f.fix, f.detail, "", ""])
    return len(rows)


def write_scorecard(d: Data, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "priority", "tickets", "open", "response_target_min", "response_measured", "response_met_pct",
                    "response_breached", "resolution_target_hours", "resolution_measured", "resolution_met_pct", "resolution_breached",
                    "target_pct", "avg_resolution_hours", "resolved_in_last_10pct_of_window", "status"])
        for r in scorecard(d):
            tg = r["target"]
            w.writerow([r["type"], r["priority"], r["n"], r["open"], tg.response_min, r["resp_n"], _p(r["resp_pct"], ""),
                        r["resp_breached"], f"{tg.resolve_hours:g}", r["res_n"], _p(r["res_pct"], ""), r["res_breached"],
                        f"{tg.pct:g}", _p(r["avg_res_hours"], ""), r["late_window"], r["status"]])


def write_breaches(d: Data, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticket", "type", "priority", "kind", "team", "organisation", "created", "actual_minutes", "target_minutes",
                    "times_over", "still_open", "category", "summary", "cause", "accepted_yes_no"])
        for b in breaches(d):
            t = b["ticket"]
            w.writerow([t.id, t.type, t.priority, b["kind"], t.team, b["org"], f"{t.created:%Y-%m-%d %H:%M}", f"{b['actual_min']:.0f}",
                        f"{b['target_min']:.0f}", f"{b['over']:.1f}", "yes" if b["open"] else "no", t.category, t.summary, "", ""])


def write_ageing(d: Data, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticket", "type", "priority", "team", "organisation", "created", "age_days", "bucket", "days_since_update",
                    "stale", "past_resolution_target", "status", "category", "summary", "decision", "owner"])
        for r in ageing(d):
            t = r["ticket"]
            w.writerow([t.id, t.type, t.priority, r["team"], r["org"], f"{t.created:%Y-%m-%d}", r["age"], r["bucket"], r["idle"],
                        "yes" if r["stale"] else "no", "yes" if r["over_target"] else "no", t.status, t.category, t.summary, "", ""])


def write_escalations(d: Data, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticket", "type", "priority", "from_team", "from_organisation", "to_team", "to_organisation", "created",
                    "escalated_at", "handoff_minutes", "handoff_share_of_window", "ola_hours", "ola_minutes", "ola_met", "still_open",
                    "category"])
        for r in sorted(escalations(d), key=lambda r: (r["ola_met"] is not False, -r["handoff_share"])):
            t = r["ticket"]
            w.writerow([t.id, t.type, t.priority, t.team, r["from_org"], r["to"], r["to_org"], f"{t.created:%Y-%m-%d %H:%M}",
                        f"{t.escalated_at:%Y-%m-%d %H:%M}" if t.escalated_at else "", f"{r['handoff_min']:.0f}",
                        f"{r['handoff_share']:.2f}", _p(r["ola_hours"], ""), f"{r['ola_min']:.0f}",
                        "" if r["ola_met"] is None else ("yes" if r["ola_met"] else "no"), "yes" if r["open"] else "no", t.category])


# ---------------------------------------------------------------- Markdown

def review_md(d: Data, findings: list[Finding], c: Config | None = None) -> str:
    """The agenda for the monthly service review: what to raise with the provider and what we owe them."""
    c = c or Config()
    s = d.settings
    sm, st = summary(d, findings, c), area_status(findings)
    card = scorecard(d)
    L = [f"# EUC service review · {s.customer} with {s.provider} · {d.period_start:%d %b} – {d.period_end:%d %b %Y}", "",
         f"Reviewed {d.as_of:%d %b %Y}. {sm['tickets']} tickets in the period ({sm['incidents']} incidents, {sm['requests']} requests) · "
         f"SLA metrics on target {sm['metrics_ok']}/{sm['metrics']} · {sm['open']} open at the review date, {sm['old']} older than "
         f"{s.backlog_max_days} days · escalated to internal teams {_p(sm['escalation_pct'])} · reopen {_p(sm['reopen_pct'])} · "
         f"FCR {_p(sm['fcr_pct'])} · CSAT {_p(sm['csat_avg'], '/5')} · service credits {sm['credit_pct']:g}% "
         f"({s.currency}{sm['credit_amount']:,.0f}) · {sm['critical']} critical, {sm['warning']} warnings.", "",
         "| Area | Status |", "|---|---|"] + [f"| {a} | {'OK' if st[a] == 'ok' else st[a].upper()} |" for a in AREAS]
    L += ["", "## 1. Scorecard", "", "| Type | Priority | Tickets | Response | Resolution | Target | Status |", "|---|---|---|---|---|---|---|"]
    for r in card:
        L.append(f"| {r['type']} | {r['priority']} | {r['n']} | {_p(r['resp_pct'])} | {_p(r['res_pct'])} | {r['target'].pct:g}% | "
                 f"{'OK' if r['status'] == 'ok' else r['status'].upper()} |")
    L += ["", "Breach list with a `cause` column to fill in with the provider: `breaches.csv`."]
    prov = [f for f in findings if f.owner == s.provider and f.severity != INFO]
    if prov:
        L += ["", f"## 2. To raise with {s.provider}", ""]
        for f in prov:
            L.append(f"- **{f.subject}** ({f.area}): {f.detail}  \n  Ask: {f.fix}")
    ours = [f for f in findings if f.owner not in (s.provider, "Service owner", "") and f.severity != INFO]
    if ours:
        L += ["", "## 3. What we owe the provider (OLAs and internal queues)", ""]
        for f in ours:
            L.append(f"- **{f.subject}** · {f.owner}: {f.detail}  \n  Next step: {f.fix}")
    so = [f for f in findings if f.owner == "Service owner" and f.severity != INFO]
    if so:
        L += ["", "## 4. Contract and service ownership", ""]
        for f in so:
            L.append(f"- **{f.subject}**: {f.detail}  \n  Next step: {f.fix}")
    infos = [f for f in findings if f.severity == INFO]
    if infos:
        L += ["", "## 5. For information", ""] + [f"- {f.subject}: {f.detail}" for f in infos]
    L += ["", "## Actions", "", "Work list with owner and `due`/`done` columns: `actions.csv`. Ageing review: `ageing.csv`. "
          "Escalations and OLA clocks: `escalations.csv`.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- HTML

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;--na:#8a94a0}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;--bad:#f2685c;--info:#5aa9f0;--na:#6d7782}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:26px}
.areas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.area{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:10px;padding:10px 14px}
.area.critical{border-left-color:var(--bad)}.area.warning{border-left-color:var(--warn)}
.area .lbl{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:4px}.area .cnt{display:block;font-size:13px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.critical{color:var(--bad)}.warning{color:var(--warn)}.info{color:var(--info)}.ok{color:var(--ok)}.na{color:var(--na)}
.area.critical,.area.warning,.area.ok{color:inherit}
.bar{display:flex;align-items:center;gap:8px;min-width:150px}.bar i{display:block;height:10px;border-radius:5px;background:var(--ok);flex:none}
.bar i.warning{background:var(--warn)}.bar i.critical{background:var(--bad)}.bar s{text-decoration:none;font-size:12px;color:var(--muted);white-space:nowrap}
.bar .t{position:relative;flex:1;height:10px;border-radius:5px;background:var(--line);overflow:hidden}.bar .t i{position:absolute;left:0;top:0}
.bar .t em{position:absolute;top:-2px;width:2px;height:14px;background:var(--ink);opacity:.6}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}.grid div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.grid b{display:block;font-size:22px}.tag{display:inline-block;font-size:12px;padding:0 6px;margin:2px 4px 0 0;border-radius:5px;background:var(--line)}
.stack{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--line);min-width:160px}.stack i{display:block;height:100%}
.b0{background:#9fc7ad}.b1{background:#6fae87}.b2{background:#e3b45c}.b3{background:#e08a4a}.b4{background:var(--bad)}
td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);max-width:380px}code{font-size:12px}
footer{margin-top:40px;font-size:13px}
"""


def _pill(s: str, label: str | None = None) -> str:
    return f"<span class='pill {s}'>{e(label or ('OK' if s == 'ok' else s.upper()))}</span>"


def _bar(pct: float | None, target: float) -> str:
    if pct is None:
        return "<span class='na'>–</span>"
    cls = "ok" if pct >= target else "warning" if pct >= target - 5 else "critical"
    return (f"<div class='bar'><div class='t'><i class='{cls}' style='width:{pct:.0f}%'></i><em style='left:{target:.0f}%'></em></div>"
            f"<s>{pct:g}%</s></div>")


def render_html(d: Data, findings: list[Finding], title: str, c: Config | None = None) -> str:
    c = c or Config()
    s = d.settings
    sm, st = summary(d, findings, c), area_status(findings)
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>{e(s.customer)} with {e(s.provider)} · {d.period_start:%d %b} – {d.period_end:%d %b %Y} · "
         f"reviewed {d.as_of:%d %b %Y}</p>", "<div class='tiles'>"]
    tiles = [("Tickets", str(sm["tickets"]), f"{sm['incidents']} incidents · {sm['requests']} requests"),
             ("SLA metrics on target", f"{sm['metrics_ok']}/{sm['metrics']}", "type × priority"),
             ("Open at review", str(sm["open"]), f"{sm['old']} older than {s.backlog_max_days} days · {sm['stale']} stale"),
             ("Escalated to us", _p(sm["escalation_pct"]), f"{sm['escalated']} tickets · limit {s.escalation_rate_max:g}%"),
             ("Reopened", _p(sm["reopen_pct"]), f"limit {s.reopen_rate_max:g}%"),
             ("First contact", _p(sm["fcr_pct"]), f"target {s.fcr_min:g}%"),
             ("Satisfaction", _p(sm["csat_avg"], ""), f"of 5 · target {s.csat_min:g}"),
             ("Service credits", f"{sm['credit_pct']:g}%", f"{s.currency}{sm['credit_amount']:,.0f} of the fee"),
             ("Critical", str(sm["critical"]), f"{sm['warning']} warnings · {sm['info']} for information")]
    h += [f"<div class='tile'><span class='muted'>{e(a)}</span><b>{e(b)}</b><span class='muted'>{e(x)}</span></div>" for a, b, x in tiles]
    h.append("</div><h2>Status by area</h2><div class='areas'>")
    for a in AREAS:
        n = sum(f.area == a and f.severity != INFO for f in findings)
        h.append(f"<div class='area {st[a]}'><span class='lbl'>{e(a)}</span>{_pill(st[a])}<span class='cnt'>{n} to act on</span></div>")
    h.append("</div>")

    act = [f for f in findings if f.severity == CRITICAL]
    if act:
        h.append("<h2>Raise first</h2><div class='wrap'><table><tr><th>Subject</th><th>What</th><th>Next step</th><th>Owner</th></tr>")
        h += [f"<tr><td><b>{e(f.subject)}</b><br><span class='muted'>{e(f.area)}</span></td><td>{e(f.detail)}</td>"
              f"<td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner or '?')}</td></tr>" for f in act]
        h.append("</table></div>")

    # scorecard
    rows = sla_rows(d)
    card = scorecard(d, rows)
    h.append("<h2>SLA scorecard</h2><div class='wrap'><table><tr><th>Type</th><th>Priority</th><th class='num'>Tickets</th>"
             "<th>Response</th><th>Resolution</th><th class='num'>Avg resolve</th><th class='num'>Last-minute</th><th>Status</th></tr>")
    for r in card:
        tg = r["target"]
        h.append(f"<tr><td>{e(r['type'])}</td><td class='nw'><b>{r['priority']}</b><br><span class='muted'>{tg.response_min} min · "
                 f"{tg.resolve_hours:g} h · {'24x7' if not tg.business_hours else 'business hours'}</span></td>"
                 f"<td class='num'>{r['n']}{'<br><span class=muted>' + str(r['open']) + ' open</span>' if r['open'] else ''}</td>"
                 f"<td>{_bar(r['resp_pct'], tg.pct)}</td><td>{_bar(r['res_pct'], tg.pct)}</td>"
                 f"<td class='num'>{_p(r['avg_res_hours'], ' h')}</td><td class='num'>{r['late_window']}</td><td class='nw'>{_pill(r['status'])}</td></tr>")
    h.append("</table></div><p class='muted'>The mark on each bar is the contractual target. Last-minute: tickets resolved in the final "
             "10% of their window. Pending time (clock stopped) is subtracted from the resolution clock.</p>")

    # breaches
    br = breaches(d)
    if br:
        h.append(f"<h2>Breaches ({len(br)})</h2><div class='wrap'><table><tr><th>Ticket</th><th>Priority</th><th>Kind</th><th>Team</th>"
                 "<th class='num'>Actual</th><th class='num'>Target</th><th class='num'>Over</th><th>Summary</th></tr>")
        for b in br[:25]:
            t = b["ticket"]
            h.append(f"<tr><td class='nw'>{e(t.id)}{'<br><span class=muted>open</span>' if b['open'] else ''}</td><td class='nw'>{t.type} {t.priority}</td>"
                     f"<td>{b['kind']}</td><td>{e(t.team or '–')}<br><span class='muted'>{e(b['org'])}</span></td>"
                     f"<td class='num'>{b['actual_min'] / 60:.1f} h</td><td class='num'>{b['target_min'] / 60:.1f} h</td>"
                     f"<td class='num critical'>×{b['over']:.1f}</td><td>{e(t.summary)}<br><span class='muted'>{e(t.category or '–')}</span></td></tr>")
        h.append("</table></div>" + (f"<p class='muted'>Showing the 25 worst of {len(br)}; the full list is in <code>breaches.csv</code>.</p>"
                                      if len(br) > 25 else ""))

    # backlog
    ag = ageing(d)
    teams = ageing_by_team(d, ag)
    h.append("<h2>Backlog and ageing</h2><div class='wrap'><table><tr><th>Team</th><th class='num'>Open</th><th>Age</th>"
             f"<th class='num'>Over {s.backlog_max_days} d</th><th class='num'>Stale</th><th class='num'>Past target</th></tr>")
    for x in teams:
        total = x["open"] or 1
        stack = "".join(f"<i class='b{i}' style='width:{100 * x[label] / total:.0f}%' title='{label}: {x[label]}'></i>"
                        for i, (_, label) in enumerate(BUCKETS))
        h.append(f"<tr><td>{e(x['team'])}<br><span class='muted'>{e(x['org'])}</span></td><td class='num'>{x['open']}</td>"
                 f"<td><div class='stack'>{stack}</div></td><td class='num {'critical' if x['old'] else ''}'>{x['old']}</td>"
                 f"<td class='num {'warning' if x['stale'] else ''}'>{x['stale']}</td><td class='num'>{x['over']}</td></tr>")
    h.append("</table></div><p class='muted'>Age buckets, left to right: " + " · ".join(
        f"<span class='tag'>{label}</span>" for _, label in BUCKETS) +
        f". Stale: no update for {s.stale_days}+ days. An open escalated ticket is counted with the team that received it.</p>")
    old = [r for r in ag if r["age"] > s.backlog_max_days]
    if old:
        h.append("<div class='wrap'><table><tr><th>Ticket</th><th>Team</th><th class='num'>Age</th><th class='num'>Idle</th><th>Status</th><th>Summary</th></tr>")
        for r in old[:20]:
            t = r["ticket"]
            h.append(f"<tr><td class='nw'>{e(t.id)}<br><span class='muted'>{t.type} {t.priority}</span></td><td>{e(r['team'])}</td>"
                     f"<td class='num critical'>{r['age']} d</td><td class='num'>{r['idle']} d</td><td>{e(t.status)}</td>"
                     f"<td>{e(t.summary)}<br><span class='muted'>{e(t.category or '–')}</span></td></tr>")
        h.append("</table></div>")

    # escalations
    esc = escalations(d)
    ola = ola_by_team(d, esc)
    h.append("<h2>Escalations and OLAs</h2>")
    if ola:
        h.append("<div class='wrap'><table><tr><th>Receiving team</th><th class='num'>Received</th><th>OLA met</th><th class='num'>OLA</th>"
                 "<th class='num'>Avg</th><th class='num'>Open</th></tr>")
        for x in ola:
            h.append(f"<tr><td>{e(x['team'])}<br><span class='muted'>{e(x['org'])}</span></td><td class='num'>{x['received']}</td>"
                     f"<td>{_bar(x['pct'], s.ola_pct) if x['ola_hours'] is not None else '<span class=na>no OLA defined</span>'}</td>"
                     f"<td class='num'>{_p(x['ola_hours'], ' h')}</td><td class='num'>{_p(x['avg_hours'], ' h')}</td><td class='num'>{x['open']}</td></tr>")
        late = [r for r in esc if r["handoff_share"] >= c.handoff_late_share]
        h.append(f"</table></div><p class='muted'>{len(esc)} escalations in the period; {len(late)} handed over after half the resolution "
                 f"window was used. OLA clock starts at the hand-over. Detail in <code>escalations.csv</code>.</p>")
    else:
        h.append("<p class='muted'>No escalations recorded (no <code>escalated_to</code> column, or nothing escalated).</p>")

    # coverage
    cov = coverage(d, rows)
    h.append("<h2>Coverage</h2><div class='grid'>")
    h.append(f"<div><span class='muted'>Response in business hours</span><b>{_p(cov['in_hours_pct'])}</b><span class='muted'>{cov['in_hours_n']} tickets</span></div>")
    h.append(f"<div><span class='muted'>Response out of hours</span><b class='{'warning' if cov['out_hours_pct'] is not None and cov['in_hours_pct'] is not None and cov['in_hours_pct'] - cov['out_hours_pct'] >= c.out_of_hours_gap else ''}'>"
             f"{_p(cov['out_hours_pct'])}</b><span class='muted'>{cov['out_hours_n']} tickets · {len(cov['out_hours_breached'])} late</span></div>")
    h.append(f"<div><span class='muted'>Urgent incidents out of hours</span><b>{len(cov['weekend_urgent'])}</b><span class='muted'>P1/P2 created outside "
             f"{s.business_start:%H:%M}–{s.business_end:%H:%M}</span></div>")
    h.append("<div><span class='muted'>Who handled the tickets</span>" + "".join(
        f"<span class='tag'>{e(k)} {v:g}%</span>" for k, v in sorted(cov["share"].items(), key=lambda kv: -kv[1])) + "</div>")
    h.append("</div>")

    # quality
    q = quality(d, c)
    h.append("<h2>Quality</h2><div class='grid'>")
    for label, val, sub in (("Reopened", _p(q["reopen_pct"]), f"{len(q['reopened'])} of {q['resolved']} · limit {s.reopen_rate_max:g}%"),
                            ("First-contact resolution", _p(q["fcr_pct"]), f"{q['fcr_n']} incidents measured · target {s.fcr_min:g}%"),
                            ("Satisfaction", _p(q["csat_avg"], ""), f"{q['csat_n']} surveys · {_p(q['csat_low_pct'])} scored {s.csat_low:g} or less"),
                            ("Resolved at the last minute", _p(q["late_window_pct"]), f"{len(q['late_window'])} tickets in the final 10% of the window"),
                            ("Clock stopped", str(len(q["pending_heavy"])), f"tickets over {c.pending_share_max:g}% of their life in pending"),
                            ("Instant closes", str(len(q["instant"])), f"incidents resolved within {c.instant_close_min} min of creation"),
                            ("No category", str(len(q["no_category"])), "resolved tickets with an empty category")):
        h.append(f"<div><span class='muted'>{e(label)}</span><b>{e(val)}</b><span class='muted'>{e(sub)}</span></div>")
    h.append("</div><p class='muted'>Top categories in the period: " + ", ".join(f"{e(k)} ({v})" for k, v in q["by_category"]) + ".</p>")

    # contract
    cr = credits(d, card)
    h.append("<h2>Contract</h2>")
    if cr:
        h.append("<div class='wrap'><table><tr><th>Metric</th><th class='num'>Achieved</th><th class='num'>Target</th><th class='num'>Gap</th>"
                 "<th class='num'>Credit</th><th class='num'>Amount</th></tr>")
        for x in cr:
            h.append(f"<tr><td>{x['type']} {x['priority']} {x['kind']}</td><td class='num'>{x['pct']:g}%</td><td class='num'>{x['target']:g}%</td>"
                     f"<td class='num critical'>-{x['gap']:g}</td><td class='num'>{x['credit_pct']:g}%</td><td class='num'>{s.currency}{x['amount']:,.0f}</td></tr>")
        cp, ca = credit_total(d, cr)
        h.append(f"</table></div><p class='muted'>Bands from settings.json: " + ", ".join(f"{a:g}+ points → {b:g}%" for a, b in s.credits) +
                 f". Monthly cap {s.credits_cap:g}%. Total due: <b>{cp:g}% = {s.currency}{ca:,.0f}</b> of a {s.currency}{s.monthly_fee:,.0f} fee.</p>")
    else:
        h.append("<p class='muted'>No SLA metric below target: no service credits this period.</p>")
    if s.baseline_volume:
        n = len(d.in_period)
        h.append(f"<p class='muted'>Volume: {n} tickets against a contracted baseline of {s.baseline_volume} ({100 * (n / s.baseline_volume - 1):+.0f}%).</p>")

    h.append("<h2>All findings</h2><div class='wrap'><table><tr><th>Severity</th><th>Area</th><th>Subject</th><th>Detail</th><th>Next step</th><th>Owner</th></tr>")
    h += [f"<tr><td>{_pill(f.severity)}</td><td class='nw'>{e(f.area)}</td><td>{e(f.subject)}</td><td>{e(f.detail)}</td>"
          f"<td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner)}</td></tr>" for f in findings]
    h.append("</table></div><footer class='muted'>Generated by eucreview from a ticket export and the service settings. Fictional demo data "
             "unless you ran it on your own export.</footer></main></body></html>")
    return "".join(h)
