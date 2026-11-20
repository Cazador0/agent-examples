---
name: uat-writeback-apply
description: Apply an approved UAT write-back batch (labels, comments, follow-up tickets) to the issue tracker. Started by a person or a pipeline step only.
disable-model-invocation: true
argument-hint: "[writeback/approved/<file>.jsonl]"
---

Apply the approved write-back batch at: $ARGUMENTS

A person approved this batch by merging it into `writeback/approved/`. Your job is to apply exactly what it says, once, and to leave a receipt. Do not add, change or skip an action on your own judgment.

## Before any write

Stop and report, without writing anything, if any of these fails.

1. The path is inside `writeback/approved/` and ends in `.jsonl`.
2. `git status --porcelain -- <file>` prints nothing: the file is committed and unmodified.
3. You are on the repository's default branch. Run `git log -1 --format='%H %an %aI' -- <file>` and show the approving commit, author and date.
4. The first line is a header and every other line is an action whose `action` is `add_labels`, `add_comment` or `create_ticket`, and that type is listed under `writeback.allowed` in `config/uat-profile.yaml`.
5. You have an issue-tracker capability that can perform each action type. If one type cannot be performed, say which and stop.

## Apply

1. Open `writeback/applied/<same file name>` if it exists. Skip every action whose `id` already has a line with `"result": "ok"` there.
2. Take the remaining actions in file order. For each one: perform it through the issue-tracker capability exactly as written, then append one receipt line to `writeback/applied/<same file name>`:
   `{"id": "a001", "action": "add_labels", "bug_key": "PC-0000", "result": "ok", "tracker_ref": "<what the tracker returned>", "applied_at": "<UTC time>"}`
3. On the first failure, write a receipt line with `"result": "failed"` and the error, then stop. Do not retry a write that may already have happened; check the ticket first.
4. For `create_ticket`, check once more that no open ticket with the same summary exists. If one does, record `"result": "skipped", "tracker_ref": "<existing key>"`.

## Report

Say how many actions were applied, skipped and failed, by type, and name the receipt file. Remind the person to commit the receipt, so the ledger shows what was written and when.
