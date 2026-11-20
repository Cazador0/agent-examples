---
name: uat-report
description: Output standards for UAT analysis runs, covering the Markdown report, the HTML dashboard, JSON and CSV for BI, and the Excel workbook with its executive dashboard. Use when a run reaches the report step, or when asked to produce or restyle any UAT output.
---

# UAT outputs

Every output is a view of two files the ledger script writes: `stats.json` and `forecast.json`. You write the words. You never retype a number: if a figure is not in those files, compute it with the script first.

## Which outputs, by depth

The profile's `outputs` block decides. These are the defaults it ships with.

| Depth | Outputs |
| --- | --- |
| Quick | In chat: a triage table (ID, issue, suspected category, status, missing evidence), theme counts, the top three gaps. A file only if asked. |
| Standard | `stats.json`, `forecast.json`, `bugs.csv`, `report.md`, and the workbook detail sheets without the dashboard. |
| Full | Everything in Standard, plus `dashboard.html` and the Executive Dashboard sheet, render-checked. |

Write to `reports/<release or cumulative>/<run-id>/`. `L` is the ledger script (see `uat-ledger`).

## Narrative file

Put the words in `narrative.json` so the layout stays identical from release to release.

```json
{
  "headline": "One sentence, 25 words or fewer: the single most important takeaway.",
  "findings": [{"text": "Theme in business terms and why it recurs.", "bug_keys": ["KEY-1"], "status": "Confirmed"}],
  "actions": [{"text": "Verb-first action, 20 words or fewer.", "owner": null, "priority": "High"}],
  "dev_focus_gap": "The developer testing gap to close first, 20 words or fewer.",
  "assumptions": ["Readings you chose without being able to ask."],
  "limitations": ["Sources you could not reach, in plain words."]
}
```

Up to five findings, most important first, each with its bug keys and an evidence status. Full depth carries exactly three actions, ranked by business impact, each with an owner or `null` (shown as "Owner TBD").

## Markdown and HTML

```bash
L report --root . --stats <dir>/stats.json --forecast <dir>/forecast.json --narrative <dir>/narrative.json --format md   --out <dir>/report.md
L report --root . --stats <dir>/stats.json --forecast <dir>/forecast.json --narrative <dir>/narrative.json --format html --out <dir>/dashboard.html
```

Add analysis the script does not render (per-bug detail, alternatives, missing evidence) to `report.md` below the generated sections, under a heading of your own. Leave the generated sections as they are.

## JSON and CSV for BI

`stats.json` and `forecast.json` are the machine-readable results. `L export --root . --out <dir>/bugs.csv` writes one row per bug. Do not edit any of the three by hand.

## Excel workbook

Use the capability mapped to the spreadsheet-builder role and the one mapped to the brand-style role. Read `workbook-standard.md` in this folder first, then build the whole workbook in one script. If no spreadsheet builder is available, deliver `bugs.csv` and `report.md` and state the limitation.

## Language for managers

A reader who never opens code must understand the dashboard and the headline in under a minute.

- Describe impact as customer, financial, compliance or operational effect: "the renewal form was not printed for customers in two states".
- Keep Jira field names, class and method names, pull-request numbers, commit hashes, type codes and rule identifiers out of the dashboard and the headline. Bug keys appear as small reference tags.
- Show evidence status with these words: Confirmed stays "Confirmed"; Suspected shows as "Likely"; Unconfirmed shows as "Needs more evidence". The words change for the reader; the rules behind them do not.
- At most one caveat line on a dashboard, and only when it changes a decision. Every other limitation goes in the limitations section.

## Check before delivering

- Every figure in the narrative appears in `stats.json` or `forecast.json`.
- Every finding lists its bug keys and its status; every Confirmed finding has evidence in the ledger.
- The forecast is shown with its stage and range, or the reason there is none.
- For the workbook, the checks at the end of `workbook-standard.md` pass.
