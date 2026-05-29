//! Choosing a leaf's [`StateVariant`] and eviction window from its config (TDD §4.1, §4.1.1).
//!
//! [`pick_state_variant`] is invoked once per behavioral leaf at filter-load time. PR 1.6
//! implements only `performed_event → BehavioralSingle`; `performed_event_multiple` (the bucket
//! variants) is deferred to PR 2.1 and returns [`UnsupportedVariant::MultipleDeferred`] so the
//! classifier drops the leaf — keeping the parity invariant that an unsupported variant never
//! reaches the worker.
//!
//! ## Time intervals are fixed-seconds, not calendar
//!
//! [`TimeInterval::seconds`] reproduces `INTERVAL_TO_SECONDS`
//! (`posthog/queries/foss_cohort_query.py:25`) exactly — `month = 30d`, `year = 365d` — because
//! that constant is the cross-runtime windowing contract. Calendar month/year arithmetic
//! (`chrono`) would diverge from the existing pipeline. There is **no minute-rejection** in
//! PR 1.6: that rule is save-time and specific to `performed_event_multiple` (D8), which is
//! deferred — `performed_event` accepts all six intervals.

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
    /// The fixed number of seconds in this interval, byte-for-byte equal to
    /// `posthog/queries/foss_cohort_query.py:25`'s `INTERVAL_TO_SECONDS`.
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

    /// Parse the wire string (the value stored in the cohort filter JSON), or [`None`] for an
    /// unrecognized one.
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

/// How a [`StateVariant::BehavioralSingle`] leaf's eviction deadline is derived. Stored per leaf in
/// the catalog ([`crate::filters::reverse_index::LeafStateMeta`]) and consulted by the worker when
/// it folds an event in. Eviction *firing* is PR 2.2–2.3; PR 1.6 only computes the deadline.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvictionWindow {
    /// A rolling window of `seconds` relative to each matching event (`time_value × interval`).
    Relative { seconds: i64 },
    /// A fixed end instant (epoch ms) from `explicit_datetime_to`; [`None`] when the bound could
    /// not be parsed (treated as "never evict" until the explicit-window machinery lands).
    Explicit { to_ms: Option<i64> },
}

impl EvictionWindow {
    /// The earliest epoch-ms at which state seeded by the newest matching event (at
    /// `newest_event_ms`) may be evicted.
    ///
    /// For a relative window this is `newest_event_ms + seconds`; for an explicit window it is the
    /// fixed end instant, or [`i64::MAX`] ("never") when that instant is absent/unparseable. Pass
    /// the *newest* matching event time so a late (out-of-order) event cannot pull the deadline
    /// earlier.
    pub fn earliest_eviction_at_ms(self, newest_event_ms: i64) -> i64 {
        match self {
            Self::Relative { seconds } => {
                newest_event_ms.saturating_add(seconds.saturating_mul(1_000))
            }
            Self::Explicit { to_ms } => to_ms.unwrap_or(i64::MAX),
        }
    }
}

/// Why a behavioral leaf has no PR 1.6 state representation. The classifier maps any of these to
/// [`LeafDropReason::UnsupportedStateVariant`](crate::filters::leaf_classifier::LeafDropReason),
/// so the leaf is dropped + counted and never reaches the worker.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum UnsupportedVariant {
    /// `performed_event_multiple` — the bucket state variants are PR 2.1.
    #[error("performed_event_multiple bucket state is deferred to PR 2.1")]
    MultipleDeferred,
    /// A `performed_event` leaf with neither a relative window (`time_value` + valid
    /// `time_interval`) nor any `explicit_datetime[_to]` — no window can be derived.
    #[error("performed_event leaf has no resolvable window")]
    MissingWindow,
    /// A behavioral value that does not produce realtime bytecode (the classifier already drops
    /// these earlier; handled here defensively so the match is total).
    #[error("behavioral value does not contribute realtime bytecode")]
    NonRealtimeValue,
}

/// Pick the [`StateVariant`] and eviction window for a behavioral leaf, or the reason it is
/// unsupported in PR 1.6.
pub fn pick_state_variant(
    leaf: &BehavioralLeafConfig,
) -> Result<(StateVariant, Option<EvictionWindow>), UnsupportedVariant> {
    match leaf.value {
        BehavioralValue::PerformedEvent => {
            Ok((StateVariant::BehavioralSingle, Some(eviction_window(leaf)?)))
        }
        BehavioralValue::PerformedEventMultiple => Err(UnsupportedVariant::MultipleDeferred),
        BehavioralValue::PerformedEventFirstTime
        | BehavioralValue::PerformedEventSequence
        | BehavioralValue::PerformedEventRegularly
        | BehavioralValue::StoppedPerformingEvent
        | BehavioralValue::RestartedPerformingEvent => Err(UnsupportedVariant::NonRealtimeValue),
    }
}

/// Derive the eviction window. An `explicit_datetime[_to]` leaf uses the explicit end bound;
/// otherwise a relative `time_value × time_interval` window. A leaf with neither is unsupported.
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
    // A negative or absent time_value clamps to 0 (a degenerate zero-length window) rather than
    // overflowing or going negative — the LeafStateKey already pins the exact stored value.
    let time_value = i64::from(leaf.time_value.unwrap_or(0).max(0));
    Ok(EvictionWindow::Relative {
        seconds: time_value.saturating_mul(interval.seconds()),
    })
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
        // Golden vs INTERVAL_TO_SECONDS (foss_cohort_query.py:25) — month=30d, year=365d.
        assert_eq!(TimeInterval::Minute.seconds(), 60);
        assert_eq!(TimeInterval::Hour.seconds(), 3_600);
        assert_eq!(TimeInterval::Day.seconds(), 86_400);
        assert_eq!(TimeInterval::Week.seconds(), 604_800);
        assert_eq!(TimeInterval::Month.seconds(), 2_592_000);
        assert_eq!(TimeInterval::Year.seconds(), 31_536_000);
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
    fn performed_event_multiple_is_deferred() {
        assert_eq!(
            pick_state_variant(&leaf(
                BehavioralValue::PerformedEventMultiple,
                Some(7),
                Some("day")
            )),
            Err(UnsupportedVariant::MultipleDeferred),
        );
    }

    #[test]
    fn performed_event_without_window_is_unsupported() {
        assert_eq!(
            pick_state_variant(&leaf(BehavioralValue::PerformedEvent, None, None)),
            Err(UnsupportedVariant::MissingWindow),
        );
        // An unrecognized interval string is also unresolvable.
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
