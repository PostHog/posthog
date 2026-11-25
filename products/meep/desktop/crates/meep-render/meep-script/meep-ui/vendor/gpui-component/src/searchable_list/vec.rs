use gpui::{App, SharedString, Task, Window};

use crate::IndexPath;

use super::delegate::{SearchableListDelegate, SearchableListItem};

// MARK: Primitive impls

impl SearchableListItem for String {
    type Value = Self;

    fn title(&self) -> SharedString {
        SharedString::from(self.clone())
    }

    fn value(&self) -> &Self::Value {
        self
    }
}

impl SearchableListItem for SharedString {
    type Value = Self;

    fn title(&self) -> SharedString {
        self.clone()
    }

    fn value(&self) -> &Self::Value {
        self
    }
}

impl SearchableListItem for &'static str {
    type Value = Self;

    fn title(&self) -> SharedString {
        SharedString::from(*self)
    }

    fn value(&self) -> &Self::Value {
        self
    }
}

// MARK: Vec delegate

impl<T: SearchableListItem + 'static> SearchableListDelegate for Vec<T> {
    type Item = T;

    fn items_count(&self, _: usize) -> usize {
        self.len()
    }

    fn item(&self, ix: IndexPath) -> Option<&Self::Item> {
        self.as_slice().get(ix.row)
    }

    fn position<V>(&self, value: &V) -> Option<IndexPath>
    where
        Self::Item: SearchableListItem<Value = V>,
        V: PartialEq,
    {
        self.iter()
            .position(|v| v.value() == value)
            .map(|ix| IndexPath::default().row(ix))
    }
}

// MARK: SearchableVec

/// A vector of items that supports incremental filtering.
///
/// On each `perform_search` call the matched view is rebuilt by filtering the
/// full `items` list. Use this as a delegate when all data is already in memory.
#[derive(Debug, Clone)]
pub struct SearchableVec<T> {
    items: Vec<T>,
    matched: Vec<Matched>,
}

/// An entry of the filtered view, pointing into `SearchableVec::items`.
#[derive(Debug, Clone)]
struct Matched {
    ix: usize,
    /// The matched rows of a group, or `None` to keep every row.
    rows: Option<Vec<usize>>,
}

impl Matched {
    fn all(ix: usize) -> Self {
        Self { ix, rows: None }
    }

    /// The number of rows shown, out of `all` rows of the item.
    fn len(&self, all: usize) -> usize {
        self.rows.as_ref().map_or(all, Vec::len)
    }

    fn row(&self, row: usize) -> Option<usize> {
        match &self.rows {
            Some(rows) => rows.get(row).copied(),
            None => Some(row),
        }
    }
}

impl<T> SearchableVec<T> {
    fn from_items(items: Vec<T>) -> Self {
        Self {
            matched: (0..items.len()).map(Matched::all).collect(),
            items,
        }
    }

    fn matched_item(&self, ix: usize) -> Option<(&Matched, &T)> {
        let matched = self.matched.get(ix)?;
        Some((matched, self.items.get(matched.ix)?))
    }

    fn matched_items(&self) -> impl Iterator<Item = (&Matched, &T)> {
        self.matched
            .iter()
            .filter_map(|matched| Some((matched, self.items.get(matched.ix)?)))
    }
}

impl<T: Clone> SearchableVec<T> {
    /// Create a new `SearchableVec` from an initial list of items.
    pub fn new(items: impl Into<Vec<T>>) -> Self {
        Self::from_items(items.into())
    }

    /// Append an item to both the master list and the current filtered view.
    pub fn push(&mut self, item: T) {
        self.matched.push(Matched::all(self.items.len()));
        self.items.push(item);
    }
}

impl<T: SearchableListItem> From<Vec<T>> for SearchableVec<T> {
    fn from(items: Vec<T>) -> Self {
        Self::from_items(items)
    }
}

impl<I: SearchableListItem + 'static> SearchableListDelegate for SearchableVec<I> {
    type Item = I;

    fn items_count(&self, _: usize) -> usize {
        self.matched.len()
    }

    fn item(&self, ix: IndexPath) -> Option<&Self::Item> {
        self.matched_item(ix.row).map(|(_, item)| item)
    }

    fn position<V>(&self, value: &V) -> Option<IndexPath>
    where
        Self::Item: SearchableListItem<Value = V>,
        V: PartialEq,
    {
        self.matched_items()
            .position(|(_, v)| v.value() == value)
            .map(|ix| IndexPath::default().row(ix))
    }

    fn perform_search(&mut self, query: &str, _: &mut Window, _: &mut App) -> Task<()> {
        self.matched = self
            .items
            .iter()
            .enumerate()
            .filter(|(_, item)| item.matches(query))
            .map(|(ix, _)| Matched::all(ix))
            .collect();

        Task::ready(())
    }
}

// MARK: SearchableGroup

/// A named group of items used for sectioned lists.
#[derive(Debug, Clone)]
pub struct SearchableGroup<I: SearchableListItem> {
    pub title: SharedString,
    pub items: Vec<I>,
}

impl<I: SearchableListItem> SearchableGroup<I> {
    /// Create an empty group with the given section title.
    pub fn new(title: impl Into<SharedString>) -> Self {
        Self {
            title: title.into(),
            items: vec![],
        }
    }

    /// Append a single item to this group.
    pub fn item(mut self, item: I) -> Self {
        self.items.push(item);
        self
    }

    /// Append multiple items to this group.
    pub fn items(mut self, items: impl IntoIterator<Item = I>) -> Self {
        self.items.extend(items);
        self
    }

    /// The rows matching `query`, or `None` when neither the title nor any
    /// row matches and the whole group is hidden.
    fn matched_rows(&self, query: &str) -> Option<Vec<usize>> {
        let rows: Vec<usize> = self
            .items
            .iter()
            .enumerate()
            .filter(|(_, item)| item.matches(query))
            .map(|(ix, _)| ix)
            .collect();

        (!rows.is_empty() || self.title.to_lowercase().contains(&query.to_lowercase()))
            .then_some(rows)
    }
}

impl<I: SearchableListItem + 'static> SearchableListDelegate for SearchableVec<SearchableGroup<I>> {
    type Item = I;

    fn sections_count(&self, _: &App) -> usize {
        self.matched.len()
    }

    fn items_count(&self, section: usize) -> usize {
        self.matched_item(section)
            .map_or(0, |(matched, group)| matched.len(group.items.len()))
    }

    fn section(&self, section: usize) -> Option<gpui::AnyElement> {
        use gpui::IntoElement as _;

        let (_, group) = self.matched_item(section)?;
        Some(group.title.clone().into_any_element())
    }

    fn item(&self, ix: IndexPath) -> Option<&Self::Item> {
        let (matched, group) = self.matched_item(ix.section)?;

        group.items.get(matched.row(ix.row)?)
    }

    fn position<V>(&self, value: &V) -> Option<IndexPath>
    where
        Self::Item: SearchableListItem<Value = V>,
        V: PartialEq,
    {
        for (ix, (matched, group)) in self.matched_items().enumerate() {
            for row_ix in 0..matched.len(group.items.len()) {
                let item = matched.row(row_ix).and_then(|row| group.items.get(row));
                if item.is_some_and(|item| item.value() == value) {
                    return Some(IndexPath::default().section(ix).row(row_ix));
                }
            }
        }

        None
    }

    fn perform_search(&mut self, query: &str, _: &mut Window, _: &mut App) -> Task<()> {
        self.matched = self
            .items
            .iter()
            .enumerate()
            .filter_map(|(ix, group)| {
                let rows = group.matched_rows(query)?;
                Some(Matched {
                    ix,
                    rows: Some(rows),
                })
            })
            .collect();

        Task::ready(())
    }
}

#[cfg(test)]
mod tests {
    use gpui::TestAppContext;

    use super::*;

    #[gpui::test]
    fn test_searchable_vec_maps_matched_rows_to_items(cx: &mut TestAppContext) {
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let mut items = SearchableVec::new(vec!["Rust", "Go", "Ruby"]);
            _ = items.perform_search("ru", window, cx);
            assert_eq!(items.items_count(0), 2);
            assert_eq!(items.item(IndexPath::new(1)), Some(&"Ruby"));
            assert_eq!(items.position(&"Ruby"), Some(IndexPath::new(1)));
            assert_eq!(items.position(&"Go"), None);

            items.push("Rune");
            assert_eq!(items.item(IndexPath::new(2)), Some(&"Rune"));

            _ = items.perform_search("", window, cx);
            assert_eq!(items.items_count(0), 4);
        });
    }

    #[gpui::test]
    fn test_searchable_group_keeps_matched_rows(cx: &mut TestAppContext) {
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            let mut groups = SearchableVec::new(vec![
                SearchableGroup::new("Fruits").items(["Apple", "Banana"]),
                SearchableGroup::new("Berries").items(["Blueberry", "Cranberry"]),
                SearchableGroup::new("Nuts").items(["Almond"]),
            ]);

            _ = groups.perform_search("cran", window, cx);
            assert_eq!(groups.sections_count(cx), 1);
            assert_eq!(groups.items_count(0), 1);
            assert_eq!(groups.item(IndexPath::new(0)), Some(&"Cranberry"));
            assert_eq!(groups.position(&"Cranberry"), Some(IndexPath::new(0)));
            assert_eq!(groups.position(&"Blueberry"), None);

            // A title match keeps the section, with only its matching rows.
            _ = groups.perform_search("nuts", window, cx);
            assert_eq!(groups.sections_count(cx), 1);
            assert_eq!(groups.items_count(0), 0);

            _ = groups.perform_search("b", window, cx);
            assert_eq!(groups.sections_count(cx), 2);
            assert_eq!(groups.items_count(1), 2);
            assert_eq!(
                groups.position(&"Cranberry"),
                Some(IndexPath::new(1).section(1))
            );
        });
    }
}
