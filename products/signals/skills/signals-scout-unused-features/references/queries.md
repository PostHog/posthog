# Unused features: query shapes

HogQL for `execute-sql`.
Replace the placeholders before you run a query:

- `{attr}`: one of the project's `data_attributes` (from `project-get`), for example `data-attr`.
- `{days}`: the window. Start with 7.
- `{host_filter}`: `AND properties.$host = '<host>'` when the project tracks several sites and the audit covers one, else nothing.
- `{internal_filter}`: the project's test account filters written as a condition, for example `AND (person.properties.email NOT ILIKE '%@example.com' OR person.properties.email IS NULL)`.
- `{min_viewers}`: the reach floor for a page in the window, about 200 a week.

Run the reach query first and look at the shape before you run the use query.
On a busy project, keep `{days}` at 7 and narrow `{host_filter}`; a timeout on the element extraction is a sign to cut the window, not to drop the reach join.

## Normalization

The same expressions appear in every query below.

```sql
-- element value: emails, UUIDs, framework ids, then digit runs become *
replaceRegexpAll(replaceRegexpAll(replaceRegexpAll(replaceRegexpAll(
  value, '[^\\s@/]+@[^\\s@/]+', '*'),
  '[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}', '*'),
  ':r[0-9a-z]+:', '*'),
  '[0-9]+', '*')

-- route: UUIDs and numeric path segments become *
replaceRegexpAll(replaceRegexpAll(properties.$pathname,
  '[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}', '*'),
  '/[0-9]+', '/*')
```

Apply the project's own `path_cleaning_filters` to the route as well when it has them; they know its id shapes better than the generic rules.

## Page reach

```sql
SELECT <route expr> AS route, uniq(distinct_id) AS viewers
FROM events
WHERE event = '$pageview'
  AND timestamp > now() - INTERVAL {days} DAY
  {host_filter} {internal_filter}
GROUP BY route
ORDER BY viewers DESC
LIMIT 200
```

## Use share per element

Each element is measured against its busiest route (`home_route`).
`routes <= 3` keeps navigation and other global controls out of the bottom of the list, since one page's reach is the wrong denominator for them.
A prefix with more than 20 distinct values in the window is treated as a templated family and collapsed to `prefix-*`.

```sql
WITH raw AS (
  SELECT <element expr on a> AS item, <route expr> AS route, distinct_id, timestamp
  FROM (
    SELECT arrayJoin(arrayDistinct(extractAll(elements_chain, 'attr__{attr}="([^"]+)"'))) AS a,
           properties.$pathname, distinct_id, timestamp
    FROM events
    WHERE event = '$autocapture'
      AND properties.$event_type = 'click'
      AND timestamp > now() - INTERVAL {days} DAY
      {host_filter} {internal_filter}
  )
),
fam AS (
  SELECT arrayStringConcat(arraySlice(splitByChar('-', item), 1, 2), '-') AS prefix, uniq(item) AS variants
  FROM raw GROUP BY prefix
),
items AS (
  SELECT if(fam.variants > 20, concat(fam.prefix, '-*'), raw.item) AS item, raw.route AS route, raw.distinct_id AS distinct_id, raw.timestamp AS timestamp
  FROM raw JOIN fam ON arrayStringConcat(arraySlice(splitByChar('-', raw.item), 1, 2), '-') = fam.prefix
),
per AS (
  SELECT item, uniq(distinct_id) AS clickers, topK(1)(route)[1] AS home_route, uniq(route) AS routes, min(timestamp) AS first_seen
  FROM items GROUP BY item
),
views AS (<page reach query without ORDER BY / LIMIT>)
SELECT per.item, per.clickers, per.routes, per.home_route, per.first_seen, views.viewers,
       round(per.clickers / views.viewers, 5) AS use_share
FROM per JOIN views ON per.home_route = views.route
WHERE views.viewers >= {min_viewers} AND per.routes <= 3
ORDER BY use_share ASC
LIMIT 50
```

Read the bottom of the list with the families in mind: a suffix that still looks like an id or a name after collapsing is customer content, so report the family and never the suffix.

## Element text fallback

For a project that tags no elements, `elements_chain_texts` holds the visible text of the clicked element and its ancestors.
The first entry is often empty (an icon button), so take the first non-empty one and apply the same normalization and family rules.

```sql
arrayFirst(t -> t != '', elements_chain_texts) AS a
```

## Flag check for one candidate

Compare the flags active for the people who clicked the item against the flags active for the people who viewed its page.
A flag that most clickers have and few viewers have means the item is behind that flag.

```sql
SELECT flag, uniq(distinct_id) AS people
FROM events
ARRAY JOIN JSONExtract(properties, '$active_feature_flags', 'Array(String)') AS flag
WHERE event = '$pageview'
  AND <route expr> = '<home_route>'
  AND timestamp > now() - INTERVAL {days} DAY
  {host_filter} {internal_filter}
GROUP BY flag
ORDER BY people DESC
LIMIT 30
```

Run it once for the page's viewers and once restricted to the item's clickers (`AND distinct_id IN (<clickers subquery>)`), then compare the shares.

## Faded check

Run the use share query for an earlier window of the same length (`timestamp BETWEEN now() - INTERVAL {2 x days} DAY AND now() - INTERVAL {days} DAY`) and compare per item.
An item whose share fell to under a third, on a page whose reach held, has faded.
