use gpui::{
    Bounds, Context, Edges, Empty, EntityId, IntoElement, ParentElement as _, Pixels, Render,
    SharedString, Styled as _, TextAlign, Window, div, prelude::FluentBuilder, px,
};

use crate::ActiveTheme as _;

/// Represents a column in a table, used for initializing table columns.
#[derive(Debug, Clone)]
pub struct Column {
    /// The unique key of the column.
    ///
    /// This is used to identify the column in the table and your data source.
    ///
    /// In most cases, it should match the field name in your data source.
    pub key: SharedString,
    /// The display name of the column.
    pub name: SharedString,
    /// The text alignment of the column.
    pub align: TextAlign,
    /// The sorting behavior of the column, if any.
    ///
    /// If `None`, the column is not sortable.
    pub sort: Option<ColumnSort>,
    /// The padding of the column.
    pub paddings: Option<Edges<Pixels>>,
    /// The width of the column.
    pub width: Pixels,
    /// Whether the column is fixed, the fixed column will pin at the left side when scrolling horizontally.
    pub fixed: Option<ColumnFixed>,
    /// Whether the column is resizable.
    pub resizable: bool,
    /// Whether the column is movable.
    pub movable: bool,
    /// Whether the column is selectable.
    ///
    /// When `true`:
    /// - In column selection mode: The entire column can be selected
    /// - In cell selection mode: Individual cells in this column can be selected
    ///
    /// When `false`:
    /// - The column and its cells cannot be selected
    /// - Useful for action columns (e.g., buttons, checkboxes) that shouldn't participate in selection
    pub selectable: bool,
    /// The minimum width of the column.
    pub min_width: Pixels,
    /// The maximum width of the column.
    pub max_width: Pixels,
}

/// A column group can be used to group multiple columns under a single header.
#[derive(Debug, Clone)]
pub struct ColumnGroup {
    pub label: SharedString,
    pub span: usize,
}

impl ColumnGroup {
    pub fn new(label: impl Into<SharedString>, span: usize) -> Self {
        Self {
            label: label.into(),
            span,
        }
    }
}

impl Default for Column {
    fn default() -> Self {
        Self {
            key: SharedString::new(""),
            name: SharedString::new(""),
            align: TextAlign::Left,
            sort: None,
            paddings: None,
            width: px(100.),
            fixed: None,
            resizable: true,
            movable: true,
            selectable: true,
            min_width: px(20.0),
            max_width: px(1200.),
        }
    }
}

impl Column {
    /// Create a new column with the given key and name.
    pub fn new(key: impl Into<SharedString>, name: impl Into<SharedString>) -> Self {
        Self {
            key: key.into(),
            name: name.into(),
            ..Default::default()
        }
    }

    /// Set the column to be sortable with custom sort function, default is None (not sortable).
    ///
    /// See also [`Column::sortable`] to enable sorting with default.
    pub fn sort(mut self, sort: ColumnSort) -> Self {
        self.sort = Some(sort);
        self
    }

    /// Set whether the column is sortable, default is true.
    ///
    /// See also [`Column::sort`].
    pub fn sortable(mut self) -> Self {
        self.sort = Some(ColumnSort::Default);
        self
    }

    /// Set whether the column is sort with ascending order.
    pub fn ascending(mut self) -> Self {
        self.sort = Some(ColumnSort::Ascending);
        self
    }

    /// Set whether the column is sort with descending order.
    pub fn descending(mut self) -> Self {
        self.sort = Some(ColumnSort::Descending);
        self
    }

    /// Center the column's text, in its header and in its cells.
    ///
    /// The table aligns text; a cell that renders its own layout, such as a
    /// flex row, aligns that layout itself.
    pub fn text_center(mut self) -> Self {
        self.align = TextAlign::Center;
        self
    }

    /// Right-align the column's text, in its header and in its cells. The
    /// default is left.
    ///
    /// The table aligns text; a cell that renders its own layout, such as a
    /// flex row, aligns that layout itself.
    pub fn text_right(mut self) -> Self {
        self.align = TextAlign::Right;
        self
    }

    /// Set the padding of the column, default is None.
    pub fn paddings(mut self, paddings: impl Into<Edges<Pixels>>) -> Self {
        self.paddings = Some(paddings.into());
        self
    }

    /// Set the padding of the column to 0px.
    pub fn p_0(mut self) -> Self {
        self.paddings = Some(Edges::all(px(0.)));
        self
    }

    /// Set the width of the column, default is 100px.
    pub fn width(mut self, width: impl Into<Pixels>) -> Self {
        self.width = width.into();
        self
    }

    /// Set whether the column is fixed, default is false.
    pub fn fixed(mut self, fixed: impl Into<ColumnFixed>) -> Self {
        self.fixed = Some(fixed.into());
        self
    }

    /// Set whether the column is fixed on left side, default is false.
    pub fn fixed_left(mut self) -> Self {
        self.fixed = Some(ColumnFixed::Left);
        self
    }

    /// Set whether the column is resizable, default is true.
    pub fn resizable(mut self, resizable: bool) -> Self {
        self.resizable = resizable;
        self
    }

    /// Set whether the column is movable, default is true.
    pub fn movable(mut self, movable: bool) -> Self {
        self.movable = movable;
        self
    }

    /// Set whether the column is selectable, default is true.
    ///
    /// When `false`, this column and its cells will not participate in selection:
    /// - In column selection mode: The column header cannot be clicked to select
    /// - In cell selection mode: Cells in this column cannot be selected
    ///
    /// This is useful for action columns (e.g., with buttons or checkboxes) that
    /// should not be part of the selection system.
    ///
    /// # Example
    ///
    /// ```rust,ignore
    /// Column::new("actions", "Actions")
    ///     .width(px(100.))
    ///     .selectable(false)  // Prevent selection of action buttons
    /// ```
    pub fn selectable(mut self, selectable: bool) -> Self {
        self.selectable = selectable;
        self
    }

    /// Set the minimum width of the column, default is 20px
    pub fn min_width(mut self, min_width: impl Into<Pixels>) -> Self {
        let min_width = min_width.into();
        self.min_width = min_width;

        // If the current width is smaller than the new minimum,
        // bump the width up to match the minimum.
        if self.width < min_width {
            self.width = min_width;
        }
        self
    }

    /// Set the maximum width when resizing the column, default is 1200px.
    ///
    /// The default protects against oversized columns during resizing. Set a
    /// larger maximum explicitly when wider columns are needed. It does not
    /// limit an initial width set afterwards with [`Self::width`].
    pub fn max_width(mut self, max_width: impl Into<Pixels>) -> Self {
        let max_width = max_width.into();
        self.max_width = max_width;

        // If the current width is larger than the new maximum,
        // pull the width down to match the maximum.
        if self.width > max_width {
            self.width = max_width;
        }
        self
    }
}

impl FluentBuilder for Column {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ColumnFixed {
    Left,
}

/// Used to sort the column runtime info in Table internal.
#[derive(Debug, Clone)]
pub(crate) struct ColGroup {
    pub(crate) column: Column,
    /// This is the runtime width of the column, we may update it when the column is resized.
    ///
    /// Including the width with next columns by col_span.
    pub(crate) width: Pixels,
    /// The bounds of the column in the table after it renders.
    pub(crate) bounds: Bounds<Pixels>,
}

impl ColGroup {
    pub(crate) fn is_resizable(&self) -> bool {
        self.column.resizable
    }
}

#[derive(Clone)]
pub(crate) struct DragColumn {
    pub(crate) entity_id: EntityId,
    pub(crate) name: SharedString,
    pub(crate) width: Pixels,
    pub(crate) col_ix: usize,
}

/// The sorting behavior of a column.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Default)]
pub enum ColumnSort {
    /// No sorting.
    #[default]
    Default,
    /// Sort in ascending order.
    Ascending,
    /// Sort in descending order.
    Descending,
}

impl Render for DragColumn {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .px_4()
            .py_1()
            .bg(cx.theme().tokens.table_head)
            .text_color(cx.theme().muted_foreground)
            .opacity(0.9)
            .border_1()
            .border_color(cx.theme().border)
            .shadow_md()
            .w(self.width)
            .min_w(px(100.))
            .max_w(px(450.))
            .child(self.name.clone())
    }
}

#[derive(Clone)]
pub(crate) struct ResizeColumn(pub (EntityId, usize));
impl Render for ResizeColumn {
    fn render(&mut self, _window: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}
