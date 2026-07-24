Run a trends query to analyze metrics over time. Trends insights visualize events over time using time series. They're useful for finding patterns in historical data.

Use 'read-data-schema' to discover available events, actions, and properties for filters and breakdowns.

The trends insights have the following features:

- The insight can show multiple trends in one request.
- Custom formulas can calculate derived metrics, like `A/B*100` to calculate a ratio.
- Filter and break down data using multiple properties.
- Compare with the previous period and sample data.
- Apply various aggregation types, like sum, average, etc., and chart types.

Examples of use cases include:

- How the product's most important metrics change over time.
- Long-term patterns, or cycles in product's usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- Users can also visualize the same data points in a variety of ways.

CRITICAL: Be minimalist. Only include filters, breakdowns, and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

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

# Trends guidelines

Trends insights enable users to plot data from people, events, and properties however they want. They're useful for finding patterns in data, as well as monitoring product usage. Users can use multiple independent series in a single query to see trends. They can also use a formula to calculate a metric. Each series has its own set of property filters. Trends insights do not require breakdowns or filters by default.

## Aggregation

Determine the math aggregation the user is asking for, such as totals, averages, ratios, or custom formulas. If not specified, choose a reasonable default based on the event type (e.g., total count). By default, the total count should be used. You can aggregate data by events, event's property values, groups, or users. If you're aggregating by users or groups, there's no need to check for their existence.

Available math aggregation types for the event count are:

- total count
- average
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile
- unique users
- unique sessions
- weekly active users
- daily active users
- first time for a user
- unique groups (requires `math_group_type_index` to be set to the group type index from the group mapping)

Available math aggregation types for event's property values are:

- average
- sum
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile

Available math aggregation types counting number of events completed per user (intensity of usage) are:

- average
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile

Examples of using aggregation types:

- `unique users` to find how many distinct users have logged the event per a day.
- `average` by the `$session_duration` property to find out what was the average session duration of an event.
- `99th percentile by users` to find out what was the 99th percentile of the event count by users.

## Combining multiple events into a single series (`GroupNode`)

**Use a `GroupNode`** when the user says "X OR Y" (or "any of these events") and wants **one line / one number** as the result. Different filters per event are fine — put them on the inner nodes. Use separate top-level series instead when the user wants the events compared side by side. Only `OR` is supported.

**Where things live:**

- On the group: `math` / `math_property` / `math_property_type` / `math_multiplier` / `math_group_type_index` / `math_hogql`, plus `name`. The engine reads aggregation from here.
- On each inner node: `event` (or action `id`), `properties`, `name` — all respected normally; `properties` applies only to that node. Mirror the group's `math*` values on each inner node for UI round-trip, but they're ignored at execution time.

### Example — different filter per event

"Pageviews on Safari OR pageleaves on Chrome, as one line." Each inner node carries its own `properties`; the group ORs them and aggregates as one series.

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "GroupNode",
      "operator": "OR",
      "name": "Pageviews on Safari, Pageleaves on Chrome",
      "math": "total",
      "nodes": [
        {
          "kind": "EventsNode",
          "event": "$pageview",
          "name": "Pageview",
          "math": "total",
          "properties": [{ "key": "$browser", "operator": "exact", "type": "event", "value": ["Safari"] }]
        },
        {
          "kind": "EventsNode",
          "event": "$pageleave",
          "name": "Pageleave",
          "math": "total",
          "properties": [{ "key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"] }]
        }
      ]
    }
  ],
  "dateRange": { "date_from": "-30d" },
  "interval": "day"
}
```

## Math formulas

If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical operations like calculating percentages or metrics. If you use a formula, you should use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas.

When using a formula, you should:

- Identify and specify **all** events and actions needed to solve the formula.
- Carefully review the list of available events and actions to find appropriate entities for each part of the formula.
- Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations.

Examples of using math formulas:

- If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B * 100`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).
- To calculate conversion rate: `A / B * 100` where A is conversions and B is total events.
- To calculate average value: `A / B` where A is sum of property and B is count.

## Time interval

Specify the time interval (group by time) using the `interval` field. Available intervals are: `hour`, `day`, `week`, `month`.
Unless the user has specified otherwise, use the following default interval:

- If the time period is less than two days, use the `hour` interval.
- If the time period is less than a month, use the `day` interval.
- If the time period is less than three months, use the `week` interval.
- Otherwise, use the `month` interval.

## Breakdowns

Breakdowns are used to segment data by property values of maximum three properties. They divide all defined trends series into multiple subseries based on the values of the property. Include breakdowns **only when they are essential to directly answer the user's question**. You should not add breakdowns if the question can be addressed without additional segmentation. Always use the minimum set of breakdowns needed.

When using breakdowns, you should:

- **Identify the property group** and name for each breakdown.
- **Provide the property name** for each breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using breakdowns:

- page views trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- number of users who have completed onboarding by an organization: you need to find a property such as `organization name` and set it as a breakdown.

# Examples

## How many users signed up?

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "user signed up", "math": "total" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "month",
  "trendsFilter": { "display": "BoldNumber" }
}
```

## Page views by referring domain for the last month

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "breakdownFilter": {
    "breakdowns": [{ "property": "$referring_domain", "type": "event" }]
  }
}
```

## DAU to MAU ratio for users from the US, compared to the previous period

```json
{
  "kind": "TrendsQuery",
  "series": [
    { "kind": "EventsNode", "event": "$pageview", "math": "dau" },
    { "kind": "EventsNode", "event": "$pageview", "math": "monthly_active" }
  ],
  "dateRange": { "date_from": "-7d" },
  "interval": "day",
  "properties": {
    "type": "AND",
    "values": [
      {
        "type": "AND",
        "values": [{ "key": "$geoip_country_name", "operator": "exact", "type": "event", "value": ["United States"] }]
      }
    ]
  },
  "compareFilter": { "compare": true },
  "trendsFilter": { "display": "ActionsLineGraph", "formula": "A/B", "aggregationAxisFormat": "percentage_scaled" }
}
```

## Unique users and first-time users for "insight created" over the last 12 months

```json
{
  "kind": "TrendsQuery",
  "series": [
    { "kind": "EventsNode", "event": "insight created", "math": "dau" },
    { "kind": "EventsNode", "event": "insight created", "math": "first_time_for_user" }
  ],
  "dateRange": { "date_from": "-12m" },
  "interval": "month",
  "filterTestAccounts": true,
  "trendsFilter": { "display": "ActionsLineGraph" }
}
```

## P99, P95, and median of a "refreshAge" property on "viewed dashboard" events

```json
{
  "kind": "TrendsQuery",
  "series": [
    { "kind": "EventsNode", "event": "viewed dashboard", "math": "p99", "math_property": "refreshAge" },
    { "kind": "EventsNode", "event": "viewed dashboard", "math": "p95", "math_property": "refreshAge" },
    { "kind": "EventsNode", "event": "viewed dashboard", "math": "median", "math_property": "refreshAge" }
  ],
  "dateRange": { "date_from": "yStart" },
  "interval": "month",
  "filterTestAccounts": true,
  "trendsFilter": { "display": "ActionsLineGraph", "aggregationAxisFormat": "duration" }
}
```

## Organizations that signed up from Google in the last 30 days (group aggregation)

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "user signed up",
      "math": "unique_group",
      "math_group_type_index": 0,
      "properties": [{ "key": "is_organization_first_user", "operator": "exact", "type": "person", "value": ["true"] }]
    }
  ],
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "properties": {
    "type": "AND",
    "values": [
      {
        "type": "OR",
        "values": [{ "key": "$initial_utm_source", "operator": "exact", "type": "person", "value": ["google"] }]
      }
    ]
  },
  "trendsFilter": { "display": "ActionsLineGraph" }
}
```

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
- When using group aggregations (unique groups), always set `math_group_type_index` to the appropriate group type index from the group mapping.
- Visualization settings (display type, axis format, etc.) should only be specified when explicitly requested or when they significantly improve the answer.
