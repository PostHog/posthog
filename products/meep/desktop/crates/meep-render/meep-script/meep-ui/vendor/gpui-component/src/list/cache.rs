use std::rc::Rc;

use gpui::{App, Pixels, Size};

use crate::IndexPath;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RowEntry {
    Entry(IndexPath),
    SectionHeader(usize),
    SectionFooter(usize),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub(crate) struct MeasuredEntrySize {
    pub(crate) item_size: Size<Pixels>,
    pub(crate) section_header_size: Size<Pixels>,
    pub(crate) section_footer_size: Size<Pixels>,
}

impl RowEntry {
    #[inline]
    #[allow(unused)]
    pub(crate) fn is_section_header(&self) -> bool {
        matches!(self, RowEntry::SectionHeader(_))
    }

    pub(crate) fn eq_index_path(&self, path: &IndexPath) -> bool {
        match self {
            RowEntry::Entry(index_path) => index_path == path,
            RowEntry::SectionHeader(_) | RowEntry::SectionFooter(_) => false,
        }
    }

    #[allow(unused)]
    pub(crate) fn index(&self) -> IndexPath {
        match self {
            RowEntry::Entry(index_path) => *index_path,
            RowEntry::SectionHeader(ix) => IndexPath::default().section(*ix),
            RowEntry::SectionFooter(ix) => IndexPath::default().section(*ix),
        }
    }

    #[inline]
    #[allow(unused)]
    pub(crate) fn is_section_footer(&self) -> bool {
        matches!(self, RowEntry::SectionFooter(_))
    }

    #[inline]
    pub(crate) fn is_entry(&self) -> bool {
        matches!(self, RowEntry::Entry(_))
    }

    #[inline]
    #[allow(unused)]
    pub(crate) fn section_ix(&self) -> Option<usize> {
        match self {
            RowEntry::SectionHeader(ix) | RowEntry::SectionFooter(ix) => Some(*ix),
            _ => None,
        }
    }
}

#[derive(Default, Clone)]
pub(crate) struct RowsCache {
    /// Only have section's that have rows.
    pub(crate) entities: Rc<Vec<RowEntry>>,
    pub(crate) items_count: usize,
    /// The sections, the item is number of rows in each section.
    pub(crate) sections: Rc<Vec<usize>>,
    pub(crate) entries_sizes: Rc<Vec<Size<Pixels>>>,
    measured_size: MeasuredEntrySize,
}

impl RowsCache {
    pub(crate) fn get(&self, flatten_ix: usize) -> Option<RowEntry> {
        self.entities.get(flatten_ix).cloned()
    }

    /// Returns the number of flattened rows (Includes header, item, footer).
    pub(crate) fn len(&self) -> usize {
        self.entities.len()
    }

    /// Return the number of items in the cache.
    pub(crate) fn items_count(&self) -> usize {
        self.items_count
    }

    /// Returns the index of the  Entry with given path in the flattened rows.
    pub(crate) fn position_of(&self, path: &IndexPath) -> Option<usize> {
        self.entities
            .iter()
            .position(|p| p.is_entry() && p.eq_index_path(path))
    }

    /// Returns the flattened position of the first item row, skipping section
    /// headers and footers.
    pub(crate) fn first_entry_position(&self) -> Option<usize> {
        self.entities.iter().position(RowEntry::is_entry)
    }

    /// Return prev row, if the row is the first in the first section, goes to the last row.
    ///
    /// Empty rows section are skipped.
    pub(crate) fn prev(&self, path: Option<IndexPath>) -> IndexPath {
        let path = path.unwrap_or_default();
        let Some(pos) = self.position_of(&path) else {
            return self
                .entities
                .iter()
                .rfind(|entry| entry.is_entry())
                .map(|entry| entry.index())
                .unwrap_or_default();
        };

        if let Some(path) = self
            .entities
            .iter()
            .take(pos)
            .rev()
            .find(|entry| entry.is_entry())
            .map(|entry| entry.index())
        {
            path
        } else {
            self.entities
                .iter()
                .rfind(|entry| entry.is_entry())
                .map(|entry| entry.index())
                .unwrap_or_default()
        }
    }

    /// Returns the next row, if the row is the last in the last section, goes to the first row.
    ///
    /// Empty rows section are skipped.
    pub(crate) fn next(&self, path: Option<IndexPath>) -> IndexPath {
        let Some(mut path) = path else {
            return IndexPath::default();
        };

        let Some(pos) = self.position_of(&path) else {
            return self
                .entities
                .iter()
                .find(|entry| entry.is_entry())
                .map(|entry| entry.index())
                .unwrap_or_default();
        };

        if let Some(next_path) = self
            .entities
            .iter()
            .skip(pos + 1)
            .find(|entry| entry.is_entry())
            .map(|entry| entry.index())
        {
            path = next_path;
        } else {
            path = self
                .entities
                .iter()
                .find(|entry| entry.is_entry())
                .map(|entry| entry.index())
                .unwrap_or_default()
        }

        path
    }

    pub(crate) fn prepare_if_needed<F>(
        &mut self,
        sections_count: usize,
        measured_size: MeasuredEntrySize,
        cx: &App,
        rows_count_f: F,
    ) where
        F: Fn(usize, &App) -> usize,
    {
        let mut new_sections = vec![];
        for section_ix in 0..sections_count {
            new_sections.push(rows_count_f(section_ix, cx));
        }

        let need_update = new_sections != *self.sections || self.measured_size != measured_size;

        if !need_update {
            return;
        }

        let mut entries_sizes = vec![];
        let mut total_items_count = 0;
        self.measured_size = measured_size;
        self.sections = Rc::new(new_sections);
        self.entities = Rc::new(
            self.sections
                .iter()
                .enumerate()
                .flat_map(|(section, items_count)| {
                    total_items_count += items_count;
                    let mut children = vec![];
                    if *items_count == 0 {
                        return children;
                    }

                    children.push(RowEntry::SectionHeader(section));
                    entries_sizes.push(measured_size.section_header_size);
                    for row in 0..*items_count {
                        children.push(RowEntry::Entry(IndexPath {
                            section,
                            row,
                            ..Default::default()
                        }));
                        entries_sizes.push(measured_size.item_size);
                    }
                    children.push(RowEntry::SectionFooter(section));
                    entries_sizes.push(measured_size.section_footer_size);
                    children
                })
                .collect(),
        );
        self.entries_sizes = Rc::new(entries_sizes);
        self.items_count = total_items_count;
    }
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use crate::{
        IndexPath,
        list::cache::{RowEntry, RowsCache},
    };

    fn build_entities(sections: &[usize]) -> Vec<RowEntry> {
        sections
            .iter()
            .enumerate()
            .flat_map(|(section, items_count)| {
                let mut children = vec![];
                if *items_count == 0 {
                    return children;
                }

                children.push(RowEntry::SectionHeader(section));
                for row in 0..*items_count {
                    children.push(RowEntry::Entry(IndexPath {
                        section,
                        row,
                        ..Default::default()
                    }));
                }
                children.push(RowEntry::SectionFooter(section));
                children
            })
            .collect()
    }

    #[test]
    fn first_entry_position_skips_section_headers() {
        let mut row_cache = RowsCache::default();
        row_cache.entities = Rc::new(build_entities(&[2]));

        assert_eq!(row_cache.first_entry_position(), Some(1));
    }

    #[test]
    fn test_prev_next() {
        let mut row_cache = RowsCache::default();
        // section 0
        //  row 0
        //  row 1
        // section 1
        //  row 0
        //  row 1
        //  row 2
        //  row 3
        // section 2
        //  row 0
        //  row 1
        //  row 2
        row_cache.sections = Rc::new(vec![2, 4, 3]);
        row_cache.entities = Rc::new(build_entities(&[2, 4, 3]));

        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(0))),
            IndexPath::new(1).section(0)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(1).section(0))),
            IndexPath::new(0).section(1)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(1))),
            IndexPath::new(1).section(1)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(3).section(1))),
            IndexPath::new(0).section(2)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(2))),
            IndexPath::new(1).section(2)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(1).section(2))),
            IndexPath::new(2).section(2)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(2).section(2))),
            IndexPath::new(0).section(0)
        );

        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(0))),
            IndexPath::new(2).section(2)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(1).section(0))),
            IndexPath::new(0).section(0)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(1))),
            IndexPath::new(1).section(0)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(1).section(1))),
            IndexPath::new(0).section(1)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(3).section(1))),
            IndexPath::new(2).section(1)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(2))),
            IndexPath::new(3).section(1)
        );
    }

    #[test]
    fn test_prev_next_with_empty_sections() {
        let mut row_cache = RowsCache::default();
        // section 0: 2 items
        // section 1: 0 items (empty, should be skipped)
        // section 2: 3 items
        // section 3: 0 items (empty, should be skipped)
        // section 4: 1 item
        row_cache.sections = Rc::new(vec![2, 0, 3, 0, 1]);
        row_cache.entities = Rc::new(build_entities(&[2, 0, 3, 0, 1]));

        // Test next: should skip empty sections
        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(0))),
            IndexPath::new(1).section(0)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(1).section(0))),
            IndexPath::new(0).section(2) // Skip section 1 (empty)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(2))),
            IndexPath::new(1).section(2)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(2).section(2))),
            IndexPath::new(0).section(4) // Skip section 3 (empty)
        );
        assert_eq!(
            row_cache.next(Some(IndexPath::new(0).section(4))),
            IndexPath::new(0).section(0) // Wrap around to first item
        );

        // Test prev: should skip empty sections
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(0))),
            IndexPath::new(0).section(4) // Wrap around to last item, skip empty sections
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(2))),
            IndexPath::new(1).section(0) // Skip section 1 (empty)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(0).section(4))),
            IndexPath::new(2).section(2) // Skip section 3 (empty)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(1).section(2))),
            IndexPath::new(0).section(2)
        );
        assert_eq!(
            row_cache.prev(Some(IndexPath::new(2).section(2))),
            IndexPath::new(1).section(2)
        );
    }
}
