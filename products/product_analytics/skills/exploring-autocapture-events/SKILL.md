---
name: exploring-autocapture-events
description: >
  Guides exploration of $autocapture events captured by posthog-js to understand user interactions,
  find CSS selectors (especially data-attr attributes), evaluate selector uniqueness, query matching
  clicks ad-hoc, and create actions. Use when the user asks about autocapture data, wants to find
  what users are clicking, needs to build actions from click events, asks about elements_chain,
  wants to build a trend or funnel filtered by clicks or other autocapture interactions, asks which
  properties autocapture sends, or asks how to filter $autocapture events. Only applies to projects
  using posthog-js autocapture.
---

# Exploring autocapture events

if users opt in then posthog-js automatically captures clicks, form submissions, and page changes as `$autocapture` events.
Each event records the clicked DOM element and its ancestors in the `elements_chain` column.

`$autocapture` is intentionally excluded from the `posthog:read-data-schema` taxonomy
because it is only useful with autocapture-specific filters (selector, tag, text, href).
This skill fills that gap.

## Materialized columns

The `events` table provides fast access to common element fields without parsing the full chain string.

| Column                    | Type          | Description                                                                                            |
| ------------------------- | ------------- | ------------------------------------------------------------------------------------------------------ |
| `elements_chain`          | String        | Full semicolon-separated element chain (see [format reference](./references/elements-chain-format.md)) |
| `elements_chain_href`     | String        | Last href value from the chain                                                                         |
| `elements_chain_texts`    | Array(String) | All text values from elements                                                                          |
| `elements_chain_ids`      | Array(String) | All id attribute values                                                                                |
| `elements_chain_elements` | Array(String) | Useful tag names: a, button, input, select, textarea, label                                            |

Use materialized columns for exploration queries whenever possible — they avoid regex parsing.

## Canonical autocapture properties

Every `$autocapture` event from posthog-js ships with a fixed set of properties.
Do not query the schema to "look them up" — they are these:

| Property          | Examples                          | Notes                                                       |
| ----------------- | --------------------------------- | ----------------------------------------------------------- |
| `$event_type`     | `click`, `submit`, `change`       | the kind of interaction                                     |
| `$el_text`        | `Sign up`, `Submit`               | text of the clicked element                                 |
| `$current_url`    | `https://app.example.com/pricing` | page the interaction happened on                            |
| `$elements_chain` | semicolon-separated chain         | parsed via the `elements_chain*` materialized columns above |

Standard event properties (`$browser`, `$os`, `$device_type`, etc.) are also present.

## Workflow

### 1. Confirm autocapture data exists

Run a count query before doing anything else.
If the count is zero, autocapture may be disabled. There are two ways this happens:

- **Project settings** — the team can set `autocapture_opt_out` in PostHog project settings
- **SDK config** — the posthog-js `init()` call can pass `autocapture: false`

Tell the user if no data is found so they can check both settings.

```sql
SELECT count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
```

### 2. Explore what users are interacting with

Start broad using the materialized columns.
The goal is to understand what users are clicking before narrowing down.

Useful explorations:

- Top clicked tag names (via `elements_chain_elements`)
- Top clicked text values (via `elements_chain_texts`)
- Top clicked hrefs (via `elements_chain_href`)
- Raw `elements_chain` values for a specific page (filtered by `properties.$current_url`)

See [example queries](./references/example-queries.md) for all patterns.

### 3. Find candidate selectors

Once the user identifies an interaction they care about, find a CSS selector that identifies it.

Priority order for selector attributes (best first):

1. **`data-attr` or other `data-*` attributes** — highest specificity, stable across deploys, developer-intended anchors.
   Search with `match(elements_chain, 'data-attr=')` or `extractAll`.
2. **Element ID** (`attr_id`) — also highly stable, queryable via `elements_chain_ids`.
3. **Tag + class combination** — moderately stable but classes change with CSS refactors.
4. **Text content** — fragile (changes with copy edits, i18n) but sometimes the only option.
5. **Tag name alone** — too broad on its own, useful as a qualifier.

When a `data-attr` value is found, construct a selector like `[data-attr="value"]` or `button[data-attr="value"]`.

### 4. Evaluate selector uniqueness

A selector is only useful if it matches the intended interaction and not unrelated events.

Run a uniqueness check using `elements_chain =~` with the regex pattern for the selector.
Then sample matching events to inspect what the selector actually captures.
Compare the count against total autocapture volume to understand selectivity.

A good selector matches a single logical interaction.
If it matches too many distinct elements, refine it in the next step.

### 5. Refine with additional filters

If the selector alone is not unique enough, layer on additional filters:

- **Text filter** — match by element text content using `elements_chain_texts`
- **URL filter** — restrict to a specific page using `properties.$current_url`
- **Href filter** — match by link target using `elements_chain_href`

Re-run the uniqueness check after each refinement.
Only include filters that are needed — fewer filters means more resilience to minor DOM changes.

### 6. Filter autocapture inside an insight query

When the user wants a funnel, trend, or other insight, the filter shape is different from HogQL.
Each step in a `FunnelsQuery` / `TrendsQuery` is an `EventsNode` (or `ActionsNode`) with `event: "$autocapture"` and a `properties` array.

Two distinct property `type` values matter — they are not interchangeable:

- **`type: "element"`** — keys: `selector`, `tag_name`, `text`, `href`. Matched against the parsed `elements_chain`. Operator support is split:
  - `selector` and `tag_name` only support `exact` and `is_not` — anything else raises `NotImplementedError` in the query compiler (`posthog/hogql/property.py`).
  - `text` and `href` accept the full string operator set (`exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`, `is_set`, `is_not_set`).
- **`type: "event"`** — keys: any of the canonical autocapture properties (`$event_type`, `$el_text`, `$current_url`) or anything else on the event. Standard event-property operators (`exact`, `icontains`, `regex`, etc.).

Example funnel from clicking one button to clicking another:

```json
{
  "kind": "FunnelsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$autocapture",
      "properties": [
        {
          "type": "element",
          "key": "selector",
          "value": ["[data-attr=\"autocapture-series-save-as-action-banner-shown\"]"],
          "operator": "exact"
        }
      ]
    },
    {
      "kind": "EventsNode",
      "event": "$autocapture",
      "properties": [
        {
          "type": "element",
          "key": "selector",
          "value": ["[data-attr=\"autocapture-save-as-action\"]"],
          "operator": "exact"
        }
      ]
    }
  ]
}
```

Two things easy to get wrong:

- `value` is an array even when matching a single selector
- The selector string includes the `[data-attr="..."]` wrapper — it is a CSS selector, not a bare attribute value

Decision rule: prefer an action (`ActionsNode` referencing an existing action — see Step 8) when the interaction will be referenced more than once; inline `type: "element"` / `type: "event"` filters when it's a one-off insight; raw HogQL (Step 7) when joining across events or doing custom aggregations.

### 7. Use in ad-hoc queries

The discovered selector can be used directly in HogQL without creating an action.

**Trends** — count matching clicks over time:

```sql
SELECT
  toStartOfDay(timestamp) as day,
  count() as clicks
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 14 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
GROUP BY day
ORDER BY day
```

**Funnel** — pageview to click conversion:

```sql
SELECT
  person_id,
  first_pageview,
  first_click_after
FROM (
  SELECT
    p.person_id,
    p.pageview_time as first_pageview,
    min(c.click_time) as first_click_after
  FROM (
    SELECT person_id, min(timestamp) as pageview_time
    FROM events
    WHERE event = '$pageview'
      AND timestamp > now() - INTERVAL 14 DAY
      AND properties.$current_url ILIKE '%/pricing%'
    GROUP BY person_id
  ) p
  INNER JOIN (
    SELECT person_id, timestamp as click_time
    FROM events
    WHERE event = '$autocapture'
      AND timestamp > now() - INTERVAL 14 DAY
      AND elements_chain =~ '(^|;)button.*?data-attr="signup"'
  ) c ON p.person_id = c.person_id AND c.click_time > p.pageview_time
  GROUP BY p.person_id, p.pageview_time
)
```

For recurring analysis, prefer creating an action (next step) or using `posthog:query-trends` / `posthog:query-funnel` with the action.

### 8. Create an action

Actions are the durable version of ad-hoc selector queries.
Once the criteria uniquely identify the interaction, create an action using `posthog:action-create`.

Construct the step with only the filters needed for uniqueness:

```json
{
  "name": "Clicked checkout button",
  "steps": [
    {
      "event": "$autocapture",
      "selector": "button[data-attr='checkout']",
      "text": "Complete Purchase",
      "text_matching": "exact",
      "url": "/checkout",
      "url_matching": "contains"
    }
  ]
}
```

Available step fields for `$autocapture`:

- `selector` — CSS selector (e.g. `button[data-attr='checkout']`)
- `tag_name` — HTML tag name (e.g. `button`, `a`, `input`)
- `text` / `text_matching` — element text (`exact`, `contains`, or `regex`)
- `href` / `href_matching` — link href (`exact`, `contains`, or `regex`)
- `url` / `url_matching` — page URL (`exact`, `contains`, or `regex`)

After creation, verify with `matchesAction()`:

```sql
SELECT count() as matching_events
FROM events
WHERE matchesAction('Clicked checkout button')
  AND timestamp > now() - INTERVAL 7 DAY
```

## Tips

- Always set timestamp filters — `$autocapture` is high volume
- Use `LIMIT` generously when sampling `elements_chain` — the strings can be long
- The `elements_chain =~` operator matches CSS selectors as regex internally;
  prefer materialized columns when possible for performance
- This workflow only applies to posthog-js — other SDKs do not capture elements
