---
name: configuring-experiment-analytics
description: Configures the analytics side of a PostHog experiment — exposure criteria (default `$feature_flag_called` vs custom exposure events), primary and secondary metrics, the supported metric types (count, sum, ratio with `math` and `math_property`, retention with `retention_window_start` and `start_handling`), multivariate user handling ("Exclude" vs "First seen variant"), and how to read results once the experiment is live. Use when the user adds or edits a primary or secondary metric (e.g. "add a secondary metric tracking 'downloaded_file' per user"), sets up a ratio metric (e.g. "revenue from purchase_completed / pageviews"), sets up a retention metric (e.g. "$pageview → uploaded_file, 7-day window"), configures custom exposure (e.g. "only count users who hit /checkout"), changes multivariate handling, or asks "who is in the analysis?", "how do I measure impact?", "is this winning?", "what's the confidence level?", or "should I ship?".
---

# Configuring experiment analytics

This skill answers: **Who is included in the analysis?** and **How to measure impact?**

## Exposure criteria

Exposure criteria determine which users are counted in the experiment analysis.

### Include people when

Two options:

1. **Feature flag called** (default) — users are included when the `$feature_flag_called` event fires for the experiment's flag. This is the standard approach — it means a user is included only when they actually encounter the feature flag in your code.
2. **Custom exposure event** — users are included when a specific custom event fires. Use this when you want tighter control over who enters the analysis (e.g., only users who actually visit the page where the experiment runs).

### Multiple variant handling

When a user is exposed to multiple variants (e.g., due to flag changes or race conditions):

- **Exclude multivariate users** — removes these users from the analysis entirely. Cleaner data, smaller sample.
- **First seen variant** — assigns users to the first variant they were exposed to. Keeps all users in the analysis. Note that "first seen" can introduce other biases as
  behavior cannot be clearly attributed to a single variant and is not recommended unless necessary.

**Bias risk on uneven splits.** "Exclude multivariate users" combined with an uneven variant split can
introduce bias — multi-variant users are dropped asymmetrically and the smaller variant loses a larger
fraction of its assignments. If those users behave differently from the rest, the smaller variant's
metrics will be skewed.

The right mitigation depends on experiment state:

- **Not yet launched, or only exposed to a few users so far** — switch to an even variant split and
  use the overall rollout percentage to limit test-variant exposure. This removes the bias and
  preserves statistical power. See `configuring-experiment-rollout`.
- **Live experiment with significant exposures** — changing the split mid-run reassigns users across
  variants, which is bad for user experience and data quality. Switch this setting to "First seen
  variant" instead — it keeps already-assigned users in their original variant (no reassignment) and
  removes the asymmetric exclusion.

### Filter test accounts

`exposure_criteria.filterTestAccounts` (default: true) — excludes internal/test users from the analysis.

## Resolving experiments

Metric changes require an experiment ID. If the user refers to an experiment by name
or description (e.g. "add metrics to the checkout test"), load the `finding-experiments`
skill to resolve it to a concrete ID before proceeding.

## Metrics

A metric reaches an experiment one of two ways, both via `experiment-update`:

- **Inline metric** — defined directly on the experiment. Sent in the `metrics` array, which
  **replaces** the entire inline list, so always get the current experiment first via `experiment-get`
  to preserve existing metrics.
- **Shared (saved) metric** — a reusable metric object that can be attached to many experiments.
  Attached by ID via `saved_metrics_ids` (this list also **replaces** the experiment's existing
  saved-metric links, so resend the full set — see Step 1).

**Prefer reusing a shared metric over duplicating it inline.** Build a new inline metric only when
no suitable shared metric already exists.

### Step 1: Check for an existing shared metric (REQUIRED — match by definition, not name)

Before building any new inline metric, you MUST check whether the project already has a shared
(saved) metric that measures the same thing, and reuse it. Duplicating a metric that already exists
as a shared metric fragments measurement and is exactly what we want to avoid.

**Reuse is decided by the metric _definition_ — the event or action plus the metric type — not the
name.** Saved metrics are named by each team's own conventions, which you cannot guess, so you must
compare on what each metric measures (its `query`), never on its title.

**Workflow:**

1. **Know what you're about to build first.** Settle the target event(s)/action(s) and metric type
   (mean / funnel / ratio / retention) before searching — see Step 2 to confirm the event exists via
   `read-data-schema`. You can only recognize a duplicate once you know the concrete event/action,
   so this check runs _after_ you've pinned down the event, not before.
2. **Search by the event, then compare each candidate's `query`.** Call `experiment-saved-metrics-list`
   with `?event=<the event you're measuring>` to find metrics that reference it — matched directly (an
   `EventsNode`) **or** via the step events of any action a metric references, so action-based metrics are
   found by the event their action fires on. Then for each returned row, inspect its **`query`** (not the
   `name`/`description`): a saved metric is a reuse match when its `query` measures the **same event or
   action with the same `metric_type`** (and compatible `math`) as the metric you'd otherwise build, even
   if its name is different.
   - **Match on the event, not the action's name.** An action-based metric is discoverable by the event
     the action fires on — pass that event, not the action's label.
   - **Do not use `search` for this.** `search` matches only the metric's own `name` / `description` / tags —
     never the underlying event or action — so it cannot find a definition match. Use `search` only when the
     user names a specific saved metric to attach (name resolution, not a definition match).
3. **If a saved metric matches the definition** — confirm the match with the user by name/description,
   then attach it instead of building a new one:
   - Call `experiment-get` to read the experiment's current `saved_metrics`.
   - Call `experiment-update` with `saved_metrics_ids` set to the full desired set — it **replaces**
     existing links, so include the already-attached ones plus the new entry. Each entry has shape
     `{ "id": <saved-metric id>, "metadata": { "type": "primary" } }` — set `type` to `"primary"` or
     `"secondary"`. `metadata` is optional and defaults to primary.
   - **Watch the id when rebuilding the set:** each item in the `saved_metrics` you just read has a
     top-level `id` (the _link_ id) AND a `saved_metric` field (the _metric_ id). `saved_metrics_ids`
     wants the **`saved_metric`** value, not the link `id` — sending the link `id` attaches the wrong
     metric or fails validation.
   - You do not need to build the inline metric — the shared metric already encodes its events.
4. **If nothing in the library measures the same event/action + type** — build an inline metric
   (Step 2+). When that inline metric is likely to be reused across experiments, offer to create it
   as a shared metric instead, via `experiment-saved-metrics-create`, then attach it as above, so the
   next experiment can reuse it.

### Step 2: Discover available events (REQUIRED before building an inline metric)

Before suggesting or building any new inline metric, you MUST call `read-data-schema` to discover
what events actually exist in the project. Do NOT skip this step. Do NOT suggest event names
based on what you think the project might track — only use events you have confirmed exist.
(Attaching an existing shared metric from Step 1 does not need this — it already encodes its events.)

This applies even when:

- The user provides event names — look them up to confirm they exist and are spelled correctly
- The user asks "what metrics do you suggest?" — look up events first, then suggest from real data
- The context makes certain events seem obvious — they may not exist or may be named differently

**Workflow:**

1. Call `read-data-schema` to get the project's events
2. Present relevant events to the user based on the experiment's hypothesis
3. User picks which events to use for metrics
4. Configure metrics with those confirmed event names

**Legitimate exception — `allow_unknown_events: true`:**
Pass this on `experiment-create` / `experiment-update` only when the user is intentionally instrumenting an event that hasn't been ingested yet (e.g. setting up the experiment before the code change ships). Confirm this with the user — never use it as a workaround for "the event lookup didn't return what I expected".

**Example:**

```text
User: "Let's add some metrics for the checkout experiment"

WRONG: "I'd suggest using purchase_completed as the primary metric..."
  (hallucinated event name — never seen the project's actual events)

RIGHT: *calls read-data-schema* → "Here are the events in your project
  related to checkout: `checkout_step_completed`, `payment_processed`,
  `order_confirmed`. Which of these represents a successful checkout?"
```

### Step 3: Choose metric type

There are four metric types. Each has `kind: "ExperimentMetric"`:

| metric_type   | When to use                                                                            | Required fields                                                                                                                |
| ------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `"mean"`      | Average of a numeric property per user (revenue, session duration, pageviews per user) | `source`                                                                                                                       |
| `"funnel"`    | Conversion rate from exposure through one or more ordered actions                      | `series` (1 or more steps)                                                                                                     |
| `"ratio"`     | Rate of one event relative to another                                                  | `numerator`, `denominator` — set `math: "sum"` + `math_property` on a side to aggregate a property; filters never aggregate    |
| `"retention"` | Do users come back after exposure?                                                     | `start_event`, `completion_event`, `retention_window_start`, `retention_window_end`, `retention_window_unit`, `start_handling` |

**Funnel metrics and the implicit exposure step**

Funnel metrics automatically prepend the experiment's exposure event as `step_0`.
So a funnel with 1 step in `series` is a valid 2-step funnel: **exposure → action**.
This is the correct choice for measuring "what percentage of exposed users did X?"

Examples:

- "What % of exposed users reached /login?" → funnel with 1 step (`$pageview` filtered to /login)
- "What % of exposed users completed checkout?" → funnel with 1 step (`checkout_completed`)
- "What % of exposed users went cart → checkout → purchase?" → funnel with 3 steps

**Mean vs funnel for the same event**

- **Mean** measures average count/value per user (e.g. "pageviews per user", "revenue per user").
- **Funnel** measures conversion rate (e.g. "% of exposed users who purchased").

Both can reference the same event — the difference is whether you care about count/magnitude (mean) or yes/no conversion (funnel).

**Retention: same vs different start/completion event**

The retention window is measured from the start event, so the events you pick decide what's measured:
The start occurrence never counts as its own completion (only a distinct later event does), so both shapes are valid:

- **Different** start and completion events → conversion-style retention ("did they reach the target action within the window?").
- **Same** event → repeat retention ("did they fire it _again_?"). `From 0` counts a repeat from the same period onward (same-day repeats included); `From ≥ 1` requires an occurrence later. Use `start_handling: "first_seen"`. When a user says "retention of `<event>`" they usually mean repeat retention.

See `references/metric-configuration.md` for the full rendered `ExperimentMetric` schema (all four metric types, with required fields per type) plus WRONG/RIGHT JSON pairs for the failure modes that come up most often (ratio with `is_set` filter instead of `math: "sum"` + `math_property`; retention without `retention_window_start` / `start_handling`). Read it before assembling a ratio or retention payload — the required fields are authoritative.

### Step 4: Primary vs secondary

- **Primary metrics** — the main success criteria for the experiment. These drive the ship/end decision.
- **Secondary metrics** — additional measurements for context. Useful for guardrail metrics (e.g., ensuring a conversion improvement doesn't increase error rates).

## Interpreting results

See `references/interpreting-results.md` for guidance on reading experiment results, statistical significance, and when to ship vs end.
