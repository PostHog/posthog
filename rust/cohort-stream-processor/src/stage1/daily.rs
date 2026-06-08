//! Dense daily-bucket array operations, shared by the event path (PR 2.1) and the sweep (PR 2.3).
//!
//! A `performed_event_multiple` leaf stores its window as a dense `[u32; window_days + 1]` count
//! array plus a `window_start_day` anchor. Both the per-event fold ([`super::super::workers::event_path`])
//! and the time-driven eviction ([`super::super::workers::sweep_callback`]) advance that window
//! forward as calendar time passes; this module is the one tested source of truth for the subtle
//! boundary math so the two can never drift.
//!
//! Everything here is pure and clock-free: a caller supplies the target "now" day (the event's own
//! day on the fold path, `day_idx_in_tz(due_before_ms)` on the sweep path), and the window slides to
//! cover it. The only timezone-aware primitive is [`daily_eviction_deadline`], which converts a day
//! index back to its local-midnight instant.

use chrono_tz::Tz;

use crate::stage1::bucket_tz::start_of_day_ms_in_tz;

/// Slide the dense window forward so its "now" day is `target_now_day`, dropping the buckets that
/// fall out of the lower bound and zeroing the vacated tail. A no-op when the window already covers
/// `target_now_day` (i.e. `target_now_day <= window_start_day + window_days`): the window only ever
/// moves forward, never back.
///
/// This is the AHEAD slide the event path performs per matching event
/// ([`mutate_behavioral_daily`](crate::workers::event_path)) **without** the trailing
/// `buckets[last] += 1`; the sweep performs the same slide with no increment to age stale buckets out
/// at a wall-clock deadline. Operates on a `&mut [u32]` because the slide never changes the array
/// length (`buckets.len() == window_days + 1`, the caller's invariant).
pub(crate) fn slide_window_forward(
    buckets: &mut [u32],
    window_start_day: &mut i32,
    window_days: u32,
    target_now_day: i32,
) {
    let len = buckets.len();
    let cur_now_day = *window_start_day + window_days as i32; // = window_start_day + (len − 1)
    if target_now_day <= cur_now_day {
        // The window already reaches `target_now_day`; nothing has aged out.
        return;
    }

    let shift = (target_now_day - cur_now_day) as usize;
    if shift >= len {
        // The whole window slid past: every bucket is now out of range.
        buckets.iter_mut().for_each(|count| *count = 0);
    } else {
        buckets.copy_within(shift.., 0);
        buckets[len - shift..]
            .iter_mut()
            .for_each(|count| *count = 0);
    }
    *window_start_day += shift as i32;
}

/// The day-boundary (epoch ms, team tz) at which the oldest non-zero bucket leaves the window — its
/// eviction deadline. A day-`d` bucket is in-window while `now_day ≤ d + window_days`, so it leaves
/// at the start of day `d + window_days + 1`. An all-zero array never evicts → [`i64::MAX`].
pub(crate) fn daily_eviction_deadline(
    buckets: &[u32],
    window_start_day: i32,
    window_days: u32,
    tz: Tz,
) -> i64 {
    match buckets.iter().position(|&count| count > 0) {
        Some(oldest) => {
            let oldest_day = window_start_day + oldest as i32;
            start_of_day_ms_in_tz(oldest_day + window_days as i32 + 1, tz)
        }
        None => i64::MAX,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::America::New_York;
    use chrono_tz::UTC;

    use crate::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};

    /// Run the slide and return the mutated `(buckets, window_start_day)` so a case table reads as
    /// data, not procedure.
    fn slide(
        mut buckets: Vec<u32>,
        mut window_start_day: i32,
        window_days: u32,
        target_now_day: i32,
    ) -> (Vec<u32>, i32) {
        slide_window_forward(
            &mut buckets,
            &mut window_start_day,
            window_days,
            target_now_day,
        );
        (buckets, window_start_day)
    }

    #[test]
    fn slide_to_the_current_now_day_is_a_noop() {
        // window_days 7 → len 8, window [100 ..= 107]; target == cur_now_day (107) → unchanged.
        let buckets = vec![1, 2, 3, 4, 5, 6, 7, 8];
        let (after, start) = slide(buckets.clone(), 100, 7, 107);
        assert_eq!(after, buckets);
        assert_eq!(start, 100);
    }

    #[test]
    fn slide_to_a_past_now_day_never_moves_backward() {
        // A target before the window's current now-day is ignored (the window only moves forward).
        let buckets = vec![1, 2, 3, 4, 5, 6, 7, 8];
        let (after, start) = slide(buckets.clone(), 100, 7, 105);
        assert_eq!(after, buckets, "no slide for a past target");
        assert_eq!(start, 100);
    }

    #[test]
    fn slide_by_one_drops_the_oldest_bucket_and_zeroes_the_new_tail() {
        // window [100 ..= 107], slide to now-day 108: shift 1, bucket[0] (day 100) falls out, the new
        // last bucket (day 108) is zeroed, window_start advances to 101.
        let (after, start) = slide(vec![9, 2, 3, 4, 5, 6, 7, 8], 100, 7, 108);
        assert_eq!(after, vec![2, 3, 4, 5, 6, 7, 8, 0]);
        assert_eq!(start, 101);
    }

    #[test]
    fn slide_by_several_drops_several_and_zeroes_the_tail() {
        // Slide to now-day 110: shift 3 → days 100,101,102 fall out; the last 3 buckets are vacated.
        let (after, start) = slide(vec![1, 2, 3, 4, 5, 6, 7, 8], 100, 7, 110);
        assert_eq!(after, vec![4, 5, 6, 7, 8, 0, 0, 0]);
        assert_eq!(start, 103);
    }

    #[test]
    fn slide_by_len_minus_one_keeps_only_the_now_day() {
        // shift == len − 1 (7): only the original last bucket survives, in position 0.
        let (after, start) = slide(vec![1, 2, 3, 4, 5, 6, 7, 8], 100, 7, 114);
        assert_eq!(after, vec![8, 0, 0, 0, 0, 0, 0, 0]);
        assert_eq!(start, 107);
    }

    #[test]
    fn slide_by_len_or_more_clears_the_whole_window() {
        // shift >= len → the whole window slid past; every bucket zeroed, window_start jumps forward.
        let (after, start) = slide(vec![1, 2, 3, 4, 5, 6, 7, 8], 100, 7, 115);
        assert_eq!(after, vec![0; 8], "shift == len clears everything");
        assert_eq!(start, 108);

        let (after_far, start_far) = slide(vec![1, 2, 3, 4, 5, 6, 7, 8], 100, 7, 1_000);
        assert_eq!(
            after_far,
            vec![0; 8],
            "a far-future target clears everything"
        );
        // shift = 1000 − (100 + 7) = 893, so window_start advances 100 → 993.
        assert_eq!(start_far, 993, "window_start advances by the shift");
    }

    #[test]
    fn slide_one_day_window_has_two_buckets() {
        // window_days 1 → len 2, window [50 ..= 51]; slide to 52 drops day 50.
        let (after, start) = slide(vec![3, 4], 50, 1, 52);
        assert_eq!(after, vec![4, 0]);
        assert_eq!(start, 51);
    }

    #[test]
    fn deadline_is_the_start_of_the_day_the_oldest_bucket_leaves() {
        // Oldest non-zero is bucket 2 (day 102) of an N=7 window; it leaves at start of 102+7+1 = 110.
        let buckets = [0, 0, 5, 0, 1, 0, 0, 0];
        assert_eq!(
            daily_eviction_deadline(&buckets, 100, 7, UTC),
            start_of_day_ms_in_tz(110, UTC),
        );
    }

    #[test]
    fn deadline_of_an_all_zero_window_never_evicts() {
        assert_eq!(daily_eviction_deadline(&[0, 0, 0], 100, 2, UTC), i64::MAX);
    }

    #[test]
    fn deadline_is_team_tz_local_midnight_not_utc() {
        // The expiry boundary is the oldest bucket's leave-day as local midnight in the team's zone.
        // A negative-offset zone (New York) shifts that instant off the UTC day boundary, so the same
        // day index resolves to a different epoch-ms — the day→instant conversion must be tz-aware.
        let window_days = 7_u32;
        let window_start_day = day_idx_in_tz(
            chrono::DateTime::parse_from_rfc3339("2026-03-01T12:00:00Z")
                .unwrap()
                .timestamp_millis(),
            New_York,
        );
        let mut buckets = vec![0_u32; window_days as usize + 1];
        buckets[0] = 1; // oldest non-zero bucket is the window's lower bound

        // Leaves at start of day window_start_day + 7 + 1, spanning New York's 2026-03-08 DST jump.
        let leave_day = window_start_day + window_days as i32 + 1;
        assert_eq!(
            daily_eviction_deadline(&buckets, window_start_day, window_days, New_York),
            start_of_day_ms_in_tz(leave_day, New_York),
        );
        assert_ne!(
            start_of_day_ms_in_tz(leave_day, New_York),
            start_of_day_ms_in_tz(leave_day, UTC),
            "a negative-offset zone's local midnight differs from UTC midnight",
        );
    }
}
