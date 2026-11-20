---
name: uat-stack-guidewire
description: Stack profile for Guidewire InsuranceSuite (PolicyCenter, ClaimCenter, BillingCenter, ContactManager) and Guidewire Cloud integrations (Cloud API, App Events, Integration Gateway). Use when classifying a UAT bug's app, component and layer, deciding where to look for evidence, or naming the developer-side test that would have caught it.
---

# Stack profile: Guidewire

Use this profile to fill `app`, `component` and `layer`, to choose where to look, and to phrase `proposed_test` in terms a Guidewire developer can act on. Names and folders differ between releases and between cloud and self-managed installs, so confirm every path with a search before you cite it.

## Vocabulary for `app` and `component`

Use these values so counts stay comparable across releases. Add a value only when none fits, and note it in memory.

| app | component values |
| --- | --- |
| PolicyCenter | `product-model`, `rating`, `forms`, `underwriting-rules`, `policy-transactions` (submission, change, renewal, cancellation, reinstatement, rewrite, audit), `quoting`, `pcf-ui`, `documents`, `batch` |
| ClaimCenter | `fnol`, `exposures-incidents`, `financials` (reserves, payments, recoveries), `assignment-rules`, `activities-workflow`, `coverage-verification`, `pcf-ui`, `documents`, `batch` |
| BillingCenter | `invoicing`, `payment-plans`, `billing-plans`, `delinquency`, `payments-distribution`, `disbursements`, `commissions`, `pcf-ui`, `batch` |
| ContactManager | `contact-sync`, `duplicate-check`, `contact-data`, `pcf-ui` |
| Integration | `cloud-api`, `app-events`, `integration-gateway`, `messaging` (event-fired rules, destinations, transports), `web-services`, `kafka`, `file-batch` |
| any | `entity-model`, `typelists`, `permissions-roles`, `environment-config`, `data-upgrade`, `localization` |

## `layer`

`ui`: PCF pages and Jutro front ends. `api`: Cloud API and other service endpoints. `rules`: Gosu business rules, validation, rating routines, form inference, underwriting rules. `data`: entities, typelists, product-model data. `integration`: App Events, Integration Gateway, messaging, Kafka, cross-application calls. `batch`: batch processes and work queues. `config`: environment and runtime configuration, plans. `security`: roles and permissions.

## Where evidence usually lives

Search for these; do not assume them. Read only what a specific hypothesis needs.

- Gosu classes and enhancements under a `gsrc` folder; unit tests under a `gtest` folder.
- Page configuration in `.pcf` files; rules in `.gr` and `.grs` files.
- Entities in `.eti` (new) and `.etx` (extension) files; typelists in `.tti` and `.ttx` files.
- Cloud API definitions as swagger, schema, mapping and updater files in an `integration` configuration folder.
- Messaging destinations in the messaging configuration; plugin implementations in the plugin registry.
- Integration Gateway applications outside the InsuranceSuite code, usually in their own repositories.
- Product, rating and form definitions in product-model resources and in the tools your team uses to author them.

## Why developer testing misses Guidewire defects

Check these before settling on `escape_reason`. Each one names the evidence that would confirm it.

- **Product and effective dates.** Local data covers a few products and states; UAT uses the real matrix. Look at jurisdiction, policy term dates, rate-book effective dates, backdated or out-of-sequence changes. Evidence: the policy data in the ticket against the availability, rating or form rule.
- **Stubbed neighbours.** Integrations are mocked locally and real in cloud UAT. Evidence: the payload or event that failed, against the contract on both sides.
- **Environment configuration.** Runtime properties, feature toggles, registered plugin implementations, deployed forms and templates differ between environments. Evidence: the configuration value in each environment.
- **Roles.** Developers test as an administrator; UAT users have business roles. Evidence: the tester's role and the permission the screen or action checks.
- **Batch and time.** Invoicing, delinquency and renewal run on schedules and clocks. Evidence: batch run history and the dates involved.
- **Cross-application flows.** A change tested in one application breaks a flow that crosses PolicyCenter, BillingCenter, ClaimCenter or ContactManager. Evidence: the record on both sides.
- **Existing data.** UAT holds upgraded or converted data that new code did not expect. Evidence: the age and origin of the failing record.

## Test levels in Guidewire terms

Use these when you fill `catch_level` and `proposed_test`.

| catch_level | What it means here |
| --- | --- |
| `unit` | A GUnit test: in-process, written in Gosu, with builder-based test data. |
| `api` | An API test against Cloud API, for example with the Guidewire testing framework's API testing, which is built on Karate. |
| `integration` | A test with the real neighbour or a simulator: an App Events consumer, an Integration Gateway route, a cross-application scenario. |
| `e2e-ui` | An automated UI test, for example with the Guidewire testing framework's UI testing. |
| `manual` | A manual check in a development or QA environment before UAT. |
| `uat-only` | Needs business judgment or production-like data that only UAT has. |

A good `proposed_test` names the level, the data and the assertion: "GUnit test that builds a renewal for each state in scope and asserts the renewal form is inferred."

## Integration bugs

For any bug in the `Integration` app, or with `layer: integration` or `layer: api`, also read `.claude/skills/uat-stack-generic/integration-contracts.md` and answer its questions from evidence. Two Guidewire specifics:

- Cloud API is the inbound path, where an outside system starts the flow. App Events is the outbound path, where something that happened inside InsuranceSuite is published to other systems, by webhook or through Integration Gateway. Integration Gateway hosts integration applications that bridge InsuranceSuite and systems that speak other protocols. Record which direction failed.
- App Events are published after the business transaction, through an event pipeline outside InsuranceSuite. Ask whether the consumer handles repeated delivery and whether it depends on order.

## Business language

Reports for managers describe impact as customer, financial, compliance or operational effect. Keep typecodes, PCF names, class names and rule identifiers in the ledger and out of the dashboard.
