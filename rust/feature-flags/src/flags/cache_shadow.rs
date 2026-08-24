//! Shadow-compare support for the `flags-cache-builder` consumer.
//!
//! A `shadow: true` invalidation asks the builder to prove parity, not to serve:
//! build the payload exactly as a real invalidation would, diff it against the
//! live cache entry Python (Celery) owns, and record the result — never write.
//! This module holds the pure parts: the semantic diff and the repeat-offender
//! suppression. Reading the live entry and emitting metrics stay in the binary.
//!
//! The diff mirrors the Python verifier's definition of parity —
//! `verify_team_flags` in `products/feature_flags/backend/flags_cache.py`:
//! per-team flag-set equality by flag id, field-level comparison for flags on
//! both sides, missing-in-cache / stale-in-cache detection, an unevaluable
//! stale row tolerated, and `filters` exempted when both sides agree the flag
//! is unevaluable (the writers blank those; entries predating blanking still
//! hold the full blob). Parity is per team, not per byte: both sides are
//! deserialized through the same typed `FeatureFlag` model before comparing,
//! so JSON key order, absent-vs-null optional fields, and serialization
//! formatting can never register as mismatches. Unlike the Python verifier's
//! "compare only DB-side keys" rule (which tolerates stale extra keys in raw
//! cache JSON — the typed round-trip already drops those), the field loop here
//! walks the union of both sides' keys: the typed model omits `None` fields on
//! serialize, so a built-side `None` against a cached value would otherwise be
//! invisible.

use std::collections::hash_map::DefaultHasher;
use std::collections::{HashMap, HashSet};
use std::hash::{Hash, Hasher};
use std::time::{Duration, Instant};

use common_types::TeamId;
use serde::Deserialize;

use crate::flags::cache_builder::is_evaluable;
use crate::flags::flag_models::{FeatureFlag, FeatureFlagId, HypercacheFlagsWrapper};

/// The slice of a live cache entry the shadow diff reads. Deserialized leniently
/// (unknown fields such as `cohorts` are ignored; `evaluation_metadata` may be
/// absent in entries predating it) so an old-shape entry surfaces as a semantic
/// mismatch below rather than a parse failure.
#[derive(Debug, Deserialize)]
pub struct ShadowLiveEntry {
    #[serde(default)]
    pub flags: Vec<FeatureFlag>,
    #[serde(default)]
    pub evaluation_metadata: Option<serde_json::Value>,
}

/// One issue class per diff entry; used as the `issue_type` metric label, so the
/// set must stay small and static.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShadowIssueType {
    /// Live entry has no `evaluation_metadata` key (pre-metadata entry shape).
    MissingEvaluationMetadata,
    /// Flag present in the fresh build but absent from the live entry.
    MissingInCache,
    /// Evaluable flag present in the live entry but absent from the fresh build.
    StaleInCache,
    /// Flag present on both sides with differing field values.
    FieldMismatch,
}

impl ShadowIssueType {
    pub fn as_label(&self) -> &'static str {
        match self {
            Self::MissingEvaluationMetadata => "missing_evaluation_metadata",
            Self::MissingInCache => "missing_in_cache",
            Self::StaleInCache => "stale_in_cache",
            Self::FieldMismatch => "field_mismatch",
        }
    }
}

/// One semantic difference between the fresh build and the live entry.
#[derive(Debug, Clone)]
pub struct ShadowDiff {
    pub issue_type: ShadowIssueType,
    /// `None` only for team-level issues (`MissingEvaluationMetadata`).
    pub flag_id: Option<FeatureFlagId>,
    pub flag_key: Option<String>,
    /// Differing field names; populated only for `FieldMismatch`.
    pub fields: Vec<String>,
    /// Content hash of the disagreement, used by `MismatchTracker` to decide
    /// whether the *same* mismatch persisted across two consecutive shadow
    /// builds. Hashing the values (not just flag id + issue type) keeps an edit
    /// session — where each save races Python's rebuild with *different* content
    /// — from ever counting as a repeat.
    fingerprint: u64,
}

fn fingerprint(
    issue_type: ShadowIssueType,
    flag_id: Option<FeatureFlagId>,
    built: Option<&serde_json::Value>,
    cached: Option<&serde_json::Value>,
) -> u64 {
    let mut hasher = DefaultHasher::new();
    issue_type.as_label().hash(&mut hasher);
    flag_id.hash(&mut hasher);
    built.map(|v| v.to_string()).hash(&mut hasher);
    cached.map(|v| v.to_string()).hash(&mut hasher);
    hasher.finish()
}

fn flag_diff(
    issue_type: ShadowIssueType,
    flag: &FeatureFlag,
    built: Option<&serde_json::Value>,
    cached: Option<&serde_json::Value>,
    fields: Vec<String>,
) -> ShadowDiff {
    ShadowDiff {
        issue_type,
        flag_id: Some(flag.id),
        flag_key: Some(flag.key.clone()),
        fields,
        fingerprint: fingerprint(issue_type, Some(flag.id), built, cached),
    }
}

/// Semantically diff a fresh build against the live cache entry. Empty result
/// means parity. Sorted by flag id for deterministic logs.
pub fn diff_live_entry(built: &HypercacheFlagsWrapper, live: &ShadowLiveEntry) -> Vec<ShadowDiff> {
    // Mirrors the Python verifier's MISSING_EVALUATION_METADATA early return:
    // an entry that old predates the current payload shape, so a per-flag diff
    // would only bury the actual finding.
    if live.evaluation_metadata.is_none() {
        return vec![ShadowDiff {
            issue_type: ShadowIssueType::MissingEvaluationMetadata,
            flag_id: None,
            flag_key: None,
            fields: Vec::new(),
            fingerprint: fingerprint(ShadowIssueType::MissingEvaluationMetadata, None, None, None),
        }];
    }

    let built_by_id: HashMap<FeatureFlagId, &FeatureFlag> =
        built.flags.iter().map(|f| (f.id, f)).collect();
    let cached_by_id: HashMap<FeatureFlagId, &FeatureFlag> =
        live.flags.iter().map(|f| (f.id, f)).collect();

    let mut diffs: Vec<ShadowDiff> = Vec::new();

    for flag in &built.flags {
        match cached_by_id.get(&flag.id) {
            None => {
                let built_value = serde_json::to_value(flag).unwrap_or_default();
                diffs.push(flag_diff(
                    ShadowIssueType::MissingInCache,
                    flag,
                    Some(&built_value),
                    None,
                    Vec::new(),
                ));
            }
            Some(cached) => {
                if let Some(diff) = compare_flag_fields(flag, cached) {
                    diffs.push(diff);
                }
            }
        }
    }

    for flag in &live.flags {
        if built_by_id.contains_key(&flag.id) {
            continue;
        }
        // An unevaluable cached row is invisible to the matcher, so its
        // presence is not drift — same tolerance as the Python verifier.
        if !is_evaluable(flag) {
            continue;
        }
        let cached_value = serde_json::to_value(flag).unwrap_or_default();
        diffs.push(flag_diff(
            ShadowIssueType::StaleInCache,
            flag,
            None,
            Some(&cached_value),
            Vec::new(),
        ));
    }

    diffs.sort_by_key(|d| d.flag_id);
    diffs
}

/// Field-level comparison of one flag present on both sides, over the union of
/// serialized keys. `filters` is exempt when both sides agree the flag is
/// unevaluable — only the cache writers blank filters, and entries predating
/// blanking still hold the full blob the matcher never reads.
fn compare_flag_fields(built: &FeatureFlag, cached: &FeatureFlag) -> Option<ShadowDiff> {
    let built_value = serde_json::to_value(built).unwrap_or_default();
    let cached_value = serde_json::to_value(cached).unwrap_or_default();
    let (Some(built_map), Some(cached_map)) = (built_value.as_object(), cached_value.as_object())
    else {
        return None;
    };

    let both_unevaluable = !is_evaluable(built) && !is_evaluable(cached);

    let mut fields: Vec<String> = built_map
        .keys()
        .chain(cached_map.keys().filter(|k| !built_map.contains_key(*k)))
        .filter(|key| !(both_unevaluable && *key == "filters"))
        .filter(|key| built_map.get(*key) != cached_map.get(*key))
        .cloned()
        .collect();

    if fields.is_empty() {
        return None;
    }
    fields.sort_unstable();
    Some(flag_diff(
        ShadowIssueType::FieldMismatch,
        built,
        Some(&built_value),
        Some(&cached_value),
        fields,
    ))
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
        let entry = match (&diff.flag_id, &diff.flag_key) {
            (Some(id), Some(key)) if diff.fields.is_empty() => {
                format!("flag {id} ({key}): {}", diff.issue_type.as_label())
            }
            (Some(id), Some(key)) => format!(
                "flag {id} ({key}): {}[{}]",
                diff.issue_type.as_label(),
                diff.fields.join(",")
            ),
            _ => diff.issue_type.as_label().to_string(),
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
    use crate::flags::flag_models::EvaluationMetadata;

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

    fn wrapper(flags: Vec<FeatureFlag>) -> HypercacheFlagsWrapper {
        HypercacheFlagsWrapper {
            flags,
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: None,
        }
    }

    fn live(flags: Vec<FeatureFlag>) -> ShadowLiveEntry {
        ShadowLiveEntry {
            flags,
            evaluation_metadata: Some(json!({})),
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
            "evaluation_metadata": {},
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
        assert_eq!(diffs[0].flag_id, Some(1));
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
        assert_eq!(diffs[0].flag_id, Some(2));
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
        assert_eq!(diffs[0].flag_id, Some(2));
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
        };

        let diffs = diff_live_entry(&built, &cached);
        assert_eq!(
            issue_types(&diffs),
            vec![ShadowIssueType::MissingEvaluationMetadata]
        );
        assert_eq!(diffs[0].flag_id, None);
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
