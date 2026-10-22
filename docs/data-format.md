# Data format

Two files in one folder: `tickets.csv` (required) and `settings.json` (optional, but the review is only as good as the targets you put in it).

## tickets.csv

One row per ticket. Comma or semicolon separated, UTF-8 with or without BOM. Columns are matched by name, case-insensitive, with these aliases (English and Spanish, Jira and ServiceNow names):

| Field | Accepted headers | Notes |
|---|---|---|
| `id` | id, key, Issue key, Number, ticket | required |
| `created` | created, Created, Opened, opened_at | required; `2026-09-03 10:15`, `03/09/2026 10:15`, ISO with offset |
| `type` | type, Issue type, record type | incident / request (Service Request, RITM, sc_req_item → request). Default incident |
| `priority` | priority | P1-P4; also `1 - Critical`, Highest/High/Medium/Low, Blocker/Major/Minor. Default P3 |
| `first_response` | first response, responded, Time to first response | when the user first heard back. If empty, the resolution time is used |
| `resolved` | resolved, resolution date, resolved_at | empty = still open |
| `updated` | updated, last update, sys_updated_on | used for the "stale" check on open tickets |
| `status` | status, state | open/closed is inferred when `resolved` is empty |
| `team` | team, assignment group, resolver group | the queue that holds or closed the ticket |
| `tier` | tier, level | L1/L2/L3, informative |
| `site` | site, location, office | informative |
| `category` | category, service, component | empty counts as a data-quality finding |
| `channel` | channel, contact type, source | informative |
| `reopened` | reopened, reopen count | number, or yes/no |
| `escalated_to` | escalated to, escalation group | team that received the escalation; turns on the OLA checks |
| `escalated_at` | escalated at, escalation date | when; defaults to `created` |
| `pending_hours` | pending hours, on hold hours, waiting hours | hours with the clock stopped; subtracted from the resolution clock |
| `csat` | csat, satisfaction, rating | 1-5 |
| `fcr` | fcr, first contact resolution | yes/no |
| `vip` | vip | yes/no, informative |
| `summary` | summary, short description, title | shown in the tables |

Only `id` and `created` are mandatory; every check that needs a column it cannot find is skipped quietly.

Exporters: `scripts/Export-JiraTickets.ps1` for Jira Cloud. For ServiceNow, a list view export of `incident` and `sc_req_item` with the columns above (Number, Opened, Resolved, Priority, Assignment group, State, Reopen count, Contact type, Category, Short description) loads as-is.

## settings.json

```json
{
  "customer": "Northwind Traders",
  "provider": "Litware",
  "currency": "€",
  "provider_teams": ["Litware Onsite Madrid", "Litware Onsite Milan"],
  "offshore_teams": ["Litware Service Desk (Bengaluru)"],
  "internal_teams": ["Workplace Engineering", "Network", "Identity & M365"],
  "business_hours": {"start": "08:00", "end": "20:00", "days": [0, 1, 2, 3, 4]},
  "holidays": ["2026-12-25"],
  "sla": {
    "P1": {"response_min": 15, "resolve_hours": 4, "pct": 95, "business_hours": false},
    "P2": {"response_min": 30, "resolve_hours": 8, "pct": 95, "business_hours": false},
    "P3": {"response_min": 240, "resolve_hours": 24, "pct": 90, "business_hours": true},
    "P4": {"response_min": 480, "resolve_hours": 72, "pct": 90, "business_hours": true}
  },
  "request_sla": {"P3": {"response_min": 480, "resolve_hours": 40, "pct": 90, "business_hours": true}},
  "ola": {"Workplace Engineering": 16, "Network": 8, "Identity & M365": 8},
  "ola_pct": 90,
  "escalation_rate_max": 15,
  "reopen_rate_max": 5,
  "fcr_min": 65,
  "csat_min": 4.2,
  "csat_low": 2,
  "backlog_max_days": 30,
  "stale_days": 7,
  "monthly_fee": 48000,
  "credits": [[5, 2], [10, 5], [20, 10]],
  "credits_cap": 10,
  "baseline_volume": 1100,
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "as_of": "2026-10-22"
}
```

- `provider_teams` / `offshore_teams` / `internal_teams`: which queues belong to whom. A team in none of the lists is "unknown" and is reported. Offshore teams count as the provider for the SLA and the escalation rate; they are shown separately in Coverage.
- `sla` and `request_sla`: per priority, minutes to first response, hours to resolve, the % that must meet it and whether the clock runs in business hours only (`true`) or 24x7 (`false`). Missing priorities take the defaults shown in the demo.
- `ola`: hours an internal team has to resolve a ticket once it is escalated to it. The clock starts at `escalated_at` and runs in the same hours as the ticket's SLA. A team with escalations and no OLA is reported for information.
- `credits`: bands of `[points below the target %, % of the monthly fee]`; the worst matching band applies to each missed metric and the sum is capped at `credits_cap`. Leave `monthly_fee` at 0 to show credits as a % only.
- `baseline_volume`: contracted tickets per month; more than 15% above it is reported.
- `period_start` / `period_end` / `as_of`: the month under review and the review date. Without them, the last full calendar month before the latest date in the export is used (or the month of the data if it only covers one), and the review date is the latest date in the export. `--period 2026-09` and `--as-of` on the command line override both.

## What is measured where

| Measure | Population | Clock |
|---|---|---|
| Response | tickets created in the period with a first response, or still open | created → first response (business hours or 24x7 per target) |
| Resolution | tickets created in the period, resolved or open past the target | created → resolved, minus `pending_hours` |
| Backlog & ageing | tickets open at the review date, whenever created | calendar days |
| Escalations | tickets created in the period with `escalated_to` | created → escalated (hand-off), escalated → resolved (OLA) |
| Coverage | tickets with a response, split by whether they were created inside business hours | |
| Quality | tickets resolved in the period | |
| Contract | the scorecard | |

A ticket still open past its target counts as a breach already; one still inside its target is not counted either way.
