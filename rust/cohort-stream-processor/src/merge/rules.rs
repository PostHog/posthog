//! Per-leaf merge rules: combine P_old's and P_new's state for one `LeafStateKey`.
//!
//! Given both sides' [`StatefulRecord`]s and the leaf's catalog meta, produces the merged record to
//! persist for P_new plus the membership flip it implies.

use std::collections::BTreeMap;

use chrono_tz::Tz;
use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::LeafStateMeta;
use crate::merge::bucket_align::align_and_sum;
use crate::merge::compressed_concat::union_by_day;
use crate::observability::metrics::MERGE_LEAVES_DROPPED_TOTAL;
use crate::stage1::bucket_tz::{daily_bucket_len, now_day_for_window};
use crate::stage1::compressed_history::{compressed_eviction_deadline, slide_window_forward};
use crate::stage1::daily::daily_eviction_deadline;
use crate::stage1::state::{AppliedOffsets, Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::TransitionKind;
use crate::stage2::evaluator::leaf_membership;

#[derive(Debug, Clone, PartialEq)]
pub struct MergedRecord {
    /// The merged record to write for P_new, or `None` to leave the leaf absent (e.g. a
    /// person-property leaf P_new never had, which will be re-evaluated on P_new's next event).
    pub record: Option<StatefulRecord>,
    /// Membership flip if the merge crossed the predicate threshold.
    pub flip: Option<TransitionKind>,
}

/// Merge P_old's leaf state into P_new's for one `LeafStateKey`.
///
/// The merged record keeps P_new's `applied_offsets` (never seeded from P_old) and gains a
/// `redirect_dedup` entry per ancestor so post-merge stragglers stay replay-safe.
pub fn merge_records(
    old_person: Uuid,
    old: &StatefulRecord,
    new: Option<&StatefulRecord>,
    meta: &LeafStateMeta,
    tz: Tz,
) -> MergedRecord {
    // Variant mismatch is a desync — keep P_new untouched.
    if old.state.variant() != meta.variant
        || new.is_some_and(|record| record.state.variant() != meta.variant)
    {
        counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "variant_mismatch").increment(1);
        return keep_new(old_person, old, new);
    }

    // Person properties: drop P_old's bit; P_new re-evaluates lazily on its next event.
    if matches!(meta.variant, StateVariant::PersonProperty) {
        return keep_new(old_person, old, new);
    }

    let merged_state = match new {
        None => old.state.clone(),
        Some(new_record) => match merge_behavioral_pair(meta, &old.state, &new_record.state, tz) {
            Some(state) => state,
            None => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "length_desync").increment(1);
                return keep_new(old_person, old, new);
            }
        },
    };

    let prev_member = leaf_membership(new.map(|record| &record.state), meta);
    let next_member = leaf_membership(Some(&merged_state), meta);

    let applied_offsets = new
        .map(|record| record.applied_offsets.clone())
        .unwrap_or_default();
    let mut redirect_dedup = new
        .map(|record| record.redirect_dedup.clone())
        .unwrap_or_default();
    compose_ancestor_dedup(&mut redirect_dedup, old_person, old);

    MergedRecord {
        record: Some(StatefulRecord {
            state: merged_state,
            applied_offsets,
            redirect_dedup,
        }),
        flip: flip_of(prev_member, next_member),
    }
}

/// Keep P_new's record unchanged (composing the ancestor dedup), or write nothing when P_new had no
/// record.
fn keep_new(old_person: Uuid, old: &StatefulRecord, new: Option<&StatefulRecord>) -> MergedRecord {
    let record = new.cloned().map(|mut record| {
        compose_ancestor_dedup(&mut record.redirect_dedup, old_person, old);
        record
    });
    MergedRecord { record, flip: None }
}

/// Fold P_old's offsets into `redirect_dedup`. P_old becomes an ancestor under its own uuid; its own
/// ancestors carry forward under their original origins (keyed, not unioned).
fn compose_ancestor_dedup(
    redirect_dedup: &mut BTreeMap<Uuid, AppliedOffsets>,
    old_person: Uuid,
    old: &StatefulRecord,
) {
    redirect_dedup
        .entry(old_person)
        .or_default()
        .merge_max(&old.applied_offsets);
    for (ancestor, offsets) in &old.redirect_dedup {
        redirect_dedup
            .entry(*ancestor)
            .or_default()
            .merge_max(offsets);
    }
}

/// Merge two same-variant behavioral states (both present). Returns `None` on a structural desync
/// (e.g. daily array length disagreeing with the window).
fn merge_behavioral_pair(
    meta: &LeafStateMeta,
    old: &Stage1State,
    new: &Stage1State,
    tz: Tz,
) -> Option<Stage1State> {
    match (old, new) {
        (
            Stage1State::BehavioralSingle {
                last_event_at_ms: old_last,
                earliest_eviction_at_ms: old_deadline,
                ..
            },
            Stage1State::BehavioralSingle {
                last_event_at_ms: new_last,
                earliest_eviction_at_ms: new_deadline,
                ..
            },
        ) => Some(Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: (*old_last).max(*new_last),
            earliest_eviction_at_ms: (*old_deadline).max(*new_deadline),
        }),

        (
            Stage1State::BehavioralDailyBuckets {
                buckets: old_buckets,
                window_start_day: old_start,
                last_event_at_ms: old_last,
                ..
            },
            Stage1State::BehavioralDailyBuckets {
                buckets: new_buckets,
                window_start_day: new_start,
                last_event_at_ms: new_last,
                ..
            },
        ) => {
            let window_days = meta
                .window_days
                .unwrap_or_else(|| old_buckets.len().saturating_sub(1) as u32);
            let expected_len = daily_bucket_len(window_days);
            if old_buckets.len() != expected_len || new_buckets.len() != expected_len {
                return None;
            }
            let (buckets, window_start_day) = align_and_sum(
                old_buckets,
                *old_start,
                new_buckets,
                *new_start,
                window_days,
            );
            let earliest_eviction_at_ms =
                daily_eviction_deadline(&buckets, window_start_day, window_days, tz);
            Some(Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                last_event_at_ms: (*old_last).max(*new_last),
                earliest_eviction_at_ms,
            })
        }

        (
            Stage1State::BehavioralCompressedHistory {
                entries: old_entries,
                window_start_day: old_start,
                last_event_at_ms: old_last,
                ..
            },
            Stage1State::BehavioralCompressedHistory {
                entries: new_entries,
                window_start_day: new_start,
                last_event_at_ms: new_last,
                ..
            },
        ) => {
            // The merged state is evaluated immediately by `compressed_predicate`, which sums every
            // entry with no window bound. Slide both sides to the merged anchor (the more-recent of
            // the two starts) first so out-of-window entries are dropped before the union — mirroring
            // the daily arm's `align_and_sum`. Without this the count is inflated until the next sweep.
            let (entries, window_start_day) = match meta.window_days {
                Some(window_days) => {
                    let target_now_day =
                        now_day_for_window((*old_start).max(*new_start), window_days);
                    let mut old_entries = old_entries.clone();
                    let mut old_start = *old_start;
                    slide_window_forward(
                        &mut old_entries,
                        &mut old_start,
                        window_days,
                        target_now_day,
                    );
                    let mut new_entries = new_entries.clone();
                    let mut new_start = *new_start;
                    slide_window_forward(
                        &mut new_entries,
                        &mut new_start,
                        window_days,
                        target_now_day,
                    );
                    union_by_day(&old_entries, old_start, &new_entries, new_start)
                }
                // Meta desync (no finite window to slide to): union as-is.
                None => union_by_day(old_entries, *old_start, new_entries, *new_start),
            };
            let earliest_eviction_at_ms = match meta.window_days {
                Some(window_days) => compressed_eviction_deadline(&entries, window_days, tz),
                // Meta desync: fail safe (never evict); next event-path fold recomputes.
                None => i64::MAX,
            };
            Some(Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                last_event_at_ms: (*old_last).max(*new_last),
                earliest_eviction_at_ms,
            })
        }

        _ => Some(new.clone()),
    }
}

fn flip_of(prev_member: bool, next_member: bool) -> Option<TransitionKind> {
    match (prev_member, next_member) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;

    use crate::stage1::pick_state::{EvictionWindow, PredicateOp};
    use crate::stage1::predicate::compressed_predicate;

    const TZ: Tz = UTC;

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn single_meta() -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralSingle,
            condition_hash: [0; 16],
            window: Some(EvictionWindow::RelativeDays { days: 7 }),
            window_days: None,
            predicate_op: None,
        }
    }

    fn daily_meta(window_days: u32, op: PredicateOp) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralDailyBuckets,
            condition_hash: [0; 16],
            window: None,
            window_days: Some(window_days),
            predicate_op: Some(op),
        }
    }

    fn compressed_meta(window_days: u32, op: PredicateOp) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralCompressedHistory,
            window_days: Some(window_days),
            predicate_op: Some(op),
            ..single_meta()
        }
    }

    fn person_meta() -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::PersonProperty,
            condition_hash: [0; 16],
            window: None,
            window_days: None,
            predicate_op: None,
        }
    }

    fn single(last: i64, deadline: i64) -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: last,
                earliest_eviction_at_ms: deadline,
            },
            AppliedOffsets::default(),
        )
    }

    fn daily(buckets: Vec<u32>, window_start_day: i32) -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                last_event_at_ms: 1_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        )
    }

    fn compressed(entries: Vec<(i32, u32)>, window_start_day: i32) -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                last_event_at_ms: 1_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        )
    }

    fn person(matches: bool, last: i64) -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::PersonProperty {
                matches,
                last_updated_at_ms: last,
                last_updated_offset: 0,
            },
            AppliedOffsets::default(),
        )
    }

    fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
        let mut applied = AppliedOffsets::default();
        for &(partition, offset) in entries {
            applied.record(partition, offset);
        }
        applied
    }

    #[test]
    fn single_ors_match_and_maxes_the_deadline() {
        let merged = merge_records(
            uuid(1),
            &single(100, 500),
            Some(&single(200, 400)),
            &single_meta(),
            TZ,
        );
        match merged.record.unwrap().state {
            Stage1State::BehavioralSingle {
                has_match,
                last_event_at_ms,
                earliest_eviction_at_ms,
            } => {
                assert!(has_match);
                assert_eq!(last_event_at_ms, 200, "max of the two last-event times");
                assert_eq!(earliest_eviction_at_ms, 500, "longest-surviving deadline");
            }
            other => panic!("expected single, got {other:?}"),
        }
        assert_eq!(merged.flip, None, "both sides were already members");
    }

    #[test]
    fn single_into_absent_new_migrates_and_enters() {
        let merged = merge_records(uuid(1), &single(100, 500), None, &single_meta(), TZ);
        assert_eq!(
            merged.flip,
            Some(TransitionKind::Entered),
            "P_new had no single, so inheriting P_old's makes it a member",
        );
        assert!(matches!(
            merged.record.unwrap().state,
            Stage1State::BehavioralSingle {
                has_match: true,
                ..
            }
        ));
    }

    #[test]
    fn daily_aligns_and_sums_per_the_worked_example() {
        let meta = daily_meta(6, PredicateOp::Gte(1));
        let merged = merge_records(
            uuid(1),
            &daily(vec![2, 0, 1, 3, 0, 1, 5], 19_500),
            Some(&daily(vec![0, 1, 2, 0, 1, 0, 4], 19_501)),
            &meta,
            TZ,
        );
        match merged.record.unwrap().state {
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                ..
            } => {
                assert_eq!(buckets, vec![0, 2, 5, 0, 2, 5, 4]);
                assert_eq!(window_start_day, 19_501);
            }
            other => panic!("expected daily, got {other:?}"),
        }
    }

    #[test]
    fn daily_count_crossing_the_threshold_enters() {
        let meta = daily_meta(2, PredicateOp::Gte(3));
        let merged = merge_records(
            uuid(1),
            &daily(vec![0, 0, 2], 100),
            Some(&daily(vec![0, 0, 1], 100)),
            &meta,
            TZ,
        );
        assert_eq!(merged.flip, Some(TransitionKind::Entered));
        match merged.record.unwrap().state {
            Stage1State::BehavioralDailyBuckets { buckets, .. } => {
                assert_eq!(buckets, vec![0, 0, 3])
            }
            other => panic!("expected daily, got {other:?}"),
        }
    }

    #[test]
    fn daily_length_desync_keeps_new() {
        let meta = daily_meta(7, PredicateOp::Gte(1));
        let old = daily(vec![1, 2, 3], 100);
        let new = daily(vec![0u32; 8], 100);
        let merged = merge_records(uuid(1), &old, Some(&new), &meta, TZ);
        assert_eq!(merged.flip, None);
        match merged.record.unwrap().state {
            Stage1State::BehavioralDailyBuckets { buckets, .. } => {
                assert_eq!(buckets.len(), 8, "kept P_new's well-formed array")
            }
            other => panic!("expected daily, got {other:?}"),
        }
    }

    #[test]
    fn compressed_unions_by_day_and_sums_shared_days() {
        let meta = compressed_meta(365, PredicateOp::Gte(1));
        let merged = merge_records(
            uuid(1),
            &compressed(vec![(100, 2), (200, 1)], 50),
            Some(&compressed(vec![(150, 3), (200, 4)], 60)),
            &meta,
            TZ,
        );
        match merged.record.unwrap().state {
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                ..
            } => {
                assert_eq!(entries, vec![(100, 2), (150, 3), (200, 5)]);
                assert_eq!(window_start_day, 60, "the more recent anchor");
            }
            other => panic!("expected compressed, got {other:?}"),
        }
    }

    #[test]
    fn compressed_drops_entries_below_the_merged_anchor_before_counting() {
        // Old is anchored older (start 0, window 10 ⇒ window [0..=10]) with a heavy day-4 entry that
        // is in-window for old but falls below the merged anchor (5, the more-recent/new start). New
        // (start 5, window [5..=15]) has a light day-12 entry. The merge is evaluated immediately, so
        // the day-4 entry must be sliced out before the union — otherwise its count inflates the sum.
        let op = PredicateOp::Gte(6);
        let meta = compressed_meta(10, op);
        let merged = merge_records(
            uuid(1),
            &compressed(vec![(4, 5), (8, 1)], 0),
            Some(&compressed(vec![(12, 1)], 5)),
            &meta,
            TZ,
        );
        match &merged.record.as_ref().unwrap().state {
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                ..
            } => {
                assert_eq!(
                    *entries,
                    vec![(8, 1), (12, 1)],
                    "the day-4 entry is below the merged anchor (5) and is dropped",
                );
                assert_eq!(*window_start_day, 5, "the more recent anchor");
                // Sum over the in-window entries is 2; the dropped day-4 (count 5) does not push it to
                // the Gte(6) threshold. Without the slide the entries would be [(4,5),(8,1),(12,1)],
                // sum 7 ≥ 6 ⇒ a (wrong) member.
                assert!(
                    !compressed_predicate(entries, op),
                    "the out-of-window day-4 count must not contribute to membership",
                );
            }
            other => panic!("expected compressed, got {other:?}"),
        }
        assert_eq!(
            merged.flip, None,
            "new alone (count 1) was not a member and the slid merge (count 2) is still under Gte(6)",
        );
    }

    #[test]
    fn compressed_window_days_desync_fails_safe_to_never_evict() {
        let meta = LeafStateMeta {
            variant: StateVariant::BehavioralCompressedHistory,
            window_days: None,
            predicate_op: Some(PredicateOp::Gte(1)),
            ..single_meta()
        };
        let merged = merge_records(
            uuid(1),
            &compressed(vec![(100, 2), (200, 1)], 50),
            Some(&compressed(vec![(150, 3)], 60)),
            &meta,
            TZ,
        )
        .record
        .unwrap();
        match merged.state {
            Stage1State::BehavioralCompressedHistory {
                earliest_eviction_at_ms,
                ..
            } => assert_eq!(
                earliest_eviction_at_ms,
                i64::MAX,
                "window_days desync fails safe to never-evict",
            ),
            other => panic!("expected compressed, got {other:?}"),
        }
    }

    #[test]
    fn person_property_keeps_new_and_drops_old() {
        let merged = merge_records(
            uuid(1),
            &person(true, 100),
            Some(&person(false, 200)),
            &person_meta(),
            TZ,
        );
        assert_eq!(merged.flip, None);
        assert!(matches!(
            merged.record.unwrap().state,
            Stage1State::PersonProperty { matches: false, .. }
        ));
    }

    #[test]
    fn person_property_with_absent_new_writes_nothing() {
        let merged = merge_records(uuid(1), &person(true, 100), None, &person_meta(), TZ);
        assert_eq!(merged.record, None, "no state migrated for P_new");
        assert_eq!(merged.flip, None);
    }

    #[test]
    fn merged_record_keeps_p_news_main_map_and_adds_an_ancestor_entry() {
        let mut old = single(100, 500);
        old.applied_offsets = applied(&[(5, 100), (6, 7)]);
        let mut new = single(200, 400);
        new.applied_offsets = applied(&[(5, 50)]);

        let merged = merge_records(uuid(0xA11CE), &old, Some(&new), &single_meta(), TZ)
            .record
            .unwrap();
        assert!(merged.applied_offsets.is_replay(5, 50));
        assert!(!merged.applied_offsets.is_replay(5, 51));
        let ancestor = &merged.redirect_dedup[&uuid(0xA11CE)];
        assert!(ancestor.is_replay(5, 100) && ancestor.is_replay(6, 7));
        assert!(!ancestor.is_replay(5, 101));
    }

    #[test]
    fn chained_merge_carries_grandparent_ancestry_keyed() {
        let grandparent = uuid(0x6172);
        let p_old = uuid(0xA11CE);
        let mut old = single(100, 500);
        old.applied_offsets = applied(&[(5, 100)]);
        old.redirect_dedup.insert(grandparent, applied(&[(9, 42)]));

        let new = single(200, 400);
        let merged = merge_records(p_old, &old, Some(&new), &single_meta(), TZ)
            .record
            .unwrap();
        assert!(
            merged.redirect_dedup[&p_old].is_replay(5, 100),
            "P_old is an ancestor under its own uuid",
        );
        assert!(
            merged.redirect_dedup[&grandparent].is_replay(9, 42),
            "P_old's own ancestor carries forward under the grandparent's origin",
        );
    }

    #[test]
    fn variant_mismatch_keeps_new_defensively() {
        let merged = merge_records(
            uuid(1),
            &person(true, 100),
            Some(&single(200, 400)),
            &single_meta(),
            TZ,
        );
        assert_eq!(merged.flip, None);
        assert!(
            matches!(
                merged.record.unwrap().state,
                Stage1State::BehavioralSingle { .. }
            ),
            "P_new's single is kept; P_old's mismatched state is not migrated",
        );
    }

    #[test]
    fn single_merge_then_fold_equals_fold_then_merge() {
        let old = single(100, 500);
        let new = single(200, 400);

        let merged = merge_records(uuid(1), &old, Some(&new), &single_meta(), TZ)
            .record
            .unwrap();
        let (m_match, m_last) = match merged.state {
            Stage1State::BehavioralSingle {
                has_match,
                last_event_at_ms,
                ..
            } => (has_match, last_event_at_ms.max(300)),
            other => panic!("expected single, got {other:?}"),
        };

        let new_folded = single(300, 400);
        let merged2 = merge_records(uuid(1), &old, Some(&new_folded), &single_meta(), TZ)
            .record
            .unwrap();
        let (f_match, f_last) = match merged2.state {
            Stage1State::BehavioralSingle {
                has_match,
                last_event_at_ms,
                ..
            } => (has_match, last_event_at_ms),
            other => panic!("expected single, got {other:?}"),
        };

        assert_eq!((m_match, m_last), (f_match, f_last));
    }
}
