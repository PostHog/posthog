//! Per-leaf Stage 1 state, its persisted wrapper, and the value codec.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Which state representation a leaf uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StateVariant {
    /// `performed_event`: a single "has any matching event in window" bit.
    BehavioralSingle,
    /// `performed_event_multiple` with a `1..=180`-day window: dense per-calendar-day counts.
    BehavioralDailyBuckets,
    /// `performed_event_multiple` with a window over 180 days: sparse run-length per-calendar-day
    /// counts.
    BehavioralCompressedHistory,
    /// A person-property filter: a last-write-wins boolean.
    PersonProperty,
}

impl StateVariant {
    /// The metric-label / log form.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BehavioralSingle => "behavioral_single",
            Self::BehavioralDailyBuckets => "behavioral_daily_buckets",
            Self::BehavioralCompressedHistory => "behavioral_compressed_history",
            Self::PersonProperty => "person_property",
        }
    }
}

/// The incremental per-`(team_id, leaf_state_key, person_id)` state a leaf maintains.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "v")]
pub enum Stage1State {
    /// `performed_event`. `has_match` is never cleared, so the predicate only flips `false → true`.
    BehavioralSingle {
        has_match: bool,
        /// Most recent matching event time (epoch ms), `max`-folded across events.
        last_event_at_ms: i64,
        /// Earliest time (epoch ms) the sweep may evict this state.
        earliest_eviction_at_ms: i64,
    },
    /// `performed_event_multiple` over a `1..=180`-day window. Membership is derived from `buckets`
    /// and the leaf's `PredicateOp` (which lives on the catalog meta, not here).
    BehavioralDailyBuckets {
        /// Dense per-day counts: `buckets[i]` is the matching-event count for calendar day
        /// `window_start_day + i`, in the team timezone. `len() == window_days + 1` (the inclusive
        /// `[now_day − N ..= now_day]` window); index `len() − 1` is the current "now" day.
        buckets: Vec<u32>,
        /// [`DayIdx`](crate::stage1::bucket_tz::DayIdx) (days since the Unix epoch, team tz) of
        /// `buckets[0]` — the window's inclusive lower bound. Monotonic non-decreasing as the window
        /// slides forward; `window_days` is not stored (it equals `buckets.len() − 1`).
        window_start_day: i32,
        /// Most recent matching event time (epoch ms), `max`-folded across events.
        last_event_at_ms: i64,
        /// Earliest time (epoch ms) the oldest non-zero bucket leaves the window — its eviction
        /// deadline. The event path never reads a wall clock.
        earliest_eviction_at_ms: i64,
    },
    /// `performed_event_multiple` over a window exceeding 180 days, stored as sparse run-length
    /// entries — the compressed analog of [`Self::BehavioralDailyBuckets`]. Membership is derived from
    /// the entries' count sum and the leaf's `PredicateOp` (on the catalog meta, not here).
    BehavioralCompressedHistory {
        /// Sparse per-day counts: `(day_idx, count)` for each calendar day (team tz) with at least one
        /// matching event, sorted ascending by day with no zero-count entries. The sparse form of
        /// [`Self::BehavioralDailyBuckets`]'s dense array — bounded by `window_days + 1` entries, far
        /// fewer for a typical user.
        entries: Vec<(i32, u32)>,
        /// [`DayIdx`](crate::stage1::bucket_tz::DayIdx) of the window's inclusive lower bound (the
        /// `window_start_day` anchor). Monotonic non-decreasing as the window slides forward; the
        /// "now" day is `window_start_day + window_days` (`window_days` lives on the meta, not here).
        window_start_day: i32,
        /// Most recent matching event time (epoch ms), `max`-folded across events.
        last_event_at_ms: i64,
        /// Earliest time (epoch ms) the oldest entry leaves the window — its eviction deadline
        /// ([`i64::MAX`] when empty).
        earliest_eviction_at_ms: i64,
    },
}

impl Stage1State {
    pub fn variant(&self) -> StateVariant {
        match self {
            Self::BehavioralSingle { .. } => StateVariant::BehavioralSingle,
            Self::BehavioralDailyBuckets { .. } => StateVariant::BehavioralDailyBuckets,
            Self::BehavioralCompressedHistory { .. } => StateVariant::BehavioralCompressedHistory,
        }
    }

    /// The eviction deadline (epoch ms) for this state. Every `cf_behavioral` variant is behavioral
    /// and time-bounded (person-property membership lives in `cf_person_records`, which is
    /// sweep-invariant), so this is always `Some`; the deadline may be [`i64::MAX`] (permanent
    /// membership). Kept `Option`-returning so the sweep-scheduling call sites read uniformly.
    pub fn eviction_deadline(&self) -> Option<i64> {
        match self {
            Self::BehavioralSingle {
                earliest_eviction_at_ms,
                ..
            }
            | Self::BehavioralDailyBuckets {
                earliest_eviction_at_ms,
                ..
            }
            | Self::BehavioralCompressedHistory {
                earliest_eviction_at_ms,
                ..
            } => Some(*earliest_eviction_at_ms),
        }
    }
}

/// Per-source-partition last-applied offsets for replay dedup. `BTreeMap` for deterministic
/// serialization.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct AppliedOffsets(BTreeMap<i32, i64>);

impl AppliedOffsets {
    /// `true` if this `(source_partition, source_offset)` was already applied.
    pub fn is_replay(&self, source_partition: i32, source_offset: i64) -> bool {
        self.0
            .get(&source_partition)
            .is_some_and(|&last| source_offset <= last)
    }

    /// Advance the high-water mark for `source_partition`. Monotonic per partition.
    pub fn record(&mut self, source_partition: i32, source_offset: i64) {
        self.0
            .entry(source_partition)
            .and_modify(|last| *last = (*last).max(source_offset))
            .or_insert(source_offset);
    }

    /// Fold another map's high-water marks into this one, per-partition max.
    pub fn merge_max(&mut self, other: &Self) {
        for (&partition, &offset) in &other.0 {
            self.record(partition, offset);
        }
    }

    /// The `(source_partition, high_water_offset)` pairs in ascending partition order — the canonical
    /// order a binary codec serializes them in.
    pub fn entries(&self) -> Vec<(i32, i64)> {
        self.0.iter().map(|(&p, &o)| (p, o)).collect()
    }

    /// Rebuild from entries already known to be sorted-distinct by partition (a codec verifies this
    /// before calling). The `BTreeMap` re-imposes the ordering regardless, so a caller that violates
    /// the precondition loses only canonicality, not correctness.
    pub fn from_sorted_entries(entries: Vec<(i32, i64)>) -> Self {
        Self(entries.into_iter().collect())
    }
}

/// The persisted `cf_behavioral` value: a [`Stage1State`] plus replay-dedup offsets.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatefulRecord {
    pub state: Stage1State,
    pub applied_offsets: AppliedOffsets,
    /// Per-ancestor replay-dedup for post-merge straggler events. Empty for non-merged persons.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub redirect_dedup: BTreeMap<Uuid, AppliedOffsets>,
}

/// A failure decoding a stored [`StatefulRecord`].
#[derive(Debug, thiserror::Error)]
#[error("decoding Stage1 record: {0}")]
pub struct StateCodecError(#[from] serde_json::Error);

impl StatefulRecord {
    /// A record with no redirect-dedup ancestry.
    pub fn new(state: Stage1State, applied_offsets: AppliedOffsets) -> Self {
        Self {
            state,
            applied_offsets,
            redirect_dedup: BTreeMap::new(),
        }
    }

    /// Origin-aware replay check.
    pub fn is_replay_for(
        &self,
        origin: Option<&Uuid>,
        source_partition: i32,
        source_offset: i64,
    ) -> bool {
        dedup_is_replay(
            &self.applied_offsets,
            &self.redirect_dedup,
            origin,
            source_partition,
            source_offset,
        )
    }

    /// Origin-aware offset advance.
    pub fn record_for(&mut self, origin: Option<&Uuid>, source_partition: i32, source_offset: i64) {
        dedup_record(
            &mut self.applied_offsets,
            &mut self.redirect_dedup,
            origin,
            source_partition,
            source_offset,
        );
    }

    pub fn encode(&self) -> Vec<u8> {
        serde_json::to_vec(self).expect("StatefulRecord is plain data and always serializes")
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StateCodecError> {
        Ok(serde_json::from_slice(bytes)?)
    }
}

/// Origin-aware replay check over a moved-out dedup pair.
pub(crate) fn dedup_is_replay(
    main: &AppliedOffsets,
    redirect: &BTreeMap<Uuid, AppliedOffsets>,
    origin: Option<&Uuid>,
    source_partition: i32,
    source_offset: i64,
) -> bool {
    match origin {
        None => main.is_replay(source_partition, source_offset),
        Some(ancestor) => redirect
            .get(ancestor)
            .is_some_and(|offsets| offsets.is_replay(source_partition, source_offset)),
    }
}

/// Origin-aware offset advance over a moved-out dedup pair.
pub(crate) fn dedup_record(
    main: &mut AppliedOffsets,
    redirect: &mut BTreeMap<Uuid, AppliedOffsets>,
    origin: Option<&Uuid>,
    source_partition: i32,
    source_offset: i64,
) {
    match origin {
        None => main.record(source_partition, source_offset),
        Some(ancestor) => redirect
            .entry(*ancestor)
            .or_default()
            .record(source_partition, source_offset),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
        let mut applied = AppliedOffsets::default();
        for &(partition, offset) in entries {
            applied.record(partition, offset);
        }
        applied
    }

    fn behavioral() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 7 * 86_400 * 1000,
            },
            applied(&[(17, 42)]),
        )
    }

    /// A second behavioral record with distinct offsets, used by the dedup-routing tests (whose
    /// invariants are variant-agnostic — they exercise `applied_offsets` / `redirect_dedup` only).
    fn dedup_record() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_123,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied(&[(3, 100)]),
        )
    }

    fn daily() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralDailyBuckets {
                buckets: vec![0, 2, 0, 1, 3, 0, 1, 5],
                window_start_day: 20_600,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 7 * 86_400 * 1000,
            },
            applied(&[(4, 7), (9, 2)]),
        )
    }

    fn compressed() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralCompressedHistory {
                entries: vec![(20_240, 2), (20_400, 1), (20_605, 5)],
                window_start_day: 20_240,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 365 * 86_400 * 1000,
            },
            applied(&[(4, 7), (9, 2)]),
        )
    }

    #[test]
    fn round_trips_every_variant() {
        for record in [behavioral(), dedup_record(), daily(), compressed()] {
            let bytes = record.encode();
            assert_eq!(StatefulRecord::decode(&bytes).unwrap(), record);
        }
    }

    #[test]
    fn garbage_bytes_decode_to_err_not_panic() {
        assert!(StatefulRecord::decode(b"not json at all").is_err());
        assert!(StatefulRecord::decode(&[]).is_err());
    }

    #[test]
    fn daily_buckets_decode_from_its_on_disk_shape() {
        let on_disk = serde_json::json!({
            "state": {
                "v": "BehavioralDailyBuckets",
                "buckets": [0, 2, 0, 1, 3, 0, 1, 5],
                "window_start_day": 20_600,
                "last_event_at_ms": 1_700_000_000_000_i64,
                "earliest_eviction_at_ms": 1_700_000_000_000_i64 + 7 * 86_400 * 1000,
            },
            "applied_offsets": { "4": 7, "9": 2 },
        });
        let bytes = serde_json::to_vec(&on_disk).unwrap();
        assert_eq!(StatefulRecord::decode(&bytes).unwrap(), daily());
    }

    #[test]
    fn compressed_history_decodes_from_its_on_disk_shape() {
        let on_disk = serde_json::json!({
            "state": {
                "v": "BehavioralCompressedHistory",
                "entries": [[20_240, 2], [20_400, 1], [20_605, 5]],
                "window_start_day": 20_240,
                "last_event_at_ms": 1_700_000_000_000_i64,
                "earliest_eviction_at_ms": 1_700_000_000_000_i64 + 365 * 86_400 * 1000,
            },
            "applied_offsets": { "4": 7, "9": 2 },
        });
        let bytes = serde_json::to_vec(&on_disk).unwrap();
        assert_eq!(StatefulRecord::decode(&bytes).unwrap(), compressed());
    }

    #[test]
    fn still_unknown_variant_tag_is_a_decode_error() {
        let forward = serde_json::json!({
            "state": { "v": "BehavioralHourlyBuckets", "buckets": [1, 2, 3] },
            "applied_offsets": { "0": 0 },
        });
        let bytes = serde_json::to_vec(&forward).unwrap();
        assert!(StatefulRecord::decode(&bytes).is_err());
    }

    #[test]
    fn old_scalar_format_fails_to_decode_rather_than_silently_defaulting() {
        // The scalar offset format (`last_applied_partition`/`last_applied_offset`) must fail-decode,
        // not silently default `applied_offsets` to empty (which would drop high-water marks and
        // re-open double-count windows).
        let old = serde_json::json!({
            "state": {
                "v": "BehavioralSingle",
                "has_match": true,
                "last_event_at_ms": 1_700_000_000_000_i64,
                "earliest_eviction_at_ms": 1_700_000_000_000_i64,
            },
            "last_applied_partition": 17,
            "last_applied_offset": 42,
        });
        let bytes = serde_json::to_vec(&old).unwrap();
        assert!(
            StatefulRecord::decode(&bytes).is_err(),
            "the old scalar format must fail-decode, not default applied_offsets to empty",
        );
    }

    #[test]
    fn applied_offsets_is_replay_table() {
        let applied = applied(&[(5, 100), (6, 50)]);
        let cases = [
            (
                5,
                100,
                true,
                "exact offset on a seen partition is a replay → skip",
            ),
            (
                5,
                99,
                true,
                "lower offset on a seen partition is a replay → skip",
            ),
            (
                5,
                101,
                false,
                "higher offset on a seen partition is new → apply",
            ),
            (
                6,
                50,
                true,
                "exact offset on the other seen partition → skip",
            ),
            (6, 51, false, "higher offset on the other partition → apply"),
            (7, 0, false, "an unseen partition is never a replay → apply"),
            (
                7,
                i64::MAX,
                false,
                "an unseen partition is never a replay, any offset → apply",
            ),
        ];
        for (partition, offset, expected, why) in cases {
            assert_eq!(
                applied.is_replay(partition, offset),
                expected,
                "is_replay({partition}, {offset}): {why}",
            );
        }
    }

    #[test]
    fn applied_offsets_empty_is_never_a_replay() {
        let applied = AppliedOffsets::default();
        assert!(!applied.is_replay(0, 0), "empty map: nothing seen yet");
        assert!(!applied.is_replay(3, 100));
    }

    #[test]
    fn applied_offsets_offset_zero_is_a_valid_first_offset() {
        let mut applied = AppliedOffsets::default();
        assert!(
            !applied.is_replay(5, 0),
            "0 before recording is not a replay"
        );
        applied.record(5, 0);
        assert!(applied.is_replay(5, 0), "0 after recording is a replay");
        assert!(!applied.is_replay(5, 1), "1 is still new");
    }

    #[test]
    fn applied_offsets_record_is_monotonic_per_partition() {
        let mut applied = AppliedOffsets::default();
        applied.record(5, 100);
        applied.record(5, 50); // lower → ignored
        assert!(applied.is_replay(5, 100));
        assert!(!applied.is_replay(5, 101), "high-water mark stayed at 100");
        applied.record(5, 150); // higher → advances
        assert!(applied.is_replay(5, 150));
        assert!(!applied.is_replay(5, 151));
    }

    #[test]
    fn applied_offsets_tracks_partitions_independently() {
        let applied = applied(&[(5, 100), (6, 10)]);
        assert!(applied.is_replay(5, 100));
        assert!(!applied.is_replay(6, 11));
        assert!(applied.is_replay(6, 10));
    }

    #[test]
    fn applied_offsets_serializes_with_sorted_partition_keys() {
        let applied = applied(&[(17, 1), (2, 2), (5, 3)]);
        assert_eq!(
            serde_json::to_string(&applied).unwrap(),
            r#"{"2":2,"5":3,"17":1}"#,
        );
    }

    #[test]
    fn multi_entry_record_round_trips_with_sorted_keys() {
        let record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied(&[(3, 100), (7, 5), (1, 0)]),
        );
        let bytes = record.encode();
        assert_eq!(StatefulRecord::decode(&bytes).unwrap(), record);
        let text = String::from_utf8(bytes).unwrap();
        assert!(
            text.contains(r#""applied_offsets":{"1":0,"3":100,"7":5}"#),
            "applied_offsets must serialize with sorted partition keys, got: {text}",
        );
    }

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    #[test]
    fn empty_redirect_dedup_serializes_byte_identical_to_master() {
        let record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied(&[(3, 100)]),
        );
        let text = String::from_utf8(record.encode()).unwrap();
        assert!(
            !text.contains("redirect_dedup"),
            "an empty redirect_dedup must not appear on the wire, got: {text}",
        );
        assert_eq!(
            text,
            r#"{"state":{"v":"BehavioralSingle","has_match":true,"last_event_at_ms":1700000000000,"earliest_eviction_at_ms":9223372036854775807},"applied_offsets":{"3":100}}"#,
        );
    }

    #[test]
    fn master_era_bytes_without_redirect_dedup_decode_to_an_empty_map() {
        let master = serde_json::json!({
            "state": {
                "v": "BehavioralSingle",
                "has_match": true,
                "last_event_at_ms": 1_700_000_000_000_i64,
                "earliest_eviction_at_ms": i64::MAX,
            },
            "applied_offsets": { "3": 100 },
        });
        let record = StatefulRecord::decode(&serde_json::to_vec(&master).unwrap()).unwrap();
        assert!(record.redirect_dedup.is_empty());
        assert_eq!(record.applied_offsets, applied(&[(3, 100)]));
    }

    #[test]
    fn non_empty_redirect_dedup_round_trips_per_ancestor() {
        let mut record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied(&[(3, 100)]),
        );
        record
            .redirect_dedup
            .insert(uuid(0xA11CE), applied(&[(5, 9), (6, 2)]));

        let bytes = record.encode();
        assert_eq!(StatefulRecord::decode(&bytes).unwrap(), record);
        let text = String::from_utf8(bytes).unwrap();
        assert!(
            text.contains("redirect_dedup"),
            "a non-empty redirect_dedup must serialize, got: {text}",
        );
    }

    #[test]
    fn merge_max_unions_per_partition_high_water_marks() {
        let mut into = applied(&[(5, 100), (6, 10)]);
        into.merge_max(&applied(&[(5, 50), (6, 20), (7, 1)]));
        assert!(into.is_replay(5, 100));
        assert!(!into.is_replay(5, 101));
        assert!(into.is_replay(6, 20));
        assert!(!into.is_replay(6, 21));
        assert!(into.is_replay(7, 1));
    }

    #[test]
    fn is_replay_for_routes_by_origin() {
        let mut record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied(&[(5, 100)]),
        );
        let ancestor = uuid(0xA11CE);
        record.redirect_dedup.insert(ancestor, applied(&[(5, 200)]));

        // origin = None → main map: offset 100 is a replay, 101 is new.
        assert!(record.is_replay_for(None, 5, 100));
        assert!(!record.is_replay_for(None, 5, 101));
        // A fresh main-map event at offset 150 (above main's 100, below the ancestor's 200) still
        // folds — the ancestor entry does not gate normal events (hazard A).
        assert!(!record.is_replay_for(None, 5, 150));
        // origin = Some(ancestor) → redirect_dedup[ancestor]: 200 is a replay, 201 is new (hazard B).
        assert!(record.is_replay_for(Some(&ancestor), 5, 200));
        assert!(!record.is_replay_for(Some(&ancestor), 5, 201));
        // origin = an unknown ancestor → never a replay (no entry yet).
        assert!(!record.is_replay_for(Some(&uuid(0xBEEF)), 5, 0));
    }

    #[test]
    fn record_for_routes_by_origin_and_creates_entries_on_demand() {
        let mut record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        );
        let ancestor = uuid(0xA11CE);

        record.record_for(None, 5, 100);
        assert!(record.is_replay_for(None, 5, 100));
        assert!(
            record.redirect_dedup.is_empty(),
            "a normal event touches only the main map"
        );

        record.record_for(Some(&ancestor), 5, 200);
        assert!(record.is_replay_for(Some(&ancestor), 5, 200));
        assert!(
            !record.is_replay_for(None, 5, 150),
            "recording into the ancestor map must not advance the main map",
        );
    }

    #[test]
    fn variant_reports_the_state_kind() {
        assert_eq!(behavioral().state.variant(), StateVariant::BehavioralSingle);
        assert_eq!(
            daily().state.variant(),
            StateVariant::BehavioralDailyBuckets
        );
        assert_eq!(
            compressed().state.variant(),
            StateVariant::BehavioralCompressedHistory
        );
    }

    #[test]
    fn eviction_deadline_is_some_for_every_behavioral_variant() {
        assert_eq!(
            behavioral().state.eviction_deadline(),
            Some(1_700_000_000_000 + 7 * 86_400 * 1000),
        );
        assert_eq!(
            daily().state.eviction_deadline(),
            Some(1_700_000_000_000 + 7 * 86_400 * 1000),
        );
        assert_eq!(
            compressed().state.eviction_deadline(),
            Some(1_700_000_000_000 + 365 * 86_400 * 1000),
        );

        // A permanent membership reports the i64::MAX sentinel.
        let permanent = Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: i64::MAX,
        };
        assert_eq!(permanent.eviction_deadline(), Some(i64::MAX));
    }

    #[test]
    fn variant_labels_are_stable() {
        assert_eq!(StateVariant::BehavioralSingle.as_str(), "behavioral_single");
        assert_eq!(
            StateVariant::BehavioralDailyBuckets.as_str(),
            "behavioral_daily_buckets"
        );
        assert_eq!(
            StateVariant::BehavioralCompressedHistory.as_str(),
            "behavioral_compressed_history"
        );
        assert_eq!(StateVariant::PersonProperty.as_str(), "person_property");
    }
}
