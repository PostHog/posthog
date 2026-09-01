//! The merge lane: MergePersons calls against live persons while the
//! blast writers and probers keep writing to them.
//!
//! Each call names one target and one or more live sources. A source
//! that settles as `merged` ran the durable saga end to end, with writes
//! racing its fence and the target's fold. A source is reserved for one
//! call at a time and is never reused after a merge, so the journal
//! always knows which person died. Targets are shared, so two calls can
//! contend for one person.

use std::collections::{HashMap, HashSet};
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
use crate::scenarios::gate::SEED_KEY;
use crate::state::{MergeAck, PersonState};
use crate::stats::StatsCollector;

/// Attempts per call, all under one op id. A retry with the same op id
/// returns the recorded outcome and does not merge again.
const MERGE_ATTEMPTS: u32 = 3;
const MERGE_RETRY_BACKOFF: Duration = Duration::from_millis(500);

/// The `$set_once` value sent for keys the survivor already holds. It
/// must never land.
const SET_ONCE_LOSER: &str = "harness_set_once_must_not_win";

pub struct MergeLane {
    pub team_id: i64,
    pub concurrency: usize,
    /// Combined target rate across the workers. Unset runs flat out.
    pub rate_per_sec: Option<f64>,
    /// Sources per call. Only a call with more than one source exercises
    /// the leader's request-order fold.
    pub sources_per_call: usize,
    pub allow_identified_sources: bool,
    pub move_limit: i64,
    /// Persons with many distinct ids. Workers prefer them while one is
    /// available, so the expensive merges happen before the pool thins.
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
    /// Person id and distinct id per source, in request order.
    pub sources: Vec<(i64, String)>,
    /// Journaled on the survivor if the op record says the merge ran.
    pub set: HashMap<String, serde_json::Value>,
    pub set_once: HashMap<String, serde_json::Value>,
}

pub struct MergeLaneResult {
    pub violations: Vec<ConsistencyViolation>,
    pub unresolved: Vec<UnresolvedMerge>,
}

/// The merge event's writes for one call. The three `$set_once` keys
/// test the fold: a fresh key it must fill, the `$set` key it must lose
/// to, and the seed key it must not change.
struct MergeEvent {
    set: HashMap<String, serde_json::Value>,
    set_once: HashMap<String, serde_json::Value>,
}

impl MergeEvent {
    fn new(op_id: &uuid::Uuid) -> Self {
        let op = json!(op_id.to_string());
        let loser = json!(SET_ONCE_LOSER);
        Self {
            set: HashMap::from([(format!("harness_merge_{op_id}"), op.clone())]),
            set_once: HashMap::from([
                (format!("harness_merge_once_{op_id}"), op),
                (format!("harness_merge_{op_id}"), loser.clone()),
                (SEED_KEY.to_string(), loser),
            ]),
        }
    }

    /// The keys and values the survivor must carry after the fold.
    fn expected(&self) -> impl Iterator<Item = (&String, &serde_json::Value)> {
        self.set.iter().chain(
            self.set_once
                .iter()
                .filter(|(_, value)| value.as_str() != Some(SET_ONCE_LOSER)),
        )
    }
}

/// Drive merges until the deadline. Merged acks go into `state`, and
/// merged sources leave `pool`. Returns the violations seen live.
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
    let wide: Arc<HashSet<i64>> = Arc::new(lane.wide_persons.iter().copied().collect());
    // An ordinary pick must not spend a wide source.
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
        let (team_id, allow_identified_sources, move_limit, sources_per_call) = (
            lane.team_id,
            lane.allow_identified_sources,
            lane.move_limit,
            lane.sources_per_call.max(1),
        );

        handles.push(tokio::spawn(async move {
            let mut rng = rand::rngs::StdRng::from_entropy();
            let mut pacer = worker_tick.map(|tick| {
                let mut ticker = interval(tick);
                ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
                ticker
            });
            let mut violations = Vec::new();
            let mut unresolved = Vec::new();
            let release = |source: i64| {
                if wide.contains(&source) {
                    wide_sources.lock().unwrap().push(source);
                } else {
                    eligible.lock().unwrap().push(source);
                }
            };

            while Instant::now() < deadline && !stop.load(Ordering::Relaxed) {
                if let Some(pacer) = pacer.as_mut() {
                    pacer.tick().await;
                }
                let picked =
                    pick_wide_pair(&wide_sources, &wide_targets, &eligible, &pool, &mut rng)
                        .or_else(|| pick_pair(&eligible, &pool, &mut rng));
                let Some((first_source, target)) = picked else {
                    // The pool is almost empty, or every source is
                    // reserved.
                    if pool.len() < 2 {
                        note_dry(&dry_at, started.elapsed());
                    }
                    sleep(Duration::from_millis(200)).await;
                    continue;
                };
                let mut sources = vec![first_source];
                reserve_more_sources(&eligible, &mut sources, target, sources_per_call, &mut rng);
                let Some(target_did) = distinct_ids.get(&target) else {
                    unreachable!("every pooled person was created with a distinct id");
                };
                let source_dids: Vec<String> = sources
                    .iter()
                    .map(|source| {
                        distinct_ids.get(source).cloned().unwrap_or_else(|| {
                            unreachable!("every pooled person was created with a distinct id")
                        })
                    })
                    .collect();

                for &source in &sources {
                    state.mark_merge_pending(source).await;
                }
                let op_id = uuid::Uuid::new_v4();
                let event = MergeEvent::new(&op_id);

                let start = Instant::now();
                let mut attempt = 0;
                let response = loop {
                    attempt += 1;
                    let result = identity
                        .merge_persons(
                            team_id,
                            target_did,
                            &source_dids,
                            json!(event.set),
                            json!(event.set_once),
                            &op_id,
                            allow_identified_sources,
                            move_limit,
                        )
                        .await;
                    match result {
                        Ok(response) => break Some(response),
                        Err(e) if attempt < MERGE_ATTEMPTS => {
                            tracing::warn!(
                                ?sources,
                                target,
                                attempt,
                                error = format!("{e:#}"),
                                "merge call failed; retrying under the same op id"
                            );
                            sleep(MERGE_RETRY_BACKOFF).await;
                        }
                        Err(e) => {
                            tracing::warn!(
                                ?sources,
                                target,
                                error = format!("{e:#}"),
                                "merge call failed on every attempt; source outcomes unknown"
                            );
                            break None;
                        }
                    }
                };

                let recorder = if wide.contains(&target) || sources.iter().any(|s| wide.contains(s))
                {
                    &collector.wide_merges
                } else {
                    &collector.merges
                };
                let Some(response) = response else {
                    recorder.record_failure();
                    // The saga can still destroy the sources after this
                    // failure. The op record settles them after traffic.
                    // Until then the sources stay reserved and take no
                    // traffic.
                    for &source in &sources {
                        state.record_merge_uncertain(source).await;
                        pool.remove(source);
                    }
                    unresolved.push(UnresolvedMerge {
                        op_id,
                        sources: sources.iter().copied().zip(source_dids).collect(),
                        set: event.set,
                        set_once: event.set_once,
                    });
                    continue;
                };
                recorder.record_success(start.elapsed());

                let mut merged = Vec::new();
                for (&source, source_did) in sources.iter().zip(&source_dids) {
                    let outcome = response
                        .results
                        .iter()
                        .find(|r| r.source_distinct_id == *source_did)
                        .map(|r| r.outcome())
                        .unwrap_or(MergeSourceOutcome::Unspecified);
                    collector.record_merge_outcome(outcome_name(outcome));
                    if outcome == MergeSourceOutcome::Merged {
                        merged.push(source);
                    } else {
                        // Every outcome except merged leaves the source alive.
                        state.clear_merge_pending(source).await;
                        release(source);
                    }
                }
                if merged.is_empty() {
                    continue;
                }

                let Some(survivor) = response.survivor else {
                    // The sources are destroyed, but the survivor is
                    // unknown. Keep them reserved, so reads tolerate
                    // their absence.
                    for &source in &merged {
                        violations.push(ConsistencyViolation {
                            person_id: source,
                            key: "__merge_ack_missing_survivor".to_string(),
                            expected: json!("a merged ack carries the survivor document"),
                            actual: serde_json::Value::Null,
                        });
                        state.record_merge_uncertain(source).await;
                        pool.remove(source);
                    }
                    continue;
                };
                let survivor_props: serde_json::Value =
                    serde_json::from_slice(&survivor.properties).unwrap_or_else(|_| json!({}));
                // The ack carries the folded document, so the merge
                // event's writes must already be in it.
                for (key, value) in event.expected() {
                    if survivor_props.get(key) != Some(value) {
                        violations.push(ConsistencyViolation {
                            person_id: survivor.id,
                            key: key.clone(),
                            expected: value.clone(),
                            actual: survivor_props
                                .get(key)
                                .cloned()
                                .unwrap_or(serde_json::Value::Null),
                        });
                    }
                }
                if survivor_props.get(SEED_KEY) == Some(&json!(SET_ONCE_LOSER)) {
                    violations.push(ConsistencyViolation {
                        person_id: survivor.id,
                        key: SEED_KEY.to_string(),
                        expected: json!(
                            "the value the fold carried; $set_once must not replace it"
                        ),
                        actual: json!(SET_ONCE_LOSER),
                    });
                }
                state
                    .record_merge(MergeAck {
                        survivor: survivor.id,
                        survivor_version: survivor.version,
                        sources: merged.clone(),
                        set: event.set,
                        set_once: event.set_once,
                    })
                    .await;
                for &source in &merged {
                    pool.remove(source);
                }

                // A strong read after the ack must not find a living
                // source.
                for &source in &merged {
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

/// Settle each unresolved merge from its op record. A `completed` op is
/// journaled as a merge with the sources the record says merged. An
/// aborted op, or a missing op row, means every source lived on. An op
/// still in flight is polled until `deadline`, which gives the sweeper
/// time to re-drive it. An op that never settles is a violation.
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
                // No op row means the saga never started.
                for (source, _) in &merge.sources {
                    state.clear_merge_pending(*source).await;
                }
                continue;
            };
            let step: String = row.get("step");
            let outcome: Option<serde_json::Value> = row.get("outcome");
            match step.as_str() {
                "completed" => {
                    let outcome = outcome.unwrap_or_default();
                    let merged_dids: HashSet<&str> = outcome["results"]
                        .as_array()
                        .map(|results| {
                            results
                                .iter()
                                .filter(|r| r["outcome"] == "merged")
                                .filter_map(|r| r["distinct_id"].as_str())
                                .collect()
                        })
                        .unwrap_or_default();
                    let mut merged = Vec::new();
                    for (source, did) in &merge.sources {
                        if merged_dids.contains(did.as_str()) {
                            merged.push(*source);
                        } else {
                            state.clear_merge_pending(*source).await;
                        }
                    }
                    if merged.is_empty() {
                        continue;
                    }
                    let survivor = &outcome["survivor"];
                    match (survivor["id"].as_i64(), survivor["version"].as_i64()) {
                        (Some(id), Some(version)) => {
                            state
                                .record_merge(MergeAck {
                                    survivor: id,
                                    survivor_version: version,
                                    sources: merged,
                                    set: merge.set,
                                    set_once: merge.set_once,
                                })
                                .await;
                        }
                        _ => {
                            for source in merged {
                                violations.push(ConsistencyViolation {
                                    person_id: source,
                                    key: "__merge_record_missing_survivor".to_string(),
                                    expected: json!("a completed merge records its survivor"),
                                    actual: outcome.clone(),
                                });
                            }
                        }
                    }
                }
                "aborted" => {
                    for (source, _) in &merge.sources {
                        state.clear_merge_pending(*source).await;
                    }
                }
                _ => still_pending.push(merge),
            }
        }
        if still_pending.is_empty() {
            return Ok(violations);
        }
        if started.elapsed() > deadline {
            for merge in still_pending {
                for (source, _) in merge.sources {
                    violations.push(ConsistencyViolation {
                        person_id: source,
                        key: "__merge_unsettled".to_string(),
                        expected: json!(format!("op {} terminal within {deadline:?}", merge.op_id)),
                        actual: json!("in flight"),
                    });
                }
            }
            return Ok(violations);
        }
        sleep(Duration::from_secs(2)).await;
        pending = still_pending;
    }
}

/// A pair with a wide person on the configured side. None when no wide
/// source is free and no wide target is live.
fn pick_wide_pair(
    wide_sources: &Mutex<Vec<i64>>,
    wide_targets: &[i64],
    eligible: &Mutex<Vec<i64>>,
    pool: &TargetPool,
    rng: &mut impl Rng,
) -> Option<(i64, i64)> {
    let live = pool.snapshot();
    let live_wide_targets: Vec<i64> = wide_targets
        .iter()
        .copied()
        .filter(|id| live.contains(id))
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
    // A few random draws almost always find a different target. A miss
    // puts the source back.
    for _ in 0..16 {
        match pool.pick_random(rng) {
            Some(target) if target != source => return Some((source, target)),
            _ => {}
        }
    }
    eligible.push(source);
    None
}

/// Reserve ordinary sources until the call carries `wanted`, or the
/// eligible set runs out. The target is never a source of its own call.
fn reserve_more_sources(
    eligible: &Mutex<Vec<i64>>,
    sources: &mut Vec<i64>,
    target: i64,
    wanted: usize,
    rng: &mut impl Rng,
) {
    let mut eligible = eligible.lock().unwrap();
    while sources.len() < wanted {
        let candidates: Vec<usize> = (0..eligible.len())
            .filter(|&i| eligible[i] != target)
            .collect();
        if candidates.is_empty() {
            return;
        }
        let source = eligible.swap_remove(candidates[rng.gen_range(0..candidates.len())]);
        sources.push(source);
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    /// The target is never one of its own sources, and each source
    /// leaves the eligible set exactly once.
    #[test]
    fn extra_sources_are_reserved_apart_from_the_target() {
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        let eligible = Mutex::new(vec![2, 3, 4]);
        let mut sources = vec![1];
        reserve_more_sources(&eligible, &mut sources, 3, 3, &mut rng);
        sources.sort_unstable();
        assert_eq!(sources, vec![1, 2, 4]);
        assert_eq!(*eligible.lock().unwrap(), vec![3]);

        // An empty eligible set caps the call. The target stays.
        reserve_more_sources(&eligible, &mut sources, 3, 10, &mut rng);
        assert_eq!(sources.len(), 3);
        assert_eq!(*eligible.lock().unwrap(), vec![3]);
    }
}
