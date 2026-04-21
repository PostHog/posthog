# Paths metrics playbook

For "the path from X to Y changed", "fewer users reach Z",
"a different dominant path emerged".

Paths metrics are _shape_ metrics: the "change" is usually a shift in how users navigate
between events, not a single scalar moving. The goal of the investigation is to identify
which edges of the path graph gained or lost volume and why.

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes.

## 1. Confirm what changed

Rerun `posthog:query-paths` with the user's paths definition and `compareFilter:
{"compare": true}` to see the current and prior periods side by side. Which specific edges
(step-to-step transitions) gained or lost volume? Which new paths appeared, which
disappeared?

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "compareFilter": { "compare": true },
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "startPoint": "/home",
    "endPoint": "/checkout",
    "edgeLimit": 50
  }
}
```

## 2. Check endpoint volume in isolation

Before assuming the path shape changed, confirm the endpoints themselves are stable. A
"drop in paths from A to B" often turns out to be a drop in **A** or **B** individually.

Run `posthog:query-trends` on the `startPoint` event and the `endPoint` event separately:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "math": "total",
      "properties": [{ "type": "event", "key": "$current_url", "value": "/home", "operator": "exact" }]
    }
  ]
}
```

If either endpoint's volume moved, the path "change" is really an endpoint change — drop
back into the Trend playbook on that endpoint event.

## 3. Reframe as a funnel if the user cares about conversion

If the user's underlying question is "what % of users who hit /home reach /checkout?" then
paths are the wrong tool — that's a funnel question. Build a funnel from the start event
to the end event and run the [funnel-playbook](./funnel-playbook.md) for step-level
decomposition (entries vs. completions, dropped-out actors, error cross-check).

Paths is the right tool only when the question is about the _shape_ of navigation between
the endpoints, not the conversion rate.

## 4. Segment with property filters

`AssistantPathsQuery` does **not** support `breakdownFilter`. Segment with `properties`
at the query level (applies to all events in the path) and rerun per segment. Use the
**breakdown dimensions** menu from shared-patterns for candidate segments to try.

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "properties": [{ "type": "event", "key": "$browser", "value": "Safari", "operator": "exact" }],
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "startPoint": "/home",
    "endPoint": "/checkout"
  }
}
```

Rerun with other segment values. A path shape that differs sharply between browsers /
countries / plans is evidence the change is segment-specific.

## 5. Session recordings for the new dominant path

Apply the **session recordings** pattern from shared-patterns. Pull recordings for users
who took the new dominant edge — watching a few usually surfaces the UI change or new
link placement that caused the shift faster than more queries.

## 6. Cross-check against errors

Apply the **error / logs cross-check** pattern. If users diverge off the expected path at
a specific page, errors on that page are a strong candidate — confirm with the three
checks (timing, plausible mechanism, user overlap) from shared-patterns.
