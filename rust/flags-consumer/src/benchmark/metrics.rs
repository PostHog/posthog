use std::time::Duration;

use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct PgSnapshot {
    pub n_tup_upd: i64,
    pub n_tup_hot_upd: i64,
    pub n_dead_tup: i64,
    pub table_bytes: i64,
    pub index_bytes: i64,
    pub wal_lsn: Option<String>,
}

pub struct PhaseDelta {
    pub hot_pct: f64,
    pub dead_tuples: i64,
}

#[derive(Debug)]
pub struct LatencyStats {
    pub count: usize,
    pub p50: Duration,
    pub p95: Duration,
    pub p99: Duration,
    pub max: Duration,
}

pub async fn capture_snapshot(pool: &PgPool) -> anyhow::Result<PgSnapshot> {
    let stats: (i64, i64, i64) = sqlx::query_as(
        "SELECT \
            COALESCE(SUM(n_tup_upd), 0)::bigint, \
            COALESCE(SUM(n_tup_hot_upd), 0)::bigint, \
            COALESCE(SUM(n_dead_tup), 0)::bigint \
         FROM pg_stat_user_tables \
         WHERE relname LIKE 'flags_person_lookup_p%'",
    )
    .fetch_one(pool)
    .await?;

    let sizes: (i64, i64) = sqlx::query_as(
        "SELECT \
            COALESCE(SUM(pg_relation_size(oid)), 0)::bigint, \
            COALESCE(SUM(pg_indexes_size(oid)), 0)::bigint \
         FROM pg_class \
         WHERE relname LIKE 'flags_person_lookup_p%'",
    )
    .fetch_one(pool)
    .await?;

    // Requires pg_monitor role; returns None on permission error.
    let wal_lsn: Option<String> =
        match sqlx::query_as::<_, (String,)>("SELECT pg_current_wal_lsn()::text")
            .fetch_one(pool)
            .await
        {
            Ok((lsn,)) => Some(lsn),
            Err(e) => {
                tracing::debug!("WAL LSN unavailable (need pg_monitor role): {e}");
                None
            }
        };

    Ok(PgSnapshot {
        n_tup_upd: stats.0,
        n_tup_hot_upd: stats.1,
        n_dead_tup: stats.2,
        table_bytes: sizes.0,
        index_bytes: sizes.1,
        wal_lsn,
    })
}

pub fn compute_delta(before: &PgSnapshot, after: &PgSnapshot) -> PhaseDelta {
    let updates = after.n_tup_upd - before.n_tup_upd;
    let hot_updates = after.n_tup_hot_upd - before.n_tup_hot_upd;
    let hot_pct = if updates > 0 {
        (hot_updates as f64 / updates as f64) * 100.0
    } else {
        0.0
    };

    PhaseDelta {
        hot_pct,
        dead_tuples: after.n_dead_tup - before.n_dead_tup,
    }
}

pub async fn compute_wal_delta(
    pool: &PgPool,
    before: &PgSnapshot,
    after: &PgSnapshot,
) -> Option<i64> {
    let (before_lsn, after_lsn) = match (&before.wal_lsn, &after.wal_lsn) {
        (Some(b), Some(a)) => (b.clone(), a.clone()),
        _ => return None,
    };

    match sqlx::query_as::<_, (i64,)>("SELECT pg_wal_lsn_diff($1::pg_lsn, $2::pg_lsn)::bigint")
        .bind(&after_lsn)
        .bind(&before_lsn)
        .fetch_one(pool)
        .await
    {
        Ok((diff,)) => Some(diff),
        Err(e) => {
            tracing::debug!("WAL diff query failed: {e}");
            None
        }
    }
}

/// Requires pg_stat_scan_tables role. Logs a warning and returns early if unavailable.
pub async fn reset_stats(pool: &PgPool) {
    for i in 0..super::schema::PARTITION_COUNT {
        let table = format!("flags_person_lookup_p{i}");
        let result = sqlx::query(
            "SELECT pg_stat_reset_single_table_counters(oid) FROM pg_class WHERE relname = $1",
        )
        .bind(&table)
        .execute(pool)
        .await;
        if let Err(e) = result {
            tracing::warn!(
                "could not reset pg_stat counters for {table} (need pg_stat_scan_tables role): {e}"
            );
            return;
        }
    }
    tracing::info!("pg_stat counters reset for all partitions");
}

/// Sorts the slice in place.
pub fn compute_percentiles(latencies: &mut [Duration]) -> LatencyStats {
    let count = latencies.len();
    if count == 0 {
        return LatencyStats {
            count: 0,
            p50: Duration::ZERO,
            p95: Duration::ZERO,
            p99: Duration::ZERO,
            max: Duration::ZERO,
        };
    }

    latencies.sort_unstable();

    let p = |pct: f64| -> Duration {
        let idx = ((count as f64 * pct) as usize).min(count - 1);
        latencies[idx]
    };

    LatencyStats {
        count,
        p50: p(0.50),
        p95: p(0.95),
        p99: p(0.99),
        max: latencies[count - 1],
    }
}
