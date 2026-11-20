---
name: uat-stack-REPLACE
description: Stack profile for REPLACE (name the product and its main parts in words people use). Use when classifying a UAT bug's app, component and layer, deciding where to look for evidence, or naming the developer-side test that would have caught it.
---

# Stack profile: REPLACE

One paragraph: what this stack is, and anything that makes its paths or names vary between teams.

## Vocabulary for `app` and `component`

| app | component values |
| --- | --- |
| REPLACE | `replace`, `replace` |

Two levels only. Use the names the team already uses.

## `layer`

Say what each of `ui`, `api`, `rules`, `data`, `integration`, `batch`, `config`, `security` means on this stack. Leave out layers that do not exist.

## Where evidence usually lives

File kinds and folders to search. Tell the reader to confirm each path before citing it.

## Why developer testing misses defects on this stack

Three to seven patterns. For each: what differs between a developer's setup and UAT, and the evidence that confirms it.

## Test levels on this stack

| catch_level | What it means here |
| --- | --- |
| `unit` | REPLACE |
| `api` | REPLACE |
| `integration` | REPLACE |
| `e2e-ui` | REPLACE |
| `manual` | REPLACE |
| `uat-only` | REPLACE |

End with one example of a good `proposed_test` for this stack.
