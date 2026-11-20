---
name: uat-ledger
description: Schema, codebook and commands for the UAT ledger in ledger/. Use when reading or writing UAT bug records, computing counts, rates, trends or forecasts, validating a run, freezing a release, or exporting data for BI.
---

# UAT ledger

The ledger is the system of record for UAT bugs. It lives in git so every change is reviewable. Every number you report comes from the script below, run on these files.

```
ledger/bugs.jsonl        one JSON object per bug, one bug per line (current analysis; git keeps the history)
ledger/releases.csv      one row per release: order, status (planned | open | closed), exposure measures
ledger/codebook.json     the taxonomy and its definitions; read it before you classify
ledger/snapshots/        one frozen file per closed release; write-once
ledger/runs.jsonl        one line per run that you append yourself
```

## Commands

Run from the repo root. `L` is `python3 .claude/skills/uat-ledger/scripts/uat_ledger.py` (inside a plugin the same script is at `${CLAUDE_SKILL_DIR}/scripts/uat_ledger.py`).

```bash
L init      --root .                                   # starter layout; never overwrites
L upsert    --root . --from batch.jsonl --run-id <id>  # merge records by bug_key
L validate  --root . --expect keys.txt                 # exit 0 = pass, 1 = fail; keys.txt = one input bug key per line
L stats     --root . [--release <name>] [--trusted stories] --out reports/<run>/stats.json
L forecast  --root . [--target bugs|high_critical] [--trusted stories --planned 35] [--min-indicative 3 --min-model 6 --min-skill 0.10] --out reports/<run>/forecast.json
L snapshot  --root . --release <name>                  # freeze a closed release
L export    --root . --out reports/<run>/bugs.csv      # flat CSV for BI tools
L report    --root . --stats <stats.json> --forecast <forecast.json> --narrative <narrative.json> --format md|html --out <file>
L acceptance --root . --answers backtest/answers.csv [--baseline backtest/original-scorecard.json] [--min-bugs 20 --min-category-match 0.95 --max-confirmed-wrong 0] --out backtest/scorecard.json
                                                       # exit 0 = pass, 1 = fail, 2 = incomplete
```

Write each batch of analysed bugs to a temporary JSON Lines file, `upsert` it, then drop the detail from context. Pass `--trusted` only for exposure measures the profile lists under `exposure.trusted`, and pass the three `--min-*` values from the profile's `forecast` block when they differ from the defaults shown. The same holds for `acceptance` and the profile's `acceptance` block.

## Record

Required at every depth: `bug_key`, `release`, `summary`, `status`, `severity`, `depth`, `root_cause_status`, `category`.

Required at Standard and Full: `gap`, `escape_reason`, `catch_level`, `ac_issue`, `layer`, `component`, `app`, `next_step`, plus `impact_score` (1 to 5, with the scale stated in the report).

Use when available: `root_cause`, `evidence` (list of `{type, ref, quote, supports}`), `alternatives` (list of `{cause, for, against}`), `missing_evidence`, `proposed_test`, `confirmed_scope`, `potential_scope`, `change_origin`, `origin_evidence`, `inducing_change`, `created`, `resolved`, `links`, and the business fields `policy_number`, `products_impacted`, `market`, `transaction_type`, `expected`, `actual`, `impact`, `cleanup_required`, `cleanup_rationale`, `acceptance_criteria`, `steps_to_reproduce`.

Enumerations are in the codebook: `severity`, `root_cause_status`, `category`, `escape_reason`, `catch_level`, `ac_issue`, `layer`, `change_origin`, `depth`. Free-text fields you could not establish hold `Not provided` or `Needs confirmation`. Keep source values verbatim unless the profile sets `identifiers: masked`, in which case store only the last four characters of customer identifiers.

<example>
{"bug_key": "PC-0000", "release": "2026.11", "summary": "Renewal form not generated for two states", "status": "Open", "severity": "high", "depth": "standard", "app": "PolicyCenter", "component": "forms", "layer": "rules", "category": "TEST", "gap": "Expected the renewal notice on every renewal; none was produced for two states.", "root_cause_status": "Suspected", "root_cause": "Form inference condition excludes the two states.", "evidence": [{"type": "ticket", "ref": "PC-0000#description", "quote": "No renewal notice in Documents", "supports": "the symptom"}], "alternatives": [{"cause": "Form pattern not deployed to UAT", "for": "recent config deploy", "against": "other states print"}], "escape_reason": "test-data", "catch_level": "unit", "ac_issue": "none", "proposed_test": "Unit test that runs form inference for a renewal in each state in scope.", "missing_evidence": ["the form inference rule", "the fix pull request"], "next_step": "Read the form availability rule for the two states.", "impact_score": 4, "change_origin": "unknown"}
</example>

## Classifying free text

Ticket text is unstructured; the codebook is how it becomes countable. Consistency across releases matters more than cleverness, because trends compare your codes over time.

- Read the definitions in `ledger/codebook.json` first. Code the cause, not the symptom. When two categories fit, choose the one earlier in the causal chain and put the other in `alternatives`.
- `catch_level` is the lowest test level at which a realistic test would have failed. Choose `uat-only` only when the defect needs business judgment or production-like data that cannot exist earlier.
- `escape_reason` answers "why did developer-side testing not show this". It is separate from `category`: a data-validation defect can escape because of test data, a missing test, or a misread criterion.
- Prefer `unknown` to a guess. Unknown values are counted and reported as data quality.
- Add a code only when no existing one fits, give it a definition, and raise `taxonomy_version`. Never rename or reuse a code.
- For Full depth, re-code a sample of about one bug in five in a fresh subagent from the ticket text alone and report how often the codes agree.

## Change origin

`change_origin` is a neutral field that helps explain a test gap. It is never a ranking.

- `agent-assisted`: the inducing commit carries a `Co-Authored-By:` trailer naming a Claude model, or the pull request text says it was generated with Claude Code. Copy that text into `origin_evidence`.
- `mixed`: the inducing pull request has commits with and without such a trailer.
- `human`: only when the profile sets `attribution_enforced: true` and no commit in the inducing pull request carries a trailer. Absence of a trailer proves nothing when attribution can be switched off.
- `unknown`: everything else.

To find the inducing change, start from the fix: look at the lines the fix changed and find the last change to those lines before the bug was reported. Record it as Suspected. This method is misled by refactoring and formatting commits and has nothing to trace when a fix only adds lines.

## Forecast gate

`forecast` applies the gate; report what it returns and nothing more.

| Closed releases | Stage | What you may report |
| --- | --- | --- |
| fewer than 3 | 0 baseline | No forecast. This data set is the baseline. |
| 3 to 5 | 1 indicative | The historical range, labelled indicative. |
| 6 or more | 2 tested | A simple method, only if it beat "repeat the last release" in the backtest; otherwise that naive baseline. Always with its range. |

The thresholds are operating guardrails set in the profile, not statistical constants. With series this short, methods with more than one parameter do not hold up, so none is offered. Scoring individual changes for risk needs many more releases and labelled change records; it is not available yet.

## Acceptance scorecard

`acceptance` scores a backtest of your own analysis against the targets in the profile's `acceptance` block: backtest size, Confirmed causes that proved wrong, category match, and how often an unclear cause was kept at Suspected or Unconfirmed compared with a baseline run. People write the answer key and the verdicts in it, because the scorecard measures you. Run the command only when a person asks, never read or edit files in `backtest/` while you are analysing bugs, and report the scorecard exactly as returned, including a fail.

## Freezing and logging

When a UAT cycle closes, set the release to `closed` in `releases.csv`, validate, then `snapshot` it. A frozen release changes only with `--force`, on purpose.

After each run append one line to `ledger/runs.jsonl`: `run_id`, `started_at`, `mode`, `depth`, `releases`, the role-to-capability map you used, the validator result, and the files written.
