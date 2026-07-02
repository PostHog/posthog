//! Choosing a leaf's [`StateVariant`] and eviction window from its config.

use chrono_tz::Tz;

use crate::filters::tree::{BehavioralLeafConfig, BehavioralValue};
use crate::stage1::bucket_tz::{
    day_idx_in_tz, day_idx_of_naive_date, start_of_day_ms_in_tz, DayIdx,
};
use crate::stage1::state::StateVariant;

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
    /// Fixed seconds in this interval (`month = 30d`, `year = 365d`).
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

    /// Whole days in this interval: `0` for sub-day intervals.
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
    /// A fixed **absolute** date range (`explicit_datetime`(_to) that parse as absolute datetimes).
    /// Bounds are tz-naive calendar **day** indices (days since 1970-01-01); either side `None` means
    /// unbounded on that side. The oracle treats a bare/naive `explicit_datetime` as a tz-naive
    /// calendar date (`toDate('2026-05-01')` is the literal date, tz-invariant), so the bound is a day,
    /// not a UTC instant — storing it as a day keeps it from shifting under a UTC-offset team timezone.
    /// Once matched within the range, membership is permanent (never evicted) — the oracle compares
    /// against fixed calendar dates, so a match can never age out. The day-granularity in-range check
    /// lives in the event path (`mutate_behavioral`), keyed off these bounds.
    Explicit {
        from_day: Option<DayIdx>,
        to_day: Option<DayIdx>,
    },
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
    /// Resolve a leaf's `(operator, operator_value)` to a comparator. Defaults to `eq`.
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
    /// An `explicit_datetime` range the sweep cannot model: a relative *upper* bound, or a relative
    /// lower bound paired with any upper bound. These need delayed entry and double-ended eviction
    /// (a person enters only once the relative `from` slides past and leaves once the relative `to`
    /// does), which the single-deadline sweep does not represent. Skipping the leaf is the safe
    /// choice — no realtime state, hence no wrong members — until that machinery exists.
    #[error("explicit_datetime relative range is unsupported")]
    RelativeRangeUnsupported,
    /// A *present* `explicit_datetime`(_to) bound that parses as neither an absolute date nor a known
    /// relative grammar. Skipping the leaf (no realtime state) is safe; silently nulling the bound
    /// would turn a closed range open-ended and create permanent members past the intended end.
    #[error("explicit_datetime bound is unparseable")]
    UnparseableExplicitBound,
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
///
/// `explicit_datetime`(_to) takes precedence over `time_value`/`time_interval` (mirroring the
/// oracle's `if prop.explicit_datetime` branch in `hogql_cohort_query.py`). The oracle resolves each
/// `explicit_datetime` bound as either an absolute datetime or a relative offset (`relative_date_parse`,
/// same convention as every analytics date filter), so we classify each present bound the same way:
///   - **absolute** (parses as a datetime) → an [`EvictionWindow::Explicit`] bound;
///   - **relative lower-only** (`"-Nd"` with no upper bound) → the equivalent relative window, which
///     is byte-identical to the `time_value:N, time_interval:<unit>` path the oracle also funnels
///     through `relative_date_parse` — so a sliding window recovers the common case correctly;
///   - **relative with any upper bound, or a relative upper bound** → [`UnsupportedVariant`], because
///     the sweep cannot model delayed entry / double-ended eviction.
fn eviction_window(leaf: &BehavioralLeafConfig) -> Result<EvictionWindow, UnsupportedVariant> {
    if leaf.explicit_datetime.is_some() || leaf.explicit_datetime_to.is_some() {
        return explicit_eviction_window(
            leaf.explicit_datetime.as_deref(),
            leaf.explicit_datetime_to.as_deref(),
        );
    }
    let interval = leaf
        .time_interval
        .as_deref()
        .and_then(TimeInterval::from_wire)
        .ok_or(UnsupportedVariant::MissingWindow)?;
    Ok(relative_window_from_interval(interval, leaf.time_value))
}

/// Classify an `explicit_datetime`(_to) pair into an eviction window. See [`eviction_window`].
fn explicit_eviction_window(
    from: Option<&str>,
    to: Option<&str>,
) -> Result<EvictionWindow, UnsupportedVariant> {
    // Each present bound is absolute (parses as a datetime) or relative (parses as `-N<unit>`).
    let from_kind = from.map(classify_bound);
    let to_kind = to.map(classify_bound);

    match (from_kind, to_kind) {
        // A *present* bound that parses as neither absolute nor a known relative grammar must skip the
        // leaf, not be silently nulled — dropping one side of a closed range would make it open-ended
        // and create permanent members past the intended end. Only a genuinely ABSENT (`None`) bound
        // means "unbounded on that side".
        (Some(Bound::Unparseable), _) | (_, Some(Bound::Unparseable)) => {
            Err(UnsupportedVariant::UnparseableExplicitBound)
        }
        // A relative *upper* bound (with or without a lower bound) needs delayed double-ended
        // eviction the sweep does not model.
        (_, Some(Bound::Relative(_))) => Err(UnsupportedVariant::RelativeRangeUnsupported),
        // A relative *lower* bound combined with any upper bound is the same problem: the person
        // would enter only once the relative `from` slides past, then leave at the upper bound.
        (Some(Bound::Relative(_)), Some(Bound::Absolute(_))) => {
            Err(UnsupportedVariant::RelativeRangeUnsupported)
        }
        // Relative lower bound, no upper bound — the dominant `performed_event` shape ("in the last
        // N days"). Map it to the matching sliding window; an unrepresentable unit (e.g. `q`) skips.
        (Some(Bound::Relative(window)), None) => {
            window.ok_or(UnsupportedVariant::RelativeRangeUnsupported)
        }
        // Absolute (or absent) on both sides — a fixed calendar range, permanent membership.
        (from_kind, to_kind) => Ok(EvictionWindow::Explicit {
            from_day: from_kind.and_then(Bound::absolute_day),
            to_day: to_kind.and_then(Bound::absolute_day),
        }),
    }
}

/// One classified `explicit_datetime` bound.
#[derive(Debug, Clone, Copy)]
enum Bound {
    /// An absolute datetime, as a tz-naive calendar **day** index (its written date).
    Absolute(DayIdx),
    /// A relative offset (`-N<unit>`), mapped to its sliding window — or `None` for a known-relative
    /// grammar we cannot represent (e.g. a quarter, which has no `TimeInterval`).
    Relative(Option<EvictionWindow>),
    /// Parses as neither an absolute datetime nor a recognized relative grammar.
    Unparseable,
}

impl Bound {
    /// The absolute calendar-day index, if this bound is absolute.
    fn absolute_day(self) -> Option<DayIdx> {
        match self {
            Self::Absolute(day) => Some(day),
            Self::Relative(_) | Self::Unparseable => None,
        }
    }
}

/// Classify a single `explicit_datetime` bound string.
fn classify_bound(raw: &str) -> Bound {
    if let Some(day) = absolute_datetime_to_day(raw) {
        return Bound::Absolute(day);
    }
    match relative_offset_to_window(raw) {
        Some(window) => Bound::Relative(window),
        None => Bound::Unparseable,
    }
}

/// Extract an absolute `explicit_datetime` bound's calendar **date** (date part), **tz-naively**, as a
/// day index. The oracle treats a naive `explicit_datetime` as a tz-naive calendar date stamped in the
/// project tz, so `toDate('2026-05-01')` is the literal `2026-05-01` regardless of timezone — the bound
/// must therefore be a day, not a UTC instant (storing it as a UTC instant shifts it one calendar day
/// earlier for a UTC-offset team). Accepts every naive shape the system emits:
///   - bare `%Y-%m-%d` (the date-picker's date-only / oracle `strptime("%Y-%m-%d")` fallback),
///   - `%Y-%m-%dT%H:%M:%S` (the date-picker's T-separated naive form — `dateFilterLogic.ts`),
///   - `%Y-%m-%d %H:%M:%S%.f` (the space-separated ClickHouse form),
///   - RFC3339 with offset (a non-UI edge): take its **written local date** via `.date_naive()`, not the
///     UTC-normalized one — the oracle's `toDate` is on the project-tz wall clock, and an offset-bearing
///     bound is not produced by the cohort date picker, so the written-date reading is the conservative
///     match.
///
/// Relative strings (`"-30d"`) return [`None`].
fn absolute_datetime_to_day(raw: &str) -> Option<DayIdx> {
    use chrono::{DateTime, NaiveDate, NaiveDateTime};

    // Offset-bearing RFC3339: take the written local date, not the UTC-normalized instant.
    if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
        return Some(day_idx_of_naive_date(dt.date_naive()));
    }
    // Naive datetime, T-separated (the date picker) or space-separated (ClickHouse) — date part only.
    let naive = NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f"))
        .map(|dt| dt.date())
        // Bare date.
        .or_else(|_| NaiveDate::parse_from_str(raw, "%Y-%m-%d"))
        .ok()?;
    Some(day_idx_of_naive_date(naive))
}

/// Parse a relative offset (`-N<unit>`) into its sliding [`EvictionWindow`], matching the oracle's
/// `relative_date_parse` grammar. Returns:
///   - `Some(Some(window))` for a unit with a clean `TimeInterval` equivalent (`d`/`w`/`m`/`y`/`h`/`M`);
///   - `Some(None)` for a recognized-but-unrepresentable unit (`q` quarter, `s` second — no cohort UI
///     emits these and they have no `TimeInterval`), signalling "relative, but skip the leaf";
///   - `None` when the string is not a relative offset at all.
///
/// `m` is **months** and `M` is **minutes** (Python's `[hdwmqysHDWMQY]` grammar is case-sensitive on
/// `m`/`M`). Mapping each unit through [`TimeInterval`] keeps a relative `-N<unit>` byte-identical to
/// the `time_value:N, time_interval:<unit>` path, which is exactly how the oracle treats them.
fn relative_offset_to_window(raw: &str) -> Option<Option<EvictionWindow>> {
    let rest = raw.strip_prefix('-')?;
    // Split into the leading digit run and the trailing unit (+ optional `Start`/`End`, which we drop
    // — the cohort UI never emits it and it does not change the window length).
    let split = rest.find(|c: char| !c.is_ascii_digit())?;
    let (digits, tail) = rest.split_at(split);
    let count: i32 = digits.parse().ok()?;
    let unit = tail
        .strip_suffix("Start")
        .or_else(|| tail.strip_suffix("End"))
        .unwrap_or(tail);
    let interval = match unit {
        "d" => TimeInterval::Day,
        "w" => TimeInterval::Week,
        "m" => TimeInterval::Month,
        "y" => TimeInterval::Year,
        "h" => TimeInterval::Hour,
        "M" => TimeInterval::Minute,
        // `q` (quarter) and `s` (second) are valid relative grammar but have no `TimeInterval`; the
        // cohort UI never emits them. Signal "relative, unrepresentable" so the leaf is skipped.
        "q" | "s" => return Some(None),
        _ => return None,
    };
    Some(Some(relative_window_from_interval(interval, Some(count))))
}

/// Build the sliding [`EvictionWindow`] for `time_value × interval`. Sub-day intervals yield
/// [`EvictionWindow::RelativeSeconds`]; whole-day intervals yield [`EvictionWindow::RelativeDays`].
/// A negative or absent `time_value` clamps to 0 rather than going negative.
fn relative_window_from_interval(
    interval: TimeInterval,
    time_value: Option<i32>,
) -> EvictionWindow {
    let time_value = time_value.unwrap_or(0).max(0);
    if interval.to_days() == 0 {
        EvictionWindow::RelativeSeconds {
            seconds: i64::from(time_value).saturating_mul(interval.seconds()),
        }
    } else {
        EvictionWindow::RelativeDays {
            days: u32::try_from(time_value)
                .unwrap_or(0)
                .saturating_mul(interval.to_days()),
        }
    }
}

/// The whole-day sliding window for a `performed_event_multiple` leaf.
///
/// `explicit_datetime`(_to) takes precedence over `time_value`/`time_interval`, mirroring the single
/// `performed_event` path ([`eviction_window`]) and the oracle's `if prop.explicit_datetime` branch.
/// Only a relative-lower-only bound (`"-Nd"`, the dominant "in the last N days" shape) has a whole-day
/// sliding form; every other explicit shape — and every sub-day or unrecognized interval — returns `0`,
/// which [`pick_state_variant`] maps to [`UnsupportedVariant::HourlyDeferred`] (the leaf drops).
pub(crate) fn effective_window_days(leaf: &BehavioralLeafConfig) -> u32 {
    if leaf.explicit_datetime.is_some() || leaf.explicit_datetime_to.is_some() {
        return explicit_window_days(
            leaf.explicit_datetime.as_deref(),
            leaf.explicit_datetime_to.as_deref(),
        );
    }
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

/// The whole-day window for an `explicit_datetime`(_to) `performed_event_multiple` bound, reusing the
/// single path's [`explicit_eviction_window`] classifier as the one source of truth. A sliding window
/// is only representable for a relative-lower-only whole-day bound; every other shape (sub-day, absolute
/// range, two-sided/relative-upper range, unparseable) has no whole-day sliding form → `0` → the leaf
/// drops, exactly as before this fix (which returned `0` for every explicit-datetime multiple leaf).
fn explicit_window_days(from: Option<&str>, to: Option<&str>) -> u32 {
    match explicit_eviction_window(from, to) {
        Ok(EvictionWindow::RelativeDays { days }) => days,
        Ok(EvictionWindow::RelativeSeconds { .. } | EvictionWindow::Explicit { .. }) | Err(_) => 0,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use chrono::{NaiveDate, TimeZone, Utc};
    use chrono_tz::America::New_York;
    use chrono_tz::UTC;

    use super::*;

    use crate::stage1::key::LeafStateKey;

    const HASH: [u8; 16] = *b"0123456789abcdef";

    /// Epoch-ms of a UTC wall-clock time.
    fn utc_ms(year: i32, month: u32, day: u32, hour: u32, minute: u32) -> i64 {
        Utc.with_ymd_and_hms(year, month, day, hour, minute, 0)
            .unwrap()
            .timestamp_millis()
    }

    /// The tz-naive calendar-day index of a `Y-M-D` date — what an absolute bound resolves to.
    fn day_of(year: i32, month: u32, day: u32) -> DayIdx {
        day_idx_of_naive_date(NaiveDate::from_ymd_opt(year, month, day).unwrap())
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

    /// Build a `performed_event` leaf carrying an explicit datetime range.
    fn explicit_leaf(from: Option<&str>, to: Option<&str>) -> BehavioralLeafConfig {
        let mut l = leaf(BehavioralValue::PerformedEvent, None, None);
        l.explicit_datetime = from.map(str::to_string);
        l.explicit_datetime_to = to.map(str::to_string);
        l.with_state_key()
    }

    #[test]
    fn absolute_explicit_datetime_yields_an_explicit_window() {
        // The space-separated ClickHouse form and the date picker's T-separated naive form must both
        // resolve to the same calendar-day bounds — the date part, tz-naively.
        for (from, to) in [
            ("2026-01-01 00:00:00.000000", "2026-02-01 00:00:00.000000"),
            ("2026-01-01T00:00:00", "2026-02-01T00:00:00"),
        ] {
            let (variant, window) =
                pick_state_variant(&explicit_leaf(Some(from), Some(to))).unwrap();
            assert_eq!(variant, StateVariant::BehavioralSingle);
            assert_eq!(
                window,
                Some(EvictionWindow::Explicit {
                    from_day: Some(day_of(2026, 1, 1)),
                    to_day: Some(day_of(2026, 2, 1)),
                }),
                "{from}..{to}",
            );
        }
    }

    #[test]
    fn absolute_explicit_from_only_leaves_upper_bound_unbounded() {
        let from = "2026-01-01 00:00:00.000000";
        let (_, window) = pick_state_variant(&explicit_leaf(Some(from), None)).unwrap();
        assert_eq!(
            window,
            Some(EvictionWindow::Explicit {
                from_day: Some(day_of(2026, 1, 1)),
                to_day: None,
            }),
        );
    }

    #[test]
    fn absolute_explicit_to_only_leaves_lower_bound_unbounded() {
        let to = "2026-02-01 00:00:00.000000";
        let (_, window) = pick_state_variant(&explicit_leaf(None, Some(to))).unwrap();
        assert_eq!(
            window,
            Some(EvictionWindow::Explicit {
                from_day: None,
                to_day: Some(day_of(2026, 2, 1)),
            }),
        );
    }

    #[test]
    fn absolute_datetime_to_day_is_the_literal_date_for_every_accepted_shape() {
        // Bare, T-separated naive (the date picker), space-separated ClickHouse, and RFC3339-with-offset
        // must all yield the same tz-naive calendar day — the written date, never UTC-shifted.
        let expected = day_of(2026, 5, 1);
        for raw in [
            "2026-05-01",
            "2026-05-01T00:00:00",
            "2026-05-01 00:00:00.000000",
            "2026-05-01T12:34:56-04:00", // offset-bearing: written local date is still 2026-05-01
        ] {
            assert_eq!(absolute_datetime_to_day(raw), Some(expected), "{raw}");
        }
        // A relative offset is not an absolute date.
        assert_eq!(absolute_datetime_to_day("-30d"), None);
    }

    #[test]
    fn bare_date_explicit_bound_parses_as_the_literal_calendar_day() {
        // The cohort date picker can emit a date-only absolute bound; the oracle accepts it via its
        // `strptime("%Y-%m-%d")` fallback. It resolves to the literal calendar day, tz-invariant.
        let (_, window) = pick_state_variant(&explicit_leaf(Some("2026-01-01"), None)).unwrap();
        assert_eq!(
            window,
            Some(EvictionWindow::Explicit {
                from_day: Some(day_of(2026, 1, 1)),
                to_day: None,
            }),
        );
    }

    #[test]
    fn ui_t_separated_upper_bound_parses_and_bounds_the_range() {
        // The date picker emits the upper bound as `dayjs(...).format('YYYY-MM-DDTHH:mm:ss')`
        // (T-separated, no offset). It must parse to the correct `to_day`, not be silently dropped —
        // dropping it would turn the closed range open-ended.
        let (_, window) = pick_state_variant(&explicit_leaf(
            Some("2026-01-01"),
            Some("2026-12-31T00:00:00"),
        ))
        .unwrap();
        assert_eq!(
            window,
            Some(EvictionWindow::Explicit {
                from_day: Some(day_of(2026, 1, 1)),
                to_day: Some(day_of(2026, 12, 31)),
            }),
        );
    }

    #[test]
    fn a_present_but_unparseable_bound_skips_the_leaf_rather_than_nulling_that_side() {
        // A present bound that is neither absolute nor relative-grammar must skip the leaf (no state),
        // NOT be nulled — nulling one side of a closed range would create permanent members past the
        // intended end.
        for (from, to) in [
            (Some("garbage"), Some("2026-12-31")),
            (Some("2026-01-01"), Some("garbage")),
            (Some("garbage"), None),
        ] {
            assert_eq!(
                pick_state_variant(&explicit_leaf(from, to)),
                Err(UnsupportedVariant::UnparseableExplicitBound),
                "{from:?}..{to:?}",
            );
        }
    }

    #[test]
    fn relative_lower_only_explicit_maps_to_the_matching_sliding_window() {
        // "-Nd"/"-Nw"/"-Nm"/"-Ny"/"-Nh"/"-NM" with no upper bound are the dominant `performed_event`
        // shape; each maps to the identical window as `time_value:N, time_interval:<unit>`.
        let cases = [
            ("-30d", EvictionWindow::RelativeDays { days: 30 }),
            ("-1w", EvictionWindow::RelativeDays { days: 7 }),
            ("-2m", EvictionWindow::RelativeDays { days: 2 * 30 }),
            ("-1y", EvictionWindow::RelativeDays { days: 365 }),
            (
                "-2h",
                EvictionWindow::RelativeSeconds { seconds: 2 * 3_600 },
            ),
            ("-15M", EvictionWindow::RelativeSeconds { seconds: 15 * 60 }),
        ];
        for (raw, expected) in cases {
            let (variant, window) = pick_state_variant(&explicit_leaf(Some(raw), None)).unwrap();
            assert_eq!(variant, StateVariant::BehavioralSingle, "{raw}");
            assert_eq!(window, Some(expected), "{raw}");
        }
    }

    #[test]
    fn relative_window_matches_the_time_value_interval_path_byte_for_byte() {
        // A relative `explicit_datetime` and the equivalent `time_value`/`time_interval` must resolve
        // to the same window — they are the same query in the oracle.
        for (raw, time_value, interval) in [
            ("-30d", 30, "day"),
            ("-1w", 1, "week"),
            ("-2m", 2, "month"),
            ("-1y", 1, "year"),
            ("-2h", 2, "hour"),
            ("-15M", 15, "minute"),
        ] {
            let (_, relative) = pick_state_variant(&explicit_leaf(Some(raw), None)).unwrap();
            let (_, interval_path) = pick_state_variant(&leaf(
                BehavioralValue::PerformedEvent,
                Some(time_value),
                Some(interval),
            ))
            .unwrap();
            assert_eq!(relative, interval_path, "{raw} vs {time_value}{interval}");
        }
    }

    #[test]
    fn relative_explicit_ranges_and_relative_upper_bounds_are_unsupported() {
        // Two-sided relative, relative upper bound, and relative-lower + absolute-upper all need
        // delayed-entry / double-ended eviction the sweep cannot model.
        let cases = [
            (Some("-30d"), Some("-7d")),                        // two-sided relative
            (Some("2026-01-01 00:00:00.000000"), Some("-7d")),  // absolute lower, relative upper
            (Some("-30d"), Some("2026-12-31 00:00:00.000000")), // relative lower, absolute upper
            (None, Some("-7d")),                                // relative upper only
        ];
        for (from, to) in cases {
            assert_eq!(
                pick_state_variant(&explicit_leaf(from, to)),
                Err(UnsupportedVariant::RelativeRangeUnsupported),
                "{from:?}..{to:?}",
            );
        }
    }

    #[test]
    fn unrepresentable_relative_units_are_unsupported() {
        // `q` (quarter) and `s` (second) are valid relative grammar but have no `TimeInterval`, so a
        // relative-lower-only bound in one of those units skips as a relative range.
        for raw in ["-1q", "-30s"] {
            assert_eq!(
                pick_state_variant(&explicit_leaf(Some(raw), None)),
                Err(UnsupportedVariant::RelativeRangeUnsupported),
                "{raw}",
            );
        }
    }

    #[test]
    fn an_outright_garbage_bound_is_an_unparseable_skip() {
        // A string that is neither an absolute date nor relative grammar is `UnparseableExplicitBound`,
        // distinct from a recognized-relative-but-unrepresentable unit.
        assert_eq!(
            pick_state_variant(&explicit_leaf(Some("not-a-date"), None)),
            Err(UnsupportedVariant::UnparseableExplicitBound),
        );
    }

    #[test]
    fn subday_window_deadline_is_event_plus_window() {
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
        let window = EvictionWindow::RelativeDays { days: 0 };
        let event_ms = utc_ms(2026, 5, 26, 9, 0);
        assert_eq!(
            window.earliest_eviction_at_ms(event_ms, UTC),
            start_of_day_ms_in_tz(day_idx_in_tz(event_ms, UTC) + 1, UTC),
        );
    }

    #[test]
    fn explicit_window_never_evicts_for_permanent_membership() {
        // An in-range absolute match is permanent: never evict at the upper bound, or the sweep would
        // emit a spurious `Left` even though the oracle's fixed-date predicate still matches.
        for window in [
            EvictionWindow::Explicit {
                from_day: Some(day_of(2026, 1, 1)),
                to_day: Some(day_of(2026, 12, 31)),
            },
            EvictionWindow::Explicit {
                from_day: None,
                to_day: None,
            },
            EvictionWindow::Explicit {
                from_day: Some(day_of(2026, 1, 1)),
                to_day: None,
            },
        ] {
            assert_eq!(window.earliest_eviction_at_ms(1_000, UTC), i64::MAX);
        }
    }

    /// Build a `performed_event_multiple` leaf carrying an explicit datetime range (gte 3).
    fn explicit_multiple_leaf(from: Option<&str>, to: Option<&str>) -> BehavioralLeafConfig {
        let mut l = leaf(BehavioralValue::PerformedEventMultiple, None, None);
        l.operator = Some("gte".to_string());
        l.operator_value = Some(3);
        l.explicit_datetime = from.map(str::to_string);
        l.explicit_datetime_to = to.map(str::to_string);
        l.with_state_key()
    }

    #[test]
    fn performed_event_multiple_explicit_datetime_routes_by_effective_window_days() {
        let daily = Ok((StateVariant::BehavioralDailyBuckets, None));
        let compressed = Ok((StateVariant::BehavioralCompressedHistory, None));
        let deferred = Err(UnsupportedVariant::HourlyDeferred);
        // Only a relative-lower-only whole-day bound has a sliding form. Every other explicit shape
        // funnels to 0 → HourlyDeferred by design — the shape distinction is intentionally erased once
        // it passes through `effective_window_days` (the discarded `UnsupportedVariant` buys no
        // observability, so the overload is accepted, matching the time_value/interval path).
        let cases = [
            (
                Some("-7d"),
                None,
                7,
                daily,
                "relative lower -7d → 7 days → daily",
            ),
            (
                Some("-180d"),
                None,
                180,
                daily,
                "-180d → 180 days → daily (upper boundary)",
            ),
            (
                Some("-1y"),
                None,
                365,
                compressed,
                "-1y ≡ -365d → compressed",
            ),
            (
                Some("-181d"),
                None,
                181,
                compressed,
                "-181d → just over the daily boundary → compressed",
            ),
            (
                Some("-2h"),
                None,
                0,
                deferred,
                "sub-day hour → 0 → deferred",
            ),
            (
                Some("-30M"),
                None,
                0,
                deferred,
                "sub-day minute → 0 → deferred",
            ),
            (
                Some("-1q"),
                None,
                0,
                deferred,
                "unrepresentable quarter unit → 0 → deferred",
            ),
            (
                Some("2026-01-01"),
                Some("2026-12-31"),
                0,
                deferred,
                "absolute range → 0 → deferred",
            ),
            (
                Some("2026-01-01"),
                None,
                0,
                deferred,
                "absolute lower only → 0 → deferred",
            ),
            (
                Some("-30d"),
                Some("-7d"),
                0,
                deferred,
                "relative range → 0 → deferred",
            ),
            (
                Some("garbage"),
                None,
                0,
                deferred,
                "unparseable bound → 0 → deferred",
            ),
        ];
        for (from, to, days, expected, why) in cases {
            let leaf = explicit_multiple_leaf(from, to);
            assert_eq!(effective_window_days(&leaf), days, "window_days: {why}");
            assert_eq!(pick_state_variant(&leaf), expected, "variant: {why}");
        }
    }

    #[test]
    fn explicit_relative_window_days_match_the_time_value_interval_multiple_path() {
        // A relative `explicit_datetime` and the equivalent `time_value`/`time_interval` resolve to the
        // same window days and state variant for a `performed_event_multiple` — the same oracle query.
        for (raw, time_value, interval) in [
            ("-30d", 30, "day"),
            ("-1w", 1, "week"),
            ("-2m", 2, "month"),
            ("-1y", 1, "year"),
        ] {
            let explicit = explicit_multiple_leaf(Some(raw), None);
            let interval_path = leaf(
                BehavioralValue::PerformedEventMultiple,
                Some(time_value),
                Some(interval),
            );
            assert_eq!(
                effective_window_days(&explicit),
                effective_window_days(&interval_path),
                "{raw} vs {time_value}{interval} window_days",
            );
            assert_eq!(
                pick_state_variant(&explicit),
                pick_state_variant(&interval_path),
                "{raw} vs {time_value}{interval} variant",
            );
        }
    }
}
