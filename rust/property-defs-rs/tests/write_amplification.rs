// Real-DB write-amplification harness. Unlike the in-memory benchmark (which counts updates
// that *would* hit the DB), this drives the actual `process_batch` write path against Postgres
// and reads how many rows the real `ON CONFLICT` statements actually changed. It quantifies the
// D1 win — flooring event-def `last_seen_at` to a day instead of an hour — in terms of real
// rows written, and asserts the reduction so it also guards against regressions.
//
// Requires a live Postgres (DATABASE_URL). Run:
//   DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog \
//     cargo test -p property-defs-rs --test write_amplification -- --nocapture

use std::sync::{Arc, OnceLock};

use chrono::{Duration, Utc};
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use sqlx::PgPool;

use property_defs_rs::{
    batch_ingestion::process_batch,
    config::Config,
    metrics_consts::V2_EVENT_DEFS_BATCH_ROWS_AFFECTED,
    types::{floor_last_seen, EventDefinition, Update},
    update_cache::Cache,
};

fn snapshotter() -> &'static Snapshotter {
    static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
    SNAPSHOTTER.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let s = recorder.snapshotter();
        drop(recorder.install());
        s
    })
}

fn counter(metric: &'static str) -> u64 {
    snapshotter()
        .snapshot()
        .into_vec()
        .into_iter()
        .find(|(key, _, _, _)| key.key().name() == metric)
        .and_then(|(_, _, _, value)| match value {
            DebugValue::Counter(v) => Some(v),
            _ => None,
        })
        .unwrap_or(0)
}

/// Replay `num_defs` event definitions across `hours` simulated hourly arrivals, flooring
/// last_seen_at by `floor_secs`, through the producer cache filter + the real write path.
/// Returns (rows_attempted, rows_affected): updates that survived the cache and reached the
/// DB, and rows the DB actually changed.
async fn replay(db: &PgPool, floor_secs: i64, hours: i64, num_defs: i32) -> (u64, u64) {
    let config = Config::init_with_defaults().unwrap();
    let cache = Arc::new(Cache::new(1_000_000, 1_000_000, 1_000_000));
    let base = floor_last_seen(Utc::now(), 3600);

    let affected_before = counter(V2_EVENT_DEFS_BATCH_ROWS_AFFECTED);
    let mut attempted: u64 = 0;

    for h in 0..hours {
        let ts = floor_last_seen(base + Duration::hours(h), floor_secs);
        let mut batch: Vec<Update> = Vec::new();
        for t in 0..num_defs {
            let update = Update::Event(EventDefinition {
                name: format!("amp_event_{t}"),
                team_id: 1,
                project_id: 1,
                last_seen_at: ts,
            });
            // mirror the producer: shared-cache dedup before the DB
            if cache.contains_key(&update) {
                continue;
            }
            cache.insert(update.clone());
            batch.push(update);
        }
        attempted += batch.len() as u64;
        if !batch.is_empty() {
            process_batch(&config, cache.clone(), db, batch).await;
        }
    }

    let affected = counter(V2_EVENT_DEFS_BATCH_ROWS_AFFECTED) - affected_before;
    (attempted, affected)
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn eventdef_write_amplification_hourly_vs_daily(db: PgPool) {
    let hours = 24;
    let defs = 500;

    let (attempted_hourly, affected_hourly) = replay(&db, 3600, hours, defs).await;

    // Reset so the two runs are independent (fresh table; replay() builds a fresh cache).
    sqlx::query("TRUNCATE posthog_eventdefinition")
        .execute(&db)
        .await
        .unwrap();

    let (attempted_daily, affected_daily) = replay(&db, 86400, hours, defs).await;

    println!("\n=== event-def write amplification ({hours}h, {defs} defs) ===");
    println!("hourly floor : attempted={attempted_hourly:>6}  rows_affected={affected_hourly:>6}");
    println!("daily  floor : attempted={attempted_daily:>6}  rows_affected={affected_daily:>6}");
    let reduction = 100.0 * (1.0 - affected_daily as f64 / affected_hourly as f64);
    println!("rows written reduced by {reduction:.1}% with the daily floor");

    // Hourly re-issues every event def every hour (24 * defs). Daily collapses those into the
    // 1-2 day buckets a rolling 24h window touches, so it writes each def at most twice.
    assert!(
        attempted_daily <= 2 * defs as u64,
        "daily floor should attempt at most one write per def per day-bucket ({attempted_daily})"
    );
    assert!(
        affected_daily * 5 < affected_hourly,
        "daily floor must change far fewer rows ({affected_daily} vs {affected_hourly})"
    );
}
