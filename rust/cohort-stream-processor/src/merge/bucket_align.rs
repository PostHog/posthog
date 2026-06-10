//! Dense daily-bucket alignment for merging two `BehavioralDailyBuckets` states (TDD §4.5 / §4.5.1).
//!
//! Pure array math: both sides belong to the *same* leaf, so they share `window_days` (hence array
//! length). The S6b alignment rule picks the more recent window start and sums element-wise.

use crate::stage1::daily::slide_window_forward;

/// Align two dense bucket arrays to the more recent window and sum them element-wise.
///
/// Returns `(merged_buckets, merged_window_start_day)` where `merged_window_start_day =
/// max(old_window_start_day, new_window_start_day)` — the S6b rule. The merged window is
/// `[target_start, target_start + window_days]`, so each side is slid forward to that window via the
/// same [`slide_window_forward`] the event path uses (dropping its buckets below `target_start`,
/// which the next sweep would evict on the trailing side anyway), then the aligned arrays are summed
/// (saturating). Both inputs must have length `window_days + 1`; a length mismatch (a desync the
/// caller guards) truncates to the shorter side rather than panicking.
pub fn align_and_sum(
    old_buckets: &[u32],
    old_window_start_day: i32,
    new_buckets: &[u32],
    new_window_start_day: i32,
    window_days: u32,
) -> (Vec<u32>, i32) {
    let target_start = old_window_start_day.max(new_window_start_day);
    // Sliding each side to this "now" makes its window start land exactly on `target_start`.
    let target_now = target_start + window_days as i32;

    let mut old_aligned = old_buckets.to_vec();
    let mut old_start = old_window_start_day;
    slide_window_forward(&mut old_aligned, &mut old_start, window_days, target_now);

    let mut new_aligned = new_buckets.to_vec();
    let mut new_start = new_window_start_day;
    slide_window_forward(&mut new_aligned, &mut new_start, window_days, target_now);

    let merged = old_aligned
        .iter()
        .zip(new_aligned.iter())
        .map(|(&old, &new)| old.saturating_add(new))
        .collect();
    (merged, target_start)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tdd_4_5_1_worked_example() {
        // The pinned regression from TDD §4.5.1 (acceptance #9): window_days 6 (7 buckets), the two
        // window starts differing by 1.
        let (merged, start) = align_and_sum(
            &[2, 0, 1, 3, 0, 1, 5],
            19_500,
            &[0, 1, 2, 0, 1, 0, 4],
            19_501,
            6,
        );
        assert_eq!(merged, vec![0, 2, 5, 0, 2, 5, 4]);
        assert_eq!(
            start, 19_501,
            "the merged window anchors on the more recent start"
        );
    }

    #[test]
    fn identical_windows_sum_without_shifting() {
        let (merged, start) = align_and_sum(&[1, 2, 3], 100, &[4, 5, 6], 100, 2);
        assert_eq!(merged, vec![5, 7, 9]);
        assert_eq!(start, 100);
    }

    #[test]
    fn old_window_ahead_aligns_new_forward() {
        // new is one day behind: its day-100 bucket drops, the rest shift, a zero is appended.
        let (merged, start) = align_and_sum(&[10, 20, 30], 101, &[1, 2, 3], 100, 2);
        // new slides to now 103: shift 1 → [2, 3, 0]; old (already at 101) unchanged → [10, 20, 30].
        assert_eq!(merged, vec![12, 23, 30]);
        assert_eq!(start, 101);
    }

    #[test]
    fn disjoint_windows_one_side_fully_slides_out() {
        // new is far behind; sliding it to old's window drains every bucket.
        let (merged, start) = align_and_sum(&[1, 1, 1, 1], 1_000, &[9, 9, 9, 9], 100, 3);
        assert_eq!(
            merged,
            vec![1, 1, 1, 1],
            "new's stale buckets all slid past"
        );
        assert_eq!(start, 1_000);
    }

    #[test]
    fn counts_saturate_at_u32_max() {
        let (merged, _) = align_and_sum(&[u32::MAX, 0], 50, &[5, 0], 50, 1);
        assert_eq!(merged, vec![u32::MAX, 0], "saturating add never wraps");
    }
}
