use std::ops::Range;

use gpui::{
    App, Context, Div, InteractiveElement as _, IntoElement, ParentElement as _, Pixels,
    SharedString, Stateful, Styled as _, Window, div,
};

use crate::{
    ActiveTheme as _, Icon, IconName, Size, h_flex,
    menu::PopupMenu,
    table::{Column, ColumnGroup, ColumnSort, TableState, loading::Loading},
};

/// A delegate trait for providing data and rendering for a table.
#[allow(unused)]
pub trait TableDelegate: Sized + 'static {
    /// Return the number of columns in the table.
    fn columns_count(&self, cx: &App) -> usize;

    /// Return the number of rows in the table.
    fn rows_count(&self, cx: &App) -> usize;

    /// Returns the table column at the given index.
    ///
    /// This only call on Table prepare or refresh.
    fn column(&self, col_ix: usize, cx: &App) -> Column;

    /// Perform sort on the column at the given index.
    fn perform_sort(
        &mut self,
        col_ix: usize,
        sort: ColumnSort,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) {
    }

    /// Return the width the content of column `col_ix` needs to be read
    /// whole, or `None` to leave the column as it is.
    ///
    /// Called when the column's resize handle is double-clicked. Measure the
    /// widest of the column's cells and its header as drawn; the table adds
    /// the cell padding, clamps the sum to the column's `min_width` and
    /// `max_width`, and emits [`TableEvent::ColumnWidthsChanged`]. A sortable
    /// column's header also holds the table's sort icon (a 0.75rem icon with
    /// 2 px of padding on each side), which a header measurement must count.
    ///
    /// This is called from inside the table's own update, so an
    /// implementation must not update the table's entity again.
    ///
    /// Returns `None` by default, so a double-click changes nothing.
    ///
    /// [`TableEvent::ColumnWidthsChanged`]: crate::table::TableEvent::ColumnWidthsChanged
    fn fit_column(
        &mut self,
        col_ix: usize,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> Option<Pixels> {
        None
    }

    /// Render the table head row.
    fn render_header(
        &mut self,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> Stateful<Div> {
        div().id("header")
    }

    /// Return the group headers definitions (can be multi-level).
    ///
    /// By default, it returns None, meaning no group headers.
    fn group_headers(&self, cx: &App) -> Option<Vec<Vec<ColumnGroup>>> {
        None
    }

    /// Custom render for a group header cell.
    /// Receives the group label, the logical col_span, and the pixel width.
    fn render_group_th(
        &mut self,
        label: &SharedString,
        _col_span: usize,
        width: Pixels,
        _window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        div()
            .w(width)
            .h_full()
            .flex_shrink_0()
            .flex()
            .items_center()
            .justify_center()
            .border_r_1()
            .border_color(cx.theme().border)
            .child(label.clone())
    }

    /// Render the header cell at the given column index, default to the column name.
    fn render_th(
        &mut self,
        col_ix: usize,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        div()
            .size_full()
            .child(self.column(col_ix, cx).name.clone())
    }

    /// Render the row at the given row and column.
    ///
    /// Not include the table head row.
    fn render_tr(
        &mut self,
        row_ix: usize,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> Stateful<Div> {
        div().id(("row", row_ix))
    }

    /// Render the context menu for the row at the given row index.
    fn context_menu(
        &mut self,
        row_ix: usize,
        menu: PopupMenu,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> PopupMenu {
        menu
    }

    /// Render cell at the given row and column.
    fn render_td(
        &mut self,
        row_ix: usize,
        col_ix: usize,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement;

    /// Return the text a screen reader should read for the cell at the given
    /// row and column, usually the text [`render_td`](Self::render_td) draws.
    ///
    /// Plain text drawn by a cell is not exposed to assistive technology, so
    /// without this a cell is announced with no content. Returns `None` by
    /// default.
    fn cell_label(&self, row_ix: usize, col_ix: usize, cx: &App) -> Option<SharedString> {
        None
    }

    /// Move the column at the given `col_ix` so that it ends up at the index `to_ix`.
    ///
    /// e.g.: `let col = self.columns.remove(col_ix); self.columns.insert(to_ix, col);`
    fn move_column(
        &mut self,
        col_ix: usize,
        to_ix: usize,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) {
    }

    /// Return a Element to show when table is empty.
    fn render_empty(
        &mut self,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        h_flex()
            .size_full()
            .justify_center()
            .text_color(cx.theme().muted_foreground.opacity(0.6))
            .child(Icon::new(IconName::Inbox).size_12())
            .into_any_element()
    }

    /// Return true to show the loading view.
    fn loading(&self, cx: &App) -> bool {
        false
    }

    /// Return a Element to show when table is loading, default is built-in Skeleton loading view.
    ///
    /// The size is the size of the Table.
    fn render_loading(
        &mut self,
        size: Size,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        Loading::new().size(size)
    }

    /// Return true to enable load more data when scrolling to the bottom.
    ///
    /// Default: false
    fn has_more(&self, cx: &App) -> bool {
        false
    }

    /// Returns a threshold value (n rows), of course, when scrolling to the bottom,
    /// the remaining number of rows triggers `load_more`.
    /// This should smaller than the total number of first load rows.
    ///
    /// Default: 20 rows
    fn load_more_threshold(&self) -> usize {
        20
    }

    /// Load more data when the table is scrolled to the bottom.
    ///
    /// This will performed in a background task.
    ///
    /// This is always called when the table is near the bottom,
    /// so you must check if there is more data to load or lock the loading state.
    fn load_more(&mut self, window: &mut Window, cx: &mut Context<TableState<Self>>) {}

    /// Render the last empty column, default to empty.
    fn render_last_empty_col(
        &mut self,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        h_flex().w_3().h_full().flex_shrink_0()
    }

    /// Called when the visible range of the rows changed.
    ///
    /// The range never ends past `rows_count`; a table whose rows drop to none
    /// reports `0..0`.
    ///
    /// NOTE: Make sure this method is fast, because it will be called frequently.
    ///
    /// This can used to handle some data update, to only update the visible rows.
    /// Please ensure that the data is updated in the background task.
    fn visible_rows_changed(
        &mut self,
        visible_range: Range<usize>,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) {
    }

    /// Called when the visible range of the columns changed.
    ///
    /// NOTE: Make sure this method is fast, because it will be called frequently.
    ///
    /// This can used to handle some data update, to only update the visible rows.
    /// Please ensure that the data is updated in the background task.
    fn visible_columns_changed(
        &mut self,
        visible_range: Range<usize>,
        window: &mut Window,
        cx: &mut Context<TableState<Self>>,
    ) {
    }

    /// Get the text representation of a cell for export purposes (e.g., CSV export).
    ///
    /// Returns an empty string by default. Implement this method to support export.
    /// The text should be formatted as it should appear in the exported data.
    fn cell_text(&self, row_ix: usize, col_ix: usize, cx: &App) -> String {
        String::new()
    }
}
