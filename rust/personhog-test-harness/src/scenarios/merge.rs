//! The merge lane: MergePersons calls against random pairs of live
//! persons while the blast writers and probers keep writing to both.
//!
//! Every pair is two distinct live persons. Thus every call that settles
//! as `merged` ran the durable saga end to end (fence, seal, fold, flip,
//! release) with writes racing the source's fence and the target's fold.
//! A source distinct id is reserved for one in-flight call and is never
//! reused after a merge, so the journal always knows which person died.
//! Targets are shared, so two calls can contend for one person and
//! exercise the saga's conflict settlements.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use personhog_proto::personhog::identity::v1::MergeSourceOutcome;
use personhog_proto::personhog::types::v1::ConsistencyLevel;
use rand::{Rng, SeedableRng};
use serde_json::json;
use sqlx::postgres::PgPool;
use sqlx::Row;
use tokio::time::{interval, sleep, MissedTickBehavior};

use crate::client::{HarnessClient, IdentityClient};
use crate::pool::TargetPool;
use crate::report::ConsistencyViolation;
use crate::scenarios::blast::{is_not_found, per_worker_tick};
use crate::state::PersonState;
use crate::stats::StatsCollector;

/// Attempts per merge call under one op id. A retry under the same op id
/// returns the recorded outcome, so a lost response is asked again, not
/// guessed at.
const MERGE_ATTEMPTS: u32 = 3;
const MERGE_RETRY_BACKOFF: Duration = Duration::from_millis(500);

pub struct MergeLane {
    pub team_id: i64,
    pub concurrency: usize,
    /// Combined target rate across the workers. Unset runs flat out.
    pub rate_per_sec: Option<f64>,
    pub allow_identified_sources: bool,
    pub move_limit: i64,
    /// Persons created with many distinct ids. Workers prefer a wide
    /// pair while one is available, so the expensive merges happen
    /// before the pool thins. Their latency is recorded apart.
    pub wide_persons: Vec<i64>,
    pub wide_role: WideRole,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum WideRole {
    Source,
    Target,
    Both,
}

impl WideRole {
    pub fn parse(role: &str) -> Option<Self> {
        match role {
            "source" => Some(Self::Source),
            "target" => Some(Self::Target),
            "both" => Some(Self::Both),
            _ => None,
        }
    }
}

/// A merge call whose every attempt lost its response. The saga may have
/// run anyway. The op record decides, see [`settle_unresolved`].
pub struct UnresolvedMerge {
    pub op_id: uuid::Uuid,
    pub source: i64,
    /// The merge event's `$set` key and value. Journaled on the survivor
    /// if the op record says the merge ran.
    pub key: String,
    pub value: serde_json::Value,
}

pub struct MergeLaneResult {
    pub violations: Vec<ConsistencyViolation>,
    pub unresolved: Vec<UnresolvedMerge>,
}

/// Drive merges until the deadline. Every `merged` ack is journaled into
/// `state` and the destroyed source leaves `pool`. Returns the violations
/// observed live: a survivor without the merge's own write, a merged
/// source that still reads as alive, or an ack with no survivor.
#[allow(clippy::too_many_arguments)]
pub async fn run_merges(
    identity: &IdentityClient,
    router: &HarnessClient,
    lane: MergeLane,
    pool: Arc<TargetPool>,
    distinct_ids: Arc<HashMap<i64, String>>,
    duration: Duration,
    collector: &Arc<StatsCollector>,
    state: &PersonState,
    stop: Arc<AtomicBool>,
) -> Result<MergeLaneResult> {
    let deadline = Instant::now() + duration;
    let worker_tick = lane
        .rate_per_sec
        .map(|rate| per_worker_tick(rate, lane.concurrency));
    let wide: Arc<std::collections::HashSet<i64>> =
        Arc::new(lane.wide_persons.iter().copied().collect());
    // The eligible set excludes the wide persons so an ordinary pair
    // cannot spend a wide source.
    let eligible = Arc::new(Mutex::new(
        pool.snapshot()
            .into_iter()
            .filter(|id| !wide.contains(id))
            .collect::<Vec<_>>(),
    ));
    let wide_sources = Arc::new(Mutex::new(match lane.wide_role {
        WideRole::Source | WideRole::Both => lane.wide_persons.clone(),
        WideRole::Target => Vec::new(),
    }));
    let wide_targets: Arc<Vec<i64>> = Arc::new(match lane.wide_role {
        WideRole::Target | WideRole::Both => lane.wide_persons.clone(),
        WideRole::Source => Vec::new(),
    });
    let dry_at: Arc<Mutex<Option<Duration>>> = Arc::new(Mutex::new(None));
    let started = Instant::now();

    let mut handles = Vec::new();
    for _ in 0..lane.concurrency {
        let identity = identity.clone();
        let router = router.clone();
        let pool = pool.clone();
        let distinct_ids = distinct_ids.clone();
        let eligible = eligible.clone();
        let wide = wide.clone();
        let wide_sources = wide_sources.clone();
        let wide_targets = wide_targets.clone();
        let dry_at = dry_at.clone();
        let collector = collector.clone();
        let state = state.clone();
        let stop = stop.clone();
        let (team_id, allow_identified_sources, move_limit) =
            (lane.team_id, lane.allow_identified_sources, lane.move_limit);

        handles.push(tokio::spawn(async move {
            let mut rng = rand::rngs::StdRng::from_entropy();
            let mut pacer = worker_tick.map(|tick| {
                let mut ticker = interval(tick);
                ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
                ticker
            });
            let mut violations = Vec::new();
            let mut unresolved = Vec::new();

            while Instant::now() < deadline && !stop.load(Ordering::Relaxed) {
                if let Some(pacer) = pacer.as_mut() {
                    pacer.tick().await;
                }
                let picked =
                    pick_wide_pair(&wide_sources, &wide_targets, &eligible, &pool, &mut rng)
                        .or_else(|| pick_pair(&eligible, &pool, &mut rng));
                let Some((source, target)) = picked else {
                    // Fewer than two live persons remain, or every
                    // source is reserved.
                    if pool.len() < 2 {
                        note_dry(&dry_at, started.elapsed());
                    }
                    sleep(Duration::from_millis(200)).await;
                    continue;
                };
                let (Some(source_did), Some(target_did)) =
                    (distinct_ids.get(&source), distinct_ids.get(&target))
                else {
                    unreachable!("every pooled person was created with a distinct id");
                };

                state.mark_merge_pending(source).await;
                let op_id = uuid::Uuid::new_v4();
                let key = format!("harness_merge_{op_id}");
                let value = serde_json::Value::String(op_id.to_string());

                let start = Instant::now();
                let mut attempt = 0;
                let response = loop {
                    attempt += 1;
                    let result = identity
                        .merge_persons(
                            team_id,
                            target_did,
                            std::slice::from_ref(source_did),
                            json!({ &key: &value }),
                            &op_id,
                            allow_identified_sources,
                            move_limit,
                        )
                        .await;
                    match result {
                        Ok(response) => break Some(response),
                        Err(e) if attempt < MERGE_ATTEMPTS => {
                            tracing::warn!(
                                source,
                                target,
                                attempt,
                                error = format!("{e:#}"),
                                "merge call failed; retrying under the same op id"
                            );
                            sleep(MERGE_RETRY_BACKOFF).await;
                        }
                        Err(e) => {
                            tracing::warn!(
                                source,
                                target,
                                error = format!("{e:#}"),
                                "merge call failed on every attempt; source outcome unknown"
                            );
                            break None;
                        }
                    }
                };

                let recorder = if wide.contains(&source) || wide.contains(&target) {
                    &collector.wide_merges
                } else {
                    &collector.merges
                };
                let Some(response) = response else {
                    recorder.record_failure();
                    // The saga is durable, and the sweeper re-drives
                    // abandoned ops. The call can still destroy the
                    // source after this failure. The op record settles
                    // it after traffic. Until then the source stays
                    // reserved and takes no more traffic.
                    state.record_merge_uncertain(source).await;
                    pool.remove(source);
                    unresolved.push(UnresolvedMerge {
                        op_id,
                        source,
                        key,
                        value,
                    });
                    continue;
                };
                recorder.record_success(start.elapsed());

                let source_outcome = response
                    .results
                    .iter()
                    .find(|r| r.source_distinct_id == *source_did)
                    .map(|r| r.outcome())
                    .unwrap_or(MergeSourceOutcome::Unspecified);
                collector.record_merge_outcome(outcome_name(source_outcome));

                if source_outcome != MergeSourceOutcome::Merged {
                    // Every outcome except merged leaves the source alive.
                    state.clear_merge_pending(source).await;
                    if wide.contains(&source) {
                        wide_sources.lock().unwrap().push(source);
                    } else {
                        eligible.lock().unwrap().push(source);
                    }
                    continue;
                }

                let Some(survivor) = response.survivor else {
                    violations.push(ConsistencyViolation {
                        person_id: source,
                        key: "__merge_ack_missing_survivor".to_string(),
                        expected: json!("a merged ack carries the survivor document"),
                        actual: serde_json::Value::Null,
                    });
                    // The source is destroyed but the survivor is
                    // unknown. Keep the reservation so reads tolerate
                    // its absence, and stop asserting on it.
                    state.record_merge_uncertain(source).await;
                    pool.remove(source);
                    continue;
                };
                let survivor_props: serde_json::Value =
                    serde_json::from_slice(&survivor.properties).unwrap_or_else(|_| json!({}));
                if survivor_props.get(&key) != Some(&value) {
                    // The fold applies the merge event's $set last. The
                    // folded document in the ack must already carry it.
                    violations.push(ConsistencyViolation {
                        person_id: survivor.id,
                        key: key.clone(),
                        expected: value.clone(),
                        actual: survivor_props
                            .get(&key)
                            .cloned()
                            .unwrap_or(serde_json::Value::Null),
                    });
                }
                state
                    .record_merge(
                        source,
                        survivor.id,
                        survivor.version,
                        HashMap::from([(key, value)]),
                    )
                    .await;
                pool.remove(source);

                // Read-your-merge check. The release produced the
                // source's death document before the saga completed. A
                // strong read served now must not find a living person.
                let read_start = Instant::now();
                match router
                    .get_person(team_id, source, ConsistencyLevel::Strong)
                    .await
                {
                    Ok(Some(person)) if !person.is_deleted => {
                        collector.reads.record_success(read_start.elapsed());
                        violations.push(ConsistencyViolation {
                            person_id: source,
                            key: "__merged_source_alive".to_string(),
                            expected: json!("not found after the merge ack"),
                            actual: json!({ "version": person.version }),
                        });
                    }
                    Ok(_) => collector.reads.record_success(read_start.elapsed()),
                    Err(e) if is_not_found(&e) => {
                        collector.reads.record_success(read_start.elapsed())
                    }
                    Err(e) => {
                        // Readability is end-of-run verification's job.
                        collector.reads.record_failure();
                        tracing::warn!(source, error = %e, "post-merge read failed");
                    }
                }
            }
            (violations, unresolved)
        }));
    }

    let mut violations = Vec::new();
    let mut unresolved = Vec::new();
    for handle in handles {
        let (worker_violations, worker_unresolved) =
            handle.await.context("merge worker panicked")?;
        violations.extend(worker_violations);
        unresolved.extend(worker_unresolved);
    }
    if let Some(at) = *dry_at.lock().unwrap() {
        println!(
            "Merge lane ran the pool dry {:.1}s into traffic; size --persons up or the rate down \
             for a longer merge window",
            at.as_secs_f64()
        );
    }
    Ok(MergeLaneResult {
        violations,
        unresolved,
    })
}

/// Settle every unresolved merge from the saga's own record. A
/// `completed` op with the source `merged` is journaled as the merge it
/// was. That is safe after later merges' acks, because the journal
/// orders folds by the recorded survivor version. An aborted op means
/// the source lived on. So does a missing op row, because the call
/// failed before the saga froze its request. An op still in flight is
/// polled until `deadline` elapses, which gives the sweeper time to
/// re-drive it. An op that never settles is a violation: no lifecycle
/// op can ever touch that person again.
pub async fn settle_unresolved(
    pool: &PgPool,
    state: &PersonState,
    unresolved: Vec<UnresolvedMerge>,
    deadline: Duration,
) -> Result<Vec<ConsistencyViolation>> {
    if unresolved.is_empty() {
        return Ok(Vec::new());
    }
    println!(
        "Settling {} merge calls that lost every response from the saga's op records...",
        unresolved.len()
    );
    let mut violations = Vec::new();
    let mut pending = unresolved;
    let started = Instant::now();
    loop {
        let mut still_pending = Vec::new();
        for merge in pending {
            let row = sqlx::query("SELECT step, outcome FROM lifecycle_op WHERE op_id = $1")
                .bind(merge.op_id)
                .fetch_optional(pool)
                .await
                .context("reading an unresolved merge op")?;
            let Some(row) = row else {
                // No op row means the saga never froze the request, so
                // nothing destructive started.
                state.clear_merge_pending(merge.source).await;
                continue;
            };
            let step: String = row.get("step");
            let outcome: Option<serde_json::Value> = row.get("outcome");
            match step.as_str() {
                "completed" => {
                    let outcome = outcome.unwrap_or_default();
                    let merged = outcome["results"]
                        .as_array()
                        .is_some_and(|results| results.iter().any(|r| r["outcome"] == "merged"));
                    let survivor = &outcome["survivor"];
                    match (
                        merged,
                        survivor["id"].as_i64(),
                        survivor["version"].as_i64(),
                    ) {
                        (true, Some(id), Some(version)) => {
                            state
                                .record_merge(
                                    merge.source,
                                    id,
                                    version,
                                    HashMap::from([(merge.key, merge.value)]),
                                )
                                .await;
                        }
                        (true, _, _) => violations.push(ConsistencyViolation {
                            person_id: merge.source,
                            key: "__merge_record_missing_survivor".to_string(),
                            expected: json!("a completed merge records its survivor"),
                            actual: outcome,
                        }),
                        (false, _, _) => state.clear_merge_pending(merge.source).await,
                    }
                }
                "aborted" => state.clear_merge_pending(merge.source).await,
                _ => still_pending.push(merge),
            }
        }
        if still_pending.is_empty() {
            return Ok(violations);
        }
        if started.elapsed() > deadline {
            for merge in still_pending {
                violations.push(ConsistencyViolation {
                    person_id: merge.source,
                    key: "__merge_unsettled".to_string(),
                    expected: json!(format!("op {} terminal within {deadline:?}", merge.op_id)),
                    actual: json!("in flight"),
                });
            }
            return Ok(violations);
        }
        sleep(Duration::from_secs(2)).await;
        pending = still_pending;
    }
}

/// A pair with a wide person on the configured side. None when no wide
/// source is left to reserve and no wide target is live. With wide
/// targets only, the source comes from the ordinary eligible set.
fn pick_wide_pair(
    wide_sources: &Mutex<Vec<i64>>,
    wide_targets: &[i64],
    eligible: &Mutex<Vec<i64>>,
    pool: &TargetPool,
    rng: &mut impl Rng,
) -> Option<(i64, i64)> {
    let live_wide_targets: Vec<i64> = wide_targets
        .iter()
        .copied()
        .filter(|id| pool.snapshot().contains(id))
        .collect();
    let source = {
        let mut wide_sources = wide_sources.lock().unwrap();
        if wide_sources.is_empty() {
            None
        } else {
            let index = rng.gen_range(0..wide_sources.len());
            Some(wide_sources.swap_remove(index))
        }
    };
    match source {
        Some(source) => {
            let target = if live_wide_targets.is_empty() {
                (0..16)
                    .filter_map(|_| pool.pick_random(rng))
                    .find(|&target| target != source)
            } else {
                live_wide_targets
                    .iter()
                    .copied()
                    .filter(|&target| target != source)
                    .nth(rng.gen_range(0..live_wide_targets.len().max(1)))
                    .or_else(|| live_wide_targets.iter().copied().find(|&t| t != source))
            };
            match target {
                Some(target) => Some((source, target)),
                None => {
                    wide_sources.lock().unwrap().push(source);
                    None
                }
            }
        }
        None if !live_wide_targets.is_empty() => {
            let target = live_wide_targets[rng.gen_range(0..live_wide_targets.len())];
            let mut eligible = eligible.lock().unwrap();
            let candidates: Vec<usize> = (0..eligible.len())
                .filter(|&i| eligible[i] != target)
                .collect();
            if candidates.is_empty() {
                return None;
            }
            let source = eligible.swap_remove(candidates[rng.gen_range(0..candidates.len())]);
            Some((source, target))
        }
        None => None,
    }
}

/// Reserve a random eligible source and pick a different live target.
/// None when fewer than two live persons remain or every source is
/// reserved.
fn pick_pair(
    eligible: &Mutex<Vec<i64>>,
    pool: &TargetPool,
    rng: &mut impl Rng,
) -> Option<(i64, i64)> {
    let mut eligible = eligible.lock().unwrap();
    if eligible.is_empty() || pool.len() < 2 {
        return None;
    }
    let index = rng.gen_range(0..eligible.len());
    let source = eligible.swap_remove(index);
    // The pool holds at least two persons, so a different target exists
    // and a few random draws almost always find one. A miss only puts
    // the source back.
    for _ in 0..16 {
        match pool.pick_random(rng) {
            Some(target) if target != source => return Some((source, target)),
            _ => {}
        }
    }
    eligible.push(source);
    None
}

fn note_dry(dry_at: &Mutex<Option<Duration>>, at: Duration) {
    let mut dry = dry_at.lock().unwrap();
    if dry.is_none() {
        *dry = Some(at);
    }
}

pub fn outcome_name(outcome: MergeSourceOutcome) -> &'static str {
    match outcome {
        MergeSourceOutcome::Merged => "merged",
        MergeSourceOutcome::NoopSamePerson => "noop_same_person",
        MergeSourceOutcome::Attached => "attached",
        MergeSourceOutcome::SkippedIllegal => "skipped_illegal",
        MergeSourceOutcome::SkippedAlreadyIdentified => "skipped_already_identified",
        MergeSourceOutcome::SkippedConflict => "skipped_conflict",
        MergeSourceOutcome::SkippedMoveLimit => "skipped_move_limit",
        MergeSourceOutcome::Error => "error",
        MergeSourceOutcome::Unspecified => "unspecified",
    }
}
