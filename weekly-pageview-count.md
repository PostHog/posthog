# Weekly pageview count

- Generated at: 2026-04-14T09:45:00.852Z
- Window: last 7 days (rolling)
- Event: `$pageview`
- Count: **4**

```sql
SELECT count() AS pageviews_last_7d
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 7 DAY
```
