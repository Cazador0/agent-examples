# UAT analytics kit

A Claude Code agent that analyzes UAT bugs per release and cumulatively, explains why developer testing missed them, and forecasts only as far as the history supports. Built for Claude Code on Amazon Bedrock, with Guidewire as the first stack profile.

## What is here

```
agent-src/uat.agent.md            annotated source. Read this one; every section says why it is written that way
.claude/agents/uat.agent.md       lean twin, generated. This is the copy Claude Code loads
.claude/skills/uat-ledger/        ledger schema, codebook rules and the script that computes every number
.claude/skills/uat-stack-guidewire/   PolicyCenter, ClaimCenter, BillingCenter, ContactManager, integrations
.claude/skills/uat-stack-generic/     any other application, the integration checklist, a profile template
.claude/skills/uat-report/        output standards, including your workbook and dashboard standard
.claude/skills/uat-writeback/     how the agent proposes Jira changes
.claude/skills/uat-writeback-apply/   the only thing that writes to Jira; a model cannot start it
.claude/settings.json             lets the two scripts run without a prompt
config/uat-profile.yaml           your answers: release key, roles, identifiers, exposure, outputs
ledger/                           the record: bugs.jsonl, releases.csv, codebook.json, snapshots/
reports/                          one folder per run
writeback/                        proposed/ -> approved/ -> applied/
backtest/                         answer key and scorecards for the acceptance test
tools/build_agent.py              source -> lean twin
tools/stop_gate.py                optional hard gate (see Hardening)
examples/synthetic/               fake data to try every command without Jira
tests/                            checks for the scripts and the twin
```

## Install

1. Create an empty repository, for example `uat-analytics`, and copy this folder into it.
2. Check that Claude Code is on Bedrock: run `/status` in a session and confirm the provider. Your administrators should have pinned models with `ANTHROPIC_MODEL` or the `ANTHROPIC_DEFAULT_*_MODEL` variables; the agent uses `model: inherit` and follows that pin.
3. Open `config/uat-profile.yaml` and resolve every line marked `CONFIRM`. The UAT bug filter matters most: a wrong filter gives wrong counts.
4. Run the checks: `python3 -m unittest discover -s tests`.
5. Start `claude` in the repository once and accept the workspace trust dialog. Until you do, Claude Code ignores the two allow rules in `.claude/settings.json`.
6. Block tracker writes for the agent. Find the exact names of your Jira plugin's create, update and comment tools with `/mcp` in a session. Add them to the `disallowedTools` line in `agent-src/uat.agent.md` and rebuild. The names below are made up; use yours:

   ```yaml
   disallowedTools: WebFetch, WebSearch, NotebookEdit, mcp__jira__create_issue, mcp__jira__edit_issue, mcp__jira__add_comment
   ```

   ```bash
   python3 tools/build_agent.py
   ```

   Then set `tracker_writes_denied: true` in the profile. Until this step is done, "the agent only proposes Jira changes" is a rule in the prompt, not a block.

   Put the names in the agent file, not in a `deny` rule in `.claude/settings.json`. A deny rule there covers the whole session and no allow rule can override it, so it would also block `/uat-writeback-apply`. In the agent file the tools are removed from the `uat` agent only. For the same reason, run the apply step in a plain `claude` session, not in one started with `--agent uat`. If your plugin writes through a shell command and not through MCP tools, this line cannot single it out. That case needs a `PreToolUse` hook in the agent's frontmatter, which this kit does not include.

Two Bedrock facts to know. The WebSearch tool is not available on Bedrock, and the agent does not depend on it. Model aliases resolve to Claude Code's built-in Bedrock defaults unless your team pins them.

## Try it in two minutes, without Jira

```bash
python3 examples/synthetic/make_synthetic.py --out /tmp/uat-demo --closed 7
L="python3 .claude/skills/uat-ledger/scripts/uat_ledger.py"
$L init     --root /tmp/uat-demo
$L upsert   --root /tmp/uat-demo --from /tmp/uat-demo/batch.jsonl
$L validate --root /tmp/uat-demo
$L stats    --root /tmp/uat-demo --out /tmp/uat-demo/reports/stats.json
$L forecast --root /tmp/uat-demo --out /tmp/uat-demo/reports/forecast.json
$L report   --root /tmp/uat-demo --stats /tmp/uat-demo/reports/stats.json --forecast /tmp/uat-demo/reports/forecast.json --format html --out /tmp/uat-demo/reports/dashboard.html
```

Change `--closed` to 2, 4 and 7 to watch the forecast move through its three stages.

The generator also writes a made-up backtest of 20 bugs, so you can try the scorecard described below. Its numbers are invented and say nothing about how any prompt performs.

```bash
B=/tmp/uat-demo/backtest
$L acceptance --root /tmp/uat-demo --answers $B/answers.csv --results $B/original-results.csv --out $B/original-scorecard.json
$L acceptance --root /tmp/uat-demo --answers $B/answers.csv --baseline $B/original-scorecard.json --out $B/scorecard.json
```

## Four ways to run the agent

**1. Delegated, from a normal session.** Start in this repository and attach the product repositories you want evidence from.

```bash
claude --add-dir ../policycenter --add-dir ../claimcenter
```

Then ask: `Use the uat agent to analyze the UAT bugs for fix version 2026.11 at Standard depth.` or address it directly with `@agent-uat`. A delegated agent cannot open a question dialog, so it records its assumptions and continues.

**2. As the whole session.** `claude --agent uat` starts with a preflight report and asks what to analyze. Use this when you want it to interview you.

**3. Headless, for a pipeline or a schedule.** Nobody can approve a prompt, so pre-approve exactly what the run needs and deny the rest.

```bash
claude -p "Analyze the UAT bugs for fix version 2026.11 at Standard depth. Nobody is available to answer questions." \
  --agent uat \
  --add-dir ../policycenter \
  --permission-mode dontAsk \
  --allowedTools "Read,Grep,Glob,Edit,Bash(python3 .claude/skills/uat-ledger/scripts/uat_ledger.py *),<your Jira read tools>,<your Bitbucket read tools>" \
  --max-budget-usd 15 \
  --output-format json > reports/last-run.json
```

The budget cap is an example; set your own. Find the exact tool names of your Jira and Bitbucket plugins with `/mcp` in a session, or by running once with `--verbose`. Do not add `--bare` to this command: bare mode skips agents, skills, plugins and MCP servers. The Claude Code documentation says bare mode will become the default for `-p` in a future release; when it does, pass what the run needs explicitly (`--agents`, `--plugin-dir`, `--mcp-config`, `--settings`).

**4. Inside an Agent SDK application.** The SDK reads the same files when the project setting source is loaded. A sketch; check option names against the SDK reference for your version:

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        cwd="/path/to/uat-analytics",
        setting_sources=["project"],      # loads .claude/agents, .claude/skills and CLAUDE.md
        allowed_tools=["Agent", "Skill", "Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    )
    prompt = "Use the uat agent to analyze the UAT bugs for fix version 2026.11 at Standard depth."
    async for message in query(prompt=prompt, options=options):
        print(message)

asyncio.run(main())
```

## Backtest it before you rely on it

This step comes from your original document, and it is the most important one.

The agent is accepted when one backtest meets every target below. The targets are in the `acceptance` block of the profile.

| Criterion | Target |
| --- | --- |
| Backtest size | At least 20 resolved bugs. With fewer, a 95% target allows no miss at all. |
| Causes marked Confirmed that prove wrong | Zero |
| Category matches the team's call | 95% or more (19 of 20) |
| Unclear causes kept at Suspected or Unconfirmed | At least as often as your original prompt on the same bugs |
| Ledger validation | Passes |

Two more criteria are checked elsewhere. The forecast command backtests itself and reports a method only when it beats "repeat the last release" by 10%. Unapproved Jira writes are prevented by the agent's `disallowedTools` line from Install step 6 and the human-only apply step.

**Steps**

1. Pick at least 20 resolved UAT bugs whose causes the team agrees on. Include some whose cause could not be known from the ticket alone.
2. Write the answer key from `backtest/answers.template.csv`, one row per bug: `key`, the team's `category` code from `ledger/codebook.json`, and `cause_clear` (`yes` if the ticket as reported holds enough evidence to confirm the cause, `no` if it does not). Leave `cause_verdict` blank for now. Keep this file outside the repository until the runs have finished, so the agent cannot read the answers.
3. Work on a branch and do not merge its ledger changes: these records were analysed with evidence hidden.
4. Give the agent each ticket as it looked when it was reported: description, acceptance criteria, steps. Leave out resolution comments and fix links. Run at Standard depth.
5. Run your original prompt on the same tickets. Copy what it returned into a file made from `backtest/original-results.template.csv`: `key`, `category` (as a codebook code), `root_cause_status`, and `cause_verdict` (`right` or `wrong`) for every cause it marked Confirmed.
6. Copy the answer key to `backtest/answers.csv`. For every cause the agent marked Confirmed, fill in `cause_verdict` with `right` or `wrong`. A Confirmed cause left blank makes the result incomplete.
7. Score both runs. The first command scores the original prompt and its result line does not matter; the second compares the agent with it.

   ```bash
   $L acceptance --root . --answers backtest/answers.csv --results backtest/original-results.csv --out backtest/original-scorecard.json
   $L acceptance --root . --answers backtest/answers.csv --baseline backtest/original-scorecard.json --out backtest/scorecard.json
   ```

   The command prints `pass`, `fail` or `incomplete` with one line per criterion, and exits with 0, 1 or 2. The scorecard file lists every category mismatch and every wrong Confirmed cause by bug key. Commit `backtest/` as the record of the decision.
8. When it fails, fix the codebook definition, the stack profile or the profile first, then repeat with a fresh set of bugs. Adding capital letters to the agent file is the last resort, not the first.

People write the answer key and the verdicts. The agent is the one being measured, so it does not fill them in.

## Each release

During UAT, run Quick or Standard on new bugs while the release is `open` in `ledger/releases.csv`. When UAT closes: set the release to `closed`, run Standard or Full, then

```bash
$L validate --root .
$L snapshot --root . --release <fix version>
```

Open a pull request with the ledger, the reports and any file in `writeback/proposed/`. Review is the audit. To approve Jira changes, move the batch to `writeback/approved/` in that pull request; after the merge run `/uat-writeback-apply writeback/approved/<file>` in a plain `claude` session (not one started with `--agent uat`, which has the tracker's write tools removed) and commit the receipt.

## Changing the agent

Edit `agent-src/uat.agent.md`, then `python3 tools/build_agent.py`. In CI, `python3 tools/build_agent.py --check` fails when the twin is stale. Field names in the frontmatter are case-sensitive and an unknown field is ignored without an error, so run with `claude --debug` after a frontmatter change and read the log.

Treat the agent file like code. If the agent ignores a rule, the file is probably too long or the rule unclear. Prune before you add.

## Hardening (optional)

**Keep product code read-only.** Directories added with `--add-dir` can be edited under the session's permission mode. Add deny rules for them to `.claude/settings.json`, using absolute paths with a double leading slash:

```json
{ "permissions": { "deny": ["Edit(//abs/path/to/policycenter/**)", "Edit(//abs/path/to/claimcenter/**)"] } }
```

**Turn the validator into a hard gate.** Instructions are advisory; hooks are deterministic. To stop a run from ending while the ledger fails validation, add this to the frontmatter in `agent-src/uat.agent.md` and rebuild. `tools/stop_gate.py` is tested on its own with piped input; the wiring below follows the documented format and has not been exercised inside a live session here, so try it interactively first.

```yaml
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 \"${CLAUDE_PROJECT_DIR}/tools/stop_gate.py\""
```

## What was tested, and what was not

Tested in the build environment: the frontmatter of both agent files parses; the twin is generated from the source and every instruction line survives; the ledger script's validation rules, statistics, forecast stages and backtest arithmetic (checked against hand calculation), snapshot freezing, CSV export and both report formats; the acceptance scorecard's targets, its comparison with a baseline and its exit codes; the stop gate with piped input. Run `python3 -m unittest discover -s tests -v` to repeat them.

Not tested: the agent running under Claude Code against Bedrock, your Jira and Bitbucket plugins, the Excel workbook build, and the optional hook wiring. The Guidewire profile is written from product documentation and general practice, not from your repositories; expect to correct its component names in the first week.

## Sources

- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Claude Code on Amazon Bedrock: https://code.claude.com/docs/en/amazon-bedrock
- Skills: https://code.claude.com/docs/en/skills
- Memory and CLAUDE.md: https://code.claude.com/docs/en/memory
- Hooks: https://code.claude.com/docs/en/hooks
- Permissions: https://code.claude.com/docs/en/permissions
- Running programmatically: https://code.claude.com/docs/en/headless
- Prompting best practices: https://platform.claude.com/en/docs/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Fitting models to short time series (Rob Hyndman): https://www.r-bloggers.com/2014/03/fitting-models-to-short-time-series/
- Guidewire cloud integration frameworks: https://www.guidewire.com/resources/blog/developers/simplifying-outbound-integrations-in-insurancesuite-cloud-part-1
- Guidewire testing framework: https://www.guidewire.com/developers/developer-tools-and-guides/guidewire-testing-framework
