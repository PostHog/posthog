Run a paths query to analyze the most common sequences of events or pages that users navigate through. Paths insights visualize user flows as a directed graph, showing how users move between steps and where they drop off.

Use 'read-data-schema' to discover available events, actions, and properties for filters.

Examples of use cases include:

- What do users do after signing up?
- What pages do users visit before making a purchase?
- What are the most common navigation flows on your website?
- Where do users drop off in a particular flow?
- What custom events lead to a conversion?

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

# Paths guidelines

## Event types

Paths analyze sequences of events. Specify which event types to include using `includeEventTypes`. If omitted, all events are included without type filtering.

- `$pageview` - web page views. Path values come from `$current_url`, with trailing slashes stripped, so they must match your stored URL format. This is often a path like `/login`, but may also be a full URL like `https://example.com/login`. Best for analyzing website navigation flows. This is the most common choice.
- `$screen` - mobile screen views. Path values are screen names (from `$screen_name`). Use for mobile app navigation analysis.
- `custom_event` - custom events (any event whose name does not start with `$`). Path values are event names. Use for analyzing flows of custom-tracked events like button clicks, form submissions, or feature usage.
- `hogql` - custom HogQL expression. Use with `pathsHogQLExpression` for advanced path definitions.

You can combine multiple types. For example, include both `$pageview` and `custom_event` to see how page views and custom events interleave.

## Start and end points

Use `startPoint` to filter paths that begin at a specific step, or `endPoint` to filter paths that end at a specific step. The value format depends on the event type:

- For `$pageview`: use the same URL format as your `$current_url` values, often paths like `/login`, `/dashboard`, `/settings`, but sometimes full URLs
- For `$screen`: use screen names
- For `custom_event`: use event names like `user signed up`, `purchase completed`

## Path cleaning

Use `localPathCleaningFilters` to normalize dynamic URLs. Each filter has a `regex` pattern (ClickHouse regex syntax) and an `alias` replacement. Filters are applied in sequence using `replaceRegexpAll(path, regex, alias)`. For example, to normalize product URLs: `{ "regex": "\\/product\\/\\d+", "alias": "/product/:id" }`.

Use `pathGroupings` for simpler glob-like grouping of paths into single nodes. Use `*` as a wildcard — the patterns are auto-escaped so only `*` has special meaning. For example, `/product/*` groups all product sub-pages into one node.

## Exclusions

Use `excludeEvents` to remove specific path items that clutter the visualization. The values must match path item values, not event types: for `$pageview` paths these must match your stored `$current_url` format (e.g., `/health-check` or `https://example.com/health-check`), for `custom_event` paths these are event names (e.g., `heartbeat`). To control which event types are included, use `includeEventTypes` instead.

# Examples

## What pages do users visit after the homepage?

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "startPoint": "/",
    "stepLimit": 5
  },
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true
}
```

## What do users do after signing up?

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["custom_event"],
    "startPoint": "user signed up",
    "stepLimit": 5
  },
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true
}
```

## Navigation paths excluding noisy URLs

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "excludeEvents": ["/health-check", "/ping"],
    "stepLimit": 5,
    "edgeLimit": 30
  },
  "dateRange": { "date_from": "-14d" },
  "filterTestAccounts": true
}
```

## Custom event paths excluding noisy events

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["custom_event"],
    "excludeEvents": ["heartbeat"],
    "stepLimit": 5
  },
  "dateRange": { "date_from": "-14d" },
  "filterTestAccounts": true
}
```

## Paths with URL cleaning for dynamic segments

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "stepLimit": 5,
    "localPathCleaningFilters": [
      { "regex": "\\/user\\/\\d+", "alias": "/user/:id" },
      { "regex": "\\/project\\/[a-f0-9-]+", "alias": "/project/:id" }
    ]
  },
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true
}
```

## What paths lead to the pricing page for mobile users?

```json
{
  "kind": "PathsQuery",
  "pathsFilter": {
    "includeEventTypes": ["$pageview"],
    "endPoint": "/pricing",
    "stepLimit": 5
  },
  "properties": [{ "key": "$os", "operator": "exact", "type": "event", "value": ["iOS", "Android"] }],
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true
}
```

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
- Always specify `includeEventTypes` to scope the analysis to relevant event types. If omitted, all events are included which may produce noisy results.
- Use `$pageview` as the default event type for web navigation questions.
- Path cleaning filters (`localPathCleaningFilters`) use ClickHouse regex and are only needed when dynamic URL segments would fragment the visualization. Path groupings (`pathGroupings`) use glob-like patterns with `*` wildcards for simpler cases.
- Paths group events into sessions with a 30-minute inactivity threshold — events more than 30 minutes apart start a new path session.
