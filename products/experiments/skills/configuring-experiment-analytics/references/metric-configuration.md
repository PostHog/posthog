# Metric configuration examples

All metrics use `kind: "ExperimentMetric"`. Legacy kinds (`ExperimentTrendsQuery`, `ExperimentFunnelsQuery`) are rejected.

## Mean metric

Average of a numeric property per user. Use for revenue, session duration, page views per user, etc.

```json
{
  "kind": "ExperimentMetric",
  "metric_type": "mean",
  "name": "Average revenue per user",
  "source": {
    "kind": "EventsNode",
    "event": "purchase_completed"
  }
}
```

## Funnel metric

Conversion rate from exposure through one or more ordered actions. The experiment's exposure event is automatically prepended as `step_0`, so even a single entry in `series` creates a valid 2-step funnel (exposure → action).

### Single-step funnel (exposure → action)

```json
{
  "kind": "ExperimentMetric",
  "metric_type": "funnel",
  "name": "Reached checkout",
  "series": [{ "kind": "EventsNode", "event": "checkout_started" }]
}
```

Measures "% of exposed users who reached checkout".

### Multi-step funnel (exposure → action 1 → action 2 → ...)

```json
{
  "kind": "ExperimentMetric",
  "metric_type": "funnel",
  "name": "Checkout conversion",
  "series": [
    { "kind": "EventsNode", "event": "add_to_cart" },
    { "kind": "EventsNode", "event": "checkout_started" },
    { "kind": "EventsNode", "event": "purchase_completed" }
  ]
}
```

Step order matters — users must complete steps in sequence.

## Ratio metric

Rate of one event relative to another. Use for click-through rates, error rates, engagement ratios.

```json
{
  "kind": "ExperimentMetric",
  "metric_type": "ratio",
  "name": "Click-through rate",
  "numerator": {
    "kind": "EventsNode",
    "event": "button_clicked"
  },
  "denominator": {
    "kind": "EventsNode",
    "event": "$pageview"
  }
}
```

## Retention metric

Whether users return after initial exposure. Use for measuring long-term engagement.

```json
{
  "kind": "ExperimentMetric",
  "metric_type": "retention",
  "name": "7-day retention",
  "start_event": {
    "kind": "EventsNode",
    "event": "$feature_flag_called"
  },
  "completion_event": {
    "kind": "EventsNode",
    "event": "$pageview"
  },
  "retention_window_start": 0,
  "retention_window_end": 7,
  "retention_window_unit": "day"
}
```

## Adding metrics to an experiment

Call `experiment-update` with the full `metrics` array. This **replaces** the entire list.

To add a metric without losing existing ones:

1. Call `experiment-get` to get current metrics
2. Append the new metric to the existing array
3. Call `experiment-update` with the combined array

## Property filters

Any EventsNode can include property filters to narrow which events count:

```json
{
  "kind": "EventsNode",
  "event": "purchase_completed",
  "properties": [
    {
      "key": "plan",
      "value": ["pro", "enterprise"],
      "operator": "exact",
      "type": "event"
    }
  ]
}
```
