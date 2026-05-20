use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use crate::storage::{
    postgres::PostgresStorage,
    types::{DistinctIdAssignmentData, PersonUpdateData},
};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use sqlx::PgPool;
use uuid::Uuid;

use super::data_gen::{generate_properties, select_team_weighted, BenchmarkData};
use super::metrics::{self, LatencyStats, PgSnapshot};
use super::BenchmarkArgs;

pub struct PhaseResult {
    pub name: String,
    pub latency: LatencyStats,
    pub before: PgSnapshot,
    pub after: PgSnapshot,
    pub wal_bytes: Option<i64>,
    pub errors: u64,
}

fn spawn_merge_writers(
    pool: &PgPool,
    data: &BenchmarkData,
    concurrency: usize,
    deadline: Instant,
    seed_offset: u64,
    version_counter: Arc<AtomicI64>,
    error_counter: Arc<AtomicU64>,
) -> Vec<tokio::task::JoinHandle<Vec<Duration>>> {
    let mut handles = Vec::with_capacity(concurrency);

    for task_id in 0..concurrency {
        let storage = PostgresStorage::new(pool.clone());
        let distinct_ids = data.distinct_ids.clone();
        let team_indices = data.team_person_indices.clone();
        let team_cdf = data.team_cdf.clone();
        let version_counter = version_counter.clone();
        let error_counter = error_counter.clone();

        handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(10_000);
            let mut rng = StdRng::seed_from_u64(seed_offset + task_id as u64);

            while Instant::now() < deadline {
                let team_id = match select_team_weighted(&team_cdf, &mut rng) {
                    Some(tid) => tid,
                    None => continue,
                };

                let indices = match team_indices.get(&team_id) {
                    Some(idx) if idx.len() >= 2 => idx,
                    _ => continue,
                };

                let src_local = rng.gen_range(0..indices.len());
                let mut tgt_local = rng.gen_range(0..indices.len());
                while tgt_local == src_local {
                    tgt_local = rng.gen_range(0..indices.len());
                }

                let (_, _, src_did) = &distinct_ids[indices[src_local]];
                let (_, tgt_uuid, _) = &distinct_ids[indices[tgt_local]];

                let assignment = DistinctIdAssignmentData {
                    team_id,
                    person_uuid: *tgt_uuid,
                    distinct_id: src_did.clone().into_boxed_str(),
                    version: version_counter.fetch_add(1, Ordering::Relaxed),
                };

                let start = Instant::now();
                match storage.upsert_distinct_id(&assignment).await {
                    Ok(_) => latencies.push(start.elapsed()),
                    Err(_) => {
                        error_counter.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            latencies
        }));
    }

    handles
}

/// Property-only updates. Does not mutate distinct_ids, so the GIN index is untouched
/// and updates should be HOT-eligible.
pub async fn phase_property_updates(
    pool: &PgPool,
    data: &BenchmarkData,
    args: &BenchmarkArgs,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(args.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(100));
    let error_counter = Arc::new(AtomicU64::new(0));

    let mut handles = Vec::with_capacity(args.concurrency);

    for task_id in 0..args.concurrency {
        let storage = PostgresStorage::new(pool.clone());
        let persons = data.persons.clone();
        let batch_size = args.batch_size;
        let version_counter = version_counter.clone();
        let error_counter = error_counter.clone();

        handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(10_000);
            let mut rng = StdRng::seed_from_u64(task_id as u64);

            while Instant::now() < deadline {
                // Unique persons per batch to avoid "ON CONFLICT DO UPDATE cannot affect
                // row a second time". Sorted by (team_id, person_uuid) to prevent deadlocks.
                let actual_batch = batch_size.min(persons.len());
                let mut seen = std::collections::HashSet::with_capacity(actual_batch);
                let mut batch = Vec::with_capacity(actual_batch);
                while batch.len() < actual_batch {
                    let idx = rng.gen_range(0..persons.len());
                    if seen.insert(idx) {
                        let (team_id, person_uuid) = &persons[idx];
                        batch.push(PersonUpdateData {
                            team_id: *team_id,
                            person_uuid: *person_uuid,
                            properties: generate_properties(&mut rng, 700),
                            version: version_counter.fetch_add(1, Ordering::Relaxed),
                        });
                    }
                }
                batch.sort_by(|a, b| {
                    a.team_id
                        .cmp(&b.team_id)
                        .then(a.person_uuid.cmp(&b.person_uuid))
                });

                let start = Instant::now();
                match storage.batch_upsert_persons(&batch).await {
                    Ok(_) => latencies.push(start.elapsed()),
                    Err(e) => {
                        tracing::warn!("batch_upsert_persons error: {e}");
                        error_counter.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            latencies
        }));
    }

    let mut all_latencies = Vec::new();
    for handle in handles {
        all_latencies.extend(handle.await?);
    }

    let after = metrics::capture_snapshot(pool).await?;
    let wal_bytes = metrics::compute_wal_delta(pool, &before, &after).await;

    Ok(PhaseResult {
        name: "Property updates".into(),
        latency: metrics::compute_percentiles(&mut all_latencies),
        before,
        after,
        wal_bytes,
        errors: error_counter.load(Ordering::Relaxed),
    })
}

/// Assign new distinct_ids to existing persons. Each operation appends to the
/// distinct_ids array and forces a GIN index update.
pub async fn phase_identification_appends(
    pool: &PgPool,
    data: &BenchmarkData,
    args: &BenchmarkArgs,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(args.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(1_000_000));
    let error_counter = Arc::new(AtomicU64::new(0));

    let mut handles = Vec::with_capacity(args.concurrency);

    for task_id in 0..args.concurrency {
        let storage = PostgresStorage::new(pool.clone());
        let persons = data.persons.clone();
        let version_counter = version_counter.clone();
        let error_counter = error_counter.clone();

        handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(10_000);
            let mut rng = StdRng::seed_from_u64(1000 + task_id as u64);

            while Instant::now() < deadline {
                let idx = rng.gen_range(0..persons.len());
                let (team_id, person_uuid) = &persons[idx];

                let mut did_bytes = [0u8; 16];
                rng.fill(&mut did_bytes);

                let assignment = DistinctIdAssignmentData {
                    team_id: *team_id,
                    person_uuid: *person_uuid,
                    distinct_id: Uuid::from_bytes(did_bytes).to_string().into_boxed_str(),
                    version: version_counter.fetch_add(1, Ordering::Relaxed),
                };

                let start = Instant::now();
                match storage.upsert_distinct_id(&assignment).await {
                    Ok(_) => latencies.push(start.elapsed()),
                    Err(_) => {
                        error_counter.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            latencies
        }));
    }

    let mut all_latencies = Vec::new();
    for handle in handles {
        all_latencies.extend(handle.await?);
    }

    let after = metrics::capture_snapshot(pool).await?;
    let wal_bytes = metrics::compute_wal_delta(pool, &before, &after).await;

    Ok(PhaseResult {
        name: "ID appends".into(),
        latency: metrics::compute_percentiles(&mut all_latencies),
        before,
        after,
        wal_bytes,
        errors: error_counter.load(Ordering::Relaxed),
    })
}

/// Reassign a distinct_id from one person to another within the same team.
/// Each merge triggers array_remove on the source and array_append on the target,
/// causing two GIN index updates per operation.
pub async fn phase_merges(
    pool: &PgPool,
    data: &BenchmarkData,
    args: &BenchmarkArgs,
    name: &str,
    concurrency_override: Option<usize>,
    duration_override: Option<u64>,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let concurrency = concurrency_override.unwrap_or(args.concurrency);
    let duration = duration_override.unwrap_or(args.duration_secs);
    let deadline = Instant::now() + Duration::from_secs(duration);
    let version_counter = Arc::new(AtomicI64::new(10_000_000));
    let error_counter = Arc::new(AtomicU64::new(0));

    let handles = spawn_merge_writers(
        pool,
        data,
        concurrency,
        deadline,
        2000,
        version_counter,
        error_counter.clone(),
    );

    let mut all_latencies = Vec::new();
    for handle in handles {
        all_latencies.extend(handle.await?);
    }

    let after = metrics::capture_snapshot(pool).await?;
    let wal_bytes = metrics::compute_wal_delta(pool, &before, &after).await;

    Ok(PhaseResult {
        name: name.into(),
        latency: metrics::compute_percentiles(&mut all_latencies),
        before,
        after,
        wal_bytes,
        errors: error_counter.load(Ordering::Relaxed),
    })
}

pub struct QueryPlanInfo {
    pub gin_index_used: bool,
    pub plan_text: String,
}

/// Merge writers alongside GIN-indexed read queries to measure whether
/// GIN maintenance degrades read latency.
pub async fn phase_concurrent_reads_writes(
    pool: &PgPool,
    data: &BenchmarkData,
    args: &BenchmarkArgs,
) -> anyhow::Result<(PhaseResult, PhaseResult, QueryPlanInfo)> {
    let plan_info = check_read_query_plan(pool, data).await;

    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(args.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(100_000_000));
    let write_errors = Arc::new(AtomicU64::new(0));
    let read_errors = Arc::new(AtomicU64::new(0));

    let write_handles = spawn_merge_writers(
        pool,
        data,
        args.concurrency,
        deadline,
        5000,
        version_counter,
        write_errors.clone(),
    );

    let mut read_handles = Vec::with_capacity(args.concurrency);

    for task_id in 0..args.concurrency {
        let pool = pool.clone();
        let distinct_ids = data.distinct_ids.clone();
        let read_errors = read_errors.clone();

        read_handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(50_000);
            let mut rng = StdRng::seed_from_u64(6000 + task_id as u64);

            while Instant::now() < deadline {
                let idx = rng.gen_range(0..distinct_ids.len());
                let (team_id, _, did) = &distinct_ids[idx];

                let start = Instant::now();
                let result = sqlx::query(
                    "SELECT person_uuid, distinct_ids, properties \
                     FROM flags_person_lookup \
                     WHERE team_id = $1 AND distinct_ids @> ARRAY[$2]::text[] \
                       AND deleted_at IS NULL \
                     LIMIT 1",
                )
                .bind(team_id)
                .bind(did)
                .fetch_optional(&pool)
                .await;

                match result {
                    Ok(_) => latencies.push(start.elapsed()),
                    Err(_) => {
                        read_errors.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            latencies
        }));
    }

    let mut write_latencies = Vec::new();
    for handle in write_handles {
        write_latencies.extend(handle.await?);
    }
    let mut read_latencies = Vec::new();
    for handle in read_handles {
        read_latencies.extend(handle.await?);
    }

    let after = metrics::capture_snapshot(pool).await?;
    let wal_bytes = metrics::compute_wal_delta(pool, &before, &after).await;

    let write_result = PhaseResult {
        name: "Reads+Writes (writes)".into(),
        latency: metrics::compute_percentiles(&mut write_latencies),
        before: before.clone(),
        after: after.clone(),
        wal_bytes,
        errors: write_errors.load(Ordering::Relaxed),
    };

    let read_result = PhaseResult {
        name: "Reads+Writes (reads)".into(),
        latency: metrics::compute_percentiles(&mut read_latencies),
        before,
        after,
        wal_bytes: None,
        errors: read_errors.load(Ordering::Relaxed),
    };

    Ok((write_result, read_result, plan_info))
}

/// Run EXPLAIN on the read query and check whether the GIN index is used.
/// After heavy mutations the planner might fall back to sequential scans.
async fn check_read_query_plan(pool: &PgPool, data: &BenchmarkData) -> QueryPlanInfo {
    if data.distinct_ids.is_empty() {
        return QueryPlanInfo {
            gin_index_used: false,
            plan_text: "no data".into(),
        };
    }

    let (team_id, _, did) = &data.distinct_ids[0];

    let plan: Result<Vec<(String,)>, _> = sqlx::query_as(
        "EXPLAIN (ANALYZE, BUFFERS) \
         SELECT person_uuid, distinct_ids, properties \
         FROM flags_person_lookup \
         WHERE team_id = $1 AND distinct_ids @> ARRAY[$2]::text[] \
           AND deleted_at IS NULL \
         LIMIT 1",
    )
    .bind(team_id)
    .bind(did)
    .fetch_all(pool)
    .await;

    match plan {
        Ok(rows) => {
            let plan_text = rows
                .into_iter()
                .map(|(line,)| line)
                .collect::<Vec<_>>()
                .join("\n");
            // The migration names the parent GIN index `idx_flags_person_gin`,
            // but Postgres auto-names partition-local indexes as
            // `<partition>_team_id_distinct_ids_idx`, so we match either form.
            let gin_index_used = plan_text.contains("idx_flags_person_gin")
                || plan_text.contains("team_id_distinct_ids_idx");
            tracing::info!(gin_index_used, "Phase 5 read query plan:\n{plan_text}");
            QueryPlanInfo {
                gin_index_used,
                plan_text,
            }
        }
        Err(e) => {
            tracing::warn!("could not run EXPLAIN for read query: {e}");
            QueryPlanInfo {
                gin_index_used: false,
                plan_text: format!("EXPLAIN failed: {e}"),
            }
        }
    }
}
