//! A fixed header and a uniform native row list. No script work for stock cells.
use super::*;
use crate::datasets::{Table, display};

#[derive(Clone)]
enum Item {
    Group(Value, usize),
    Row(usize),
}
/// What every row of one table shares.
struct RowSpec {
    columns: Vec<Value>,
    props: Value,
    /// The table's key, the prefix of its row and group IDs.
    base: String,
}
/// A table's items for one dataset generation and query.
pub(super) struct Rows {
    generation: u64,
    /// The props that decide the items: query, groupBy and collapsed.
    spec: (Value, Value, Value),
    items: Rc<Vec<Item>>,
    /// The selected key and its item index.
    selected: Option<(Value, Option<usize>)>,
}
impl Build {
    /// The items for a table node, reusing the last ones while nothing they
    /// depend on changed. Errors are not cached.
    fn table_items(
        &self,
        key: &str,
        table: &Table,
        p: &Value,
    ) -> Result<(Rc<Vec<Item>>, Option<usize>), String> {
        let mut cache = self.shared.tables.borrow_mut();
        let fresh = cache.get(key).is_some_and(|rows| {
            rows.generation == table.generation
                && rows.spec.0 == p["query"]
                && rows.spec.1 == p["groupBy"]
                && rows.spec.2 == p["collapsed"]
        });
        if !fresh {
            let items = Rc::new(table_items(table, p)?);
            self.shared.perf.borrow_mut().table_queries += 1;
            cache.insert(
                key.to_owned(),
                Rows {
                    generation: table.generation,
                    spec: (
                        p["query"].clone(),
                        p["groupBy"].clone(),
                        p["collapsed"].clone(),
                    ),
                    items,
                    selected: None,
                },
            );
        }
        let rows = cache.get_mut(key).expect("just cached");
        let selected = &p["selected"];
        let index = match &rows.selected {
            Some((value, index)) if value == selected => *index,
            _ => {
                let index = table.position(selected).and_then(|row| {
                    let index = rows
                        .items
                        .iter()
                        .position(|item| matches!(item, Item::Row(i) if *i == row))?;
                    Some(
                        if index > 0 && matches!(rows.items[index - 1], Item::Group(_, _)) {
                            index - 1
                        } else {
                            index
                        },
                    )
                });
                rows.selected = Some((selected.clone(), index));
                index
            }
        };
        Ok((rows.items.clone(), index))
    }
    pub(super) fn table(&self, node: &Node, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        let name = text(p, "data");
        let table = match self.shared.engine.data.borrow_mut().table(&name) {
            Ok(t) => t,
            Err(e) => return ui::error(e).into_any_element(),
        };
        let key = node.key.to_string();
        let (items, selected) = match self.table_items(&key, &table, p) {
            Ok(items) => items,
            Err(e) => return ui::error(e).into_any_element(),
        };
        let generation = table.generation;
        drop(table);
        let columns = p["columns"].as_array().cloned().unwrap_or_default();
        let mut header = ui::row()
            .gap(px(0.))
            .h(px(32.))
            .flex_shrink_0()
            .border_b_1()
            .border_color(rgb(ui::theme::color(ui::RULE)));
        for column in &columns {
            let field = text(column, "field");
            let mut cell = column_box(column)
                .id(ElementId::Name(format!("{key}-sort-{field}").into()))
                .text_size(px(ui::SMALL))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(text(column, "title"));
            if let Some(h) = handler(p, "onSort") {
                let current = p["query"]["sort"].as_array().and_then(|s| s.first());
                let desc = current.is_some_and(|s| s["field"] == field && s["dir"] == "asc");
                let send = self.send(
                    h,
                    json!({"field":field,"dir":if desc {"desc"} else {"asc"}}),
                );
                cell = cell.cursor_pointer().on_click(move |_, _, cx| send(cx));
            }
            header = header.child(cell);
        }
        let mut outer = ui::column()
            .gap(px(0.))
            .w_full()
            .h_full()
            .flex_1()
            .min_h_0()
            .min_w_0()
            .child(header);
        if items.is_empty() {
            return outer
                .child(ui::empty(p["empty"].as_str().unwrap_or("No rows"), ""))
                .into_any_element();
        }
        let scroll = self
            .shared
            .scrolls
            .borrow_mut()
            .entry(key.clone())
            .or_insert_with(|| (UniformListScrollHandle::new(), None))
            .0
            .clone();
        if let Some(index) = selected {
            // Explicit selection changes reveal the selected row, with no JS on scroll.
            let mut handles = self.shared.scrolls.borrow_mut();
            let slot = handles.get_mut(&key).unwrap();
            if slot.1 != Some(index as u64) {
                scroll.scroll_to_item(index, ScrollStrategy::Nearest);
                slot.1 = Some(index as u64);
            }
        }
        // A table's rows are picked and clicked, so text in its cells
        // stays a label unless a cell asks to be selectable.
        let build = Build {
            inputs: Rc::default(),
            control: true,
            ..self.clone()
        };
        let spec = RowSpec {
            columns,
            props: p.clone(),
            base: key.clone(),
        };
        outer = outer.child(
            uniform_list(
                ElementId::Name(key.into()),
                items.len(),
                move |range, window, cx| {
                    // Read the dataset now rather than holding it, so a later
                    // change edits it in place instead of copying it.
                    let table = build.shared.engine.data.borrow_mut().table(&name).ok();
                    let Some(table) = table.filter(|t| t.generation == generation) else {
                        // The dataset changed after this build; its next one shows it.
                        return range.map(|_| div().into_any_element()).collect();
                    };
                    range
                        .map(|i| build.table_row(&table, &items[i], &spec, window, cx))
                        .collect::<Vec<_>>()
                },
            )
            .track_scroll(&scroll)
            .w_full()
            .flex_1()
            .min_h_0(),
        );
        let _ = (window, cx);
        style(outer, node).into_any_element()
    }
    fn table_row(
        &self,
        table: &Table,
        item: &Item,
        spec: &RowSpec,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let (columns, p, base) = (&spec.columns[..], &spec.props, spec.base.as_str());
        self.shared.perf.borrow_mut().native_rows_built += 1;
        let height = p["rowHeight"].as_f64().unwrap_or(28.).clamp(20., 200.) as f32;
        let row = ui::row()
            .gap(px(0.))
            .h(px(height))
            .w_full()
            .overflow_hidden()
            .border_b_1()
            .border_color(rgb(ui::theme::color(ui::RULE)));
        let i = match item {
            Item::Group(value, count) => {
                let collapsed = p["collapsed"].as_array().is_some_and(|v| v.contains(value));
                let mut row = row
                    .id(ElementId::Name(
                        format!("{base}-group-{}", display(value)).into(),
                    ))
                    .bg(rgb(ui::theme::color(ui::INSET)))
                    .px(px(8.))
                    .text_size(px(ui::SMALL))
                    .child(format!(
                        "{} {} · {count}",
                        if collapsed { "›" } else { "⌄" },
                        display(value)
                    ));
                if let Some(h) = handler(p, "onToggleGroup") {
                    let send = self.send(h, value.clone());
                    row = row.cursor_pointer().on_click(move |_, _, cx| send(cx));
                }
                return row.into_any_element();
            }
            Item::Row(i) => *i,
        };
        let record = &table.rows[i];
        let key = &record[&table.key];
        let mut row = row.id(ElementId::Name(
            format!("{base}-row-{}", display(key)).into(),
        ));
        if key == &p["selected"] {
            row = row.bg(rgb(ui::theme::color(ui::INSET)));
        }
        if let Some(h) = handler(p, "onRowClick") {
            let send = self.send(h, key.clone());
            row = row
                .cursor_pointer()
                .hover(|s| s.bg(rgb(ui::theme::color(ui::INSET))))
                .on_click(move |_, _, cx| send(cx));
        }
        for (c, column) in columns.iter().enumerate() {
            let value = &record[text(column, "field")];
            let cell = if let Some(function) = handler(column, "cell") {
                let cached = self.shared.rows.borrow().get(&(function, i)).cloned();
                let node = cached.map(Ok).unwrap_or_else(|| {
                    let node = ScriptEngine::cell(&self.shared.engine, function, record)?;
                    script::check_tree(&node)?;
                    if contains_input(&node) {
                        return Err("Table custom cells cannot contain text inputs".into());
                    }
                    let path = format!("{base}.{i}.{c}");
                    let node = Node::fragment(node, path, &mut self.shared.memo.borrow_mut())?;
                    self.shared
                        .rows
                        .borrow_mut()
                        .insert((function, i), node.clone());
                    Ok::<_, String>(node)
                });
                match node {
                    Ok(node) => self.node(&node, window, cx),
                    Err(e) => ui::caption(e).into_any_element(),
                }
            } else {
                self.table_cell(
                    value,
                    record,
                    column,
                    &format!("{base}.{i}.{c}"),
                    window,
                    cx,
                )
            };
            row = row.child(column_box(column).child(cell));
        }
        row.into_any_element()
    }
    fn table_cell(
        &self,
        value: &Value,
        row: &Value,
        column: &Value,
        path: &str,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let mut label = display(value);
        let kind = column["kind"].as_str().unwrap_or("text");
        if kind == "text" || kind == "mono" {
            let cell = div().min_w_0().truncate().child(label);
            return if kind == "mono" {
                cell.font_family(ui::mono_font())
                    .text_size(px(11.5))
                    .into_any_element()
            } else {
                cell.into_any_element()
            };
        }
        let mut props = json!({"text":label,"truncate":true});
        let element = match kind {
            "mono" => "mono",
            "badge" => {
                props["color"] = column["colors"][&label].clone();
                "badge"
            }
            "tag" => {
                props["text"] = json!(format!("● {label}"));
                props["color"] = column["colors"][&label].clone();
                "text"
            }
            "number" => {
                if let Some(n) = value.as_f64() {
                    label = if let Some(d) = column["decimals"].as_u64() {
                        format!("{:.*}", (d as usize).min(6), n)
                    } else {
                        label
                    };
                }
                props["text"] = json!(label);
                "text"
            }
            "date" => {
                if let Ok(d) = chrono::DateTime::parse_from_rfc3339(&label) {
                    label = if column["format"] == "relative" {
                        let days = (chrono::Utc::now() - d.with_timezone(&chrono::Utc)).num_days();
                        if days == 0 {
                            "Today".into()
                        } else if days > 0 {
                            format!("{days}d ago")
                        } else {
                            format!("in {}d", -days)
                        }
                    } else {
                        d.format("%b %-d, %Y").to_string()
                    };
                } else if let Ok(d) = chrono::NaiveDate::parse_from_str(&label, "%Y-%m-%d") {
                    label = if column["format"] == "relative" {
                        let days = (chrono::Utc::now().date_naive() - d).num_days();
                        if days == 0 {
                            "Today".into()
                        } else if days > 0 {
                            format!("{days}d ago")
                        } else {
                            format!("in {}d", -days)
                        }
                    } else {
                        d.format("%b %-d, %Y").to_string()
                    };
                }
                props["text"] = json!(label);
                "text"
            }
            "link" => {
                props["url"] = column["urlField"]
                    .as_str()
                    .map(|f| row[f].clone())
                    .unwrap_or_else(|| value.clone());
                "link"
            }
            "progress" => {
                props["value"] = value.clone();
                props["color"] = column["color"].clone();
                "progress"
            }
            "checks" => {
                let n = |k: &str| display(&row[column[k].as_str().unwrap_or(k)]);
                props["text"] = json!(format!(
                    "✓ {}  × {}  ◷ {}",
                    n("ok"),
                    n("fail"),
                    n("pending")
                ));
                "mono"
            }
            _ => "text",
        };
        let cell = json!({"t": element, "p": props, "c": []});
        match Node::fragment(cell, path.to_owned(), &mut self.shared.memo.borrow_mut()) {
            Ok(node) => self.node(&node, window, cx),
            Err(error) => ui::caption(error).into_any_element(),
        }
    }
}
fn column_box(column: &Value) -> Div {
    let mut cell = div()
        .flex()
        .items_center()
        .h_full()
        .min_w_0()
        .overflow_hidden()
        .px(px(8.))
        .text_size(px(ui::BODY));
    if column["grow"] == true {
        cell = cell.flex_1();
    } else {
        cell = cell
            .w(px(
                column["w"].as_f64().unwrap_or(100.).clamp(24., 2000.) as f32
            ))
            .flex_shrink_0();
    }
    match column["align"].as_str() {
        Some("right" | "end") => cell.justify_end(),
        Some("center") => cell.justify_center(),
        _ => cell,
    }
}
fn contains_input(node: &Value) -> bool {
    matches!(node["t"].as_str(), Some("input" | "textarea"))
        || node["c"]
            .as_array()
            .is_some_and(|v| v.iter().any(contains_input))
}

/// A table's items in display order: rows, or group headers and their rows.
fn table_items(table: &Table, p: &Value) -> Result<Vec<Item>, String> {
    let indices = table.indices(&p["query"])?;
    let mut items = Vec::new();
    if let Some(group) = p["groupBy"].as_str() {
        if p["query"]["sort"].as_array().is_none_or(|s| s.is_empty()) {
            let groups = table.groups(group);
            let all = indices.len() == table.rows.len();
            let mut matched = vec![false; table.rows.len()];
            if !all {
                for i in indices {
                    matched[i] = true;
                }
            }
            for (value, rows) in groups.iter() {
                let count = if all {
                    rows.len()
                } else {
                    rows.iter().filter(|i| matched[**i]).count()
                };
                if count == 0 {
                    continue;
                }
                items.push(Item::Group(value.clone(), count));
                if !p["collapsed"].as_array().is_some_and(|v| v.contains(value)) {
                    items.extend(
                        rows.iter()
                            .copied()
                            .filter(|i| all || matched[*i])
                            .map(Item::Row),
                    );
                }
            }
        } else {
            // Preserve first-seen order, including the query's sort order inside groups.
            let mut groups: Vec<(Value, Vec<usize>)> = vec![];
            let mut lookup = HashMap::new();
            for i in indices {
                let value = table.rows[i][group].clone();
                let next = groups.len();
                let g = *lookup.entry(value.to_string()).or_insert(next);
                if g == groups.len() {
                    groups.push((value, vec![]));
                }
                groups[g].1.push(i);
            }
            for (value, rows) in groups {
                items.push(Item::Group(value.clone(), rows.len()));
                if !p["collapsed"]
                    .as_array()
                    .is_some_and(|v| v.contains(&value))
                {
                    items.extend(rows.into_iter().map(Item::Row));
                }
            }
        }
    } else {
        items.extend(indices.into_iter().map(Item::Row));
    }
    Ok(items)
}
