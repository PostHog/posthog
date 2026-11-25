use crate::{
    ActiveTheme, Sizable, Size, ThemeStyled as _,
    actions::{
        Cancel, SelectDown, SelectFirst, SelectLast, SelectNextColumn, SelectPageDown,
        SelectPageUp, SelectPrevColumn, SelectUp,
    },
    table::{TableDelegate, TableState},
};
use gpui::{
    App, Edges, Entity, Focusable, InteractiveElement, IntoElement, KeyBinding, ParentElement,
    Pixels, RenderOnce, SharedString, StatefulInteractiveElement, Styled, Window, div,
    prelude::FluentBuilder,
};
use gpui_base::TestSupportExt as _;

const CONTEXT: &'static str = "DataTable";
pub(super) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
        KeyBinding::new("up", SelectUp, Some(CONTEXT)),
        KeyBinding::new("down", SelectDown, Some(CONTEXT)),
        KeyBinding::new("left", SelectPrevColumn, Some(CONTEXT)),
        KeyBinding::new("right", SelectNextColumn, Some(CONTEXT)),
        KeyBinding::new("home", SelectFirst, Some(CONTEXT)),
        KeyBinding::new("end", SelectLast, Some(CONTEXT)),
        KeyBinding::new("pageup", SelectPageUp, Some(CONTEXT)),
        KeyBinding::new("pagedown", SelectPageDown, Some(CONTEXT)),
        KeyBinding::new("tab", SelectNextColumn, Some(CONTEXT)),
        KeyBinding::new("shift-tab", SelectPrevColumn, Some(CONTEXT)),
    ]);
}

pub(super) struct TableOptions {
    pub(super) scroll_bounce: Option<bool>,
    pub(super) scrollbar_visible: Edges<bool>,
    /// Set stripe style of the table.
    pub(super) stripe: bool,
    /// Set to use border style of the table.
    pub(super) bordered: bool,
    /// Draw the border on the right edge of the fixed columns.
    pub(super) fixed_cols_border: bool,
    /// The cell size of the table.
    pub(super) size: Size,
    /// Height of each header row. `None` uses [`Size::table_row_height`].
    pub(super) header_row_height: Option<Pixels>,
}

impl Default for TableOptions {
    fn default() -> Self {
        Self {
            scroll_bounce: None,
            scrollbar_visible: Edges::all(true),
            stripe: false,
            bordered: true,
            fixed_cols_border: true,
            size: Size::default(),
            header_row_height: None,
        }
    }
}

/// A table element with support for row, column, and cell selection.
///
/// # Features
///
/// - **Multiple Selection Modes**: Support for row, column, and cell selection
/// - **Cell Selection**: Click to select individual cells, with keyboard navigation
/// - **Virtual Scrolling**: Efficient rendering of large datasets
/// - **Resizable Columns**: Drag column borders to resize
/// - **Movable Columns**: Drag column headers to reorder
/// - **Fixed Columns**: Pin columns to the left side
/// - **Sortable Columns**: Click column headers to sort
/// - **Context Menus**: Right-click support for rows and cells
///
/// # Cell Selection Mode
///
/// When cell selection is enabled via [`TableState::cell_selectable()`]:
/// - Click on cells to select them
/// - A row header column appears on the left for selecting entire rows
///   (use [`TableState::row_header()`] to hide it)
/// - Keyboard navigation (arrow keys, Tab, Home, End, PageUp, PageDown) works at cell level
/// - Right-click and double-click events are supported
///
/// See [`TableState`] for more details on cell selection.
///
/// # Example
///
/// ```rust,ignore
/// let table_state = cx.new(|cx| {
///     TableState::new(delegate, cx)
///         .cell_selectable(true)
///         .row_selectable(true)
/// });
///
/// DataTable::new(&table_state)
///     .stripe(true)
///     .bordered(true)
/// ```
#[derive(IntoElement)]
pub struct DataTable<D: TableDelegate> {
    state: Entity<TableState<D>>,
    options: TableOptions,
    focus_ring_enabled: bool,
    accessibility_label: Option<SharedString>,
}

impl<D> DataTable<D>
where
    D: TableDelegate,
{
    /// Create a new DataTable element with the given [`TableState`].
    pub fn new(state: &Entity<TableState<D>>) -> Self {
        Self {
            state: state.clone(),
            options: TableOptions::default(),
            focus_ring_enabled: true,
            accessibility_label: None,
        }
    }

    /// Sets the label exposed to accessibility clients, the table's name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Set to use stripe style of the table, default to false.
    pub fn stripe(mut self, stripe: bool) -> Self {
        self.options.stripe = stripe;
        self
    }

    /// Bounce the rows at the vertical boundaries, keeping headers and
    /// scrollbars fixed. On by default on iOS,
    /// Android and macOS, off elsewhere.
    pub fn scroll_bounce(mut self, enabled: bool) -> Self {
        self.options.scroll_bounce = Some(enabled);
        self
    }

    /// Set to use border style of the table, default to true.
    pub fn bordered(mut self, bordered: bool) -> Self {
        self.options.bordered = bordered;
        self
    }

    /// Set the height of each header row.
    ///
    /// Column-group rows use the same height, so the whole header is this
    /// height times the number of header rows. Body rows keep the height from
    /// [`Size::table_row_height`]. When this is unset, header rows use that
    /// same height.
    pub fn header_row_height(mut self, height: impl Into<Pixels>) -> Self {
        self.options.header_row_height = Some(height.into());
        self
    }

    /// Set whether to draw the border on the right edge of the fixed columns,
    /// default to true.
    ///
    /// Turn it off when the fixed cells draw that edge themselves, so the
    /// boundary is not drawn twice.
    pub fn fixed_cols_border(mut self, fixed_cols_border: bool) -> Self {
        self.options.fixed_cols_border = fixed_cols_border;
        self
    }

    /// Set scrollbar visibility.
    pub fn scrollbar_visible(mut self, vertical: bool, horizontal: bool) -> Self {
        self.options.scrollbar_visible = Edges {
            right: vertical,
            bottom: horizontal,
            ..Default::default()
        };
        self
    }
}

impl<D> Sizable for DataTable<D>
where
    D: TableDelegate,
{
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.options.size = size.into();
        self
    }
}

impl<D> crate::FocusableExt for DataTable<D>
where
    D: TableDelegate,
{
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl<D> RenderOnce for DataTable<D>
where
    D: TableDelegate,
{
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let bordered = self.options.bordered;
        let focus_ring_enabled = self.focus_ring_enabled;
        let focus_handle = self.state.focus_handle(cx);
        let (role, rows_count, columns_count) = self.state.update(cx, |state, cx| {
            state.options = self.options;
            // A table that selects rows or cells is a grid.
            let role = if state.row_selectable || state.cell_selectable {
                gpui::Role::Grid
            } else {
                gpui::Role::Table
            };
            let delegate = state.delegate();
            (role, delegate.rows_count(cx), delegate.columns_count(cx))
        });

        // The element that holds the keyboard focus is the table's
        // accessibility node: GPUI reports focus only on an element with a
        // role, and otherwise falls back to the window.
        div()
            .id("table")
            .test_support()
            .role(role)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            // The counts cover every row, not just the rendered ones, plus
            // the header row.
            .aria_row_count(rows_count + 1)
            .aria_column_count(columns_count)
            .size_full()
            .key_context(CONTEXT)
            .track_focus(&focus_handle)
            .on_action(window.listener_for(&self.state, TableState::action_cancel))
            .on_action(window.listener_for(&self.state, TableState::action_select_next))
            .on_action(window.listener_for(&self.state, TableState::action_select_prev))
            .on_action(window.listener_for(&self.state, TableState::action_select_next_col))
            .on_action(window.listener_for(&self.state, TableState::action_select_prev_col))
            .on_action(window.listener_for(&self.state, TableState::action_select_first_column))
            .on_action(window.listener_for(&self.state, TableState::action_select_last_column))
            .on_action(window.listener_for(&self.state, TableState::action_select_page_up))
            .on_action(window.listener_for(&self.state, TableState::action_select_page_down))
            .bg(cx.theme().tokens.table)
            .when(bordered, |this| {
                this.rounded(cx.theme().radius)
                    .border_1()
                    .border_color(cx.theme().border)
            })
            .child(self.state)
            // Clicking a row focuses the table too, so only keyboard focus
            // shows it, as CSS `:focus-visible` does.
            .when(
                focus_ring_enabled
                    && focus_handle.is_focused(window)
                    && window.last_input_was_keyboard(),
                |this| this.focus_ring_style(window, cx),
            )
    }
}

#[cfg(test)]
mod tests {
    use gpui::{
        AppContext as _, Context, Entity, Render, TestAppContext, VisualTestContext, Window, div,
        px,
    };

    use super::*;
    use crate::{
        FocusableExt as _,
        table::{Column, TableState},
    };

    struct RowsDelegate;

    impl TableDelegate for RowsDelegate {
        fn columns_count(&self, _: &App) -> usize {
            1
        }
        fn rows_count(&self, _: &App) -> usize {
            3
        }
        fn column(&self, _: usize, _: &App) -> Column {
            Column::new("name", "Name")
        }
        fn render_td(
            &mut self,
            row: usize,
            _: usize,
            _: &mut Window,
            _: &mut Context<TableState<Self>>,
        ) -> impl IntoElement {
            div().child(row.to_string())
        }
    }

    struct FocusRingHarness {
        state: Entity<TableState<RowsDelegate>>,
        focus_ring: bool,
    }

    impl Render for FocusRingHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(240.))
                .h(px(160.))
                .child(DataTable::new(&self.state).focus_ring(self.focus_ring))
        }
    }

    /// Focuses the table and moves the selection with the keyboard, the way
    /// a user arriving with up/down sees the ring.
    fn keyboard_focused_table(cx: &mut TestAppContext, focus_ring: bool) -> &mut VisualTestContext {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(move |window, cx| FocusRingHarness {
            state: cx.new(|cx| TableState::new(RowsDelegate, window, cx)),
            focus_ring,
        });
        let state = view.read_with(cx, |view, _| view.state.clone());
        cx.update(|window, cx| {
            let handle = state.focus_handle(cx);
            window.focus(&handle, cx);
        });
        cx.simulate_keystrokes("down");
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx
    }

    #[gpui::test]
    fn test_data_table_builder(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|window, cx| FocusRingHarness {
            state: cx.new(|cx| TableState::new(RowsDelegate, window, cx)),
            focus_ring: true,
        });
        let state = view.read_with(cx, |view, _| view.state.clone());
        assert!(DataTable::new(&state).is_focus_ring_enabled());

        let table = DataTable::new(&state)
            .stripe(true)
            .bordered(false)
            .scroll_bounce(false)
            .header_row_height(px(32.))
            .fixed_cols_border(false)
            .scrollbar_visible(false, true)
            .with_size(Size::Small)
            .focus_ring(false);
        assert!(table.options.stripe);
        assert!(!table.options.bordered);
        assert_eq!(table.options.scroll_bounce, Some(false));
        assert_eq!(table.options.header_row_height, Some(px(32.)));
        assert!(!table.options.fixed_cols_border);
        assert!(!table.options.scrollbar_visible.right);
        assert!(table.options.scrollbar_visible.bottom);
        assert_eq!(table.options.size, Size::Small);
        assert!(!table.is_focus_ring_enabled());
        assert!(table.focus_ring(true).is_focus_ring_enabled());
    }

    #[gpui::test]
    fn data_table_draws_the_focus_ring_by_default(cx: &mut TestAppContext) {
        let cx = keyboard_focused_table(cx, true);
        assert!(
            cx.debug_bounds("focus-ring").is_some(),
            "a keyboard-focused table draws its focus ring"
        );
    }

    #[gpui::test]
    fn data_table_focus_ring_can_be_turned_off(cx: &mut TestAppContext) {
        let cx = keyboard_focused_table(cx, false);
        assert!(
            cx.debug_bounds("focus-ring").is_none(),
            "`focus_ring(false)` must not draw a ring"
        );
    }
}
