//! Per-leaf Stage 1 state, its persisted wrapper, and the value codec.
//!
//! The internal `#[serde(tag = "v")]` discriminator makes adding the `performed_event_multiple`
//! bucket variants a purely additive change to the on-disk form.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Which state representation a leaf uses; recorded per [`crate::stage1::key::LeafStateKey`] so the
/// worker can pick the apply path without decoding stored state first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StateVariant {
    /// `performed_event`: a single "has any matching event in window" bit.
    BehavioralSingle,
    /// `performed_event_multiple` with a `1..=180`-day window: dense per-calendar-day counts in the
    /// team timezone, with a count comparator (the leaf's [`PredicateOp`]) on their sum.
    ///
    /// [`PredicateOp`]: crate::stage1::pick_state::PredicateOp
    BehavioralDailyBuckets,
    /// `performed_event_multiple` with a window over 180 days: sparse run-length per-calendar-day
    /// counts in the team timezone (the compressed analog of [`Self::BehavioralDailyBuckets`]), with
    /// the same count comparator on their sum.
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
        /// deadline. Computed and stored but not yet read; the event path never reads a wall clock.
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
    /// A person-property filter: last-write-wins, tie-broken by event-time argMax
    /// (`argMax(matches, (_timestamp, _offset))`).
    PersonProperty {
        matches: bool,
        /// The argMax key's first component.
        last_updated_at_ms: i64,
        /// The argMax key's tiebreaker second component.
        last_updated_offset: i64,
    },
}

impl Stage1State {
    pub fn variant(&self) -> StateVariant {
        match self {
            Self::BehavioralSingle { .. } => StateVariant::BehavioralSingle,
            Self::BehavioralDailyBuckets { .. } => StateVariant::BehavioralDailyBuckets,
            Self::BehavioralCompressedHistory { .. } => StateVariant::BehavioralCompressedHistory,
            Self::PersonProperty { .. } => StateVariant::PersonProperty,
        }
    }
}

/// Per-source-partition last-applied offsets: `source_partition → last_applied_offset`.
///
/// The shuffler re-keys events by `hash(team_id, person_id)`, so one person's events span multiple
/// source partitions. A single scalar pair would only dedup replays *within* one source partition;
/// a non-idempotent fold (`buckets[i] += 1`) would then double-count on a Kafka replay arriving from
/// a *different* source partition. One high-water mark per source partition closes that window (L11).
///
/// `BTreeMap` (not `HashMap`/`SmallVec`) so the serialized form has deterministic, sorted keys and
/// the shadow diff stays byte-stable; the container is private behind the newtype so a later perf
/// swap is a one-file change. Bounded by the source topic's partition count
/// (`clickhouse_events_json` = 512), realistically a handful per person — **no eviction**, since
/// evicting an entry would re-open the very replay window this closes.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct AppliedOffsets(BTreeMap<i32, i64>);

impl AppliedOffsets {
    /// `true` ⇒ this `(source_partition, source_offset)` was already folded into the key's state, so
    /// a non-idempotent fold must **skip** it. An absent partition key means "never seen" — not a
    /// replay — so offset `0` is a valid first offset (seen-ness is key presence, not a sentinel
    /// value).
    pub fn is_replay(&self, source_partition: i32, source_offset: i64) -> bool {
        self.0
            .get(&source_partition)
            .is_some_and(|&last| source_offset <= last)
    }

    /// Advance the high-water mark for `source_partition` to cover `source_offset`. Monotonic per
    /// partition: a lower offset for an already-recorded partition never regresses it.
    pub fn record(&mut self, source_partition: i32, source_offset: i64) {
        self.0
            .entry(source_partition)
            .and_modify(|last| *last = (*last).max(source_offset))
            .or_insert(source_offset);
    }
}

/// The persisted `cf_stage1` value: a [`Stage1State`] plus the per-source-partition offsets already
/// folded into it, which makes non-idempotent folds replay-safe via [`AppliedOffsets::is_replay`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatefulRecord {
    pub state: Stage1State,
    pub applied_offsets: AppliedOffsets,
}

/// A failure decoding a stored [`StatefulRecord`]; surfaced (never panicked) so a single corrupt
/// row is skipped rather than taking down the worker.
#[derive(Debug, thiserror::Error)]
#[error("decoding Stage1 record: {0}")]
pub struct StateCodecError(#[from] serde_json::Error);

impl StatefulRecord {
    /// Infallible for these plain structs — `serde_json` only errors on a refusing `Serialize` or
    /// non-string map keys, neither of which occurs here.
    pub fn encode(&self) -> Vec<u8> {
        serde_json::to_vec(self).expect("StatefulRecord is plain data and always serializes")
    }

    /// Garbage bytes and unknown `"v"` tags both yield an [`Err`] (forward-compat), never a panic.
    pub fn decode(bytes: &[u8]) -> Result<Self, StateCodecError> {
        Ok(serde_json::from_slice(bytes)?)
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
        StatefulRecord {
            state: Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 7 * 86_400 * 1000,
            },
            applied_offsets: applied(&[(17, 42)]),
        }
    }

    fn person() -> StatefulRecord {
        StatefulRecord {
            state: Stage1State::PersonProperty {
                matches: false,
                last_updated_at_ms: 1_700_000_000_123,
                last_updated_offset: 99,
            },
            applied_offsets: applied(&[(3, 100)]),
        }
    }

    fn daily() -> StatefulRecord {
        StatefulRecord {
            state: Stage1State::BehavioralDailyBuckets {
                buckets: vec![0, 2, 0, 1, 3, 0, 1, 5],
                window_start_day: 20_600,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 7 * 86_400 * 1000,
            },
            applied_offsets: applied(&[(4, 7), (9, 2)]),
        }
    }

    fn compressed() -> StatefulRecord {
        StatefulRecord {
            state: Stage1State::BehavioralCompressedHistory {
                entries: vec![(20_240, 2), (20_400, 1), (20_605, 5)],
                window_start_day: 20_240,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 365 * 86_400 * 1000,
            },
            applied_offsets: applied(&[(4, 7), (9, 2)]),
        }
    }

    #[test]
    fn round_trips_every_variant() {
        for record in [behavioral(), person(), daily(), compressed()] {
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
        // Entries serialize as nested `[day, count]` arrays; pin the on-disk form so a future codec
        // change is caught.
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
        // An unknown state tag must surface as Err, not silently mis-deserialize. `applied_offsets`
        // is valid so the failure is the inner unknown variant, not a missing outer field.
        let forward = serde_json::json!({
            "state": { "v": "BehavioralHourlyBuckets", "buckets": [1, 2, 3] },
            "applied_offsets": { "0": 0 },
        });
        let bytes = serde_json::to_vec(&forward).unwrap();
        assert!(StatefulRecord::decode(&bytes).is_err());
    }

    #[test]
    fn old_scalar_format_fails_to_decode_rather_than_silently_defaulting() {
        // Migration guard: the pre-L11 `{last_applied_partition, last_applied_offset}` shape must
        // fail-decode (worker skips + counts, rewrites on the next event) — NOT deserialize into an
        // empty `applied_offsets`. A silent default would drop the high-water marks and re-open the
        // exact double-count L11 closes, so `applied_offsets` must never carry `#[serde(default)]`.
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
        // Seen-ness is key presence, not a sentinel value: a *re*-seen 0 is a replay.
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
        // Partition 6 far behind 5 must neither mask a new event on 6 nor a replay on 5.
        assert!(applied.is_replay(5, 100));
        assert!(!applied.is_replay(6, 11));
        assert!(applied.is_replay(6, 10));
    }

    #[test]
    fn applied_offsets_serializes_with_sorted_partition_keys() {
        // Inserted out of order; the BTreeMap must serialize keys in ascending integer order so the
        // shadow diff is byte-stable regardless of arrival order.
        let applied = applied(&[(17, 1), (2, 2), (5, 3)]);
        assert_eq!(
            serde_json::to_string(&applied).unwrap(),
            r#"{"2":2,"5":3,"17":1}"#,
        );
    }

    #[test]
    fn multi_entry_record_round_trips_with_sorted_keys() {
        let record = StatefulRecord {
            state: Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied_offsets: applied(&[(3, 100), (7, 5), (1, 0)]),
        };
        let bytes = record.encode();
        assert_eq!(StatefulRecord::decode(&bytes).unwrap(), record);
        let text = String::from_utf8(bytes).unwrap();
        assert!(
            text.contains(r#""applied_offsets":{"1":0,"3":100,"7":5}"#),
            "applied_offsets must serialize with sorted partition keys, got: {text}",
        );
    }

    #[test]
    fn variant_reports_the_state_kind() {
        assert_eq!(behavioral().state.variant(), StateVariant::BehavioralSingle);
        assert_eq!(person().state.variant(), StateVariant::PersonProperty);
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
