# Paths metrics playbook

For "the path from X to Y changed", "a different dominant path emerged". Paths are
shape metrics — the change is usually a shift in navigation between events, not a
single scalar moving.

## 1. What changed

`PathsQuery` doesn't support `compareFilter`. Run `posthog:query-paths` twice with
date ranges of equal length and compare which edges gained or lost volume.

```json
posthog:query-paths
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-7d" },
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "startPoint": "/home",
    "endPoint": "/checkout",
    "edgeLimit": 50
  }
}
```

Then rerun with `"dateRange": { "date_from": "-14d", "date_to": "-7d" }`.

## 2. Endpoint volume

A "drop in paths A → B" is often a drop in A or B alone. Run `posthog:query-trends` on
each endpoint event separately. If either moved, drop into the trend playbook on that
event instead.

## 3. Wrong tool?

If the user's actual question is conversion rate, paths is the wrong tool — build a
funnel and run the [funnel-playbook](./funnel-playbook.md). Paths is for shape, not
conversion.

## 4. Segment

`AssistantPathsQuery` doesn't support `breakdownFilter`. Filter via top-level
`properties` and rerun per segment. A path shape that differs sharply across
browsers / countries / plans is evidence the change is segment-specific.

## 5. Recordings + errors

Pull session recordings for users on the new dominant edge — usually surfaces the UI
change faster than more queries. Cross-check `error-tracking-issues-list` for errors on
the page where users diverge.
