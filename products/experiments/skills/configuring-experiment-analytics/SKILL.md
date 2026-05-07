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

Metrics are added via `experiment-update` after creation. The `metrics` array **replaces** the entire list, so always get the current experiment first via `experiment-get` to preserve existing metrics.

### Step 1: Discover available events (REQUIRED — always do this first)

Before suggesting or configuring ANY metric, you MUST call `read-data-schema` to discover
what events actually exist in the project. Do NOT skip this step. Do NOT suggest event names
based on what you think the project might track — only use events you have confirmed exist.

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

### Step 2: Choose metric type

There are four metric types. Each has `kind: "ExperimentMetric"`:

| metric_type   | When to use                                                                            | Key fields                                         |
| ------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `"mean"`      | Average of a numeric property per user (revenue, session duration, pageviews per user) | `source` EventsNode                                |
| `"funnel"`    | Conversion rate from exposure through one or more ordered actions                      | `series` array of EventsNode steps (**1 or more**) |
| `"ratio"`     | Rate of one event relative to another                                                  | `numerator`, `denominator` EventsNode              |
| `"retention"` | Do users come back after exposure?                                                     | `start_event`, `completion_event`, window config   |

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

See `references/metric-configuration.md` for detailed JSON examples of each type.

### Step 3: Primary vs secondary

- **Primary metrics** — the main success criteria for the experiment. These drive the ship/end decision.
- **Secondary metrics** — additional measurements for context. Useful for guardrail metrics (e.g., ensuring a conversion improvement doesn't increase error rates).

## Interpreting results

See `references/interpreting-results.md` for guidance on reading experiment results, statistical significance, and when to ship vs end.
