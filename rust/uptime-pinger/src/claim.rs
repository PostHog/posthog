use anyhow::Result;
use chrono::{DateTime, Utc};
use sqlx::PgPool;
use uuid::Uuid;

/// One monitor claimed for an immediate ping.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct ClaimedMonitor {
    pub id: Uuid,
    pub team_id: i64,
    pub name: String,
    pub url: String,
    pub interval_seconds: i32,
    pub leased_until: DateTime<Utc>,
}

/// Atomically claim up to `batch_size` monitors whose `next_check_at` has passed.
///
/// The query advances `next_check_at` by the monitor's own `interval_seconds` and stamps
/// `leased_until = now() + $lease_ttl`. Re-pick is implicitly gated by `next_check_at`,
/// so a crashed worker doesn't strand a monitor — once `next_check_at` falls in the past,
/// some other worker takes it.
///
/// `FOR UPDATE SKIP LOCKED` lets multiple workers hit this CTE in parallel without
/// blocking each other or double-claiming a row.
pub async fn claim_due_monitors(
    pool: &PgPool,
    batch_size: i64,
    lease_ttl_seconds: i64,
) -> Result<Vec<ClaimedMonitor>> {
    let rows = sqlx::query_as::<_, ClaimedMonitor>(
        r#"
WITH due AS (
    SELECT id
    FROM uptime_monitor
    WHERE next_check_at <= NOW()
    ORDER BY next_check_at ASC
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
UPDATE uptime_monitor m
SET
    next_check_at = NOW() + (m.interval_seconds * INTERVAL '1 second'),
    leased_until = NOW() + ($2 * INTERVAL '1 second')
FROM due
WHERE m.id = due.id
RETURNING m.id, m.team_id, m.name, m.url, m.interval_seconds, m.leased_until
"#,
    )
    .bind(batch_size)
    .bind(lease_ttl_seconds as f64)
    .fetch_all(pool)
    .await?;

    Ok(rows)
}
