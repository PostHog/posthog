//! Domain layer: pure day/band planning (`plan_days`, `conditions_active_on`, `bands_for_day`)
//! and the split of one chunk's scan by table (`table_scans`). Depends on `pinned`, `condition`,
//! `window`, `ids`, and `cohort-core`.

use std::collections::{BTreeMap, BTreeSet};
use std::num::NonZeroU16;

use cohort_core::bucket_tz::window_start_for_now;

use super::condition::{EventNameSet, Lookback, PinnedCondition};
use super::ids::{Band, ConditionHash, DayIdx};
use super::pinned::{PinnedRun, ScanTable};
use super::window::{Boundary, PlanCaps};

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ActiveConditions(BTreeSet<ConditionHash>);

impl ActiveConditions {
    pub fn new(hashes: impl IntoIterator<Item = ConditionHash>) -> Self {
        Self(hashes.into_iter().collect())
    }

    pub fn contains(&self, hash: &ConditionHash) -> bool {
        self.0.contains(hash)
    }

    pub fn get(&self, hash: &[u8; 16]) -> Option<ConditionHash> {
        self.0.get(hash).copied()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = &ConditionHash> {
        self.0.iter()
    }
}

/// Every day the run seeds, through the last day the live path may have missed the start of.
/// [`Boundary::schedule`] decides when each one may be scanned.
pub fn plan_days(
    conditions: &[PinnedCondition],
    boundary: Boundary,
    caps: &PlanCaps,
) -> BTreeSet<DayIdx> {
    let mut days = BTreeSet::new();
    let Some(last_historical_day) = boundary.day().checked_sub(1) else {
        return days;
    };
    let last_seedable_day = boundary.last_seedable_day(caps.live_tracking_lag);
    let capped_start = window_start_for_now(boundary.day(), caps.max_lookback_days);

    for condition in conditions {
        let (start, end) = match condition.lookback {
            Lookback::SlidingDays(days) => {
                let effective_days = days.min(caps.max_lookback_days);
                if effective_days == 0 {
                    continue;
                }
                (
                    window_start_for_now(boundary.day(), effective_days),
                    last_seedable_day,
                )
            }
            // The processor discards sub-day tiles, and a sub-day gap closes within a day anyway.
            Lookback::SubDay => {
                if caps.max_lookback_days == 0 {
                    continue;
                }
                (last_historical_day, last_historical_day)
            }
            // `from_day` is clamped to the cap like sliding windows are: an explicit_datetime far
            // in the past would otherwise plan one chunk per day since that date, unbounded.
            Lookback::FixedRange { from_day, to_day } => (
                from_day.unwrap_or(capped_start).max(capped_start),
                to_day.unwrap_or(last_seedable_day).min(last_seedable_day),
            ),
        };
        if start > end {
            continue;
        }
        days.extend(start..=end);
    }
    days
}

pub fn conditions_active_on(
    day: DayIdx,
    now_day: DayIdx,
    conditions: &[PinnedCondition],
) -> ActiveConditions {
    ActiveConditions::new(conditions.iter().filter_map(|condition| {
        let active = match condition.lookback {
            Lookback::SlidingDays(days) => {
                window_start_for_now(now_day, days) <= day && day <= now_day
            }
            Lookback::SubDay => window_start_for_now(now_day, 1) <= day && day <= now_day,
            Lookback::FixedRange { from_day, to_day } => {
                from_day.is_none_or(|from| day >= from) && to_day.is_none_or(|to| day <= to)
            }
        };
        active.then_some(condition.hash)
    }))
}

/// The person-hash bands a day is planned into. Each band scans `cityHash64(person) % n = band`,
/// so raising the count bounds one chunk's in-memory aggregate at the cost of re-reading the day's
/// rows per band. Settings validation keeps the count within `i16` (the `band` column's width).
pub fn bands_for_day(_day: DayIdx, bands_per_day: NonZeroU16) -> Vec<Band> {
    (0..bands_per_day.get())
        .map(|band| Band(i16::try_from(band).expect("bands_per_day is validated to fit i16")))
        .collect()
}

/// One table's share of a chunk's scan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TableScan {
    pub event_names: EventNameSet,
    pub active: ActiveConditions,
}

/// The chunk's active event names and active conditions, grouped by the table that holds each
/// event. A table appears only when it has an event name to scan.
pub fn table_scans(run: &PinnedRun, active: &ActiveConditions) -> BTreeMap<ScanTable, TableScan> {
    let mut event_names = BTreeMap::<ScanTable, Vec<String>>::new();
    for event_name in active_event_names(run, active) {
        event_names
            .entry(run.table_for(&event_name))
            .or_default()
            .push(event_name);
    }
    event_names
        .into_iter()
        .map(|(table, names)| {
            let conditions = run
                .conditions
                .iter()
                .filter(|condition| {
                    active.contains(&condition.hash)
                        && run.table_for(&condition.event_name) == table
                })
                .map(|condition| condition.hash);
            let scan = TableScan {
                event_names: EventNameSet::new(names),
                active: ActiveConditions::new(conditions),
            };
            (table, scan)
        })
        .collect()
}

fn active_event_names(run: &PinnedRun, active: &ActiveConditions) -> EventNameSet {
    EventNameSet::new(
        run.event_names
            .iter()
            .filter(|event_name| {
                run.filters
                    .behavioral_by_event_name
                    .get(*event_name)
                    .is_some_and(|bucket| {
                        bucket
                            .conditions
                            .iter()
                            .any(|hash| active.get(hash).is_some())
                    })
            })
            .cloned(),
    )
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use chrono_tz::UTC;
    use cohort_core::filters::CohortId;
    use proptest::prelude::*;

    use super::super::ids::UtcMillis;
    use super::super::pinned::test_runs::{run_with, RunLeaf};
    use super::super::row_filter::test_catalog::event_is;
    use super::*;

    fn condition(hash: &str, lookback: Lookback) -> PinnedCondition {
        PinnedCondition {
            cohort_id: CohortId(1),
            hash: ConditionHash::parse(hash).unwrap(),
            event_name: "event".to_string(),
            lookback,
        }
    }

    #[test]
    fn planning_intersects_ranges_with_the_cap_and_preserves_holes() {
        let boundary = Boundary::new(UtcMillis::new(100 * 86_400_000), UTC);
        let conditions = [
            condition(
                "unbounded0000000",
                Lookback::FixedRange {
                    from_day: None,
                    to_day: Some(94),
                },
            ),
            condition(
                "range00000000000",
                Lookback::FixedRange {
                    from_day: Some(98),
                    to_day: Some(99),
                },
            ),
            // Starts below the cap: clamped to the capped start, keeping only 90..=96.
            condition(
                "straddling000000",
                Lookback::FixedRange {
                    from_day: Some(85),
                    to_day: Some(96),
                },
            ),
            // Entirely below the cap: clamping empties it, so it plans nothing.
            condition(
                "ancient000000000",
                Lookback::FixedRange {
                    from_day: Some(80),
                    to_day: Some(82),
                },
            ),
        ];
        let caps = PlanCaps {
            max_lookback_days: 10,
            ..PlanCaps::default()
        };
        let expected = BTreeSet::from([90, 91, 92, 93, 94, 95, 96, 98, 99]);
        assert_eq!(plan_days(&conditions, boundary, &caps), expected);
    }

    #[test]
    fn open_ended_lookbacks_plan_through_the_last_day_the_live_path_may_have_missed() {
        let caps = PlanCaps {
            live_tracking_lag: Duration::from_secs(420),
            ..PlanCaps::default()
        };
        let boundary_at = |seconds_into_day_100: i64| {
            Boundary::new(
                UtcMillis::new((100 * 86_400 + seconds_into_day_100) * 1000),
                UTC,
            )
        };
        for lookback in [
            Lookback::SlidingDays(2),
            Lookback::FixedRange {
                from_day: Some(98),
                to_day: None,
            },
        ] {
            let conditions = [condition("condition0000000", lookback)];
            assert_eq!(
                plan_days(&conditions, boundary_at(12 * 3_600), &caps),
                BTreeSet::from([98, 99, 100]),
                "{lookback:?} at noon"
            );
            // The live path may start counting after midnight, so the next day is trailing too.
            assert_eq!(
                plan_days(&conditions, boundary_at(86_400 - 300), &caps),
                BTreeSet::from([98, 99, 100, 101]),
                "{lookback:?} five minutes before midnight"
            );
        }
    }

    #[test]
    fn bands_fan_out_zero_indexed() {
        assert_eq!(bands_for_day(0, NonZeroU16::MIN), vec![Band(0)]);
        assert_eq!(
            bands_for_day(5, NonZeroU16::new(3).unwrap()),
            vec![Band(0), Band(1), Band(2)]
        );
    }

    /// Each table's scan narrows to its own conditions, so a condition filed under the wrong table
    /// widens or narrows the other table's projection and row filter.
    #[test]
    fn a_chunk_splits_its_event_names_and_conditions_by_the_table_that_holds_each_event() {
        const PAGEVIEW: &str = "pageview00000000";
        const FLAG_CALL: &str = "flagcall00000000";
        const LOOKALIKE: &str = "lookalike0000000";
        const UNBUCKETED: &str = "unbucketed000000";
        let leaves = || {
            ["$pageview", "$feature_flag_called", "$Feature_Flag_Called"]
                .into_iter()
                .zip([PAGEVIEW, FLAG_CALL, LOOKALIKE])
                .map(|(event, hash)| RunLeaf {
                    cohort_id: 1,
                    hash,
                    event,
                    body: event_is(event),
                })
                .collect::<Vec<_>>()
        };
        let hashes = |hashes: &[&str]| {
            hashes
                .iter()
                .map(|hash| ConditionHash::parse(hash).unwrap())
                .collect::<Vec<_>>()
        };
        let scan = |names: &[&str], active: &[&str]| TableScan {
            event_names: EventNameSet::new(names.iter().map(|name| (*name).to_owned())),
            active: ActiveConditions::new(hashes(active)),
        };
        let active_except = |run: &PinnedRun, inactive: &[&str]| {
            let inactive = hashes(inactive);
            ActiveConditions::new(
                run.conditions
                    .iter()
                    .map(|condition| condition.hash)
                    .filter(|hash| !inactive.contains(hash)),
            )
        };

        let flags = run_with(ScanTable::FlagEvaluations, 7, &leaves());
        assert_eq!(
            table_scans(&flags, &active_except(&flags, &[])),
            BTreeMap::from([
                (
                    ScanTable::Events,
                    scan(
                        &["$Feature_Flag_Called", "$pageview"],
                        &[LOOKALIKE, PAGEVIEW]
                    ),
                ),
                (
                    ScanTable::FlagEvaluations,
                    scan(&["$feature_flag_called"], &[FLAG_CALL]),
                ),
            ])
        );
        assert_eq!(
            table_scans(&flags, &active_except(&flags, &[FLAG_CALL])),
            BTreeMap::from([(
                ScanTable::Events,
                scan(
                    &["$Feature_Flag_Called", "$pageview"],
                    &[LOOKALIKE, PAGEVIEW]
                ),
            )]),
            "a table with no active event name is not scanned"
        );

        // An `events` run scans one table with every active condition, even one whose event name
        // no active bucket holds.
        let mut events = run_with(ScanTable::Events, 7, &leaves());
        events.conditions.push(PinnedCondition {
            cohort_id: CohortId(1),
            hash: ConditionHash::parse(UNBUCKETED).unwrap(),
            event_name: "unbucketed".to_owned(),
            lookback: Lookback::SlidingDays(7),
        });
        assert_eq!(
            table_scans(&events, &active_except(&events, &[])),
            BTreeMap::from([(
                ScanTable::Events,
                scan(
                    &["$Feature_Flag_Called", "$feature_flag_called", "$pageview"],
                    &[FLAG_CALL, LOOKALIKE, PAGEVIEW, UNBUCKETED],
                ),
            )])
        );
    }

    #[test]
    fn active_conditions_expire_sliding_days_and_keep_inclusive_fixed_bounds() {
        let sliding = condition("sliding000000000", Lookback::SlidingDays(2));
        let fixed = condition(
            "fixed00000000000",
            Lookback::FixedRange {
                from_day: Some(95),
                to_day: Some(97),
            },
        );
        let conditions = [sliding.clone(), fixed.clone()];

        let on_97 = conditions_active_on(97, 100, &conditions);
        assert!(!on_97.contains(&sliding.hash));
        assert!(on_97.contains(&fixed.hash));
        let on_98 = conditions_active_on(98, 100, &conditions);
        assert!(on_98.contains(&sliding.hash));
        assert!(!on_98.contains(&fixed.hash));
    }

    proptest! {
        #[test]
        fn planned_days_are_deterministic_and_stay_inside_the_capped_history(
            boundary_day in -20_000i32..20_000,
            cap in 0u16..500,
            live_lag_secs in 0u64..200_000,
            windows in prop::collection::vec(0u16..1_000, 0..20),
            ranges in prop::collection::vec(
                (prop::option::of(-30_000i32..30_000), prop::option::of(-30_000i32..30_000)),
                0..8,
            ),
        ) {
            let boundary = Boundary::new(UtcMillis::new(i64::from(boundary_day) * 86_400_000), UTC);
            let sliding = windows
                .into_iter()
                .map(|days| Lookback::SlidingDays(u32::from(days)));
            let fixed = ranges
                .into_iter()
                .map(|(from_day, to_day)| Lookback::FixedRange { from_day, to_day });
            let conditions = sliding
                .chain(fixed)
                .enumerate()
                .map(|(index, lookback)| condition(&format!("{index:016}"), lookback))
                .collect::<Vec<_>>();
            let caps = PlanCaps {
                max_lookback_days: u32::from(cap),
                live_tracking_lag: Duration::from_secs(live_lag_secs),
                ..PlanCaps::default()
            };
            let first = plan_days(&conditions, boundary, &caps);
            let second = plan_days(&conditions, boundary, &caps);
            prop_assert_eq!(&first, &second);
            let lower = window_start_for_now(boundary.day(), u32::from(cap));
            let upper = boundary.last_seedable_day(caps.live_tracking_lag);
            prop_assert!(first.iter().all(|day| lower <= *day && *day <= upper));
        }
    }
}
