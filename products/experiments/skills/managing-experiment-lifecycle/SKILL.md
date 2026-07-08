---
name: managing-experiment-lifecycle
description: "Guides experiment state transitions: launching, pausing, resuming, ending, shipping variants, archiving, resetting, duplicating, and copying to another project. Covers preconditions, implications for variant assignment and analysis, and the decision framework for when to use each action.\nTRIGGER when: user asks to launch, pause, resume, end, ship, archive, reset, duplicate, or copy an experiment to another project.\nDO NOT TRIGGER when: user is creating an experiment (use creating-experiments), configuring rollout (use configuring-experiment-rollout), or setting up metrics (use configuring-experiment-analytics)."
---

# Managing experiment lifecycle

This skill covers experiment state transitions — what each action does, when to use it, and how it affects variant assignment and analysis.

## State diagram

```text
draft ──launch──▶ running ──end──▶ stopped ──archive──▶ archived
                    │   ▲              │
                  pause resume    ship_variant
                    │   │         (also ends if running)
                    ▼   │
                  paused (flag inactive, still "running" status)

Any non-draft state ──reset──▶ draft
```

## Actions and their implications

For each action, the two key questions:

1. **Who sees what variant?** (user perspective)
2. **Who is in my analysis?** (statistical perspective)

### Launch (`experiment-launch`)

Transitions draft → running. Activates the feature flag and sets `start_date`.

- **Preconditions**: must be in draft, flag needs ≥2 variants with "control" first
- **Pre-launch checklist**: has at least one metric? Variants correct? Flag implemented in code?
- **Variants**: users start being bucketed into variants based on the configured split
- **Analysis**: data collection begins from `start_date`

No request body needed.

### Pause (`experiment-pause`)

Deactivates the feature flag. Users fall back to the default experience (typically control).

- **Preconditions**: must be running and not already paused
- **Variants**: flag is not returned by `/decide` — no new exposure events recorded
- **Analysis**: no new data while paused, but existing data is preserved. Experiment stays "running".

No request body. Use `experiment-resume` to reactivate.

### Resume (`experiment-resume`)

Reactivates the feature flag after a pause. Users are re-bucketed deterministically into the same variants.

- **Preconditions**: must be paused
- **Variants**: same assignment as before pause — deterministic bucketing
- **Analysis**: exposure tracking resumes

No request body.

### End (`experiment-end`)

Sets `end_date` and transitions to stopped. The feature flag is **NOT modified**.

- **Preconditions**: must be running (launched, not already stopped)
- **Variants**: users continue seeing assigned variants (flag stays active)
- **Analysis**: results frozen to data up to `end_date`

Optional body: `conclusion` ("won", "lost", "inconclusive", "stopped_early", "invalid") and `conclusion_comment`.

Use this when you want to freeze results without changing what users see.

### Ship variant (`experiment-ship-variant`)

Rewrites the feature flag so the selected variant is served to 100% of users.

- **Preconditions**: must be launched (running or stopped). Cannot ship from draft.
- **Variants**: ALL users see the shipped variant. The flag is rewritten with a catch-all group.
- **Analysis**: if still running, the experiment is also ended (end_date set)

**Always confirm with the user before shipping** — this permanently rewrites the feature flag.

Required: `variant_key` (e.g. "test"). Optional: `conclusion`, `conclusion_comment`.

Returns 409 if an approval policy requires review before the flag change.

### Archive (`experiment-archive`)

Hides a stopped experiment from the default list view.

- **Preconditions**: must be stopped (end_date set)
- **Variants**: no change — flag is unaffected
- **Analysis**: no change — results remain accessible

No request body. Can be restored by setting `archived=false` via `experiment-update`.

### Reset (`experiment-reset`)

Returns an experiment to draft state. Clears `start_date`, `end_date`, `conclusion`, and `archived`.

- **Preconditions**: must not already be in draft
- **Variants**: flag is left unchanged — users continue seeing assigned variants
- **Analysis**: previously collected data still exists but won't be included in results unless `start_date` is adjusted after re-launch

No request body.

### Duplicate (`experiment-duplicate`)

Creates a copy as a new draft with fresh dates and no results.

**Important**: always provide a unique `feature_flag_key` different from the original. If the same key is used, both experiments share a flag — changes to one affect both.

Optional: custom `name` (defaults to "Original Name (Copy)").

### Copy to project (`experiment-copy-to-project`)

Copies an experiment into a **different project in the same organization** as a new draft. Use this instead of
`experiment-duplicate` when the copy should land in another project; use duplicate when it stays in the same project.

- **Preconditions**: source must not use legacy metrics; target project must be in the same organization and you must
  have write access to it. Cannot copy across organizations or regions.
- **What's copied**: name, description, type, parameters, filters, primary/secondary metrics (fresh uuids), stats and
  scheduling config, exposure criteria. **Not copied**: saved-metric references (project-scoped), holdout, exposure
  cohort, dates, results, conclusion.
- **Feature flag**: `target_team_id` is required; `feature_flag_key` is optional. The resolved key is then looked up
  **in the target project**, and the lookup result — not whether you passed the key — decides what happens:
  - **If `feature_flag_key` is omitted**: it defaults to the _source_ experiment's flag key. That key normally
    doesn't exist in the target project, so a new flag with it is created there. (The default can still collide — see
    the next point — so to be safe, pass an explicit key.)
  - **If the resolved key already exists as a flag in the target project**: the copy **shares** that existing flag
    instead of creating one. Both experiments then point at the same flag, so lifecycle ops (ship, pause) on either
    affect both. The existing flag must have ≥2 variants including one keyed `control`, otherwise the call returns 400.
  - **If the resolved key does not exist in the target project**: a new, independent flag is created with that key.
    To guarantee independence, pass a `feature_flag_key` that doesn't already exist in the target.

**Confirm the source experiment and target project by name before calling** — this writes into a project the user
isn't looking at. The returned experiment (and its id) belongs to the target project.

## Decision framework

| Situation                                          | Action                   | Tool                         |
| -------------------------------------------------- | ------------------------ | ---------------------------- |
| Draft ready, flag implemented, metrics set         | Launch                   | `experiment-launch`          |
| Clear winner, significant results                  | Ship the winning variant | `experiment-ship-variant`    |
| No significant difference after sufficient time    | End as inconclusive      | `experiment-end`             |
| Something wrong, need to stop exposure temporarily | Pause                    | `experiment-pause`           |
| Resume after pause                                 | Resume                   | `experiment-resume`          |
| Experiment ended, ready to clean up                | Archive                  | `experiment-archive`         |
| Need to start over with same config                | Reset to draft           | `experiment-reset`           |
| Want a similar experiment with a fresh start       | Duplicate                | `experiment-duplicate`       |
| Want the same experiment in a different project    | Copy to another project  | `experiment-copy-to-project` |

## Resolving experiments

All lifecycle actions require an experiment ID. If you don't have one, load the
`finding-experiments` skill to resolve the user's reference (name, description,
"latest", etc.) to a concrete ID before proceeding.

## Error handling

| Error message                           | Meaning                              |
| --------------------------------------- | ------------------------------------ |
| "Experiment has already been launched." | Can't launch a non-draft experiment  |
| "Experiment has not been launched yet." | Can't end/pause/ship a draft         |
| "Experiment has already ended."         | Can't end/pause a stopped experiment |
| "Experiment is already paused."         | Use resume instead                   |
| "Experiment is not paused."             | It's already active                  |
| "Experiment is already in draft state." | Nothing to reset                     |
| "Experiment is already archived."       | Already done                         |

When you get a 400, explain the situation to the user rather than retrying.
