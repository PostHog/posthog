use std::ops::{Range, RangeBounds};

/// A selection in the text, represented by start and end byte indices.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Default)]
pub struct Selection {
    pub start: usize,
    pub end: usize,
}

impl Selection {
    pub fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }

    pub fn len(&self) -> usize {
        self.end.saturating_sub(self.start)
    }

    pub fn is_empty(&self) -> bool {
        self.start == self.end
    }

    /// Clears the selection, setting start and end to 0.
    pub fn clear(&mut self) {
        self.start = 0;
        self.end = 0;
    }

    /// Checks if the given offset is within the selection range.
    pub fn contains(&self, offset: usize) -> bool {
        offset >= self.start && offset < self.end
    }
}

impl From<Range<usize>> for Selection {
    fn from(value: Range<usize>) -> Self {
        Self::new(value.start, value.end)
    }
}
impl From<Selection> for Range<usize> {
    fn from(value: Selection) -> Self {
        value.start..value.end
    }
}
impl RangeBounds<usize> for Selection {
    fn start_bound(&self) -> std::ops::Bound<&usize> {
        std::ops::Bound::Included(&self.start)
    }

    fn end_bound(&self) -> std::ops::Bound<&usize> {
        std::ops::Bound::Excluded(&self.end)
    }
}

use gpui::Pixels;

use super::selection::CursorId;

#[derive(Debug, Copy, Clone, PartialEq)]
pub(super) struct CursorSelection {
    pub(super) id: CursorId,
    pub(super) start: usize,
    pub(super) end: usize,
    pub(super) reversed: bool,
    pub(super) column_anchor: Option<(Pixels, usize)>,
}

impl CursorSelection {
    pub(super) fn new(id: CursorId, start: usize, end: usize) -> Self {
        Self {
            id,
            start,
            end,
            reversed: false,
            column_anchor: None,
        }
    }

    pub(super) fn len(&self) -> usize {
        self.end.saturating_sub(self.start)
    }

    pub(super) fn is_empty(&self) -> bool {
        self.start == self.end
    }

    pub(super) fn clear(&mut self) {
        self.start = 0;
        self.end = 0;
    }

    pub(super) fn contains(&self, offset: usize) -> bool {
        offset >= self.start && offset < self.end
    }

    pub(super) fn cursor_offset(&self) -> usize {
        if self.reversed { self.start } else { self.end }
    }

    pub(super) fn place_at(&mut self, offset: usize, column_anchor: Option<(Pixels, usize)>) {
        self.start = offset;
        self.end = offset;
        self.reversed = false;
        self.column_anchor = column_anchor;
    }

    pub(super) fn is_collapsed(&self) -> bool {
        self.is_empty()
    }
}

impl From<Range<usize>> for CursorSelection {
    fn from(value: Range<usize>) -> Self {
        Self::new(CursorId::default(), value.start, value.end)
    }
}

impl From<CursorSelection> for Range<usize> {
    fn from(value: CursorSelection) -> Self {
        value.start..value.end
    }
}

impl RangeBounds<usize> for CursorSelection {
    fn start_bound(&self) -> std::ops::Bound<&usize> {
        std::ops::Bound::Included(&self.start)
    }

    fn end_bound(&self) -> std::ops::Bound<&usize> {
        std::ops::Bound::Excluded(&self.end)
    }
}

pub(super) struct Selections {
    selections: Vec<CursorSelection>,
    next_id: usize,
}

impl Selections {
    pub(super) fn new() -> Self {
        Self {
            selections: vec![CursorSelection::new(CursorId::new(0), 0, 0)],
            next_id: 1,
        }
    }

    /// Returns the active selection.
    pub(super) fn active(&self) -> &CursorSelection {
        self.selections
            .first()
            .expect("Selections always has at least one selection")
    }

    /// Returns a mutable reference to the active selection.
    pub(super) fn active_mut(&mut self) -> &mut CursorSelection {
        self.selections
            .first_mut()
            .expect("Selections always has at least one selection")
    }

    pub(super) fn iter(&self) -> impl Iterator<Item = &CursorSelection> {
        self.selections.iter()
    }

    /// Returns the number of selections (always `>= 1`).
    pub(super) fn len(&self) -> usize {
        self.selections.len()
    }

    /// Returns true when there is exactly one selection.
    pub(super) fn is_single(&self) -> bool {
        self.selections.len() == 1
    }

    /// Generates a new unique cursor id.
    pub(super) fn generate_id(&mut self) -> CursorId {
        let id = CursorId::new(self.next_id);
        self.next_id += 1;
        id
    }

    /// Adds an additional selection.
    pub(super) fn add(&mut self, selection: CursorSelection) {
        self.selections.push(selection);
    }

    /// Replaces all selections. Ignores an empty vec to keep the
    /// "always at least one selection" invariant.
    pub(super) fn replace_all(&mut self, selections: Vec<CursorSelection>) {
        if !selections.is_empty() {
            self.selections = selections;
        }
    }

    /// Removes every selection except the active one (index 0).
    pub(super) fn remove_all_but_active(&mut self) {
        self.selections.truncate(1);
    }

    /// Merges overlapping selections.
    ///
    /// Selections are sorted by start and folded together when they overlap.
    /// The active selection is preserved, propagated onto
    /// the merged result if it was absorbed, and re-fronted afterwards.
    pub(super) fn merge_overlapping(&mut self) {
        if self.selections.len() <= 1 {
            return;
        }

        let active_id = self.active().id;

        self.selections.sort_by_key(|s| s.start);

        let mut merged: Vec<CursorSelection> = Vec::with_capacity(self.selections.len());
        for selection in &self.selections {
            if let Some(last) = merged.last_mut() {
                if selection.start <= last.end {
                    // Overlapping or adjacent, extend the last one.
                    let did_merge = selection.start != last.start || selection.end != last.end;
                    last.end = last.end.max(selection.end);
                    if selection.id == active_id {
                        last.id = active_id;
                        last.reversed = selection.reversed;
                    }
                    // Reset the column anchor on a real merge.
                    if did_merge {
                        last.column_anchor = None;
                    }
                    continue;
                }
            }
            merged.push(*selection);
        }

        // Re-front the active selection so it stays at index 0.
        if let Some(pos) = merged.iter().position(|s| s.id == active_id) {
            merged.swap(0, pos);
        }

        self.selections = merged;
    }
}

impl Default for Selections {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::Position;
    use gpui::px;

    #[test]
    fn selection_keeps_its_public_range_api() {
        fn assert_eq<T: Eq>() {}

        assert_eq::<Selection>();
        let selection = Selection::new(2, 5);
        assert_eq!(selection, Selection { start: 2, end: 5 });
        assert_eq!(Range::<usize>::from(selection), 2..5);
    }

    #[test]
    fn test_line_column_from_to() {
        assert_eq!(
            Position::new(1, 2),
            Position {
                line: 1,
                character: 2
            }
        );
    }

    #[test]
    fn test_cursor_offset_reversed() {
        let mut sel = CursorSelection::new(CursorId::new(0), 5, 10);
        assert_eq!(sel.cursor_offset(), 10);
        sel.reversed = true;
        assert_eq!(sel.cursor_offset(), 5);
    }

    #[test]
    fn test_place_at() {
        let mut sel = CursorSelection::new(CursorId::new(0), 5, 10);
        sel.reversed = true;
        sel.place_at(7, Some((px(12.), 3)));
        assert_eq!(sel.start, 7);
        assert_eq!(sel.end, 7);
        assert!(sel.is_collapsed());
        assert!(!sel.reversed);
        assert_eq!(sel.column_anchor, Some((px(12.), 3)));
    }

    #[test]
    fn test_selections_never_empty() {
        let selections = Selections::new();
        assert_eq!(selections.len(), 1);
        assert_eq!(selections.active().id, CursorId::new(0));

        let default = Selections::default();
        assert_eq!(default.len(), 1);
    }

    #[test]
    fn test_selections_active_mut() {
        let mut selections = Selections::new();
        selections.active_mut().place_at(4, None);
        assert_eq!(selections.active().cursor_offset(), 4);
    }

    #[test]
    fn test_selections_merge_overlapping() {
        let mut selections = Selections::new();

        let id1 = selections.generate_id();
        let id2 = selections.generate_id();
        let id3 = selections.generate_id();

        // id1 is the active selection (index 0).
        selections.replace_all(vec![
            CursorSelection::new(id1, 0, 10),
            CursorSelection::new(id2, 5, 15), // Overlaps with the first.
            CursorSelection::new(id3, 20, 30), // Non-overlapping.
        ]);

        selections.merge_overlapping();

        // After merge: (0, 15) and (20, 30).
        assert_eq!(selections.len(), 2);
        // The active selection stays at index 0 and carries its id.
        assert_eq!(selections.active().id, id1);
        assert_eq!(
            (selections.active().start, selections.active().end),
            (0, 15)
        );

        let ranges: Vec<_> = selections.iter().map(|s| (s.start, s.end)).collect();
        assert!(ranges.contains(&(0, 15)));
        assert!(ranges.contains(&(20, 30)));
    }

    #[test]
    fn merging_preserves_the_active_selection_direction() {
        let mut selections = Selections::new();
        let active_id = selections.generate_id();
        let other_id = selections.generate_id();
        let mut active = CursorSelection::new(active_id, 5, 15);
        active.reversed = true;
        let other = CursorSelection::new(other_id, 0, 10);
        selections.replace_all(vec![active, other]);

        selections.merge_overlapping();

        assert_eq!(selections.active().id, active_id);
        assert!(selections.active().reversed);
    }
}
