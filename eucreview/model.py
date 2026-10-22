"""Input model: a ticket export (CSV) and the service settings (JSON).

The CSV can come straight from Jira Service Management, ServiceNow or any other tool: columns are matched by
name through a list of aliases, priorities are normalised to P1-P4, and dates are accepted in ISO and in the
usual European formats. Anything that is not understood is left empty rather than guessed.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

PRIORITIES = ("P1", "P2", "P3", "P4")

# column aliases: canonical -> accepted header names (case-insensitive, spaces/underscores ignored)
ALIASES = {
    "id": ["id", "ticket", "key", "issue key", "number", "ticket id", "ref", "referencia", "numero"],
    "type": ["type", "issue type", "tipo", "category type", "record type"],
    "priority": ["priority", "prioridad"],
    "created": ["created", "opened", "opened at", "created at", "fecha creacion", "fecha de creacion", "creado", "abierto"],
    "first_response": ["first response", "first response at", "responded", "responded at", "time to first response",
                       "primera respuesta", "respondido"],
    "resolved": ["resolved", "resolved at", "resolution date", "fecha resolucion", "resuelto"],
    "updated": ["updated", "updated at", "last update", "sys updated on", "ultima actualizacion", "actualizado"],
    "status": ["status", "state", "estado"],
    "team": ["team", "assignment group", "resolver group", "group", "assignee group", "equipo", "grupo"],
    "tier": ["tier", "level", "support level", "nivel"],
    "site": ["site", "location", "office", "sede", "oficina", "ubicacion"],
    "category": ["category", "categoria", "service", "servicio", "component"],
    "channel": ["channel", "contact type", "source", "canal", "origen"],
    "reopened": ["reopened", "reopen count", "reopens", "reabierto", "reaperturas"],
    "escalated_to": ["escalated to", "escalation group", "escalated team", "escalado a"],
    "escalated_at": ["escalated at", "escalation date", "escalated", "fecha escalado", "escalado"],
    "pending_hours": ["pending hours", "on hold hours", "paused hours", "waiting hours", "horas pendiente",
                     "horas en espera", "business pending hours"],
    "csat": ["csat", "satisfaction", "rating", "survey score", "satisfaccion", "valoracion"],
    "fcr": ["fcr", "first contact resolution", "first call resolution", "resuelto en primer contacto"],
    "vip": ["vip", "vip user", "usuario vip"],
    "summary": ["summary", "short description", "title", "subject", "resumen", "descripcion corta"],
}
PRIORITY_MAP = {"p1": "P1", "1": "P1", "1 - critical": "P1", "critical": "P1", "highest": "P1", "blocker": "P1", "crítica": "P1",
                "critica": "P1", "p2": "P2", "2": "P2", "2 - high": "P2", "high": "P2", "alta": "P2", "major": "P2",
                "p3": "P3", "3": "P3", "3 - moderate": "P3", "moderate": "P3", "medium": "P3", "media": "P3", "normal": "P3",
                "p4": "P4", "4": "P4", "4 - low": "P4", "low": "P4", "baja": "P4", "lowest": "P4", "minor": "P4",
                "5": "P4", "5 - planning": "P4", "planning": "P4", "trivial": "P4"}
TYPE_MAP = {"incident": "incident", "incidencia": "incident", "it help": "incident", "problem": "incident", "fault": "incident",
            "request": "request", "service request": "request", "peticion": "request", "petición": "request",
            "requested item": "request", "sc req item": "request", "ritm": "request", "solicitud": "request",
            "access": "request", "hardware": "request"}
OPEN_STATES = {"open", "new", "in progress", "assigned", "pending", "on hold", "waiting", "waiting for customer",
               "waiting for support", "escalated", "reopened", "work in progress", "abierto", "nuevo", "en curso",
               "en progreso", "asignado", "pendiente", "en espera", "escalado", "reabierto"}
YES = {"yes", "y", "true", "1", "si", "sí", "x"}


def _norm(s: str) -> str:
    s = s.strip().lower().replace("_", " ").replace("-", " ")
    s = (s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return re.sub(r"\s+", " ", s)


_LOOKUP = {_norm(a): k for k, al in ALIASES.items() for a in al}


def map_columns(headers: list[str]) -> dict[str, str]:
    """Canonical field -> actual header in this file."""
    out: dict[str, str] = {}
    for h in headers:
        k = _LOOKUP.get(_norm(h.lstrip("﻿")))
        if k and k not in out:
            out[k] = h
    return out


_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d",
               "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%y %H:%M",
               "%d/%b/%y %I:%M %p", "%d/%b/%Y %I:%M %p", "%d/%b/%y %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if not v or v.lower() in ("none", "null", "n/a", "-"):
        return None
    v = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", v)  # drop fractions and offsets
    for f in _DT_FORMATS:
        try:
            return datetime.strptime(v, f)
        except ValueError:
            continue
    return None


def parse_date(value: str | None) -> date | None:
    d = parse_dt(value)
    return d.date() if d else None


def norm_priority(value: str | None) -> str:
    v = _norm(value or "")
    if v in PRIORITY_MAP:
        return PRIORITY_MAP[v]
    m = re.match(r"p?\s*([1-5])\b", v)
    return PRIORITY_MAP.get(m.group(1), "P3") if m else "P3"


def norm_type(value: str | None) -> str:
    v = _norm(value or "")
    for k, t in TYPE_MAP.items():
        if v == k or v.startswith(k):
            return t
    return "incident"


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    v = value.strip().replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


@dataclass
class Ticket:
    id: str
    type: str = "incident"                 # incident | request
    priority: str = "P3"
    created: datetime | None = None
    first_response: datetime | None = None
    resolved: datetime | None = None
    updated: datetime | None = None
    status: str = ""
    team: str = ""                         # resolver group that closed (or holds) the ticket
    tier: str = ""                         # L1 | L2 | L3
    site: str = ""
    category: str = ""
    channel: str = ""
    reopened: int = 0
    escalated_to: str = ""
    escalated_at: datetime | None = None
    pending_hours: float = 0.0             # time with the clock stopped (waiting for the user)
    csat: float | None = None              # 1-5
    fcr: bool | None = None
    vip: bool = False
    summary: str = ""

    @property
    def is_open(self) -> bool:
        if self.resolved:
            return False
        return not self.status or _norm(self.status) in OPEN_STATES or _norm(self.status) not in ("resolved", "closed",
                                                                                               "cancelled", "canceled",
                                                                                               "resuelto", "cerrado",
                                                                                               "cancelado", "done")


@dataclass
class Target:
    response_min: int            # minutes to first response
    resolve_hours: float         # hours to resolution
    pct: float = 95.0            # % of tickets that must meet it
    business_hours: bool = True  # clock runs in business hours only (False = 24x7)


@dataclass
class Settings:
    customer: str = "Customer"
    provider: str = "Provider"
    currency: str = "€"
    provider_teams: list[str] = field(default_factory=list)
    offshore_teams: list[str] = field(default_factory=list)
    internal_teams: list[str] = field(default_factory=list)
    business_start: time = time(8, 0)
    business_end: time = time(20, 0)
    business_days: tuple[int, ...] = (0, 1, 2, 3, 4)       # Monday=0
    holidays: list[date] = field(default_factory=list)
    sla: dict[str, Target] = field(default_factory=lambda: {
        "P1": Target(15, 4, 95, False), "P2": Target(30, 8, 95, False),
        "P3": Target(240, 24, 90, True), "P4": Target(480, 72, 90, True)})
    request_sla: dict[str, Target] = field(default_factory=lambda: {
        "P1": Target(60, 8, 90, True), "P2": Target(240, 24, 90, True),
        "P3": Target(480, 40, 90, True), "P4": Target(480, 80, 90, True)})
    ola: dict[str, float] = field(default_factory=dict)      # internal team -> hours to resolve after escalation
    ola_pct: float = 90.0
    escalation_rate_max: float = 15.0        # % of provider tickets escalated to internal teams
    reopen_rate_max: float = 5.0
    fcr_min: float = 65.0
    csat_min: float = 4.2
    csat_low: float = 2.0                     # scores at or below this count as detractors
    backlog_max_days: int = 30                # open tickets older than this are a finding
    stale_days: int = 7                       # open tickets with no update for this long
    monthly_fee: float = 0.0
    credits: list[tuple[float, float]] = field(default_factory=lambda: [(5.0, 2.0), (10.0, 5.0), (20.0, 10.0)])
    # credits: (points below target, % of monthly fee) — the worst matching band applies per metric
    credits_cap: float = 10.0                 # % of the monthly fee: the most the credits can add up to in a month
    baseline_volume: int = 0                  # contracted tickets per month (0 = not set)
    period_start: date | None = None
    period_end: date | None = None
    as_of: date | None = None

    def org(self, team: str) -> str:
        """provider | offshore | internal | unknown for a resolver group."""
        t = _norm(team)
        if any(_norm(x) == t for x in self.offshore_teams):
            return "offshore"
        if any(_norm(x) == t for x in self.provider_teams):
            return "provider"
        if any(_norm(x) == t for x in self.internal_teams):
            return "internal"
        if self.provider and _norm(self.provider) in t:
            return "provider"
        return "unknown"

    def is_provider(self, team: str) -> bool:
        return self.org(team) in ("provider", "offshore")

    def target(self, t: Ticket) -> Target:
        table = self.request_sla if t.type == "request" else self.sla
        return table.get(t.priority) or table["P3"]


def _time(v: str | None, default: time) -> time:
    if not v:
        return default
    h, m = (v.split(":") + ["0"])[:2]
    return time(int(h), int(m))


def _targets(raw: dict | None, default: dict[str, Target]) -> dict[str, Target]:
    if not raw:
        return default
    out = dict(default)
    for p, v in raw.items():
        base = default.get(p.upper(), Target(240, 24))
        out[p.upper()] = Target(int(v.get("response_min", base.response_min)), float(v.get("resolve_hours", base.resolve_hours)),
                                float(v.get("pct", base.pct)), bool(v.get("business_hours", base.business_hours)))
    return out


def load_settings(path: Path | None) -> Settings:
    if not path or not path.exists():
        return Settings()
    return settings_from_dict(json.loads(path.read_text(encoding="utf-8-sig")))


def settings_from_dict(raw: dict) -> Settings:
    s = Settings()
    for k in ("customer", "provider", "currency"):
        if raw.get(k):
            setattr(s, k, str(raw[k]))
    for k in ("provider_teams", "offshore_teams", "internal_teams"):
        if raw.get(k):
            setattr(s, k, [str(x) for x in raw[k]])
    bh = raw.get("business_hours") or {}
    s.business_start = _time(bh.get("start"), s.business_start)
    s.business_end = _time(bh.get("end"), s.business_end)
    if bh.get("days"):
        s.business_days = tuple(int(d) for d in bh["days"])
    s.holidays = [d for d in (parse_date(x) for x in raw.get("holidays", [])) if d]
    s.sla = _targets(raw.get("sla"), s.sla)
    s.request_sla = _targets(raw.get("request_sla"), s.request_sla)
    s.ola = {str(k): float(v) for k, v in (raw.get("ola") or {}).items()}
    for k in ("ola_pct", "escalation_rate_max", "reopen_rate_max", "fcr_min", "csat_min", "csat_low", "monthly_fee", "credits_cap"):
        if k in raw:
            setattr(s, k, float(raw[k]))
    for k in ("backlog_max_days", "stale_days", "baseline_volume"):
        if k in raw:
            setattr(s, k, int(raw[k]))
    if raw.get("credits"):
        s.credits = [(float(a), float(b)) for a, b in raw["credits"]]
    s.period_start = parse_date(raw.get("period_start"))
    s.period_end = parse_date(raw.get("period_end"))
    s.as_of = parse_date(raw.get("as_of"))
    return s


def load_tickets(path: Path) -> list[Ticket]:
    text = path.read_text(encoding="utf-8-sig")
    sample = text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    if not rows:
        return []
    cols = map_columns(list(rows[0].keys()))
    if "id" not in cols or "created" not in cols:
        raise ValueError(f"{path.name}: need at least an id and a created column (found: {', '.join(rows[0].keys())})")

    def g(r: dict, k: str) -> str | None:
        c = cols.get(k)
        return r.get(c) if c else None

    out: list[Ticket] = []
    for r in rows:
        tid = (g(r, "id") or "").strip()
        if not tid:
            continue
        reopened_raw = (g(r, "reopened") or "").strip().lower()
        reopened = int(float(reopened_raw)) if re.fullmatch(r"\d+(\.0)?", reopened_raw) else (1 if reopened_raw in YES else 0)
        fcr_raw = (g(r, "fcr") or "").strip().lower()
        out.append(Ticket(
            id=tid, type=norm_type(g(r, "type")), priority=norm_priority(g(r, "priority")),
            created=parse_dt(g(r, "created")), first_response=parse_dt(g(r, "first_response")),
            resolved=parse_dt(g(r, "resolved")), updated=parse_dt(g(r, "updated")),
            status=(g(r, "status") or "").strip(), team=(g(r, "team") or "").strip(), tier=(g(r, "tier") or "").strip().upper(),
            site=(g(r, "site") or "").strip(), category=(g(r, "category") or "").strip(), channel=(g(r, "channel") or "").strip(),
            reopened=reopened, escalated_to=(g(r, "escalated_to") or "").strip(), escalated_at=parse_dt(g(r, "escalated_at")),
            pending_hours=_float(g(r, "pending_hours")) or 0.0, csat=_float(g(r, "csat")),
            fcr=None if not fcr_raw else fcr_raw in YES, vip=(g(r, "vip") or "").strip().lower() in YES,
            summary=(g(r, "summary") or "").strip()))
    return out


@dataclass
class Data:
    tickets: list[Ticket]
    settings: Settings
    period_start: date
    period_end: date
    as_of: date

    @property
    def in_period(self) -> list[Ticket]:
        return [t for t in self.tickets if t.created and self.period_start <= t.created.date() <= self.period_end]

    @property
    def open_tickets(self) -> list[Ticket]:
        cut = datetime.combine(self.as_of, time(23, 59))
        return [t for t in self.tickets if t.created and t.created <= cut and (t.is_open or (t.resolved and t.resolved > cut))]


def load(folder: Path, as_of: date | None = None, period: tuple[date, date] | None = None) -> Data:
    folder = Path(folder)
    tickets_path = folder / "tickets.csv"
    if not tickets_path.exists():
        found = sorted(folder.glob("*.csv"))
        if not found:
            raise FileNotFoundError(f"no tickets.csv (or any .csv) in {folder}")
        tickets_path = found[0]
    s = load_settings(folder / "settings.json")
    tickets = load_tickets(tickets_path)
    dated = [t.created for t in tickets if t.created]
    if not dated:
        raise ValueError("no ticket has a created date")
    as_of = as_of or s.as_of or max(max(dated), max((t.resolved for t in tickets if t.resolved), default=max(dated))).date()
    if period:
        start, end = period
    elif s.period_start and s.period_end:
        start, end = s.period_start, s.period_end
    else:  # the last full calendar month before as_of, or the month of the data if everything is inside one month
        months = {(d.year, d.month) for d in dated}
        if len(months) == 1:
            y, m = months.pop()
        else:
            first = as_of.replace(day=1) - timedelta(days=1)
            y, m = first.year, first.month
        start = date(y, m, 1)
        end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return Data(tickets, s, start, end, as_of)
