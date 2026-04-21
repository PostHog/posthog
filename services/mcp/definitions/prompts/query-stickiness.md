Run a stickiness query to measure how many intervals (e.g. days) within a date range users performed an event. Stickiness insights show user engagement intensity — the X-axis shows the number of intervals (1, 2, 3, ...) and the Y-axis shows how many users performed the event on exactly that many intervals. They're useful for understanding how deeply users engage with a feature.

Use 'read-data-schema' to discover available events, actions, and properties for filters.

Examples of use cases include:

- How many days per week do users use a feature?
- What percentage of users are power users (using the product every day)?
- How engaged are users with a specific feature over the past month?
- Compare stickiness of different features to find the most engaging one.
- Has a product change improved user engagement frequency?

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

# Data narrowing

## Property filters

Use property filters to narrow results. Only include property filters when they are essential to directly answer the user's question. Avoid adding them if the question can be addressed without additional segmentation and always use the minimum set of property filters needed.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you should:

- **Prioritize properties directly related to the context or objective of the user's query.** Avoid using properties for identification like IDs. Instead, prioritize filtering based on general properties like `paidCustomer` or `icp_score`.
- **Ensure that you find both the property group and name.** Property groups should be one of the following: event, person, session, group.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`).
- If the operator requires a value, use the `read-data-schema` tool to find the property values.
- You set logical operators to combine multiple properties of a single series: AND or OR.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group.

Supported operators for the String type are:

- equals (exact)
- doesn't equal (is_not)
- contains (icontains)
- doesn't contain (not_icontains)
- matches regex (regex)
- doesn't match regex (not_regex)
- is set
- is not set

Supported operators for the Numeric type are:

- equals (exact)
- doesn't equal (is_not)
- greater than (gt)
- less than (lt)
- is set
- is not set

Supported operators for the DateTime type are:

- equals (is_date_exact)
- doesn't equal (is_not for existence check)
- before (is_date_before)
- after (is_date_after)
- is set
- is not set

Supported operators for the Boolean type are:

- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values (as an array).

## Time period

You should not filter events by time using property filters. Instead, use the `dateRange` field. If the question doesn't mention time, use last 30 days as a default time period.

# Stickiness guidelines

Stickiness insights measure engagement intensity — how many intervals (days, weeks, etc.) within a date range each user performed an event. Unlike trends which show event counts over time, stickiness shows the distribution of user engagement frequency.

Key concepts:

- The `interval` field determines what counts as one period. With `day` interval over a 30-day range, the chart shows how many users performed the event on 1 day, 2 days, 3 days, etc., up to 30 days.
- When `math` is omitted on a series, stickiness counts unique persons by default.
- Multiple series can be included to compare stickiness of different events side by side.
- Stickiness does NOT support breakdowns.

## Aggregation

The default aggregation for stickiness is unique persons. You can change how users are identified using the `math` field on each series:

- `dau` or omit math — count unique persons (default behavior; both resolve to person_id aggregation)
- `unique_group` — count unique groups (requires `math_group_type_index` to be set to the group type index from the group mapping)
- `hogql` — custom HogQL expression (requires `math_hogql` to be set to a valid HogQL aggregation expression, e.g. `count(distinct properties.$session_id)`)

## Stickiness criteria

Use `stickinessFilter.stickinessCriteria` to filter which intervals count based on event frequency within each interval. This applies a HAVING clause to the inner aggregation.

- `operator` — one of `gte` (greater than or equal), `lte` (less than or equal), `exact` (exactly equal)
- `value` — the threshold count

For example, to only count intervals where the user performed the event at least 3 times, set `stickinessCriteria: { "operator": "gte", "value": 3 }`.

## Cumulative mode

Use `stickinessFilter.computedAs` to change how stickiness is computed:

- `non_cumulative` (default) — each bar shows users active on **exactly** N intervals
- `cumulative` — each bar shows users active on **N or more** intervals

## Time interval

Specify the time interval using the `interval` field. Available intervals are: `hour`, `day`, `week`, `month`.
Unless the user has specified otherwise, use `day` as the default interval.

Use `intervalCount` to group multiple base intervals into a single period. For example, `interval: "day"` with `intervalCount: 7` groups by 7-day periods. Defaults to 1.

## Compare

Use `compareFilter` with `compare: true` to show the current and previous period side by side.

# Examples

## How many days per week do users use pageview?

```json
{
  "kind": "StickinessQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "filterTestAccounts": true
}
```

## Compare stickiness of two features

```json
{
  "kind": "StickinessQuery",
  "series": [
    { "kind": "EventsNode", "event": "insight created" },
    { "kind": "EventsNode", "event": "dashboard viewed" }
  ],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "filterTestAccounts": true
}
```

## Weekly stickiness for paid users, compared to previous period

```json
{
  "kind": "StickinessQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }],
  "dateRange": { "date_from": "-90d" },
  "interval": "week",
  "properties": [{ "key": "paidCustomer", "operator": "exact", "type": "person", "value": ["true"] }],
  "compareFilter": { "compare": true },
  "filterTestAccounts": true
}
```

## Stickiness with criteria: only count days with 3+ events

```json
{
  "kind": "StickinessQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "filterTestAccounts": true,
  "stickinessFilter": {
    "stickinessCriteria": { "operator": "gte", "value": 3 }
  }
}
```

## Cumulative stickiness: users active on N or more days

```json
{
  "kind": "StickinessQuery",
  "series": [{ "kind": "EventsNode", "event": "feature used" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "filterTestAccounts": true,
  "stickinessFilter": {
    "computedAs": "cumulative"
  }
}
```

## Organization-level stickiness for a feature

```json
{
  "kind": "StickinessQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "feature used",
      "math": "unique_group",
      "math_group_type_index": 0
    }
  ],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "filterTestAccounts": true,
  "stickinessFilter": { "display": "ActionsBar" }
}
```

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
- Stickiness does NOT support breakdowns — do not include a `breakdownFilter`.
- When using group aggregations (unique groups), always set `math_group_type_index` to the appropriate group type index from the group mapping.
- The default interval is `day` and the default math is unique persons — omit these unless the user asks for something different.
