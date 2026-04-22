Run a funnel query to analyze conversion rates through a sequence of steps. Funnel insights help understand user behavior as users navigate through a product. A funnel consists of a sequence of at least two events or actions, where some users progress to the next step while others drop off. Funnels use percentages as the primary aggregation type.

Use 'read-data-schema' to discover available events, actions, and properties for filters and breakdowns.

IMPORTANT: Funnels REQUIRE AT LEAST TWO series (events or actions).

The funnel insights have the following features:

- Various visualization types (steps, time-to-convert, historical trends).
- Filter data and apply exclusion steps (events only, not actions).
- Break down data using a single property.
- Specify conversion windows (default 14 days), step order (strict/ordered/unordered), and attribution settings.
- Aggregate by users, sessions, or specific group types.
- Track first-time conversions with special math aggregations.

Examples of use cases include:

- Conversion rates between steps.
- Drop off steps (which step loses most users).
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
- Average/median/histogram of time to convert.
- Conversion trends over time (using trends visualization type).
- First-time user conversions (using first_time_for_user math).

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

# Funnel guidelines

## Exclusion steps

Users may want to use exclusion events to filter out conversions in which a particular event occurred between specific steps. These events should not be included in the main sequence. You should include start and end indexes (0-based) for each exclusion where the minimum `funnelFromStep` is 0 (first step) and the maximum `funnelToStep` is the number of steps minus one. Exclusion events cannot be actions, only events.

IMPORTANT: Exclusion steps filter out conversions where the exclusion event occurred BETWEEN the specified steps. This does NOT exclude users who completed the event before the funnel started or after it ended.

For example, there is a sequence with three steps: sign up (step 0), finish onboarding (step 1), purchase (step 2). If the user wants to exclude all conversions in which users navigated away between sign up and finishing onboarding, the exclusion step will be `$pageleave` with `funnelFromStep: 0` and `funnelToStep: 1`.

## Breakdown

A breakdown is used to segment data by a single property value. They divide all defined funnel series into multiple subseries based on the values of the property. Include a breakdown **only when it is essential to directly answer the user's question**. You should not add a breakdown if the question can be addressed without additional segmentation.

When using breakdowns, you should:

- **Identify the property group** and name for a breakdown.
- **Provide the property name** for a breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using a breakdown:

- page views to sign up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- conversion rate of users who have completed onboarding after signing up by an organization: you need to find a property such as `organization name` and set it as a breakdown.

# Examples

## Conversion from first event ingested to insight saved for organizations over 6 months

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "first team event ingested" },
    { "kind": "EventsNode", "event": "insight saved" }
  ],
  "dateRange": { "date_from": "-6m" },
  "interval": "month",
  "aggregation_group_type_index": 0,
  "funnelsFilter": {
    "funnelOrderType": "ordered",
    "funnelVizType": "trends",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day"
  },
  "filterTestAccounts": true
}
```

## Signup page CTA click rate within one hour, excluding page leaves, broken down by OS

```json
{
  "kind": "FunnelsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "properties": [{ "key": "$current_url", "type": "event", "value": "signup", "operator": "icontains" }]
    },
    {
      "kind": "EventsNode",
      "event": "click subscribe button",
      "properties": [{ "key": "$current_url", "type": "event", "value": "signup", "operator": "icontains" }]
    }
  ],
  "dateRange": { "date_from": "-180d" },
  "interval": "week",
  "funnelsFilter": {
    "funnelWindowInterval": 1,
    "funnelWindowIntervalUnit": "hour",
    "funnelOrderType": "ordered",
    "exclusions": [{ "kind": "EventsNode", "event": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1 }]
  },
  "breakdownFilter": { "breakdown_type": "event", "breakdown": "$os" },
  "filterTestAccounts": true
}
```

## Credit card purchase rate from viewing a product with strict ordering (no events in between)

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "view product" },
    {
      "kind": "EventsNode",
      "event": "purchase",
      "properties": [{ "key": "paymentMethod", "type": "event", "value": "credit_card", "operator": "exact" }]
    }
  ],
  "dateRange": { "date_from": "-30d" },
  "funnelsFilter": {
    "funnelOrderType": "strict",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day"
  },
  "filterTestAccounts": true
}
```

## View product to buy button to purchase, using actions and events

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "ActionsNode", "id": 8882, "name": "view product" },
    { "kind": "EventsNode", "event": "click buy button" },
    {
      "kind": "ActionsNode",
      "id": 573,
      "name": "purchase",
      "properties": [
        { "key": "shipping_method", "value": "express_delivery", "operator": "icontains", "type": "event" }
      ]
    }
  ],
  "funnelsFilter": { "funnelVizType": "steps" },
  "filterTestAccounts": true
}
```

# Reminders

- You MUST ALWAYS use AT LEAST TWO series (events or actions) in the funnel.
- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
- The default funnel step order is `ordered` (events in sequence but with other events allowed in between). Use `strict` when events should happen consecutively with no events in between. Use `unordered` when order doesn't matter.
- Exclusion events in funnels only exclude conversions where the event happened between the specified steps, not before or after the funnel.
