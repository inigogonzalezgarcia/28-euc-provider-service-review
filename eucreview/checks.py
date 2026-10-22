"""The checks: SLA scorecard, backlog and ageing, escalations and OLAs, coverage, quality and the contract.

Everything here works on the Data object from model.py and returns plain rows (dicts) and Findings, so the
report module can render them and the tests can assert on them.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from statistics import mean

from .model import PRIORITIES, Data, Settings, Target, Ticket

CRITICAL, WARNING, INFO = "critical", "warning", "info"
AREAS = ("SLA", "Backlog & ageing", "Escalations & OLAs", "Coverage", "Quality", "Contract")
BUCKETS = ((3, "0-2 days"), (8, "3-7 days"), (15, "8-14 days"), (31, "15-30 days"), (10 ** 6, "over 30 days"))
LATE_WINDOW = 0.90   # resolved after this share of the window is "resolved at the last minute"


@dataclass
class Config:
    late_window_share_max: float = 15.0   # % of met tickets resolved in the last 10% of the window
    pending_share_max: float = 50.0       # % of the elapsed time with the clock stopped
    instant_close_min: int = 2            # resolved this many minutes after creation = suspicious
    out_of_hours_gap: float = 10.0        # points of response compliance between in-hours and out-of-hours
    handoff_late_share: float = 0.5       # escalated after this share of the resolution window was used


@dataclass
class Finding:
    severity: str
    area: str
    code: str
    subject: str
    detail: str
    fix: str
    owner: str = ""
    ref: str = ""
    cost: float = 0.0
    tickets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- clocks

def business_minutes(a: datetime, b: datetime, s: Settings) -> float:
    """Minutes between a and b that fall inside business hours (settings), holidays excluded."""
    if b <= a:
        return 0.0
    total = 0.0
    day = a.date()
    while day <= b.date():
        if day.weekday() in s.business_days and day not in s.holidays:
            ws, we = datetime.combine(day, s.business_start), datetime.combine(day, s.business_end)
            lo, hi = max(a, ws), min(b, we)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return total


def clock_minutes(a: datetime, b: datetime, target: Target, s: Settings) -> float:
    return business_minutes(a, b, s) if target.business_hours else max(0.0, (b - a).total_seconds() / 60)


def in_business_hours(when: datetime, s: Settings) -> bool:
    return (when.weekday() in s.business_days and when.date() not in s.holidays
            and s.business_start <= when.time() < s.business_end)


def _as_of_dt(d: Data) -> datetime:
    return datetime.combine(d.as_of, time(23, 59))


# ---------------------------------------------------------------- SLA

def sla_rows(d: Data) -> list[dict]:
    """One row per ticket created in the period with its response and resolution clocks against the target."""
    s, now = d.settings, _as_of_dt(d)
    rows = []
    for t in d.in_period:
        if not t.created:
            continue
        tg = s.target(t)
        resp_end = t.first_response or t.resolved or (now if t.is_open else None)
        resp = clock_minutes(t.created, resp_end, tg, s) if resp_end else None
        resp_met = None if resp is None else resp <= tg.response_min
        if t.resolved:
            res = max(0.0, clock_minutes(t.created, t.resolved, tg, s) - t.pending_hours * 60)
            res_open = False
        else:
            res = max(0.0, clock_minutes(t.created, now, tg, s) - t.pending_hours * 60)
            res_open = True
        res_target = tg.resolve_hours * 60
        res_met = res <= res_target if not res_open else (None if res <= res_target else False)
        share = res / res_target if res_target else 0.0
        rows.append({"ticket": t, "target": tg, "resp_min": resp, "resp_met": resp_met, "res_min": res, "res_met": res_met,
                     "res_open": res_open, "share": share, "late_window": bool(res_met) and share >= LATE_WINDOW,
                     "org": s.org(t.team), "provider": s.is_provider(t.team)})
    return rows


def _pct(n: int, total: int) -> float | None:
    return round(100.0 * n / total, 1) if total else None


def scorecard(d: Data, rows: list[dict] | None = None) -> list[dict]:
    """Compliance per ticket type and priority: response and resolution, against the contractual target %."""
    rows = rows if rows is not None else sla_rows(d)
    out = []
    for typ in ("incident", "request"):
        for p in PRIORITIES:
            sub = [r for r in rows if r["ticket"].type == typ and r["ticket"].priority == p]
            if not sub:
                continue
            tg = sub[0]["target"]
            resp = [r for r in sub if r["resp_met"] is not None]
            res = [r for r in sub if r["res_met"] is not None]
            resp_pct = _pct(sum(r["resp_met"] for r in resp), len(resp))
            res_pct = _pct(sum(r["res_met"] for r in res), len(res))
            worst = min(x for x in (resp_pct, res_pct) if x is not None) if (resp_pct is not None or res_pct is not None) else None
            status = "na" if worst is None else "ok" if worst >= tg.pct else "warning" if worst >= tg.pct - 5 else "critical"
            out.append({"type": typ, "priority": p, "n": len(sub), "open": sum(r["res_open"] for r in sub), "target": tg,
                        "resp_n": len(resp), "resp_pct": resp_pct, "resp_breached": sum(not r["resp_met"] for r in resp),
                        "res_n": len(res), "res_pct": res_pct, "res_breached": sum(not r["res_met"] for r in res),
                        "late_window": sum(r["late_window"] for r in sub), "status": status,
                        "avg_res_hours": round(mean(r["res_min"] for r in res) / 60, 1) if res else None})
    return out


def breaches(d: Data, rows: list[dict] | None = None) -> list[dict]:
    """Every response or resolution breach, worst first (by how far over the target)."""
    rows = rows if rows is not None else sla_rows(d)
    out = []
    for r in rows:
        t, tg = r["ticket"], r["target"]
        if r["resp_met"] is False:
            out.append({"ticket": t, "kind": "response", "actual_min": r["resp_min"], "target_min": tg.response_min,
                        "over": r["resp_min"] / tg.response_min if tg.response_min else 0, "org": r["org"], "open": r["res_open"]})
        if r["res_met"] is False:
            out.append({"ticket": t, "kind": "resolution", "actual_min": r["res_min"], "target_min": tg.resolve_hours * 60,
                        "over": r["share"], "org": r["org"], "open": r["res_open"]})
    return sorted(out, key=lambda x: -x["over"])


# ---------------------------------------------------------------- backlog

def bucket(days: int) -> str:
    for limit, label in BUCKETS:
        if days < limit:
            return label
    return BUCKETS[-1][1]


def ageing(d: Data) -> list[dict]:
    """Open tickets at the review date with their age, bucket, owner and whether they are stale."""
    s = d.settings
    out = []
    for t in d.open_tickets:
        team = t.escalated_to or t.team or "(unassigned)"   # an open escalated ticket sits with the team that received it
        age = (d.as_of - t.created.date()).days
        last = (t.updated or t.escalated_at or t.first_response or t.created)
        idle = (d.as_of - last.date()).days
        tg = s.target(t)
        used = max(0.0, clock_minutes(t.created, _as_of_dt(d), tg, s) - t.pending_hours * 60)
        out.append({"ticket": t, "age": age, "bucket": bucket(age), "idle": idle, "stale": idle >= s.stale_days,
                    "over_target": used > tg.resolve_hours * 60, "org": s.org(team), "team": team})
    return sorted(out, key=lambda r: -r["age"])


def ageing_by_team(d: Data, rows: list[dict] | None = None) -> list[dict]:
    rows = rows if rows is not None else ageing(d)
    teams: dict[str, dict] = {}
    for r in rows:
        x = teams.setdefault(r["team"], {"team": r["team"], "org": r["org"], "open": 0, "stale": 0, "old": 0, "over": 0,
                                         **{label: 0 for _, label in BUCKETS}})
        x["open"] += 1
        x["stale"] += r["stale"]
        x["old"] += r["age"] > d.settings.backlog_max_days
        x["over"] += r["over_target"]
        x[r["bucket"]] += 1
    return sorted(teams.values(), key=lambda x: (-x["old"], -x["open"]))


# ---------------------------------------------------------------- escalations and OLAs

def escalations(d: Data) -> list[dict]:
    """Tickets escalated to another team in the period: hand-off delay and the OLA clock of the receiving team."""
    s, now = d.settings, _as_of_dt(d)
    out = []
    for t in d.in_period:
        if not t.escalated_to or not t.created:
            continue
        tg = s.target(t)
        esc_at = t.escalated_at or t.created
        handoff = clock_minutes(t.created, esc_at, tg, s)
        handoff_share = handoff / (tg.resolve_hours * 60) if tg.resolve_hours else 0
        ola_hours = s.ola.get(t.escalated_to)
        end = t.resolved or now
        ola_min = clock_minutes(esc_at, end, tg, s)
        ola_met = None if ola_hours is None else (ola_min <= ola_hours * 60 if t.resolved else (None if ola_min <= ola_hours * 60 else False))
        out.append({"ticket": t, "from_org": s.org(t.team), "to": t.escalated_to, "to_org": s.org(t.escalated_to),
                    "handoff_min": handoff, "handoff_share": handoff_share, "ola_hours": ola_hours, "ola_min": ola_min,
                    "ola_met": ola_met, "open": not t.resolved})
    return out


def ola_by_team(d: Data, rows: list[dict] | None = None) -> list[dict]:
    rows = rows if rows is not None else escalations(d)
    teams: dict[str, dict] = {}
    for r in rows:
        x = teams.setdefault(r["to"], {"team": r["to"], "org": r["to_org"], "received": 0, "measured": 0, "met": 0,
                                       "open": 0, "ola_hours": r["ola_hours"], "minutes": []})
        x["received"] += 1
        x["open"] += r["open"]
        if r["ola_met"] is not None:
            x["measured"] += 1
            x["met"] += r["ola_met"]
        if not r["open"]:
            x["minutes"].append(r["ola_min"])
    out = []
    for x in teams.values():
        x["pct"] = _pct(x["met"], x["measured"])
        x["avg_hours"] = round(mean(x["minutes"]) / 60, 1) if x["minutes"] else None
        del x["minutes"]
        out.append(x)
    return sorted(out, key=lambda x: (x["pct"] if x["pct"] is not None else 101, -x["received"]))


# ---------------------------------------------------------------- coverage

def coverage(d: Data, rows: list[dict] | None = None) -> dict:
    """Response compliance in and out of business hours, and the share handled by each organisation."""
    s = d.settings
    rows = rows if rows is not None else sla_rows(d)
    rows = [r for r in rows if r["resp_met"] is not None]
    inh = [r for r in rows if in_business_hours(r["ticket"].created, s)]
    ooh = [r for r in rows if not in_business_hours(r["ticket"].created, s)]
    weekend_urgent = [r["ticket"] for r in rows if r["ticket"].priority in ("P1", "P2") and r["ticket"].type == "incident"
                      and not in_business_hours(r["ticket"].created, s)]
    orgs = Counter(r["org"] for r in rows)
    return {"in_hours_n": len(inh), "in_hours_pct": _pct(sum(r["resp_met"] for r in inh), len(inh)),
            "out_hours_n": len(ooh), "out_hours_pct": _pct(sum(r["resp_met"] for r in ooh), len(ooh)),
            "out_hours_breached": [r for r in ooh if not r["resp_met"]],
            "weekend_urgent": weekend_urgent, "share": {k: _pct(v, len(rows)) for k, v in orgs.items()},
            "by_org": orgs}


# ---------------------------------------------------------------- quality

def quality(d: Data, c: Config | None = None) -> dict:
    c = c or Config()
    s = d.settings
    period = [t for t in d.in_period if t.created]
    resolved = [t for t in period if t.resolved]
    reopened = [t for t in resolved if t.reopened > 0]
    fcr_pool = [t for t in resolved if t.type == "incident" and t.fcr is not None]
    fcr_yes = [t for t in fcr_pool if t.fcr]
    rated = [t for t in resolved if t.csat is not None]
    low = [t for t in rated if t.csat <= s.csat_low]
    no_category = [t for t in resolved if not t.category]
    no_team = [t for t in period if not t.team]
    instant = [t for t in resolved if t.type == "incident" and (t.resolved - t.created) <= timedelta(minutes=c.instant_close_min)]
    pending_heavy = []
    for t in resolved:
        tg = s.target(t)
        elapsed = clock_minutes(t.created, t.resolved, tg, s)
        if t.pending_hours * 60 > 0 and elapsed > 0 and (t.pending_hours * 60) / elapsed * 100 >= c.pending_share_max:
            pending_heavy.append(t)
    rows = sla_rows(d)
    met = [r for r in rows if r["res_met"]]
    late = [r for r in met if r["late_window"]]
    return {"resolved": len(resolved), "reopened": reopened, "reopen_pct": _pct(len(reopened), len(resolved)),
            "fcr_n": len(fcr_pool), "fcr_pct": _pct(len(fcr_yes), len(fcr_pool)),
            "csat_n": len(rated), "csat_avg": round(mean(t.csat for t in rated), 2) if rated else None,
            "csat_low": low, "csat_low_pct": _pct(len(low), len(rated)),
            "no_category": no_category, "no_team": no_team, "instant": instant, "pending_heavy": pending_heavy,
            "late_window": late, "late_window_pct": _pct(len(late), len(met)),
            "by_category": Counter(t.category or "(none)" for t in period).most_common(8)}


# ---------------------------------------------------------------- contract

def credits(d: Data, card: list[dict] | None = None) -> list[dict]:
    """Service credits per missed SLA metric, from the credit bands in settings (points below target -> % of the fee)."""
    s = d.settings
    card = card if card is not None else scorecard(d)
    out = []
    for r in card:
        for kind, key in (("response", "resp_pct"), ("resolution", "res_pct")):
            pct = r[key]
            if pct is None or pct >= r["target"].pct:
                continue
            gap = round(r["target"].pct - pct, 1)
            band = max((b for b in s.credits if gap >= b[0]), key=lambda b: b[0], default=None)
            credit_pct = band[1] if band else 0.0
            out.append({"type": r["type"], "priority": r["priority"], "kind": kind, "pct": pct, "target": r["target"].pct,
                        "gap": gap, "credit_pct": credit_pct, "amount": round(s.monthly_fee * credit_pct / 100, 2)})
    return out


def credit_total(d: Data, rows: list[dict] | None = None) -> tuple[float, float]:
    """(% of the fee, amount) after the monthly cap."""
    s = d.settings
    rows = rows if rows is not None else credits(d)
    pct = min(sum(x["credit_pct"] for x in rows), s.credits_cap) if s.credits_cap else sum(x["credit_pct"] for x in rows)
    return round(pct, 2), round(s.monthly_fee * pct / 100, 2)


# ---------------------------------------------------------------- findings

def run_all(d: Data, c: Config | None = None) -> list[Finding]:
    c = c or Config()
    s = d.settings
    prov = s.provider
    F: list[Finding] = []
    rows = sla_rows(d)
    card = scorecard(d, rows)

    # SLA
    for r in card:
        label = f"{r['type'].title()} {r['priority']}"
        for kind, key, nb, unit in (("response", "resp_pct", "resp_breached", f"{r['target'].response_min} min"),
                                    ("resolution", "res_pct", "res_breached", f"{r['target'].resolve_hours:g} h")):
            pct = r[key]
            if pct is None or pct >= r["target"].pct:
                continue
            gap = r["target"].pct - pct
            sev = CRITICAL if (gap >= 5 or (r["type"] == "incident" and r["priority"] in ("P1", "P2"))) else WARNING
            ids = [x["ticket"].id for x in rows if x["ticket"].type == r["type"] and x["ticket"].priority == r["priority"]
                   and x[{"response": "resp_met", "resolution": "res_met"}[kind]] is False]
            F.append(Finding(sev, "SLA", f"sla_{kind}", f"{label} {kind}",
                             f"{pct:g}% within {unit} against a {r['target'].pct:g}% target ({r[nb]} of {r[key.replace('pct', 'n')]} "
                             f"breached{', ' + str(r['open']) + ' still open' if r['open'] else ''}).",
                             f"Ask {prov} for the breach list with a cause per ticket, and agree a recovery plan with a date.",
                             owner=prov, ref=f"{r['type']}/{r['priority']}", tickets=ids))
    open_urgent = [x for x in rows if x["res_open"] and x["ticket"].priority in ("P1", "P2") and x["ticket"].type == "incident"]
    if open_urgent:
        F.append(Finding(CRITICAL, "SLA", "urgent_open", f"{len(open_urgent)} P1/P2 incidents still open",
                         "Open at the review date: " + ", ".join(x["ticket"].id for x in open_urgent[:8]) + (" …" if len(open_urgent) > 8 else ""),
                         "Review each one in the meeting: owner, blocker and the date it closes.", owner=prov,
                         tickets=[x["ticket"].id for x in open_urgent]))

    # backlog
    ag = ageing(d)
    old = [r for r in ag if r["age"] > s.backlog_max_days]
    by_team = ageing_by_team(d, ag)
    for x in by_team:
        if x["old"]:
            owner = prov if x["org"] in ("provider", "offshore") else x["team"]
            sev = CRITICAL if x["old"] >= 10 else WARNING
            F.append(Finding(sev, "Backlog & ageing", "old_backlog", f"{x['team']}: {x['old']} tickets older than {s.backlog_max_days} days",
                             f"{x['open']} open in total, {x['stale']} with no update for {s.stale_days}+ days, {x['over']} past their resolution target.",
                             "Close, cancel or re-plan each one; anything older than the period goes to the ageing review with a named owner.",
                             owner=owner, ref=x["team"], tickets=[r["ticket"].id for r in ag if r["team"] == x["team"] and r["age"] > s.backlog_max_days]))
    stale = [r for r in ag if r["stale"] and r["age"] <= s.backlog_max_days]
    if stale:
        F.append(Finding(WARNING, "Backlog & ageing", "stale", f"{len(stale)} open tickets with no update for {s.stale_days}+ days",
                         "Users hear nothing while the ticket waits; these are the tickets that become complaints.",
                         "Ask for an update on every ticket idle for more than a week; add it as a weekly hygiene check.",
                         owner=prov, tickets=[r["ticket"].id for r in stale]))
    unassigned = [r for r in ag if r["team"] == "(unassigned)"]
    if unassigned:
        F.append(Finding(WARNING, "Backlog & ageing", "unassigned", f"{len(unassigned)} open tickets with no team",
                         "Nobody's queue, nobody's problem.", "Route them today and fix the assignment rule that let them through.",
                         owner=prov, tickets=[r["ticket"].id for r in unassigned]))

    # escalations
    esc = escalations(d)
    prov_rows = [r for r in rows if r["provider"]]
    from_prov = [r for r in esc if r["from_org"] in ("provider", "offshore") and r["to_org"] == "internal"]
    rate = _pct(len(from_prov), len(prov_rows)) if prov_rows else None
    if rate is not None and rate > s.escalation_rate_max:
        top = Counter(r["ticket"].category or "(none)" for r in from_prov).most_common(3)
        F.append(Finding(WARNING, "Escalations & OLAs", "escalation_rate", f"{rate:g}% of the provider's tickets escalated to internal teams",
                         f"Target is at most {s.escalation_rate_max:g}%. Most escalated: " + ", ".join(f"{k} ({v})" for k, v in top) + ".",
                         "Agree which of these the provider should resolve at L1/L2 (knowledge article, access, tooling) and track the rate monthly.",
                         owner=prov, tickets=[r["ticket"].id for r in from_prov]))
    late_handoff = [r for r in esc if r["from_org"] in ("provider", "offshore") and r["handoff_share"] >= c.handoff_late_share]
    if late_handoff:
        F.append(Finding(WARNING, "Escalations & OLAs", "late_handoff", f"{len(late_handoff)} tickets escalated after half the window was used",
                         "The receiving team inherits a breach it cannot avoid.",
                         "Set a hand-off rule: if L1/L2 cannot fix it within a share of the target, escalate at that point, not at the end.",
                         owner=prov, tickets=[r["ticket"].id for r in late_handoff]))
    for x in ola_by_team(d, esc):
        if x["pct"] is not None and x["pct"] < s.ola_pct:
            ids = [r["ticket"].id for r in esc if r["to"] == x["team"] and r["ola_met"] is False]
            F.append(Finding(WARNING if x["pct"] >= s.ola_pct - 10 else CRITICAL, "Escalations & OLAs", "ola",
                             f"{x['team']}: OLA at {x['pct']:g}%",
                             f"{x['met']} of {x['measured']} escalations resolved within {x['ola_hours']:g} h (target {s.ola_pct:g}%); {x['open']} still open.",
                             "This one is on us, not the provider: review the queue with the team lead and agree the OLA is realistic or staff it.",
                             owner=x["team"], ref=x["team"], tickets=ids))
    no_ola = [x for x in ola_by_team(d, esc) if x["org"] == "internal" and x["ola_hours"] is None and x["received"] >= 3]
    for x in no_ola:
        F.append(Finding(INFO, "Escalations & OLAs", "no_ola", f"{x['team']}: {x['received']} escalations, no OLA defined",
                         "The provider's SLA depends on this team and nothing is agreed with it.",
                         "Add the team to `ola` in settings.json with the hours agreed with its lead.", owner="Service owner", ref=x["team"]))

    # coverage
    cov = coverage(d, rows)
    if cov["in_hours_pct"] is not None and cov["out_hours_pct"] is not None and cov["out_hours_n"] >= 10 \
            and cov["in_hours_pct"] - cov["out_hours_pct"] >= c.out_of_hours_gap:
        F.append(Finding(WARNING, "Coverage", "out_of_hours", "Out-of-hours response is worse than in hours",
                         f"Response within target: {cov['in_hours_pct']:g}% in business hours against {cov['out_hours_pct']:g}% outside "
                         f"({cov['out_hours_n']} tickets, {len(cov['out_hours_breached'])} late).",
                         "Check the follow-the-sun hand-over and the on-call rota with the provider; ask for the out-of-hours figure in the monthly pack.",
                         owner=prov, tickets=[r["ticket"].id for r in cov["out_hours_breached"]]))
    weekend_late = [r for r in rows if r["ticket"] in cov["weekend_urgent"] and r["resp_met"] is False]
    if weekend_late:
        F.append(Finding(CRITICAL, "Coverage", "urgent_out_of_hours", f"{len(weekend_late)} urgent incidents outside business hours without a timely response",
                         ", ".join(f"{r['ticket'].id} ({r['resp_min']:.0f} min)" for r in weekend_late[:6]),
                         "Walk through each one: who was paged, when, and why the response took that long.",
                         owner=prov, tickets=[r["ticket"].id for r in weekend_late]))
    unknown = cov["by_org"].get("unknown", 0)
    if unknown:
        F.append(Finding(INFO, "Coverage", "unknown_team", f"{unknown} tickets in teams not mapped to the provider or to us",
                         "They are left out of the escalation rate and the OLAs.",
                         "Add the teams to provider_teams, offshore_teams or internal_teams in settings.json.", owner="Service owner"))

    # quality
    q = quality(d, c)
    if q["reopen_pct"] is not None and q["reopen_pct"] > s.reopen_rate_max:
        F.append(Finding(WARNING if q["reopen_pct"] <= s.reopen_rate_max * 2 else CRITICAL, "Quality", "reopen",
                         f"Reopen rate {q['reopen_pct']:g}%", f"{len(q['reopened'])} of {q['resolved']} resolved tickets were reopened (target at most {s.reopen_rate_max:g}%).",
                         "Sample ten reopened tickets with the provider: closed without confirmation, wrong fix, or closed to stop the clock?",
                         owner=prov, tickets=[t.id for t in q["reopened"]]))
    if q["fcr_pct"] is not None and q["fcr_pct"] < s.fcr_min:
        F.append(Finding(WARNING, "Quality", "fcr", f"First-contact resolution {q['fcr_pct']:g}%",
                         f"Target at least {s.fcr_min:g}% of incidents, measured on {q['fcr_n']} tickets.",
                         "Review the top categories that leave L1 and give the service desk the access or the article to fix them.",
                         owner=prov))
    if q["csat_avg"] is not None and q["csat_avg"] < s.csat_min:
        F.append(Finding(WARNING, "Quality", "csat", f"Satisfaction {q['csat_avg']:g}/5",
                         f"Target {s.csat_min:g}; {len(q['csat_low'])} of {q['csat_n']} surveys scored {s.csat_low:g} or less.",
                         "Read the low-score comments before the meeting and bring three concrete cases.", owner=prov,
                         tickets=[t.id for t in q["csat_low"]]))
    elif q["csat_low_pct"] is not None and q["csat_low_pct"] >= 10:
        F.append(Finding(INFO, "Quality", "csat_low", f"{q['csat_low_pct']:g}% of surveys are detractors",
                         f"The average ({q['csat_avg']:g}) hides {len(q['csat_low'])} very unhappy users.",
                         "Call the detractors back; the pattern is usually one site or one category.", owner=prov,
                         tickets=[t.id for t in q["csat_low"]]))
    if q["late_window_pct"] is not None and q["late_window_pct"] > c.late_window_share_max:
        F.append(Finding(WARNING, "Quality", "late_window", f"{q['late_window_pct']:g}% of compliant tickets resolved in the last 10% of the window",
                         f"{len(q['late_window'])} tickets closed just before the deadline. Met on paper, slow in practice.",
                         "Show the distribution in the review and ask for mean time to resolve alongside the % met.", owner=prov,
                         tickets=[r["ticket"].id for r in q["late_window"]]))
    if q["pending_heavy"]:
        F.append(Finding(WARNING, "Quality", "pending", f"{len(q['pending_heavy'])} tickets spent most of their life with the clock stopped",
                         f"Over {c.pending_share_max:g}% of the elapsed time in a pending state, so the SLA clock did not run.",
                         "Agree when pending is legitimate (waiting for the user, parts on order) and audit a sample each month.", owner=prov,
                         tickets=[t.id for t in q["pending_heavy"]]))
    if q["instant"]:
        F.append(Finding(WARNING, "Quality", "instant_close", f"{len(q['instant'])} incidents resolved within {c.instant_close_min} minutes of creation",
                         "Logged after the fact, auto-closed or duplicates: either way they inflate the compliance figure.",
                         "Exclude them from the scorecard until the provider explains each pattern.", owner=prov,
                         tickets=[t.id for t in q["instant"]]))
    if q["no_category"]:
        F.append(Finding(INFO, "Quality", "no_category", f"{len(q['no_category'])} resolved tickets without a category",
                         "No category, no trend, no problem management.", "Make the category mandatory at resolution.", owner=prov,
                         tickets=[t.id for t in q["no_category"]]))

    # contract
    cr = credits(d, card)
    raw_pct = sum(x["credit_pct"] for x in cr)
    if cr and raw_pct:
        total_pct, amount = credit_total(d, cr)
        capped = f" (uncapped: {raw_pct:g}%, cap {s.credits_cap:g}%)" if total_pct < raw_pct else ""
        F.append(Finding(WARNING, "Contract", "credits", f"Service credits due: {total_pct:g}% of the monthly fee{capped}",
                         "; ".join(f"{x['type']} {x['priority']} {x['kind']} {x['pct']:g}% ({x['credit_pct']:g}%)" for x in cr if x["credit_pct"]) + ".",
                         "Put the credit on the agenda and in writing; waiving it is a decision, not an oversight.", owner="Service owner",
                         cost=amount))
    n = len(d.in_period)
    if s.baseline_volume and n > s.baseline_volume * 1.15:
        F.append(Finding(INFO, "Contract", "volume", f"Volume {n} tickets, {100 * (n / s.baseline_volume - 1):.0f}% over the contracted baseline",
                         f"Baseline {s.baseline_volume} a month. Sustained excess is the provider's usual reason for missed targets.",
                         "Check whether the excess is real demand or noise (duplicates, auto-logged alerts) before discussing capacity.",
                         owner="Service owner"))
    return sorted(F, key=lambda f: ({CRITICAL: 0, WARNING: 1, INFO: 2}[f.severity], AREAS.index(f.area)))


def area_status(findings: list[Finding]) -> dict[str, str]:
    st = {a: "ok" for a in AREAS}
    for f in findings:
        if f.severity == CRITICAL:
            st[f.area] = CRITICAL
        elif f.severity == WARNING and st[f.area] != CRITICAL:
            st[f.area] = WARNING
    return st
