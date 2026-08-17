# Self-driving features

> Status: **Draft** · Owner: Oliver Browne · Last updated: 2026-08-17

## Summary

The Features tab gives a software feature a durable home in the PostHog inbox.
The feature starts with a planning conversation, then remains active through implementation, release, monitoring, and optimization.
A feature owner scout uses PostHog as its toolbox for measuring outcomes, finding regressions, incorporating feedback, and deciding what to improve next.

The durable object is a **feature report**.
Planning is its first phase, not its identity and not its end state.

## Lifecycle

| Phase          | Primary actor                                | Result recorded on the feature report                                                                       |
| -------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Planning       | User and planning agent                      | Outcome, scope, repositories, owners, implementation increments, success criteria, and owner scout playbook |
| Implementation | Cloud implementation agent                   | Task runs, commits, pull requests, decisions, and follow-up work                                            |
| Release        | Feature owner scout                          | Derived deployment state and measurement readiness                                                          |
| Monitoring     | Feature owner scout                          | Adoption, reliability, behavioral, and qualitative evidence from PostHog                                    |
| Optimization   | Feature owner scout and implementation agent | A bounded improvement, its implementation pass, and measured result                                         |

Finishing planning activates ownership and the first implementation pass.
It does not finish the feature.

## Core model

### Feature report

A feature reuses `SignalReport` without adding feature-specific columns.
Its title and summary provide the current human-readable state.
Its artefact log is the system of record for decisions, code context, questions, owners, task runs, commits, related reports, measurements, and optimization work.

Feature reports stay outside the signal grouping pipeline.
The `signals`/`planning` task run created with the feature is the durable Features tab membership marker.
The absence of a `safety_judgment` currently means initial planning is still active; finishing planning writes the marker together with the user-created feature's actionability defaults.

### Planning agent

Creating a feature starts an interactive, repository-less task with `ai_stage="planning"`.
The agent asks which repositories matter and shallow-clones them as read-only context.
It writes all durable work to the feature report through PostHog MCP tools.

Planning must establish:

- the user problem and intended outcome;
- constraints, repositories, owners, and priority;
- bounded implementation increments;
- baseline and success criteria;
- the events, metrics, cohorts, guardrails, and qualitative signals PostHog should monitor;
- an `## Owner scout playbook` note that explains what to watch and when to act.

The user finishes planning only after the report has a title, summary, repository selection, owners, and priority.

### Feature owner scout

Finishing planning creates a deterministic `signals-scout-feature-*` skill and enables its scout config.
The platform owns the scout's core instructions.
Feature-specific steering lives in the newest owner scout playbook note.

On every activation, the owner:

1. incorporates human feedback and answered questions;
2. progresses the next implementation increment when no pass is in flight;
3. checks whether outcome and guardrail metrics are measurable;
4. queries PostHog for adoption, conversion, retention, reliability, errors, replays, experiments, or other relevant evidence;
5. records findings and starts a bounded optimization increment when the evidence supports it;
6. finds strongly related signals and links their reports with reciprocal `associated_report` artefacts;
7. updates the feature summary last so it reflects the latest state and next action.

Deployment state is derived from task runs, commits, and pull request state.
There is no separate deployed status.

## API and UI

The feature endpoints live under `/api/projects/{team_id}/signals/features/`:

- `POST /`: create the feature report and planning conversation;
- `GET /`: list feature reports, with features still in planning first;
- `POST /{report_id}/finish_planning/`: complete initial planning and activate ownership;
- `POST /{report_id}/start_implementation/`: manually start one guarded implementation pass.

The Features tab lists the long-lived feature reports.
During planning, the detail view leads with the live agent conversation and a report preview.
After planning, Status, Owner, and Feed surfaces keep implementation, feedback, measurements, and optimization work together.

## Invariants

- The feature report and its artefact log are the only durable system of record.
- Planning agents do not implement or open pull requests.
- Feature owner scouts continue after planning and release.
- Implementation passes never overlap.
- Metrics and impact claims must come from PostHog data or be labeled as unknown.
- Related signal links are advisory and never move signals or alter report lifecycle.
- Scout core behavior is platform-owned; feature-specific decisions belong in report artefacts.

## Current limitations

- Planning completion uses `safety_judgment` as its marker because the report model has no feature phase field.
- The first implementation kickoff is best effort; the owner scout retries on its next activation.
- Monitoring quality depends on the planning agent recording queryable success metrics and required instrumentation.
- Feature lifecycle state remains derived rather than represented by a dedicated state machine.
