//! The visual editor for one workflow step: the step's own JSON, shown as
//! typed fields. It edits that JSON and nothing else, so the code view and
//! this one always say the same thing, and saving goes through the same path.
use super::*;
use gpui_kit::component::menu::{DropdownMenu, PopupMenuItem};
use gpui_kit::component::switch::Switch;
use meep_ui::gpui_kit::component::input::{InputEvent, InputState};
use meep_ui::settings as kit;
use serde_json::json;
use std::collections::HashMap;

/// Keys that are structure or identity, not settings.
const HIDDEN: [&str; 8] = [
    "id", "kind", "steps", "then", "else", "catch", "branches", "code",
];
/// Settings people look for first, in this order; the rest follow by name.
const ORDER: [&str; 14] = [
    "permit",
    "args",
    "source",
    "tool",
    "arguments",
    "items",
    "condition",
    "concurrency",
    "limit",
    "input",
    "table",
    "operation",
    "patch",
    "body",
];

pub(super) fn kind_name(kind: &str) -> &'static str {
    match kind {
        "source" => "Connection action",
        "cli" => "Command line",
        "map" => "Loop",
        "parallel" => "Parallel branches",
        "if" => "Condition",
        "try" => "Recovery",
        "merge" => "Join",
        "state" => "Save to view state",
        "dataset" => "Dataset",
        "notify" => "Notification",
        "ai" => "AI",
        "agent" => "Agent",
        "expression" => "Data step",
        "command" => "Custom JavaScript",
        _ => "Step",
    }
}

fn label(key: &str) -> String {
    match key {
        "permit" => "Command".into(),
        "args" => "Arguments".into(),
        "source" => "Connection".into(),
        "tool" => "Action".into(),
        "arguments" => "Arguments".into(),
        "items" => "For each item in".into(),
        "concurrency" => "At most at once".into(),
        "limit" => "Up to".into(),
        "input" => "Inputs".into(),
        "patch" => "Changes".into(),
        "body" => "Message".into(),
        "op" => "Check".into(),
        "left" => "Value".into(),
        "right" => "Compared with".into(),
        "default" => "If missing".into(),
        "timeoutMs" | "timeout_ms" => "Timeout (ms)".into(),
        "maxBytes" | "max_bytes" => "Size limit (bytes)".into(),
        _ => super::human_name(key),
    }
}

/// Where a `$ref` reads from, in words.
fn source_of(path: &str, definition: &Value) -> String {
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').collect();
    let rest = |n: usize| parts.get(n..).map(|p| p.join(" › ")).unwrap_or_default();
    let with = |base: String, n: usize| {
        let tail = rest(n);
        if tail.is_empty() {
            base
        } else {
            format!("{base} › {tail}")
        }
    };
    match parts.first().copied() {
        Some("steps") => {
            let id = parts.get(1).copied().unwrap_or("");
            let title = find_step(&definition["steps"], id)
                .and_then(|s| s["title"].as_str())
                .map(str::to_owned)
                .unwrap_or_else(|| super::human_name(id));
            with(title, 2)
        }
        Some("input") => with("Workflow input".into(), 1),
        Some("item") => with("Current item".into(), 1),
        Some("index") => "Item number".into(),
        Some("run") => with("This run".into(), 1),
        Some("error") => with("The error".into(), 1),
        _ => path.to_owned(),
    }
}

fn children(step: &Value) -> usize {
    ["steps", "then", "else", "catch"]
        .iter()
        .filter_map(|k| step[*k].as_array().map(Vec::len))
        .sum::<usize>()
        + step["branches"]
            .as_array()
            .map(|b| {
                b.iter()
                    .filter_map(|b| b["steps"].as_array().map(Vec::len))
                    .sum::<usize>()
            })
            .unwrap_or(0)
}

/// Fields that take one of a few values, with each value in words.
fn choices(key: &str) -> Option<&'static [(&'static str, &'static str)]> {
    match key {
        "operation" => Some(&[
            ("set", "Replace rows"),
            ("patch", "Update rows"),
            ("remove", "Remove rows"),
            ("clear", "Clear the table"),
            ("rows", "Read rows"),
            ("count", "Count rows"),
            ("aggregate", "Summarise rows"),
        ]),
        "op" => Some(&[
            ("eq", "is"),
            ("ne", "is not"),
            ("gt", "is more than"),
            ("gte", "is at least"),
            ("lt", "is less than"),
            ("lte", "is at most"),
            ("truthy", "has a value"),
            ("all", "all of"),
            ("any", "any of"),
            ("not", "not"),
        ]),
        "delivery" => Some(&[
            ("system", "macOS notification"),
            ("inApp", "In View"),
            ("both", "In View and macOS"),
        ]),
        _ => None,
    }
}

/// What kind of value a field holds, so typing keeps its type.
#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Text,
    Number,
}

/// Field editors, keyed by JSON pointer into the step.
#[derive(Default)]
pub(super) struct Form {
    inputs: HashMap<String, (Entity<InputState>, Kind)>,
    subscriptions: Vec<Subscription>,
}

impl Form {
    /// Drops editors after the JSON changed under them (code edits, adding
    /// or removing a list item), so they rebuild from it.
    pub(super) fn reset(&mut self) {
        self.inputs.clear();
        self.subscriptions.clear();
    }
}

/// What the visual editor needs from its host editor.
pub(super) trait Host: Sized + 'static {
    fn form(&mut self) -> &mut Form;
    fn draft(&self, cx: &App) -> Option<Value>;
    fn write(&mut self, step: Value, window: &mut Window, cx: &mut Context<Self>);
    fn definition(&self) -> &Value;
}

fn set(step: &mut Value, pointer: &str, value: Value) {
    if let Some(slot) = step.pointer_mut(pointer) {
        *slot = value;
    } else if let Some((parent, key)) = pointer.rsplit_once('/')
        && let Some(object) = step.pointer_mut(parent).and_then(Value::as_object_mut)
    {
        // A field the step doesn't have yet, such as an untitled step's name.
        object.insert(key.replace("~1", "/").replace("~0", "~"), value);
    }
}

fn input<H: Host>(
    host: &mut H,
    pointer: &str,
    initial: &Value,
    window: &mut Window,
    cx: &mut Context<H>,
) -> Entity<InputState> {
    if let Some((state, _)) = host.form().inputs.get(pointer) {
        return state.clone();
    }
    let kind = if initial.is_number() {
        Kind::Number
    } else {
        Kind::Text
    };
    let text = match initial {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    };
    let state = cx.new(|cx| InputState::new(window, cx).default_value(text));
    let key = pointer.to_owned();
    let subscription = cx.subscribe_in(
        &state,
        window,
        move |host: &mut H, state, event, window, cx| {
            if !matches!(event, InputEvent::Change) {
                return;
            }
            let typed = state.read(cx).value().to_string();
            let Some(mut step) = host.draft(cx) else {
                return;
            };
            let value = match kind {
                // A number field keeps a number; while half-typed it waits.
                Kind::Number => match typed.trim().parse::<f64>() {
                    Ok(n) if n.fract() == 0. && n.abs() < 9e15 => json!(n as i64),
                    Ok(n) => json!(n),
                    Err(_) => return,
                },
                Kind::Text => json!(typed),
            };
            set(&mut step, &key, value);
            host.write(step, window, cx);
        },
    );
    let form = host.form();
    form.inputs
        .insert(pointer.to_owned(), (state.clone(), kind));
    form.subscriptions.push(subscription);
    state
}

fn field(state: &Entity<InputState>, mono: bool, name: &str) -> Div {
    div().w(px(300.)).flex_shrink(1.).min_w(px(140.)).child(
        ui::forms::input(state, name.to_owned())
            .small()
            .h(px(30.))
            .min_h(px(30.))
            .rounded(px(8.))
            .when(mono, |el| el.font_family("Menlo").text_size(px(12.)))
            .aria_label(name.to_owned()),
    )
}

/// The rows for one object's settings.
fn rows<H: Host>(
    host: &mut H,
    object: &serde_json::Map<String, Value>,
    base: &str,
    depth: usize,
    window: &mut Window,
    cx: &mut Context<H>,
) -> (Vec<AnyElement>, Vec<AnyElement>) {
    let mut keys: Vec<&String> = object
        .keys()
        .filter(|k| !HIDDEN.contains(&k.as_str()) && *k != "title")
        .collect();
    keys.sort_by_key(|k| {
        (
            ORDER.iter().position(|o| o == k).unwrap_or(usize::MAX),
            (*k).clone(),
        )
    });
    let mut items: Vec<AnyElement> = vec![];
    // Nested objects become their own sections after this group.
    let mut sections: Vec<AnyElement> = vec![];
    for key in keys {
        let value = &object[key];
        let pointer = format!("{base}/{}", key.replace('~', "~0").replace('/', "~1"));
        let name = label(key);
        match value {
            Value::Bool(on) => {
                let on = *on;
                let p = pointer.clone();
                items.push(
                    kit::item(
                        name.clone(),
                        "",
                        Switch::new(SharedString::from(format!("form{pointer}")))
                            .small()
                            .checked(on)
                            .color(rgb(ui::theme::get(10)))
                            .accessibility_label(name)
                            .on_change(cx.listener(move |host: &mut H, _, window, cx| {
                                if let Some(mut step) = host.draft(cx) {
                                    set(&mut step, &p, json!(!on));
                                    host.write(step, window, cx);
                                }
                            })),
                    )
                    .into_any_element(),
                );
            }
            Value::Object(map) if map.contains_key("$ref") => {
                // A value taken from somewhere else: where it comes from, as
                // a choice of earlier steps, then which part of it.
                let path = map["$ref"].as_str().unwrap_or("").to_owned();
                items.push(
                    // Wide controls: the label keeps room for its word.
                    row()
                        .w_full()
                        .min_h(px(48.))
                        .px(px(kit::ROW_X))
                        .py(px(10.))
                        .gap(px(16.))
                        .child(kit::copy(name.clone(), "").min_w(px(96.)))
                        .child(
                            row()
                                .flex_shrink(1.)
                                .min_w_0()
                                .child(reference(host, &pointer, &path, window, cx)),
                        )
                        .into_any_element(),
                );
                if let Some(default) = map.get("default") {
                    let state = input(host, &format!("{pointer}/default"), default, window, cx);
                    items.push(
                        kit::item(
                            format!("{name} if missing"),
                            "",
                            field(&state, false, &name),
                        )
                        .into_any_element(),
                    );
                }
            }
            Value::Object(map) if depth < 2 => {
                let (inner, deeper) = rows(host, map, &pointer, depth + 1, window, cx);
                if !inner.is_empty() {
                    sections.push(kit::section(name, "", None, false).into_any_element());
                    sections.push(kit::group(inner).into_any_element());
                }
                sections.extend(deeper);
            }
            Value::Array(list) if list.iter().all(|v| !v.is_object() && !v.is_array()) => {
                // A list of plain values: one field per item, add and remove.
                let mut entries: Vec<AnyElement> = vec![];
                for (index, item) in list.iter().enumerate() {
                    let state = input(host, &format!("{pointer}/{index}"), item, window, cx);
                    let p = pointer.clone();
                    entries.push(
                        row()
                            .w_full()
                            .min_h(px(44.))
                            .px(px(kit::ROW_X))
                            .gap(px(10.))
                            .child(
                                text(format!("{}", index + 1))
                                    .w(px(18.))
                                    .text_size(px(12.))
                                    .text_color(rgb(ui::theme::get(2))),
                            )
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .child(field(&state, true, &name).w_full()),
                            )
                            .child(
                                ui::icon_button(
                                    SharedString::from(format!("form-remove{pointer}/{index}")),
                                    Glyph::X,
                                    "Remove",
                                )
                                .on_click(cx.listener(
                                    move |host: &mut H, _, window, cx| {
                                        if let Some(mut step) = host.draft(cx) {
                                            if let Some(list) =
                                                step.pointer_mut(&p).and_then(Value::as_array_mut)
                                            {
                                                list.remove(index);
                                            }
                                            host.form().reset();
                                            host.write(step, window, cx);
                                        }
                                    },
                                )),
                            )
                            .into_any_element(),
                    );
                }
                let p = pointer.clone();
                let add = kit::pill(SharedString::from(format!("form-add{pointer}")), "Add", cx)
                    .icon(Icon::new(Glyph::Plus).size(px(12.)))
                    .on_click(cx.listener(move |host: &mut H, _, window, cx| {
                        if let Some(mut step) = host.draft(cx) {
                            if let Some(list) = step.pointer_mut(&p).and_then(Value::as_array_mut) {
                                list.push(json!(""));
                            }
                            host.form().reset();
                            host.write(step, window, cx);
                        }
                    }));
                sections.push(
                    kit::section(name, "", Some(add.into_any_element()), false).into_any_element(),
                );
                sections.push(if entries.is_empty() {
                    kit::empty("Nothing yet", "Add the first one.").into_any_element()
                } else {
                    kit::group(entries).into_any_element()
                });
            }
            Value::Array(_) | Value::Object(_) => {
                items.push(
                    kit::item(name, "Structured value · edit in Code", div()).into_any_element(),
                );
            }
            Value::String(current) if choices(key).is_some() => {
                let options = choices(key).unwrap_or(&[]);
                let shown = options
                    .iter()
                    .find(|(v, _)| *v == current)
                    .map(|(_, words)| (*words).to_owned())
                    .unwrap_or_else(|| current.clone());
                let owner = cx.entity().downgrade();
                let p = pointer.clone();
                items.push(
                    kit::item(
                        name.clone(),
                        "",
                        kit::menu_pill(
                            SharedString::from(format!("form-choice{pointer}")),
                            shown,
                            cx,
                        )
                        .dropdown_menu(move |mut menu, _, _| {
                            for (value, words) in options {
                                let owner = owner.clone();
                                let p = p.clone();
                                menu = menu.item(PopupMenuItem::new(*words).on_click(
                                    move |_, window, cx| {
                                        let _ = owner.update(cx, |host: &mut H, cx| {
                                            if let Some(mut step) = host.draft(cx) {
                                                set(&mut step, &p, json!(value));
                                                host.write(step, window, cx);
                                            }
                                        });
                                    },
                                ));
                            }
                            menu
                        }),
                    )
                    .into_any_element(),
                );
            }
            Value::Null | Value::String(_) | Value::Number(_) => {
                let state = input(host, &pointer, value, window, cx);
                items.push(
                    kit::item(name.clone(), "", field(&state, false, &name)).into_any_element(),
                );
            }
        }
    }
    (items, sections)
}

/// The visual editor for the step in `host`'s draft.
pub(super) fn render<H: Host>(host: &mut H, window: &mut Window, cx: &mut Context<H>) -> Div {
    let Some(step) = host.draft(cx) else {
        return col().w_full().child(kit::empty(
            "This step's JSON has an error",
            "Fix it in Code; the visual editor opens again once it's valid.",
        ));
    };
    let Some(object) = step.as_object().cloned() else {
        return col().w_full().child(kit::empty(
            "Nothing to edit here",
            "Use Code for this step.",
        ));
    };
    let kind = object.get("kind").and_then(Value::as_str).unwrap_or("");
    let title = input(
        host,
        "/title",
        object.get("title").unwrap_or(&Value::Null),
        window,
        cx,
    );
    let mut identity = vec![
        kit::item("Name", "", field(&title, false, "Step name")).into_any_element(),
        kit::item("Kind", "", kit::value_text(kind_name(kind))).into_any_element(),
    ];
    let nested = children(&step);
    if nested > 0 {
        identity.push(
            kit::item(
                "Contains",
                "Edit those steps from the workflow outline.",
                kit::value_text(format!(
                    "{nested} {}",
                    if nested == 1 { "step" } else { "steps" }
                )),
            )
            .into_any_element(),
        );
    }
    let (settings, sections) = rows(host, &object, "", 0, window, cx);
    col()
        .w_full()
        .child(kit::section("Step", "", None, true))
        .child(kit::group(identity))
        .when(!settings.is_empty(), |el| {
            el.child(kit::section("Settings", "", None, false))
                .child(kit::group(settings))
        })
        .children(sections)
}

/// Every step a value could come from, in the order they appear.
fn steps_in(steps: &Value, out: &mut Vec<(String, String)>) {
    for step in steps.as_array().into_iter().flatten() {
        let id = step["id"].as_str().unwrap_or("").to_owned();
        let title = step["title"]
            .as_str()
            .filter(|t| !t.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| super::human_name(&id));
        out.push((id, title));
        for key in ["steps", "then", "else", "catch"] {
            steps_in(&step[key], out);
        }
        for branch in step["branches"].as_array().into_iter().flatten() {
            steps_in(&branch["steps"], out);
        }
    }
}

/// Splits a reference into where it reads from and the part it reads:
/// "/steps/project/prs" → ("/steps/project", "prs").
fn split_ref(path: &str) -> (String, String) {
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').collect();
    let root = if parts.first() == Some(&"steps") {
        2
    } else {
        1
    };
    let base = format!("/{}", parts[..root.min(parts.len())].join("/"));
    let rest = parts.get(root..).map(|p| p.join("/")).unwrap_or_default();
    (base, rest)
}

/// "From [step ▾] · [field]".
fn reference<H: Host>(
    host: &mut H,
    pointer: &str,
    path: &str,
    window: &mut Window,
    cx: &mut Context<H>,
) -> Div {
    let (base, rest) = split_ref(path);
    let definition = host.definition().clone();
    let current = source_of(&base, &definition);
    let mut choices: Vec<(String, String)> = vec![
        ("/input".into(), "Workflow input".into()),
        ("/item".into(), "Current item".into()),
    ];
    let mut steps = vec![];
    steps_in(&definition["steps"], &mut steps);
    choices.extend(
        steps
            .into_iter()
            .map(|(id, title)| (format!("/steps/{id}"), title)),
    );
    let owner = cx.entity().downgrade();
    let target = format!("{pointer}/$ref");
    let rest_for_menu = rest.clone();
    let picker = kit::menu_pill(
        SharedString::from(format!("form-ref{pointer}")),
        current,
        cx,
    )
    .max_w(px(240.))
    .dropdown_menu(move |mut menu, _, _| {
        for (value, title) in &choices {
            let owner = owner.clone();
            let target = target.clone();
            let value = value.clone();
            let rest = rest_for_menu.clone();
            menu = menu.item(
                PopupMenuItem::new(title.clone()).on_click(move |_, window, cx| {
                    let _ = owner.update(cx, |host, cx| {
                        if let Some(mut step) = host.draft(cx) {
                            let path = if rest.is_empty() {
                                value.clone()
                            } else {
                                format!("{value}/{rest}")
                            };
                            set(&mut step, &target, json!(path));
                            host.form().reset();
                            host.write(step, window, cx);
                        }
                    });
                }),
            );
        }
        menu
    });
    // The part of it, edited as text; a whole value has none.
    let target = format!("{pointer}/$ref");
    let part_key = format!("{pointer}/$ref#part");
    let state = match host.form().inputs.get(&part_key) {
        Some((state, _)) => state.clone(),
        None => {
            let state = cx.new(|cx| {
                InputState::new(window, cx)
                    .placeholder("whole value")
                    .default_value(rest.clone())
            });
            let base = base.clone();
            let subscription = cx.subscribe_in(
                &state,
                window,
                move |host: &mut H, state, event, window, cx| {
                    if !matches!(event, InputEvent::Change) {
                        return;
                    }
                    let part = state.read(cx).value().trim().trim_matches('/').to_owned();
                    let path = if part.is_empty() {
                        base.clone()
                    } else {
                        format!("{base}/{part}")
                    };
                    if let Some(mut step) = host.draft(cx) {
                        set(&mut step, &target, json!(path));
                        host.write(step, window, cx);
                    }
                },
            );
            let form = host.form();
            form.inputs.insert(part_key, (state.clone(), Kind::Text));
            form.subscriptions.push(subscription);
            state
        }
    };
    row()
        .min_w_0()
        .gap(px(8.))
        .child(
            div()
                .min_w(px(90.))
                .max_w(px(240.))
                .flex_shrink(1.)
                .child(picker),
        )
        .child(
            text("›")
                .flex_none()
                .text_size(px(13.))
                .text_color(rgb(ui::theme::get(2))),
        )
        .child(
            div().w(px(130.)).flex_shrink(1.).min_w(px(72.)).child(
                ui::forms::input(&state, "Field")
                    .small()
                    .h(px(30.))
                    .min_h(px(30.))
                    .rounded(px(8.))
                    .font_family("Menlo")
                    .text_size(px(12.))
                    .aria_label("Field"),
            ),
        )
}
