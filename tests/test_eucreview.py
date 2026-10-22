import csv
import json
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from eucreview import checks, report, simulate
from eucreview.checks import Config, business_minutes, run_all
from eucreview.model import Data, Settings, Target, Ticket, load, load_tickets, norm_priority, norm_type, parse_dt, settings_from_dict

S = Settings()


def tk(**kw) -> Ticket:
    base = dict(id="T1", type="incident", priority="P3", created=datetime(2026, 9, 7, 10, 0), team="Desk", status="Resolved",
                category="Laptop")
    base.update(kw)
    return Ticket(**base)


def data(tickets, settings=None, as_of=date(2026, 10, 5)) -> Data:
    s = settings or settings_from_dict({"provider": "Prov", "provider_teams": ["Desk", "Onsite"], "offshore_teams": ["Desk"],
                                        "internal_teams": ["Network", "Identity"], "ola": {"Network": 8}, "monthly_fee": 1000})
    return Data(tickets, s, date(2026, 9, 1), date(2026, 9, 30), as_of)


class Parsing(unittest.TestCase):
    def test_dates_and_priorities(self):
        self.assertEqual(parse_dt("2026-09-03 10:15"), datetime(2026, 9, 3, 10, 15))
        self.assertEqual(parse_dt("03/09/2026 10:15"), datetime(2026, 9, 3, 10, 15))
        self.assertEqual(parse_dt("2026-09-03T10:15:00.000+0200"), datetime(2026, 9, 3, 10, 15))
        self.assertIsNone(parse_dt(""))
        for raw, want in (("1 - Critical", "P1"), ("Highest", "P1"), ("High", "P2"), ("P3", "P3"), ("Low", "P4"), ("5 - Planning", "P4"), ("", "P3")):
            self.assertEqual(norm_priority(raw), want, raw)
        self.assertEqual(norm_type("Service Request"), "request")
        self.assertEqual(norm_type("Incidencia"), "incident")
        self.assertEqual(norm_type("sc_req_item"), "request")

    def test_servicenow_style_csv_with_bom_and_semicolons(self):
        text = ("﻿Number;Opened;Resolved;Priority;Assignment group;State;Reopen count;Contact type\n"
                "INC001;03/09/2026 10:00;03/09/2026 12:00;2 - High;Desk;Closed;1;Phone\n"
                "RITM02;04/09/2026 09:00;;3 - Moderate;Onsite;Work in Progress;;Portal\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tickets.csv"
            p.write_text(text, encoding="utf-8")
            ts = load_tickets(p)
        self.assertEqual([t.id for t in ts], ["INC001", "RITM02"])
        self.assertEqual(ts[0].priority, "P2")
        self.assertEqual(ts[0].reopened, 1)
        self.assertFalse(ts[0].is_open)
        self.assertTrue(ts[1].is_open)
        self.assertEqual(ts[1].channel, "Portal")

    def test_load_picks_last_full_month(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tickets.csv"
            with open(p, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "created", "resolved", "priority"])
                w.writerow(["A", "2026-08-10 10:00", "2026-08-10 11:00", "P3"])
                w.writerow(["B", "2026-09-10 10:00", "2026-09-10 11:00", "P3"])
                w.writerow(["C", "2026-10-02 10:00", "", "P3"])
            dd = load(Path(d))
        self.assertEqual((dd.period_start, dd.period_end), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual([t.id for t in dd.in_period], ["B"])


class Clocks(unittest.TestCase):
    def test_business_minutes_skip_nights_and_weekends(self):
        # Friday 18:00 -> Monday 09:00 = 2 h Friday + 1 h Monday
        self.assertEqual(business_minutes(datetime(2026, 9, 4, 18, 0), datetime(2026, 9, 7, 9, 0), S), 180)
        s = settings_from_dict({"holidays": ["2026-09-07"]})
        self.assertEqual(business_minutes(datetime(2026, 9, 4, 18, 0), datetime(2026, 9, 8, 9, 0), s), 180)
        self.assertEqual(business_minutes(datetime(2026, 9, 7, 10, 0), datetime(2026, 9, 7, 9, 0), S), 0)

    def test_add_clock_matches_business_minutes(self):
        start = datetime(2026, 9, 4, 17, 0)  # Friday
        end = simulate.add_clock(start, 600, Target(60, 10, business_hours=True), S)
        self.assertEqual(end, datetime(2026, 9, 7, 15, 0))
        self.assertEqual(business_minutes(start, end, S), 600)


class SLA(unittest.TestCase):
    def test_pending_time_is_subtracted_and_24x7_clock(self):
        # P2 incident 24x7, 8 h target: 10 h elapsed with 3 h pending = met
        t = tk(priority="P2", created=datetime(2026, 9, 5, 22, 0), first_response=datetime(2026, 9, 5, 22, 10),
               resolved=datetime(2026, 9, 6, 8, 0), pending_hours=3)
        r = checks.sla_rows(data([t]))[0]
        self.assertTrue(r["res_met"])
        self.assertTrue(r["resp_met"])
        t.pending_hours = 0
        self.assertFalse(checks.sla_rows(data([t]))[0]["res_met"])

    def test_open_ticket_past_target_counts_as_breach_and_scorecard(self):
        ts = [tk(id="A", first_response=datetime(2026, 9, 7, 10, 30), resolved=datetime(2026, 9, 7, 15, 0)),
              tk(id="B", resolved=None, status="Open"),                       # open since 7 Sep: past 24 business hours
              tk(id="C", first_response=datetime(2026, 9, 7, 18, 0), resolved=datetime(2026, 9, 7, 18, 30))]  # 8 h response
        card = checks.scorecard(data(ts))
        self.assertEqual(len(card), 1)
        r = card[0]
        self.assertEqual((r["n"], r["open"], r["res_breached"], r["resp_breached"]), (3, 1, 1, 2))   # B: no response yet
        self.assertEqual(r["res_pct"], 66.7)
        kinds = {(b["ticket"].id, b["kind"]) for b in checks.breaches(data(ts))}
        self.assertEqual(kinds, {("B", "resolution"), ("B", "response"), ("C", "response")})

    def test_last_minute_resolution(self):
        t = tk(first_response=datetime(2026, 9, 7, 10, 5), resolved=simulate.add_clock(datetime(2026, 9, 7, 10, 0), 24 * 60 * 0.95,
                                                                                            Target(240, 24), S))
        self.assertTrue(checks.sla_rows(data([t]))[0]["late_window"])


class Backlog(unittest.TestCase):
    def test_ageing_buckets_stale_and_escalated_owner(self):
        ts = [tk(id="old", created=datetime(2026, 7, 1, 9, 0), resolved=None, status="Pending", updated=datetime(2026, 8, 1),
                 escalated_to="Network", escalated_at=datetime(2026, 7, 2)),
              tk(id="new", created=datetime(2026, 10, 4, 9, 0), resolved=None, status="Open", updated=datetime(2026, 10, 4)),
              tk(id="done", resolved=datetime(2026, 9, 8))]
        ag = checks.ageing(data(ts))
        self.assertEqual([r["ticket"].id for r in ag], ["old", "new"])
        self.assertEqual((ag[0]["bucket"], ag[0]["team"], ag[0]["stale"]), ("over 30 days", "Network", True))
        self.assertEqual((ag[1]["bucket"], ag[1]["stale"]), ("0-2 days", False))
        by = {x["team"]: x for x in checks.ageing_by_team(data(ts), ag)}
        self.assertEqual(by["Network"]["old"], 1)
        f = [f for f in run_all(data(ts)) if f.code == "old_backlog"]
        self.assertEqual(f[0].owner, "Network")


class Escalations(unittest.TestCase):
    def test_ola_clock_handoff_and_rate(self):
        esc_at = datetime(2026, 9, 7, 11, 0)
        ts = [tk(id="E1", escalated_to="Network", escalated_at=esc_at, first_response=datetime(2026, 9, 7, 10, 10),
                 resolved=simulate.add_clock(esc_at, 7 * 60, Target(240, 24), S)),
              tk(id="E2", escalated_to="Network", escalated_at=datetime(2026, 9, 8, 10, 0), first_response=datetime(2026, 9, 7, 10, 10),
                 resolved=datetime(2026, 9, 9, 18, 0)),
              tk(id="E3", escalated_to="Identity", escalated_at=esc_at, first_response=esc_at, resolved=datetime(2026, 9, 7, 12, 0)),
              tk(id="N1", first_response=datetime(2026, 9, 7, 10, 10), resolved=datetime(2026, 9, 7, 12, 0))]
        d = data(ts)
        esc = {r["ticket"].id: r for r in checks.escalations(d)}
        self.assertTrue(esc["E1"]["ola_met"])
        self.assertFalse(esc["E2"]["ola_met"])
        self.assertGreaterEqual(esc["E2"]["handoff_share"], 0.5)   # escalated the next day: 12 business hours of 24
        self.assertIsNone(esc["E3"]["ola_met"])               # no OLA for Identity
        ola = {x["team"]: x for x in checks.ola_by_team(d, list(esc.values()))}
        self.assertEqual(ola["Network"]["pct"], 50.0)
        codes = {f.code: f for f in run_all(d)}
        self.assertIn("escalation_rate", codes)      # 3 of 4 provider tickets
        self.assertIn("late_handoff", codes)
        self.assertEqual(codes["ola"].owner, "Network")


class Coverage(unittest.TestCase):
    def test_out_of_hours_gap_and_urgent_weekend(self):
        ts = []
        for i in range(20):
            ts.append(tk(id=f"I{i}", created=datetime(2026, 9, 7, 10, i), first_response=datetime(2026, 9, 7, 10, i + 1),
                         resolved=datetime(2026, 9, 7, 12, 0)))
        for i in range(10):
            late = i < 4
            ts.append(tk(id=f"O{i}", priority="P2", created=datetime(2026, 9, 5, 23, 0), first_response=datetime(2026, 9, 5, 23, 50 if late else 10),
                         resolved=datetime(2026, 9, 6, 2, 0)))
        d = data(ts)
        cov = checks.coverage(d)
        self.assertEqual((cov["in_hours_pct"], cov["out_hours_pct"]), (100.0, 60.0))
        self.assertEqual(len(cov["weekend_urgent"]), 10)
        codes = {f.code for f in run_all(d)}
        self.assertIn("out_of_hours", codes)
        self.assertIn("urgent_out_of_hours", codes)


class Quality(unittest.TestCase):
    def test_reopen_fcr_csat_pending_instant(self):
        ts = [tk(id="R", reopened=2, fcr=False, csat=1, resolved=datetime(2026, 9, 7, 12, 0)),
              tk(id="I", fcr=True, csat=5, resolved=datetime(2026, 9, 7, 10, 1)),
              tk(id="P", fcr=False, resolved=datetime(2026, 9, 8, 10, 0), pending_hours=9, category=""),
              tk(id="Q", type="request", resolved=datetime(2026, 9, 7, 11, 0))]
        q = checks.quality(data(ts))
        self.assertEqual(q["reopen_pct"], 25.0)
        self.assertEqual(q["fcr_pct"], 33.3)
        self.assertEqual(q["csat_avg"], 3.0)
        self.assertEqual([t.id for t in q["instant"]], ["I"])
        self.assertEqual([t.id for t in q["pending_heavy"]], ["P"])   # 9 h pending of 12 business hours
        self.assertEqual([t.id for t in q["no_category"]], ["P"])
        codes = {f.code for f in run_all(data(ts))}
        for c in ("reopen", "fcr", "csat", "pending", "instant_close", "no_category"):
            self.assertIn(c, codes)


class Contract(unittest.TestCase):
    def test_credits_bands_and_cap(self):
        s = settings_from_dict({"provider": "Prov", "provider_teams": ["Desk"], "monthly_fee": 1000, "credits": [[5, 2], [10, 5]],
                                "credits_cap": 6})
        ts = [tk(id=f"T{i}", priority="P2", first_response=datetime(2026, 9, 7, 10, 5),
                 resolved=datetime(2026, 9, 7, 11, 0) if i < 8 else datetime(2026, 9, 8, 11, 0)) for i in range(10)]
        d = data(ts, s)
        cr = checks.credits(d)
        self.assertEqual([(x["kind"], x["credit_pct"]) for x in cr], [("resolution", 5.0)])   # 80% vs 95%: 15 points -> 5%
        self.assertEqual(checks.credit_total(d, cr), (5.0, 50.0))
        s.credits_cap = 3
        self.assertEqual(checks.credit_total(d, cr), (3.0, 30.0))

    def test_clean_service_has_no_findings(self):
        ts = [tk(id=f"T{i}", first_response=datetime(2026, 9, 7, 10, 5), resolved=datetime(2026, 9, 7, 12, 0), category="Laptop",
                 fcr=True, csat=5) for i in range(30)]
        self.assertEqual(run_all(data(ts)), [])
        self.assertEqual(set(checks.area_status([]).values()), {"ok"})


class Demo(unittest.TestCase):
    def test_demo_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir, out = Path(tmp) / "data", Path(tmp) / "out"
            simulate.write(data_dir)
            self.assertTrue((data_dir / "tickets.csv").exists())
            json.loads((data_dir / "settings.json").read_text())
            from eucreview.cli import run
            sm = run(data_dir, out, "Demo", Config())
            for name in ("report.html", "service-review.md", "scorecard.csv", "breaches.csv", "ageing.csv", "escalations.csv",
                         "actions.csv", "findings.csv"):
                self.assertTrue((out / name).exists(), name)
            d = load(data_dir)
            self.assertEqual((d.period_start, d.as_of), (date(2026, 9, 1), date(2026, 10, 22)))
            codes = {f.code for f in run_all(d)}
            for c in ("sla_resolution", "urgent_open", "old_backlog", "stale", "unassigned", "escalation_rate", "late_handoff", "ola",
                      "no_ola", "out_of_hours", "urgent_out_of_hours", "unknown_team", "reopen", "fcr", "late_window", "pending",
                      "instant_close", "no_category", "credits", "volume"):
                self.assertIn(c, codes)
            self.assertEqual(sm["credit_pct"], 10.0)
            html = (out / "report.html").read_text()
            self.assertIn("Northwind Traders", html)
            self.assertIn("SLA scorecard", html)
            md = (out / "service-review.md").read_text()
            self.assertIn("## 2. To raise with Litware", md)
            self.assertIn("## 3. What we owe the provider", md)
            rows = list(csv.DictReader(open(out / "scorecard.csv")))
            self.assertEqual(len(rows), 7)

    def test_demo_is_deterministic(self):
        a, _ = simulate.build()
        b, _ = simulate.build()
        self.assertEqual([(t.id, t.created, t.resolved) for t in a], [(t.id, t.created, t.resolved) for t in b])


if __name__ == "__main__":
    unittest.main()
