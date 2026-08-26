//! Shadow-compare support for the `flags-cache-builder` consumer.
//!
//! A `shadow: true` invalidation asks the builder to prove parity, not to serve:
//! build the payload exactly as a real invalidation would, diff it against the
//! live cache entry Python (Celery) owns, and record the result — never write.
//! This module holds the pure parts: the semantic diff and the repeat-offender
//! suppression. Reading the live entry and emitting metrics stay in the binary.
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

use std::collections::hash_map::DefaultHasher;
use std::collections::{HashMap, HashSet};
use std::hash::{Hash, Hasher};
use std::time::{Duration, Instant};

use common_types::TeamId;
use serde::Deserialize;

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

fn fingerprint(
    issue_type: ShadowIssueType,
    subject: Option<&str>,
    built: Option<&serde_json::Value>,
    cached: Option<&serde_json::Value>,
) -> u64 {
    let mut hasher = DefaultHasher::new();
    issue_type.as_label().hash(&mut hasher);
    subject.hash(&mut hasher);
    built.map(|v| v.to_string()).hash(&mut hasher);
    cached.map(|v| v.to_string()).hash(&mut hasher);
    hasher.finish()
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
}

impl ShadowObservation {
    pub fn is_match(&self) -> bool {
        self.confirmed.is_empty() && self.first_sight.is_empty()
    }
}

struct PendingMismatch {
    fingerprints: HashSet<u64>,
    recorded_at: Instant,
}

/// Above this many pending teams, expired entries are swept on the next observe.
/// Sized far beyond realistic mismatch volume — it only bounds memory if
/// something goes systemically wrong.
const PENDING_PRUNE_THRESHOLD: usize = 10_000;

/// In-memory repeat-offender suppression: a mismatch counts only when the same
/// fingerprint shows up on two consecutive shadow builds of the team within
/// `ttl`. A shadow build races Python's own rebuild of the same team, so a
/// single-shot mismatch is expected noise; Python repairs the entry and the next
/// shadow build of the team comes back clean, clearing the pending state.
pub struct MismatchTracker {
    ttl: Duration,
    pending: HashMap<TeamId, PendingMismatch>,
}

impl MismatchTracker {
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            pending: HashMap::new(),
        }
    }

    /// Fold one shadow build's diffs into the tracker and split them into
    /// confirmed (fingerprint also seen on the previous, unexpired observation)
    /// and first-sight. An empty `diffs` clears the team's pending state.
    pub fn observe(
        &mut self,
        team_id: TeamId,
        diffs: Vec<ShadowDiff>,
        now: Instant,
    ) -> ShadowObservation {
        if self.pending.len() >= PENDING_PRUNE_THRESHOLD {
            let ttl = self.ttl;
            self.pending
                .retain(|_, p| now.duration_since(p.recorded_at) < ttl);
        }

        if diffs.is_empty() {
            self.pending.remove(&team_id);
            return ShadowObservation::default();
        }

        let prior: Option<HashSet<u64>> = self
            .pending
            .get(&team_id)
            .filter(|p| now.duration_since(p.recorded_at) < self.ttl)
            .map(|p| p.fingerprints.clone());

        self.pending.insert(
            team_id,
            PendingMismatch {
                fingerprints: diffs.iter().map(|d| d.fingerprint).collect(),
                recorded_at: now,
            },
        );

        match prior {
            Some(previous) => {
                let (confirmed, first_sight) = diffs
                    .into_iter()
                    .partition(|d| previous.contains(&d.fingerprint));
                ShadowObservation {
                    confirmed,
                    first_sight,
                }
            }
            None => ShadowObservation {
                confirmed: Vec::new(),
                first_sight: diffs,
            },
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
    use std::time::{Duration, Instant};

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

    fn mismatch_diffs() -> Vec<ShadowDiff> {
        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["has_experiment"] = json!(true);
        let cached = live(vec![flag_from_json(cached_json)]);
        diff_live_entry(&built, &cached)
    }

    #[test]
    fn tracker_suppresses_first_sight_and_confirms_repeat() {
        let mut tracker = MismatchTracker::new(Duration::from_secs(3600));
        let now = Instant::now();

        let first = tracker.observe(7, mismatch_diffs(), now);
        assert!(first.confirmed.is_empty());
        assert_eq!(first.first_sight.len(), 1);

        let second = tracker.observe(7, mismatch_diffs(), now + Duration::from_secs(60));
        assert_eq!(second.confirmed.len(), 1);
        assert!(second.first_sight.is_empty());
    }

    #[test]
    fn tracker_clears_pending_state_on_match() {
        let mut tracker = MismatchTracker::new(Duration::from_secs(3600));
        let now = Instant::now();

        tracker.observe(7, mismatch_diffs(), now);
        let clean = tracker.observe(7, Vec::new(), now + Duration::from_secs(30));
        assert!(clean.is_match());

        // The earlier sighting no longer counts — mismatch starts over.
        let after = tracker.observe(7, mismatch_diffs(), now + Duration::from_secs(60));
        assert!(after.confirmed.is_empty());
        assert_eq!(after.first_sight.len(), 1);
    }

    #[test]
    fn tracker_expires_pending_state_after_ttl() {
        let mut tracker = MismatchTracker::new(Duration::from_secs(100));
        let now = Instant::now();

        tracker.observe(7, mismatch_diffs(), now);
        let late = tracker.observe(7, mismatch_diffs(), now + Duration::from_secs(101));
        assert!(late.confirmed.is_empty());
        assert_eq!(late.first_sight.len(), 1);
    }

    #[test]
    fn tracker_treats_different_content_as_first_sight() {
        // An edit session produces a different disagreement each save — the
        // fingerprint hashes the content, so those never confirm.
        let mut tracker = MismatchTracker::new(Duration::from_secs(3600));
        let now = Instant::now();

        tracker.observe(7, mismatch_diffs(), now);

        let built = wrapper(vec![flag_from_json(base_flag_json(1))]);
        let mut cached_json = base_flag_json(1);
        cached_json["filters"]["groups"][0]["rollout_percentage"] = json!(25.0);
        let other = diff_live_entry(&built, &live(vec![flag_from_json(cached_json)]));

        let second = tracker.observe(7, other, now + Duration::from_secs(60));
        assert!(second.confirmed.is_empty());
        assert_eq!(second.first_sight.len(), 1);
    }

    #[test]
    fn tracker_is_per_team() {
        let mut tracker = MismatchTracker::new(Duration::from_secs(3600));
        let now = Instant::now();

        tracker.observe(7, mismatch_diffs(), now);
        let other_team = tracker.observe(8, mismatch_diffs(), now + Duration::from_secs(60));
        assert!(other_team.confirmed.is_empty());
        assert_eq!(other_team.first_sight.len(), 1);
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
