//! Sparse run-length daily-count operations for `performed_event_multiple` windows over 180 days.
//!
//! Entries are `(day_idx, count)` pairs sorted ascending, no zero-count entries. Windowing semantics
//! mirror [`super::daily`]: slide forward, prune out-of-window days, sum in-window. Clock-free;
//! callers supply the "now" day index.

use chrono_tz::Tz;

use crate::stage1::bucket_tz::{now_day_for_window, window_leave_day_ms, window_start_for_now};

/// Insert or increment `day`'s count (saturating), keeping entries sorted with no zero-count entries.
/// The caller must slide the window before calling; `day` must be within the current window.
pub(crate) fn insert_event(entries: &mut Vec<(i32, u32)>, day: i32) {
    match entries.binary_search_by_key(&day, |&(entry_day, _)| entry_day) {
        Ok(idx) => entries[idx].1 = entries[idx].1.saturating_add(1),
        Err(idx) => entries.insert(idx, (day, 1)),
    }
}

/// Slide the sparse window forward to `target_now_day`, dropping entries below the new lower bound.
/// No-op when the window already covers `target_now_day`; the window only moves forward, never back.
pub(crate) fn slide_window_forward(
    entries: &mut Vec<(i32, u32)>,
    window_start_day: &mut i32,
    window_days: u32,
    target_now_day: i32,
) {
    let cur_now_day = now_day_for_window(*window_start_day, window_days);
    if target_now_day <= cur_now_day {
        return;
    }
    let new_window_start_day = window_start_for_now(target_now_day, window_days);
    let dropped = entries.partition_point(|&(day, _)| day < new_window_start_day);
    entries.drain(..dropped);
    *window_start_day = new_window_start_day;
}

/// Saturating sum of all entries' counts.
pub(crate) fn compressed_sum(entries: &[(i32, u32)]) -> u32 {
    entries
        .iter()
        .map(|&(_, count)| count)
        .fold(0, u32::saturating_add)
}

/// Deadline (epoch ms, team tz) at which the oldest entry leaves the window. A day-`d` entry
/// leaves at the start of day `d + window_days + 1`. Returns [`i64::MAX`] when empty.
pub(crate) fn compressed_eviction_deadline(
    entries: &[(i32, u32)],
    window_days: u32,
    tz: Tz,
) -> i64 {
    match entries.first() {
        Some(&(oldest_day, _)) => window_leave_day_ms(oldest_day, window_days, tz),
        None => i64::MAX,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::America::New_York;
    use chrono_tz::UTC;

    use crate::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};

    fn slide(
        mut entries: Vec<(i32, u32)>,
        mut window_start_day: i32,
        window_days: u32,
        target_now_day: i32,
    ) -> (Vec<(i32, u32)>, i32) {
        slide_window_forward(
            &mut entries,
            &mut window_start_day,
            window_days,
            target_now_day,
        );
        (entries, window_start_day)
    }

    #[test]
    fn insert_into_an_empty_set_creates_a_count_one_entry() {
        let mut entries = Vec::new();
        insert_event(&mut entries, 100);
        assert_eq!(entries, vec![(100, 1)]);
    }

    #[test]
    fn insert_on_an_existing_day_increments_in_place() {
        let mut entries = vec![(100, 3), (105, 1)];
        insert_event(&mut entries, 100);
        assert_eq!(entries, vec![(100, 4), (105, 1)], "no new entry, count + 1");
    }

    #[test]
    fn insert_keeps_entries_sorted_by_day() {
        let mut entries = Vec::new();
        for day in [105, 100, 110, 102] {
            insert_event(&mut entries, day);
        }
        assert_eq!(entries, vec![(100, 1), (102, 1), (105, 1), (110, 1)]);
    }

    #[test]
    fn insert_count_saturates_at_u32_max() {
        let mut entries = vec![(100, u32::MAX)];
        insert_event(&mut entries, 100);
        assert_eq!(entries, vec![(100, u32::MAX)], "saturating, never wraps");
    }

    #[test]
    fn slide_to_the_current_now_day_is_a_noop() {
        // window_days 365, window [100 ..= 465]; target == cur_now_day (465) → unchanged.
        let entries = vec![(100, 9), (300, 2), (465, 1)];
        let (after, start) = slide(entries.clone(), 100, 365, 465);
        assert_eq!(after, entries);
        assert_eq!(start, 100);
    }

    #[test]
    fn slide_to_a_past_now_day_never_moves_backward() {
        let entries = vec![(100, 9), (300, 2)];
        let (after, start) = slide(entries.clone(), 100, 365, 400);
        assert_eq!(after, entries, "no slide for a past target");
        assert_eq!(start, 100);
    }

    #[test]
    fn slide_drops_only_the_entries_below_the_new_lower_bound() {
        // window [100 ..= 465], slide to now-day 466: new lower bound 101, so day-100 drops; the rest
        // (all ≥ 101) survive, and window_start advances to 101.
        let (after, start) = slide(vec![(100, 9), (101, 2), (300, 3), (465, 1)], 100, 365, 466);
        assert_eq!(after, vec![(101, 2), (300, 3), (465, 1)]);
        assert_eq!(start, 101);
    }

    #[test]
    fn slide_by_several_days_drops_every_entry_now_out_of_window() {
        // Slide to now-day 470: new lower bound 105 → days 100..=104 fall out, day 105+ survive.
        let (after, start) = slide(
            vec![(100, 1), (103, 2), (105, 3), (460, 4), (470, 5)],
            100,
            365,
            470,
        );
        assert_eq!(after, vec![(105, 3), (460, 4), (470, 5)]);
        assert_eq!(start, 105);
    }

    #[test]
    fn slide_far_past_every_entry_clears_the_window() {
        // A far-future now-day (1000) sets the lower bound to 635; every stored day predates it.
        let (after, start) = slide(vec![(100, 1), (300, 2), (465, 3)], 100, 365, 1_000);
        assert!(after.is_empty(), "the whole window slid past");
        // window_start advances to target − window_days = 1000 − 365 = 635.
        assert_eq!(start, 635, "window_start advances to target − window_days");
    }

    #[test]
    fn slide_on_an_empty_set_only_advances_the_anchor() {
        // A drained window still advances its anchor so the next event classifies AHEAD/WITHIN/BEHIND
        // against the right lower bound.
        let (after, start) = slide(Vec::new(), 100, 365, 500);
        assert!(after.is_empty());
        assert_eq!(start, 135, "500 − 365");
    }

    #[test]
    fn sum_adds_the_retained_counts() {
        assert_eq!(compressed_sum(&[(100, 3), (200, 4), (300, 1)]), 8);
        assert_eq!(compressed_sum(&[]), 0);
    }

    #[test]
    fn sum_saturates_at_u32_max() {
        assert_eq!(
            compressed_sum(&[(100, u32::MAX), (200, 5)]),
            u32::MAX,
            "saturating, never wraps",
        );
    }

    #[test]
    fn deadline_is_the_start_of_the_day_the_oldest_entry_leaves() {
        // Oldest entry is day 102 of a 365-day window; it leaves at start of 102+365+1 = 468.
        let entries = [(102, 5), (200, 1)];
        assert_eq!(
            compressed_eviction_deadline(&entries, 365, UTC),
            start_of_day_ms_in_tz(468, UTC),
        );
    }

    #[test]
    fn deadline_of_an_empty_set_never_evicts() {
        assert_eq!(compressed_eviction_deadline(&[], 365, UTC), i64::MAX);
    }

    #[test]
    fn deadline_saturates_for_an_astronomical_window_instead_of_panicking() {
        // `window_days` is unbounded `u32` user input; a naïve `oldest_day + window_days as i32 + 1`
        // either panics in debug (when the sum exceeds i32::MAX — the case below) or at u32::MAX
        // silently wraps to a near-epoch instant (flapping entered/left). Arithmetic must be total:
        // an effectively infinite window never evicts → i64::MAX.
        let entries = [(1_000, 1_u32)];
        // `1_000 + 2_147_483_000 + 1` overflows i32 without saturation.
        assert_eq!(
            compressed_eviction_deadline(&entries, 2_147_483_000, UTC),
            i64::MAX,
        );
        assert_eq!(
            compressed_eviction_deadline(&entries, u32::MAX, UTC),
            i64::MAX,
            "u32::MAX (which casts to -1) must not wrap to a near-epoch deadline",
        );
    }

    #[test]
    fn slide_with_an_astronomical_window_never_evicts_and_does_not_panic() {
        // `window_start_day + window_days` (cur "now") overflows i32 for a large anchor + huge
        // window; a naïve `as i32` add panics in debug. With saturation the window already covers
        // any realistic target, so the slide is a no-op (nothing drops, anchor unchanged).
        let entries = vec![(2_000_000_000, 9), (2_000_000_100, 2)];
        // `2_000_000_000 + 200_000_000` overflows i32 → unfixed code panics in `slide_window_forward`.
        let (after, start) = slide(entries.clone(), 2_000_000_000, 200_000_000, i32::MAX);
        assert_eq!(
            after, entries,
            "an essentially infinite window never slides out"
        );
        assert_eq!(start, 2_000_000_000, "window anchor unchanged");
    }

    #[test]
    fn deadline_is_team_tz_local_midnight_not_utc() {
        // The expiry boundary is the oldest entry's leave-day as local midnight in the team's zone. A
        // negative-offset zone (New York) shifts that instant off the UTC day boundary, so the same
        // day index resolves to a different epoch-ms — the day→instant conversion must be tz-aware.
        let window_days = 365_u32;
        let oldest_day = day_idx_in_tz(
            chrono::DateTime::parse_from_rfc3339("2026-03-01T12:00:00Z")
                .unwrap()
                .timestamp_millis(),
            New_York,
        );
        let entries = [(oldest_day, 1_u32)];

        let leave_day = oldest_day + window_days as i32 + 1;
        assert_eq!(
            compressed_eviction_deadline(&entries, window_days, New_York),
            start_of_day_ms_in_tz(leave_day, New_York),
        );
        assert_ne!(
            start_of_day_ms_in_tz(leave_day, New_York),
            start_of_day_ms_in_tz(leave_day, UTC),
            "a negative-offset zone's local midnight differs from UTC midnight",
        );
    }
}
