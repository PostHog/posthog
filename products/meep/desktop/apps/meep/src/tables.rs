use super::*;
pub(super) use meep_wire::table::{extension, read};

pub(super) fn tabular(path: &str) -> bool {
    matches!(extension(path).as_str(), "json" | "csv" | "tsv")
}
pub(super) fn render(path: &str, bytes: &[u8]) -> Div {
    let table = match read(path, bytes) {
        Ok(t) => t,
        Err(e) => return ui::caption(e.to_string()),
    };
    let min_width = px(110. * table.columns.len() as f32);
    let row = |cells: Vec<String>, header: bool| {
        ui::row()
            .gap_0()
            .min_w(min_width)
            .border_b_1()
            .border_color(ui::ink(18))
            .children(cells.into_iter().map(|s| {
                let cell = if header {
                    ui::caption(s).font_weight(FontWeight::MEDIUM)
                } else {
                    div().child(s)
                };
                cell.flex_1()
                    .min_w(px(110.))
                    .truncate()
                    .px(px(8.))
                    .py(px(7.))
            }))
    };
    let n = table.rows.len();
    let grid = ui::column()
        .gap_0()
        .min_w(min_width)
        .child(row(table.columns, true))
        .children(
            table
                .rows
                .into_iter()
                .take(200)
                .map(|cells| row(cells, false)),
        );
    ui::column()
        .child(div().id("table-grid").overflow_x_scroll().child(grid))
        .when(n > 200, |e| {
            e.child(ui::caption("Showing the first 200 rows."))
        })
}
