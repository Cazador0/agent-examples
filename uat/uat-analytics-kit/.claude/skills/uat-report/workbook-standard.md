# Workbook and Executive Dashboard standard

This is the standard from the team's original "UAT Bug Trends Analyzer" document, moved here so it loads only when a workbook is being built. Three things were added for release trends and forecasts; each is marked **(added)**.

Build the workbook in one script with the spreadsheet-builder capability: formulas, native charts and recalculation. Do not make cell-by-cell tool calls. Take the brand name, palette and fonts from the brand-style capability named in the profile.

## Sheets, in order

1. **Executive Dashboard** (Full only; first and active)
2. **Raw Bugs**: source fields preserved, plus the analysis fields, with filters
3. **Individual Bug Analysis**: every ledger field, the gap, evidence references, status and rationale, missing evidence, clean-up, validation steps
4. **Gap Analysis**: systemic gaps, linked bugs, evidence, status, impact, actions, owner or TBD
5. **Trends**: category counts and percentages, confirmed against suspected, linked bugs, recurrence, analyst charts, how counts were calculated. **(added)** One row per closed release with bugs, high or critical, share automatable before UAT and share AC-related; then a Forecast block with stage, range, method and backtest result.
6. **Evidence & Limitations**: every source that was unavailable and every open question

## Excel standards

- Arial, consistent headers, freeze panes, auto-filters.
- Counts and percentages are formulas over the detail sheets, never typed.
- **(added)** Every formula result must equal the matching figure in `stats.json`. If they differ, the workbook is wrong; fix it before delivering. The Forecast block is the one exception to "never typed": its values are copied from `forecast.json` and labelled "from forecast.json".
- Detail sheets landscape, fit one page wide.
- Ready to email without cleanup.

## Executive Dashboard (Full only)

Build it last; it only reads from the detail sheets. A non-technical reader must understand it in under 60 seconds, and it must fit on one landscape page: print area set, fit 1 by 1, gridlines off, zoom that fits a laptop screen.

Layout, top to bottom:

1. **Title band**: brand name, "UAT Bug Trends", and the scope in one short line, for example "3 UAT bugs, Underwriting, analysis date".
2. **Headline**: one sentence of 25 words or fewer stating the single most important takeaway.
3. **KPI tiles (five at most)**: a big number and a label of 3 to 6 words. Default set: Bugs analyzed; Need customer or data clean-up; Critical or High priority; Awaiting UAT sign-off; Root causes confirmed (as "2 of 3"). All values are formulas.
4. **Chart row (three or four charts)**, each with a title that states the takeaway:
   - bugs by root-cause theme (horizontal bar, sorted)
   - impact by bug (coloured by severity)
   - evidence confidence (stacked bar or doughnut: Confirmed / Likely / Needs more evidence)
   - where bugs cluster (product, market or process stage, whichever has the most spread)
   - **(added)** a trend-over-time line, only when the ledger has three or more closed releases
5. **Top 3 themes**: a dot, the theme in business terms (8 words at most), why it keeps happening (20 words at most), and the bug count.
6. **Recommended actions (exactly 3)**: verb-first, 20 words at most each, with an owner or "Owner TBD" and a priority colour. Rank them by business impact.
7. **Dev focus gap**: one line of 20 words at most naming the testing gap the development team should close first. Link it to its row on Gap Analysis.
8. **Footer**: "Details, evidence and sources are on the following tabs." plus the data-as-of date.

Hard limits:

- no paragraph longer than 2 lines
- about 150 words of prose in total
- no table with more than 5 rows
- no more than 5 colours (brand palette; red, amber and green reserved for severity)
- every number is a formula pointing at a detail sheet

Evidence badges: Confirmed shows as Confirmed (green). Suspected shows as Likely (amber). Unconfirmed shows as Needs more evidence (grey). The badges are presentation only; the evidence rules still apply.

## Charts

- One message per chart.
- Native Excel charts bound to formula cells, never pasted images.
- Horizontal bars for categories; stacked bar or doughnut for parts of a whole (4 slices at most); a line for time. No 3D, no dual axes.
- Direct data labels, sorted by value, with category names mapped to business wording in a helper range.
- Do not rely on colour alone, and hide zero-count categories.

## Render check

Render the dashboard to an image or PDF once and fix anything clipped or overlapping. Render again only if you changed it.

## Checks before delivering the workbook

- Every input bug is accounted for, with its identifiers preserved.
- Required fields are present or marked missing.
- Every count reconciles with the detail sheets and with `stats.json`.
- Every Confirmed cause cites its evidence, and every trend lists its bugs.
- In Full, every dashboard number equals its source cell, the word limits hold, and the badges match the statuses.
