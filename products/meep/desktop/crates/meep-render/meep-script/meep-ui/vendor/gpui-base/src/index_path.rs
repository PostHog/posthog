use std::fmt::{Debug, Display};

use gpui::ElementId;

/// Represents an index path in a list, which consists of a section index,
///
/// The default values for section, row, and column are all set to 0.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct IndexPath {
    /// The section index.
    pub section: usize,
    /// The item index in the section.
    pub row: usize,
    /// The column index.
    pub column: usize,
}

impl From<IndexPath> for ElementId {
    fn from(path: IndexPath) -> Self {
        ElementId::Name(format!("index-path({},{},{})", path.section, path.row, path.column).into())
    }
}

impl Display for IndexPath {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "IndexPath(section: {}, row: {}, column: {})",
            self.section, self.row, self.column
        )
    }
}

impl IndexPath {
    /// Create a new index path with the specified section and row.
    ///
    /// The `section` is set to 0 by default.
    /// The `column` is set to 0 by default.
    pub fn new(row: usize) -> Self {
        IndexPath {
            section: 0,
            row,
            ..Default::default()
        }
    }

    /// Set the section for the index path.
    pub fn section(mut self, section: usize) -> Self {
        self.section = section;
        self
    }

    /// Set the row for the index path.
    pub fn row(mut self, row: usize) -> Self {
        self.row = row;
        self
    }

    /// Set the column for the index path.
    pub fn column(mut self, column: usize) -> Self {
        self.column = column;
        self
    }

    /// Check if the self is equal to the given index path (Same section and row).
    pub fn eq_row(&self, index: IndexPath) -> bool {
        self.section == index.section && self.row == index.row
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_into_element_id() {
        let index_path = IndexPath::new(2).section(1).column(3);
        let element_id: ElementId = index_path.into();
        assert_eq!(element_id.to_string(), "index-path(1,2,3)");
    }

    #[test]
    fn test_display() {
        assert_eq!(
            format!("{}", IndexPath::new(2).section(1).column(3)),
            "IndexPath(section: 1, row: 2, column: 3)"
        );
    }

    #[test]
    fn test_index_path() {
        let mut index_path = IndexPath::default();
        assert_eq!(index_path.section, 0);
        assert_eq!(index_path.row, 0);
        assert_eq!(index_path.column, 0);

        index_path = index_path.section(1).row(2).column(3);
        assert_eq!(index_path.section, 1);
        assert_eq!(index_path.row, 2);
        assert_eq!(index_path.column, 3);
    }
}
