Run a lifecycle query to categorize users into lifecycle stages based on their activity pattern relative to a single event or action. Lifecycle insights break users into four mutually exclusive groups for each time period: new, returning, resurrecting, and dormant. They're useful for understanding the composition of your active users and diagnosing growth or churn patterns.

Use 'read-data-schema' to discover available events, actions, and properties for filters.

Examples of use cases include:

- What is the composition of my active users over time?
- Are we gaining new users faster than we're losing dormant ones?
- How many users resurrected (came back after being inactive) last week?
- Is the returning user base growing or shrinking?
- How does user engagement change after a product launch?

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

# Lifecycle guidelines

Lifecycle insights analyze a **single event or action** over time. The `series` array must contain exactly one item. If the user mentions multiple events, pick the most relevant one or clarify.

## Lifecycle statuses

Each user is categorized into one of four statuses for each time period:

- **New** – the user performed the event for the first time ever during this period.
- **Returning** – the user was active in the previous period and is active again in the current period.
- **Resurrecting** – the user was inactive for one or more periods and became active again.
- **Dormant** – the user was active in the previous period but did not perform the event in the current period. Dormant counts are shown as negative values.

## Time interval

Specify the time interval using the `interval` field. Available intervals are: `hour`, `day`, `week`, `month`. The default is `day`.

Unless the user has specified otherwise, use the following default interval:

- If the time period is less than two days, use the `hour` interval.
- If the time period is less than a month, use the `day` interval.
- If the time period is less than three months, use the `week` interval.
- Otherwise, use the `month` interval.

## Toggled lifecycles

Use `toggledLifecycles` in `lifecycleFilter` to control which lifecycle statuses are displayed. By default, all four statuses are shown. Only set this when the user wants to focus on specific statuses (e.g., only new and dormant users).

## Math aggregation

Lifecycle insights do **not** support math aggregation types. Do not set `math` on the series node.

# Examples

## Daily lifecycle of pageviews over the last 30 days

```json
{
  "kind": "LifecycleQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day"
}
```

## Weekly lifecycle of sign ups, excluding test accounts

```json
{
  "kind": "LifecycleQuery",
  "series": [{ "kind": "EventsNode", "event": "user signed up" }],
  "dateRange": { "date_from": "-90d" },
  "interval": "week",
  "filterTestAccounts": true
}
```

## Monthly lifecycle of "insight created" showing only new and dormant users

```json
{
  "kind": "LifecycleQuery",
  "series": [{ "kind": "EventsNode", "event": "insight created" }],
  "dateRange": { "date_from": "-12m" },
  "interval": "month",
  "lifecycleFilter": {
    "toggledLifecycles": ["new", "dormant"]
  },
  "filterTestAccounts": true
}
```

## Lifecycle of purchases by mobile users

```json
{
  "kind": "LifecycleQuery",
  "series": [{ "kind": "EventsNode", "event": "purchase completed" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "properties": [{ "key": "$os", "operator": "exact", "type": "event", "value": ["iOS", "Android"] }]
}
```

# Reminders

- Lifecycle insights support only **one** series — do not add multiple events or actions.
- Do not set `math` on the series node — lifecycle does not support math aggregation.
- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
