# Pulse event contract

Every product-analytics event Pulse emits, with its properties and the dashboard panel(s) that consume it.
This is the contract the Pulse dashboard (and the future feedback-driven tuning loop) builds against — treat property renames as breaking changes and update this file in the same PR.

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

Dashboard panels: generation volume/status mix, scheduled-vs-on-demand split, goal adoption, opportunity yield, investigation health, signals-emit failure rate.

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

Dashboard panels: brief attention (views per generated brief), scheduled-brief readership.

## Opportunity lifecycle

### `opportunity_acted` / `opportunity_dismissed` / `opportunity_reopened`

Emitted from `api/opportunity.py` on each successful lifecycle transition.

| Property         | Type       | Meaning                                                            |
| ---------------- | ---------- | ------------------------------------------------------------------ |
| `opportunity_id` | str (UUID) | The transitioned opportunity.                                      |
| `kind`           | str        | `build`, `fix`, or `instrument`.                                   |
| `status`         | str        | The status after the transition.                                   |
| `goal_relevant`  | bool       | Whether the opportunity was marked as advancing the config's goal. |

Dashboard panels: act/dismiss rates by kind, goal-relevant vs not, reopen churn.

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

Dashboard panels: helpfulness rate by brief shape (goal vs not, section mix) and by opportunity kind; feedback volume as an engagement proxy.

## Non-events (deliberate)

- `pulse_opportunity_signal_emit_failed` is a structured **log**, not an event; its per-run count is charted via `emit_failed_count` on `product_brief_generated`.
- Votes are stored per user in the models' `feedback` JSONField but the API only ever exposes derived counts and the caller's own vote — the events likewise never carry other voters' identities.
