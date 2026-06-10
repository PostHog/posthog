//! Sparse run-length union for merging two `BehavioralCompressedHistory` states (TDD §4.5 / §4.5.1).
//!
//! Resolves the SESSION.md "compressed-history merge concat (PR 3.1)" residual. No index alignment is
//! needed (unlike the dense daily variant) because RLE stores **absolute** day indices, so the union
//! is a straight by-day sum (TDD §4.5).

use std::collections::BTreeMap;

/// Union two sparse run-length histories by absolute `day_idx`, summing counts for shared days.
///
/// Returns `(merged_entries, merged_window_start_day)`:
/// - `merged_entries` is sorted ascending by day with no zero-count entries (the compressed
///   invariant), counts saturating-summed across the two sides.
/// - `merged_window_start_day = max(old_window_start_day, new_window_start_day)` — the same anchor
///   rule as the daily variant. Entries below it are left in place (the predicate sums all entries;
///   the next sweep slide prunes any now out of window), so no alignment shift is performed.
pub fn union_by_day(
    old_entries: &[(i32, u32)],
    old_window_start_day: i32,
    new_entries: &[(i32, u32)],
    new_window_start_day: i32,
) -> (Vec<(i32, u32)>, i32) {
    let mut by_day: BTreeMap<i32, u32> = BTreeMap::new();
    for &(day, count) in old_entries.iter().chain(new_entries.iter()) {
        let slot = by_day.entry(day).or_insert(0);
        *slot = slot.saturating_add(count);
    }
    let merged = by_day.into_iter().filter(|&(_, count)| count > 0).collect();
    (merged, old_window_start_day.max(new_window_start_day))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shared_days_sum_and_disjoint_days_union_sorted() {
        let (merged, start) = union_by_day(
            &[(100, 2), (200, 1), (300, 5)],
            10,
            &[(150, 3), (200, 4)],
            20,
        );
        assert_eq!(
            merged,
            vec![(100, 2), (150, 3), (200, 5), (300, 5)],
            "day 200 sums to 5; the rest union, sorted ascending",
        );
        assert_eq!(
            start, 20,
            "the merged anchor is the more recent window start"
        );
    }

    #[test]
    fn one_empty_side_returns_the_other() {
        let (merged, start) = union_by_day(&[], 5, &[(100, 1), (200, 2)], 50);
        assert_eq!(merged, vec![(100, 1), (200, 2)]);
        assert_eq!(start, 50);

        let (merged, start) = union_by_day(&[(100, 1)], 50, &[], 5);
        assert_eq!(merged, vec![(100, 1)]);
        assert_eq!(start, 50);
    }

    #[test]
    fn both_empty_is_empty() {
        let (merged, start) = union_by_day(&[], 7, &[], 9);
        assert!(merged.is_empty());
        assert_eq!(start, 9);
    }

    #[test]
    fn counts_saturate_at_u32_max() {
        let (merged, _) = union_by_day(&[(100, u32::MAX)], 0, &[(100, 5)], 0);
        assert_eq!(merged, vec![(100, u32::MAX)], "saturating add never wraps");
    }

    #[test]
    fn entries_below_the_merged_anchor_are_retained_rle_invariant_holds() {
        // The trailing side has a day below the merged anchor; it is kept (the predicate sums all
        // entries) and the result stays sorted and zero-free.
        let (merged, start) = union_by_day(&[(5, 1)], 5, &[(100, 1)], 90);
        assert_eq!(merged, vec![(5, 1), (100, 1)]);
        assert_eq!(start, 90);
        assert!(
            merged.windows(2).all(|w| w[0].0 < w[1].0),
            "entries stay strictly sorted by day",
        );
    }
}
