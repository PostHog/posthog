# Vetted queries — SEO scout

## Naming

`{gsc}` is the Search Console table prefix you resolved in query 0. Use the dotted name exactly as query 0 returned it — a source created with a prefix resolves as `sourcetype.prefix.table`, so `{gsc}` is not always a single segment.

`{primary}` is the table you are rolling up: `{gsc}.search_analytics_by_query_page` normally, or `{gsc}.search_analytics_by_page` when that narrower table is armed (cheaper, and it escapes the query × page sampling cap). Only `search_analytics_by_query_page` is armed by default, so write every page-grain query to work against it.

Rolling `query_page` up to page grain needs an **impression-weighted** position, not a plain average — a page ranks differently per query, and averaging the rows equally overweights the long tail:

```sql
sum(position * impressions) / nullif(sum(impressions), 0) AS pos
```

Against `search_analytics_by_page` there is one row per page per day, so a plain `avg(position)` is correct there.

## Windows

Resolve `latest = max(date)` once in query 0 and **substitute the literal date into every later query**. Do not repeat `(SELECT max(date) ...)` as a correlated subquery — it re-scans the table each time it appears.

- `recent` = `[latest - 27, latest]`
- `prior` = `[latest - 55, latest - 28]`

Anchor on `latest`, never `now()`. Not because the recent days are incomplete — the importer already ends its window three days back, so `max(date)` is a complete day — but because it keeps every lane on one clock. That is also why query 3 takes `latest` rather than using `now()`.

## 0. What is armed, and is it usable?

Run this first, every run — a team can arm a schema at any time.

```sql
SELECT table_name, table_schema
FROM system.information_schema.tables
WHERE table_name LIKE '%search_analytics%'
```

Two things to filter before you pick a table:

- **Search type suffixes.** Non-web search types get their own tables (`search_analytics_by_page_news`, `..._image`, `..._video`). Keep the bare names — those are web search. Reading a `_news` table as "the page grain" produces confidently wrong findings.
- **More than one property.** Two connected sources return two sets of tables. Pick one property per run and record the choice in `pattern:seo:source`.

Then resolve the anchor and the guards in one pass over the table you picked:

```sql
SELECT max(date) AS latest,
       min(date) AS first_date,
       today() - max(date) AS days_behind,
       max(date) - min(date) AS span_days
FROM {primary}
```

Walk the ladder: no table → close out. `days_behind` over about 5 → the sync is frozen, `noise:seo:stale-sync`, close out. `span_days` under 56 → the prior window is not fully covered and every page will read as a large loss, so close out naming the backfill. Page grain but no query grain → do not file.

### Sampling caveat

`search_analytics_by_query_page` hits Google's ~50K row/day API cap fastest, and above the cap the tail is dropped silently by clicks. On a large property a dropped tail looks exactly like clicks lost. When daily row counts sit near 50K, treat the disappearance of low-click queries as possible sampling rather than ranking loss, and prefer `search_analytics_by_page` for the page grain where it is armed.

## Content scoping

Read `pattern:seo:source` first; run this only when the key is absent or you are extending it.

Derive the site's own sections rather than carrying a list between projects:

```sql
SELECT splitByChar('/', page)[4] AS top_level_path,
       count(DISTINCT page) AS pages,
       sum(clicks) AS clicks
FROM {primary}
WHERE date >= {latest:Date} - 27
GROUP BY top_level_path
ORDER BY clicks DESC
LIMIT 30
```

Keep the sections holding evergreen content the team ranks for. Drop the sections a team publishes for itself rather than to rank, one-off campaign sections, and asset URLs (`page NOT LIKE '%.png'` and friends). What counts as internal differs per site, so read the paths rather than assuming a taxonomy. Record the result and extend it through `noise:seo:` memory.

## 1. Rank the declines (candidates and the volume floor in one scan)

One pass over the 56-day span. Conditional aggregation replaces the two-CTE self-join, which matters twice: it halves the scan, and a join would silently drop pages that vanished from the recent window entirely — the worst declines of all.

The floor is the 90th percentile page by prior clicks, computed over the same scan rather than in a separate query, so a small property is not permanently below the bar.

```sql
WITH per_page AS (
  SELECT page,
         sumIf(clicks, date >= {latest:Date} - 27) AS recent_clicks,
         sumIf(clicks, date <= {latest:Date} - 28) AS prior_clicks,
         sumIf(position * impressions, date >= {latest:Date} - 27)
           / nullif(sumIf(impressions, date >= {latest:Date} - 27), 0) AS recent_pos,
         sumIf(position * impressions, date <= {latest:Date} - 28)
           / nullif(sumIf(impressions, date <= {latest:Date} - 28), 0) AS prior_pos
  FROM {primary}
  WHERE date >= {latest:Date} - 55
    -- + your derived content scoping, applied to `page`
  GROUP BY page),
floor AS (
  SELECT greatest(20, round(quantile(0.90)(prior_clicks))) AS floor_clicks
  FROM per_page WHERE prior_clicks > 0)
SELECT page,
       prior_clicks, recent_clicks,
       prior_clicks - recent_clicks AS clicks_lost,
       round(1 - recent_clicks / prior_clicks, 2) AS clicks_lost_pct,
       round(prior_pos, 1) AS prior_pos, round(recent_pos, 1) AS recent_pos,
       round(recent_pos - prior_pos, 1) AS pos_worsened
FROM per_page, floor
WHERE prior_clicks >= floor.floor_clicks          -- the page mattered before
  AND (1 - recent_clicks / prior_clicks) >= 0.30  -- at least 30% of clicks lost
  AND (recent_pos - prior_pos) >= 1.5             -- rank actually slipped
  AND prior_pos <= 20                             -- a slide only costs clicks near the top
ORDER BY (prior_clicks - recent_clicks) * (recent_pos - prior_pos) DESC
LIMIT 30
```

A page going 20 → 13 clicks over eight weeks clears both relative bars on noise alone. Before spending a lane on a low-volume survivor, sanity-check that the loss is larger than the spread you would expect at that click count.

## 2. Branded vs non-branded lost queries

Batch every surviving candidate into one query rather than firing this per page. Non-branded is the signal; branded slippage at position ~1 is demand.

The per-query floor is derived from each page's own volume — a fixed floor here would undo the derived page floor in query 1, because on a small property no single query clears it and the branded split could never be made.

```sql
WITH per_query AS (
  SELECT page, query,
         sumIf(clicks, date >= {latest:Date} - 27) AS recent_clicks,
         sumIf(clicks, date <= {latest:Date} - 28) AS prior_clicks,
         sumIf(position * impressions, date >= {latest:Date} - 27)
           / nullif(sumIf(impressions, date >= {latest:Date} - 27), 0) AS recent_pos,
         sumIf(position * impressions, date <= {latest:Date} - 28)
           / nullif(sumIf(impressions, date <= {latest:Date} - 28), 0) AS prior_pos
  FROM {gsc}.search_analytics_by_query_page
  WHERE date >= {latest:Date} - 55
    AND page IN {pages:Array(String)}
  GROUP BY page, query)
SELECT page, query,
       NOT multiSearchAnyCaseInsensitive(query, {brand_tokens:Array(String)}) AS non_branded,
       prior_clicks, recent_clicks,
       round(prior_pos, 1) AS prior_pos, round(recent_pos, 1) AS recent_pos
FROM per_query
WHERE prior_clicks >= greatest(3, 0.10 * (SELECT max(prior_clicks) FROM per_query AS p WHERE p.page = per_query.page))
ORDER BY page, non_branded DESC, (prior_clicks - recent_clicks) DESC
```

### Confirming brand tokens

Generate candidates from the registrable domain and the project or organization name, with spacing and hyphen variants. Use the data only to confirm or reject each candidate — never to generate tokens from position, which misclassifies a generic term the site genuinely owns:

```sql
SELECT query, sum(clicks) AS clicks,
       round(sum(position * impressions) / nullif(sum(impressions), 0), 1) AS pos
FROM {gsc}.search_analytics_by_query_page
WHERE date >= {latest:Date} - 27
  AND multiSearchAnyCaseInsensitive(query, {candidate_tokens:Array(String)})
GROUP BY query
ORDER BY clicks DESC
LIMIT 30
```

Cache the confirmed set in `pattern:seo:source` and skip this query on later runs.

## 3. Corroborate with real organic landings

Confirm the drop shows in real traffic and the page still has volume. Windowed on `latest`, so it covers the same period the warehouse queries measured. Confirm the property names with `read-data-schema` first — `$host`, `$pathname`, and `$referring_domain` are standard but vary per project.

`{hosts}` is the host set that actually joined; a domain property covers subdomains and the project may record `www.` where Search Console does not. Match search referrers by domain shape rather than one literal host, since organic traffic arrives from many country domains. Widen the pattern when the team cares about other search engines.

```sql
SELECT properties.$pathname AS path,
       countIf(toDate(timestamp) > {latest:Date} - 28) AS recent_landings,
       countIf(toDate(timestamp) <= {latest:Date} - 28) AS prior_landings
FROM events
WHERE event = '$pageview'
  AND toDate(timestamp) > {latest:Date} - 56
  AND toDate(timestamp) <= {latest:Date}
  AND properties.$host IN {hosts:Array(String)}
  AND properties.$pathname IN {paths:Array(String)}
  AND match(properties.$referring_domain, '(^|\\.)google\\.')
GROUP BY path
```

When the project captures no `$pageview` for these hosts at all, say so and lower the confidence rather than dropping the check.

A page whose clicks collapsed to near zero **and** whose `recent_landings` is zero is most likely gone or broken rather than outranked. That is the broken-URL case — file it directly instead of sending it to competitor research.

## 4. Site-wide sanity, and seasonality

Catch the case where the whole property fell together — a search engine update or a tracking gap — before blaming one page. Use `search_analytics_by_date` when armed; otherwise aggregate the primary table over the same windows.

```sql
SELECT sumIf(clicks, date >= {latest:Date} - 27) AS recent_clicks,
       sumIf(clicks, date <= {latest:Date} - 28) AS prior_clicks,
       round(1 - sumIf(clicks, date >= {latest:Date} - 27)
               / nullif(sumIf(clicks, date <= {latest:Date} - 28), 0), 2) AS site_clicks_lost_pct
FROM {gsc}.search_analytics_by_date
WHERE date >= {latest:Date} - 55
```

When `site_clicks_lost_pct` is close to the page's own loss, the page is not the story — record `noise:seo:site-wide-{date}` and do not file per-page.

For seasonality, re-run query 1's aggregation one year earlier **scoped to the surviving candidates** (`page IN {pages}`), not site-wide. Only worth it when `span_days` from query 0 exceeds 365. A dip that repeats annually is seasonal.
