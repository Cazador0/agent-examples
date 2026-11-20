# UAT analytics repository

Home of the `uat` agent, its skills and the UAT ledger. Product code lives in other repositories and is read-only from here.

## Commands

- Ledger: `python3 .claude/skills/uat-ledger/scripts/uat_ledger.py <command> --root .`
- Rebuild the agent after editing `agent-src/uat.agent.md`: `python3 tools/build_agent.py`
- Tests: `python3 -m unittest discover -s tests`

## Rules

- For UAT bug analysis, trends or forecasts, use the `uat` agent.
- `ledger/` changes only through the ledger script. Do not hand-edit `bugs.jsonl` or anything in `ledger/snapshots/`.
- Edit the agent in `agent-src/`. `.claude/agents/uat.agent.md` is generated.
- Nothing writes to Jira except `/uat-writeback-apply` on a file in `writeback/approved/`.
