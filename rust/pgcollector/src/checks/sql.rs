//! Every query the checks job runs against the stats DB.

use super::rules::{BaselinePoint, Baselines, ServerContext, Window, WindowRow};
use anyhow::{Context, Result};
use chrono::{DateTime, Duration, DurationRound, Timelike, Utc};
use deadpool_postgres::Client;

const ROLLUP_STATE_KEY: &str = "rollup_through";
/// Hours of raw data one rollup statement covers; bounds the cost of a catch-up.
const ROLLUP_CHUNK_HOURS: i64 = 6;

pub async fn try_lock(c: &Client) -> Result<bool> {
    let r = c
        .query_one(
            "SELECT pg_try_advisory_lock(hashtext('pgcollector:checks'))",
            &[],
        )
        .await?;
    Ok(r.get(0))
}

pub async fn unlock(c: &Client) -> Result<()> {
    c.execute(
        "SELECT pg_advisory_unlock(hashtext('pgcollector:checks'))",
        &[],
    )
    .await?;
    Ok(())
}

pub async fn servers(c: &Client) -> Result<Vec<String>> {
    Ok(c.query("SELECT server_id FROM cur_servers ORDER BY 1", &[])
        .await?
        .into_iter()
        .map(|r| r.get(0))
        .collect())
}

/// Roll completed hours of `ts_query_stats` into `ts_query_stats_1h` / `ts_server_stats_1h`,
/// continuing from where the last run stopped. Returns the number of hours processed.
pub async fn fill_rollup(
    c: &Client,
    now: DateTime<Utc>,
    baseline_days: u32,
    ignore_roles: &[String],
) -> Result<i64> {
    let end = now.duration_trunc(Duration::hours(1))?;
    let earliest = end - Duration::days(baseline_days as i64 + 1);
    let through: Option<DateTime<Utc>> = c
        .query_opt(
            "SELECT (value->>'through')::timestamptz FROM checks_state WHERE key = $1",
            &[&ROLLUP_STATE_KEY],
        )
        .await?
        .map(|r| r.get(0));
    let mut from = through.unwrap_or(earliest).max(earliest);
    let mut hours = 0;
    while from < end {
        let to = (from + Duration::hours(ROLLUP_CHUNK_HOURS)).min(end);
        c.execute(
            "INSERT INTO ts_query_stats_1h (server_id, datname, queryid, hour, calls, total_ms, sumsq, rows, shared_blks_read, temp_blks_written, wal_bytes, instances)
             SELECT server_id, datname, queryid, date_trunc('hour', collected_at),
                    sum(calls)::bigint, sum(total_exec_time)::float8, sum(sumsq_exec_time)::float8, sum(rows)::bigint,
                    sum(shared_blks_read)::bigint, sum(temp_blks_written)::bigint, sum(wal_bytes)::bigint, count(DISTINCT instance)::int
             FROM ts_query_stats
             WHERE collected_at >= $1 AND collected_at < $2 AND toplevel AND datname IS NOT NULL AND NOT (rolname = ANY($3))
             GROUP BY 1, 2, 3, 4
             ON CONFLICT (server_id, datname, queryid, hour) DO UPDATE SET
               calls = EXCLUDED.calls, total_ms = EXCLUDED.total_ms, sumsq = EXCLUDED.sumsq, rows = EXCLUDED.rows,
               shared_blks_read = EXCLUDED.shared_blks_read, temp_blks_written = EXCLUDED.temp_blks_written,
               wal_bytes = EXCLUDED.wal_bytes, instances = EXCLUDED.instances",
            &[&from, &to, &ignore_roles],
        )
        .await
        .context("rollup")?;
        c.execute(
            "INSERT INTO ts_server_stats_1h (server_id, hour, total_ms, calls)
             SELECT server_id, hour, sum(total_ms), sum(calls) FROM ts_query_stats_1h
             WHERE hour >= $1 AND hour < $2 GROUP BY 1, 2
             ON CONFLICT (server_id, hour) DO UPDATE SET total_ms = EXCLUDED.total_ms, calls = EXCLUDED.calls",
            &[&from, &to],
        )
        .await?;
        c.execute(
            "INSERT INTO checks_state (key, value, updated_at) VALUES ($1, jsonb_build_object('through', $2::timestamptz), now())
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            &[&ROLLUP_STATE_KEY, &to],
        )
        .await?;
        hours += (to - from).num_hours();
        from = to;
    }
    c.execute(
        "DELETE FROM ts_query_stats_1h WHERE hour < $1",
        &[&earliest],
    )
    .await?;
    c.execute(
        "DELETE FROM ts_server_stats_1h WHERE hour < $1",
        &[&earliest],
    )
    .await?;
    Ok(hours)
}

pub async fn server_context(c: &Client, server: &str) -> Result<ServerContext> {
    let first_seen: Option<DateTime<Utc>> = c
        .query_opt(
            "SELECT first_seen FROM cur_servers WHERE server_id = $1",
            &[&server],
        )
        .await?
        .map(|r| r.get(0));
    let resets: i64 = c
        .query_one(
            "SELECT count(*) FROM events WHERE server_id = $1 AND kind = 'stats_reset' AND at >= now() - interval '24 hours'",
            &[&server],
        )
        .await?
        .get(0);
    Ok(ServerContext {
        first_seen,
        stats_reset_recent: resets > 0,
    })
}

pub async fn window(
    c: &Client,
    server: &str,
    from: DateTime<Utc>,
    to: DateTime<Utc>,
    ignore_roles: &[String],
) -> Result<Window> {
    let rows = c
        .query(
            "WITH w AS (
               SELECT datname, queryid, sum(calls)::bigint AS calls, sum(total_exec_time)::float8 AS total_ms,
                      sum(rows)::bigint AS rows, sum(shared_blks_read)::bigint AS shared_blks_read,
                      sum(temp_blks_written)::bigint AS temp_blks_written,
                      array_agg(DISTINCT rolname) AS rolnames
               FROM ts_query_stats
               WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 AND toplevel
                 AND datname IS NOT NULL AND NOT (rolname = ANY($4))
               GROUP BY 1, 2),
             q AS (
               SELECT DISTINCT ON (datname, queryid) datname, queryid, query, fingerprint, first_seen
               FROM cur_queries WHERE server_id = $1 ORDER BY datname, queryid, first_seen)
             SELECT w.datname, w.queryid, w.calls, w.total_ms, w.rows, w.shared_blks_read, w.temp_blks_written, w.rolnames,
                    q.query, q.fingerprint, q.first_seen
             FROM w LEFT JOIN q USING (datname, queryid)
             WHERE w.total_ms > 0",
            &[&server, &from, &to, &ignore_roles],
        )
        .await
        .context("window")?;
    let totals = c
        .query_one(
            "SELECT coalesce(sum(total_exec_time), 0)::float8, count(DISTINCT collected_at)::bigint
             FROM ts_query_stats WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 AND toplevel",
            &[&server, &from, &to],
        )
        .await?;
    Ok(Window {
        rows: rows
            .iter()
            .map(|r| WindowRow {
                datname: r.get(0),
                queryid: r.get(1),
                calls: r.get(2),
                total_ms: r.get(3),
                rows: r.get(4),
                shared_blks_read: r.get(5),
                temp_blks_written: r.get(6),
                rolnames: r
                    .get::<_, Option<Vec<Option<String>>>>(7)
                    .unwrap_or_default()
                    .into_iter()
                    .flatten()
                    .collect(),
                query: r.get(8),
                fingerprint: r.get(9),
                first_seen: r.get(10),
            })
            .collect(),
        server_total_ms: totals.get(0),
        samples: totals.get(1),
        from,
        to,
    })
}

/// Same hour-of-day as `at` on each of the previous `days` days, per (datname, queryid).
pub async fn baselines(
    c: &Client,
    server: &str,
    queryids: &[i64],
    at: DateTime<Utc>,
    days: u32,
) -> Result<Baselines> {
    let mut out = Baselines::new();
    if queryids.is_empty() {
        return Ok(out);
    }
    let hour = at.duration_trunc(Duration::hours(1))?;
    let from = hour - Duration::days(days as i64);
    let rows = c
        .query(
            "SELECT s.datname, s.queryid, s.calls, s.total_ms, t.total_ms
             FROM ts_query_stats_1h s JOIN ts_server_stats_1h t USING (server_id, hour)
             WHERE s.server_id = $1 AND s.queryid = ANY($2) AND s.hour >= $3 AND s.hour < $4
               AND extract(hour FROM s.hour AT TIME ZONE 'UTC') = $5 AND s.calls > 0",
            &[&server, &queryids, &from, &hour, &(hour.hour() as f64)],
        )
        .await
        .context("baselines")?;
    for r in rows {
        let (datname, queryid, calls, total_ms, server_ms): (String, i64, i64, f64, f64) =
            (r.get(0), r.get(1), r.get(2), r.get(3), r.get(4));
        out.entry((datname, queryid))
            .or_default()
            .push(BaselinePoint {
                mean_ms: total_ms / calls as f64,
                share_pct: if server_ms > 0.0 {
                    total_ms / server_ms * 100.0
                } else {
                    0.0
                },
            });
    }
    Ok(out)
}
