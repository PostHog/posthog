use std::collections::BTreeSet;

use chrono_tz::Tz;
use cohort_core::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};

use crate::ids::{ConditionHash, DayIdx, SChunkMs};
use crate::pinned::{Lookback, PinnedCondition};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Boundary {
    at_ms: i64,
    day: DayIdx,
}

impl Boundary {
    pub fn new(at_ms: i64, tz: Tz) -> Self {
        Self {
            at_ms,
            day: day_idx_in_tz(at_ms, tz),
        }
    }

    pub const fn at_ms(self) -> i64 {
        self.at_ms
    }

    pub const fn day(self) -> DayIdx {
        self.day
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlanCaps {
    pub max_lookback_days: u32,
}

impl Default for PlanCaps {
    fn default() -> Self {
        Self {
            max_lookback_days: 400,
        }
    }
}

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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SeedDomain {
    day: DayIdx,
    tz: Tz,
    day_start_utc_ms: i64,
    day_end_utc_ms: i64,
    s_chunk: SChunkMs,
}

impl SeedDomain {
    pub fn new(
        day: DayIdx,
        boundary: Boundary,
        tz: Tz,
        s_chunk: SChunkMs,
    ) -> Result<Self, DomainError> {
        if day >= boundary.day {
            return Err(DomainError::AtOrAfterBoundary {
                day,
                boundary_day: boundary.day,
            });
        }
        let next_day = day.checked_add(1).ok_or(DomainError::DayOverflow(day))?;
        let day_start_utc_ms = start_of_day_ms_in_tz(day, tz);
        let day_end_utc_ms = start_of_day_ms_in_tz(next_day, tz);
        if day_start_utc_ms > day_end_utc_ms {
            return Err(DomainError::InvalidUtcRange {
                day,
                start_ms: day_start_utc_ms,
                end_ms: day_end_utc_ms,
            });
        }
        Ok(Self {
            day,
            tz,
            day_start_utc_ms,
            day_end_utc_ms,
            s_chunk,
        })
    }

    pub const fn day(&self) -> DayIdx {
        self.day
    }

    pub const fn s_chunk(&self) -> SChunkMs {
        self.s_chunk
    }

    pub const fn utc_range(&self) -> (i64, i64) {
        (self.day_start_utc_ms, self.day_end_utc_ms)
    }

    pub const fn is_empty(&self) -> bool {
        self.day_start_utc_ms == self.day_end_utc_ms
    }

    pub fn contains(&self, event_ts_ms: i64) -> bool {
        day_idx_in_tz(event_ts_ms, self.tz) == self.day
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum DomainError {
    #[error("seed day {day} is not before boundary day {boundary_day}")]
    AtOrAfterBoundary { day: DayIdx, boundary_day: DayIdx },
    #[error("seed day {0} has no representable successor")]
    DayOverflow(DayIdx),
    #[error("seed day {day} produced invalid UTC range [{start_ms}, {end_ms})")]
    InvalidUtcRange {
        day: DayIdx,
        start_ms: i64,
        end_ms: i64,
    },
}

pub fn plan_days(
    conditions: &[PinnedCondition],
    boundary: Boundary,
    caps: &PlanCaps,
) -> BTreeSet<DayIdx> {
    let mut days = BTreeSet::new();
    let Some(last_historical_day) = boundary.day.checked_sub(1) else {
        return days;
    };
    let capped_start = subtract_days(boundary.day, caps.max_lookback_days);

    for condition in conditions {
        let (start, end) = match condition.lookback {
            Lookback::SlidingDays(days) => {
                let effective_days = days.min(caps.max_lookback_days);
                if effective_days == 0 {
                    continue;
                }
                (
                    subtract_days(boundary.day, effective_days),
                    last_historical_day,
                )
            }
            Lookback::SubDay => {
                if caps.max_lookback_days == 0 {
                    continue;
                }
                (last_historical_day, last_historical_day)
            }
            Lookback::FixedRange { from_day, to_day } => (
                from_day.unwrap_or(capped_start),
                to_day
                    .unwrap_or(last_historical_day)
                    .min(last_historical_day),
            ),
            Lookback::Dropped => continue,
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
            Lookback::SlidingDays(days) => subtract_days(now_day, days) <= day && day <= now_day,
            Lookback::SubDay => subtract_days(now_day, 1) <= day && day <= now_day,
            Lookback::FixedRange { from_day, to_day } => {
                from_day.is_none_or(|from| day >= from) && to_day.is_none_or(|to| day <= to)
            }
            Lookback::Dropped => false,
        };
        active.then_some(condition.hash)
    }))
}

fn subtract_days(day: DayIdx, days: u32) -> DayIdx {
    i64::from(day)
        .saturating_sub(i64::from(days))
        .clamp(i64::from(DayIdx::MIN), i64::from(DayIdx::MAX)) as DayIdx
}

#[cfg(test)]
mod tests {
    use chrono::{NaiveDate, TimeZone, Utc};
    use chrono_tz::America::New_York;
    use chrono_tz::Pacific::Apia;
    use chrono_tz::UTC;
    use cohort_core::filters::CohortId;
    use cohort_core::stage1::bucket_tz::day_idx_of_naive_date;
    use proptest::prelude::*;

    use super::*;

    fn condition(hash: &str, lookback: Lookback) -> PinnedCondition {
        PinnedCondition {
            cohort_id: CohortId(1),
            hash: ConditionHash::parse(hash).unwrap(),
            event_name: Some("event".to_string()),
            lookback,
        }
    }

    #[test]
    fn planning_intersects_ranges_with_the_cap_and_preserves_holes() {
        let boundary = Boundary::new(100 * 86_400_000, UTC);
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
            condition(
                "oldrange00000000",
                Lookback::FixedRange {
                    from_day: Some(80),
                    to_day: Some(82),
                },
            ),
            condition("dropped000000000", Lookback::Dropped),
        ];
        let caps = PlanCaps {
            max_lookback_days: 10,
        };
        let expected = BTreeSet::from([80, 81, 82, 90, 91, 92, 93, 94, 98, 99]);
        assert_eq!(plan_days(&conditions, boundary, &caps), expected);
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
        let dropped = condition("dropped000000000", Lookback::Dropped);
        let conditions = [sliding.clone(), fixed.clone(), dropped];

        let on_97 = conditions_active_on(97, 100, &conditions);
        assert!(!on_97.contains(&sliding.hash));
        assert!(on_97.contains(&fixed.hash));
        let on_98 = conditions_active_on(98, 100, &conditions);
        assert!(on_98.contains(&sliding.hash));
        assert!(!on_98.contains(&fixed.hash));
    }

    #[test]
    fn seed_domain_excludes_the_boundary_day_and_uses_dst_exact_half_open_ranges() {
        let spring_day = day_idx_in_tz(
            Utc.with_ymd_and_hms(2026, 3, 8, 12, 0, 0)
                .unwrap()
                .timestamp_millis(),
            New_York,
        );
        let boundary = Boundary::new(start_of_day_ms_in_tz(spring_day + 1, New_York), New_York);
        assert!(matches!(
            SeedDomain::new(
                boundary.day(),
                boundary,
                New_York,
                SChunkMs(boundary.at_ms())
            ),
            Err(DomainError::AtOrAfterBoundary { .. })
        ));

        let domain =
            SeedDomain::new(spring_day, boundary, New_York, SChunkMs(boundary.at_ms())).unwrap();
        let (start, end) = domain.utc_range();
        assert_eq!(end - start, 23 * 3_600_000);
        assert!(domain.contains(start));
        assert!(domain.contains(end - 1));
        assert!(!domain.contains(end));
    }

    #[test]
    fn skipped_civil_day_is_vacuous_without_truncating_its_neighbors() {
        let day = |year, month, day| {
            day_idx_of_naive_date(NaiveDate::from_ymd_opt(year, month, day).unwrap())
        };
        let preceding = day(2011, 12, 29);
        let skipped = day(2011, 12, 30);
        let following = day(2011, 12, 31);
        let boundary = Boundary::new(
            Utc.with_ymd_and_hms(2012, 1, 2, 0, 0, 0)
                .unwrap()
                .timestamp_millis(),
            Apia,
        );
        let domain =
            |day| SeedDomain::new(day, boundary, Apia, SChunkMs(boundary.at_ms())).unwrap();

        let preceding_domain = domain(preceding);
        let skipped_domain = domain(skipped);
        let following_domain = domain(following);
        assert_eq!(
            preceding_domain.utc_range(),
            (
                Utc.with_ymd_and_hms(2011, 12, 29, 10, 0, 0)
                    .unwrap()
                    .timestamp_millis(),
                Utc.with_ymd_and_hms(2011, 12, 30, 10, 0, 0)
                    .unwrap()
                    .timestamp_millis(),
            )
        );
        assert!(skipped_domain.is_empty());
        assert_eq!(skipped_domain.utc_range().0, skipped_domain.utc_range().1);
        assert!(!skipped_domain.contains(skipped_domain.utc_range().0));
        assert_eq!(
            following_domain.utc_range(),
            (
                Utc.with_ymd_and_hms(2011, 12, 30, 10, 0, 0)
                    .unwrap()
                    .timestamp_millis(),
                Utc.with_ymd_and_hms(2011, 12, 31, 10, 0, 0)
                    .unwrap()
                    .timestamp_millis(),
            )
        );
    }

    proptest! {
        #[test]
        fn contains_matches_timezone_bucketing_near_dst_transitions(
            fall_transition in any::<bool>(),
            delta_minutes in -2_880i64..2_880,
        ) {
            let center = if fall_transition {
                Utc.with_ymd_and_hms(2026, 11, 1, 6, 0, 0).unwrap().timestamp_millis()
            } else {
                Utc.with_ymd_and_hms(2026, 3, 8, 7, 0, 0).unwrap().timestamp_millis()
            };
            let day = day_idx_in_tz(center, New_York);
            let boundary = Boundary::new(start_of_day_ms_in_tz(day + 2, New_York), New_York);
            let domain = SeedDomain::new(day, boundary, New_York, SChunkMs(center)).unwrap();
            let timestamp = center + delta_minutes * 60_000;
            prop_assert_eq!(domain.contains(timestamp), day_idx_in_tz(timestamp, New_York) == day);
        }

        #[test]
        fn planned_days_are_deterministic_and_stay_inside_the_capped_history(
            boundary_day in -20_000i32..20_000,
            cap in 0u16..500,
            windows in prop::collection::vec(0u16..1_000, 0..20),
        ) {
            let boundary = Boundary::new(i64::from(boundary_day) * 86_400_000, UTC);
            let conditions = windows
                .into_iter()
                .enumerate()
                .map(|(index, days)| condition(&format!("{index:016}"), Lookback::SlidingDays(u32::from(days))))
                .collect::<Vec<_>>();
            let caps = PlanCaps { max_lookback_days: u32::from(cap) };
            let first = plan_days(&conditions, boundary, &caps);
            let second = plan_days(&conditions, boundary, &caps);
            prop_assert_eq!(&first, &second);
            let lower = subtract_days(boundary.day(), u32::from(cap));
            prop_assert!(first.iter().all(|day| lower <= *day && *day < boundary.day()));
        }
    }
}
