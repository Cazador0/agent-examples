#!/usr/bin/env python3
"""Generate a SYNTHETIC ledger so you can try every command without Jira.

    python3 examples/synthetic/make_synthetic.py --out /tmp/uat-demo --closed 7

Nothing here describes a real release, bug, policy or customer. Keys start
with SYN- so a synthetic record can never be mistaken for a real one.
"""
import argparse
import csv
import json
import random
from pathlib import Path

COUNTS = [14, 11, 16, 12, 15, 10, 13, 9, 12, 11, 14, 10]
APPS = {
    "PolicyCenter": ["rating", "forms", "product-model", "pcf-ui", "underwriting-rules"],
    "ClaimCenter": ["fnol", "financials", "assignment-rules", "pcf-ui"],
    "BillingCenter": ["invoicing", "payment-plans", "delinquency"],
    "ContactManager": ["contact-sync", "duplicate-check"],
    "Integration": ["cloud-api", "app-events", "integration-gateway", "kafka-consumer"],
}
LAYER = {"rating": "rules", "forms": "rules", "product-model": "config", "pcf-ui": "ui", "underwriting-rules": "rules",
         "fnol": "ui", "financials": "rules", "assignment-rules": "rules", "invoicing": "batch", "payment-plans": "config",
         "delinquency": "batch", "contact-sync": "integration", "duplicate-check": "rules", "cloud-api": "api",
         "app-events": "integration", "integration-gateway": "integration", "kafka-consumer": "integration"}
CATS = ["REQ", "TEST", "TEST", "INT", "DATA", "ENV", "UI", "REG", "PROC"]
ESCAPE = {"REQ": "ac-interpretation", "TEST": "missing-test", "INT": "integration-unavailable", "DATA": "test-data",
          "ENV": "environment", "UI": "missing-test", "REG": "test-not-run", "PROC": "unknown"}
CATCH = {"REQ": "uat-only", "TEST": "unit", "INT": "integration", "DATA": "api", "ENV": "manual", "UI": "e2e-ui",
         "REG": "unit", "PROC": "unknown"}
AC = {"REQ": "ambiguous", "TEST": "none", "INT": "none", "DATA": "missing", "ENV": "none", "UI": "none", "REG": "none",
      "PROC": "unknown"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--closed", type=int, default=7, help="number of closed releases (one open release is added after them)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(args.out)
    (out / "ledger").mkdir(parents=True, exist_ok=True)
    total = args.closed + 1
    with (out / "ledger" / "releases.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["release", "order", "status", "uat_start", "uat_end", "stories", "story_points", "merged_prs",
                    "uat_test_executions", "notes"])
        for i in range(total):
            status = "closed" if i < args.closed else "open"
            w.writerow([f"SYN-R{i + 1}", i + 1, status, f"2026-{(i % 12) + 1:02d}-01", f"2026-{(i % 12) + 1:02d}-14",
                        30 + (i * 7) % 11, "", 40 + (i * 5) % 13, "", "synthetic"])
    records, n = [], 100
    for i in range(total):
        for _ in range(COUNTS[i % len(COUNTS)]):
            n += 1
            app = rng.choice(list(APPS))
            comp = rng.choice(APPS[app])
            cat = rng.choice(CATS)
            status = rng.choice(["Confirmed", "Suspected", "Suspected", "Unconfirmed"])
            rec = {
                "bug_key": f"SYN-{n}", "release": f"SYN-R{i + 1}", "summary": f"Synthetic {comp} defect {n}",
                "status": rng.choice(["Open", "In Progress", "Resolved", "Closed"]),
                "severity": rng.choice(["critical", "high", "medium", "medium", "low"]),
                "depth": "standard", "root_cause_status": status, "category": cat,
                "gap": "Synthetic expected-versus-actual gap", "escape_reason": ESCAPE[cat], "catch_level": CATCH[cat],
                "ac_issue": AC[cat], "layer": LAYER[comp], "component": comp, "app": app,
                "next_step": "Synthetic next step", "impact_score": rng.randint(1, 5),
                "policy_number": f"SYN-POL-{n:05d}", "market": rng.choice(["Synthetic-A", "Synthetic-B"]),
                "transaction_type": rng.choice(["Submission", "Policy Change", "Renewal", "Not provided"]),
                "change_origin": "unknown",
            }
            if status == "Confirmed":
                rec["evidence"] = [{"type": "ticket", "ref": f"SYN-{n}#description", "quote": "synthetic quote"}]
            if rng.random() < 0.25:
                rec["change_origin"] = rng.choice(["human", "agent-assisted", "mixed"])
                rec["origin_evidence"] = "synthetic commit trailer"
            records.append(rec)
    batch = out / "batch.jsonl"
    with batch.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {out / 'ledger' / 'releases.csv'} and {batch} ({len(records)} synthetic bugs, {args.closed} closed releases)")
    write_backtest(out, records[:20])


def write_backtest(out, sample):
    """A made-up backtest for trying the acceptance command. It shows the mechanics only:
    the numbers are invented and say nothing about how any prompt performs."""
    bt = out / "backtest"
    bt.mkdir(parents=True, exist_ok=True)
    with (bt / "answers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "category", "cause_clear", "cause_verdict"])
        for i, r in enumerate(sample):
            confirmed = r["root_cause_status"] == "Confirmed"
            # The team disagrees with the run on one category: 19 of 20 match.
            team_cat = r["category"] if i != 7 else next(c for c in CATS if c != r["category"])
            w.writerow([r["bug_key"], team_cat, "yes" if confirmed else "no", "right" if confirmed else ""])
    with (bt / "original-results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "category", "root_cause_status", "cause_verdict"])
        unclear = [r for r in sample if r["root_cause_status"] != "Confirmed"]
        overclaimed = {r["bug_key"] for r in unclear[: len(unclear) // 2]}
        for i, r in enumerate(sample):
            cat = r["category"] if i not in (2, 7, 11) else next(c for c in CATS if c != r["category"])
            if r["bug_key"] in overclaimed:
                w.writerow([r["bug_key"], cat, "Confirmed", "wrong"])
            else:
                w.writerow([r["bug_key"], cat, r["root_cause_status"], "right" if r["root_cause_status"] == "Confirmed" else ""])
    print(f"wrote {bt / 'answers.csv'} and {bt / 'original-results.csv'} (a made-up backtest of {len(sample)} bugs)")


if __name__ == "__main__":
    main()
