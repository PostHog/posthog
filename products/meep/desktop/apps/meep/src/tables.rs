use super::*;
pub(super) use meep_wire::table::{extension, read};

pub(super) fn render(path: &str, bytes: &[u8]) -> Div {
    let table = match read(path, bytes) {
        Ok(t) => t,
        Err(e) => return ui::caption(e.to_string()),
    };
    let shown = &table.rows[..table.rows.len().min(200)];
    let widths: Vec<f32> = table
        .columns
        .iter()
        .enumerate()
        .map(|(i, head)| {
            let longest = shown
                .iter()
                .filter_map(|r| r.get(i))
                .map(|c| c.chars().count() as f32 * 7.8)
                .fold(head.chars().count() as f32 * 7., f32::max);
            longest.clamp(36., 260.) + 12.
        })
        .collect();
    let min_width = px(widths.iter().sum());
    let row = |cells: Vec<String>, header: bool| {
        ui::row()
            .gap_0()
            .min_w(min_width)
            .border_b_1()
            .border_color(ui::ink(18))
            .children(cells.into_iter().zip(&widths).map(|(s, w)| {
                let cell = if header {
                    ui::caption(s).font_weight(FontWeight::MEDIUM)
                } else {
                    div().text_size(px(13.)).child(s)
                };
                cell.flex_grow(1.)
                    .flex_shrink_0()
                    .flex_basis(px(*w))
                    .truncate()
                    .px(px(6.))
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

#[cfg(test)]
mod tests {
    use super::read;
    use anyhow::Result;
    use core::prelude::v1::test;
    #[test]
    fn quoted_csv_keeps_commas_and_newlines_inside_cells() -> Result<()> {
        let table = read("results.csv", b"Name,Note\nRail,\"One, two\nand three\"\n")?;
        assert_eq!(table.columns, ["Name", "Note"]);
        assert_eq!(table.rows[0], ["Rail", "One, two\nand three"]);
        Ok(())
    }
    #[test]
    fn sparse_json_records_share_one_ordered_header() -> Result<()> {
        let t = read("results.json", br#"[{"a":1},{"b":2}]"#)?;
        assert_eq!(t.columns, ["a", "b"]);
        assert_eq!(t.rows, [["1", ""], ["", "2"]]);
        Ok(())
    }
    #[test]
    fn declared_columns_align_short_rows_and_reject_cells_without_a_header() -> Result<()> {
        let t = read(
            "grid.json",
            br#"{"columns":["State","Added by"],"rows":[["Done"],[]]}"#,
        )?;
        assert_eq!(t.rows, [["Done", ""], ["", ""]]);
        assert!(
            read(
                "bad.json",
                br#"{"columns":["State"],"rows":[["Done","Inbox"]]}"#
            )
            .is_err()
        );
        Ok(())
    }
}
