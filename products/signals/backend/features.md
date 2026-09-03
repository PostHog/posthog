# Self-driving features

> Status: **Draft** · Owner: Oliver Browne · Last updated: 2026-09-03

## Summary

The Features tab gives a software feature a durable home in the PostHog inbox.
The feature starts as a staged discovery or a planning conversation, then remains active through implementation, release, monitoring, and optimization.
A feature owner scout uses PostHog as its toolbox for measuring outcomes, finding regressions, incorporating feedback, and deciding what to improve next.

The durable object is a **feature report**.
Planning is its first phase, not its identity and not its end state.
Its summary is a living overview of the feature, including its intended functionality, current status, implementation boundaries, in-flight work, health, and next step.
It is not structured like a reactive finding or incident report.

## Lifecycle

| Phase          | Primary actor                                | Result recorded on the feature report                                                                                        |
| -------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Discovery      | Repository discovery agent                   | A staged feature report grounded in code, owners, measurement ideas, and feature boundaries                                  |
| Planning       | User and planning agent                      | Intended functionality, current status, scope, owners, implementation increments, success criteria, and owner scout playbook |
| Implementation | Cloud implementation agent                   | Task runs, commits, pull requests, decisions, and follow-up work                                                             |
| Release        | Feature owner scout                          | Derived deployment state and measurement readiness                                                                           |
| Monitoring     | Feature owner scout                          | Adoption, reliability, behavioral, and qualitative evidence from PostHog                                                     |
| Optimization   | Feature owner scout and implementation agent | A bounded improvement, its implementation pass, and measured result                                                          |

Finishing planning activates ownership and the first implementation pass.
It does not finish the feature.

## Core model

### Feature report

A feature reuses `SignalReport` without adding feature-specific columns.
Its title names the feature, and its summary provides the current human-readable overview rather than a one-time outcome or recommendation.
Its artefact log is the system of record for decisions, code context, questions, owners, task runs, commits, related reports, measurements, and optimization work.

Feature reports stay outside the signal grouping pipeline.
The latest `feature_lifecycle` artefact records whether the feature is `staged`, `planning`, or `managed`, and whether it came from a person or repository discovery.
Older feature reports without that artefact still derive membership and phase from their `signals`/`planning` task run and safety judgment.

### Repository discovery agent

Starting discovery creates a team-scoped `FeatureDiscoveryRun` and a Temporal workflow.
The workflow provisions the same trusted, full-clone sandbox used by report research and keeps one agent session alive across all turns.

The agent:

1. explores the primary repository and builds a codebase-level product map;
2. checks repository-host metadata and remote branches for relevant work that is not on the default branch;
3. shallow-clones a related repository only when an in-scope feature cannot be understood without it;
4. emits one structured feature document with a living overview, current status, user journey, implementation boundaries, in-flight work, measurement and health, and next steps;
5. decides whether another distinct feature remains in scope;
6. repeats the document and continuation turns until no feature remains or the safety cap is reached.

Discovery separates features by user goal, lifecycle, success measures, and ownership needs rather than by source-tree layout.
Shared files do not collapse distinct workflows into one feature, while internal mechanisms do not become standalone features merely because they have separate modules.
An in-flight-work section states which available repository-host and version-control sources were checked when no relevant work is found.

The agent records every uncertainty about intended functionality as an open question instead of guessing.
Each agent-authored question includes two to five concise, mutually exclusive suggested answers.
Those questions become task-attributed `question` artefacts on the staged feature so a human can select an answer or write a custom one before dependent implementation work begins.

An optional focus from the user is a hard scope constraint throughout exploration and continuation.
The workflow persists no feature reports until every turn succeeds.
It then creates all reports in one transaction, marks them `staged`, and links them to the discovery task.
Activity retries see a completed run and return without creating duplicates.
Each run persists its current state and a user-safe error message.
Failures also retain bounded diagnostic details on the run without exposing them through the feature API.
The main discovery activity records failures directly, and the workflow cleanup activity provides a second attempt after retries are exhausted.

### Planning agent

Creating a feature from the list modal starts an interactive, repository-less task with `ai_stage="planning"` and opens its Planning tab.
The Planning tab can start a fresh session for any feature without changing its lifecycle.
A discovered feature stays discovered until the user finishes planning, while a managed feature keeps its existing owner.
The agent verifies discovery against the current code, checks related repositories when needed, and asks the user what future they intend for the feature instead of treating current behavior as approved intent.
For a manually created feature, the agent asks which repositories matter and shallow-clones them as read-only context.
It writes all durable work to the feature report through PostHog MCP tools.

Planning must establish:

- the user problem and intended functionality;
- constraints, repositories, owners, and priority;
- bounded implementation increments;
- baseline and success criteria;
- the events, metrics, cohorts, guardrails, and qualitative signals PostHog should monitor;
- an `## Owner scout playbook` note that explains what to watch and when to act.

The planning agent reads outstanding questions before proposing work.
It creates a `question` artefact whenever intended functionality is uncertain, supplies concise suggested answers, asks the user in the live conversation, and updates the same artefact when answered.
The user finishes planning only after the report has a title, summary, repository selection, owners, and priority, and every question affecting the first implementation increment is resolved.

### Feature owner scout

Finishing planning creates a deterministic `signals-scout-feature-*` skill and enables its scout config.
The platform owns the scout's core instructions.
Feature-specific steering lives in the newest owner scout playbook note.

On every activation, the owner:

1. reads every question, incorporates human feedback and answers, and asks rather than guessing when intended behavior remains unclear;
2. progresses the next implementation increment only when its relevant questions are answered and no pass is in flight;
3. checks whether outcome and guardrail metrics are measurable;
4. queries PostHog for adoption, conversion, retention, reliability, errors, replays, experiments, or other relevant evidence;
5. records findings and starts a bounded optimization increment when the evidence supports it;
6. finds strongly related signals and links their reports with reciprocal `associated_report` artefacts;
7. updates the feature summary last so it reflects the latest state and next action.

Every implementation agent performs the same question check before writing code.
If intended behavior is unresolved, it records a question and the blocked work instead of opening a speculative pull request.

Deployment state is derived from task runs, commits, and pull request state.
There is no separate deployed status.

## API and UI

The feature endpoints live under `/api/projects/{team_id}/signals/features/`:

- `POST /`: create the feature report and planning conversation;
- `GET /`: list feature reports, with staged features first;
- `POST /discover/`: start guided repository discovery;
- `GET /discovery_runs/`: list recent discovery runs and their progress;
- `POST /{report_id}/start_planning/`: start a fresh planning session without changing feature lifecycle;
- `POST /{report_id}/finish_planning/`: complete initial planning and activate ownership;
- `POST /{report_id}/start_implementation/`: manually start one guarded implementation pass.

The Features tab lists discovered reports separately from planning and managed features.
The discovery modal selects a connected GitHub repository and accepts an optional scope instruction.
Every feature detail view has Status, Planning, Owner, and Feed tabs for code context, implementation, feedback, measurements, and optimization work.
Opening the Planning tab never starts a task. Its controls start, restart, or add a planning session explicitly.
The list's New feature modal is the exception: it starts the first session and opens the new report on the Planning tab.
After a planning run finishes, sending another message starts an interactive continuation that retains the planning context and cannot open a pull request.
Finishing initial planning promotes a discovered or new feature, activates its owner scout, and attempts the first implementation pass.

## Invariants

- The feature report and its artefact log are the only durable system of record.
- Discovery publishes staged reports only after the complete multi-turn run succeeds.
- A discovery retry never creates the same staged report twice.
- Planning agents do not implement or open pull requests.
- Agents ask a question whenever intended functionality is uncertain instead of choosing an assumption.
- Agent-authored questions offer two to five suggested answers, and the user can always provide a custom answer.
- Implementation work does not begin while a relevant agent question is unanswered.
- Feature owner scouts continue after planning and release.
- Implementation passes never overlap.
- Metrics and impact claims must come from PostHog data or be labeled as unknown.
- Related signal links are advisory and never move signals or alter report lifecycle.
- Scout core behavior is platform-owned; feature-specific decisions belong in report artefacts.

## Current limitations

- The first implementation kickoff is best effort; the owner scout retries on its next activation.
- Monitoring quality depends on the planning agent recording queryable success metrics and required instrumentation.
- Discovery can inspect related repositories only when the connected GitHub installation can read them.
- One discovery run stages at most 30 features.
