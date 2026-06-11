//! Choosing a leaf's [`StateVariant`] and eviction window from its config.
//!
//! Time intervals are fixed-seconds (`month = 30d`, `year = 365d`) matching the cross-runtime
//! windowing contract.

use chrono_tz::Tz;

use crate::filters::tree::{BehavioralLeafConfig, BehavioralValue};
use crate::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};
use crate::stage1::state::StateVariant;
use crate::stage1::time::clickhouse_timestamp_to_millis;

/// A cohort time interval with its fixed second-count (the `INTERVAL_TO_SECONDS` contract).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeInterval {
    Minute,
    Hour,
    Day,
    Week,
    Month,
    Year,
}

impl TimeInterval {
    /// The fixed number of seconds in this interval, equal to Python's `INTERVAL_TO_SECONDS`.
    pub fn seconds(self) -> i64 {
        match self {
            Self::Minute => 60,
            Self::Hour => 3_600,
            Self::Day => 86_400,
            Self::Week => 604_800,
            Self::Month => 2_592_000,
            Self::Year => 31_536_000,
        }
    }

    /// Whole days in this interval (`seconds / 86_400`): `0` for sub-day intervals.
    pub fn to_days(self) -> u32 {
        (self.seconds() / 86_400) as u32
    }

    /// Parse the wire string, or [`None`] for an unrecognized one.
    pub fn from_wire(s: &str) -> Option<Self> {
        Some(match s {
            "minute" => Self::Minute,
            "hour" => Self::Hour,
            "day" => Self::Day,
            "week" => Self::Week,
            "month" => Self::Month,
            "year" => Self::Year,
            _ => return None,
        })
    }
}

/// How a `BehavioralSingle` leaf's eviction deadline is derived.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvictionWindow {
    /// A whole-day window: evicts at tz-midnight of `day(newest_event) + days + 1`.
    RelativeDays { days: u32 },
    /// A sub-day window (`hour`/`minute`): deadline is `newest_event + seconds`.
    RelativeSeconds { seconds: i64 },
    /// A fixed explicit date range. Once matched, membership is permanent (never evicted).
    Explicit { to_ms: Option<i64> },
}

impl EvictionWindow {
    /// The earliest epoch-ms at which this state may be evicted, given the newest matching event
    /// time and the team's timezone.
    pub fn earliest_eviction_at_ms(self, newest_event_ms: i64, tz: Tz) -> i64 {
        match self {
            Self::RelativeDays { days } => {
                let leave_day = i64::from(day_idx_in_tz(newest_event_ms, tz)) + i64::from(days) + 1;
                match i32::try_from(leave_day) {
                    Ok(day) => start_of_day_ms_in_tz(day, tz),
                    Err(_) => i64::MAX,
                }
            }
            Self::RelativeSeconds { seconds } => {
                newest_event_ms.saturating_add(seconds.saturating_mul(1_000))
            }
            Self::Explicit { .. } => i64::MAX,
        }
    }
}

/// Count comparator for a `performed_event_multiple` leaf's window sum.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PredicateOp {
    Gte(u32),
    Lte(u32),
    Gt(u32),
    Lt(u32),
    Eq(u32),
}

impl PredicateOp {
    /// Resolve a leaf's `(operator, operator_value)` to a comparator. Defaults to `eq`; `exact`
    /// aliases `eq`. Negative or absent `operator_value` clamps to `0`.
    pub fn from_leaf(operator: Option<&str>, operator_value: Option<i32>) -> Self {
        let value = operator_value.unwrap_or(0).max(0) as u32;
        match operator {
            Some("gte") => Self::Gte(value),
            Some("lte") => Self::Lte(value),
            Some("gt") => Self::Gt(value),
            Some("lt") => Self::Lt(value),
            // `eq`, `exact`, absent, or unrecognized all map to `eq` (the pipeline's default).
            _ => Self::Eq(value),
        }
    }

    /// Evaluate the comparator against a window `count`.
    pub fn evaluate(self, count: u32) -> bool {
        match self {
            Self::Gte(value) => count >= value,
            Self::Lte(value) => count <= value,
            Self::Gt(value) => count > value,
            Self::Lt(value) => count < value,
            Self::Eq(value) => count == value,
        }
    }
}

/// Why a behavioral leaf has no supported state representation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum UnsupportedVariant {
    /// A `performed_event_multiple` with a sub-day window (`hour`/`minute`).
    #[error("performed_event_multiple sub-day window is unsupported")]
    HourlyDeferred,
    #[error("performed_event leaf has no resolvable window")]
    MissingWindow,
    #[error("behavioral value does not contribute realtime bytecode")]
    NonRealtimeValue,
}

/// Pick the [`StateVariant`] and eviction window for a behavioral leaf, or why it is unsupported.
pub fn pick_state_variant(
    leaf: &BehavioralLeafConfig,
) -> Result<(StateVariant, Option<EvictionWindow>), UnsupportedVariant> {
    match leaf.value {
        BehavioralValue::PerformedEvent => {
            Ok((StateVariant::BehavioralSingle, Some(eviction_window(leaf)?)))
        }
        BehavioralValue::PerformedEventMultiple => match effective_window_days(leaf) {
            0 => Err(UnsupportedVariant::HourlyDeferred),
            1..=180 => Ok((StateVariant::BehavioralDailyBuckets, None)),
            _ => Ok((StateVariant::BehavioralCompressedHistory, None)),
        },
        BehavioralValue::PerformedEventFirstTime
        | BehavioralValue::PerformedEventSequence
        | BehavioralValue::PerformedEventRegularly
        | BehavioralValue::StoppedPerformingEvent
        | BehavioralValue::RestartedPerformingEvent => Err(UnsupportedVariant::NonRealtimeValue),
    }
}

/// Derive the eviction window from a leaf's datetime/interval config.
fn eviction_window(leaf: &BehavioralLeafConfig) -> Result<EvictionWindow, UnsupportedVariant> {
    if leaf.explicit_datetime.is_some() || leaf.explicit_datetime_to.is_some() {
        let to_ms = leaf
            .explicit_datetime_to
            .as_deref()
            .and_then(clickhouse_timestamp_to_millis);
        return Ok(EvictionWindow::Explicit { to_ms });
    }
    let interval = leaf
        .time_interval
        .as_deref()
        .and_then(TimeInterval::from_wire)
        .ok_or(UnsupportedVariant::MissingWindow)?;
    // A negative or absent time_value clamps to 0 rather than going negative.
    let time_value = leaf.time_value.unwrap_or(0).max(0);
    if interval.to_days() == 0 {
        Ok(EvictionWindow::RelativeSeconds {
            seconds: i64::from(time_value).saturating_mul(interval.seconds()),
        })
    } else {
        Ok(EvictionWindow::RelativeDays {
            days: u32::try_from(time_value)
                .unwrap_or(0)
                .saturating_mul(interval.to_days()),
        })
    }
}

/// The whole-day window for a `performed_event_multiple` leaf: `time_value × interval.to_days()`.
/// Returns `0` for sub-day or unrecognized intervals.
pub(crate) fn effective_window_days(leaf: &BehavioralLeafConfig) -> u32 {
    let Some(interval) = leaf
        .time_interval
        .as_deref()
        .and_then(TimeInterval::from_wire)
    else {
        return 0;
    };
    let time_value = u32::try_from(leaf.time_value.unwrap_or(0).max(0)).unwrap_or(0);
    time_value.saturating_mul(interval.to_days())
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use chrono::{TimeZone, Utc};
    use chrono_tz::America::New_York;
    use chrono_tz::UTC;

    use super::*;
    use crate::stage1::key::LeafStateKey;

    const HASH: [u8; 16] = *b"0123456789abcdef";

    /// Epoch-ms of a UTC wall-clock time, computed via chrono so the deadline goldens don't re-derive
    /// the day math under test.
    fn utc_ms(year: i32, month: u32, day: u32, hour: u32, minute: u32) -> i64 {
        Utc.with_ymd_and_hms(year, month, day, hour, minute, 0)
            .unwrap()
            .timestamp_millis()
    }

    fn leaf(
        value: BehavioralValue,
        time_value: Option<i32>,
        time_interval: Option<&str>,
    ) -> BehavioralLeafConfig {
        BehavioralLeafConfig {
            condition_hash: HASH,
            value,
            event_key: "$pageview".to_string(),
            time_value,
            operator_value: None,
            time_interval: time_interval.map(str::to_string),
            operator: None,
            explicit_datetime: None,
            explicit_datetime_to: None,
            leaf_state_key: LeafStateKey([0u8; 16]),
            state_variant: None,
            bytecode: Arc::new(vec![]),
            negated: false,
        }
        .with_state_key()
    }

    #[test]
    fn interval_seconds_match_the_python_constants() {
        // Golden vs INTERVAL_TO_SECONDS — month=30d, year=365d.
        assert_eq!(TimeInterval::Minute.seconds(), 60);
        assert_eq!(TimeInterval::Hour.seconds(), 3_600);
        assert_eq!(TimeInterval::Day.seconds(), 86_400);
        assert_eq!(TimeInterval::Week.seconds(), 604_800);
        assert_eq!(TimeInterval::Month.seconds(), 2_592_000);
        assert_eq!(TimeInterval::Year.seconds(), 31_536_000);
    }

    #[test]
    fn to_days_floors_each_interval_and_gives_year_day_equivalence() {
        assert_eq!(TimeInterval::Minute.to_days(), 0);
        assert_eq!(TimeInterval::Hour.to_days(), 0);
        assert_eq!(TimeInterval::Day.to_days(), 1);
        assert_eq!(TimeInterval::Week.to_days(), 7);
        assert_eq!(TimeInterval::Month.to_days(), 30);
        assert_eq!(TimeInterval::Year.to_days(), 365);
        assert_eq!(
            TimeInterval::Year.to_days(),
            365 * TimeInterval::Day.to_days()
        );
    }

    #[test]
    fn from_wire_round_trips_every_interval() {
        for (wire, interval) in [
            ("minute", TimeInterval::Minute),
            ("hour", TimeInterval::Hour),
            ("day", TimeInterval::Day),
            ("week", TimeInterval::Week),
            ("month", TimeInterval::Month),
            ("year", TimeInterval::Year),
        ] {
            assert_eq!(TimeInterval::from_wire(wire), Some(interval));
        }
        assert_eq!(TimeInterval::from_wire("fortnight"), None);
    }

    #[test]
    fn performed_event_is_behavioral_single_with_relative_window() {
        let (variant, window) =
            pick_state_variant(&leaf(BehavioralValue::PerformedEvent, Some(7), Some("day")))
                .unwrap();
        assert_eq!(variant, StateVariant::BehavioralSingle);
        assert_eq!(window, Some(EvictionWindow::RelativeDays { days: 7 }));
    }

    #[test]
    fn day_window_yields_relative_days_and_subday_yields_seconds() {
        // Whole-day intervals (day/week/month/year) route to a calendar `RelativeDays` window with the
        // same day count `effective_window_days` uses; sub-day (hour/minute) stays instant `RelativeSeconds`.
        let cases = [
            ("day", EvictionWindow::RelativeDays { days: 2 }),
            ("week", EvictionWindow::RelativeDays { days: 2 * 7 }),
            ("month", EvictionWindow::RelativeDays { days: 2 * 30 }),
            ("year", EvictionWindow::RelativeDays { days: 2 * 365 }),
            (
                "hour",
                EvictionWindow::RelativeSeconds { seconds: 2 * 3_600 },
            ),
            (
                "minute",
                EvictionWindow::RelativeSeconds { seconds: 2 * 60 },
            ),
        ];
        for (interval, expected) in cases {
            let (variant, window) = pick_state_variant(&leaf(
                BehavioralValue::PerformedEvent,
                Some(2),
                Some(interval),
            ))
            .unwrap();
            assert_eq!(variant, StateVariant::BehavioralSingle, "{interval}");
            assert_eq!(window, Some(expected), "{interval}");
        }
    }

    #[test]
    fn performed_event_multiple_routes_by_effective_window_days() {
        use BehavioralValue::PerformedEventMultiple as Multiple;
        // (time_value, time_interval) → expected routing, exercising the 1 and 180 daily boundaries
        // and the >180-day compressed routing.
        let daily = Ok((StateVariant::BehavioralDailyBuckets, None));
        let compressed = Ok((StateVariant::BehavioralCompressedHistory, None));
        let cases = [
            (
                Some(1),
                "day",
                daily,
                "day,1 = 1 day → daily (lower boundary)",
            ),
            (Some(7), "day", daily, "day,7 = 7 days → daily"),
            (Some(1), "week", daily, "week,1 = 7 days → daily"),
            (Some(180), "day", daily, "day,180 → daily (upper boundary)"),
            (
                Some(181),
                "day",
                compressed,
                "day,181 → compressed (just over the boundary)",
            ),
            (
                Some(5),
                "hour",
                Err(UnsupportedVariant::HourlyDeferred),
                "hour,5 = 0 whole days → hourly-deferred",
            ),
            (
                Some(30),
                "minute",
                Err(UnsupportedVariant::HourlyDeferred),
                "minute,30 = 0 whole days → hourly-deferred",
            ),
            (
                Some(1),
                "year",
                compressed,
                "year,1 = 365 days → compressed",
            ),
            (
                Some(365),
                "day",
                compressed,
                "day,365 = 365 days → compressed, same as 1 year",
            ),
        ];
        for (time_value, interval, expected, why) in cases {
            assert_eq!(
                pick_state_variant(&leaf(Multiple, time_value, Some(interval))),
                expected,
                "{why}",
            );
        }
    }

    #[test]
    fn performed_event_multiple_without_window_is_hourly_deferred() {
        // No time_interval (e.g. an explicit-datetime multiple) resolves to 0 whole days.
        assert_eq!(
            pick_state_variant(&leaf(BehavioralValue::PerformedEventMultiple, None, None)),
            Err(UnsupportedVariant::HourlyDeferred),
        );
    }

    #[test]
    fn predicate_op_from_leaf_maps_every_operator_and_defaults_to_eq() {
        let cases = [
            (Some("gte"), PredicateOp::Gte(3)),
            (Some("lte"), PredicateOp::Lte(3)),
            (Some("gt"), PredicateOp::Gt(3)),
            (Some("lt"), PredicateOp::Lt(3)),
            (Some("eq"), PredicateOp::Eq(3)),
            (Some("exact"), PredicateOp::Eq(3)), // exact aliases eq
            (None, PredicateOp::Eq(3)),          // absent defaults to eq
            (Some("garbage"), PredicateOp::Eq(3)), // unrecognized falls back to eq
        ];
        for (operator, expected) in cases {
            assert_eq!(
                PredicateOp::from_leaf(operator, Some(3)),
                expected,
                "{operator:?}"
            );
        }
    }

    #[test]
    fn predicate_op_from_leaf_clamps_absent_or_negative_value_to_zero() {
        assert_eq!(
            PredicateOp::from_leaf(Some("gte"), None),
            PredicateOp::Gte(0)
        );
        assert_eq!(
            PredicateOp::from_leaf(Some("lte"), Some(-5)),
            PredicateOp::Lte(0)
        );
    }

    #[test]
    fn predicate_op_evaluate_matches_each_comparator() {
        assert!(PredicateOp::Gte(3).evaluate(3));
        assert!(!PredicateOp::Gte(3).evaluate(2));
        assert!(PredicateOp::Lte(3).evaluate(3));
        assert!(!PredicateOp::Lte(3).evaluate(4));
        assert!(PredicateOp::Gt(3).evaluate(4));
        assert!(!PredicateOp::Gt(3).evaluate(3));
        assert!(PredicateOp::Lt(3).evaluate(2));
        assert!(!PredicateOp::Lt(3).evaluate(3));
        assert!(PredicateOp::Eq(3).evaluate(3));
        assert!(!PredicateOp::Eq(3).evaluate(2));
    }

    #[test]
    fn performed_event_without_window_is_unsupported() {
        assert_eq!(
            pick_state_variant(&leaf(BehavioralValue::PerformedEvent, None, None)),
            Err(UnsupportedVariant::MissingWindow),
        );
        assert_eq!(
            pick_state_variant(&leaf(
                BehavioralValue::PerformedEvent,
                Some(7),
                Some("fortnight")
            )),
            Err(UnsupportedVariant::MissingWindow),
        );
    }

    #[test]
    fn explicit_datetime_yields_an_explicit_window() {
        let mut l = leaf(BehavioralValue::PerformedEvent, None, None);
        l.explicit_datetime = Some("2026-01-01 00:00:00.000000".to_string());
        l.explicit_datetime_to = Some("2026-02-01 00:00:00.000000".to_string());
        let l = l.with_state_key();
        let (variant, window) = pick_state_variant(&l).unwrap();
        assert_eq!(variant, StateVariant::BehavioralSingle);
        let to_ms = clickhouse_timestamp_to_millis("2026-02-01 00:00:00.000000");
        assert_eq!(window, Some(EvictionWindow::Explicit { to_ms }));
    }

    #[test]
    fn subday_window_deadline_is_event_plus_window() {
        // A sub-day window stays instant-granular: deadline = newest_event + seconds (tz-independent).
        let window = EvictionWindow::RelativeSeconds { seconds: 5 * 3_600 };
        assert_eq!(
            window.earliest_eviction_at_ms(1_000, UTC),
            1_000 + 5 * 3_600 * 1_000,
        );
        assert_eq!(
            window.earliest_eviction_at_ms(1_000, New_York),
            1_000 + 5 * 3_600 * 1_000,
            "a sub-day deadline does not depend on the timezone",
        );
    }

    #[test]
    fn relative_days_deadline_is_local_midnight_after_the_window() {
        // A whole-day window evicts at tz-midnight of `day(newest_event) + days + 1`, identical to the
        // daily-bucket variant. Golden in both UTC and a negative-offset zone.
        let event_ms = utc_ms(2026, 5, 26, 12, 34);
        let window = EvictionWindow::RelativeDays { days: 7 };
        for tz in [UTC, New_York] {
            let leave_day = day_idx_in_tz(event_ms, tz) + 7 + 1;
            assert_eq!(
                window.earliest_eviction_at_ms(event_ms, tz),
                start_of_day_ms_in_tz(leave_day, tz),
                "{tz}",
            );
        }
        // The zone matters: New York's local midnight is a different instant than UTC's.
        assert_ne!(
            window.earliest_eviction_at_ms(event_ms, UTC),
            window.earliest_eviction_at_ms(event_ms, New_York),
        );
    }

    #[test]
    fn calendar_identical_events_share_one_eviction_midnight() {
        // The boundary regression: two events on the same local calendar day — one just after midnight,
        // one just before the next — must yield the *same* eviction midnight, not deadlines ~23h apart.
        let window = EvictionWindow::RelativeDays { days: 7 };
        let early = utc_ms(2026, 5, 26, 0, 30); // 00:30 UTC
        let late = utc_ms(2026, 5, 26, 23, 30); // 23:30 UTC, same calendar day
        assert_eq!(
            window.earliest_eviction_at_ms(early, UTC),
            window.earliest_eviction_at_ms(late, UTC),
            "two events on day D share the eviction midnight of D + 8",
        );
    }

    #[test]
    fn zero_time_value_day_window_evicts_at_the_next_midnight() {
        // `time_value = 0, day` (the old `-0d`) holds the member through the end of the event's own
        // day, so eviction is the next local midnight (`day + 0 + 1`).
        let window = EvictionWindow::RelativeDays { days: 0 };
        let event_ms = utc_ms(2026, 5, 26, 9, 0);
        assert_eq!(
            window.earliest_eviction_at_ms(event_ms, UTC),
            start_of_day_ms_in_tz(day_idx_in_tz(event_ms, UTC) + 1, UTC),
        );
    }

    #[test]
    fn explicit_window_never_evicts_for_permanent_membership() {
        // An explicit `[from, to]` range is a fixed historical question: once matched, the person is
        // a member permanently, so the deadline is always `i64::MAX` regardless of `to_ms`. Returning
        // `to` would make the sweep emit a spurious `Left` at `to`; `i64::MAX` keeps the leaf out of
        // the sweep queue entirely.
        assert_eq!(
            EvictionWindow::Explicit { to_ms: Some(5_000) }.earliest_eviction_at_ms(1_000, UTC),
            i64::MAX,
        );
        assert_eq!(
            EvictionWindow::Explicit { to_ms: None }.earliest_eviction_at_ms(1_000, UTC),
            i64::MAX,
        );
    }
}
