//! Shadow-compare support for the `flags-cache-builder` consumer.
//!
//! A `shadow: true` invalidation asks the builder to prove parity, not to serve:
//! build the payload exactly as a real invalidation would, diff it against the
//! live cache entry Python (Celery) owns, and record the result — never write.
//! This module holds the semantic diff and the repeat-offender suppression. The
//! diff is pure; the suppression keeps its pending state in the flags Redis
//! tier, because it has to outlive the process. Reading the live entry and
//! emitting metrics stay in the binary.
//!
//! The diff covers all three top-level payload keys, because all three feed the
//! serve path (`flag_definitions_cache.rs` evaluates from `flags`,
//! `evaluation_metadata`, and `cohorts` as cached, with no read-time repair):
//!
//! - `flags`: per-flag comparison mirroring the Python verifier's definition of
//!   parity (`verify_team_flags` in `products/feature_flags/backend/flags_cache.py`)
//!   — flag-set equality by id, field-level comparison, missing-in-cache and
//!   stale-in-cache detection, an unevaluable stale row tolerated, and `filters`
//!   exempted when both sides agree the flag is unevaluable (the writers blank
//!   those; entries predating blanking still hold the full blob).
//! - `evaluation_metadata`: full value comparison, not just the presence check
//!   the Python verifier does. That verifier compares Python-written state
//!   against a Python DB read, so its metadata can't disagree with itself; here
//!   the Rust reimplementation of dependency staging is exactly what's under test.
//! - `cohorts`: per-cohort comparison by id, for the same reason — the Rust
//!   cohort BFS is a reimplementation that can truncate or diverge, and the
//!   serve path evaluates cohort-filtered flags from this cached array. A live
//!   entry with no `cohorts` key predates the field and is skipped, since the
//!   service falls back to its own cohort load for such entries.
//!
//! Parity is per team, not per byte: both sides are deserialized through the
//! same typed models before comparing, so JSON key order, absent-vs-null
//! optional fields, and serialization formatting can never register as
//! mismatches. Unlike the Python verifier's "compare only DB-side keys" rule
//! (which tolerates stale extra keys in raw cache JSON — the typed round-trip
//! already drops those), the field loop here walks the union of both sides'
//! keys: the typed model omits `None` fields on serialize, so a built-side
//! `None` against a cached value would otherwise be invisible.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use common_redis::{Client, CustomRedisError};
use common_types::TeamId;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::cohorts::cohort_models::Cohort;
use crate::flags::cache_builder::is_evaluable;
use crate::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagId, HypercacheFlagsWrapper,
};

/// The slice of a live cache entry the shadow diff reads. Deserialized leniently
/// (unknown fields are ignored; `evaluation_metadata` and `cohorts` may be
/// absent in entries predating them) so an old-shape entry surfaces as a
/// semantic mismatch or a skip below rather than a parse failure.
#[derive(Debug, Deserialize)]
pub struct ShadowLiveEntry {
    #[serde(default)]
    pub flags: Vec<FeatureFlag>,
    #[serde(default)]
    pub evaluation_metadata: Option<EvaluationMetadata>,
    #[serde(default)]
    pub cohorts: Option<Vec<Cohort>>,
}

/// One issue class per diff entry; used as the `issue_type` metric label, so the
/// set must stay small and static.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShadowIssueType {
    /// Live entry has no `evaluation_metadata` key (pre-metadata entry shape).
    MissingEvaluationMetadata,
    /// Live entry's `evaluation_metadata` value differs from the fresh build's.
    EvaluationMetadataMismatch,
    /// Flag present in the fresh build but absent from the live entry.
    MissingInCache,
    /// Evaluable flag present in the live entry but absent from the fresh build.
    StaleInCache,
    /// Flag present on both sides with differing field values.
    FieldMismatch,
    /// Cohort present in the fresh build but absent from the live entry.
    CohortMissingInCache,
    /// Cohort present in the live entry but absent from the fresh build.
    CohortStaleInCache,
    /// Cohort present on both sides with differing field values.
    CohortFieldMismatch,
}

impl ShadowIssueType {
    pub fn as_label(&self) -> &'static str {
        match self {
            Self::MissingEvaluationMetadata => "missing_evaluation_metadata",
            Self::EvaluationMetadataMismatch => "evaluation_metadata_mismatch",
            Self::MissingInCache => "missing_in_cache",
            Self::StaleInCache => "stale_in_cache",
            Self::FieldMismatch => "field_mismatch",
            Self::CohortMissingInCache => "cohort_missing_in_cache",
            Self::CohortStaleInCache => "cohort_stale_in_cache",
            Self::CohortFieldMismatch => "cohort_field_mismatch",
        }
    }
}

/// One semantic difference between the fresh build and the live entry.
#[derive(Debug, Clone)]
pub struct ShadowDiff {
    pub issue_type: ShadowIssueType,
    /// What differs: `"flag 42 (checkout)"` or `"cohort 7"`. `None` for
    /// team-level issues (the evaluation-metadata ones).
    pub subject: Option<String>,
    /// Differing field names; populated for the field-mismatch issue types.
    pub fields: Vec<String>,
    /// Content hash of the disagreement, used by `MismatchTracker` to decide
    /// whether the *same* mismatch persisted across two consecutive shadow
    /// builds. Hashing the values (not just the subject + issue type) keeps an
    /// edit session — where each save races Python's rebuild with *different*
    /// content — from ever counting as a repeat.
    fingerprint: u64,
}

/// Truncated SHA-256 rather than `DefaultHasher`, because the value is written
/// to Redis and compared by a later process, which can be a different build of
/// this binary. The standard library does not promise `DefaultHasher` gives the
/// same output across Rust versions, so a toolchain bump would change every
/// fingerprint and demote each team's pending mismatch to a first sighting for
/// one build after the deploy. SHA-256 of the same input is the same value in
/// every build, which is what a persisted comparison needs.
///
/// 64 bits of the digest is enough, because a collision would have to be two
/// different disagreements for the same team inside the TTL.
fn fingerprint(
    issue_type: ShadowIssueType,
    subject: Option<&str>,
    built: Option<&serde_json::Value>,
    cached: Option<&serde_json::Value>,
) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(issue_type.as_label().as_bytes());
    for part in [
        subject.map(|s| s.to_string()),
        built.map(|v| v.to_string()),
        cached.map(|v| v.to_string()),
    ] {
        // The marker byte separates the parts and tells an absent part from an
        // empty one. It is not an escape: `subject` is a formatted string that
        // carries whatever bytes a flag key carries, so a part can contain a
        // marker byte and the encoding is not self-delimiting. The part count is
        // fixed at three, which is what keeps distinct disagreements apart in
        // practice. A collision would need a contrived flag key, and would cost
        // one wrongly paired confirmation for one team.
        match part {
            Some(part) => {
                hasher.update([0x01]);
                hasher.update(part.as_bytes());
            }
            None => hasher.update([0x00]),
        }
    }
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[..8].try_into().expect("SHA-256 digest is 32 bytes"))
}

fn diff(
    issue_type: ShadowIssueType,
    subject: String,
    built: Option<&serde_json::Value>,
    cached: Option<&serde_json::Value>,
    fields: Vec<String>,
) -> ShadowDiff {
    ShadowDiff {
        issue_type,
        fingerprint: fingerprint(issue_type, Some(&subject), built, cached),
        subject: Some(subject),
        fields,
    }
}

/// Field names whose values differ between two serialized objects, over the
/// union of both sides' keys (see the module doc for why the union), skipping
/// `skip_key` when given. Sorted for deterministic logs and fingerprints.
fn differing_fields(
    built: &serde_json::Value,
    cached: &serde_json::Value,
    skip_key: Option<&str>,
) -> Vec<String> {
    let (Some(built_map), Some(cached_map)) = (built.as_object(), cached.as_object()) else {
        return Vec::new();
    };
    let mut fields: Vec<String> = built_map
        .keys()
        .chain(cached_map.keys().filter(|k| !built_map.contains_key(*k)))
        .filter(|key| Some(key.as_str()) != skip_key)
        .filter(|key| built_map.get(*key) != cached_map.get(*key))
        .cloned()
        .collect();
    fields.sort_unstable();
    fields
}

/// Semantically diff a fresh build against the live cache entry. Empty result
/// means parity across all three payload keys.
pub fn diff_live_entry(built: &HypercacheFlagsWrapper, live: &ShadowLiveEntry) -> Vec<ShadowDiff> {
    // Mirrors the Python verifier's MISSING_EVALUATION_METADATA early return:
    // an entry that old predates the current payload shape, so a per-flag diff
    // would only bury the actual finding.
    let Some(live_metadata) = &live.evaluation_metadata else {
        return vec![ShadowDiff {
            issue_type: ShadowIssueType::MissingEvaluationMetadata,
            subject: None,
            fields: Vec::new(),
            fingerprint: fingerprint(ShadowIssueType::MissingEvaluationMetadata, None, None, None),
        }];
    };

    let mut diffs: Vec<ShadowDiff> = Vec::new();

    if *live_metadata != built.evaluation_metadata {
        let built_value = serde_json::to_value(&built.evaluation_metadata).unwrap_or_default();
        let cached_value = serde_json::to_value(live_metadata).unwrap_or_default();
        diffs.push(ShadowDiff {
            issue_type: ShadowIssueType::EvaluationMetadataMismatch,
            subject: None,
            fields: differing_fields(&built_value, &cached_value, None),
            fingerprint: fingerprint(
                ShadowIssueType::EvaluationMetadataMismatch,
                None,
                Some(&built_value),
                Some(&cached_value),
            ),
        });
    }

    diffs.extend(diff_flags(&built.flags, &live.flags));

    // A live entry without the `cohorts` key predates the field; the service
    // falls back to its own cohort load for such entries, so there is nothing
    // wrong being served from it and nothing to compare.
    if let Some(live_cohorts) = &live.cohorts {
        let built_cohorts = built.cohorts.as_deref().unwrap_or(&[]);
        diffs.extend(diff_cohorts(built_cohorts, live_cohorts));
    }

    diffs
}

fn diff_flags(built: &[FeatureFlag], live: &[FeatureFlag]) -> Vec<ShadowDiff> {
    let built_by_id: HashMap<FeatureFlagId, &FeatureFlag> =
        built.iter().map(|f| (f.id, f)).collect();
    let cached_by_id: HashMap<FeatureFlagId, &FeatureFlag> =
        live.iter().map(|f| (f.id, f)).collect();

    let mut diffs: Vec<(FeatureFlagId, ShadowDiff)> = Vec::new();

    for flag in built {
        let subject = format!("flag {} ({})", flag.id, flag.key);
        match cached_by_id.get(&flag.id) {
            None => {
                let built_value = serde_json::to_value(flag).unwrap_or_default();
                diffs.push((
                    flag.id,
                    diff(
                        ShadowIssueType::MissingInCache,
                        subject,
                        Some(&built_value),
                        None,
                        Vec::new(),
                    ),
                ));
            }
            Some(cached) => {
                if let Some(d) = compare_flag_fields(flag, cached) {
                    diffs.push((flag.id, d));
                }
            }
        }
    }

    for flag in live {
        if built_by_id.contains_key(&flag.id) {
            continue;
        }
        // An unevaluable cached row is invisible to the matcher, so its
        // presence is not drift — same tolerance as the Python verifier.
        if !is_evaluable(flag) {
            continue;
        }
        let cached_value = serde_json::to_value(flag).unwrap_or_default();
        diffs.push((
            flag.id,
            diff(
                ShadowIssueType::StaleInCache,
                format!("flag {} ({})", flag.id, flag.key),
                None,
                Some(&cached_value),
                Vec::new(),
            ),
        ));
    }

    diffs.sort_by_key(|(id, _)| *id);
    diffs.into_iter().map(|(_, d)| d).collect()
}

/// Field-level comparison of one flag present on both sides. `filters` is
/// exempt when both sides agree the flag is unevaluable — only the cache
/// writers blank filters, and entries predating blanking still hold the full
/// blob the matcher never reads.
fn compare_flag_fields(built: &FeatureFlag, cached: &FeatureFlag) -> Option<ShadowDiff> {
    let built_value = serde_json::to_value(built).unwrap_or_default();
    let cached_value = serde_json::to_value(cached).unwrap_or_default();
    let both_unevaluable = !is_evaluable(built) && !is_evaluable(cached);
    let skip = both_unevaluable.then_some("filters");

    let fields = differing_fields(&built_value, &cached_value, skip);
    if fields.is_empty() {
        return None;
    }
    Some(diff(
        ShadowIssueType::FieldMismatch,
        format!("flag {} ({})", built.id, built.key),
        Some(&built_value),
        Some(&cached_value),
        fields,
    ))
}

/// Per-cohort comparison by id, order-insensitive (the Rust builder sorts by
/// id; Python appends in load order). No unevaluable tolerance: both writers
/// emit exactly the referenced set, so any set or field difference is drift.
fn diff_cohorts(built: &[Cohort], live: &[Cohort]) -> Vec<ShadowDiff> {
    let built_by_id: HashMap<i32, &Cohort> = built.iter().map(|c| (c.id, c)).collect();
    let cached_by_id: HashMap<i32, &Cohort> = live.iter().map(|c| (c.id, c)).collect();

    let mut diffs: Vec<(i32, ShadowDiff)> = Vec::new();

    for cohort in built {
        let subject = format!("cohort {}", cohort.id);
        match cached_by_id.get(&cohort.id) {
            None => {
                let built_value = serde_json::to_value(cohort).unwrap_or_default();
                diffs.push((
                    cohort.id,
                    diff(
                        ShadowIssueType::CohortMissingInCache,
                        subject,
                        Some(&built_value),
                        None,
                        Vec::new(),
                    ),
                ));
            }
            Some(cached) => {
                let built_value = serde_json::to_value(cohort).unwrap_or_default();
                let cached_value = serde_json::to_value(cached).unwrap_or_default();
                let fields = differing_fields(&built_value, &cached_value, None);
                if !fields.is_empty() {
                    diffs.push((
                        cohort.id,
                        diff(
                            ShadowIssueType::CohortFieldMismatch,
                            subject,
                            Some(&built_value),
                            Some(&cached_value),
                            fields,
                        ),
                    ));
                }
            }
        }
    }

    for cohort in live {
        if built_by_id.contains_key(&cohort.id) {
            continue;
        }
        let cached_value = serde_json::to_value(cohort).unwrap_or_default();
        diffs.push((
            cohort.id,
            diff(
                ShadowIssueType::CohortStaleInCache,
                format!("cohort {}", cohort.id),
                None,
                Some(&cached_value),
                Vec::new(),
            ),
        ));
    }

    diffs.sort_by_key(|(id, _)| *id);
    diffs.into_iter().map(|(_, d)| d).collect()
}

/// The tracker's judgement on one shadow build's diffs: which mismatches were
/// also present (same fingerprint) on the team's previous shadow build — those
/// count — and which are first sightings, suppressed as probable races against
/// Python's own rebuild of the team.
#[derive(Debug, Default)]
pub struct ShadowObservation {
    pub confirmed: Vec<ShadowDiff>,
    pub first_sight: Vec<ShadowDiff>,
    /// Tracker store accesses that failed while this observation was made. The
    /// caller counts them. They never move a diff into `confirmed`.
    pub store_errors: Vec<TrackerStoreOp>,
}

impl ShadowObservation {
    pub fn is_match(&self) -> bool {
        self.confirmed.is_empty() && self.first_sight.is_empty()
    }
}

/// Which tracker store access failed. Used as a metric label, so the set must
/// stay small and static.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrackerStoreOp {
    /// Read of the team's previous observation. The build falls back to first
    /// sight, so confirmations are lost while reads fail.
    Read,
    /// Write of this observation. The previous observation is cleared in its place,
    /// so the team's next shadow build finds nothing to compare against and also
    /// reports first sight.
    Write,
    /// Clear of the team's pending state, either after a clean build or in place of
    /// a write that failed.
    Clear,
}

impl TrackerStoreOp {
    pub fn as_label(&self) -> &'static str {
        match self {
            Self::Read => "read",
            Self::Write => "write",
            Self::Clear => "clear",
        }
    }
}

/// Redis key for a team's pending mismatch. The `posthog:1:` prefix is how
/// django-redis addresses keys in this tier (see `warm_run_status`). The
/// `feature_flags/shadow_mismatch/` path keeps these keys clear of the cache
/// entries the serve path reads, which are
/// `posthog:1:cache/teams/{team}/feature_flags/flags.json` (see
/// `HYPERCACHE_NAMESPACE` and `HYPERCACHE_OBJECT_NAME` in `cache_writer`): those
/// hold `cache/` in the segment where these hold `feature_flags/`, and Python's
/// hypercache scans match on the `cache/` form.
fn pending_key(team_id: TeamId) -> String {
    format!("posthog:1:feature_flags/shadow_mismatch/{team_id}")
}

/// Cap on one tracker Redis call. `common_hypercache` puts the same bound around
/// its own Redis access, and the tracker needs it for the same reason: a shadow
/// team that waits on Redis delays the real invalidations in the batches behind
/// it. The client's own response timeout cannot carry this, because it is
/// configurable and `FLAGS_REDIS_RESPONSE_TIMEOUT_MS=0` disables it entirely.
const STORE_TIMEOUT: Duration = Duration::from_millis(500);

/// Cap on the fingerprints stored for one team. The state shadow mode exists to
/// find is a systematic builder bug, which makes every flag on every team
/// disagree at once, and the whole set would then be written, held for the TTL,
/// and read back on the team's next build, against the Redis tier the serve path
/// reads from. Past the cap a team confirms only the disagreements that fit, which
/// is the right trade: a team with hundreds of confirmed diffs has already told
/// you what you needed to know. The confirmed log line is capped for the same
/// reason.
///
/// The cap takes the first entries of `diff_live_entry`'s stable order, so a given
/// disagreement either fits on every build or on none, which makes its
/// confirmation deterministic. An unstable subset would leave the aggregate
/// confirmed count about the same, because the next build compares every diff it
/// finds against whatever was stored, but a specific flag would then confirm on
/// some builds and not others.
const MAX_STORED_FINGERPRINTS: usize = 256;

/// Bound one tracker call and report an elapsed timer as the client's own timeout
/// error, so callers have a single error type to handle.
async fn with_timeout<T>(
    call: impl std::future::Future<Output = Result<T, CustomRedisError>>,
) -> Result<T, CustomRedisError> {
    match tokio::time::timeout(STORE_TIMEOUT, call).await {
        Ok(result) => result,
        Err(_elapsed) => Err(CustomRedisError::Timeout),
    }
}

/// Repeat-offender suppression: a mismatch counts only when the same fingerprint
/// shows up on two consecutive shadow builds of the team within `ttl`. A shadow
/// build races Python's own rebuild of the same team, so a single-shot mismatch
/// is expected noise; Python repairs the entry and the next shadow build of the
/// team comes back clean, clearing the pending state.
///
/// The pending state lives in the flags Redis tier rather than in the process,
/// because builder pods roll and Kafka partitions move between them far more
/// often than the TTL elapses. Process-local state made the real confirmation
/// window "as long as this pod lives", so a team that rebuilds less often than
/// that could never confirm, however wrong its cache entry was.
///
/// Expiry is the TTL on the Redis key. Nothing in this process sweeps or bounds
/// the pending set.
pub struct MismatchTracker {
    /// The same client the hypercache writer and reader use.
    redis: Arc<dyn Client + Send + Sync>,
    ttl: Duration,
}

impl MismatchTracker {
    pub fn new(redis: Arc<dyn Client + Send + Sync>, ttl: Duration) -> Self {
        Self { redis, ttl }
    }

    /// Fold one shadow build's diffs into the store and split them into
    /// confirmed (fingerprint also present in the team's previous, unexpired
    /// observation) and first-sight. An empty `diffs` clears the team's pending
    /// state.
    ///
    /// Store failures resolve towards first sight and none of them fail the shadow
    /// build: a mismatch we cannot prove is a repeat is reported as a first
    /// sighting, so an unreachable store loses confirmations rather than inventing
    /// them. The failures come back in `store_errors` to be counted.
    ///
    /// That fallback needs the team's stale pending state gone, and removing it is
    /// itself a store access that can fail. When a clean build's clear fails, or
    /// when a write and the clear that compensates for it both fail, the previous
    /// fingerprints stand until the TTL. A disagreement that then returns byte for
    /// byte can confirm one build early. The counter shows it: `op="clear"` alone,
    /// or `op="write"` together with `op="clear"`.
    pub async fn observe(&self, team_id: TeamId, diffs: Vec<ShadowDiff>) -> ShadowObservation {
        let key = pending_key(team_id);

        if diffs.is_empty() {
            return ShadowObservation {
                store_errors: self.clear_pending(team_id, key).await,
                ..ShadowObservation::default()
            };
        }

        let mut store_errors = Vec::new();
        let prior = match self.read_pending(key.clone()).await {
            Ok(prior) => prior,
            Err(e) => {
                tracing::warn!(team_id, error = %e, "Shadow mismatch tracker read failed; counting this build as a first sighting");
                store_errors.push(TrackerStoreOp::Read);
                HashSet::new()
            }
        };

        if let Err(e) = self.write_pending(key.clone(), &diffs).await {
            tracing::warn!(team_id, error = %e, "Shadow mismatch tracker write failed; clearing the team's pending state instead");
            store_errors.push(TrackerStoreOp::Write);
            // A failed SETEX leaves the previous build's fingerprints in place with
            // their own TTL, so the team's next build would compare against an
            // observation from two builds ago and could confirm a disagreement that
            // the build in between did not see. Clearing keeps the fallback at first
            // sight. Redis serves DEL when it refuses a write for `maxmemory`, which
            // is the case that produces this.
            store_errors.extend(self.clear_pending(team_id, key).await);
        }

        let (confirmed, first_sight) = diffs
            .into_iter()
            .partition(|d| prior.contains(&d.fingerprint));
        ShadowObservation {
            confirmed,
            first_sight,
            store_errors,
        }
    }

    /// Fingerprints from the team's previous shadow build. An absent key is how
    /// the TTL expires the window, so it reads as "no previous build" and not as
    /// an error. A value that does not parse is an error, because a stored shape
    /// this build cannot read is worth seeing on the failure counter.
    async fn read_pending(&self, key: String) -> Result<HashSet<u64>, CustomRedisError> {
        match with_timeout(self.redis.get(key)).await {
            Ok(raw) => {
                serde_json::from_str(&raw).map_err(|e| CustomRedisError::ParseError(e.to_string()))
            }
            Err(CustomRedisError::NotFound) => Ok(HashSet::new()),
            Err(e) => Err(e),
        }
    }

    async fn write_pending(
        &self,
        key: String,
        diffs: &[ShadowDiff],
    ) -> Result<(), CustomRedisError> {
        let fingerprints: Vec<u64> = diffs
            .iter()
            .take(MAX_STORED_FINGERPRINTS)
            .map(|d| d.fingerprint)
            .collect();
        let payload = serde_json::to_string(&fingerprints)
            .map_err(|e| CustomRedisError::ParseError(e.to_string()))?;
        with_timeout(self.redis.setex(key, payload, self.ttl.as_secs())).await
    }

    /// Drop the team's pending state, so the next mismatch starts over as a first
    /// sighting. Called after a clean build, and in place of a write that failed.
    ///
    /// A failed clear is the residual described on `observe`. It needs the same
    /// disagreement to come back byte for byte inside the TTL, and the fingerprint
    /// hashes the content, so that is a real recurrence rather than the rebuild
    /// race the suppression exists to filter.
    async fn clear_pending(&self, team_id: TeamId, key: String) -> Vec<TrackerStoreOp> {
        match with_timeout(self.redis.del(key)).await {
            Ok(()) => Vec::new(),
            Err(e) => {
                tracing::warn!(team_id, error = %e, "Shadow mismatch tracker clear failed; the team's pending state stands until it expires");
                vec![TrackerStoreOp::Clear]
            }
        }
    }
}

/// Render diffs for a log line, capped in entries and bytes: at full shadow
/// volume an unbounded dump of a large team's field diffs would swamp the
/// log pipeline.
pub fn summarize_diffs(diffs: &[ShadowDiff], max_entries: usize, max_bytes: usize) -> String {
    let mut out = String::new();
    let mut rendered = 0;
    for diff in diffs.iter().take(max_entries) {
        let label = diff.issue_type.as_label();
        let head = match &diff.subject {
            Some(subject) => format!("{subject}: {label}"),
            None => label.to_string(),
        };
        let entry = if diff.fields.is_empty() {
            head
        } else {
            format!("{head}[{}]", diff.fields.join(","))
        };
        let separator = if out.is_empty() { 0 } else { 2 };
        if out.len() + separator + entry.len() > max_bytes {
            break;
        }
        if !out.is_empty() {
            out.push_str("; ");
        }
        out.push_str(&entry);
        rendered += 1;
    }
    if rendered < diffs.len() {
        out.push_str(&format!("; +{} more", diffs.len() - rendered));
    }
    out
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use common_redis::{MockRedisCall, MockRedisClient, MockRedisValue};
    use serde_json::json;

    use super::*;

    fn flag_from_json(value: serde_json::Value) -> FeatureFlag {
        serde_json::from_value(value).expect("flag json must parse")
    }

    fn base_flag_json(id: i32) -> serde_json::Value {
        json!({
            "id": id,
            "team_id": 1,
            "key": format!("flag-{id}"),
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100.0}]},
            "active": true,
            "deleted": false,
            "has_experiment": false,
        })
    }

    fn base_cohort_json(id: i32) -> serde_json::Value {
        json!({
            "id": id,
            "team_id": 1,
            "name": format!("cohort-{id}"),
            "deleted": false,
            "filters": {"properties": {"type": "OR", "values": []}},
            "is_calculating": false,
            "is_static": false,
            "errors_calculating": 0,
            "groups": [],
        })
    }

    fn cohort_from_json(value: serde_json::Value) -> Cohort {
        serde_json::from_value(value).expect("cohort json must parse")
    }

    fn wrapper(flags: Vec<FeatureFlag>) -> HypercacheFlagsWrapper {
        HypercacheFlagsWrapper {
            flags,
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: Some(Vec::new()),
        }
    }

    fn live(flags: Vec<FeatureFlag>) -> ShadowLiveEntry {
        ShadowLiveEntry {
            flags,
            evaluation_metadata: Some(EvaluationMetadata::default()),
            cohorts: Some(Vec::new()),
        }
    }

    fn issue_types(diffs: &[ShadowDiff]) -> Vec<ShadowIssueType> {
        diffs.iter().map(|d| d.issue_type).collect()
    }

    #[test]
    fn identical_sides_match() {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let cached = live(vec![flag_from_json(base_flag_json(1))]);
        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn key_order_only_difference_is_a_match() {
        // Same content, keys in a different order and rollout as int vs float —
        // parity is semantic, not byte-for-byte.
        let built = wrapper(vec![flag_from_json(json!({
            "id": 1,
            "team_id": 1,
            "key": "flag-1",
            "active": true,
            "deleted": false,
            "has_experiment": false,
            "filters": {"groups": [{"rollout_percentage": 100.0, "properties": []}]},
        }))]);
        let cached: ShadowLiveEntry = serde_json::from_value(json!({
            "evaluation_metadata": {
                "dependency_stages": [],
                "flags_with_missing_deps": [],
                "transitive_deps": {},
            },
            "cohorts": [],
            "flags": [{
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "has_experiment": false,
                "deleted": false,
                "active": true,
                "key": "flag-1",
                "team_id": 1,
                "id": 1,
            }],
        }))
        .expect("live entry must parse");
        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn null_optional_field_matches_absent_field() {
        // Python's serializer can emit explicit nulls where the typed model
        // omits the key; both deserialize to None, so this must not be drift.
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["filters"]["payloads"] = serde_json::Value::Null;
        cached_json["evaluation_runtime"] = serde_json::Value::Null;
        let cached = live(vec![flag_from_json(cached_json)]);
        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn field_change_reports_field_mismatch_with_field_names() {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["filters"]["groups"][0]["rollout_percentage"] = json!(50.0);
        cached_json["has_experiment"] = json!(true);
        let cached = live(vec![flag_from_json(cached_json)]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(issue_types(&diffs), vec![ShadowIssueType::FieldMismatch]);
        assert_eq!(diffs[0].fields, vec!["filters", "has_experiment"]);
        assert_eq!(diffs[0].subject.as_deref(), Some("flag 1 (flag-1)"));
    }

    #[test]
    fn built_none_field_against_cached_value_is_a_mismatch() {
        // The typed model omits None fields on serialize, so a union-of-keys
        // walk is required to see a cached-only value like this one.
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["bucketing_identifier"] = json!("device_id");
        let cached = live(vec![flag_from_json(cached_json)]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(issue_types(&diffs), vec![ShadowIssueType::FieldMismatch]);
        assert_eq!(diffs[0].fields, vec!["bucketing_identifier"]);
    }

    #[test]
    fn missing_flag_reports_missing_in_cache() {
        let built = wrapper(vec![
            flag_from_json(base_flag_json(1)),
            flag_from_json(base_flag_json(2)),
        ]);
        let cached = live(vec![flag_from_json(base_flag_json(1))]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(issue_types(&diffs), vec![ShadowIssueType::MissingInCache]);
        assert_eq!(diffs[0].subject.as_deref(), Some("flag 2 (flag-2)"));
    }

    #[test]
    fn stale_active_flag_reports_stale_in_cache() {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let cached = live(vec![
            flag_from_json(base_flag_json(1)),
            flag_from_json(base_flag_json(2)),
        ]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(issue_types(&diffs), vec![ShadowIssueType::StaleInCache]);
        assert_eq!(diffs[0].subject.as_deref(), Some("flag 2 (flag-2)"));
    }

    #[test]
    fn stale_unevaluable_flag_is_tolerated() {
        // Matcher-invisible rows aren't drift — mirrors the Python verifier.
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut stale = base_flag_json(2);
        stale["active"] = json!(false);
        let cached = live(vec![
            flag_from_json(base_flag_json(1)),
            flag_from_json(stale),
        ]);

        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn blanked_filters_on_unevaluable_flag_are_tolerated() {
        // Fresh build blanks unevaluable filters; a live entry predating
        // blanking still holds the full blob. Both agree the flag is
        // unevaluable, so `filters` is exempt.
        let mut built_json = base_flag_json(1);
        built_json["active"] = json!(false);
        built_json["filters"] = json!({"groups": []});
        let mut cached_json = base_flag_json(1);
        cached_json["active"] = json!(false);
        let built = wrapper(vec![flag_from_json(built_json)]);
        let cached = live(vec![flag_from_json(cached_json)]);

        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn active_disagreement_still_reports() {
        // The blanked-filters exemption requires both sides unevaluable; a
        // disagreement about `active` itself is always drift.
        let mut cached_json = base_flag_json(1);
        cached_json["active"] = json!(false);
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let cached = live(vec![flag_from_json(cached_json)]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(issue_types(&diffs), vec![ShadowIssueType::FieldMismatch]);
        assert!(diffs[0].fields.contains(&"active".to_string()));
    }

    #[test]
    fn missing_evaluation_metadata_short_circuits() {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let cached = ShadowLiveEntry {
            flags: vec![],
            evaluation_metadata: None,
            cohorts: Some(Vec::new()),
        };

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(
            issue_types(&diffs),
            vec![ShadowIssueType::MissingEvaluationMetadata]
        );
        assert_eq!(diffs[0].subject, None);
    }

    #[test]
    fn evaluation_metadata_value_difference_reports() {
        // The Python verifier only checks presence; here the Rust dependency
        // staging is under test, so the value must match too.
        let mut built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        built.evaluation_metadata = EvaluationMetadata {
            dependency_stages: vec![vec![1]],
            flags_with_missing_deps: vec![],
            transitive_deps: [(1, Default::default())].into(),
        };
        let mut cached = live(vec![flag_from_json(base_flag_json(1))]);
        cached.evaluation_metadata = Some(EvaluationMetadata {
            dependency_stages: vec![vec![1]],
            flags_with_missing_deps: vec![1],
            transitive_deps: [(1, Default::default())].into(),
        });

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(
            issue_types(&diffs),
            vec![ShadowIssueType::EvaluationMetadataMismatch]
        );
        assert_eq!(diffs[0].fields, vec!["flags_with_missing_deps"]);
        assert_eq!(diffs[0].subject, None);
    }

    #[test]
    fn equal_evaluation_metadata_matches_regardless_of_map_order() {
        // transitive_deps is a map and stages are sorted by construction, so
        // equal metadata built independently must compare equal.
        let metadata = || EvaluationMetadata {
            dependency_stages: vec![vec![1, 2]],
            flags_with_missing_deps: vec![],
            transitive_deps: [(1, Default::default()), (2, Default::default())].into(),
        };
        let mut built = wrapper(vec![]);
        built.evaluation_metadata = metadata();
        let mut cached = live(vec![]);
        cached.evaluation_metadata = Some(metadata());

        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn cohort_field_difference_reports_with_field_names() {
        let mut built = wrapper(vec![]);
        built.cohorts = Some(vec![cohort_from_json(base_cohort_json(7))]);
        let mut cached_json = base_cohort_json(7);
        cached_json["filters"] = json!({"properties": {"type": "AND", "values": []}});
        let mut cached = live(vec![]);
        cached.cohorts = Some(vec![cohort_from_json(cached_json)]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(
            issue_types(&diffs),
            vec![ShadowIssueType::CohortFieldMismatch]
        );
        assert_eq!(diffs[0].fields, vec!["filters"]);
        assert_eq!(diffs[0].subject.as_deref(), Some("cohort 7"));
    }

    #[test]
    fn cohort_set_differences_report_missing_and_stale() {
        // A truncated Rust cohort BFS shows up as cohort_missing_in_cache on
        // the live side or stale on the built side — both must be visible.
        let mut built = wrapper(vec![]);
        built.cohorts = Some(vec![
            cohort_from_json(base_cohort_json(1)),
            cohort_from_json(base_cohort_json(2)),
        ]);
        let mut cached = live(vec![]);
        cached.cohorts = Some(vec![
            cohort_from_json(base_cohort_json(1)),
            cohort_from_json(base_cohort_json(3)),
        ]);

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(
            issue_types(&diffs),
            vec![
                ShadowIssueType::CohortMissingInCache,
                ShadowIssueType::CohortStaleInCache,
            ]
        );
        assert_eq!(diffs[0].subject.as_deref(), Some("cohort 2"));
        assert_eq!(diffs[1].subject.as_deref(), Some("cohort 3"));
    }

    #[test]
    fn cohort_null_optional_field_matches_absent_field() {
        // Python's _serialize_cohort emits explicit nulls for empty optionals;
        // the typed model omits them. Not drift.
        let mut cached_json = base_cohort_json(7);
        cached_json["description"] = serde_json::Value::Null;
        cached_json["query"] = serde_json::Value::Null;
        let mut built = wrapper(vec![]);
        built.cohorts = Some(vec![cohort_from_json(base_cohort_json(7))]);
        let mut cached = live(vec![]);
        cached.cohorts = Some(vec![cohort_from_json(cached_json)]);

        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    #[test]
    fn live_entry_without_cohorts_key_skips_cohort_compare() {
        // Entries predating the cohorts field carry none; the service falls
        // back to its own cohort load for them, so absence is not drift.
        let mut built = wrapper(vec![]);
        built.cohorts = Some(vec![cohort_from_json(base_cohort_json(1))]);
        let mut cached = live(vec![]);
        cached.cohorts = None;

        assert!(diff_live_entry(&built, &cached).is_empty());
    }

    /// Pinned so a change to the hashed parts, the marker bytes, or the digest has
    /// to be made on purpose. The value is written to Redis and compared by a later
    /// process, so its encoding is a cross-process contract like the key string. A
    /// silent change stops every team's pending state from matching for one TTL
    /// window after the deploy, and confirmations drop to zero with nothing saying
    /// why. Called with literal parts rather than through `diff_live_entry`, so a
    /// new field on `FeatureFlag` does not fail it.
    #[test]
    fn fingerprint_encoding_is_pinned() {
        assert_eq!(
            fingerprint(
                ShadowIssueType::FieldMismatch,
                Some("flag 1 (flag-1)"),
                Some(&json!({"has_experiment": false})),
                Some(&json!({"has_experiment": true})),
            ),
            0x3e37_1bcf_8d31_4c14
        );

        // The all-absent shape, which exercises the other marker byte.
        assert_eq!(
            fingerprint(ShadowIssueType::MissingEvaluationMetadata, None, None, None),
            0xdcb8_1973_c8ce_a9d4
        );
    }

    fn mismatch_diffs() -> Vec<ShadowDiff> {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["has_experiment"] = json!(true);
        let cached = live(vec![flag_from_json(cached_json)]);
        diff_live_entry(&built, &cached)
    }

    const TRACKER_TTL: Duration = Duration::from_secs(3600);
    const PENDING_KEY_TEAM_7: &str = "posthog:1:feature_flags/shadow_mismatch/7";

    /// One disagreement per flag, for a flag count the caller picks. Used to cross
    /// the store cap.
    fn many_mismatch_diffs(count: i32) -> Vec<ShadowDiff> {
        let built = (1..=count).map(|id| flag_from_json(base_flag_json(id)));
        let cached = (1..=count).map(|id| {
            let mut cached_json = base_flag_json(id);
            cached_json["has_experiment"] = json!(true);
            flag_from_json(cached_json)
        });
        diff_live_entry(&wrapper(built.collect()), &live(cached.collect()))
    }

    /// A disagreement on the same flag with different content, so the fingerprint
    /// differs from `mismatch_diffs`.
    fn other_mismatch_diffs() -> Vec<ShadowDiff> {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["filters"]["groups"][0]["rollout_percentage"] = json!(25.0);
        diff_live_entry(&built, &live(vec![flag_from_json(cached_json)]))
    }

    fn tracker(redis: &MockRedisClient) -> MismatchTracker {
        MismatchTracker::new(Arc::new(redis.clone()), TRACKER_TTL)
    }

    /// The store as the team's next shadow build finds it, in a new process.
    /// `MockRedisClient` records writes but serves no reads, so replaying its
    /// recorded writes into a fresh client is what models state that outlived the
    /// process which wrote it. The tracker holds nothing in memory, so a later
    /// build in the same pod and one in a new pod run the same code path.
    ///
    /// It replays *attempted* writes. The mock records a call whether or not it
    /// returned an error, so a test that injects a write failure must build the
    /// next store itself rather than call this.
    ///
    /// `shadow_observation` in `bin/flags_cache_builder.rs` models the same thing
    /// inline for the outcome-label test. A change to what the mock records has to
    /// reach both.
    fn next_build(prior: &MockRedisClient) -> MockRedisClient {
        let mut next = MockRedisClient::new();
        for call in prior.get_calls() {
            match (call.op.as_str(), call.value) {
                ("setex", MockRedisValue::StringWithTTL(value, _)) => {
                    next.get_ret(&call.key, Ok(value));
                }
                ("del", _) => {
                    next.get_ret(&call.key, Err(CustomRedisError::NotFound));
                }
                _ => {}
            }
        }
        next
    }

    fn calls_with_op(redis: &MockRedisClient, op: &str) -> Vec<MockRedisCall> {
        redis
            .get_calls()
            .into_iter()
            .filter(|call| call.op == op)
            .collect()
    }

    #[tokio::test]
    async fn tracker_suppresses_first_sight_and_confirms_repeat_across_a_restart() {
        let first_pod = MockRedisClient::new();
        let first = tracker(&first_pod).observe(7, mismatch_diffs()).await;
        assert!(first.confirmed.is_empty());
        assert_eq!(first.first_sight.len(), 1);
        assert!(first.store_errors.is_empty());

        let second_pod = next_build(&first_pod);
        let second = tracker(&second_pod).observe(7, mismatch_diffs()).await;
        assert_eq!(second.confirmed.len(), 1);
        assert!(second.first_sight.is_empty());
    }

    #[tokio::test]
    async fn tracker_clears_pending_state_on_match() {
        let first_pod = MockRedisClient::new();
        tracker(&first_pod).observe(7, mismatch_diffs()).await;

        let mut second_pod = next_build(&first_pod);
        second_pod.del_ret(PENDING_KEY_TEAM_7, Ok(()));

        let clean = tracker(&second_pod).observe(7, Vec::new()).await;
        assert!(clean.is_match());
        assert!(clean.store_errors.is_empty());

        // Asserted against the store, not against the next build: an unseeded mock
        // reads as an absent key, so a later first sighting proves nothing about
        // whether the clean build cleared anything.
        assert_eq!(
            calls_with_op(&second_pod, "del")
                .iter()
                .map(|call| call.key.as_str())
                .collect::<Vec<_>>(),
            vec![PENDING_KEY_TEAM_7]
        );

        // The earlier sighting no longer counts — mismatch starts over.
        let third_pod = next_build(&second_pod);
        let after = tracker(&third_pod).observe(7, mismatch_diffs()).await;
        assert!(after.confirmed.is_empty());
        assert_eq!(after.first_sight.len(), 1);
    }

    #[tokio::test]
    async fn tracker_expires_pending_state_after_ttl() {
        let first_pod = MockRedisClient::new();
        tracker(&first_pod).observe(7, mismatch_diffs()).await;

        // The TTL on this write is the only thing that bounds the confirmation
        // window, and the key is pinned because a tracker write must never land
        // on a cache entry the serve path reads.
        let writes = calls_with_op(&first_pod, "setex");
        assert_eq!(writes.len(), 1);
        assert_eq!(writes[0].key, PENDING_KEY_TEAM_7);
        match writes[0].value.clone() {
            MockRedisValue::StringWithTTL(_, ttl) => assert_eq!(ttl, TRACKER_TTL.as_secs()),
            other => panic!("expected a value with a TTL, got {other:?}"),
        }

        // The mock has no clock, so expiry is modelled as the key being gone by the
        // time the next build reads it. Stated rather than left to the mock's
        // default, so the test still means this if that default changes.
        let mut expired = next_build(&first_pod);
        expired.get_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::NotFound));

        let late = tracker(&expired).observe(7, mismatch_diffs()).await;
        assert!(late.confirmed.is_empty());
        assert_eq!(late.first_sight.len(), 1);
        assert!(late.store_errors.is_empty());
    }

    #[tokio::test]
    async fn tracker_treats_different_content_as_first_sight() {
        // An edit session produces a different disagreement each save — the
        // fingerprint hashes the content, so those never confirm.
        let first_pod = MockRedisClient::new();
        tracker(&first_pod).observe(7, mismatch_diffs()).await;

        let second_pod = next_build(&first_pod);
        let second = tracker(&second_pod)
            .observe(7, other_mismatch_diffs())
            .await;
        assert!(second.confirmed.is_empty());
        assert_eq!(second.first_sight.len(), 1);
    }

    #[tokio::test]
    async fn tracker_is_per_team() {
        let first_pod = MockRedisClient::new();
        tracker(&first_pod).observe(7, mismatch_diffs()).await;

        let second_pod = next_build(&first_pod);
        let other_team = tracker(&second_pod).observe(8, mismatch_diffs()).await;
        assert!(other_team.confirmed.is_empty());
        assert_eq!(other_team.first_sight.len(), 1);
    }

    #[tokio::test]
    async fn tracker_read_failure_falls_back_to_first_sight() {
        let first_pod = MockRedisClient::new();
        tracker(&first_pod).observe(7, mismatch_diffs()).await;

        let mut second_pod = next_build(&first_pod);
        second_pod.get_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::Timeout));

        let second = tracker(&second_pod).observe(7, mismatch_diffs()).await;
        assert!(second.confirmed.is_empty());
        assert_eq!(second.first_sight.len(), 1);
        assert_eq!(second.store_errors, vec![TrackerStoreOp::Read]);
    }

    #[tokio::test]
    async fn tracker_write_failure_clears_the_stale_observation() {
        // A failed write leaves the previous build's fingerprints in place with
        // their own TTL. Without the compensating clear, the team's next build
        // compares against an observation from two builds ago and can confirm a
        // disagreement the build in between did not see.
        let mut second_pod = next_build(&{
            let first_pod = MockRedisClient::new();
            tracker(&first_pod).observe(7, mismatch_diffs()).await;
            first_pod
        });
        second_pod.set_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::Timeout));
        second_pod.del_ret(PENDING_KEY_TEAM_7, Ok(()));

        let second = tracker(&second_pod)
            .observe(7, other_mismatch_diffs())
            .await;
        assert_eq!(second.store_errors, vec![TrackerStoreOp::Write]);
        assert_eq!(
            calls_with_op(&second_pod, "del")
                .iter()
                .map(|call| call.key.as_str())
                .collect::<Vec<_>>(),
            vec![PENDING_KEY_TEAM_7]
        );
    }

    #[tokio::test]
    async fn tracker_write_and_clear_failure_leaves_the_stale_observation() {
        // Both accesses failing is the residual `observe` documents: the previous
        // fingerprints stand until the TTL, so a disagreement that returns byte for
        // byte can confirm one build early. The counter pair is the only signal.
        let mut second_pod = next_build(&{
            let first_pod = MockRedisClient::new();
            tracker(&first_pod).observe(7, mismatch_diffs()).await;
            first_pod
        });
        second_pod.set_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::Timeout));
        second_pod.del_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::Timeout));

        let second = tracker(&second_pod)
            .observe(7, other_mismatch_diffs())
            .await;
        assert_eq!(
            second.store_errors,
            vec![TrackerStoreOp::Write, TrackerStoreOp::Clear]
        );
        assert!(second.confirmed.is_empty());
    }

    #[tokio::test]
    async fn tracker_unreadable_stored_value_is_reported_not_ignored() {
        // A stored value this build cannot parse counts as a read failure rather
        // than an absent key, so a value shape that changed across deploys shows on
        // the counter instead of looking like an expired window.
        let mut redis = MockRedisClient::new();
        redis.get_ret(PENDING_KEY_TEAM_7, Ok("not json".to_string()));

        let observation = tracker(&redis).observe(7, mismatch_diffs()).await;
        assert!(observation.confirmed.is_empty());
        assert_eq!(observation.first_sight.len(), 1);
        assert_eq!(observation.store_errors, vec![TrackerStoreOp::Read]);
    }

    #[tokio::test]
    async fn tracker_confirms_the_diffs_that_fit_the_stored_cap() {
        let over_cap = MAX_STORED_FINGERPRINTS as i32 + 20;
        let first_pod = MockRedisClient::new();
        let first = tracker(&first_pod)
            .observe(7, many_mismatch_diffs(over_cap))
            .await;
        assert_eq!(first.first_sight.len(), over_cap as usize);

        let second_pod = next_build(&first_pod);
        let second = tracker(&second_pod)
            .observe(7, many_mismatch_diffs(over_cap))
            .await;

        // Pins the cap, and that a diff inside it confirms. It does not pin which
        // diffs are stored: the next build compares all of its diffs against the
        // stored set, so any 256 of them produce 256 confirmations. Taking the
        // first entries of a stable order is what makes one flag's disagreement
        // confirm on every build rather than on some.
        assert_eq!(second.confirmed.len(), MAX_STORED_FINGERPRINTS);
        assert_eq!(second.first_sight.len(), 20);
    }

    #[tokio::test]
    async fn tracker_clear_failure_is_reported() {
        let mut redis = MockRedisClient::new();
        redis.del_ret(PENDING_KEY_TEAM_7, Err(CustomRedisError::Timeout));

        let clean = tracker(&redis).observe(7, Vec::new()).await;
        assert!(clean.is_match());
        assert_eq!(clean.store_errors, vec![TrackerStoreOp::Clear]);
    }

    #[test]
    fn summarize_caps_entries_and_reports_remainder() {
        let diffs = mismatch_diffs();
        let mut many: Vec<ShadowDiff> = Vec::new();
        for _ in 0..5 {
            many.extend(diffs.iter().cloned());
        }

        let summary = summarize_diffs(&many, 2, 4096);
        assert_eq!(summary.matches("flag 1").count(), 2);
        assert!(summary.ends_with("; +3 more"));
    }

    #[test]
    fn summarize_caps_bytes() {
        let diffs = mismatch_diffs();
        let summary = summarize_diffs(&diffs, 10, 8);
        assert_eq!(summary, "; +1 more");
        assert!(summary.len() <= 8 + "; +1 more".len());
    }

    #[test]
    fn summarize_renders_fields() {
        let summary = summarize_diffs(&mismatch_diffs(), 10, 4096);
        assert_eq!(summary, "flag 1 (flag-1): field_mismatch[has_experiment]");
    }
}
