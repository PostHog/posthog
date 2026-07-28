//! Domain layer: `Boundary`, `SeedDomain`, and `PlanCaps` — the tz-anchored seed window and its caps,
//! with validity proven in the constructors. Depends on `ids` and `cohort-core`'s tz math.

use std::num::NonZeroU16;

use chrono_tz::Tz;
use cohort_core::{day_idx_in_tz, start_of_day_ms_in_tz};

use super::ids::{DayIdx, SChunkMs, UtcMillis, UtcMsRange, UtcRangeError};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Boundary {
    at_ms: UtcMillis,
    day: DayIdx,
}

impl Boundary {
    pub fn new(at_ms: UtcMillis, tz: Tz) -> Self {
        Self {
            at_ms,
            day: day_idx_in_tz(at_ms.as_i64(), tz),
        }
    }

    pub const fn at_ms(self) -> UtcMillis {
        self.at_ms
    }

    pub const fn day(self) -> DayIdx {
        self.day
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlanCaps {
    pub max_lookback_days: u32,
    /// Bands each planned day is split into: the scan hashes persons via `cityHash64 % bands`, so
    /// one chunk's in-memory aggregate holds roughly `uniq(person, condition) / bands` entries.
    pub bands_per_day: NonZeroU16,
}

impl Default for PlanCaps {
    fn default() -> Self {
        Self {
            max_lookback_days: 400,
            bands_per_day: NonZeroU16::MIN,
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
        let range = UtcMsRange::new(
            UtcMillis::new(start_of_day_ms_in_tz(day, tz)),
            UtcMillis::new(start_of_day_ms_in_tz(next_day, tz)),
        )?;
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
    #[error("seed day {day} is not before boundary day {boundary_day}")]
    AtOrAfterBoundary { day: DayIdx, boundary_day: DayIdx },
    #[error("seed day {0} has no representable successor")]
    DayOverflow(DayIdx),
    #[error(transparent)]
    InvalidUtcRange(#[from] UtcRangeError),
}

#[cfg(test)]
mod tests {
    use chrono::{NaiveDate, TimeZone, Utc};
    use chrono_tz::America::New_York;
    use chrono_tz::Pacific::Apia;
    use cohort_core::day_idx_of_naive_date;
    use proptest::prelude::*;

    use super::*;

    #[test]
    fn seed_domain_excludes_the_boundary_day_and_uses_dst_exact_half_open_ranges() {
        let spring_day = day_idx_in_tz(
            Utc.with_ymd_and_hms(2026, 3, 8, 12, 0, 0)
                .unwrap()
                .timestamp_millis(),
            New_York,
        );
        let boundary = Boundary::new(
            UtcMillis::new(start_of_day_ms_in_tz(spring_day + 1, New_York)),
            New_York,
        );
        assert!(matches!(
            SeedDomain::new(
                boundary.day(),
                boundary,
                New_York,
                SChunkMs(boundary.at_ms().as_i64())
            ),
            Err(DomainError::AtOrAfterBoundary { .. })
        ));

        let domain = SeedDomain::new(
            spring_day,
            boundary,
            New_York,
            SChunkMs(boundary.at_ms().as_i64()),
        )
        .unwrap();
        let range = domain.utc_range();
        let (start, end) = (range.start().as_i64(), range.end().as_i64());
        assert_eq!(end - start, 23 * 3_600_000);
        assert!(domain.contains(UtcMillis::new(start)));
        assert!(domain.contains(UtcMillis::new(end - 1)));
        assert!(!domain.contains(UtcMillis::new(end)));
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
            UtcMillis::new(
                Utc.with_ymd_and_hms(2012, 1, 2, 0, 0, 0)
                    .unwrap()
                    .timestamp_millis(),
            ),
            Apia,
        );
        let domain = |day| {
            SeedDomain::new(day, boundary, Apia, SChunkMs(boundary.at_ms().as_i64())).unwrap()
        };

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
            let boundary = Boundary::new(
                UtcMillis::new(start_of_day_ms_in_tz(day + 2, New_York)),
                New_York,
            );
            let domain = SeedDomain::new(day, boundary, New_York, SChunkMs(center)).unwrap();
            let timestamp = center + delta_minutes * 60_000;
            prop_assert_eq!(domain.contains(UtcMillis::new(timestamp)), day_idx_in_tz(timestamp, New_York) == day);
        }
    }
}
