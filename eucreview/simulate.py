"""Fictional demo data: Northwind Traders, an EUC service run by the provider Litware, September 2026.

Everything is invented and deterministic (seeded). The problems are placed on purpose so that every check has
something to say; see README "The demo data".
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .model import Settings, Target, Ticket, settings_from_dict

CUSTOMER, PROVIDER = "Northwind Traders", "Litware"
DESK = "Litware Service Desk (Bengaluru)"
ONSITE = {"Madrid": "Litware Onsite Madrid", "Milan": "Litware Onsite Milan", "Lisbon": "Litware Onsite Lisbon",
          "Warsaw": "Litware Onsite Madrid"}
INTERNAL = ["Workplace Engineering", "Network", "Identity & M365", "Business Applications"]
SITES = (("Madrid", 0.48), ("Milan", 0.24), ("Lisbon", 0.16), ("Warsaw", 0.12))
CATEGORIES = {
    "incident": [("Laptop / hardware", 0.17), ("Microsoft 365 / Outlook", 0.16), ("Teams / meeting rooms", 0.11),
                 ("Printing", 0.08), ("Network / Wi-Fi", 0.10), ("VPN / remote access", 0.09), ("Identity / password", 0.13),
                 ("Business application", 0.09), ("Mobile device", 0.05), ("", 0.02)],
    "request": [("New starter / leaver", 0.22), ("Software install", 0.26), ("Access request", 0.21), ("Hardware request", 0.14),
                ("Shared mailbox / distribution list", 0.09), ("Mobile device", 0.06), ("", 0.02)],
}
ESCALATE_TO = {"Network / Wi-Fi": "Network", "VPN / remote access": "Network", "Identity / password": "Identity & M365",
               "Microsoft 365 / Outlook": "Identity & M365", "Business application": "Business Applications",
               "Laptop / hardware": "Workplace Engineering", "Teams / meeting rooms": "Workplace Engineering",
               "Software install": "Workplace Engineering", "Access request": "Identity & M365"}
SUMMARIES = {
    "Laptop / hardware": ["Laptop does not boot after update", "Docking station not detected", "Battery drains in two hours",
                          "Blue screen twice a day", "Keyboard keys not working"],
    "Microsoft 365 / Outlook": ["Outlook keeps asking for password", "Cannot open shared calendar", "Mail stuck in outbox",
                                "OneDrive not syncing", "Excel crashes on open"],
    "Teams / meeting rooms": ["Room Milan 2.1 shows offline", "No audio in Teams call", "Cannot share screen in room",
                              "Teams Rooms console frozen"],
    "Printing": ["Printer offline on floor 3", "Print job stuck in queue", "Cannot print in colour"],
    "Network / Wi-Fi": ["Wi-Fi drops every few minutes", "No network on desk 4-12", "Slow connection on floor 1",
                        "Guest Wi-Fi not working in meeting rooms", "Switch port down in the warehouse", "Wi-Fi certificate expired on laptop"],
    "VPN / remote access": ["VPN disconnects after 10 minutes", "Cannot connect to VPN from home", "Citrix session does not open"],
    "Identity / password": ["Account locked", "MFA not receiving codes", "Cannot reset password", "Access denied to shared drive"],
    "Business application": ["ERP client error on login", "CRM report does not load", "Warehouse scanner app frozen"],
    "Mobile device": ["Company phone not enrolling", "Cannot open email on iPhone"],
    "New starter / leaver": ["New starter 7 Sept, Madrid sales", "Leaver: disable accounts and collect laptop"],
    "Software install": ["Install Visio", "Install Adobe Acrobat Pro", "Install Power BI Desktop"],
    "Access request": ["Access to finance shared folder", "Add to distribution list", "SAP role request"],
    "Hardware request": ["Second monitor", "Replacement headset", "Laptop for contractor"],
    "Shared mailbox / distribution list": ["Create shared mailbox", "Change DL owner"],
    "": ["Issue", "Problem with my computer", "Help needed"],
}
PERIOD = (date(2026, 9, 1), date(2026, 9, 30))
AS_OF = date(2026, 10, 22)

SETTINGS = {
    "customer": CUSTOMER, "provider": PROVIDER, "currency": "€",
    "provider_teams": list(dict.fromkeys(ONSITE.values())), "offshore_teams": [DESK], "internal_teams": INTERNAL,
    "business_hours": {"start": "08:00", "end": "20:00", "days": [0, 1, 2, 3, 4]},
    "holidays": [],
    "sla": {"P1": {"response_min": 15, "resolve_hours": 4, "pct": 95, "business_hours": False},
            "P2": {"response_min": 30, "resolve_hours": 8, "pct": 95, "business_hours": False},
            "P3": {"response_min": 240, "resolve_hours": 24, "pct": 90, "business_hours": True},
            "P4": {"response_min": 480, "resolve_hours": 72, "pct": 90, "business_hours": True}},
    "request_sla": {"P1": {"response_min": 60, "resolve_hours": 8, "pct": 90, "business_hours": True},
                    "P2": {"response_min": 240, "resolve_hours": 24, "pct": 90, "business_hours": True},
                    "P3": {"response_min": 480, "resolve_hours": 40, "pct": 90, "business_hours": True},
                    "P4": {"response_min": 480, "resolve_hours": 80, "pct": 90, "business_hours": True}},
    "ola": {"Workplace Engineering": 16, "Network": 8, "Identity & M365": 8},
    "ola_pct": 90, "escalation_rate_max": 15, "reopen_rate_max": 5, "fcr_min": 65, "csat_min": 4.2, "csat_low": 2,
    "backlog_max_days": 30, "stale_days": 7,
    "monthly_fee": 48000, "credits": [[5, 2], [10, 5], [20, 10]], "credits_cap": 10, "baseline_volume": 1100,
    "period_start": "2026-09-01", "period_end": "2026-09-30", "as_of": "2026-10-22",
}


def _pick(rng: random.Random, weighted: list[tuple[str, float]]) -> str:
    return rng.choices([w[0] for w in weighted], [w[1] for w in weighted])[0]


def add_clock(start: datetime, minutes: float, target: Target, s: Settings) -> datetime:
    """start + minutes, counting only business hours when the target says so."""
    if not target.business_hours:
        return start + timedelta(minutes=minutes)
    cur, left = start, minutes
    while True:
        day_ok = cur.weekday() in s.business_days and cur.date() not in s.holidays
        ws, we = datetime.combine(cur.date(), s.business_start), datetime.combine(cur.date(), s.business_end)
        if not day_ok or cur >= we:
            cur = datetime.combine(cur.date() + timedelta(days=1), s.business_start)
            continue
        if cur < ws:
            cur = ws
        avail = (we - cur).total_seconds() / 60
        if left <= avail:
            return cur + timedelta(minutes=left)
        left -= avail
        cur = we


def _created(rng: random.Random, start: date, end: date, out_of_hours: bool) -> datetime:
    days = (end - start).days + 1
    for _ in range(200):
        d = start + timedelta(days=rng.randrange(days))
        if out_of_hours:
            h, m = rng.choice([rng.randrange(0, 8), rng.randrange(20, 24)]), rng.randrange(60)
            if rng.random() < 0.35:
                d = d + timedelta(days=(5 - d.weekday()) % 7 or 6)  # push to the weekend sometimes
                h = rng.randrange(8, 22)
                if d > end:
                    continue
        else:
            if d.weekday() >= 5:
                continue
            h, m = rng.choices(range(8, 20), [8, 14, 15, 12, 9, 6, 7, 10, 9, 6, 3, 1])[0], rng.randrange(60)
        return datetime.combine(d, time(h, m))
    return datetime.combine(start, time(10, 0))


def build(seed: int = 28) -> tuple[list[Ticket], Settings]:
    rng = random.Random(seed)
    s = settings_from_dict(SETTINGS)
    tickets: list[Ticket] = []
    n_id = [10000]

    def new_id() -> str:
        n_id[0] += 1
        return f"NWT-{n_id[0]}"

    def make(typ: str, prio: str, created: datetime, *, resolve_share: float | None, resp_share: float, team: str,
             site: str, category: str, escalate: str = "", handoff_share: float = 0.2, ola_share: float | None = None,
             reopened: int = 0, pending_h: float = 0.0, csat: float | None = None, fcr: bool | None = None,
             tier: str = "L1", vip: bool = False, status: str = "") -> Ticket:
        tg = s.target(Ticket(id="x", type=typ, priority=prio))
        resp = add_clock(created, tg.response_min * resp_share, tg, s)
        resolved = None
        esc_at = None
        if escalate:
            esc_at = add_clock(created, tg.resolve_hours * 60 * handoff_share, tg, s)
            if ola_share is not None:
                ola_h = s.ola.get(escalate, tg.resolve_hours)
                resolved = add_clock(esc_at, ola_h * 60 * ola_share, tg, s)
        elif resolve_share is not None:
            resolved = add_clock(created, tg.resolve_hours * 60 * resolve_share + pending_h * 60, tg, s)
        if resolved and resolved < resp:
            resp = resolved
        summ = rng.choice(SUMMARIES.get(category, SUMMARIES[""]))
        updated = resolved or (esc_at or resp) + timedelta(days=rng.randrange(0, 4))
        return Ticket(id=new_id(), type=typ, priority=prio, created=created, first_response=resp, resolved=resolved,
                      updated=updated, status=status or ("Resolved" if resolved else "In progress"), team=team, tier=tier,
                      site=site, category=category, channel=rng.choices(["Portal", "Phone", "Email", "Chat", "Walk-up"],
                                                                        [38, 30, 18, 10, 4])[0],
                      reopened=reopened, escalated_to=escalate, escalated_at=esc_at, pending_hours=pending_h, csat=csat,
                      fcr=fcr, vip=vip, summary=summ)

    def csat_for(rng: random.Random, good: bool) -> float | None:
        if rng.random() > 0.31:
            return None
        if (not good and rng.random() < 0.5) or rng.random() < 0.04:
            return float(rng.choice([1, 2]))
        return float(rng.choices([3, 4, 5], [10, 38, 52])[0])

    # ---- incidents in the period ------------------------------------------------------------
    # resolution compliance per priority (placed): P1 6 tickets with one bad weekend; P2 88%; P3 91%; P4 95%
    plan = {"P1": (6, 0.99, 0.99), "P2": (74, 0.93, 0.90), "P3": (560, 0.96, 0.915), "P4": (190, 0.97, 0.95)}
    for prio, (n, resp_ok, res_ok) in plan.items():
        for i in range(n):
            ooh = rng.random() < (0.30 if prio in ("P1", "P2") else 0.12)
            created = _created(rng, *PERIOD, out_of_hours=ooh)
            site = _pick(rng, list(SITES))
            cat = _pick(rng, CATEGORIES["incident"])
            # out-of-hours response is worse on purpose
            r_ok = rng.random() < (resp_ok - (0.08 if prio in ("P1", "P2") else 0.16) if ooh else min(0.995, resp_ok + 0.02))
            resp_share = rng.uniform(0.05, 0.9) if r_ok else rng.uniform(1.1, 3.5)
            escal = ""
            team = DESK if rng.random() < 0.62 else ONSITE[site]
            fcr = None
            if team == DESK:
                fcr = rng.random() < 0.78
                if not fcr:
                    team = ONSITE[site] if rng.random() < 0.55 else team
            res_good = rng.random() < res_ok
            # escalation to internal teams (rate ~21% of provider tickets)
            if cat in ESCALATE_TO and rng.random() < (0.12 if prio == "P2" else 0.34) and prio != "P1":
                escal = ESCALATE_TO[cat]
                handoff = rng.uniform(0.05, 0.45) if rng.random() < 0.82 else rng.uniform(0.5, 0.95)
                ola_ok = {"Network": 0.71, "Identity & M365": 0.88, "Workplace Engineering": 0.93,
                          "Business Applications": 0.8}[escal]
                good = rng.random() < ola_ok
                ola_share = rng.uniform(0.1, 0.95) if good else rng.uniform(1.05, 2.4)
                t = make("incident", prio, created, resolve_share=None, resp_share=resp_share, team=team, site=site,
                         category=cat, escalate=escal, handoff_share=handoff, ola_share=ola_share, tier="L2",
                         reopened=1 if rng.random() < 0.06 else 0, csat=csat_for(rng, good), fcr=False if fcr is not None else None)
            else:
                if res_good:
                    share = rng.uniform(0.9, 0.995) if rng.random() < 0.34 else rng.uniform(0.03, 0.85)
                else:
                    share = rng.uniform(1.02, 2.6)
                pending = rng.uniform(4, 30) if rng.random() < 0.03 else 0.0
                t = make("incident", prio, created, resolve_share=share, resp_share=resp_share, team=team, site=site,
                         category=cat, pending_h=pending, reopened=1 if rng.random() < 0.105 else 0,
                         csat=csat_for(rng, res_good), fcr=fcr, tier="L1" if team == DESK else "L2",
                         vip=rng.random() < 0.04)
            tickets.append(t)
    # P1 on a Saturday night, paged late, resolved late
    t = make("incident", "P1", datetime(2026, 9, 12, 22, 40), resolve_share=1.55, resp_share=12.7, team=ONSITE["Madrid"],
             site="Madrid", category="Network / Wi-Fi", tier="L2", csat=1.0)
    t.summary = "Trading floor Madrid: no network on floor 2 (weekend batch)"
    tickets.append(t)
    # instant closes (logged after the fact)
    for _ in range(17):
        created = _created(rng, *PERIOD, out_of_hours=False)
        t = make("incident", "P3", created, resolve_share=0.0, resp_share=0.0, team=ONSITE["Milan"], site="Milan",
                 category="Printing", tier="L2", fcr=True)
        t.resolved = created + timedelta(minutes=1)
        t.first_response = t.resolved
        tickets.append(t)
    # tickets parked in pending for most of their life
    for _ in range(26):
        created = _created(rng, *PERIOD, out_of_hours=False)
        prio = rng.choice(["P3", "P3", "P4"])
        tg = s.target(Ticket(id="x", type="incident", priority=prio))
        pend = tg.resolve_hours * rng.uniform(1.2, 3.0)
        tickets.append(make("incident", prio, created, resolve_share=rng.uniform(0.2, 0.8), resp_share=0.4, team=DESK,
                            site=_pick(rng, list(SITES)), category="Laptop / hardware", pending_h=pend, fcr=False))
    # unmapped team
    for _ in range(9):
        tickets.append(make("incident", "P3", _created(rng, *PERIOD, out_of_hours=False), resolve_share=rng.uniform(0.2, 0.9),
                            resp_share=0.3, team="Facilities", site="Madrid", category="Teams / meeting rooms", tier="L2"))

    # ---- requests in the period -------------------------------------------------------------
    rplan = {"P2": (38, 0.93), "P3": (330, 0.84), "P4": (120, 0.93)}
    for prio, (n, res_ok) in rplan.items():
        for _ in range(n):
            created = _created(rng, *PERIOD, out_of_hours=rng.random() < 0.06)
            site = _pick(rng, list(SITES))
            cat = _pick(rng, CATEGORIES["request"])
            good = rng.random() < res_ok
            share = rng.uniform(0.1, 0.95) if good else rng.uniform(1.05, 2.2)
            escal = ESCALATE_TO.get(cat, "") if prio != "P2" and rng.random() < 0.22 else ""
            if escal:
                t = make("request", prio, created, resolve_share=None, resp_share=rng.uniform(0.1, 0.8), team=DESK, site=site,
                         category=cat, escalate=escal, handoff_share=rng.uniform(0.05, 0.6),
                         ola_share=rng.uniform(0.1, 0.9) if rng.random() < 0.86 else rng.uniform(1.05, 2.0),
                         csat=csat_for(rng, True))
            else:
                t = make("request", prio, created, resolve_share=share, resp_share=rng.uniform(0.05, 0.9) if rng.random() < 0.94 else rng.uniform(1.1, 2.0), team=DESK, site=site,
                         category=cat, csat=csat_for(rng, good), reopened=1 if rng.random() < 0.03 else 0)
            tickets.append(t)

    # ---- still open at the review date ------------------------------------------------------
    def open_ticket(created: datetime, typ: str, prio: str, team: str, cat: str, idle_days: int, escalate: str = "") -> Ticket:
        t = make(typ, prio, created, resolve_share=None, resp_share=0.5, team=team, site=_pick(rng, list(SITES)), category=cat,
                 escalate=escalate, handoff_share=0.3, status="In progress" if idle_days < 7 else "Pending")
        t.updated = datetime.combine(AS_OF - timedelta(days=idle_days), time(11, 0))
        return t

    for _ in range(12):   # Network: old backlog on the OLA
        tickets.append(open_ticket(datetime(2026, 7, rng.randrange(1, 29), 10, 0), "incident", "P3", DESK, "Network / Wi-Fi",
                                   rng.randrange(8, 40), escalate="Network"))
    for _ in range(6):    # provider onsite: old requests
        tickets.append(open_ticket(datetime(2026, 8, rng.randrange(1, 20), 9, 30), "request", "P3", ONSITE["Madrid"],
                                   "Hardware request", rng.randrange(10, 30)))
    for _ in range(3):
        tickets.append(open_ticket(datetime(2026, 8, rng.randrange(1, 28), 15, 0), "incident", "P4", ONSITE["Lisbon"],
                                   "Printing", rng.randrange(30, 50)))
    def cat_for(typ: str) -> str:
        return rng.choice(["Laptop / hardware", "Microsoft 365 / Outlook", "Teams / meeting rooms", "Printing"] if typ == "incident"
                          else ["Software install", "Access request", "Hardware request"])

    for _ in range(25):   # recent but stale
        typ = rng.choice(["incident", "request"])
        tickets.append(open_ticket(datetime(2026, 9, rng.randrange(24, 31), 12, 0) + timedelta(days=rng.randrange(0, 18)),
                                   typ, rng.choice(["P3", "P4"]), DESK, cat_for(typ), rng.randrange(7, 15)))
    for _ in range(31):   # recent, active
        typ = rng.choice(["incident", "request"])
        tickets.append(open_ticket(datetime(2026, 10, rng.randrange(12, 22), 9, 0), typ, rng.choice(["P3", "P4", "P2"]),
                                   rng.choice([DESK, ONSITE["Madrid"], ONSITE["Milan"]]), cat_for(typ), rng.randrange(0, 4)))
    for _ in range(4):    # unassigned
        t = open_ticket(datetime(2026, 10, rng.randrange(14, 21), 9, 0), "incident", "P3", "", "Mobile device", 2)
        t.team = ""
        tickets.append(t)
    # two P2 incidents open past their target
    for d in (datetime(2026, 9, 29, 16, 10), datetime(2026, 9, 30, 9, 5)):
        tickets.append(open_ticket(d, "incident", "P2", ONSITE["Milan"], "Business application", 3, escalate="Business Applications"))

    tickets.sort(key=lambda t: t.created)
    for i, t in enumerate(tickets, 10001):   # chronological ticket numbers, like a real tool
        t.id = f"NWT-{i}"
    return tickets, s


FIELDS = ["id", "type", "priority", "created", "first_response", "resolved", "updated", "status", "team", "tier", "site",
          "category", "channel", "reopened", "escalated_to", "escalated_at", "pending_hours", "csat", "fcr", "vip", "summary"]


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def write(folder: Path, seed: int = 28) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tickets, _ = build(seed)
    with open(folder / "tickets.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for t in tickets:
            w.writerow([_fmt(getattr(t, f)) for f in FIELDS])
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder
