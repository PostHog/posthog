/// FoldMap: Folding projection layer (Wrap rows → Display rows).
///
/// This module manages code folding by:
/// - Filtering out wrap rows that belong to folded regions
/// - Maintaining bidirectional mapping: wrap_row ↔ display_row
/// - Handling fold state changes and rebuilding the projection
use std::ops::Range;

use super::folding::FoldRange;
use super::wrap_map::WrapMap;

/// A run of wrap rows hidden by folding.
#[derive(Debug, Clone, PartialEq, Eq)]
struct HiddenRows {
    wrap_rows: Range<usize>,
    /// How many wrap rows the runs before this one hide.
    hidden_before: usize,
}

impl HiddenRows {
    /// The display row of the first visible wrap row after this run.
    fn display_start(&self) -> usize {
        self.wrap_rows.start - self.hidden_before
    }
}

/// FoldMap projects wrap rows to display rows by hiding folded regions.
pub(super) struct FoldMap {
    /// The wrap rows hidden by folding: sorted, disjoint and non-adjacent.
    ///
    /// The projection is kept as these runs rather than a table per wrap row,
    /// so rebuilding it after an edit costs the number of folds, not the
    /// length of the document, and both directions are a binary search.
    hidden: Vec<HiddenRows>,

    /// How many wrap rows `hidden` hides in total.
    total_hidden: usize,

    /// The wrap row count the projection was last built for.
    projected_wrap_row_count: usize,

    /// Candidate fold ranges (from tree-sitter/LSP)
    /// Sorted by start_line, unique start_line
    candidates: Vec<FoldRange>,

    /// Currently folded ranges
    /// Subset of candidates, sorted by start_line
    folded: Vec<FoldRange>,

    /// Flag indicating if the fold projection needs rebuilding
    /// Used for lazy evaluation to avoid expensive rebuilds on every text change
    needs_rebuild: bool,

    /// Cached wrap_row_count from last rebuild
    /// Used to detect if WrapMap changed and rebuild is needed
    cached_wrap_row_count: usize,
}

impl FoldMap {
    pub(super) fn new() -> Self {
        Self {
            hidden: Vec::new(),
            total_hidden: 0,
            projected_wrap_row_count: 0,
            candidates: Vec::new(),
            folded: Vec::new(),
            needs_rebuild: true,
            cached_wrap_row_count: 0,
        }
    }

    /// Update cached wrap_row_count without full rebuild.
    /// Used when no folds are active (identity mapping assumed).
    pub(super) fn mark_dirty_with_wrap_count(&mut self, wrap_row_count: usize) {
        self.needs_rebuild = true;
        self.cached_wrap_row_count = wrap_row_count;
    }

    /// Get total number of visible display rows
    pub(super) fn display_row_count(&self) -> usize {
        if self.folded.is_empty() {
            return self.cached_wrap_row_count;
        }
        self.projected_wrap_row_count - self.total_hidden
    }

    /// How many wrap rows the runs before `index` hide.
    fn hidden_before(&self, index: usize) -> usize {
        self.hidden
            .get(index)
            .map_or(self.total_hidden, |run| run.hidden_before)
    }

    /// Convert wrap_row to display_row
    /// Returns None if the wrap_row is hidden by folding
    pub(super) fn wrap_row_to_display_row(&self, wrap_row: usize) -> Option<usize> {
        if self.folded.is_empty() {
            return if wrap_row < self.cached_wrap_row_count {
                Some(wrap_row)
            } else {
                None
            };
        }
        if wrap_row >= self.projected_wrap_row_count {
            return None;
        }
        let index = self
            .hidden
            .partition_point(|run| run.wrap_rows.end <= wrap_row);
        if self
            .hidden
            .get(index)
            .is_some_and(|run| run.wrap_rows.start <= wrap_row)
        {
            return None;
        }
        Some(wrap_row - self.hidden_before(index))
    }

    /// Convert display_row to wrap_row
    pub(super) fn display_row_to_wrap_row(&self, display_row: usize) -> Option<usize> {
        if self.folded.is_empty() {
            return if display_row < self.cached_wrap_row_count {
                Some(display_row)
            } else {
                None
            };
        }
        if display_row >= self.display_row_count() {
            return None;
        }
        let index = self
            .hidden
            .partition_point(|run| run.display_start() <= display_row);
        Some(display_row + self.hidden_before(index))
    }

    /// Find the nearest visible display_row for a given wrap_row
    pub(super) fn nearest_visible_display_row(&self, wrap_row: usize) -> usize {
        if self.folded.is_empty() {
            return wrap_row.min(self.cached_wrap_row_count.saturating_sub(1));
        }

        if let Some(dr) = self.wrap_row_to_display_row(wrap_row) {
            return dr;
        }

        // A hidden row maps to the last visible row before it.
        let visible_before = if wrap_row >= self.projected_wrap_row_count {
            self.display_row_count()
        } else {
            let index = self
                .hidden
                .partition_point(|run| run.wrap_rows.end <= wrap_row);
            self.hidden
                .get(index)
                .map_or(self.display_row_count(), HiddenRows::display_start)
        };
        visible_before.saturating_sub(1)
    }

    /// Set fold candidates (from tree-sitter/LSP), full replacement.
    pub(super) fn set_candidates(&mut self, mut candidates: Vec<FoldRange>) {
        // Sort and deduplicate by start_line
        candidates.sort_by_key(|r| r.start_line);
        candidates.dedup_by_key(|r| r.start_line);
        self.candidates = candidates;

        // Remove any folded ranges that are no longer in candidates
        self.folded.retain(|fold| {
            self.candidates
                .iter()
                .any(|c| c.start_line == fold.start_line)
        });
    }

    /// Merge new candidates extracted from an edited region into existing candidates.
    ///
    /// Replaces candidates within [edit_start_line, edit_end_line] with `new_candidates`,
    /// keeping candidates outside the edit range intact.
    pub(super) fn merge_candidates_for_edit(
        &mut self,
        edit_start_line: usize,
        edit_end_line: usize,
        new_candidates: Vec<FoldRange>,
    ) {
        // Remove old candidates within the edit range (already done by adjust_folds_for_edit)
        // But do it again in case adjust wasn't called or range differs
        self.candidates
            .retain(|c| c.start_line < edit_start_line || c.start_line > edit_end_line);

        // Add new candidates
        self.candidates.extend(new_candidates);
        self.candidates.sort_by_key(|r| r.start_line);
        self.candidates.dedup_by_key(|r| r.start_line);
    }

    /// Set a fold at the given start_line (must be in candidates)
    pub(super) fn set_folded(&mut self, start_line: usize, folded: bool) {
        if folded {
            // Find the candidate range for this start_line
            if let Some(candidate) = self.candidates.iter().find(|c| c.start_line == start_line) {
                // Add to folded if not already present
                if !self.folded.iter().any(|f| f.start_line == start_line) {
                    self.folded.push(*candidate);
                    self.folded.sort_by_key(|r| r.start_line);
                    self.needs_rebuild = true;
                }
            }
        } else {
            // Remove from folded
            self.folded.retain(|f| f.start_line != start_line);
            self.needs_rebuild = true;
        }
    }

    /// Toggle fold at the given start_line
    pub(super) fn toggle_fold(&mut self, start_line: usize) {
        let is_folded = self.is_folded_at(start_line);
        self.set_folded(start_line, !is_folded);
    }

    /// Check if a line is currently folded
    pub(super) fn is_folded_at(&self, start_line: usize) -> bool {
        self.folded.iter().any(|f| f.start_line == start_line)
    }

    /// Check if a line is a fold candidate
    pub(super) fn is_fold_candidate(&self, start_line: usize) -> bool {
        self.candidates.iter().any(|c| c.start_line == start_line)
    }

    /// Get all fold candidates
    #[inline]
    pub(super) fn fold_candidates(&self) -> &[FoldRange] {
        &self.candidates
    }

    /// Get all currently folded ranges
    #[inline]
    pub(super) fn folded_ranges(&self) -> &[FoldRange] {
        &self.folded
    }

    /// Clear all folds
    #[inline]
    pub(super) fn clear_folds(&mut self) {
        self.folded.clear();
    }

    /// Adjust folds and candidates after a text edit.
    ///
    /// - Folds/candidates overlapping the edited line range are removed
    /// - Folds/candidates after the edit are shifted by line_delta
    ///
    /// This avoids expensive full tree traversal on every keystroke.
    pub(super) fn adjust_folds_for_edit(
        &mut self,
        edit_start_line: usize,
        edit_end_line: usize,
        line_delta: isize,
    ) {
        // Adjust folded ranges
        if !self.folded.is_empty() {
            self.folded.retain(|fold| {
                !(fold.start_line <= edit_end_line && fold.end_line >= edit_start_line)
            });

            if line_delta != 0 {
                for fold in &mut self.folded {
                    if fold.start_line > edit_end_line {
                        fold.start_line = (fold.start_line as isize + line_delta).max(0) as usize;
                        fold.end_line = (fold.end_line as isize + line_delta).max(0) as usize;
                    }
                }
            }
        }

        // Adjust candidates the same way
        if !self.candidates.is_empty() {
            self.candidates
                .retain(|c| !(c.start_line <= edit_end_line && c.end_line >= edit_start_line));

            if line_delta != 0 {
                for c in &mut self.candidates {
                    if c.start_line > edit_end_line {
                        c.start_line = (c.start_line as isize + line_delta).max(0) as usize;
                        c.end_line = (c.end_line as isize + line_delta).max(0) as usize;
                    }
                }
            }
        }

        self.needs_rebuild = true;
    }

    /// Rebuild the fold mapping after wrap_map or fold state changes
    ///
    /// This is the core algorithm that projects wrap rows to display rows.
    pub(super) fn rebuild(&mut self, wrap_map: &WrapMap) {
        let wrap_row_count = wrap_map.wrap_row_count();

        // Performance optimization: skip rebuild if nothing changed
        if !self.needs_rebuild && wrap_row_count == self.cached_wrap_row_count {
            return;
        }

        self.cached_wrap_row_count = wrap_row_count;

        if self.folded.is_empty() {
            // Fast path: no folds, all wrap rows are visible
            self.set_hidden_rows(wrap_row_count, Vec::new());
            self.needs_rebuild = false;
            return;
        }

        // Build set of hidden wrap_row ranges from folded buffer lines
        let mut hidden_ranges = Vec::new();
        for fold in &self.folded {
            // Hide wrap rows from (start_line + 1) to (end_line - 1) (inclusive)
            // Both the first line and last line of the fold remain visible
            let hide_start_line = fold.start_line + 1;
            let hide_end_line = fold.end_line.saturating_sub(1);

            if hide_start_line > hide_end_line {
                continue; // No middle lines to hide (0 or 1 lines between start and end)
            }

            // Get wrap_row ranges for the hidden buffer lines
            let start_wrap_row = wrap_map.buffer_line_to_first_wrap_row(hide_start_line);
            let end_wrap_row = if hide_end_line + 1 < wrap_map.buffer_line_count() {
                wrap_map.buffer_line_to_first_wrap_row(hide_end_line + 1)
            } else {
                wrap_row_count
            };

            if start_wrap_row < end_wrap_row {
                hidden_ranges.push(start_wrap_row..end_wrap_row);
            }
        }

        self.set_hidden_rows(wrap_row_count, hidden_ranges);
        self.needs_rebuild = false;
    }

    /// Install the projection for `wrap_row_count` wrap rows with
    /// `hidden_ranges` hidden, merging overlapping and adjacent ranges.
    fn set_hidden_rows(&mut self, wrap_row_count: usize, mut hidden_ranges: Vec<Range<usize>>) {
        hidden_ranges.sort_by_key(|range| range.start);

        self.hidden.clear();
        self.total_hidden = 0;
        self.projected_wrap_row_count = wrap_row_count;
        for range in hidden_ranges {
            let range = range.start..range.end.min(wrap_row_count);
            if range.is_empty() {
                continue;
            }
            if let Some(last) = self.hidden.last_mut()
                && range.start <= last.wrap_rows.end
            {
                // Overlapping or adjacent, merge
                if range.end > last.wrap_rows.end {
                    self.total_hidden += range.end - last.wrap_rows.end;
                    last.wrap_rows.end = range.end;
                }
                continue;
            }
            self.total_hidden += range.len();
            self.hidden.push(HiddenRows {
                hidden_before: self.total_hidden - range.len(),
                wrap_rows: range,
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The per-row tables the projection used to be stored as: display row to
    /// wrap row, and wrap row to display row.
    fn dense_projection(
        wrap_row_count: usize,
        hidden: &[Range<usize>],
    ) -> (Vec<usize>, Vec<Option<usize>>) {
        let mut visible = Vec::new();
        let mut display_rows = vec![None; wrap_row_count];
        for (wrap_row, display_row) in display_rows.iter_mut().enumerate() {
            if !hidden.iter().any(|range| range.contains(&wrap_row)) {
                *display_row = Some(visible.len());
                visible.push(wrap_row);
            }
        }
        (visible, display_rows)
    }

    #[test]
    fn hidden_runs_match_the_dense_projection() {
        let wrap_row_count = 10;
        let cases: &[&[Range<usize>]] = &[
            &[],
            &[0..3],
            &[2..5],
            &[7..10],
            &[2..4, 4..6],
            &[1..5, 3..8],
            &[6..9, 1..3],
            &[0..2, 3..4, 8..20],
            &[0..10],
        ];
        for &hidden in cases {
            let mut fold_map = FoldMap::new();
            fold_map.folded.push(FoldRange::new(0, 1));
            fold_map.set_hidden_rows(wrap_row_count, hidden.to_vec());
            let (visible, display_rows) = dense_projection(wrap_row_count, hidden);

            assert_eq!(fold_map.display_row_count(), visible.len(), "{hidden:?}");
            for wrap_row in 0..wrap_row_count + 2 {
                let display_row = display_rows.get(wrap_row).copied().flatten();
                assert_eq!(
                    fold_map.wrap_row_to_display_row(wrap_row),
                    display_row,
                    "{hidden:?}, wrap row {wrap_row}"
                );
                let nearest = match visible.binary_search(&wrap_row) {
                    Ok(index) => index,
                    Err(index) => index.saturating_sub(1),
                };
                assert_eq!(
                    fold_map.nearest_visible_display_row(wrap_row),
                    nearest,
                    "{hidden:?}, wrap row {wrap_row}"
                );
            }
            for display_row in 0..wrap_row_count + 2 {
                assert_eq!(
                    fold_map.display_row_to_wrap_row(display_row),
                    visible.get(display_row).copied(),
                    "{hidden:?}, display row {display_row}"
                );
            }
        }
    }
}
