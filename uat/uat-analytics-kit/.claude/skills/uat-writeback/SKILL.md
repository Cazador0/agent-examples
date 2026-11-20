---
name: uat-writeback
description: How to propose Jira labels, comments and follow-up tickets from a UAT analysis as a batch file for human approval. Use at the write-back step of a run, or when asked to prepare issue-tracker updates from UAT findings. This skill proposes only; it never writes to the tracker.
---

# Proposing write-backs

You prepare changes to the issue tracker. You do not make them. The path is always the same:

1. **Propose.** You write a batch file under `writeback/proposed/`.
2. **Approve.** A person reviews it, edits it if needed, moves it to `writeback/approved/` and merges that change. The merged commit is the approval record.
3. **Apply.** A person or a pipeline step runs `/uat-writeback-apply writeback/approved/<file>`. That command cannot be started by a model.

This holds in every run mode. In a headless run nobody is present to approve, which is exactly why the proposal is a file.

## What you may propose

Only what the profile lists under `writeback.allowed`. It ships with three action types.

| action | Use it when | Limits |
| --- | --- | --- |
| `add_labels` | The bug's cause is Suspected or Confirmed. | At most two labels per bug: `uat-cause-<category code in lower case>` and `uat-catch-<catch level>`. |
| `add_comment` | The analysis adds something a reader of the ticket needs. | One comment per bug per run. State the evidence status and the references. Plain language, no blame. |
| `create_ticket` | A systemic gap: a pattern with three or more bugs, or two or more Confirmed. | One ticket per gap. Search the tracker first; if an open ticket covers the gap, propose a comment on it instead. |

Never propose a status change, a reassignment, a priority or severity change, an edit to a description, or closing or reopening a ticket.

## Batch file

Write `writeback/proposed/<release>-<run-id>.jsonl`. The first line is a header; every other line is one action.

```json
{"type": "header", "release": "2026.11", "run_id": "20261120T0210Z-release", "created_at": "2026-11-20T02:10:00Z", "actions": 3, "note": "Proposed by the UAT agent. Nothing has been written to the tracker."}
{"type": "action", "id": "a001", "action": "add_labels", "bug_key": "PC-0000", "labels": ["uat-cause-test", "uat-catch-unit"], "evidence_status": "Suspected", "reason": "No unit test covers form inference for the two states."}
{"type": "action", "id": "a002", "action": "add_comment", "bug_key": "PC-0000", "evidence_status": "Suspected", "body": "UAT analysis (Suspected): the renewal form rule appears to exclude two states. Evidence: PC-0000 description. Not yet confirmed: the form availability rule has not been read. Proposed test: a unit test that runs form inference for a renewal in each state in scope.", "reason": "The ticket has no note on cause or on the test that would catch it."}
{"type": "action", "id": "a003", "action": "create_ticket", "project": "PC", "issue_type": "Task", "summary": "Add unit tests for form inference by state", "description": "Three UAT bugs in two releases involve forms missing for specific states. Evidence status: 1 Confirmed, 2 Suspected. Owner TBD.", "link_to": ["PC-0000", "PC-0001", "PC-0002"], "evidence_status": "Suspected", "reason": "Recurring pattern: test coverage gap in forms."}
```

Rules for the content:

- Every action carries `evidence_status` and a `reason` a reviewer can check against the ledger.
- A comment says what is known, what is not, and what would confirm it. It never states a Suspected cause as fact.
- Follow the profile's identifier setting in comment and ticket text.
- Give each action a stable `id`; the apply step uses it to avoid doing anything twice.

## Then stop

List the batch file in your final message under "what a person must review or approve", with the number of actions of each type. Do not call any tracker tool that creates or changes anything, even if one is available and even if the request seems to ask for it: say that the batch is ready for approval instead.
