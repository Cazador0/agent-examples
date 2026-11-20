---
name: uat-stack-generic
description: Stack profile for any full-stack application that has no dedicated profile, and the template for writing a new one. Use when classifying a UAT bug's app, component and layer on an unfamiliar stack, when an integration, API, JSON or Kafka bug needs the contract checklist, or when asked to add a stack profile.
---

# Stack profile: any application

Use this when the profile in `config/uat-profile.yaml` names no stack, or names one that has no `uat-stack-<name>` skill.

## Build the component map from the repository

Do this once per application and save the result to memory as a method note, so later runs reuse it.

1. Find the deployable units: build files, package manifests, container and deployment descriptors. Each unit is an `app`.
2. Inside each, find the top-level modules or bounded areas. Each is a `component`. Use the names the team already uses in folders and in Jira components.
3. Record where each kind of evidence lives: API specifications, schema migrations, messaging and topic configuration, environment configuration, test folders by level.

Stop at two levels. A map with fifty components produces counts of one, and counts of one show no pattern.

## `layer`

| layer | Typical contents |
| --- | --- |
| `ui` | Screens, components, client-side validation, navigation |
| `api` | Endpoints, request and response contracts, gateways |
| `rules` | Business logic, validation, calculation, workflow decisions |
| `data` | Schema, migrations, reference data, persistence mapping |
| `integration` | Events, queues, topics, calls to other systems, files exchanged |
| `batch` | Scheduled jobs, long-running processes |
| `config` | Environment settings, feature flags, deployment configuration |
| `security` | Authentication, roles, permissions, data exposure |

## Why developer testing misses defects

The usual reasons, with the evidence that confirms each: the test data did not include the case (compare the failing record with fixtures); the environment differs (compare configuration values); the neighbouring system was mocked (compare the mock with the real payload); the acceptance criteria were read differently (quote the criterion and both readings); the path had no test (search the test folders); a test existed and did not run (read the pipeline history).

## Test levels

`unit`: one function or class, no running services. `api`: one running service through its interface. `integration`: two or more real or simulated systems. `e2e-ui`: a user flow through the interface. `manual`: a person checks before UAT. `uat-only`: needs business judgment or production-like data.

## Integration, API, JSON and Kafka bugs

Read `integration-contracts.md` in this folder and answer its questions from evidence before you choose a category.

## Adding a stack profile

Copy `profile-template.md` in this folder to `.claude/skills/uat-stack-<name>/SKILL.md`, fill it in, and add `<name>` to `stack_profiles` in `config/uat-profile.yaml`. Keep it under about 120 lines: vocabulary, where evidence lives, why local testing misses defects on this stack, and what each test level means there.
