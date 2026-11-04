//! Domain layer: the conditions of a run on which only each person's newest scanned day changes
//! stage-1 state, so an older day's tile can be skipped. Depends on `condition`, `ids`, and
//! `cohort-core`.

use std::collections::{BTreeSet, HashMap};

use cohort_core::filters::{LeafStateMeta, TeamFilters};
use cohort_core::{EvictionWindow, StateVariant};

use super::condition::PinnedCondition;
use super::ids::ConditionHash;

/// A condition on which every leaf of the run keeps only its newest matching day. Only
/// [`NewestDayConditions::slot`] hands one out, so an index can only key a qualifying condition.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ConditionSlot(u32);

/// The qualifying conditions of one run, each with a dense slot.
#[derive(Debug)]
pub struct NewestDayConditions(HashMap<ConditionHash, ConditionSlot>);

impl NewestDayConditions {
    /// The processor routes a tile to every leaf on its hash in the team's live catalog. A hash
    /// qualifies only when every leaf on it in this run's frozen catalog does. A live leaf outside
    /// the run gets every day from its own run.
    pub fn of(conditions: &[PinnedCondition], filters: &TeamFilters) -> Self {
        let hashes: BTreeSet<ConditionHash> =
            conditions.iter().map(|condition| condition.hash).collect();
        let qualifying = hashes
            .into_iter()
            .filter(|hash| every_leaf_keeps_only_newest_day(*hash, filters));
        Self(qualifying.zip((0..).map(ConditionSlot)).collect())
    }

    pub fn slot(&self, hash: ConditionHash) -> Option<ConditionSlot> {
        self.0.get(&hash).copied()
    }
}

fn every_leaf_keeps_only_newest_day(hash: ConditionHash, filters: &TeamFilters) -> bool {
    filters
        .by_condition_to_lsk
        .get(&hash.as_bytes())
        .is_some_and(|lsks| {
            !lsks.is_empty()
                && lsks
                    .iter()
                    .all(|lsk| filters.by_lsk.get(lsk).is_some_and(keeps_only_newest_day))
        })
}

/// Whether a leaf's merged state depends on the newest seeded day alone.
///
/// `merge_single` in `cohort-stream-processor/src/workers/seed_path.rs` is the source of truth, and
/// this rule must change with it. It keeps `max(last_event_at, end of the tile's day)`, so an older
/// day's tile leaves the state unchanged. Its drops are monotone in the day: when the newest tile
/// falls before `from_day` or outside its window, every older tile does too. An explicit upper
/// bound breaks that: the newest day can fall after `to_day` and drop, and the leaf then needs the
/// older in-range day. Count variants sum every day.
fn keeps_only_newest_day(meta: &LeafStateMeta) -> bool {
    match (meta.variant, meta.window) {
        (
            StateVariant::BehavioralSingle,
            Some(
                EvictionWindow::RelativeDays { .. }
                | EvictionWindow::RelativeSeconds { .. }
                | EvictionWindow::Explicit { to_day: None, .. },
            ),
        ) => true,
        (
            StateVariant::BehavioralSingle,
            Some(EvictionWindow::Explicit {
                to_day: Some(_), ..
            })
            | None,
        ) => false,
        (
            StateVariant::BehavioralDailyBuckets
            | StateVariant::BehavioralCompressedHistory
            | StateVariant::PersonProperty,
            _,
        ) => false,
    }
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use serde_json::{json, Value};

    use super::*;
    use crate::domain::Lookback;

    const HASH: &str = "aaaaaaaaaaaaaaaa";
    const EVENT: &str = "$pageview";

    fn leaf(shape: Value) -> Value {
        let mut leaf = json!({
            "type": "behavioral",
            "key": EVENT,
            "conditionHash": HASH,
            "bytecode": ["_H", 1, 32, EVENT, 32, "event", 1, 1, 11],
        });
        leaf.as_object_mut()
            .unwrap()
            .extend(shape.as_object().unwrap().clone());
        leaf
    }

    fn sliding(days: u32) -> Value {
        leaf(json!({ "value": "performed_event", "time_value": days, "time_interval": "day" }))
    }

    /// Each leaf is its own cohort, because the processor routes a tile to every cohort's leaves.
    fn qualifies(leaves: &[Value]) -> bool {
        let mut builder = TeamFiltersBuilder::default();
        for (cohort, leaf) in (1..).zip(leaves) {
            builder
                .add_cohort(
                    CohortId(cohort),
                    TeamId(2),
                    &json!({ "properties": { "type": "AND", "values": [leaf] } }),
                )
                .unwrap();
        }
        let filters = builder.freeze(UTC);
        let hash = ConditionHash::parse(HASH).unwrap();
        let conditions = [PinnedCondition {
            cohort_id: CohortId(1),
            hash,
            event_name: EVENT.to_owned(),
            lookback: Lookback::SlidingDays(7),
        }];
        NewestDayConditions::of(&conditions, &filters)
            .slot(hash)
            .is_some()
    }

    #[test]
    fn a_hash_qualifies_only_when_every_leaf_on_it_keeps_only_the_newest_day() {
        let count = leaf(json!({
            "value": "performed_event_multiple",
            "time_value": 14,
            "time_interval": "day",
            "operator": "gte",
            "operator_value": 2,
        }));
        let bounded = leaf(json!({
            "value": "performed_event",
            "explicit_datetime": "2026-01-01",
            "explicit_datetime_to": "2026-02-01",
        }));
        let open_ended = leaf(json!({
            "value": "performed_event",
            "explicit_datetime": "2026-01-01",
        }));
        for (case, leaves, expected) in [
            ("sliding leaves only", vec![sliding(7), sliding(30)], true),
            ("plus a count leaf", vec![sliding(7), count], false),
            (
                "plus an explicit upper bound",
                vec![sliding(7), bounded],
                false,
            ),
            (
                "plus an explicit range with no upper bound",
                vec![sliding(7), open_ended],
                true,
            ),
        ] {
            assert_eq!(qualifies(&leaves), expected, "{case}");
        }
    }
}
