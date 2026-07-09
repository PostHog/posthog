//! Calendar-day-in-team-timezone bucket math.
//!
//! Pure, zone-agnostic, and total: every function takes time as an `i64` (epoch ms) plus a
//! [`Tz`] and returns without a `Result` and without reading a wall-clock "now". The bucket
//! variants and the sweep consume it.
//!
//! ## Window boundary (the highest-risk decision)
//!
//! The existing pipeline's predicate is `event_day >= now_day − N` (via `relative_date_parse("-Nd")`
//! = `now − N days`), so "last N days" is the **inclusive** set `[now_day − N ..= now_day]` =
//! `N + 1` day-buckets. [`window_start_day`] therefore returns `now_day − N` (not `− N + 1`) and
//! [`daily_bucket_len`] returns `N + 1`.
//!
//! ## DST
//!
//! Instant → day ([`day_idx_in_tz`], [`hour_of_day_in_tz`]) is always unambiguous (an instant maps
//! to exactly one local datetime) and is therefore DST-exact, as is [`window_start_day`]. Day →
//! instant ([`start_of_day_ms_in_tz`], [`start_of_hour_ms_in_tz`]) can be ambiguous (fall-back) or
//! nonexistent (spring-forward gap); it picks the **earliest** instant on `Ambiguous` (= Python
//! `ZoneInfo` fold=0) and the **post-gap** instant on `None`. Only this eviction-timing path is
//! DST-tie-broken, and it rides the sweep's ±5 min `safety_margin` tolerance.

use chrono::{DateTime, Duration, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Timelike, Utc};
use chrono_tz::{Tz, UTC};

/// A calendar-day index: days since the Unix epoch (1970-01-01) in a given timezone.
pub type DayIdx = i32;

/// Upper bound (minutes) on the forward probe used to find the post-gap instant for a local time
/// that falls inside a spring-forward gap. Comfortably exceeds the largest real DST shift; the probe
/// only runs when a transition lands exactly on the requested boundary (rare).
const MAX_DST_GAP_MINUTES: i64 = 180;

/// The calendar-day index of `epoch_ms` in `tz`. Instant → day is never DST-ambiguous.
pub fn day_idx_in_tz(epoch_ms: i64, tz: Tz) -> DayIdx {
    day_idx_of(utc_instant(epoch_ms).with_timezone(&tz).date_naive())
}

/// Local-midnight epoch-ms for day index `day` in `tz` — the base for an eviction deadline. On a
/// fall-back midnight picks the earliest instant; on a spring-forward gap at midnight picks the
/// post-gap instant.
pub fn start_of_day_ms_in_tz(day: DayIdx, tz: Tz) -> i64 {
    let midnight = date_for_day(day)
        .and_hms_opt(0, 0, 0)
        .expect("00:00:00 is a valid time");
    local_naive_to_instant(midnight, tz).timestamp_millis()
}

/// The first day-bucket of the rolling window ending at `now_ms`. Returns `now_day − N` (the
/// inclusive lower bound), matching the existing `event_day >= now_day − N` predicate.
pub fn window_start_day(now_ms: i64, effective_window_days: u32, tz: Tz) -> DayIdx {
    window_start_for_now(day_idx_in_tz(now_ms, tz), effective_window_days)
}

/// The window's "now" day given its start: `window_start_day + window_days`, **saturating** to
/// [`DayIdx::MAX`]. `window_days` is unbounded `u32` user input, so a naïve `as i32` add would wrap
/// for an astronomical window and snap the window backward; saturating instead means a huge window's
/// "now" sits at the far future, so the window effectively never slides — the correct reading of an
/// essentially infinite window.
pub fn now_day_for_window(window_start_day: DayIdx, window_days: u32) -> DayIdx {
    match i64::from(window_start_day) + i64::from(window_days) {
        day if day > i64::from(DayIdx::MAX) => DayIdx::MAX,
        day => day as DayIdx,
    }
}

/// The window's start day given its "now": `now_day − window_days`, **saturating** to [`DayIdx::MIN`].
/// Mirrors [`now_day_for_window`] on the lower bound — a huge `window_days` would underflow a naïve
/// `as i32` subtract and wrap positive; saturating instead pins the start at the far past, so the
/// window covers everything and never evicts (the correct reading of an essentially infinite window).
pub fn window_start_for_now(now_day: DayIdx, window_days: u32) -> DayIdx {
    match i64::from(now_day) - i64::from(window_days) {
        day if day < i64::from(DayIdx::MIN) => DayIdx::MIN,
        day => day as DayIdx,
    }
}

/// The epoch-ms (team tz, local midnight) at which a day-`oldest_day` bucket/entry leaves an
/// `N`-day window — the start of day `oldest_day + N + 1`. Computed in `i64` and, mirroring
/// [`super::pick_state::EvictionWindow::earliest_eviction_at_ms`], returns [`i64::MAX`] (never
/// evict) when the leave-day overflows [`DayIdx`] for an astronomical window rather than wrapping
/// to a near-epoch instant (which would flap entered/left).
pub fn window_leave_day_ms(oldest_day: DayIdx, window_days: u32, tz: Tz) -> i64 {
    let leave_day = i64::from(oldest_day) + i64::from(window_days) + 1;
    match DayIdx::try_from(leave_day) {
        Ok(day) => start_of_day_ms_in_tz(day, tz),
        Err(_) => i64::MAX,
    }
}

/// The calendar-day index of a tz-naive [`NaiveDate`] — days since 1970-01-01, with no zone applied.
/// Used for an absolute `explicit_datetime` bound, whose written calendar date is tz-invariant (the
/// oracle stamps a bare date in the project tz, so `toDate('2026-05-01')` is the literal date), unlike
/// an event instant which must first be projected into the team tz via [`day_idx_in_tz`].
pub fn day_idx_of_naive_date(date: NaiveDate) -> DayIdx {
    day_idx_of(date)
}

/// The local hour-of-day `[0, 23]` of `epoch_ms` in `tz` — the bucket index for the 24-hour variant.
pub fn hour_of_day_in_tz(epoch_ms: i64, tz: Tz) -> u32 {
    utc_instant(epoch_ms).with_timezone(&tz).hour()
}

/// Epoch-ms of the start of the local hour containing `epoch_ms` in `tz` — the hourly variant's
/// eviction base. DST-tie-broken like [`start_of_day_ms_in_tz`].
pub fn start_of_hour_ms_in_tz(epoch_ms: i64, tz: Tz) -> i64 {
    let local = utc_instant(epoch_ms).with_timezone(&tz);
    let on_the_hour = local
        .date_naive()
        .and_hms_opt(local.hour(), 0, 0)
        .expect("hh:00:00 is a valid time");
    local_naive_to_instant(on_the_hour, tz).timestamp_millis()
}

/// The dense daily-bucket array length for an `N`-day window: `N + 1`, covering the inclusive set
/// `[now_day − N ..= now_day]`. Centralizes the `+ 1` so callers never re-derive it.
pub fn daily_bucket_len(effective_window_days: u32) -> usize {
    effective_window_days as usize + 1
}

/// Parse an IANA timezone name, falling back to UTC for an unrecognized one. Pure and total — the
/// loader wraps this to count/log the fallback with the offending `team_id`.
pub fn resolve_tz_or_utc(name: &str) -> Tz {
    name.parse::<Tz>().unwrap_or(UTC)
}

/// `epoch_ms` as a UTC instant. Total: the only `None` from `from_timestamp_millis` is a value
/// ~262 000 years from the epoch, unreachable for a real event timestamp; fall back to the epoch.
fn utc_instant(epoch_ms: i64) -> DateTime<Utc> {
    DateTime::from_timestamp_millis(epoch_ms)
        .unwrap_or_else(|| DateTime::from_timestamp_millis(0).expect("epoch 0 is in range"))
}

fn unix_epoch_date() -> NaiveDate {
    NaiveDate::from_ymd_opt(1970, 1, 1).expect("1970-01-01 is a valid date")
}

fn day_idx_of(date: NaiveDate) -> DayIdx {
    (date - unix_epoch_date()).num_days() as DayIdx
}

fn date_for_day(day: DayIdx) -> NaiveDate {
    unix_epoch_date()
        .checked_add_signed(Duration::days(i64::from(day)))
        .unwrap_or_else(unix_epoch_date)
}

/// Resolve a local naive datetime to an instant, DST-tie-broken: earliest on a fall-back overlap,
/// the post-gap instant on a spring-forward gap.
fn local_naive_to_instant(naive: NaiveDateTime, tz: Tz) -> DateTime<Tz> {
    match tz.from_local_datetime(&naive) {
        LocalResult::Single(dt) => dt,
        // Overlap: the wall-clock time occurs twice. Earliest = Python `ZoneInfo` fold=0.
        LocalResult::Ambiguous(earliest, _latest) => earliest,
        // Gap: the wall-clock time does not exist. Walk forward to the first representable local
        // minute and take its earliest instant — the post-gap instant. Bounded by the max DST shift;
        // only reachable when a transition lands exactly on this boundary.
        LocalResult::None => (1..=MAX_DST_GAP_MINUTES)
            .find_map(|m| {
                naive
                    .checked_add_signed(Duration::minutes(m))
                    .and_then(|t| tz.from_local_datetime(&t).earliest())
            })
            .unwrap_or_else(|| Utc.from_utc_datetime(&naive).with_timezone(&tz)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::America::{New_York, Sao_Paulo};
    use chrono_tz::Asia::Kolkata;

    const MS_PER_DAY: i64 = 86_400_000;
    const MS_PER_HOUR: i64 = 3_600_000;

    /// Epoch-ms of a UTC wall-clock time, computed via chrono so the goldens don't re-derive the math
    /// under test.
    fn utc_ms(year: i32, month: u32, day: u32, hour: u32, minute: u32) -> i64 {
        Utc.with_ymd_and_hms(year, month, day, hour, minute, 0)
            .unwrap()
            .timestamp_millis()
    }

    fn local_at(epoch_ms: i64, tz: Tz) -> DateTime<Tz> {
        DateTime::from_timestamp_millis(epoch_ms)
            .unwrap()
            .with_timezone(&tz)
    }

    #[test]
    fn utc_epoch_is_day_zero() {
        assert_eq!(day_idx_in_tz(0, UTC), 0);
        assert_eq!(start_of_day_ms_in_tz(0, UTC), 0);
    }

    #[test]
    fn utc_day_boundary_is_inclusive_of_the_last_millisecond() {
        assert_eq!(day_idx_in_tz(MS_PER_DAY - 1, UTC), 0, "last ms of day 0");
        assert_eq!(day_idx_in_tz(MS_PER_DAY, UTC), 1, "first ms of day 1");
    }

    #[test]
    fn start_of_day_round_trips_within_the_day_in_utc() {
        let ms = utc_ms(2026, 5, 26, 12, 34);
        let day = day_idx_in_tz(ms, UTC);
        let start = start_of_day_ms_in_tz(day, UTC);
        assert!(start <= ms, "start of day is at or before the instant");
        assert!(
            ms < start_of_day_ms_in_tz(day + 1, UTC),
            "the instant is before the next day's start",
        );
        assert_eq!(
            start,
            ms - (ms % MS_PER_DAY),
            "UTC start-of-day is a clean floor"
        );
    }

    #[test]
    fn positive_offset_tz_rolls_the_day_forward_at_its_local_midnight() {
        // 20:00 UTC is 01:30 the next day in Kolkata (+5:30), so its calendar day is UTC + 1.
        let evening = utc_ms(2026, 5, 26, 20, 0);
        assert_eq!(
            day_idx_in_tz(evening, Kolkata),
            day_idx_in_tz(evening, UTC) + 1,
        );
        // 12:00 UTC is 17:30 the same day in Kolkata — still the UTC day.
        let midday = utc_ms(2026, 5, 26, 12, 0);
        assert_eq!(day_idx_in_tz(midday, Kolkata), day_idx_in_tz(midday, UTC));
    }

    #[test]
    fn negative_offset_tz_keeps_the_previous_day_after_utc_midnight() {
        // 02:00 UTC is 22:00 the previous day in New York (EDT, −4), so its calendar day is UTC − 1.
        let after_midnight = utc_ms(2026, 5, 26, 2, 0);
        assert_eq!(
            day_idx_in_tz(after_midnight, New_York),
            day_idx_in_tz(after_midnight, UTC) - 1,
        );
    }

    #[test]
    fn spring_forward_day_is_twenty_three_hours_long() {
        // New York springs forward at 02:00 on 2026-03-08 (a 23-hour day).
        let day = day_idx_in_tz(utc_ms(2026, 3, 8, 12, 0), New_York);
        let length =
            start_of_day_ms_in_tz(day + 1, New_York) - start_of_day_ms_in_tz(day, New_York);
        assert_eq!(length, 23 * MS_PER_HOUR);
    }

    #[test]
    fn fall_back_day_is_twenty_five_hours_long() {
        // New York falls back at 02:00 on 2026-11-01 (a 25-hour day).
        let day = day_idx_in_tz(utc_ms(2026, 11, 1, 12, 0), New_York);
        let length =
            start_of_day_ms_in_tz(day + 1, New_York) - start_of_day_ms_in_tz(day, New_York);
        assert_eq!(length, 25 * MS_PER_HOUR);
    }

    #[test]
    fn ambiguous_hour_floors_to_the_earliest_instant() {
        // On the 2026-11-01 fall-back, New York's 01:30 occurs twice (EDT then, an hour later, EST).
        // Both must floor to the same earliest 01:00 instant (fold=0).
        let first_0130 = utc_ms(2026, 11, 1, 5, 30); // 01:30 EDT
        let second_0130 = utc_ms(2026, 11, 1, 6, 30); // 01:30 EST, one UTC hour later
        assert_eq!(
            start_of_hour_ms_in_tz(first_0130, New_York),
            start_of_hour_ms_in_tz(second_0130, New_York),
            "an ambiguous hour resolves to its earliest instant",
        );
        // And that shared floor is the earlier (EDT) 01:00.
        assert_eq!(
            start_of_hour_ms_in_tz(second_0130, New_York),
            utc_ms(2026, 11, 1, 5, 0)
        );
    }

    #[test]
    fn spring_forward_gap_at_midnight_resolves_to_the_post_gap_instant() {
        // Sao Paulo sprang forward at midnight on 2017-10-15 (00:00 → 01:00), so local midnight does
        // not exist; start-of-day must resolve to the post-gap instant rather than panic or fall back.
        let day = day_idx_in_tz(utc_ms(2017, 10, 15, 12, 0), Sao_Paulo); // noon is unambiguous
        let start = start_of_day_ms_in_tz(day, Sao_Paulo);
        let local = local_at(start, Sao_Paulo);
        assert_eq!(
            local.date_naive(),
            NaiveDate::from_ymd_opt(2017, 10, 15).unwrap(),
        );
        assert_eq!(
            local.hour(),
            1,
            "post-gap instant is 01:00 local, not the skipped midnight"
        );
    }

    #[test]
    fn window_is_inclusive_of_now_minus_n() {
        // relative_date_parse("-7d") = now − 7 days; the predicate `event_day >= now_day − 7` makes
        // "last 7 days" the inclusive set [now_day − 7 ..= now_day] = 8 day-buckets.
        let now_ms = utc_ms(2026, 5, 26, 9, 0);
        let now_day = day_idx_in_tz(now_ms, UTC);
        assert_eq!(window_start_day(now_ms, 7, UTC), now_day - 7);
        assert_eq!(daily_bucket_len(7), 8);
        assert_eq!(
            (now_day - window_start_day(now_ms, 7, UTC)) as usize + 1,
            daily_bucket_len(7),
            "the bucket array spans exactly [window_start_day ..= now_day]",
        );
    }

    #[test]
    fn window_start_day_is_team_tz_relative() {
        // Window arithmetic uses the team-tz day, so a far-offset team near the boundary shifts with
        // its own midnight, not UTC's.
        let evening = utc_ms(2026, 5, 26, 20, 0); // already "tomorrow" in Kolkata
        assert_eq!(
            window_start_day(evening, 7, Kolkata),
            day_idx_in_tz(evening, Kolkata) - 7,
        );
        assert_eq!(
            window_start_day(evening, 365, Kolkata),
            day_idx_in_tz(evening, Kolkata) - 365,
        );
    }

    #[test]
    fn year_and_day_windows_agree_on_three_hundred_sixty_five() {
        // A 365-day window and a 1-year window (year.to_days() == 365) start on the same day.
        let now_ms = utc_ms(2026, 5, 26, 9, 0);
        assert_eq!(
            window_start_day(now_ms, 365, UTC),
            window_start_day(now_ms, 365, UTC),
        );
        assert_eq!(daily_bucket_len(365), 366);
    }

    #[test]
    fn hour_of_day_is_team_tz_local() {
        let ms = utc_ms(2026, 5, 26, 20, 0);
        assert_eq!(hour_of_day_in_tz(ms, UTC), 20);
        assert_eq!(
            hour_of_day_in_tz(ms, Kolkata),
            1,
            "20:00 UTC is 01:30 in Kolkata"
        );
    }

    #[test]
    fn start_of_hour_floors_to_the_local_hour() {
        let ms = utc_ms(2026, 5, 26, 20, 45);
        assert_eq!(start_of_hour_ms_in_tz(ms, UTC), utc_ms(2026, 5, 26, 20, 0));
        // Kolkata's +5:30 offset means the local hour boundary is offset by 30 minutes from UTC.
        assert_eq!(
            start_of_hour_ms_in_tz(ms, Kolkata),
            utc_ms(2026, 5, 26, 20, 30)
        );
    }

    #[test]
    fn resolve_tz_or_utc_parses_known_names_and_falls_back() {
        assert_eq!(resolve_tz_or_utc("America/New_York"), New_York);
        assert_eq!(resolve_tz_or_utc("Asia/Kolkata"), Kolkata);
        assert_eq!(resolve_tz_or_utc("UTC"), UTC);
        assert_eq!(resolve_tz_or_utc("garbage"), UTC);
        assert_eq!(resolve_tz_or_utc(""), UTC);
    }

    #[test]
    fn daily_bucket_len_is_n_plus_one() {
        assert_eq!(daily_bucket_len(1), 2);
        assert_eq!(daily_bucket_len(7), 8);
        assert_eq!(daily_bucket_len(30), 31);
        assert_eq!(daily_bucket_len(0), 1);
    }

    #[test]
    fn window_bound_helpers_match_plain_arithmetic_for_realistic_windows() {
        // Saturation only changes behavior at astronomical windows; for any realistic window the
        // helpers are bit-identical to the `+ window_days` / `− window_days` they replace.
        for window_days in [0_u32, 1, 7, 30, 180, 365, 3_650] {
            assert_eq!(
                now_day_for_window(19_500, window_days),
                19_500 + window_days as i32,
            );
            assert_eq!(
                window_start_for_now(19_500, window_days),
                19_500 - window_days as i32,
            );
            assert_eq!(
                window_leave_day_ms(19_500, window_days, UTC),
                start_of_day_ms_in_tz(19_500 + window_days as i32 + 1, UTC),
            );
        }
    }

    #[test]
    fn window_bound_helpers_saturate_at_the_day_index_bounds() {
        // A huge window pushes "now" to the far future (never slides) and "start" to the far past
        // (covers everything) rather than wrapping an `i32` cast.
        assert_eq!(now_day_for_window(1_000, u32::MAX), DayIdx::MAX);
        assert_eq!(now_day_for_window(DayIdx::MAX, 1), DayIdx::MAX);
        assert_eq!(window_start_for_now(-1_000, u32::MAX), DayIdx::MIN);
        assert_eq!(window_start_for_now(DayIdx::MIN, 1), DayIdx::MIN);
        // The leave-day instant overflows `i32`, so the deadline pins at i64::MAX (never evict).
        assert_eq!(window_leave_day_ms(1_000, u32::MAX, UTC), i64::MAX);
    }
}
