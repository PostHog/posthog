//! Choosing a leaf's [`StateVariant`] and eviction window from its config.
//!
//! Time intervals are fixed-seconds, not calendar: [`TimeInterval::seconds`] reproduces
//! `INTERVAL_TO_SECONDS` exactly (`month = 30d`, `year = 365d`) as the cross-runtime windowing
//! contract. Calendar month/year arithmetic would diverge from the existing pipeline.

use crate::filters::tree::{BehavioralLeafConfig, BehavioralValue};
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

    /// The fixed number of whole days in this interval (`seconds / 86_400`): `day = 1`, `week = 7`,
    /// `month = 30`, `year = 365`, and `0` for sub-day `hour`/`minute`. Gives the D8 year/day
    /// equivalence (`365 day` ≡ `1 year`) for free.
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

/// How a [`StateVariant::BehavioralSingle`] leaf's eviction deadline is derived.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvictionWindow {
    /// A rolling window of `seconds` relative to each matching event.
    Relative { seconds: i64 },
    /// A fixed end instant (epoch ms); [`None`] when unparseable (treated as "never evict").
    Explicit { to_ms: Option<i64> },
}

impl EvictionWindow {
    /// The earliest epoch-ms at which state seeded by the newest matching event may be evicted.
    /// Pass the *newest* matching event time so a late (out-of-order) event cannot pull the
    /// deadline earlier.
    pub fn earliest_eviction_at_ms(self, newest_event_ms: i64) -> i64 {
        match self {
            Self::Relative { seconds } => {
                newest_event_ms.saturating_add(seconds.saturating_mul(1_000))
            }
            Self::Explicit { to_ms } => to_ms.unwrap_or(i64::MAX),
        }
    }
}

/// The count comparator a `performed_event_multiple` leaf applies to its window's matching-event
/// count. Net-new in PR 2.1 — there is no other operator→comparison mapping in the crate. Held on
/// the leaf's [`LeafStateMeta`](crate::filters::reverse_index::LeafStateMeta), never denormalized
/// into the stored bucket state, so the count threshold has one source of truth.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PredicateOp {
    Gte(u32),
    Lte(u32),
    Gt(u32),
    Lt(u32),
    Eq(u32),
}

impl PredicateOp {
    /// Resolve a leaf's `(operator, operator_value)` to a comparator, reproducing the existing
    /// pipeline's `VALID_OPERATORS` map (`hogql_cohort_query.py:986`): `{gte,lte,gt,lt,eq,exact}`,
    /// **default `eq`** when the operator is absent, and `exact` aliased to `eq`. An absent or
    /// negative `operator_value` clamps to `0` (the existing pipeline validates it positive at save
    /// time, so this is a defensive floor, not a parity case).
    pub fn from_leaf(operator: Option<&str>, operator_value: Option<i32>) -> Self {
        let value = operator_value.unwrap_or(0).max(0) as u32;
        match operator {
            Some("gte") => Self::Gte(value),
            Some("lte") => Self::Lte(value),
            Some("gt") => Self::Gt(value),
            Some("lt") => Self::Lt(value),
            // `eq`, `exact`, absent, or any unrecognized operator → `eq` (the pipeline's falsy
            // default). A genuinely malformed operator is a save-time validation failure upstream.
            _ => Self::Eq(value),
        }
    }

    /// Evaluate the comparator against a window's matching-event `count`.
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

/// Why a behavioral leaf has no supported state representation; the classifier drops + counts it so
/// it never reaches the worker.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum UnsupportedVariant {
    /// A `performed_event_multiple` whose `effective_window_days` is sub-day (`hour`/`minute`
    /// intervals): needs `BehavioralHourlyBuckets`, which is a parity *divergence* (the existing
    /// pipeline is calendar-day granular) and is deferred to a follow-up.
    #[error("performed_event_multiple sub-day window needs BehavioralHourlyBuckets (deferred)")]
    HourlyDeferred,
    /// A `performed_event_multiple` whose window exceeds 180 days: needs the run-length-encoded
    /// `BehavioralCompressedHistory`, deferred to a follow-up.
    #[error("performed_event_multiple window over 180 days needs BehavioralCompressedHistory (deferred)")]
    CompressedDeferred,
    #[error("performed_event leaf has no resolvable window")]
    MissingWindow,
    /// Handled defensively so the match is total — the classifier drops these earlier.
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
        // Routed by whole-day window: sub-day → hourly (deferred, a parity divergence), 1..=180 →
        // daily buckets (this PR; `day,1` = 2 buckets is parity-faithful, the existing pipeline
        // being calendar-day granular), > 180 → compressed history (deferred). The eviction window
        // is `None` — daily buckets derive their deadline from the bucket array, not a relative
        // window.
        BehavioralValue::PerformedEventMultiple => match effective_window_days(leaf) {
            0 => Err(UnsupportedVariant::HourlyDeferred),
            1..=180 => Ok((StateVariant::BehavioralDailyBuckets, None)),
            _ => Err(UnsupportedVariant::CompressedDeferred),
        },
        BehavioralValue::PerformedEventFirstTime
        | BehavioralValue::PerformedEventSequence
        | BehavioralValue::PerformedEventRegularly
        | BehavioralValue::StoppedPerformingEvent
        | BehavioralValue::RestartedPerformingEvent => Err(UnsupportedVariant::NonRealtimeValue),
    }
}

/// An `explicit_datetime[_to]` leaf uses the explicit end bound; otherwise a relative
/// `time_value × time_interval` window. A leaf with neither is unsupported.
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
    let time_value = i64::from(leaf.time_value.unwrap_or(0).max(0));
    Ok(EvictionWindow::Relative {
        seconds: time_value.saturating_mul(interval.seconds()),
    })
}

/// The whole-day window for a `performed_event_multiple` leaf: `time_value × interval.to_days()`,
/// mirroring [`eviction_window`]'s relative branch. Returns `0` when there is no resolvable relative
/// day-window (sub-day `hour`/`minute` intervals, an unrecognized interval, or an explicit-datetime
/// multiple with no `time_interval`) — all of which route to [`UnsupportedVariant::HourlyDeferred`]
/// and stay dropped, exactly as every `performed_event_multiple` was before this PR.
///
/// `pub(crate)` so the catalog freeze can recover a daily leaf's `window_days` (the bucket array
/// length − 1) from the same function the picker routed on — they cannot drift.
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

    use super::*;
    use crate::stage1::key::LeafStateKey;

    const HASH: [u8; 16] = *b"0123456789abcdef";

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
        // D8: 365 days ≡ 1 year.
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
        assert_eq!(
            window,
            Some(EvictionWindow::Relative {
                seconds: 7 * 86_400
            })
        );
    }

    #[test]
    fn performed_event_multiple_routes_by_effective_window_days() {
        use BehavioralValue::PerformedEventMultiple as Multiple;
        // (time_value, time_interval) → expected routing. Boundaries 1 and 180 are daily; 0 (sub-day)
        // is hourly-deferred; > 180 is compressed-deferred. `day,1` (2 buckets) is intentionally
        // daily — the existing pipeline's calendar-day granularity makes daily parity-faithful.
        let daily = Ok((StateVariant::BehavioralDailyBuckets, None));
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
                Err(UnsupportedVariant::CompressedDeferred),
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
                Err(UnsupportedVariant::CompressedDeferred),
                "D8: year,1 = 365 days → compressed",
            ),
            (
                Some(365),
                "day",
                Err(UnsupportedVariant::CompressedDeferred),
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
        // No time_interval (e.g. an explicit-datetime multiple) resolves to 0 whole days, so it stays
        // dropped exactly as every multiple was before this PR — no half-supported state.
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
            (None, PredicateOp::Eq(3)),          // absent → eq (the pipeline's falsy default)
            (Some("garbage"), PredicateOp::Eq(3)), // unrecognized → eq, defensively
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
    fn relative_window_deadline_is_event_plus_window() {
        let window = EvictionWindow::Relative {
            seconds: 7 * 86_400,
        };
        assert_eq!(
            window.earliest_eviction_at_ms(1_000),
            1_000 + 7 * 86_400 * 1_000
        );
    }

    #[test]
    fn explicit_window_deadline_is_the_bound_or_never() {
        assert_eq!(
            EvictionWindow::Explicit { to_ms: Some(5_000) }.earliest_eviction_at_ms(1_000),
            5_000,
        );
        assert_eq!(
            EvictionWindow::Explicit { to_ms: None }.earliest_eviction_at_ms(1_000),
            i64::MAX,
        );
    }
}
