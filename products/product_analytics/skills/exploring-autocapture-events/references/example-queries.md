# Example queries for autocapture exploration

All queries filter by timestamp — adjust the interval to match your analysis window.

## Confirm autocapture exists

```sql
SELECT count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
```

## Top clicked tag names

```sql
SELECT
  arrayJoin(elements_chain_elements) as tag,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY tag
ORDER BY cnt DESC
LIMIT 20
```

## Top clicked text values

```sql
SELECT
  arrayJoin(elements_chain_texts) as text,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND length(text) > 0
GROUP BY text
ORDER BY cnt DESC
LIMIT 30
```

## Top clicked hrefs

```sql
SELECT
  elements_chain_href as href,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain_href != ''
GROUP BY href
ORDER BY cnt DESC
LIMIT 20
```

## Sample raw elements_chain for a page

Replace the URL pattern to match the page of interest.

```sql
SELECT
  elements_chain,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND properties.$current_url ILIKE '%/pricing%'
  AND elements_chain != ''
GROUP BY elements_chain
ORDER BY cnt DESC
LIMIT 10
```

## Find elements with data-attr attributes

```sql
SELECT
  arrayJoin(extractAll(elements_chain, 'data-attr="([^"]*)"')) as data_attr_value,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND match(elements_chain, 'data-attr=')
GROUP BY data_attr_value
ORDER BY cnt DESC
LIMIT 20
```

## Find all data-\* attribute keys in use

Useful for discovering which data attributes the application sets on interactive elements.

```sql
SELECT
  arrayJoin(extractAll(elements_chain, '(data-[a-zA-Z0-9_-]+)=')) as data_key,
  count() as cnt
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND match(elements_chain, 'data-')
GROUP BY data_key
ORDER BY cnt DESC
LIMIT 20
```

## Test selector uniqueness

Replace the regex pattern with one matching your candidate selector.
See [elements-chain-format.md](./elements-chain-format.md) for how selectors map to regex.

```sql
SELECT count() as matching_events
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
```

## Sample matching events to inspect captures

Verify that the selector matches only the intended interaction by inspecting what it captures.

```sql
SELECT
  elements_chain,
  properties.$current_url as url,
  elements_chain_texts as texts,
  timestamp
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
ORDER BY timestamp DESC
LIMIT 10
```

## Refine with text filter

```sql
SELECT count() as matching_events
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
  AND arrayExists(x -> x = 'Complete Purchase', elements_chain_texts)
```

## Refine with URL filter

```sql
SELECT count() as matching_events
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
  AND properties.$current_url ILIKE '%/checkout%'
```

## Ad-hoc trends: count matching clicks over time

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

## Ad-hoc trends: breakdown by page

```sql
SELECT
  properties.$current_url as url,
  count() as clicks
FROM events
WHERE event = '$autocapture'
  AND timestamp > now() - INTERVAL 7 DAY
  AND elements_chain =~ '(^|;)button.*?data-attr="checkout"'
GROUP BY url
ORDER BY clicks DESC
LIMIT 20
```

## Ad-hoc funnel: pageview to click

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

## Verify an action matches correctly

After creating an action, verify it captures the right events.

```sql
SELECT count() as matching_events
FROM events
WHERE matchesAction('Clicked checkout button')
  AND timestamp > now() - INTERVAL 7 DAY
```
