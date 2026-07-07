# Pulse event contract

Every product-analytics event Pulse emits, with its properties and the dashboard panel(s) that consume it.
This is the contract the Pulse health dashboard (and the future feedback-driven tuning loop) builds against — treat property renames as breaking changes and update this file in the same PR.
The contract is maintained by hand (deliberate for 7 events): emission _shapes_ are pinned by tests (`test_feedback_api.py`, `test_activities.py`), so a property rename fails tests; keeping this file in sync is part of those PRs.
The dashboard is defined as code in `terraform/us/project-2/team-analytics-platform/pulse-health/`; its README carries the panel ↔ event table this file's "Dashboard panels" lines mirror.

All events are captured against the acting user's distinct id.
Backend request-context events go through `report_user_action` (which merges request analytics properties); the generation event goes through `ph_scoped_capture` because it fires from a Temporal worker.

## Generation

### `product_brief_generated`

Emitted from `temporal/activities.py` when a brief generation run persists its output (any terminal status).
Skipped when the brief has no creating user (no distinct id to attribute to).

| Property                     | Type       | Meaning                                                                                                                                                                           |
| ---------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `brief_id`                   | str (UUID) | The generated brief.                                                                                                                                                              |
| `status`                     | str        | Terminal status: `ready`, `quiet`, or `failed`.                                                                                                                                   |
| `trigger`                    | str        | `on_demand` or `scheduled`.                                                                                                                                                       |
| `period_days`                | int        | Days the brief covers.                                                                                                                                                            |
| `has_config`                 | bool       | Whether the brief was generated for a saved config.                                                                                                                               |
| `has_goal`                   | bool       | Whether the config has a non-blank goal (goal-conditioned run).                                                                                                                   |
| `new_opportunity_count`      | int        | Opportunities persisted by this run (post-dedup).                                                                                                                                 |
| `investigation_step_count`   | int        | Goal-investigation steps executed (0 for goal-less briefs).                                                                                                                       |
| `investigation_failed_count` | int        | Investigation steps that failed.                                                                                                                                                  |
| `emit_failed_count`          | int        | Opportunity→signals emits that failed in this run. Carried here (instead of a dedicated event) because the failures are already counted in the emit loop and only matter per run. |

Dashboard panels: Brief generation volume (`status`, `trigger`), Opportunity action rate (`new_opportunity_count`), Investigation step survival + distribution (`investigation_step_count`, `investigation_failed_count`), Signal emit failure rate (`new_opportunity_count`, `emit_failed_count`).
Future tuning loop — not yet charted: goal adoption (`has_goal`), period mix (`period_days`), `has_config` split.

## Attention

### `product_brief_viewed`

Emitted from `pulseLogic.ts` (frontend) the first time a terminal brief is shown per mount — poll ticks and re-renders don't re-fire.

| Property      | Type       | Meaning                                         |
| ------------- | ---------- | ----------------------------------------------- |
| `brief_id`    | str (UUID) | The viewed brief.                               |
| `status`      | str        | Brief status at view time (never `generating`). |
| `trigger`     | str        | `on_demand` or `scheduled`.                     |
| `period_days` | int        | Days the brief covers.                          |
| `has_config`  | bool       | Whether the brief belongs to a saved config.    |

Dashboard panels: Attention retention (person-level uniques only).
Future tuning loop — not yet charted: scheduled-brief readership (`trigger`).

## Opportunity lifecycle

### `opportunity_acted` / `opportunity_dismissed` / `opportunity_reopened`

Emitted from `api/opportunity.py` on each successful lifecycle transition.

| Property         | Type       | Meaning                                                            |
| ---------------- | ---------- | ------------------------------------------------------------------ |
| `opportunity_id` | str (UUID) | The transitioned opportunity.                                      |
| `kind`           | str        | `build`, `fix`, or `instrument`.                                   |
| `status`         | str        | The status after the transition.                                   |
| `goal_relevant`  | bool       | Whether the opportunity was marked as advancing the config's goal. |

Dashboard panels: Opportunity action rate (7d) — `opportunity_acted` + `opportunity_dismissed` event counts against generated opportunities; no properties consumed.
Future tuning loop — not yet charted: by-kind act/dismiss rates (`kind`), goal-relevant split (`goal_relevant`), reopen churn (`opportunity_reopened`).

## Helpfulness feedback

The context properties on these two events ARE the tuning signal — they let the feedback stream answer "which brief/opportunity shapes are helpful" (e.g. "fix opportunities are helpful, context sections are not") without joining back to the rows.

### `product_brief_feedback`

Emitted from `api/brief.py` on every feedback POST — votes, revotes, and clears alike.

| Property            | Type         | Meaning                                                                                  |
| ------------------- | ------------ | ---------------------------------------------------------------------------------------- |
| `brief_id`          | str (UUID)   | The voted brief.                                                                         |
| `helpful`           | bool \| null | `true` = helpful, `false` = not helpful, `null` = the user cleared their vote.           |
| `status`            | str          | Brief status at vote time.                                                               |
| `trigger`           | str          | `on_demand` or `scheduled`.                                                              |
| `has_goal`          | bool         | Whether the brief was goal-conditioned.                                                  |
| `section_kinds`     | list[str]    | Sorted unique kinds of the brief's sections (e.g. `["goal_progress", "what_happened"]`). |
| `has_investigation` | bool         | Whether the brief carries goal-investigation findings.                                   |

### `opportunity_feedback`

Emitted from `api/opportunity.py` on every feedback POST — votes, revotes, and clears alike.

| Property                  | Type         | Meaning                                                                        |
| ------------------------- | ------------ | ------------------------------------------------------------------------------ |
| `opportunity_id`          | str (UUID)   | The voted opportunity.                                                         |
| `helpful`                 | bool \| null | `true` = helpful, `false` = not helpful, `null` = the user cleared their vote. |
| `kind`                    | str          | `build`, `fix`, or `instrument`.                                               |
| `status`                  | str          | Opportunity status at vote time.                                               |
| `goal_relevant`           | bool         | Whether the opportunity was marked as advancing the config's goal.             |
| `has_proposed_experiment` | bool         | Whether goal-conditioned synthesis attached an experiment proposal.            |

Dashboard panels: Brief helpfulness (`helpful`, `has_goal`), Opportunity helpfulness (`helpful`, `kind`).
Future tuning loop — not yet charted: section-mix helpfulness (`section_kinds`), investigation split (`has_investigation`), proposed-experiment split (`has_proposed_experiment`), status splits.

Rate math: rate panels must exclude `helpful = null` (clears are engagement, not sentiment).
Event-based ratios measure vote actions, not current stance — revotes emit again; for point-in-time stance use latest-event-per-user-per-target.

## Non-events (deliberate)

- `pulse_opportunity_signal_emit_failed` is a structured **log**, not an event; its per-run count is charted via `emit_failed_count` on `product_brief_generated`.
- Votes are stored per user in the models' `feedback` JSONField but the API only ever exposes derived counts and the caller's own vote — the events likewise never carry other voters' identities.
