//! Sparse run-length daily-count operations for windows over 180 days, shared by the event path and
//! the sweep — the compressed analog of [`super::daily`].
//!
//! A `performed_event_multiple` leaf with a window over 180 days stores its counts as sparse
//! `(day_idx, count)` entries (sorted ascending, no zero-count entries) plus a `window_start_day`
//! anchor, instead of a dense `[u32; window_days + 1]` array. The windowing semantics are otherwise
//! identical to daily — slide forward, prune out-of-window days, sum in-window, deadline = the oldest
//! in-window day's leave boundary — so this module mirrors [`super::daily`] arm for arm, only over a
//! sparse vector. Both the per-event fold ([`super::super::workers::event_path`]) and the
//! time-driven eviction ([`super::super::workers::sweep_callback`]) advance the window through it, so
//! it is the one tested source of truth for the boundary math.
//!
//! Everything here is pure and clock-free: a caller supplies the target "now" day (the event's own
//! day on the fold path, `day_idx_in_tz(due_before_ms)` on the sweep path), and the window slides to
//! cover it. The only timezone-aware primitive is [`compressed_eviction_deadline`], which converts a
//! day index back to its local-midnight instant.

use chrono_tz::Tz;

use crate::stage1::bucket_tz::start_of_day_ms_in_tz;

/// Count one matching event on `day` into the sparse entries: increment the existing day's count
/// (saturating) or insert a fresh `(day, 1)` at its sorted position. Keeps `entries` sorted ascending
/// by day with no zero-count entries (the storage invariant), the sparse analog of daily's
/// `buckets[idx] += 1`. The caller positions `day` inside the window first (sliding on the AHEAD
/// path); a `day` already out of the window must not reach here.
pub(crate) fn insert_event(entries: &mut Vec<(i32, u32)>, day: i32) {
    match entries.binary_search_by_key(&day, |&(entry_day, _)| entry_day) {
        Ok(idx) => entries[idx].1 = entries[idx].1.saturating_add(1),
        Err(idx) => entries.insert(idx, (day, 1)),
    }
}

/// Slide the sparse window forward so its "now" day is `target_now_day`, dropping the entries that
/// fall below the new lower bound. A no-op when the window already covers `target_now_day` (i.e.
/// `target_now_day <= window_start_day + window_days`): the window only ever moves forward, never
/// back.
///
/// This is the AHEAD slide the event path performs per matching event
/// ([`mutate_behavioral_compressed`](crate::workers::event_path)) **before** counting the event in;
/// the sweep performs the same slide with no insert to age stale days out at a wall-clock deadline.
/// The sparse analog of daily's dense `copy_within` + tail-zero: since entries are sorted, the
/// out-of-window days are a contiguous prefix, removed in one drain.
pub(crate) fn slide_window_forward(
    entries: &mut Vec<(i32, u32)>,
    window_start_day: &mut i32,
    window_days: u32,
    target_now_day: i32,
) {
    let cur_now_day = *window_start_day + window_days as i32;
    if target_now_day <= cur_now_day {
        // The window already reaches `target_now_day`; nothing has aged out.
        return;
    }
    // The new inclusive lower bound after sliding the now-day to `target_now_day`.
    let new_window_start_day = target_now_day - window_days as i32;
    let dropped = entries.partition_point(|&(day, _)| day < new_window_start_day);
    entries.drain(..dropped);
    *window_start_day = new_window_start_day;
}

/// The window's matching-event count: the saturating sum of the retained entries' counts. Clock-free
/// — every retained entry is in-window by the slide invariant, so this is the analog of summing the
/// dense bucket array.
pub(crate) fn compressed_sum(entries: &[(i32, u32)]) -> u32 {
    entries
        .iter()
        .map(|&(_, count)| count)
        .fold(0, u32::saturating_add)
}

/// The day-boundary (epoch ms, team tz) at which the oldest entry leaves the window — its eviction
/// deadline. A day-`d` entry is in-window while `now_day ≤ d + window_days`, so it leaves at the start
/// of day `d + window_days + 1`. Entries are sorted, so `entries[0]` is the oldest; an empty set never
/// evicts → [`i64::MAX`]. Unlike [`daily_eviction_deadline`](super::daily::daily_eviction_deadline)
/// no `window_start_day` is needed — each entry already carries its absolute day.
pub(crate) fn compressed_eviction_deadline(
    entries: &[(i32, u32)],
    window_days: u32,
    tz: Tz,
) -> i64 {
    match entries.first() {
        Some(&(oldest_day, _)) => start_of_day_ms_in_tz(oldest_day + window_days as i32 + 1, tz),
        None => i64::MAX,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::America::New_York;
    use chrono_tz::UTC;

    use crate::stage1::bucket_tz::{day_idx_in_tz, start_of_day_ms_in_tz};

    /// Run the slide and return the mutated `(entries, window_start_day)` so a case table reads as
    /// data, not procedure.
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
        // Insert out of order; the binary-search insert keeps the vector ascending.
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
        // A target before the window's current now-day is ignored (the window only moves forward).
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
