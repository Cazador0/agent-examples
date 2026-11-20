#!/usr/bin/env python3
"""uat_ledger.py: deterministic helpers for the UAT ledger. Standard library only.

Commands
  init       create the starter layout (never overwrites a file)
  upsert     merge analysed bug records into ledger/bugs.jsonl
  validate   check the ledger; exit code 0 = pass, 1 = fail
  stats      per-release and cumulative statistics as JSON
  forecast   staged next-release forecast with a backtest
  snapshot   freeze a closed release
  export     flat CSV of the bug records for BI tools
  report     Markdown or HTML report from stats (plus forecast and narrative)
  acceptance score a backtest against the success criteria; exit 0 = pass,
             1 = fail, 2 = incomplete

Rule for the agent: every number in a report comes from this script, never
from arithmetic done in prose.
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA_VERSION = 1
EXPOSURES = ["stories", "story_points", "merged_prs", "uat_test_executions"]
RELEASE_COLUMNS = ["release", "order", "status", "uat_start", "uat_end"] + EXPOSURES + ["notes"]
RELEASE_STATUSES = ("planned", "open", "closed")
AUTOMATABLE = ("unit", "api", "integration", "e2e-ui")
AC_RELATED = ("missing", "ambiguous", "conflicting", "misread")
REQUIRED_ALWAYS = ["bug_key", "release", "summary", "status", "severity", "depth",
                   "root_cause_status", "category"]
REQUIRED_STANDARD = ["gap", "escape_reason", "catch_level", "ac_issue", "layer",
                     "component", "app", "next_step"]
LIST_FIELDS = ["evidence", "alternatives", "missing_evidence", "links"]

DEFAULT_CODEBOOK = {
    "taxonomy_version": "1.0",
    "rule": "Add codes when needed. Never rename or reuse a code: old releases must stay comparable.",
    "categories": [
        {"code": "REQ", "label": "Requirements incomplete or ambiguous",
         "definition": "The requirement or acceptance criteria did not state, or stated unclearly, the behaviour UAT expected."},
        {"code": "TEST", "label": "Test coverage gap",
         "definition": "The requirement was clear and the build was wrong; no developer-side test exercised the failing path."},
        {"code": "ENV", "label": "Environment or configuration",
         "definition": "Works as built, fails because of environment, deployment or configuration differences."},
        {"code": "INT", "label": "Integration or interface",
         "definition": "A contract, payload, sequence or timing problem between two systems or modules."},
        {"code": "DATA", "label": "Data validation",
         "definition": "Missing or wrong validation, defaulting or handling of data values."},
        {"code": "UI", "label": "UI or UX",
         "definition": "Layout, labels, navigation or interaction is wrong while the underlying logic is right."},
        {"code": "PERF", "label": "Performance",
         "definition": "Correct result, unacceptable time or resource use."},
        {"code": "SEC", "label": "Security",
         "definition": "Access, permission or data-exposure defect."},
        {"code": "REG", "label": "Regression from a previous fix",
         "definition": "Previously working behaviour broken by a later change. Needs evidence of the earlier working state."},
        {"code": "PROC", "label": "Process or workflow",
         "definition": "The software matches its design; the delivery or business process around it caused the bug report."},
        {"code": "OTHER", "label": "Other",
         "definition": "None of the above. Say why in root_cause."},
    ],
    "escape_reasons": [
        {"code": "test-data", "definition": "Developer data did not include the case UAT used."},
        {"code": "environment", "definition": "The local or dev environment differs from UAT in a way that hid the defect."},
        {"code": "integration-unavailable", "definition": "The other system was mocked, stubbed or absent before UAT."},
        {"code": "ac-interpretation", "definition": "Developer and tester read the acceptance criteria differently."},
        {"code": "missing-test", "definition": "The path could have been tested locally and no test existed."},
        {"code": "test-not-run", "definition": "A test existed and was skipped, disabled or not run for this change."},
        {"code": "unknown", "definition": "Not established."},
    ],
    "catch_levels": [
        {"code": "unit", "definition": "An in-process unit test could have caught it."},
        {"code": "api", "definition": "An API or contract test against a running service could have caught it."},
        {"code": "integration", "definition": "A test with the real or simulated neighbouring system could have caught it."},
        {"code": "e2e-ui", "definition": "An automated end-to-end UI test could have caught it."},
        {"code": "manual", "definition": "Only a manual check before UAT could have caught it."},
        {"code": "uat-only", "definition": "Realistically visible only in UAT: business judgment or production-like data."},
        {"code": "unknown", "definition": "Not established."},
    ],
    "ac_issues": ["none", "missing", "ambiguous", "conflicting", "misread", "unknown"],
    "layers": ["ui", "api", "rules", "data", "integration", "batch", "config", "security", "unknown"],
    "severities": ["critical", "high", "medium", "low", "unknown"],
    "root_cause_statuses": ["Confirmed", "Suspected", "Unconfirmed"],
    "origins": ["human", "agent-assisted", "mixed", "unknown"],
    "depths": ["quick", "standard", "full"],
}


# ----------------------------------------------------------------------------- helpers
def P(root):
    root = Path(root)
    led = root / "ledger"
    return {
        "root": root, "ledger": led, "bugs": led / "bugs.jsonl", "releases": led / "releases.csv",
        "codebook": led / "codebook.json", "snapshots": led / "snapshots", "runs": led / "runs.jsonl",
    }


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_blank(v):
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def to_num(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def codes(codebook, key):
    return [c["code"] if isinstance(c, dict) else c for c in codebook.get(key, [])]


def label_of(codebook, key, code):
    for c in codebook.get(key, []):
        if isinstance(c, dict) and c.get("code") == code:
            return c.get("label") or code
    return code


def load_codebook(root):
    p = P(root)["codebook"]
    if p.exists():
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CODEBOOK


def load_releases(root):
    p = P(root)["releases"]
    rows = []
    if not p.exists():
        return rows
    with p.open(newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            row = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not row.get("release"):
                continue
            row["_line"] = i + 2
            row["_order"] = to_num(row.get("order"))
            for m in EXPOSURES:
                row[m] = to_num(row.get(m))
            rows.append(row)
    rows.sort(key=lambda r: (r["_order"] is None, r["_order"] or 0, r.get("uat_end") or "", r["_line"]))
    return rows


def load_bugs(root):
    p = P(root)["bugs"]
    bugs, errs = [], []
    if not p.exists():
        return bugs, errs
    with p.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"bugs.jsonl line {n}: not valid JSON ({e.msg})")
                continue
            if not isinstance(obj, dict):
                errs.append(f"bugs.jsonl line {n}: expected a JSON object")
                continue
            obj["_line"] = n
            bugs.append(obj)
    return bugs, errs


def clean(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}


def write_bugs(root, bugs, releases):
    order = {r["release"]: i for i, r in enumerate(releases)}
    bugs = sorted(bugs, key=lambda b: (order.get(b.get("release"), 10 ** 6), str(b.get("release")), str(b.get("bug_key"))))
    p = P(root)["bugs"]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for b in bugs:
            f.write(json.dumps(clean(b), ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(p)


def release_hash(bugs, release):
    recs = sorted((clean(b) for b in bugs if b.get("release") == release), key=lambda b: str(b.get("bug_key")))
    blob = json.dumps(recs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), len(recs)


def emit(obj, out=None):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)


def share(n, d):
    return round(n / d, 4) if d else None


def ordered_counts(values, preferred=None):
    c = Counter(values)
    keys = sorted(c, key=lambda k: (-c[k], str(k)))
    if preferred:
        keys = [k for k in preferred if k in c] + [k for k in keys if k not in preferred]
    return {k: c[k] for k in keys}


# ----------------------------------------------------------------------------- init
def cmd_init(args):
    paths = P(args.root)
    made = []
    for d in [paths["ledger"], paths["snapshots"], paths["root"] / "reports",
              paths["root"] / "writeback" / "proposed", paths["root"] / "writeback" / "approved",
              paths["root"] / "writeback" / "applied"]:
        if not d.exists():
            d.mkdir(parents=True)
            made.append(str(d))
    if not paths["bugs"].exists():
        paths["bugs"].write_text("", encoding="utf-8")
        made.append(str(paths["bugs"]))
    if not paths["releases"].exists():
        with paths["releases"].open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(RELEASE_COLUMNS)
        made.append(str(paths["releases"]))
    if not paths["codebook"].exists():
        paths["codebook"].write_text(json.dumps(DEFAULT_CODEBOOK, indent=2) + "\n", encoding="utf-8")
        made.append(str(paths["codebook"]))
    print(json.dumps({"created": made, "note": "existing files were left untouched"}, indent=2))
    return 0


# ----------------------------------------------------------------------------- upsert
def read_records(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        data = json.loads(text)
    else:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not all(isinstance(d, dict) for d in data):
        raise SystemExit("error: every record must be a JSON object")
    return data


def cmd_upsert(args):
    paths = P(args.root)
    codebook = load_codebook(args.root)
    releases = load_releases(args.root)
    bugs, errs = load_bugs(args.root)
    if errs:
        print(json.dumps({"result": "fail", "errors": errs}, indent=2))
        return 1
    incoming = read_records(args.source)
    missing_key = [i + 1 for i, r in enumerate(incoming) if is_blank(r.get("bug_key"))]
    if missing_key:
        print(json.dumps({"result": "fail", "errors": [f"record {i} has no bug_key" for i in missing_key]}, indent=2))
        return 1
    frozen = {p.stem for p in paths["snapshots"].glob("*.json")} if paths["snapshots"].exists() else set()
    by_key = {b["bug_key"]: b for b in bugs}
    blocked = sorted({r["bug_key"] for r in incoming
                      if (r.get("release") in frozen or by_key.get(r["bug_key"], {}).get("release") in frozen)})
    if blocked and not args.force:
        print(json.dumps({"result": "fail", "errors": [
            "these bugs belong to a release frozen by a snapshot: " + ", ".join(blocked),
            "a frozen release changes only on purpose: rerun with --force, then re-snapshot with --force"]}, indent=2))
        return 1
    added = updated = 0
    stamp = now_iso()
    for rec in incoming:
        rec = clean(rec)
        rec.setdefault("schema_version", SCHEMA_VERSION)
        rec.setdefault("taxonomy_version", codebook.get("taxonomy_version"))
        rec.setdefault("analyzed_at", stamp)
        if args.run_id:
            rec["run_id"] = args.run_id
        if rec["bug_key"] in by_key:
            by_key[rec["bug_key"]].update(rec)
            updated += 1
        else:
            by_key[rec["bug_key"]] = rec
            added += 1
    write_bugs(args.root, list(by_key.values()), releases)
    print(json.dumps({"result": "ok", "added": added, "updated": updated, "total": len(by_key)}, indent=2))
    return 0


# ----------------------------------------------------------------------------- validate
def check_record(b, cb, release_names, errors, warnings):
    key = b.get("bug_key") or f"(bugs.jsonl line {b.get('_line')})"

    def err(msg):
        errors.append(f"{key}: {msg}")

    def warn(msg):
        warnings.append(f"{key}: {msg}")

    for f in REQUIRED_ALWAYS:
        if is_blank(b.get(f)):
            err(f"missing required field '{f}'")
    depth = b.get("depth")
    enum_fields = [("depth", "depths"), ("severity", "severities"), ("root_cause_status", "root_cause_statuses"),
                   ("category", "categories"), ("escape_reason", "escape_reasons"), ("catch_level", "catch_levels"),
                   ("ac_issue", "ac_issues"), ("layer", "layers"), ("change_origin", "origins")]
    for field, cb_key in enum_fields:
        v = b.get(field)
        if not is_blank(v) and v not in codes(cb, cb_key):
            err(f"{field} '{v}' is not in the codebook ({', '.join(codes(cb, cb_key))})")
    if depth in ("standard", "full"):
        for f in REQUIRED_STANDARD:
            if is_blank(b.get(f)):
                err(f"depth '{depth}' requires '{f}' (use 'unknown' or 'Not provided' when it could not be established)")
        if b.get("impact_score") is None:
            warn("no impact_score")
    score = b.get("impact_score")
    if score is not None and not (isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5):
        err("impact_score must be an integer from 1 to 5")
    for lf in LIST_FIELDS:
        if b.get(lf) is not None and not isinstance(b.get(lf), list):
            err(f"{lf} must be a list")
    ev = b.get("evidence") if isinstance(b.get("evidence"), list) else []
    for i, item in enumerate(ev, 1):
        if not isinstance(item, dict) or is_blank(item.get("type")) or is_blank(item.get("ref")):
            err(f"evidence item {i} needs 'type' and 'ref'")
        elif isinstance(item.get("quote"), str) and len(item["quote"]) > 300:
            warn(f"evidence item {i} quote is longer than 300 characters; keep quotes short")
    if b.get("root_cause_status") == "Confirmed":
        if not ev:
            err("a Confirmed cause needs at least one evidence item")
        if depth == "quick":
            err("Quick depth cannot produce a Confirmed cause")
    origin = b.get("change_origin")
    if not is_blank(origin) and origin != "unknown" and is_blank(b.get("origin_evidence")):
        err(f"change_origin '{origin}' needs origin_evidence (the commit trailer or pull-request text that proves it)")
    if not is_blank(b.get("release")) and b.get("release") not in release_names:
        err(f"release '{b.get('release')}' is not in releases.csv")
    for df in ("created", "resolved"):
        v = b.get(df)
        if not is_blank(v):
            try:
                dt.date.fromisoformat(str(v)[:10])
            except ValueError:
                err(f"{df} '{v}' is not an ISO date (YYYY-MM-DD)")


def validate_ledger(root, expect=None, allow_drift=False):
    paths = P(root)
    errors, warnings = [], []
    cb = load_codebook(root)
    releases = load_releases(root)
    bugs, parse_errors = load_bugs(root)
    errors.extend(parse_errors)
    if not paths["bugs"].exists():
        errors.append("ledger/bugs.jsonl does not exist (run: init)")
    if not paths["releases"].exists():
        errors.append("ledger/releases.csv does not exist (run: init)")
    names = [r["release"] for r in releases]
    for name, n in Counter(names).items():
        if n > 1:
            errors.append(f"releases.csv lists release '{name}' {n} times")
    for r in releases:
        if r.get("status") not in RELEASE_STATUSES:
            errors.append(f"releases.csv line {r['_line']}: status '{r.get('status')}' must be one of {', '.join(RELEASE_STATUSES)}")
    for key, n in Counter(b.get("bug_key") for b in bugs if b.get("bug_key")).items():
        if n > 1:
            errors.append(f"{key}: appears {n} times in bugs.jsonl")
    for b in bugs:
        check_record(b, cb, set(names), errors, warnings)
    if expect:
        present = {b.get("bug_key") for b in bugs}
        wanted = [ln.strip() for ln in Path(expect).read_text(encoding="utf-8").splitlines() if ln.strip()]
        for k in wanted:
            if k not in present:
                errors.append(f"{k}: expected input bug is not in the ledger")
    if paths["snapshots"].exists():
        for snap in sorted(paths["snapshots"].glob("*.json")):
            data = json.loads(snap.read_text(encoding="utf-8"))
            digest, n = release_hash(bugs, data.get("release"))
            if digest != data.get("records_sha256"):
                msg = (f"release '{data.get('release')}' changed after its snapshot "
                       f"({data.get('bugs')} bugs frozen, {n} now); re-snapshot with --force if intended")
                (warnings if allow_drift else errors).append(msg)
    summary = {
        "bugs": len(bugs),
        "releases": len(releases),
        "by_release": ordered_counts([b.get("release") for b in bugs], names),
        "by_root_cause_status": ordered_counts([b.get("root_cause_status") for b in bugs], codes(cb, "root_cause_statuses")),
    }
    return errors, warnings, summary


def cmd_validate(args):
    errors, warnings, summary = validate_ledger(args.root, args.expect, args.allow_drift)
    emit({"result": "fail" if errors else "pass", "errors": errors, "warnings": warnings, "summary": summary})
    return 1 if errors else 0


# ----------------------------------------------------------------------------- stats
def summarize(bugs, cb):
    n = len(bugs)
    sev = [b.get("severity") or "unknown" for b in bugs]
    catch = [b.get("catch_level") or "unknown" for b in bugs]
    ac = [b.get("ac_issue") or "unknown" for b in bugs]
    classified_catch = sum(1 for c in catch if c != "unknown")
    classified_ac = sum(1 for a in ac if a != "unknown")
    automatable = sum(1 for c in catch if c in AUTOMATABLE)
    before_uat = sum(1 for c in catch if c in AUTOMATABLE or c == "manual")
    ac_related = sum(1 for a in ac if a in AC_RELATED)
    return {
        "bugs": n,
        "high_critical": sum(1 for s in sev if s in ("critical", "high")),
        "by_severity": ordered_counts(sev, codes(cb, "severities")),
        "by_category": ordered_counts([b.get("category") or "OTHER" for b in bugs]),
        "by_root_cause_status": ordered_counts([b.get("root_cause_status") or "Unconfirmed" for b in bugs], codes(cb, "root_cause_statuses")),
        "by_escape_reason": ordered_counts([b.get("escape_reason") or "unknown" for b in bugs]),
        "by_catch_level": ordered_counts(catch, codes(cb, "catch_levels")),
        "by_ac_issue": ordered_counts(ac, codes(cb, "ac_issues")),
        "by_layer": ordered_counts([b.get("layer") or "unknown" for b in bugs]),
        "by_app": ordered_counts([b.get("app") or "unknown" for b in bugs]),
        "by_component": ordered_counts([b.get("component") or "unknown" for b in bugs]),
        "by_change_origin": ordered_counts([b.get("change_origin") or "unknown" for b in bugs], codes(cb, "origins")),
        "by_depth": ordered_counts([b.get("depth") or "unknown" for b in bugs], codes(cb, "depths")),
        "automatable_before_uat": {"count": automatable, "classified": classified_catch,
                                   "share_of_classified": share(automatable, classified_catch), "share_of_all": share(automatable, n)},
        "catchable_before_uat": {"count": before_uat, "classified": classified_catch,
                                 "share_of_classified": share(before_uat, classified_catch), "share_of_all": share(before_uat, n)},
        "ac_related": {"count": ac_related, "classified": classified_ac,
                       "share_of_classified": share(ac_related, classified_ac), "share_of_all": share(ac_related, n)},
    }


def direction(series, band=0.15):
    vals = [v for v in series if v is not None]
    if len(vals) < 3:
        return "insufficient history"
    prev = sum(vals[:-1]) / len(vals[:-1])
    last = vals[-1]
    if prev == 0:
        return "up" if last > 0 else "flat"
    ratio = last / prev
    if ratio > 1 + band:
        return "up"
    if ratio < 1 - band:
        return "down"
    return "flat"


def compute_stats(root, release=None, trusted=()):
    cb = load_codebook(root)
    releases = load_releases(root)
    bugs, _ = load_bugs(root)
    names = [r["release"] for r in releases]
    if release:
        if release not in names:
            raise SystemExit(f"error: release '{release}' is not in releases.csv")
        scope_releases = [r for r in releases if r["release"] == release]
    else:
        scope_releases = releases
    scope_names = [r["release"] for r in scope_releases]
    in_scope = [b for b in bugs if b.get("release") in scope_names]

    per_release = []
    for r in scope_releases:
        rb = [b for b in bugs if b.get("release") == r["release"]]
        s = summarize(rb, cb)
        s = {"release": r["release"], "status": r.get("status"), "uat_start": r.get("uat_start") or None,
             "uat_end": r.get("uat_end") or None, **s}
        s["exposure"] = {m: r.get(m) for m in EXPOSURES if r.get(m) is not None}
        s["rates_per_100"] = {m: round(len(rb) / r[m] * 100, 2) for m in EXPOSURES if r.get(m)}
        per_release.append(s)

    closed = [s for s in per_release if s["status"] == "closed"]
    closed_all = [r for r in releases if r.get("status") == "closed"]
    exposure = {}
    for m in EXPOSURES:
        have = sum(1 for r in closed_all if r.get(m))
        exposure[m] = {"closed_releases_with_value": have, "closed_releases": len(closed_all),
                       "complete": bool(closed_all) and have == len(closed_all), "trusted": m in trusted}

    series = {
        "releases": [s["release"] for s in closed],
        "bugs": [s["bugs"] for s in closed],
        "high_critical": [s["high_critical"] for s in closed],
        "automatable_before_uat_share": [s["automatable_before_uat"]["share_of_classified"] for s in closed],
        "ac_related_share": [s["ac_related"]["share_of_classified"] for s in closed],
    }
    trend = {**series,
             "direction": {k: direction(v) for k, v in series.items() if k != "releases"},
             "direction_rule": "Direction compares the last closed release with the mean of earlier closed releases; "
                               "within 15% is flat; fewer than 3 closed releases is insufficient history. Descriptive only."}

    groups = defaultdict(list)
    for b in in_scope:
        groups[(b.get("category") or "OTHER", b.get("component") or "unknown")].append(b)
    patterns = []
    for (cat, comp), items in groups.items():
        if len(items) < 2:
            continue
        st = Counter(i.get("root_cause_status") for i in items)
        patterns.append({"category": cat, "component": comp, "bugs": len(items),
                         "confirmed": st.get("Confirmed", 0), "suspected": st.get("Suspected", 0),
                         "unconfirmed": st.get("Unconfirmed", 0),
                         "releases": [n for n in names if n in {i.get("release") for i in items}],
                         "bug_keys": sorted(str(i.get("bug_key")) for i in items)})
    patterns.sort(key=lambda p: (-p["bugs"], p["category"], p["component"]))

    cum = summarize(in_scope, cb)
    n = len(in_scope)
    quality = {
        "unknown_catch_level_share": share(sum(1 for b in in_scope if (b.get("catch_level") or "unknown") == "unknown"), n),
        "unknown_escape_reason_share": share(sum(1 for b in in_scope if (b.get("escape_reason") or "unknown") == "unknown"), n),
        "unknown_ac_issue_share": share(sum(1 for b in in_scope if (b.get("ac_issue") or "unknown") == "unknown"), n),
        "unknown_origin_share": share(sum(1 for b in in_scope if (b.get("change_origin") or "unknown") == "unknown"), n),
        "unconfirmed_share": share(sum(1 for b in in_scope if b.get("root_cause_status") == "Unconfirmed"), n),
        "bugs_in_unlisted_releases": sorted({str(b.get("release")) for b in bugs if b.get("release") not in names}),
    }
    return {
        "generated_at": now_iso(), "schema_version": SCHEMA_VERSION,
        "taxonomy_version": cb.get("taxonomy_version"),
        "scope": {"release": release, "releases_included": scope_names,
                  "closed_releases": len(closed), "open_or_planned": [s["release"] for s in per_release if s["status"] != "closed"]},
        "labels": {"categories": {c: label_of(cb, "categories", c) for c in codes(cb, "categories")}},
        "cumulative": cum, "per_release": per_release, "trend": trend, "patterns": patterns,
        "exposure": exposure, "data_quality": quality,
        "notes": ["Rates are shown for every exposure measure that has a value; report them only for measures marked trusted.",
                  "Trend and forecast use closed releases only; an open release is still accumulating bugs."],
    }


def cmd_stats(args):
    emit(compute_stats(args.root, args.release, tuple(args.trusted or ())), args.out)
    return 0


# ----------------------------------------------------------------------------- forecast
def ses_fit(y, alpha):
    level, errs = y[0], []
    for v in y[1:]:
        errs.append(abs(v - level))
        level = alpha * v + (1 - alpha) * level
    return level, (sum(errs) / len(errs) if errs else 0.0)


def best_alpha(y):
    return min((ses_fit(y, a)[1], a) for a in (0.2, 0.4, 0.6, 0.8))[1]


def m_naive_last(y, e, ne):
    return y[-1]


def m_mean(y, e, ne):
    return sum(y) / len(y)


def m_median(y, e, ne):
    return statistics.median(y)


def m_ses(y, e, ne):
    return ses_fit(y, best_alpha(y))[0]


def m_rate_mean(y, e, ne):
    if not e or ne is None or sum(e) <= 0:
        return None
    return sum(y) / sum(e) * ne


def m_rate_last(y, e, ne):
    if not e or ne is None or e[-1] <= 0:
        return None
    return y[-1] / e[-1] * ne


METHODS = [  # order = preference when the backtest ties (simplest first)
    ("naive_last", "repeat the last closed release", 0, m_naive_last, False),
    ("mean", "mean of history", 1, m_mean, False),
    ("median", "median of history", 1, m_median, False),
    ("ses", "simple exponential smoothing", 1, m_ses, False),
    ("rate_mean", "pooled bugs-per-exposure times planned exposure", 1, m_rate_mean, True),
    ("rate_last", "last release's bugs-per-exposure times planned exposure", 0, m_rate_last, True),
]


def backtest(y, e, fn, min_train):
    errs = []
    for t in range(min_train, len(y)):
        pred = fn(y[:t], e[:t] if e else None, e[t] if e else None)
        if pred is None:
            return None
        errs.append(abs(y[t] - pred))
    return errs


def quantile(values, q):
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    pos = q * (len(v) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def compute_forecast(root, target="bugs", trusted=None, planned=None, min_indicative=3, min_model=6, min_skill=0.10):
    stats = compute_stats(root, None, (trusted,) if trusted else ())
    closed = [s for s in stats["per_release"] if s["status"] == "closed"]
    y = [s[target] for s in closed]
    names = [s["release"] for s in closed]
    n = len(y)
    use_exposure = bool(trusted) and stats["exposure"].get(trusted, {}).get("complete") and planned is not None
    e = [s["exposure"].get(trusted) for s in closed] if use_exposure else None
    caveats = ["The range describes how far these methods missed on your own past releases. It is not a guarantee.",
               "Closed releases only. A release still in UAT is excluded because its count is incomplete."]
    if trusted and not use_exposure:
        caveats.append(f"Exposure measure '{trusted}' was requested but is incomplete for closed releases or no planned "
                       "value was given, so the forecast is not adjusted for release size.")
    if not trusted:
        caveats.append("No trusted exposure measure, so the forecast is not adjusted for release size. "
                       "A larger or smaller release than usual will fall outside this range.")
    out = {"generated_at": now_iso(), "target": target, "closed_releases": n,
           "history": [{"release": names[i], "value": y[i], **({"exposure": e[i]} if e else {})} for i in range(n)],
           "thresholds": {"min_releases_indicative": min_indicative, "min_releases_model": min_model, "min_skill": min_skill,
                          "note": "Operating guardrails chosen for this ledger, not statistical constants. "
                                  "Change them in config/uat-profile.yaml and pass them as flags."},
           "exposure_used": trusted if use_exposure else None, "planned_exposure": planned if use_exposure else None,
           "caveats": caveats}
    if n < min_indicative:
        out.update({"stage": 0, "stage_name": "baseline only",
                    "stage_reason": f"{n} closed release(s); at least {min_indicative} are needed before any range is shown",
                    "forecast": None})
        return out
    if n < min_model:
        point = statistics.median(y)
        fc = {"point": round(point, 1), "low": min(y), "high": max(y), "label": "indicative",
              "method": "median of history", "interval": "lowest and highest closed release so far"}
        if use_exposure:
            rates = [y[i] / e[i] for i in range(n) if e[i]]
            fc["exposure_adjusted"] = {"low": round(min(rates) * planned, 1), "high": round(max(rates) * planned, 1),
                                       "basis": f"lowest and highest bugs per {trusted} so far, times planned {trusted}"}
        out.update({"stage": 1, "stage_name": "indicative range",
                    "stage_reason": f"{n} closed releases: enough to show the historical range, too few to test a model "
                                    f"(needs {min_model})",
                    "forecast": fc})
        return out
    min_train = 3
    table = []
    for name, desc, params, fn, needs_e in METHODS:
        if needs_e and not use_exposure:
            continue
        errs = backtest(y, e, fn, min_train)
        if errs is None:
            continue
        pred = fn(y, e, planned if use_exposure else None)
        row = {"method": name, "description": desc, "parameters": params,
               "backtest_folds": len(errs), "backtest_mae": round(sum(errs) / len(errs), 3),
               "next_release": round(pred, 1), "_errs": errs}
        if name == "ses":
            row["alpha"] = best_alpha(y)
        table.append(row)
    naive = next(r for r in table if r["method"] == "naive_last")
    best = min(table, key=lambda r: r["backtest_mae"])        # first minimum = simplest on ties
    if naive["backtest_mae"] == 0:
        skill = 0.0
    else:
        skill = round(1 - best["backtest_mae"] / naive["backtest_mae"], 3)
    beat = best["method"] != "naive_last" and skill >= min_skill
    chosen = best if beat else naive
    errs = chosen["_errs"]
    if len(errs) >= 4:
        spread, interval = quantile(errs, 0.8), "point plus or minus the 80th percentile of backtest errors"
    else:
        spread, interval = max(errs), f"point plus or minus the largest of {len(errs)} backtest errors"
    point = chosen["next_release"]
    fc = {"point": point, "low": round(max(0.0, point - spread), 1), "high": round(point + spread, 1),
          "label": "modeled" if beat else "naive baseline",
          "method": chosen["description"], "interval": interval}
    caveats.append(f"The backtest has {len(errs)} fold(s). With so few, a win over the naive baseline is weak evidence.")
    out.update({"stage": 2, "stage_name": "tested simple model",
                "stage_reason": f"{n} closed releases: simple methods were backtested from the 4th release onward",
                "methods": [{k: v for k, v in r.items() if not k.startswith("_")} for r in table],
                "naive_backtest_mae": naive["backtest_mae"], "best_method": best["method"],
                "skill_vs_naive": skill, "beat_naive": beat,
                "decision": (f"'{best['method']}' beat the naive baseline by {skill:.0%} in the backtest, so it is reported."
                             if beat else
                             f"No method beat the naive baseline by at least {min_skill:.0%}, so the naive baseline is reported."),
                "forecast": fc})
    return out


def cmd_forecast(args):
    emit(compute_forecast(args.root, args.target, args.trusted, args.planned,
                          args.min_indicative, args.min_model, args.min_skill), args.out)
    return 0


# ----------------------------------------------------------------------------- snapshot / export
def cmd_snapshot(args):
    paths = P(args.root)
    releases = {r["release"]: r for r in load_releases(args.root)}
    if args.release not in releases:
        raise SystemExit(f"error: release '{args.release}' is not in releases.csv")
    if releases[args.release].get("status") != "closed":
        raise SystemExit(f"error: release '{args.release}' is not closed; only closed releases are frozen")
    errors, _, _ = validate_ledger(args.root, allow_drift=True)
    if errors:
        raise SystemExit("error: the ledger does not validate; fix it before taking a snapshot:\n  " + "\n  ".join(errors[:10]))
    target = paths["snapshots"] / f"{args.release}.json"
    if target.exists() and not args.force:
        raise SystemExit(f"error: {target} exists; a snapshot is write-once (use --force to replace it on purpose)")
    bugs, _ = load_bugs(args.root)
    digest, n = release_hash(bugs, args.release)
    stats = compute_stats(args.root, args.release)
    paths["snapshots"].mkdir(parents=True, exist_ok=True)
    emit({"release": args.release, "frozen_at": now_iso(), "bugs": n, "records_sha256": digest,
          "summary": stats["per_release"][0]}, target)
    return 0


def cmd_export(args):
    bugs, _ = load_bugs(args.root)
    rows = [clean(b) for b in bugs]
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    front = [c for c in REQUIRED_ALWAYS + REQUIRED_STANDARD if c in cols]
    cols = front + sorted(c for c in cols if c not in front)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([json.dumps(r[c], ensure_ascii=False) if isinstance(r.get(c), (list, dict)) else r.get(c, "") for c in cols])
    print(f"wrote {args.out} ({len(rows)} rows, {len(cols)} columns)")
    return 0


# ----------------------------------------------------------------------------- report
def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def forecast_lines(fc):
    if not fc:
        return ["No forecast file was supplied."]
    lines = [f"Stage {fc['stage']} ({fc['stage_name']}): {fc['stage_reason']}."]
    f = fc.get("forecast")
    if f is None:
        lines.append("No forecast is shown at this stage.")
    else:
        lines.append(f"Next release, {fc['target'].replace('_', ' ')}: about {f['point']:g}, "
                     f"range {f['low']:g} to {f['high']:g} ({f['label']}; {f['method']}; {f['interval']}).")
        if f.get("exposure_adjusted"):
            a = f["exposure_adjusted"]
            lines.append(f"Adjusted for planned size: {a['low']:g} to {a['high']:g} ({a['basis']}).")
        if fc.get("decision"):
            lines.append(fc["decision"])
    lines.extend(fc.get("caveats", []))
    return lines


def table_rows(stats):
    rows = []
    for s in stats["per_release"]:
        rows.append([s["release"], s["status"] or "", str(s["bugs"]), str(s["high_critical"]),
                     pct(s["automatable_before_uat"]["share_of_classified"]), pct(s["ac_related"]["share_of_classified"]),
                     f"{s['by_root_cause_status'].get('Confirmed', 0)} of {s['bugs']}"])
    return rows


HEAD = ["Release", "Status", "UAT bugs", "High or critical", "Automatable before UAT", "AC-related", "Causes confirmed"]


def render_md(stats, fc, nar):
    cum, labels = stats["cumulative"], stats["labels"]["categories"]
    scope = stats["scope"]["release"] or "all releases (cumulative)"
    L = [f"# UAT bug report: {scope}", "",
         f"Generated {stats['generated_at']} from the ledger (schema v{stats['schema_version']}, "
         f"taxonomy v{stats['taxonomy_version']}). Every figure is computed by uat_ledger.py.", ""]
    if nar.get("headline"):
        L += ["## Headline", "", nar["headline"], ""]
    if nar.get("findings"):
        L += ["## Findings", ""]
        for f in nar["findings"]:
            keys = ", ".join(f.get("bug_keys", []))
            L.append(f"- {f.get('text', '')} [{f.get('status', 'Unconfirmed')}]" + (f" ({keys})" if keys else ""))
        L.append("")
    if nar.get("actions"):
        L += ["## Recommended actions", ""]
        for i, a in enumerate(nar["actions"], 1):
            L.append(f"{i}. {str(a.get('text', '')).rstrip('. ')}. Owner: {a.get('owner') or 'Owner TBD'}. Priority: {a.get('priority') or 'TBD'}.")
        L.append("")
    if nar.get("dev_focus_gap"):
        L += ["## Developer testing gap to close first", "", nar["dev_focus_gap"], ""]
    L += ["## Numbers by release", "", "| " + " | ".join(HEAD) + " |", "|" + "|".join([" --- "] * len(HEAD)) + "|"]
    L += ["| " + " | ".join(r) + " |" for r in table_rows(stats)]
    L += ["", f"Total in scope: {cum['bugs']} bugs, {cum['high_critical']} high or critical.", ""]

    def block(title, counts, namer=lambda k: k):
        out = [f"## {title}", "", "| Item | Bugs | Share |", "| --- | --- | --- |"]
        out += [f"| {namer(k)} | {v} | {pct(share(v, cum['bugs']))} |" for k, v in counts.items()]
        return out + [""]

    L += block("Root-cause category", cum["by_category"], lambda k: labels.get(k, k))
    L += block("Why developer testing missed it", cum["by_escape_reason"])
    L += block("Earliest test level that could have caught it", cum["by_catch_level"])
    L += block("Acceptance-criteria issue", cum["by_ac_issue"])
    L += ["## Recurring patterns", ""]
    if stats["patterns"]:
        L += ["| Category | Component | Bugs | Confirmed | Suspected | Bug keys |", "| --- | --- | --- | --- | --- | --- |"]
        L += [f"| {labels.get(p['category'], p['category'])} | {p['component']} | {p['bugs']} | {p['confirmed']} | "
              f"{p['suspected']} | {', '.join(p['bug_keys'])} |" for p in stats["patterns"]]
    else:
        L.append("No category and component pair has two or more bugs in this scope.")
    L += ["", "A shared category and component is a place to look, not proof of a shared cause.", "",
          "## Trend across closed releases", ""]
    t = stats["trend"]
    if t["releases"]:
        L += ["| Measure | " + " | ".join(t["releases"]) + " | Direction |", "|" + "|".join([" --- "] * (len(t["releases"]) + 2)) + "|",
              "| UAT bugs | " + " | ".join(str(v) for v in t["bugs"]) + f" | {t['direction']['bugs']} |",
              "| High or critical | " + " | ".join(str(v) for v in t["high_critical"]) + f" | {t['direction']['high_critical']} |",
              "| Automatable before UAT | " + " | ".join(pct(v) for v in t["automatable_before_uat_share"]) + f" | {t['direction']['automatable_before_uat_share']} |",
              "| AC-related | " + " | ".join(pct(v) for v in t["ac_related_share"]) + f" | {t['direction']['ac_related_share']} |",
              "", t["direction_rule"]]
    else:
        L.append("No closed release yet. This data set is the baseline.")
    L += ["", "## Forecast", ""] + [f"- {x}" for x in forecast_lines(fc)] + [""]
    q = stats["data_quality"]
    L += ["## Data quality and limitations", "",
          f"- Catch level not established: {pct(q['unknown_catch_level_share'])} of bugs.",
          f"- Escape reason not established: {pct(q['unknown_escape_reason_share'])} of bugs.",
          f"- Root cause Unconfirmed: {pct(q['unconfirmed_share'])} of bugs.",
          f"- Change origin unknown: {pct(q['unknown_origin_share'])} of bugs.",
          "- Counts are not adjusted for release size unless an exposure measure is marked trusted in the profile."]
    L += [f"- {x}" for x in nar.get("limitations", [])]
    if nar.get("assumptions"):
        L += ["", "## Assumptions", ""] + [f"- {x}" for x in nar["assumptions"]]
    L += ["", "Root-cause conclusions and corrective actions need human review before the team relies on them.", ""]
    return "\n".join(L)


CSS = """
:root{--ink:#10151C;--muted:#4A5565;--line:#D5DAE1;--ground:#F3F5F7;--card:#FFFFFF;--blue:#1F5AA8;--orange:#A8490A}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:32px 20px 64px}h1{font-size:30px;line-height:1.2;margin:0 0 4px}
h2{font-size:20px;margin:32px 0 12px}.meta{color:var(--muted);font-size:14px}
.headline{font-size:22px;line-height:1.35;margin:20px 0;padding:16px 20px;background:var(--card);border:1px solid var(--line);border-radius:8px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(190px,100%),1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.tile b{display:block;font-size:30px;line-height:1.1}.tile span{color:var(--muted);font-size:14px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}
.card h3{margin:0 0 10px;font-size:16px}.bar{display:grid;grid-template-columns:minmax(0,1fr) 44px;gap:8px;align-items:center;margin:8px 0;font-size:14px}
.bar .track{grid-column:1/-1;height:8px;background:#E6EAEF;border-radius:4px;overflow:hidden}.bar .fill{height:100%;background:var(--blue)}
.bar .n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;background:var(--card)}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:12px;color:var(--muted)}
ul,ol{padding-left:20px}li{margin:6px 0}.note{color:var(--muted);font-size:14px}
"""


def esc(x):
    return html.escape(str(x))


def bars(title, counts, total, namer=lambda k: k):
    rows = []
    for k, v in counts.items():
        w = 0 if not total else round(v / total * 100, 1)
        rows.append(f'<div class="bar"><span>{esc(namer(k))}</span><span class="n">{v}</span>'
                    f'<div class="track"><div class="fill" style="width:{w}%"></div></div></div>')
    return f'<div class="card"><h3>{esc(title)}</h3>{"".join(rows) or "<p class=note>No data.</p>"}</div>'


def render_html(stats, fc, nar):
    cum, labels = stats["cumulative"], stats["labels"]["categories"]
    scope = stats["scope"]["release"] or "all releases (cumulative)"
    f = (fc or {}).get("forecast")
    tiles = [(cum["bugs"], "UAT bugs in scope"), (cum["high_critical"], "High or critical"),
             (pct(cum["automatable_before_uat"]["share_of_classified"]), "Could have been caught by an automated test before UAT"),
             (pct(cum["ac_related"]["share_of_classified"]), "Involve an acceptance-criteria issue"),
             (f"{cum['by_root_cause_status'].get('Confirmed', 0)} of {cum['bugs']}", "Root causes confirmed")]
    H = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f"<title>UAT bug report: {esc(scope)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>UAT bug report: {esc(scope)}</h1>",
         f'<p class="meta">Generated {esc(stats["generated_at"])} from the ledger. Every figure is computed by uat_ledger.py.</p>']
    if nar.get("headline"):
        H.append(f'<p class="headline">{esc(nar["headline"])}</p>')
    H.append('<div class="tiles">' + "".join(f'<div class="tile"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for v, k in tiles) + "</div>")
    if nar.get("findings"):
        H.append("<h2>Findings</h2><ul>" + "".join(
            f'<li>{esc(x.get("text", ""))} <span class="tag">{esc(x.get("status", "Unconfirmed"))}</span> '
            f'<span class="note">{esc(", ".join(x.get("bug_keys", [])))}</span></li>' for x in nar["findings"]) + "</ul>")
    if nar.get("actions"):
        H.append("<h2>Recommended actions</h2><ol>" + "".join(
            f'<li>{esc(str(a.get("text", "")).rstrip(". "))}. <span class="note">Owner: {esc(a.get("owner") or "Owner TBD")}. '
            f'Priority: {esc(a.get("priority") or "TBD")}.</span></li>' for a in nar["actions"]) + "</ol>")
    if nar.get("dev_focus_gap"):
        H.append(f'<h2>Developer testing gap to close first</h2><p>{esc(nar["dev_focus_gap"])}</p>')
    H.append('<h2>Where the bugs are</h2><div class="cols">'
             + bars("Root-cause category", cum["by_category"], cum["bugs"], lambda k: labels.get(k, k))
             + bars("Why developer testing missed it", cum["by_escape_reason"], cum["bugs"])
             + bars("Earliest test level that could have caught it", cum["by_catch_level"], cum["bugs"])
             + bars("Acceptance-criteria issue", cum["by_ac_issue"], cum["bugs"]) + "</div>")
    H.append('<h2>Numbers by release</h2><div class="scroll"><table><thead><tr>'
             + "".join(f'<th{" class=num" if i > 1 else ""}>{esc(h)}</th>' for i, h in enumerate(HEAD)) + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(f'<td{" class=num" if i > 1 else ""}>{esc(c)}</td>' for i, c in enumerate(r)) + "</tr>"
                       for r in table_rows(stats)) + "</tbody></table></div>")
    H.append("<h2>Recurring patterns</h2>")
    if stats["patterns"]:
        H.append('<div class="scroll"><table><thead><tr><th>Category</th><th>Component</th><th class=num>Bugs</th>'
                 "<th class=num>Confirmed</th><th class=num>Suspected</th><th>Bug keys</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{esc(labels.get(p['category'], p['category']))}</td><td>{esc(p['component'])}</td>"
                           f"<td class=num>{p['bugs']}</td><td class=num>{p['confirmed']}</td><td class=num>{p['suspected']}</td>"
                           f"<td>{esc(', '.join(p['bug_keys']))}</td></tr>" for p in stats["patterns"])
                 + "</tbody></table></div><p class=note>A shared category and component is a place to look, not proof of a shared cause.</p>")
    else:
        H.append("<p class=note>No category and component pair has two or more bugs in this scope.</p>")
    H.append("<h2>Forecast</h2>")
    if f:
        H.append(f'<div class="tiles"><div class="tile"><b>{f["low"]:g} to {f["high"]:g}</b>'
                 f'<span>Expected {esc((fc or {}).get("target", "bugs").replace("_", " "))} next release ({esc(f["label"])})</span></div></div>')
    H.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in forecast_lines(fc)) + "</ul>")
    q = stats["data_quality"]
    lim = [f"Catch level not established for {pct(q['unknown_catch_level_share'])} of bugs.",
           f"Root cause Unconfirmed for {pct(q['unconfirmed_share'])} of bugs.",
           "Counts are not adjusted for release size unless an exposure measure is marked trusted in the profile."] + list(nar.get("limitations", []))
    H.append("<h2>Data quality and limitations</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in lim) + "</ul>")
    if nar.get("assumptions"):
        H.append("<h2>Assumptions</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in nar["assumptions"]) + "</ul>")
    H.append('<p class="note">Root-cause conclusions and corrective actions need human review before the team relies on them.</p>')
    H.append("</main></body></html>")
    return "\n".join(H)


def cmd_report(args):
    stats = load_json(args.stats)
    fc = load_json(args.forecast)
    nar = load_json(args.narrative) or {}
    text = render_md(stats, fc, nar) if args.format == "md" else render_html(stats, fc, nar)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


# ----------------------------------------------------------------------------- acceptance
ANSWER_COLUMNS = ["key", "category", "cause_clear", "cause_verdict"]
RESULT_COLUMNS = ["key", "category", "root_cause_status", "cause_verdict"]
HELD_BACK = ("Suspected", "Unconfirmed")


def read_table(path, required, what):
    """Read a CSV into {key: row}. Values are stripped; a missing column or a duplicate key stops the run."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"error: {what} file not found: {path}")
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in (reader.fieldnames or [])]
        missing = [c for c in required if c not in cols]
        if missing:
            raise SystemExit(f"error: {what} file {path} is missing column(s): {', '.join(missing)}")
        rows = {}
        for n, r in enumerate(reader, 2):
            row = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            if not row.get("key"):
                continue
            if row["key"] in rows:
                raise SystemExit(f"error: {what} file {path} line {n}: duplicate key {row['key']}")
            rows[row["key"]] = row
    return rows


def pick(value, allowed, where):
    """Match a cell to one of the allowed values, ignoring case. Blank stays blank."""
    if value == "":
        return ""
    for a in allowed:
        if value.lower() == a.lower():
            return a
    raise SystemExit(f"error: {where}: '{value}' is not one of {', '.join(allowed)}")


def compute_acceptance(root, answers_path, results_path=None, baseline_path=None,
                       min_bugs=20, min_category_match=0.95, max_confirmed_wrong=0):
    """Score one backtest run against the success criteria.

    answers  the team's answer key: key, category, cause_clear (yes|no), cause_verdict (right|wrong|blank)
    results  the run being scored. Default: the ledger at root. A CSV (key, category,
             root_cause_status, cause_verdict) scores a run that is not in the ledger,
             such as the original prompt.
    baseline a scorecard written earlier by this command; the honest-uncertainty rate is compared with it.
    """
    cb = load_codebook(root)
    cats = codes(cb, "categories")
    statuses = codes(cb, "root_cause_statuses")
    answers = read_table(answers_path, ANSWER_COLUMNS[:3], "answers")
    if not answers:
        raise SystemExit(f"error: answers file {answers_path} has no rows")
    for k, a in answers.items():
        a["category"] = pick(a["category"], cats, f"answers {k} category")
        a["cause_clear"] = pick(a["cause_clear"], ["yes", "no"], f"answers {k} cause_clear")
        a["cause_verdict"] = pick(a.get("cause_verdict", ""), ["right", "wrong"], f"answers {k} cause_verdict")
        if not a["category"] or not a["cause_clear"]:
            raise SystemExit(f"error: answers {k}: category and cause_clear are required")

    if results_path:
        source = str(results_path)
        run = read_table(results_path, RESULT_COLUMNS[:3], "results")
        for k, r in run.items():
            r["category"] = pick(r["category"], cats, f"results {k} category")
            r["root_cause_status"] = pick(r["root_cause_status"], statuses, f"results {k} root_cause_status")
            r["cause_verdict"] = pick(r.get("cause_verdict", ""), ["right", "wrong"], f"results {k} cause_verdict")
    else:
        source = "ledger"
        bugs, _ = load_bugs(root)
        run = {str(b.get("bug_key")): {"category": b.get("category") or "",
                                       "root_cause_status": b.get("root_cause_status") or ""} for b in bugs}

    n = len(answers)
    missing, mismatches, wrong, unjudged = [], [], [], []
    matched = held_back = 0
    for k, a in answers.items():
        r = run.get(k)
        if r is None:
            # Not analysed: counts against the category match and against holding back.
            missing.append(k)
            continue
        if r["category"] == a["category"]:
            matched += 1
        else:
            mismatches.append({"key": k, "expected": a["category"], "got": r["category"] or "Not provided"})
        verdict = r["cause_verdict"] if results_path else a["cause_verdict"]
        if r["root_cause_status"] == "Confirmed":
            if verdict == "wrong":
                wrong.append(k)
            elif verdict == "":
                unjudged.append(k)
        if a["cause_clear"] == "no" and r["root_cause_status"] in HELD_BACK:
            held_back += 1
    unclear_total = sum(1 for a in answers.values() if a["cause_clear"] == "no")

    def row(id_, label, value, target, status, **extra):
        d = {"id": id_, "label": label, "value": value, "target": target, "status": status}
        d.update(extra)
        return d

    criteria = [row("sample_size", "Backtest size", n, f"at least {min_bugs} bugs",
                    "pass" if n >= min_bugs else "fail")]

    # A Confirmed cause nobody has judged yet cannot count as right.
    if len(wrong) > max_confirmed_wrong:
        st = "fail"
    elif unjudged:
        st = "not judged"
    else:
        st = "pass"
    criteria.append(row("confirmed_wrong", "Causes marked Confirmed that prove wrong", len(wrong),
                        f"at most {max_confirmed_wrong}", st, unjudged=len(unjudged)))

    # Compare counts, not rounded shares: 19 of 20 must meet a 0.95 target exactly.
    criteria.append(row("category_match", "Category matches the team's call", share(matched, n),
                        f"at least {min_category_match:.0%}",
                        "pass" if matched + 1e-9 >= min_category_match * n else "fail", matched=matched, of=n))

    rate = share(held_back, unclear_total)
    base = None
    if baseline_path:
        card = load_json(baseline_path) or {}
        base = next((c.get("value") for c in card.get("criteria", []) if c.get("id") == "honest_uncertainty"), None)
    if rate is None:
        st, note = "not judged", "No bug in the answers has cause_clear = no; add some unclear cases."
    elif baseline_path is None:
        st, note = "not judged", "No --baseline scorecard given; score the original prompt first to compare."
    elif base is None:
        st, note = "not judged", "The baseline scorecard has no honest-uncertainty rate."
    else:
        st, note = ("pass" if rate + 1e-9 >= base else "fail"), ""
    criteria.append(row("honest_uncertainty", "Unclear causes kept at Suspected or Unconfirmed", rate,
                        "at least the baseline's rate", st, held_back=held_back, of=unclear_total,
                        baseline=base, note=note))

    if not results_path:
        errors, _, _ = validate_ledger(root, allow_drift=True)
        criteria.append(row("ledger_validates", "Ledger passes validation", len(errors), "0 errors",
                            "pass" if not errors else "fail"))

    states = [c["status"] for c in criteria]
    result = "fail" if "fail" in states else ("incomplete" if "not judged" in states else "pass")
    return {
        "result": result, "scored_at": now_iso(), "source": source, "answers": str(answers_path), "bugs": n,
        "criteria": criteria,
        "category_mismatches": mismatches, "confirmed_wrong_keys": wrong,
        "confirmed_unjudged_keys": unjudged, "missing_keys": missing,
        "not_scored_here": [
            "Forecast skill: the forecast command applies its own backtest and reports the result.",
            "Unapproved writes: prevented by the agent's disallowedTools line and the human-only apply step.",
        ],
    }


def cmd_acceptance(args):
    card = compute_acceptance(args.root, args.answers, args.results, args.baseline,
                              args.min_bugs, args.min_category_match, args.max_confirmed_wrong)
    emit(card, args.out)
    if args.out:
        print(f"result: {card['result']}")
        for c in card["criteria"]:
            value = c["value"]
            if "of" in c:
                done = c.get("matched", c.get("held_back"))
                value = "no cases" if value is None else f"{value:.0%} ({done} of {c['of']})"
            target = c["target"] if c.get("baseline") is None else f"{c['target']}, {c['baseline']:.0%}"
            print(f"  {c['status']:<10} {c['label']}: {value} (target: {target})")
            if c.get("note"):
                print(f"             {c['note']}")
    return {"pass": 0, "fail": 1}.get(card["result"], 2)


# ----------------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(prog="uat_ledger.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--root", default=".", help="repo root that contains ledger/ (default: current directory)")
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create the starter layout")
    sp = add("upsert", cmd_upsert, "merge records into the ledger")
    sp.add_argument("--from", dest="source", required=True, help="JSON Lines file or JSON array of bug records")
    sp.add_argument("--run-id")
    sp.add_argument("--force", action="store_true", help="allow changes to a release frozen by a snapshot")
    sp = add("validate", cmd_validate, "check the ledger")
    sp.add_argument("--expect", help="file with one bug key per line that must be present")
    sp.add_argument("--allow-drift", action="store_true", help="report snapshot drift as a warning, not an error")
    sp = add("stats", cmd_stats, "compute statistics")
    sp.add_argument("--release")
    sp.add_argument("--trusted", action="append", choices=EXPOSURES, help="exposure measure the profile marks trusted (repeatable)")
    sp.add_argument("--out")
    sp = add("forecast", cmd_forecast, "staged forecast for the next release")
    sp.add_argument("--target", choices=["bugs", "high_critical"], default="bugs")
    sp.add_argument("--trusted", choices=EXPOSURES, help="trusted exposure measure to adjust for release size")
    sp.add_argument("--planned", type=float, help="planned value of that exposure measure for the next release")
    sp.add_argument("--min-indicative", type=int, default=3)
    sp.add_argument("--min-model", type=int, default=6)
    sp.add_argument("--min-skill", type=float, default=0.10)
    sp.add_argument("--out")
    sp = add("snapshot", cmd_snapshot, "freeze a closed release")
    sp.add_argument("--release", required=True)
    sp.add_argument("--force", action="store_true")
    sp = add("export", cmd_export, "write a flat CSV for BI tools")
    sp.add_argument("--out", required=True)
    sp = add("report", cmd_report, "render Markdown or HTML from stats")
    sp.add_argument("--stats", required=True)
    sp.add_argument("--forecast")
    sp.add_argument("--narrative", help="JSON with headline, findings, actions, dev_focus_gap, assumptions, limitations")
    sp.add_argument("--format", choices=["md", "html"], required=True)
    sp.add_argument("--out", required=True)
    sp = add("acceptance", cmd_acceptance, "score a backtest against the success criteria")
    sp.add_argument("--answers", required=True, help="CSV answer key: key, category, cause_clear, cause_verdict")
    sp.add_argument("--results", help="CSV of a run that is not in the ledger: key, category, root_cause_status, cause_verdict")
    sp.add_argument("--baseline", help="scorecard JSON of the run to beat, written earlier with --out")
    sp.add_argument("--min-bugs", type=int, default=20)
    sp.add_argument("--min-category-match", type=float, default=0.95)
    sp.add_argument("--max-confirmed-wrong", type=int, default=0)
    sp.add_argument("--out")

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
