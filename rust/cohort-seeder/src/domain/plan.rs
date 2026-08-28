//! Domain layer: pure day/band planning — `plan_days`, `conditions_active_on`, `bands_for_day`.
//! Depends on `condition`, `window`, `ids`, and `cohort-core`.

use std::collections::BTreeSet;
use std::num::NonZeroU16;

use cohort_core::bucket_tz::window_start_for_now;

use super::condition::{Lookback, PinnedCondition};
use super::ids::{Band, ConditionHash, DayIdx};
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

pub fn plan_days(
    conditions: &[PinnedCondition],
    boundary: Boundary,
    caps: &PlanCaps,
) -> BTreeSet<DayIdx> {
    let mut days = BTreeSet::new();
    let Some(last_historical_day) = boundary.day().checked_sub(1) else {
        return days;
    };
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
                    last_historical_day,
                )
            }
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
                to_day
                    .unwrap_or(last_historical_day)
                    .min(last_historical_day),
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

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::filters::CohortId;
    use proptest::prelude::*;

    use super::super::ids::UtcMillis;
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
    fn bands_fan_out_zero_indexed() {
        assert_eq!(bands_for_day(0, NonZeroU16::MIN), vec![Band(0)]);
        assert_eq!(
            bands_for_day(5, NonZeroU16::new(3).unwrap()),
            vec![Band(0), Band(1), Band(2)]
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
            let caps = PlanCaps { max_lookback_days: u32::from(cap), ..PlanCaps::default() };
            let first = plan_days(&conditions, boundary, &caps);
            let second = plan_days(&conditions, boundary, &caps);
            prop_assert_eq!(&first, &second);
            let lower = window_start_for_now(boundary.day(), u32::from(cap));
            prop_assert!(first.iter().all(|day| lower <= *day && *day < boundary.day()));
        }
    }
}
