"""Checks for the kit's deterministic parts. Run from the repo root:

    python3 -m unittest discover -s tests -v

Standard library only. Uses synthetic data in temporary folders.
"""
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".claude" / "skills" / "uat-ledger" / "scripts" / "uat_ledger.py"
BUILD = ROOT / "tools" / "build_agent.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = load(SCRIPT, "uat_ledger")
B = load(BUILD, "build_agent")


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def bug(key, release, **over):
    rec = {"bug_key": key, "release": release, "summary": "s", "status": "Open", "severity": "medium",
           "depth": "standard", "root_cause_status": "Suspected", "category": "TEST", "gap": "g",
           "escape_reason": "missing-test", "catch_level": "unit", "ac_issue": "none", "layer": "rules",
           "component": "rating", "app": "PolicyCenter", "next_step": "n", "impact_score": 3}
    rec.update(over)
    return rec


def make(tmp, counts, statuses=None, bugs=None, exposure=None):
    root = Path(tmp)
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    with (root / "ledger" / "releases.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(L.RELEASE_COLUMNS)
        for i, _ in enumerate(counts):
            st = (statuses or ["closed"] * len(counts))[i]
            w.writerow([f"R{i + 1}", i + 1, st, "", "", (exposure or [""] * len(counts))[i], "", "", "", ""])
    recs = bugs if bugs is not None else [bug(f"K-{i}-{j}", f"R{i + 1}") for i, c in enumerate(counts) for j in range(c)]
    with (root / "ledger" / "bugs.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return root


class Validate(unittest.TestCase):
    def errors(self, recs, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [1], bugs=recs)
            return L.validate_ledger(root, **kw)[0]

    def test_clean_record_passes(self):
        self.assertEqual(self.errors([bug("A-1", "R1")]), [])

    def test_confirmed_needs_evidence(self):
        errs = self.errors([bug("A-1", "R1", root_cause_status="Confirmed")])
        self.assertTrue(any("Confirmed cause needs at least one evidence" in e for e in errs))
        ok = bug("A-1", "R1", root_cause_status="Confirmed", evidence=[{"type": "pr", "ref": "PR-9"}])
        self.assertEqual(self.errors([ok]), [])

    def test_quick_cannot_confirm(self):
        rec = bug("A-1", "R1", depth="quick", root_cause_status="Confirmed", evidence=[{"type": "pr", "ref": "PR-9"}])
        self.assertTrue(any("Quick depth cannot" in e for e in self.errors([rec])))

    def test_origin_needs_proof(self):
        errs = self.errors([bug("A-1", "R1", change_origin="agent-assisted")])
        self.assertTrue(any("needs origin_evidence" in e for e in errs))
        self.assertEqual(self.errors([bug("A-1", "R1", change_origin="unknown")]), [])

    def test_unknown_release_enum_duplicate_and_score(self):
        self.assertTrue(any("not in releases.csv" in e for e in self.errors([bug("A-1", "R9")])))
        self.assertTrue(any("not in the codebook" in e for e in self.errors([bug("A-1", "R1", category="NOPE")])))
        self.assertTrue(any("appears 2 times" in e for e in self.errors([bug("A-1", "R1"), bug("A-1", "R1")])))
        self.assertTrue(any("impact_score" in e for e in self.errors([bug("A-1", "R1", impact_score=9)])))

    def test_standard_depth_requires_analysis_fields(self):
        rec = bug("A-1", "R1")
        del rec["catch_level"]
        self.assertTrue(any("requires 'catch_level'" in e for e in self.errors([rec])))
        quick = {k: v for k, v in bug("A-1", "R1", depth="quick").items() if k in L.REQUIRED_ALWAYS}
        self.assertEqual(self.errors([quick]), [])

    def test_every_input_bug_is_accounted_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [1], bugs=[bug("A-1", "R1")])
            expect = root / "expect.txt"
            expect.write_text("A-1\nA-2\n", encoding="utf-8")
            errs = L.validate_ledger(root, expect=str(expect))[0]
            self.assertEqual(errs, ["A-2: expected input bug is not in the ledger"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [2])
            self.assertEqual(run("validate", "--root", str(root)).returncode, 0)
            make(tmp, [1], bugs=[bug("A-1", "R1", root_cause_status="Confirmed")])
            self.assertEqual(run("validate", "--root", str(root)).returncode, 1)


class Stats(unittest.TestCase):
    def test_counts_and_shares(self):
        recs = [bug("A-1", "R1", catch_level="unit", ac_issue="ambiguous", severity="high"),
                bug("A-2", "R1", catch_level="api", ac_issue="none", severity="critical"),
                bug("A-3", "R1", catch_level="uat-only", ac_issue="none"),
                bug("A-4", "R1", catch_level="unknown", ac_issue="unknown")]
        with tempfile.TemporaryDirectory() as tmp:
            s = L.compute_stats(make(tmp, [4], bugs=recs))
        c = s["cumulative"]
        self.assertEqual(c["bugs"], 4)
        self.assertEqual(c["high_critical"], 2)
        self.assertEqual(c["automatable_before_uat"], {"count": 2, "classified": 3, "share_of_classified": 0.6667, "share_of_all": 0.5})
        self.assertEqual(c["ac_related"]["count"], 1)
        self.assertEqual(c["ac_related"]["share_of_classified"], 0.3333)
        self.assertEqual(sum(c["by_category"].values()), 4)

    def test_patterns_need_two_bugs_and_keep_keys(self):
        recs = [bug("A-1", "R1"), bug("A-2", "R2"), bug("A-3", "R2", component="forms")]
        with tempfile.TemporaryDirectory() as tmp:
            s = L.compute_stats(make(tmp, [1, 2], bugs=recs))
        self.assertEqual(len(s["patterns"]), 1)
        self.assertEqual(s["patterns"][0]["bug_keys"], ["A-1", "A-2"])
        self.assertEqual(s["patterns"][0]["releases"], ["R1", "R2"])

    def test_open_release_is_excluded_from_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = L.compute_stats(make(tmp, [3, 4, 9], statuses=["closed", "closed", "open"]))
        self.assertEqual(s["trend"]["bugs"], [3, 4])
        self.assertEqual(s["trend"]["direction"]["bugs"], "insufficient history")
        self.assertEqual(s["cumulative"]["bugs"], 16)

    def test_rates_and_exposure_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = L.compute_stats(make(tmp, [5, 10], exposure=[50, 40]), trusted=("stories",))
        self.assertEqual(s["per_release"][0]["rates_per_100"], {"stories": 10.0})
        self.assertEqual(s["per_release"][1]["rates_per_100"], {"stories": 25.0})
        self.assertTrue(s["exposure"]["stories"]["trusted"] and s["exposure"]["stories"]["complete"])
        self.assertFalse(s["exposure"]["merged_prs"]["complete"])


class Forecast(unittest.TestCase):
    def fc(self, counts, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            return L.compute_forecast(make(tmp, counts, exposure=kw.pop("exposure", None)), **kw)

    def test_stage_0_shows_nothing(self):
        f = self.fc([10, 12])
        self.assertEqual((f["stage"], f["forecast"]), (0, None))

    def test_stage_1_is_the_historical_range(self):
        f = self.fc([14, 11, 16, 12])
        self.assertEqual(f["stage"], 1)
        self.assertEqual((f["forecast"]["low"], f["forecast"]["high"], f["forecast"]["point"]), (11, 16, 13.0))
        self.assertEqual(f["forecast"]["label"], "indicative")

    def test_stage_2_backtest_matches_hand_calculation(self):
        f = self.fc([14, 11, 16, 12, 15, 10, 13])
        mae = {m["method"]: m["backtest_mae"] for m in f["methods"]}
        self.assertEqual(mae["naive_last"], 3.75)      # |12-16| |15-12| |10-15| |13-10| -> 15 / 4
        self.assertEqual(mae["mean"], 1.754)           # 1.667 + 1.75 + 3.6 + 0 -> 7.017 / 4
        self.assertEqual(mae["median"], 2.0)
        self.assertEqual(f["best_method"], "mean")
        self.assertTrue(f["beat_naive"])
        self.assertEqual((f["forecast"]["point"], f["forecast"]["low"], f["forecast"]["high"]), (13.0, 10.5, 15.5))

    def test_naive_is_reported_when_nothing_beats_it(self):
        f = self.fc([10, 11, 12, 13, 14, 15, 16])     # steady climb: last value wins
        self.assertFalse(f["beat_naive"])
        self.assertEqual(f["forecast"]["label"], "naive baseline")
        self.assertEqual(f["forecast"]["point"], 16)

    def test_exposure_is_used_only_when_trusted_complete_and_planned(self):
        counts, exp = [10, 20, 30, 40, 50, 60], [10, 20, 30, 40, 50, 60]
        plain = self.fc(counts, exposure=exp)
        self.assertIsNone(plain["exposure_used"])
        self.assertNotIn("rate_mean", [m["method"] for m in plain["methods"]])
        adj = self.fc(counts, exposure=exp, trusted="stories", planned=70)
        self.assertEqual(adj["exposure_used"], "stories")
        self.assertEqual(adj["best_method"], "rate_mean")   # bugs are exactly 1 per story
        self.assertEqual(adj["forecast"]["point"], 70.0)

    def test_range_never_goes_below_zero(self):
        f = self.fc([0, 9, 0, 9, 0, 9, 0])
        self.assertGreaterEqual(f["forecast"]["low"], 0)


class FreezeExportReport(unittest.TestCase):
    def test_snapshot_freezes_a_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [2, 1])
            self.assertEqual(run("snapshot", "--root", str(root), "--release", "R1").returncode, 0)
            self.assertEqual(run("snapshot", "--root", str(root), "--release", "R1").returncode, 1)   # write-once
            batch = root / "b.jsonl"
            batch.write_text(json.dumps(bug("K-0-0", "R1", severity="high")) + "\n", encoding="utf-8")
            blocked = run("upsert", "--root", str(root), "--from", str(batch))
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("frozen by a snapshot", blocked.stdout)
            self.assertEqual(run("upsert", "--root", str(root), "--from", str(batch), "--force").returncode, 0)
            drift = run("validate", "--root", str(root))
            self.assertEqual(drift.returncode, 1)
            self.assertIn("changed after its snapshot", drift.stdout)

    def test_upsert_merges_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [1])
            batch = root / "b.jsonl"
            batch.write_text(json.dumps({"bug_key": "K-0-0", "severity": "critical"}) + "\n"
                             + json.dumps(bug("NEW-1", "R1")) + "\n", encoding="utf-8")
            out = json.loads(run("upsert", "--root", str(root), "--from", str(batch), "--run-id", "t1").stdout)
            self.assertEqual((out["added"], out["updated"], out["total"]), (1, 1, 2))
            bugs, _ = L.load_bugs(root)
            merged = {b["bug_key"]: b for b in bugs}["K-0-0"]
            self.assertEqual((merged["severity"], merged["component"], merged["run_id"]), ("critical", "rating", "t1"))

    def test_export_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [3, 4, 5], bugs=[bug("A-1", "R1", summary="<script>alert(1)</script>", component="<b>x</b>"),
                                              bug("A-2", "R2", component="<b>x</b>"), bug("A-3", "R3")])
            stats, fc, nar = root / "s.json", root / "f.json", root / "n.json"
            self.assertEqual(run("stats", "--root", str(root), "--out", str(stats)).returncode, 0)
            self.assertEqual(run("forecast", "--root", str(root), "--out", str(fc)).returncode, 0)
            nar.write_text(json.dumps({"headline": "Three bugs <i>found</i>", "findings": [
                {"text": "Rating gap", "bug_keys": ["A-1"], "status": "Suspected"}],
                "actions": [{"text": "Add a rating unit test", "owner": None, "priority": "High"}]}), encoding="utf-8")
            for fmt in ("md", "html"):
                out = root / f"r.{fmt}"
                r = run("report", "--root", str(root), "--stats", str(stats), "--forecast", str(fc),
                        "--narrative", str(nar), "--format", fmt, "--out", str(out))
                self.assertEqual(r.returncode, 0, r.stderr)
                text = out.read_text(encoding="utf-8")
                self.assertIn("Owner TBD", text)
                self.assertIn("Stage 1", text)
            page = (root / "r.html").read_text(encoding="utf-8")
            self.assertNotIn("<b>x</b>", page)
            self.assertNotIn("<i>found</i>", page)
            self.assertIn("&lt;b&gt;x&lt;/b&gt;", page)
            csv_out = root / "bugs.csv"
            self.assertEqual(run("export", "--root", str(root), "--out", str(csv_out)).returncode, 0)
            with csv_out.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["bug_key"], "A-1")


class Acceptance(unittest.TestCase):
    """The backtest scorecard: 95% category match, zero wrong Confirmed, held-back rate vs a baseline."""
    EVID = [{"type": "ticket", "ref": "x", "quote": "q", "supports": "s"}]

    def setup(self, tmp, n=20, wrong_category=(), confirmed=(), verdicts=None, unclear=range(15, 20), held_back=None):
        """n bugs K-0..K-n-1, team category TEST. Bugs in `unclear` have cause_clear = no."""
        held_back = set(unclear) if held_back is None else set(held_back)
        recs = []
        for i in range(n):
            status = "Confirmed" if i in confirmed else ("Suspected" if i in held_back or i not in unclear else "Confirmed")
            over = {"category": "DATA" if i in wrong_category else "TEST", "root_cause_status": status}
            if status == "Confirmed":
                over["evidence"] = self.EVID
            recs.append(bug(f"K-{i}", "R1", **over))
        root = make(tmp, [n], bugs=recs)
        answers = root / "answers.csv"
        with answers.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(L.ANSWER_COLUMNS)
            for i in range(n):
                w.writerow([f"K-{i}", "TEST", "no" if i in unclear else "yes", (verdicts or {}).get(i, "")])
        return root, answers

    def baseline(self, root, rate):
        p = root / "baseline.json"
        p.write_text(json.dumps({"criteria": [{"id": "honest_uncertainty", "value": rate}]}), encoding="utf-8")
        return p

    def status(self, card):
        return {c["id"]: c["status"] for c in card["criteria"]}

    def test_nineteen_of_twenty_meets_the_95_percent_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, wrong_category=[3])
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.6))
            self.assertEqual(card["result"], "pass")
            cat = next(c for c in card["criteria"] if c["id"] == "category_match")
            self.assertEqual((cat["matched"], cat["of"], cat["value"]), (19, 20, 0.95))
            self.assertEqual(card["category_mismatches"], [{"key": "K-3", "expected": "TEST", "got": "DATA"}])

    def test_eighteen_of_twenty_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, wrong_category=[3, 4])
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.6))
            self.assertEqual(card["result"], "fail")
            self.assertEqual(self.status(card)["category_match"], "fail")

    def test_one_wrong_confirmed_cause_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, confirmed=[0, 1], verdicts={0: "right", 1: "wrong"})
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.6))
            self.assertEqual(card["result"], "fail")
            self.assertEqual(card["confirmed_wrong_keys"], ["K-1"])

    def test_an_unjudged_confirmed_cause_is_incomplete_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdicts = {i: "right" for i in range(1, 15)}          # K-0 left blank
            root, answers = self.setup(tmp, confirmed=[0], verdicts=verdicts)
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.6))
            self.assertEqual(card["result"], "incomplete")
            self.assertEqual(card["confirmed_unjudged_keys"], ["K-0"])

    def test_held_back_rate_matches_hand_calculation_and_is_compared_with_the_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 5 unclear causes; the run held back 4 and confirmed 1 (judged right): 4 / 5 = 0.8
            verdicts = {i: "right" for i in range(0, 20)}
            root, answers = self.setup(tmp, held_back=[15, 16, 17, 18], verdicts=verdicts)
            hu = lambda c: next(x for x in c["criteria"] if x["id"] == "honest_uncertainty")
            better = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.6))
            self.assertEqual((hu(better)["held_back"], hu(better)["of"], hu(better)["value"]), (4, 5, 0.8))
            self.assertEqual(hu(better)["status"], "pass")
            worse = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 1.0))
            self.assertEqual((hu(worse)["status"], worse["result"]), ("fail", "fail"))
            none = L.compute_acceptance(root, answers)
            self.assertEqual((hu(none)["status"], none["result"]), ("not judged", "incomplete"))

    def test_small_sample_and_missing_bugs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, n=10, unclear=range(8, 10), verdicts={i: "right" for i in range(10)})
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.5))
            self.assertEqual(self.status(card)["sample_size"], "fail")
            self.assertEqual(self.status(card)["category_match"], "pass")
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, verdicts={i: "right" for i in range(20)})
            with answers.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["K-99", "TEST", "yes", ""])
                csv.writer(f).writerow(["K-98", "TEST", "yes", ""])
            card = L.compute_acceptance(root, answers, baseline_path=self.baseline(root, 0.5))
            self.assertEqual(card["missing_keys"], ["K-99", "K-98"])
            self.assertEqual(self.status(card)["category_match"], "fail")   # 20 of 22

    def test_bad_answer_files_stop_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp)
            for text in ("key,category\nK-0,TEST\n",                                  # column missing
                         "key,category,cause_clear\nK-0,NOPE,yes\n",                  # unknown category
                         "key,category,cause_clear\nK-0,TEST,maybe\n",                # bad yes/no
                         "key,category,cause_clear\nK-0,TEST,yes\nK-0,TEST,yes\n"):   # duplicate key
                answers.write_text(text, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    L.compute_acceptance(root, answers)

    def test_cli_scores_the_original_prompt_then_compares_the_agent_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, answers = self.setup(tmp, verdicts={i: "right" for i in range(20)})
            # The original prompt's run, transcribed by hand: it confirmed 3 of the 5 unclear causes.
            results = root / "original.csv"
            with results.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(L.RESULT_COLUMNS)
                for i in range(20):
                    w.writerow([f"K-{i}", "test", "confirmed" if i < 18 else "Suspected", "wrong" if i in (15, 16, 17) else "right"])
            base = root / "original-scorecard.json"
            r = run("acceptance", "--root", str(root), "--answers", str(answers), "--results", str(results), "--out", str(base))
            self.assertEqual(r.returncode, 1, r.stderr)                      # three wrong Confirmed causes
            card = json.loads(base.read_text(encoding="utf-8"))
            self.assertEqual(card["confirmed_wrong_keys"], ["K-15", "K-16", "K-17"])
            self.assertEqual(next(c["value"] for c in card["criteria"] if c["id"] == "honest_uncertainty"), 0.4)
            self.assertNotIn("ledger_validates", [c["id"] for c in card["criteria"]])
            out = root / "scorecard.json"
            r = run("acceptance", "--root", str(root), "--answers", str(answers), "--baseline", str(base), "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("result: pass", r.stdout)
            r = run("acceptance", "--root", str(root), "--answers", str(answers))
            self.assertEqual(r.returncode, 2)                                # no baseline: incomplete

    def test_the_readme_rehearsal_on_synthetic_data_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = ROOT / "examples" / "synthetic" / "make_synthetic.py"
            subprocess.run([sys.executable, str(gen), "--out", tmp, "--closed", "7"], check=True, capture_output=True)
            self.assertEqual(run("init", "--root", tmp).returncode, 0)
            self.assertEqual(run("upsert", "--root", tmp, "--from", f"{tmp}/batch.jsonl").returncode, 0)
            bt = Path(tmp) / "backtest"
            r = run("acceptance", "--root", tmp, "--answers", str(bt / "answers.csv"),
                    "--results", str(bt / "original-results.csv"), "--out", str(bt / "original-scorecard.json"))
            self.assertEqual(r.returncode, 1, r.stderr)
            r = run("acceptance", "--root", tmp, "--answers", str(bt / "answers.csv"),
                    "--baseline", str(bt / "original-scorecard.json"), "--out", str(bt / "scorecard.json"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_templates_and_profile_match_the_command(self):
        head = lambda name: (ROOT / "backtest" / name).read_text(encoding="utf-8").splitlines()[0].split(",")
        self.assertEqual(head("answers.template.csv"), L.ANSWER_COLUMNS)
        self.assertEqual(head("original-results.template.csv"), L.RESULT_COLUMNS)
        profile = (ROOT / "config" / "uat-profile.yaml").read_text(encoding="utf-8")
        for line in ("min_bugs: 20", "min_category_match: 0.95", "max_confirmed_wrong: 0"):
            self.assertIn(line, profile)
        with tempfile.TemporaryDirectory() as tmp:                           # the command's defaults are the same numbers
            root, answers = self.setup(tmp, n=19, unclear=range(15, 19), verdicts={i: "right" for i in range(19)})
            card = L.compute_acceptance(root, answers)
            self.assertEqual([c["target"] for c in card["criteria"][:3]], ["at least 20 bugs", "at most 0", "at least 95%"])


class LeanTwin(unittest.TestCase):
    def test_twin_is_current_and_comment_free(self):
        src = (ROOT / "agent-src" / "uat.agent.md").read_text(encoding="utf-8")
        twin_path = ROOT / ".claude" / "agents" / "uat.agent.md"
        self.assertEqual(twin_path.read_text(encoding="utf-8"), B.build(src), "run: python3 tools/build_agent.py")
        body = twin_path.read_text(encoding="utf-8").split("\n---\n", 1)[1]
        self.assertNotIn("<!--", body)
        self.assertNotIn("-->", body)

    def test_stripping_removes_comments_only(self):
        src = "---\n# note\nname: x\ndescription: \"d\"\n---\n\n<!-- why -->\nKeep this.\n\n```\n<!-- stays in code -->\n```\nAnd <!-- gone --> this.\n"
        out = B.build(src)
        self.assertIn("Keep this.", out)
        self.assertIn("<!-- stays in code -->", out)
        self.assertIn("And  this.", out)
        self.assertNotIn("why", out)
        self.assertNotIn("# note", out)

    def test_every_instruction_line_survives(self):
        src = (ROOT / "agent-src" / "uat.agent.md").read_text(encoding="utf-8")
        twin = (ROOT / ".claude" / "agents" / "uat.agent.md").read_text(encoding="utf-8")
        _, body = B.split_frontmatter(src)
        kept = [ln for ln in B.strip_html_comments(body) if ln.strip()]
        twin_lines = set(twin.split("\n"))
        missing = [ln for ln in kept if ln not in twin_lines]
        self.assertEqual(missing, [])


class KitFiles(unittest.TestCase):
    SKILLS = ROOT / ".claude" / "skills"

    def test_every_skill_has_name_and_description(self):
        found = sorted(p.parent.name for p in self.SKILLS.glob("*/SKILL.md"))
        self.assertEqual(found, ["uat-ledger", "uat-report", "uat-stack-generic", "uat-stack-guidewire",
                                 "uat-writeback", "uat-writeback-apply"])
        for name in found:
            fm, body = B.split_frontmatter((self.SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            keys = {ln.split(":", 1)[0].strip() for ln in fm if ln and not ln.startswith((" ", "#"))}
            self.assertIn("name", keys, name)
            self.assertIn("description", keys, name)
            self.assertIn(f"name: {name}", fm, name)
            self.assertTrue(any(ln.strip() for ln in body), name)

    def test_only_the_apply_skill_is_human_only(self):
        for path in self.SKILLS.glob("*/SKILL.md"):
            human_only = "disable-model-invocation: true" in path.read_text(encoding="utf-8")
            self.assertEqual(human_only, path.parent.name == "uat-writeback-apply", path.parent.name)

    def test_the_documented_example_record_is_valid(self):
        text = (self.SKILLS / "uat-ledger" / "SKILL.md").read_text(encoding="utf-8")
        rec = json.loads(text.split("<example>", 1)[1].split("</example>", 1)[0].strip())
        with tempfile.TemporaryDirectory() as tmp:
            root = make(tmp, [1], bugs=[rec])
            with (root / "ledger" / "releases.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(L.RELEASE_COLUMNS)
                w.writerow([rec["release"], 1, "open", "", "", "", "", "", "", ""])
            self.assertEqual(L.validate_ledger(root)[0], [])

    def test_the_documented_writeback_batch_is_well_formed(self):
        text = (self.SKILLS / "uat-writeback" / "SKILL.md").read_text(encoding="utf-8")
        block = text.split("```json", 1)[1].split("```", 1)[0].strip().splitlines()
        lines = [json.loads(ln) for ln in block]
        self.assertEqual(lines[0]["type"], "header")
        self.assertEqual(lines[0]["actions"], len(lines) - 1)
        self.assertEqual({a["action"] for a in lines[1:]}, {"add_labels", "add_comment", "create_ticket"})
        self.assertTrue(all(a.get("id") and a.get("evidence_status") and a.get("reason") for a in lines[1:]))

    def test_agent_preloads_a_skill_that_exists_and_names_real_companions(self):
        twin = (ROOT / ".claude" / "agents" / "uat.agent.md").read_text(encoding="utf-8")
        for skill in ("uat-ledger", "uat-report", "uat-writeback", "uat-stack-guidewire", "uat-stack-generic"):
            self.assertIn(skill, twin)
            self.assertTrue((self.SKILLS / skill / "SKILL.md").exists(), skill)
        self.assertNotIn("uat-writeback-apply", twin)   # the agent must not know how to apply

    def test_profile_parses_when_yaml_is_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        p = yaml.safe_load((ROOT / "config" / "uat-profile.yaml").read_text(encoding="utf-8"))
        self.assertEqual(p["release"]["key"], "fixVersion")
        self.assertEqual(p["identifiers"], "verbatim")
        self.assertEqual(p["exposure"]["trusted"], [])
        self.assertEqual(p["writeback"]["mode"], "propose-approve-apply")
        self.assertEqual(p["stack_profiles"], ["guidewire"])
        self.assertEqual(set(p["roles"]), {"issue_tracker", "code_host", "test_management", "spreadsheet_builder", "brand_style"})

    def test_settings_json_is_valid(self):
        s = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(all(r.startswith("Bash(python3 ") and r.endswith(" *)") for r in s["permissions"]["allow"]))


class StopGate(unittest.TestCase):
    GATE = ROOT / "tools" / "stop_gate.py"

    def gate(self, root, event):
        import os
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        return subprocess.run([sys.executable, str(self.GATE)], input=json.dumps(event), capture_output=True, text=True, env=env)

    def project(self, tmp, recs):
        import shutil
        root = make(tmp, [1], bugs=recs)
        dest = root / ".claude" / "skills" / "uat-ledger" / "scripts"
        dest.mkdir(parents=True)
        shutil.copy(SCRIPT, dest / "uat_ledger.py")
        return root

    def test_blocks_on_invalid_ledger_and_passes_on_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp, [bug("A-1", "R1", root_cause_status="Confirmed")])
            blocked = self.gate(root, {"hook_event_name": "SubagentStop", "stop_hook_active": False})
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("Confirmed cause needs at least one evidence", blocked.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp, [bug("A-1", "R1")])
            self.assertEqual(self.gate(root, {"stop_hook_active": False}).returncode, 0)

    def test_loop_guard_and_empty_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp, [bug("A-1", "R1", root_cause_status="Confirmed")])
            self.assertEqual(self.gate(root, {"stop_hook_active": True}).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.gate(Path(tmp), {}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
