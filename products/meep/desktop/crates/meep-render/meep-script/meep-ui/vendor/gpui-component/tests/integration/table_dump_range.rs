#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use std::{cell::Cell, rc::Rc};

use gpui::{App, Context, IntoElement, TestAppContext, Window, div};
use gpui_component::table::{Column, TableDelegate, TableState};

struct DumpDelegate {
    rows: usize,
    columns: usize,
    cell_text_calls: Rc<Cell<usize>>,
}

impl TableDelegate for DumpDelegate {
    fn columns_count(&self, _: &App) -> usize {
        self.columns
    }

    fn rows_count(&self, _: &App) -> usize {
        self.rows
    }

    fn column(&self, col_ix: usize, _: &App) -> Column {
        let name = format!("column-{col_ix}");
        Column::new(name.clone(), name)
    }

    fn render_td(
        &mut self,
        _: usize,
        _: usize,
        _: &mut Window,
        _: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        div()
    }

    fn cell_text(&self, row_ix: usize, col_ix: usize, _: &App) -> String {
        self.cell_text_calls.set(self.cell_text_calls.get() + 1);
        format!("row-{row_ix}-column-{col_ix}")
    }
}

fn new_table(
    cx: &mut TestAppContext,
    rows: usize,
    columns: usize,
) -> (
    gpui::WindowHandle<TableState<DumpDelegate>>,
    Rc<Cell<usize>>,
) {
    cx.skip_drawing();
    let cell_text_calls = Rc::new(Cell::new(0));
    let delegate_calls = cell_text_calls.clone();
    let window = cx.add_window(move |window, cx| {
        TableState::new(
            DumpDelegate {
                rows,
                columns,
                cell_text_calls: delegate_calls,
            },
            window,
            cx,
        )
    });
    (window, cell_text_calls)
}

#[gpui::test]
fn dump_range_clamps_and_only_materializes_requested_rows(cx: &mut TestAppContext) {
    let (window, cell_text_calls) = new_table(cx, 100, 2);

    let (headers, rows) = window
        .update(cx, |table, _, cx| table.dump_range(98..103, cx))
        .unwrap();

    assert_eq!(headers, ["column-0", "column-1"]);
    assert_eq!(
        rows,
        [
            ["row-98-column-0", "row-98-column-1"],
            ["row-99-column-0", "row-99-column-1"],
        ]
    );
    assert_eq!(cell_text_calls.get(), 4);
}

#[gpui::test]
fn dump_still_materializes_the_complete_table(cx: &mut TestAppContext) {
    let (window, cell_text_calls) = new_table(cx, 3, 2);

    let (headers, rows) = window.update(cx, |table, _, cx| table.dump(cx)).unwrap();

    assert_eq!(headers, ["column-0", "column-1"]);
    assert_eq!(
        rows,
        [
            ["row-0-column-0", "row-0-column-1"],
            ["row-1-column-0", "row-1-column-1"],
            ["row-2-column-0", "row-2-column-1"],
        ]
    );
    assert_eq!(cell_text_calls.get(), 6);
}
