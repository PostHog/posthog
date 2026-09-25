Run a retention query to analyze how many users return over time after performing an initial action. Retention insights show you how many users return during subsequent periods. They're useful for understanding user engagement and stickiness.

Use 'read-data-schema' to discover available events, actions, and properties for filters.

Examples of use cases include:

- Are new sign ups coming back to use your product after trying it?
- Have recent changes improved retention?
- How many users come back and perform an action after their first visit.
- How many users come back to perform action X after performing action Y.
- How often users return to use a specific feature.

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

Send `operator` as the code below, never its label: use `"operator": "exact"`, not `"operator": "equals"`.

Supported operators for the String type are:

- `exact` - equals
- `is_not` - doesn't equal
- `icontains` - contains
- `not_icontains` - doesn't contain
- `regex` - matches regex
- `not_regex` - doesn't match regex
- `is_set` - is set
- `is_not_set` - is not set

Supported operators for the Numeric type are:

- `exact` - equals
- `is_not` - doesn't equal
- `gt` - greater than
- `lt` - less than
- `is_set` - is set
- `is_not_set` - is not set

Supported operators for the DateTime type are:

- `is_date_exact` - equals
- `is_date_before` - before
- `is_date_after` - after
- `is_set` - is set
- `is_not_set` - is not set

Supported operators for the Boolean type are:

- `exact` - equals
- `is_not` - doesn't equal
- `is_set` - is set
- `is_not_set` - is not set

`value` takes a single string, except:

- `exact` and `is_not` also take an array of strings, to match any one of several values. Every entry must be a string, so convert a number or a boolean first.
- `gt` and `lt` take a number.
- Boolean properties take the strings `"true"` and `"false"`.
- `is_set` and `is_not_set` take no value.

## Time period

You should not filter events by time using property filters. Instead, use the `dateRange` field. If the question doesn't mention time, use last 30 days as a default time period.

# Retention guidelines

Retention insights always require two entities:

- The activation event (targetEntity) – determines if the user is a part of a cohort (when they "start").
- The retention event (returningEntity) – determines whether a user has been retained (when they "return").

For activation and retention events, use the `$pageview` event by default or the equivalent for mobile apps `$screen`. Avoid infrequent or inconsistent events like `signed in` unless asked explicitly, as they skew the data.

The activation and retention events can be the same (e.g., both `$pageview` to see if users who viewed pages come back to view pages again) or different (e.g., activation is `signed up` and retention is `completed purchase` to see if sign-ups convert to purchases over time).

# Examples

## Weekly retention of users who created an insight

```json
{
  "kind": "RetentionQuery",
  "retentionFilter": {
    "period": "Week",
    "totalIntervals": 9,
    "targetEntity": { "id": "insight created", "name": "insight created", "type": "events" },
    "returningEntity": { "id": "insight created", "name": "insight created", "type": "events" },
    "retentionType": "retention_first_time",
    "retentionReference": "total",
    "cumulative": false
  },
  "filterTestAccounts": true
}
```

## Do users who sign up come back to view pages?

```json
{
  "kind": "RetentionQuery",
  "retentionFilter": {
    "period": "Week",
    "totalIntervals": 8,
    "targetEntity": { "id": "user signed up", "name": "user signed up", "type": "events" },
    "returningEntity": { "id": "$pageview", "name": "$pageview", "type": "events" },
    "retentionType": "retention_first_time",
    "retentionReference": "total",
    "cumulative": false
  },
  "dateRange": { "date_from": "-60d" },
  "filterTestAccounts": true
}
```

## Daily retention of pageviews for mobile users only

```json
{
  "kind": "RetentionQuery",
  "retentionFilter": {
    "period": "Day",
    "totalIntervals": 14,
    "targetEntity": { "id": "$pageview", "name": "$pageview", "type": "events" },
    "returningEntity": { "id": "$pageview", "name": "$pageview", "type": "events" },
    "retentionType": "retention_first_time",
    "retentionReference": "total",
    "cumulative": false
  },
  "properties": [{ "key": "$os", "operator": "exact", "type": "event", "value": ["iOS", "Android"] }],
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true
}
```

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
