use chrono::{DateTime, Datelike, Duration, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Utc};
use chrono_tz::Tz;
use once_cell::sync::Lazy;
use regex::Regex;

// Compile regex once at startup
static RELATIVE_DATE_REGEX: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^-?(?P<number>[0-9]+)(?P<interval>[hdwmy])$").expect("Invalid regex pattern")
});

/// Parse a relative date string like "-3d", "3d", "-3h", etc., anchored to the
/// current UTC time.
///
/// Returns None if the string doesn't match the expected format or if the number
/// is too large.
///
/// This implementation matches Python's behavior using relativedelta:
/// - Hours and days use fixed durations
/// - Weeks are 7 days
/// - Months and years use calendar-aware calculations
///
/// # Examples
/// ```
/// use chrono::Utc;
/// use feature_flags::properties::relative_date::parse_relative_date;
///
/// let now = Utc::now();
/// let three_days_ago = parse_relative_date("-3d").unwrap();
/// assert!(three_days_ago < now);
/// ```
pub fn parse_relative_date(date_str: &str) -> Option<DateTime<Utc>> {
    // The wall clock in UTC is the same as the absolute instant, so the naive
    // arithmetic below reproduces the previous UTC-anchored behavior exactly.
    parse_relative_date_naive(date_str, Utc::now().naive_utc()).map(|naive| naive.and_utc())
}

/// Parse a relative date string anchored to the current wall clock in `tz`,
/// returning the resulting instant in UTC.
///
/// This mirrors HogQL's `relative_date_parse(value, team.timezone_info)`: the
/// relativedelta arithmetic runs against the team-timezone wall clock, and the
/// resulting wall clock is then interpreted back in the team timezone. Keeping
/// the subtraction on the naive wall clock (rather than on an absolute UTC
/// instant) is what makes "in the last N days" land on the same local day
/// boundary in both engines.
pub fn parse_relative_date_in_tz(date_str: &str, tz: Tz) -> Option<DateTime<Utc>> {
    // Cheap reject for the common case (absolute date strings) before reading the
    // clock and localizing — that work is wasted whenever the regex won't match.
    if !RELATIVE_DATE_REGEX.is_match(date_str) {
        return None;
    }
    let now_local = Utc::now().with_timezone(&tz).naive_local();
    let result = parse_relative_date_naive(date_str, now_local)?;
    naive_to_utc_in_tz(result, tz)
}

/// Interpret a naive wall-clock datetime as a moment in `tz`, returning UTC.
///
/// On a DST fall-back overlap (the same wall clock occurs twice) we pick the
/// earliest instant; on a spring-forward gap (the wall clock never occurs) we
/// return None. The gap case is a ~1h/year edge well outside the day-boundary
/// window this fix targets, and a missing match there is preferable to a silently
/// shifted one.
pub(crate) fn naive_to_utc_in_tz(naive: NaiveDateTime, tz: Tz) -> Option<DateTime<Utc>> {
    match tz.from_local_datetime(&naive) {
        LocalResult::Single(dt) => Some(dt.with_timezone(&Utc)),
        LocalResult::Ambiguous(earliest, _latest) => Some(earliest.with_timezone(&Utc)),
        LocalResult::None => None,
    }
}

/// Apply the relativedelta-style subtraction purely on a naive wall clock.
///
/// All arithmetic is timezone-agnostic here; callers decide how to anchor `now`
/// and how to interpret the result. Time-of-day (including sub-second precision)
/// is preserved across calendar month/year shifts.
fn parse_relative_date_naive(date_str: &str, now: NaiveDateTime) -> Option<NaiveDateTime> {
    let captures = RELATIVE_DATE_REGEX.captures(date_str)?;

    let number: i64 = captures.name("number")?.as_str().parse().ok()?;
    if number >= 10_000 {
        // Guard against overflow, disallow numbers greater than 10_000
        return None;
    }

    let interval = captures.name("interval")?.as_str();

    match interval {
        "h" => Some(now - Duration::hours(number)),
        "d" => Some(now - Duration::days(number)),
        "w" => Some(now - Duration::weeks(number)),
        "m" => {
            // Calendar-aware month calculation
            let mut result = now;
            for _ in 0..number {
                // Go back one month, preserving the day if possible
                let day = result.day();
                let month = result.month();
                let year = result.year();

                // Calculate previous month
                let (prev_year, prev_month) = if month == 1 {
                    (year - 1, 12)
                } else {
                    (year, month - 1)
                };

                // Use the minimum of the original day and the last day of the previous month
                let new_day = day.min(last_day_of_month(prev_year, prev_month));
                result = NaiveDate::from_ymd_opt(prev_year, prev_month, new_day)?
                    .and_time(result.time());
            }
            Some(result)
        }
        "y" => {
            // Calendar-aware year calculation
            let mut result = now;
            for _ in 0..number {
                let year = result.year() - 1;
                let month = result.month();
                let day = result.day();

                // Handle February 29 in non-leap target years
                let new_day = if month == 2 {
                    day.min(last_day_of_month(year, month))
                } else {
                    day
                };

                result = NaiveDate::from_ymd_opt(year, month, new_day)?.and_time(result.time());
            }
            Some(result)
        }
        _ => None,
    }
}

/// Last calendar day of the given month, accounting for leap years.
fn last_day_of_month(year: i32, month: u32) -> u32 {
    if month == 2 {
        if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) {
            29
        } else {
            28
        }
    } else if [4, 6, 9, 11].contains(&month) {
        30
    } else {
        31
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Timelike, Utc};
    use test_case::test_case;

    // Helper function to parse relative date with a fixed "now" time. The naive
    // UTC wall clock equals the absolute instant, so this exercises the same
    // arithmetic the UTC-anchored `parse_relative_date` uses.
    fn parse_relative_date_fixed(date_str: &str, now: DateTime<Utc>) -> Option<DateTime<Utc>> {
        parse_relative_date_naive(date_str, now.naive_utc()).map(|naive| naive.and_utc())
    }

    #[test_case("-3d" => true; "negative days")]
    #[test_case("3d" => true; "positive days")]
    #[test_case("-3h" => true; "negative hours")]
    #[test_case("3h" => true; "positive hours")]
    #[test_case("-3w" => true; "negative weeks")]
    #[test_case("3w" => true; "positive weeks")]
    #[test_case("-3m" => true; "negative months")]
    #[test_case("3m" => true; "positive months")]
    #[test_case("-3y" => true; "negative years")]
    #[test_case("3y" => true; "positive years")]
    #[test_case("invalid" => false; "invalid format")]
    #[test_case("3x" => false; "invalid interval")]
    #[test_case("100000d" => false; "too large number")]
    fn test_parse_relative_date_validity(input: &str) -> bool {
        parse_relative_date(input).is_some()
    }

    #[test]
    fn test_invalid_input() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        // Test various invalid inputs
        assert!(parse_relative_date_fixed("1", now).is_none());
        assert!(parse_relative_date_fixed("1x", now).is_none());
        assert!(parse_relative_date_fixed("1.2y", now).is_none());
        assert!(parse_relative_date_fixed("1z", now).is_none());
        assert!(parse_relative_date_fixed("1s", now).is_none());
        assert!(parse_relative_date_fixed("123344000.134m", now).is_none());
        assert!(parse_relative_date_fixed("bazinga", now).is_none());
        assert!(parse_relative_date_fixed("000bello", now).is_none());
        assert!(parse_relative_date_fixed("000hello", now).is_none());

        // Valid inputs with leading zeros
        assert!(parse_relative_date_fixed("000h", now).is_some());
        assert!(parse_relative_date_fixed("1000h", now).is_some());
    }

    #[test]
    fn test_overflow() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert!(parse_relative_date_fixed("1000000h", now).is_none());
        assert!(parse_relative_date_fixed("100000000000000000y", now).is_none());
    }

    #[test]
    fn test_hour_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1h", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 1, 1, 11, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2h", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 1, 1, 10, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("24h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("30h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 6, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("48h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 30, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // 24h should equal 1d
        assert_eq!(
            parse_relative_date_fixed("24h", now).unwrap(),
            parse_relative_date_fixed("1d", now).unwrap()
        );
        // 48h should equal 2d
        assert_eq!(
            parse_relative_date_fixed("48h", now).unwrap(),
            parse_relative_date_fixed("2d", now).unwrap()
        );
    }

    #[test]
    fn test_day_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 30, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("7d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 25, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("14d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 18, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("30d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 2, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // 7d should equal 1w
        assert_eq!(
            parse_relative_date_fixed("7d", now).unwrap(),
            parse_relative_date_fixed("1w", now).unwrap()
        );
    }

    #[test]
    fn test_week_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 25, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 18, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 4, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 11, 6, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // Test month and year relationships
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_ne!(
            parse_relative_date_fixed("4w", now).unwrap(),
            parse_relative_date_fixed("1m", now).unwrap()
        );
    }

    #[test]
    fn test_month_parsing() {
        // Test from January
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 11, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 9, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 5, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // Test year relationships
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("12m", now).unwrap(),
            parse_relative_date_fixed("1y", now).unwrap()
        );

        // Test from April
        let now = Utc.with_ymd_and_hms(2020, 4, 3, 0, 0, 0).unwrap();

        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 3, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 2, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 8, 3, 0, 0, 0).unwrap()
        );

        // Test year relationships from April
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 4, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("12m", now).unwrap(),
            parse_relative_date_fixed("1y", now).unwrap()
        );
    }

    #[test]
    fn test_year_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2y", now).unwrap(),
            Utc.with_ymd_and_hms(2018, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4y", now).unwrap(),
            Utc.with_ymd_and_hms(2016, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8y", now).unwrap(),
            Utc.with_ymd_and_hms(2012, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
    }

    #[test]
    fn test_edge_cases() {
        // Test month boundaries
        let now = Utc.with_ymd_and_hms(2020, 3, 31, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 2, 29, 12, 0, 0).unwrap() // Leap year
        );

        let now = Utc.with_ymd_and_hms(2019, 3, 31, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 2, 28, 12, 0, 0).unwrap() // Non-leap year
        );

        // Test year boundaries
        let now = Utc.with_ymd_and_hms(2020, 2, 29, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 2, 28, 12, 0, 0).unwrap() // Non-leap year
        );

        // Test large numbers
        let now = Utc.with_ymd_and_hms(2020, 1, 1, 12, 0, 0).unwrap();
        assert!(parse_relative_date_fixed("9999d", now).is_some());
        assert!(parse_relative_date_fixed("9999h", now).is_some());
        assert!(parse_relative_date_fixed("9999w", now).is_some());
        assert!(parse_relative_date_fixed("9999m", now).is_some());
        assert!(parse_relative_date_fixed("9999y", now).is_some());
    }

    #[test]
    fn test_naive_to_utc_in_tz_pacific_offset() {
        // June → PDT (UTC-7). A wall clock of 2024-06-03 02:00 in Pacific is
        // 2024-06-03 09:00 UTC.
        let naive = NaiveDate::from_ymd_opt(2024, 6, 3)
            .unwrap()
            .and_hms_opt(2, 0, 0)
            .unwrap();
        let utc = naive_to_utc_in_tz(naive, Tz::America__Los_Angeles).unwrap();
        assert_eq!(utc, Utc.with_ymd_and_hms(2024, 6, 3, 9, 0, 0).unwrap());
    }

    #[test]
    fn test_relative_date_naive_anchored_in_tz_matches_hogql() {
        // Mirrors HogQL's relative_date_parse(value, team.timezone_info): the
        // relativedelta runs on the team-timezone wall clock, then the result is
        // interpreted back in the team timezone. Anchoring "now" to 2024-06-10
        // 02:00 Pacific, "-7d" lands on 2024-06-03 02:00 Pacific = 09:00 UTC.
        let now_pacific_wall = NaiveDate::from_ymd_opt(2024, 6, 10)
            .unwrap()
            .and_hms_opt(2, 0, 0)
            .unwrap();
        let result = parse_relative_date_naive("-7d", now_pacific_wall).unwrap();
        let utc = naive_to_utc_in_tz(result, Tz::America__Los_Angeles).unwrap();
        assert_eq!(utc, Utc.with_ymd_and_hms(2024, 6, 3, 9, 0, 0).unwrap());

        // The same wall clock interpreted as UTC (the pre-fix behavior) lands 7h
        // earlier, which is exactly the day-boundary divergence this fix removes.
        let utc_anchored = parse_relative_date_naive("-7d", now_pacific_wall)
            .unwrap()
            .and_utc();
        assert_eq!(
            utc_anchored,
            Utc.with_ymd_and_hms(2024, 6, 3, 2, 0, 0).unwrap()
        );
        assert_ne!(utc, utc_anchored);
    }

    #[test]
    fn test_naive_to_utc_in_tz_fall_back_picks_earliest() {
        // On 2024-11-03 the Pacific clock falls back 02:00 PDT → 01:00 PST, so 01:30
        // occurs twice. We pick the earliest instant (PDT, UTC-7 = 08:30 UTC).
        let naive = NaiveDate::from_ymd_opt(2024, 11, 3)
            .unwrap()
            .and_hms_opt(1, 30, 0)
            .unwrap();
        let utc = naive_to_utc_in_tz(naive, Tz::America__Los_Angeles).unwrap();
        assert_eq!(utc, Utc.with_ymd_and_hms(2024, 11, 3, 8, 30, 0).unwrap());
    }

    #[test]
    fn test_naive_to_utc_in_tz_spring_forward_gap_is_none() {
        // On 2024-03-10 the Pacific clock jumps 02:00 → 03:00, so 02:30 never occurs.
        let naive = NaiveDate::from_ymd_opt(2024, 3, 10)
            .unwrap()
            .and_hms_opt(2, 30, 0)
            .unwrap();
        assert!(naive_to_utc_in_tz(naive, Tz::America__Los_Angeles).is_none());
    }
}
