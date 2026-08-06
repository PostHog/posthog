//! Public-API smoke test for the calendar-day bucket math. The exhaustive DST / boundary golden
//! matrix lives in the in-crate `#[cfg(test)]` module; this only pins that the module is reachable
//! through its public path and that the headline window/DST contracts hold from outside the crate.

use chrono_tz::America::New_York;
use chrono_tz::{Tz, UTC};
use cohort_stream_processor::stage1::bucket_tz::{
    daily_bucket_len, day_idx_in_tz, resolve_tz_or_utc, start_of_day_ms_in_tz, window_start_day,
    DayIdx,
};

const MS_PER_DAY: i64 = 86_400_000;

fn utc_day_ms(day: DayIdx) -> i64 {
    i64::from(day) * MS_PER_DAY
}

#[test]
fn utc_day_index_round_trips_through_start_of_day() {
    let day: DayIdx = 20_600; // ~2026
    let start = utc_day_ms(day);
    assert_eq!(day_idx_in_tz(start, UTC), day);
    assert_eq!(start_of_day_ms_in_tz(day, UTC), start);
}

#[test]
fn window_is_inclusive_n_plus_one_days() {
    let now_ms = utc_day_ms(20_600) + 9 * 3_600_000;
    let now_day = day_idx_in_tz(now_ms, UTC);
    assert_eq!(window_start_day(now_ms, 7, UTC), now_day - 7);
    assert_eq!(daily_bucket_len(7), 8);
}

#[test]
fn resolve_tz_or_utc_is_reachable_and_falls_back() {
    let tz: Tz = resolve_tz_or_utc("America/New_York");
    assert_eq!(tz, New_York);
    assert_eq!(resolve_tz_or_utc("nonsense"), UTC);
}
