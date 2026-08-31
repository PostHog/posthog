//! The data layer: every question the REST API and the MCP tools can answer, as
//! functions over the stats DB returning JSON. Keep SQL here so both surfaces stay
//! in lock-step and the API layer is thin.

use crate::db::Db;
use anyhow::Result;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

type Ts = DateTime<Utc>;

/// Query a table that may not exist yet (created on first data by the collector).
async fn opt(
    db: &Db,
    sql: &str,
    params: &[&(dyn tokio_postgres::types::ToSql + Sync)],
) -> Result<Vec<Value>> {
    match db.query(sql, params).await {
        Ok(v) => Ok(v),
        Err(e)
            if format!("{e:#}").contains("42P01")
                || format!("{e:#}").contains("does not exist") =>
        {
            Ok(vec![])
        }
        Err(e) => Err(e),
    }
}

pub async fn servers(db: &Db) -> Result<Value> {
    let rows = db.query(
        "SELECT s.server_id, s.version, s.version_num, s.aurora_version, s.instances, s.databases, s.first_seen, s.last_seen,
                (SELECT max(started_at) FROM collector_runs r WHERE r.server_id = s.server_id) AS last_collected_at,
                (SELECT count(*) FROM collector_runs r WHERE r.server_id = s.server_id AND r.started_at > now() - interval '10 minutes' AND r.error IS NOT NULL)::bigint AS errors_10m
         FROM cur_servers s ORDER BY s.server_id", &[]).await?;
    Ok(json!(rows))
}

pub async fn overview(db: &Db, server: &str, from: Ts, to: Ts) -> Result<Value> {
    let dbs = opt(db, "SELECT datname, instance,
                sum(xact_commit)::bigint AS xact_commit, sum(xact_rollback)::bigint AS xact_rollback,
                sum(blks_hit)::bigint AS blks_hit, sum(blks_read)::bigint AS blks_read,
                CASE WHEN sum(blks_hit + blks_read) > 0 THEN round((sum(blks_hit)::numeric / sum(blks_hit + blks_read)) * 100, 2)::float8 END AS cache_hit_pct,
                sum(tup_inserted)::bigint AS tup_inserted, sum(tup_updated)::bigint AS tup_updated, sum(tup_deleted)::bigint AS tup_deleted,
                sum(deadlocks)::bigint AS deadlocks, sum(temp_files)::bigint AS temp_files, sum(temp_bytes)::bigint AS temp_bytes,
                max(xid_age)::bigint AS xid_age, max(numbackends)::bigint AS max_backends
         FROM ts_database_stats WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3
         GROUP BY 1, 2 ORDER BY 1, 2", &[&server, &from, &to]).await?;
    let conns = opt(db, "SELECT instance, state, sum(backends)::bigint AS backends
         FROM ts_activity_samples WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_activity_samples WHERE server_id = $1 AND collected_at >= $2)
         GROUP BY 1, 2 ORDER BY 1, 2", &[&server, &from]).await?;
    let waits = opt(db, "SELECT wait_event_type, wait_event, sum(backends)::bigint AS samples
         FROM ts_activity_samples WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 AND state = 'active'
         GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15", &[&server, &from, &to]).await?;
    let events = opt(db, "SELECT kind, count(*)::bigint AS n FROM events WHERE server_id = $1 AND at >= $2 AND at < $3 GROUP BY 1 ORDER BY 2 DESC", &[&server, &from, &to]).await?;
    let top = top_queries(db, server, from, to, None, "total_exec_time", 5).await?;
    let vac = opt(db, "SELECT datname, relname, round(vacuum_ratio::numeric, 2)::float8 AS vacuum_ratio, round(freeze_ratio::numeric, 3)::float8 AS freeze_ratio, autovacuum_enabled
         FROM ts_vacuum_needed WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_vacuum_needed WHERE server_id = $1 AND collected_at >= $2)
         AND (vacuum_ratio >= 1 OR freeze_ratio >= 0.5) ORDER BY greatest(vacuum_ratio, freeze_ratio * 2) DESC LIMIT 10", &[&server, &from]).await?;
    Ok(
        json!({ "server_id": server, "from": from, "to": to, "databases": dbs, "connections": conns, "top_wait_events": waits, "events": events, "top_queries": top, "vacuum_attention": vac }),
    )
}

pub async fn top_queries(
    db: &Db,
    server: &str,
    from: Ts,
    to: Ts,
    datname: Option<&str>,
    order: &str,
    limit: i64,
) -> Result<Value> {
    let order_col = match order {
        "calls" => "calls",
        "mean_exec_time" => "mean_ms",
        "rows" => "rows",
        "shared_blks_read" => "shared_blks_read",
        "wal_bytes" => "wal_bytes",
        "storage_blks_read" => "storage_blks_read",
        _ => "total_ms",
    };
    let sql = format!(
        "WITH agg AS (
           SELECT s.queryid, s.datname, s.rolname,
                  sum(s.calls)::bigint AS calls, sum(s.total_exec_time)::float8 AS total_ms, sum(s.rows)::bigint AS rows,
                  CASE WHEN sum(s.calls) > 0 THEN sum(s.total_exec_time) / sum(s.calls) END::float8 AS mean_ms,
                  CASE WHEN sum(s.calls) > 0 THEN sqrt(greatest(sum(s.sumsq_exec_time) / sum(s.calls) - power(sum(s.total_exec_time) / sum(s.calls), 2), 0)) END::float8 AS stddev_ms,
                  sum(s.shared_blks_hit)::bigint AS shared_blks_hit, sum(s.shared_blks_read)::bigint AS shared_blks_read,
                  sum(s.temp_blks_written)::bigint AS temp_blks_written, sum(s.wal_bytes)::bigint AS wal_bytes,
                  sum(s.blk_read_time)::float8 AS blk_read_ms,
                  {aurora}
                  count(DISTINCT s.instance)::bigint AS instances
           FROM ts_query_stats s
           WHERE s.server_id = $1 AND s.collected_at >= $2 AND s.collected_at < $3 AND ($4::text IS NULL OR s.datname = $4)
           GROUP BY 1, 2, 3)
         SELECT a.*, q.query, q.fingerprint,
                round((a.total_ms / nullif(sum(a.total_ms) OVER (), 0) * 100)::numeric, 2)::float8 AS pct_of_total_time
         FROM agg a LEFT JOIN cur_queries q ON q.server_id = $1 AND q.queryid = a.queryid AND q.datname = a.datname
         ORDER BY {order_col} DESC NULLS LAST LIMIT $5",
        aurora = if has_column(db, "ts_query_stats", "storage_blks_read").await { "sum(s.storage_blks_read)::bigint AS storage_blks_read, max(s.max_exec_peakmem)::bigint AS max_exec_peakmem," } else { "NULL::bigint AS storage_blks_read, NULL::bigint AS max_exec_peakmem," },
    );
    Ok(json!(
        opt(db, &sql, &[&server, &from, &to, &datname, &limit]).await?
    ))
}

async fn has_column(db: &Db, table: &str, col: &str) -> bool {
    db.query(
        "SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2",
        &[&table, &col],
    )
    .await
    .map(|r| !r.is_empty())
    .unwrap_or(false)
}

pub async fn query_detail(db: &Db, server: &str, queryid: i64, from: Ts, to: Ts) -> Result<Value> {
    let texts = opt(db, "SELECT datname, query, fingerprint, truncated, first_seen, last_seen FROM cur_queries WHERE server_id = $1 AND queryid = $2", &[&server, &queryid]).await?;
    let fingerprint: Option<i64> = texts.first().and_then(|t| t["fingerprint"].as_i64());
    let series = opt(db, "SELECT date_trunc('minute', collected_at) AS minute, instance, datname,
                sum(calls)::bigint AS calls, sum(total_exec_time)::float8 AS total_ms,
                CASE WHEN sum(calls) > 0 THEN sum(total_exec_time) / sum(calls) END::float8 AS mean_ms,
                sum(rows)::bigint AS rows, sum(shared_blks_read)::bigint AS shared_blks_read, sum(shared_blks_hit)::bigint AS shared_blks_hit
         FROM ts_query_stats WHERE server_id = $1 AND queryid = $2 AND collected_at >= $3 AND collected_at < $4
         GROUP BY 1, 2, 3 ORDER BY 1", &[&server, &queryid, &from, &to]).await?;
    let quantiles = opt(db, "SELECT count(*)::bigint AS samples,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)::float8 AS p50,
                percentile_cont(0.9) WITHIN GROUP (ORDER BY duration_ms)::float8 AS p90,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::float8 AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)::float8 AS p99,
                max(duration_ms)::float8 AS max_ms, min(log_time) AS first_sample, max(log_time) AS last_sample
         FROM ts_query_durations WHERE server_id = $1 AND collected_at >= $3 AND collected_at < $4
           AND (query_id = $2 OR ($5::bigint IS NOT NULL AND fingerprint = $5))", &[&server, &queryid, &from, &to, &fingerprint]).await?;
    let slow_samples = opt(db, "SELECT log_time, log_stream, datname, usename, duration_ms, left(query, 500) AS query
         FROM ts_query_durations WHERE server_id = $1 AND collected_at >= $3 AND collected_at < $4
           AND (query_id = $2 OR ($5::bigint IS NOT NULL AND fingerprint = $5)) ORDER BY duration_ms DESC LIMIT 10", &[&server, &queryid, &from, &to, &fingerprint]).await?;
    let aurora_plans = opt(db, "SELECT p.planid, p.plan_type, p.plan_captured_time, p.explain_plan,
                (SELECT sum(calls) FROM ts_aurora_plans a WHERE a.server_id = $1 AND a.planid = p.planid AND a.queryid = $2 AND a.collected_at >= $3 AND a.collected_at < $4)::bigint AS calls,
                (SELECT sum(total_exec_time) FROM ts_aurora_plans a WHERE a.server_id = $1 AND a.planid = p.planid AND a.queryid = $2 AND a.collected_at >= $3 AND a.collected_at < $4)::float8 AS total_ms
         FROM cur_query_plans p WHERE p.server_id = $1 AND p.queryid = $2 ORDER BY calls DESC NULLS LAST", &[&server, &queryid, &from, &to]).await?;
    let logged_plans = opt(db, "SELECT log_time, datname, duration_ms, plan FROM ts_log_plans WHERE server_id = $1 AND collected_at >= $3 AND collected_at < $4
           AND (query_id = $2 OR ($5::bigint IS NOT NULL AND fingerprint = $5)) ORDER BY duration_ms DESC LIMIT 5", &[&server, &queryid, &from, &to, &fingerprint]).await?;
    let waits = opt(db, "SELECT wait_event_type, wait_event, sum(backends)::bigint AS samples FROM ts_activity_samples
         WHERE server_id = $1 AND query_id = $2 AND collected_at >= $3 AND collected_at < $4 GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10", &[&server, &queryid, &from, &to]).await?;
    Ok(
        json!({ "queryid": queryid, "texts": texts, "series": series, "latency_from_logs": quantiles.into_iter().next(), "slowest_samples": slow_samples,
               "plans": aurora_plans, "logged_plans": logged_plans, "wait_events": waits }),
    )
}

pub async fn wait_events(db: &Db, server: &str, from: Ts, to: Ts, bucket: &str) -> Result<Value> {
    let b = match bucket {
        "10s" => "10 seconds",
        "5m" => "5 minutes",
        "1h" => "1 hour",
        _ => "1 minute",
    };
    let sql = format!("SELECT to_timestamp(floor(extract(epoch FROM collected_at) / extract(epoch FROM interval '{b}')) * extract(epoch FROM interval '{b}')) AS bucket,
                instance, coalesce(wait_event_type, 'CPU') AS wait_event_type, coalesce(wait_event, 'CPU') AS wait_event,
                round(avg(backends)::numeric, 2)::float8 AS avg_active_sessions
         FROM ts_activity_samples WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 AND state = 'active'
         GROUP BY 1, 2, 3, 4 ORDER BY 1");
    let sampled = opt(db, &sql, &[&server, &from, &to]).await?;
    let measured = opt(db, "SELECT instance, type_name, event_name, sum(waits)::bigint AS waits, sum(wait_time)::bigint AS wait_time_us
         FROM ts_aurora_system_waits WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1, 2, 3 ORDER BY 5 DESC LIMIT 30", &[&server, &from, &to]).await?;
    Ok(json!({ "sampled": sampled, "measured_aurora": measured }))
}

pub async fn current_activity(db: &Db, server: &str) -> Result<Value> {
    let sessions = opt(db, "SELECT * FROM ts_activity_sessions WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_activity_sessions WHERE server_id = $1 AND collected_at > now() - interval '5 minutes') ORDER BY query_age_s DESC NULLS LAST", &[&server]).await?;
    let locks = opt(db, "SELECT * FROM ts_lock_waits WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_lock_waits WHERE server_id = $1 AND collected_at > now() - interval '5 minutes') ORDER BY waiting_s DESC", &[&server]).await?;
    let counts = opt(db, "SELECT instance, datname, state, sum(backends)::bigint AS backends FROM ts_activity_samples WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_activity_samples WHERE server_id = $1 AND collected_at > now() - interval '5 minutes') GROUP BY 1, 2, 3 ORDER BY 1, 2, 3", &[&server]).await?;
    let memctx = opt(db, "SELECT * FROM ts_aurora_memctx WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_aurora_memctx WHERE server_id = $1 AND collected_at > now() - interval '5 minutes') ORDER BY allocated_bytes DESC LIMIT 20", &[&server]).await?;
    Ok(
        json!({ "connections": counts, "sessions": sessions, "lock_waits": locks, "memory_hogs": memctx }),
    )
}

pub async fn tables(
    db: &Db,
    server: &str,
    datname: &str,
    from: Ts,
    to: Ts,
    limit: i64,
) -> Result<Value> {
    let rows = opt(db, "WITH stats AS (
           SELECT schemaname, relname, sum(seq_scan)::bigint AS seq_scan, sum(seq_tup_read)::bigint AS seq_tup_read, sum(idx_scan)::bigint AS idx_scan,
                  sum(n_tup_ins)::bigint AS n_tup_ins, sum(n_tup_upd)::bigint AS n_tup_upd, sum(n_tup_del)::bigint AS n_tup_del, sum(n_tup_hot_upd)::bigint AS n_tup_hot_upd,
                  sum(heap_blks_read)::bigint AS heap_blks_read, sum(heap_blks_hit)::bigint AS heap_blks_hit,
                  sum(vacuum_count + autovacuum_count)::bigint AS vacuums, sum(analyze_count + autoanalyze_count)::bigint AS analyzes
           FROM ts_table_stats WHERE server_id = $1 AND datname = $2 AND collected_at >= $3 AND collected_at < $4 GROUP BY 1, 2),
         latest AS (
           SELECT schemaname, relname, n_live_tup, n_dead_tup, n_mod_since_analyze, xid_age, reltuples, last_autovacuum, last_autoanalyze
           FROM ts_table_stats WHERE server_id = $1 AND datname = $2 AND collected_at = (SELECT max(collected_at) FROM ts_table_stats WHERE server_id = $1 AND datname = $2 AND collected_at >= $3)),
         sizes AS (
           SELECT schemaname, relname, heap_bytes, index_bytes, toast_bytes, total_bytes
           FROM ts_sizes WHERE server_id = $1 AND datname = $2 AND collected_at = (SELECT max(collected_at) FROM ts_sizes WHERE server_id = $1 AND datname = $2 AND collected_at >= $3))
         SELECT coalesce(l.schemaname, s.schemaname, z.schemaname) AS schemaname, coalesce(l.relname, s.relname, z.relname) AS relname,
                l.n_live_tup, l.n_dead_tup, l.n_mod_since_analyze, l.xid_age, l.last_autovacuum, l.last_autoanalyze,
                s.seq_scan, s.seq_tup_read, s.idx_scan, s.n_tup_ins, s.n_tup_upd, s.n_tup_del, s.n_tup_hot_upd, s.heap_blks_read, s.heap_blks_hit, s.vacuums, s.analyzes,
                z.heap_bytes, z.index_bytes, z.toast_bytes, z.total_bytes
         FROM latest l FULL JOIN stats s USING (schemaname, relname) FULL JOIN sizes z USING (schemaname, relname)
         ORDER BY z.total_bytes DESC NULLS LAST LIMIT $5", &[&server, &datname, &from, &to, &limit]).await?;
    Ok(json!(rows))
}

pub async fn indexes(db: &Db, server: &str, datname: &str, from: Ts, to: Ts) -> Result<Value> {
    let rows = opt(db, "WITH stats AS (
           SELECT schemaname, relname, indexrelname, sum(idx_scan)::bigint AS idx_scan, sum(idx_tup_read)::bigint AS idx_tup_read, sum(idx_blks_read)::bigint AS idx_blks_read
           FROM ts_index_stats WHERE server_id = $1 AND datname = $2 AND collected_at >= $3 AND collected_at < $4 GROUP BY 1, 2, 3)
         SELECT d.schemaname, d.relname, d.indexname, d.definition, d.is_unique, d.is_primary, d.is_valid, d.access_method, d.columns,
                coalesce(s.idx_scan, 0) AS idx_scan, s.idx_tup_read, s.idx_blks_read,
                (coalesce(s.idx_scan, 0) = 0 AND NOT d.is_unique AND NOT d.is_primary) AS unused_in_range
         FROM cur_schema_indexes d LEFT JOIN stats s ON s.schemaname = d.schemaname AND s.relname = d.relname AND s.indexrelname = d.indexname
         WHERE d.server_id = $1 AND d.datname = $2 AND d.last_seen > now() - interval '3 hours'
         ORDER BY unused_in_range DESC, idx_scan ASC", &[&server, &datname, &from, &to]).await?;
    Ok(json!(rows))
}

pub async fn vacuum(
    db: &Db,
    server: &str,
    datname: Option<&str>,
    from: Ts,
    to: Ts,
) -> Result<Value> {
    let needed = opt(db, "SELECT * FROM ts_vacuum_needed WHERE server_id = $1 AND ($2::text IS NULL OR datname = $2)
         AND collected_at = (SELECT max(collected_at) FROM ts_vacuum_needed WHERE server_id = $1 AND collected_at >= $3)
         ORDER BY greatest(vacuum_ratio, analyze_ratio, freeze_ratio * 2) DESC", &[&server, &datname, &from]).await?;
    let runs = opt(db, "SELECT log_time, log_stream, kind, relation, aggressive, index_scans, pages_removed, pages_remain, tuples_removed, tuples_remain, tuples_dead_not_removable,
                buffer_hits, buffer_misses, wal_bytes, read_mb_s, write_mb_s, elapsed_s
         FROM ts_autovacuum_runs WHERE server_id = $1 AND collected_at >= $3 AND collected_at < $4 AND ($2::text IS NULL OR relation LIKE $2 || '.%')
         ORDER BY log_time DESC LIMIT 100", &[&server, &datname, &from, &to]).await?;
    let progress = opt(db, "SELECT * FROM ts_vacuum_progress WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_vacuum_progress WHERE server_id = $1 AND collected_at > now() - interval '5 minutes')", &[&server]).await?;
    let xid = opt(db, "SELECT datname, max(xid_age)::bigint AS xid_age FROM ts_database_stats WHERE server_id = $1 AND collected_at >= $2 GROUP BY 1 ORDER BY 2 DESC", &[&server, &from]).await?;
    Ok(
        json!({ "needed": needed, "recent_runs": runs, "in_progress": progress, "database_xid_age": xid }),
    )
}

pub async fn events(
    db: &Db,
    server: &str,
    from: Ts,
    to: Ts,
    kind: Option<&str>,
    limit: i64,
) -> Result<Value> {
    Ok(json!(opt(db, "SELECT id, at, instance, datname, kind, subject, before, after FROM events WHERE server_id = $1 AND at >= $2 AND at < $3 AND ($4::text IS NULL OR kind LIKE $4)
         ORDER BY at DESC LIMIT $5", &[&server, &from, &to, &kind, &limit]).await?))
}

pub async fn settings(db: &Db, server: &str, non_default_only: bool) -> Result<Value> {
    Ok(json!(opt(db, "SELECT instance, name, setting, unit, source, boot_val, pending_restart, category FROM cur_settings WHERE server_id = $1 AND ($2 = false OR source <> 'default') ORDER BY name", &[&server, &non_default_only]).await?))
}

pub async fn schema(db: &Db, server: &str, datname: &str, relname: Option<&str>) -> Result<Value> {
    let rels = opt(db, "SELECT schemaname, relname, relkind, parent, partition_key, partition_bound, n_columns, columns, reloptions, view_definition, first_seen, last_seen
         FROM cur_schema_relations WHERE server_id = $1 AND datname = $2 AND ($3::text IS NULL OR relname = $3) AND last_seen > now() - interval '3 hours' ORDER BY 1, 2", &[&server, &datname, &relname]).await?;
    let idx = opt(db, "SELECT schemaname, relname, indexname, definition, is_unique, is_primary, is_valid, is_partial, columns FROM cur_schema_indexes WHERE server_id = $1 AND datname = $2 AND ($3::text IS NULL OR relname = $3) AND last_seen > now() - interval '3 hours' ORDER BY 1, 2, 3", &[&server, &datname, &relname]).await?;
    let cons = opt(db, "SELECT schemaname, relname, conname, contype, definition, is_validated, referenced_table FROM cur_schema_constraints WHERE server_id = $1 AND datname = $2 AND ($3::text IS NULL OR relname = $3) AND last_seen > now() - interval '3 hours' ORDER BY 1, 2, 3", &[&server, &datname, &relname]).await?;
    Ok(json!({ "relations": rels, "indexes": idx, "constraints": cons }))
}

pub async fn log_errors(db: &Db, server: &str, from: Ts, to: Ts, limit: i64) -> Result<Value> {
    let errors = opt(db, "SELECT log_time, log_stream, level, class, sqlstate, datname, usename, pid, query_id, message, detail, statement FROM ts_log_errors
         WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 ORDER BY log_time DESC LIMIT $4", &[&server, &from, &to, &limit]).await?;
    let summary = opt(db, "SELECT class, sqlstate, left(message, 120) AS message, count(*)::bigint AS n FROM ts_log_errors
         WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 20", &[&server, &from, &to]).await?;
    let counts = opt(db, "SELECT level, class, sum(count)::bigint AS n FROM ts_logs WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1, 2 ORDER BY 3 DESC", &[&server, &from, &to]).await?;
    let temp = opt(db, "SELECT log_time, datname, usename, query_id, size_bytes, left(statement, 300) AS statement FROM ts_temp_files WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 ORDER BY size_bytes DESC LIMIT 20", &[&server, &from, &to]).await?;
    Ok(json!({ "summary": summary, "counts": counts, "recent": errors, "temp_files": temp }))
}

pub async fn system(db: &Db, server: &str, from: Ts, to: Ts) -> Result<Value> {
    let cpu = opt(db, "SELECT collected_at, instance,
                round(((user_jiffies + nice_jiffies + system_jiffies + iowait_jiffies)::numeric / nullif(user_jiffies + nice_jiffies + system_jiffies + iowait_jiffies + idle_jiffies, 0)) * 100, 2)::float8 AS cpu_pct,
                round((iowait_jiffies::numeric / nullif(user_jiffies + nice_jiffies + system_jiffies + iowait_jiffies + idle_jiffies, 0)) * 100, 2)::float8 AS iowait_pct
         FROM ts_system_cpu WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 ORDER BY 1", &[&server, &from, &to]).await?;
    let mem = opt(db, "SELECT collected_at, instance, mem_used_kb, mem_free_kb, mem_cached_kb, swap_used_kb, load1, load5 FROM ts_system_memory WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 ORDER BY 1", &[&server, &from, &to]).await?;
    let backends = opt(db, "SELECT instance, datname, usename, application_name, backend_type, sum(utime_jiffies + stime_jiffies)::bigint AS cpu_jiffies, max(rss_kb)::bigint AS max_rss_kb
         FROM ts_backend_cpu WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1, 2, 3, 4, 5 ORDER BY 6 DESC LIMIT 20", &[&server, &from, &to]).await?;
    let checkpoints = opt(db, "SELECT log_time, log_stream, kind, buffers_written, buffers_pct, write_s, sync_s, total_s, distance_kb FROM ts_checkpoints WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 ORDER BY log_time DESC LIMIT 50", &[&server, &from, &to]).await?;
    let bgw = opt(db, "SELECT instance, sum(checkpoints_timed)::bigint AS checkpoints_timed, sum(checkpoints_req)::bigint AS checkpoints_req, sum(buffers_checkpoint)::bigint AS buffers_checkpoint, sum(buffers_clean)::bigint AS buffers_clean, sum(buffers_alloc)::bigint AS buffers_alloc
         FROM ts_bgwriter WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1", &[&server, &from, &to]).await?;
    let repl = opt(db, "SELECT * FROM ts_aurora_replica_status WHERE server_id = $1 AND collected_at = (SELECT max(collected_at) FROM ts_aurora_replica_status WHERE server_id = $1 AND collected_at >= $2)", &[&server, &from]).await?;
    let latency = opt(db, "SELECT datname, sum(commit_latency_us)::bigint AS commit_latency_us, sum(select_count)::bigint AS selects, sum(update_count)::bigint AS updates,
                CASE WHEN sum(update_count) > 0 THEN sum(update_latency_us) / sum(update_count) END::float8 AS avg_update_latency_us
         FROM ts_aurora_db_latency WHERE server_id = $1 AND collected_at >= $2 AND collected_at < $3 GROUP BY 1", &[&server, &from, &to]).await?;
    Ok(
        json!({ "cpu": cpu, "memory": mem, "top_backends_by_cpu": backends, "checkpoints": checkpoints, "bgwriter": bgw, "aurora_replicas": repl, "aurora_db_latency": latency }),
    )
}

pub async fn collector_health(db: &Db) -> Result<Value> {
    Ok(json!(db.query("SELECT server_id, instance, collector, count(*)::bigint AS ticks, count(error)::bigint AS errors, round(avg(duration_ms))::bigint AS avg_ms, max(duration_ms)::bigint AS max_ms, max(started_at) AS last_tick,
                max(error) AS last_error
         FROM collector_runs WHERE started_at > now() - interval '15 minutes' GROUP BY 1, 2, 3 ORDER BY errors DESC, 1, 2, 3", &[]).await?))
}

/// Free-form read-only SQL against the stats DB for agents.
///
/// Defence in depth, because a leading `SELECT` does not make a statement side-effect
/// free (`pg_advisory_lock()`, `pg_sleep()`, `set_config()` are all callable from one):
/// * only a single SELECT / WITH / EXPLAIN statement is accepted;
/// * it runs inside a read-only transaction with its own short statement timeout;
/// * the session is `DISCARD ALL`ed afterwards (drops advisory locks, temp tables,
///   session settings) and, if that fails, thrown away rather than returned to the pool;
/// * the DB user is a read-only role with no privileges beyond SELECT.
pub async fn raw_sql(db: &Db, sql: &str, limit: i64) -> Result<Value> {
    let trimmed = sql.trim().trim_end_matches(';').trim();
    let head = trimmed
        .split_whitespace()
        .next()
        .unwrap_or("")
        .to_ascii_uppercase();
    anyhow::ensure!(
        matches!(head.as_str(), "SELECT" | "WITH" | "EXPLAIN"),
        "only SELECT / WITH / EXPLAIN statements are allowed"
    );
    anyhow::ensure!(!trimmed.contains(';'), "one statement only");
    if let Some(f) = denied_function(trimmed) {
        anyhow::bail!("function {f}() is not allowed here");
    }
    let statement = if head == "EXPLAIN" {
        // EXPLAIN cannot be wrapped in a subquery; it returns text rows itself.
        trimmed.to_string()
    } else {
        format!(
            "SELECT * FROM ({trimmed}) _q LIMIT {}",
            limit.clamp(1, 5000)
        )
    };
    db.query_isolated(&statement).await
}

/// Functions that have effects beyond returning rows and are therefore refused in raw
/// SQL even though the statement is a SELECT. Session isolation (`query_isolated`)
/// already contains most of these; the denylist makes the intent explicit and stops
/// the cheap ones (sleeping, signalling backends, resetting stats) before they run.
const DENIED_FUNCTIONS: &[&str] = &[
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_advisory_lock",
    "pg_advisory_lock_shared",
    "pg_advisory_xact_lock",
    "pg_advisory_xact_lock_shared",
    "pg_try_advisory_lock",
    "pg_try_advisory_lock_shared",
    "pg_try_advisory_xact_lock",
    "pg_try_advisory_xact_lock_shared",
    "pg_advisory_unlock",
    "pg_advisory_unlock_all",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_stat_reset",
    "pg_stat_reset_shared",
    "pg_stat_reset_single_table_counters",
    "pg_stat_reset_single_function_counters",
    "pg_stat_statements_reset",
    "set_config",
    "pg_notify",
    "pg_switch_wal",
    "pg_create_restore_point",
    "pg_backup_start",
    "pg_backup_stop",
    "pg_start_backup",
    "pg_stop_backup",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "lo_unlink",
    "dblink",
    "dblink_connect",
    "dblink_exec",
    "nextval",
    "setval",
    "txid_current",
    "pg_current_xact_id",
];

fn denied_function(sql: &str) -> Option<&'static str> {
    static COMMENT: once_cell::sync::Lazy<regex::Regex> =
        once_cell::sync::Lazy::new(|| regex::Regex::new(r"(?s)/\*.*?\*/|--[^\n]*").unwrap());
    static CALL: once_cell::sync::Lazy<regex::Regex> =
        once_cell::sync::Lazy::new(|| regex::Regex::new(r"(?i)\b([a-z_][a-z0-9_]*)\s*\(").unwrap());
    // Comments are legal between a function name and its parenthesis (`pg_sleep/**/(1)`),
    // so scan the statement with them removed.
    let stripped = COMMENT.replace_all(sql, " ");
    CALL.captures_iter(&stripped).find_map(|c| {
        let name = c[1].to_ascii_lowercase();
        DENIED_FUNCTIONS.iter().copied().find(|d| *d == name)
    })
}

pub async fn schema_of_stats_db(db: &Db) -> Result<Value> {
    Ok(json!(db.query("SELECT c.relname AS table_name, string_agg(a.attname || ' ' || format_type(a.atttypid, a.atttypmod), ', ' ORDER BY a.attnum) AS columns
         FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname !~ '_[0-9]{8}$' GROUP BY 1 ORDER BY 1", &[]).await?))
}

#[cfg(test)]
mod tests {
    use super::denied_function;

    #[test]
    fn denylist_catches_side_effecting_calls() {
        assert_eq!(denied_function("select pg_sleep(20)"), Some("pg_sleep"));
        assert_eq!(
            denied_function("select PG_Advisory_Lock (1)"),
            Some("pg_advisory_lock")
        );
        assert_eq!(
            denied_function("select set_config('x', 'y', false)"),
            Some("set_config")
        );
        assert_eq!(
            denied_function("select count(*), max(collected_at) from ts_query_stats"),
            None
        );
        assert_eq!(denied_function("select pg_sleepy from t"), None);
        assert_eq!(denied_function("select pg_sleep/**/(1)"), Some("pg_sleep"));
        assert_eq!(
            denied_function("select pg_sleep -- x\n(1)"),
            Some("pg_sleep")
        );
        assert_eq!(
            denied_function("select pg_catalog.pg_advisory_lock/* c */ (1)"),
            Some("pg_advisory_lock")
        );
    }
}
