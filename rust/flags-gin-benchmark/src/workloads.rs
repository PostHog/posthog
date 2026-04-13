use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use flags_consumer::storage::{
    postgres::PostgresStorage,
    types::{DistinctIdAssignmentData, PersonUpdateData},
};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use sqlx::PgPool;
use uuid::Uuid;

use crate::config::BenchmarkConfig;
use crate::data_gen::{generate_properties, select_team_weighted, BenchmarkData};
use crate::metrics::{self, LatencyStats, PgSnapshot};

/// Result of a single workload phase.
pub struct PhaseResult {
    pub name: String,
    pub latency: LatencyStats,
    pub before: PgSnapshot,
    pub after: PgSnapshot,
    pub wal_bytes: Option<i64>,
    pub errors: u64,
}

/// Phase 1: Sustained property-only updates via batch_upsert_persons.
///
/// These updates change `properties` and `person_version` only — no `distinct_ids`
/// mutation, so the GIN index should remain untouched and updates should be HOT-eligible.
/// Properties are generated at ~700 bytes per update to match production row sizes.
pub async fn phase_property_updates(
    pool: &PgPool,
    data: &BenchmarkData,
    config: &BenchmarkConfig,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(config.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(100));
    let error_counter = Arc::new(AtomicU64::new(0));

    let mut handles = Vec::with_capacity(config.concurrency);

    for task_id in 0..config.concurrency {
        let storage = PostgresStorage::new(pool.clone());
        let persons = data.persons.clone();
        let batch_size = config.batch_size;
        let version_counter = version_counter.clone();
        let error_counter = error_counter.clone();

        handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(10_000);
            let mut rng = StdRng::seed_from_u64(task_id as u64);

            while Instant::now() < deadline {
                // Pick unique persons to avoid "ON CONFLICT DO UPDATE cannot
                // affect row a second time" within a single UNNEST batch.
                // Sort by (team_id, person_uuid) to prevent deadlocks between
                // concurrent batches that touch overlapping rows.
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

/// Phase 2: Identification appends — assign NEW distinct_ids to existing persons.
///
/// This exercises the `upsert_distinct_id` path where the `array_remove` step is a
/// no-op (no previous owner) but the `INSERT ON CONFLICT` appends to the array via `||`.
/// Each operation mutates the distinct_ids array and forces a GIN index update.
pub async fn phase_identification_appends(
    pool: &PgPool,
    data: &BenchmarkData,
    config: &BenchmarkConfig,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(config.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(1_000_000));
    let error_counter = Arc::new(AtomicU64::new(0));

    let mut handles = Vec::with_capacity(config.concurrency);

    for task_id in 0..config.concurrency {
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

                // UUID-format distinct_id (~36 bytes) matching real-world ID length.
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

/// Phase 3 / Phase 4 / Phase 6: Merge workload — reassign a distinct_id from one person to another.
///
/// This triggers `array_remove` on the source person and `array_append` on the target,
/// causing two GIN index updates per operation. This is the core scenario for the benchmark.
///
/// Teams are selected proportionally to their person count (weighted CDF), so large
/// teams get more merge traffic — matching production where traffic correlates with team size.
///
/// `concurrency_override` lets the burst phase (Phase 4) use a higher task count.
/// `duration_override` lets the burst phase run for a shorter window.
pub async fn phase_merges(
    pool: &PgPool,
    data: &BenchmarkData,
    config: &BenchmarkConfig,
    name: &str,
    concurrency_override: Option<usize>,
    duration_override: Option<u64>,
) -> anyhow::Result<PhaseResult> {
    let before = metrics::capture_snapshot(pool).await?;
    let concurrency = concurrency_override.unwrap_or(config.concurrency);
    let duration = duration_override.unwrap_or(config.duration_secs);
    let deadline = Instant::now() + Duration::from_secs(duration);
    let version_counter = Arc::new(AtomicI64::new(10_000_000));
    let error_counter = Arc::new(AtomicU64::new(0));

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
            let mut rng = StdRng::seed_from_u64(2000 + task_id as u64);

            while Instant::now() < deadline {
                // Weighted team selection: larger teams get proportionally more traffic.
                let team_id = match select_team_weighted(&team_cdf, &mut rng) {
                    Some(tid) => tid,
                    None => continue,
                };

                let indices = match team_indices.get(&team_id) {
                    Some(idx) if idx.len() >= 2 => idx,
                    _ => continue,
                };

                // Pick source and target persons (different).
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

/// Phase 5: Concurrent reads and writes.
///
/// Runs merge writers alongside GIN-indexed read queries to measure whether
/// GIN maintenance degrades read latency. Writers use weighted team selection
/// matching the merge phases.
pub async fn phase_concurrent_reads_writes(
    pool: &PgPool,
    data: &BenchmarkData,
    config: &BenchmarkConfig,
) -> anyhow::Result<(PhaseResult, PhaseResult)> {
    let before = metrics::capture_snapshot(pool).await?;
    let deadline = Instant::now() + Duration::from_secs(config.duration_secs);
    let version_counter = Arc::new(AtomicI64::new(100_000_000));
    let write_errors = Arc::new(AtomicU64::new(0));
    let read_errors = Arc::new(AtomicU64::new(0));

    let mut write_handles = Vec::with_capacity(config.concurrency);
    let mut read_handles = Vec::with_capacity(config.concurrency);

    // Spawn writer tasks (merge workload with weighted team selection).
    for task_id in 0..config.concurrency {
        let storage = PostgresStorage::new(pool.clone());
        let distinct_ids = data.distinct_ids.clone();
        let team_indices = data.team_person_indices.clone();
        let team_cdf = data.team_cdf.clone();
        let version_counter = version_counter.clone();
        let write_errors = write_errors.clone();

        write_handles.push(tokio::spawn(async move {
            let mut latencies = Vec::with_capacity(10_000);
            let mut rng = StdRng::seed_from_u64(5000 + task_id as u64);

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
                        write_errors.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            latencies
        }));
    }

    // Spawn reader tasks (the production GIN-indexed lookup).
    for task_id in 0..config.concurrency {
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
                     WHERE team_id = $1 AND $2 = ANY(distinct_ids) \
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

    Ok((write_result, read_result))
}
