//! Domain layer: `Boundary`, `SeedDomain`, and `PlanCaps` — the tz-anchored seed window and its caps,
//! with validity proven in the constructors. Depends on `ids` and `cohort-core`'s tz math.

use std::num::NonZeroU16;
use std::time::Duration;

use chrono_tz::Tz;
use cohort_core::{day_idx_in_tz, start_of_day_ms_in_tz};

use super::ids::{DayIdx, SChunkMs, UtcMillis, UtcMsRange, UtcRangeError};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Boundary {
    at_ms: UtcMillis,
    tz: Tz,
    day: DayIdx,
}

impl Boundary {
    pub fn new(at_ms: UtcMillis, tz: Tz) -> Self {
        Self {
            at_ms,
            tz,
            day: day_idx_in_tz(at_ms.as_i64(), tz),
        }
    }

    pub const fn at_ms(self) -> UtcMillis {
        self.at_ms
    }

    pub const fn day(self) -> DayIdx {
        self.day
    }

    /// The last day the live path may have missed the start of. The processor starts counting a new
    /// leaf when its catalog next loads, up to `live_lag` after the boundary, and that instant can
    /// fall past the team's midnight.
    pub fn last_seedable_day(self, live_lag: Duration) -> DayIdx {
        day_idx_in_tz(
            self.at_ms.as_i64().saturating_add(millis(live_lag)),
            self.tz,
        )
    }

    /// When the seeder may scan `day`. A day from the boundary day on is scanned only after it ends,
    /// because a tile is the day's absolute count only once nothing more can land in it.
    pub fn schedule(self, day: DayIdx, grace: Duration) -> PlannedDay {
        let schedule = if day < self.day {
            DaySchedule::Historical
        } else {
            DaySchedule::Trailing {
                claimable_after: UtcMillis::new(
                    start_of_day_ms_in_tz(day + 1, self.tz).saturating_add(millis(grace)),
                ),
            }
        };
        PlannedDay { day, schedule }
    }
}

/// A day a run seeds, with when the seeder may scan it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlannedDay {
    pub day: DayIdx,
    pub schedule: DaySchedule,
}

/// When the seeder may scan a planned day, which also decides whether the run's readiness waits for
/// it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaySchedule {
    /// A day before the boundary day. It has ended by the time the boundary is set, so it is
    /// claimable at once, and readiness waits for it.
    Historical,
    /// The boundary day, or a later day the live path may have missed the start of. The seeder
    /// claims it only after `claimable_after`, and readiness does not wait for it: the run stamps
    /// readiness first and seeds these days afterwards.
    Trailing { claimable_after: UtcMillis },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlanCaps {
    pub max_lookback_days: u32,
    /// Bands each planned day is split into: the scan hashes persons via `cityHash64 % bands`, so
    /// one chunk's in-memory aggregate holds roughly `uniq(person, condition) / bands` entries.
    pub bands_per_day: NonZeroU16,
    /// How long after the boundary the live path may start counting a new leaf. Every day it can
    /// reach is planned as a trailing day.
    pub live_tracking_lag: Duration,
    /// How long after a trailing day ends the seeder waits before it scans the day, so that events
    /// ingested late for that day are in the tile.
    pub trailing_day_grace: Duration,
}

impl Default for PlanCaps {
    fn default() -> Self {
        Self {
            max_lookback_days: 400,
            bands_per_day: NonZeroU16::MIN,
            live_tracking_lag: Duration::ZERO,
            trailing_day_grace: Duration::ZERO,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SeedDomain {
    day: DayIdx,
    tz: Tz,
    range: UtcMsRange,
    s_chunk: SChunkMs,
}

impl SeedDomain {
    /// Refuses a day that has not ended at `s_chunk`. Its tile would be a partial count, and a
    /// confirmed chunk is never scanned again, so the day would stay short for the whole window.
    pub fn new(day: DayIdx, tz: Tz, s_chunk: SChunkMs) -> Result<Self, DomainError> {
        let next_day = day.checked_add(1).ok_or(DomainError::DayOverflow(day))?;
        let range = UtcMsRange::new(
            UtcMillis::new(start_of_day_ms_in_tz(day, tz)),
            UtcMillis::new(start_of_day_ms_in_tz(next_day, tz)),
        )?;
        if range.end().as_i64() > s_chunk.0 {
            return Err(DomainError::NotElapsed { day, s_chunk });
        }
        Ok(Self {
            day,
            tz,
            range,
            s_chunk,
        })
    }

    pub const fn day(&self) -> DayIdx {
        self.day
    }

    pub const fn s_chunk(&self) -> SChunkMs {
        self.s_chunk
    }

    pub const fn utc_range(&self) -> UtcMsRange {
        self.range
    }

    pub const fn is_empty(&self) -> bool {
        self.range.is_empty()
    }

    pub fn contains(&self, event_ts_ms: UtcMillis) -> bool {
        day_idx_in_tz(event_ts_ms.as_i64(), self.tz) == self.day
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum DomainError {
    #[error("seed day {day} has not ended at the chunk's scan instant {s_chunk:?}")]
    NotElapsed { day: DayIdx, s_chunk: SChunkMs },
    #[error("seed day {0} has no representable successor")]
    DayOverflow(DayIdx),
    #[error(transparent)]
    InvalidUtcRange(#[from] UtcRangeError),
}

fn millis(duration: Duration) -> i64 {
    i64::try_from(duration.as_millis()).unwrap_or(i64::MAX)
}

#[cfg(test)]
mod tests {
    use chrono::{NaiveDate, TimeZone, Utc};
    use chrono_tz::America::New_York;
    use chrono_tz::Pacific::Apia;
    use cohort_core::day_idx_of_naive_date;
    use proptest::prelude::*;

    use super::*;

    fn new_york_spring_forward_day() -> DayIdx {
        day_idx_in_tz(
            Utc.with_ymd_and_hms(2026, 3, 8, 12, 0, 0)
                .unwrap()
                .timestamp_millis(),
            New_York,
        )
    }

    #[test]
    fn seed_domain_admits_a_day_only_once_it_has_ended_and_uses_dst_exact_half_open_ranges() {
        let spring_day = new_york_spring_forward_day();
        let end = start_of_day_ms_in_tz(spring_day + 1, New_York);
        assert!(matches!(
            SeedDomain::new(spring_day, New_York, SChunkMs(end - 1)),
            Err(DomainError::NotElapsed { .. })
        ));

        let domain = SeedDomain::new(spring_day, New_York, SChunkMs(end)).unwrap();
        let range = domain.utc_range();
        let (start, end) = (range.start().as_i64(), range.end().as_i64());
        assert_eq!(end - start, 23 * 3_600_000);
        assert!(domain.contains(UtcMillis::new(start)));
        assert!(domain.contains(UtcMillis::new(end - 1)));
        assert!(!domain.contains(UtcMillis::new(end)));
    }

    #[test]
    fn schedule_holds_days_from_the_boundary_day_until_their_local_midnight_plus_grace() {
        let spring_day = new_york_spring_forward_day();
        let boundary = Boundary::new(
            UtcMillis::new(
                Utc.with_ymd_and_hms(2026, 3, 8, 17, 8, 0)
                    .unwrap()
                    .timestamp_millis(),
            ),
            New_York,
        );
        let grace = Duration::from_secs(30 * 60);

        assert_eq!(
            boundary.schedule(spring_day - 1, grace).schedule,
            DaySchedule::Historical
        );
        // New York is on EDT after the spring-forward, so its next midnight is 04:00 UTC.
        let after_midnight = |day, hour| DaySchedule::Trailing {
            claimable_after: UtcMillis::new(
                Utc.with_ymd_and_hms(2026, 3, day, hour, 30, 0)
                    .unwrap()
                    .timestamp_millis(),
            ),
        };
        assert_eq!(
            boundary.schedule(spring_day, grace).schedule,
            after_midnight(9, 4)
        );
        assert_eq!(
            boundary.schedule(spring_day + 1, grace).schedule,
            after_midnight(10, 4)
        );
    }

    #[test]
    fn skipped_civil_day_is_vacuous_without_truncating_its_neighbors() {
        let day = |year, month, day| {
            day_idx_of_naive_date(NaiveDate::from_ymd_opt(year, month, day).unwrap())
        };
        let preceding = day(2011, 12, 29);
        let skipped = day(2011, 12, 30);
        let following = day(2011, 12, 31);
        let s_chunk = SChunkMs(
            Utc.with_ymd_and_hms(2012, 1, 2, 0, 0, 0)
                .unwrap()
                .timestamp_millis(),
        );
        let domain = |day| SeedDomain::new(day, Apia, s_chunk).unwrap();

        let preceding_domain = domain(preceding);
        let skipped_domain = domain(skipped);
        let following_domain = domain(following);
        assert_eq!(
            preceding_domain.utc_range(),
            UtcMsRange::new(
                UtcMillis::new(
                    Utc.with_ymd_and_hms(2011, 12, 29, 10, 0, 0)
                        .unwrap()
                        .timestamp_millis(),
                ),
                UtcMillis::new(
                    Utc.with_ymd_and_hms(2011, 12, 30, 10, 0, 0)
                        .unwrap()
                        .timestamp_millis(),
                ),
            )
            .unwrap()
        );
        assert!(skipped_domain.is_empty());
        assert_eq!(
            skipped_domain.utc_range().start(),
            skipped_domain.utc_range().end()
        );
        assert!(!skipped_domain.contains(skipped_domain.utc_range().start()));
        assert_eq!(
            following_domain.utc_range(),
            UtcMsRange::new(
                UtcMillis::new(
                    Utc.with_ymd_and_hms(2011, 12, 30, 10, 0, 0)
                        .unwrap()
                        .timestamp_millis(),
                ),
                UtcMillis::new(
                    Utc.with_ymd_and_hms(2011, 12, 31, 10, 0, 0)
                        .unwrap()
                        .timestamp_millis(),
                ),
            )
            .unwrap()
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
            let s_chunk = SChunkMs(start_of_day_ms_in_tz(day + 2, New_York));
            let domain = SeedDomain::new(day, New_York, s_chunk).unwrap();
            let timestamp = center + delta_minutes * 60_000;
            prop_assert_eq!(domain.contains(UtcMillis::new(timestamp)), day_idx_in_tz(timestamp, New_York) == day);
        }
    }
}
