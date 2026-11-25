//! Retained native source editor. Drafts are local until validated/CAS-saved.
use super::*;
use gpui_kit::component::input::{Editor, EditorState, InputEvent};
use std::rc::Rc;

use meep_ui::controls::{Unavailable as _, quiet_button};
use meep_ui::gpui_kit::component::button::Button;
use serde_json::json;
use std::{future::Future, pin::Pin};
fn label(s: impl Into<SharedString>) -> Div {
    ui::caption(s)
}
fn code(s: impl Into<SharedString>) -> Div {
    text(s)
        .font_family("Menlo")
        .text_size(px(11.))
        .text_color(rgb(ui::theme::get(1)))
}
fn back_button(id: &'static str, parent: &'static str, cx: &App) -> Button {
    quiet_button(id, cx)
        .small()
        .h(px(ui::CONTROL))
        .icon(Icon::new(Glyph::ChevronLeft).size(px(14.)))
        .label(parent)
        .self_start()
        .ml(px(-ui::GHOST_INSET))
}
#[derive(Clone)]
pub enum Target {
    Definition,
    Step(String),
    Script,
    Run { input: Value, required: Vec<String> },
}
/// Start from declared binding defaults and expose inputs that callers normally
/// supply. This is input configuration, not a second workflow definition.
pub fn run_input(definition: &Value) -> (Value, Vec<String>) {
    fn literal(value: &Value) -> bool {
        match value {
            Value::Object(map) => !map.contains_key("$ref") && map.values().all(literal),
            Value::Array(array) => array.iter().all(literal),
            _ => true,
        }
    }
    fn collect(value: &Value, paths: &mut std::collections::BTreeMap<String, Option<Value>>) {
        match value {
            Value::Object(map) => {
                if let Some(reference) = map.get("$ref").and_then(Value::as_str)
                    && (reference == "/input" || reference.starts_with("/input/"))
                {
                    let path = reference.trim_start_matches("/input").to_owned();
                    let default = map.get("default").cloned();
                    paths
                        .entry(path)
                        .and_modify(|old| {
                            if default.is_none() {
                                *old = None;
                            }
                        })
                        .or_insert(default);
                }
                for value in map.values() {
                    collect(value, paths);
                }
            }
            Value::Array(array) => {
                for value in array {
                    collect(value, paths);
                }
            }
            _ => {}
        }
    }
    let mut paths = std::collections::BTreeMap::new();
    collect(&definition["steps"], &mut paths);
    if let Some(result) = definition.get("result") {
        collect(result, &mut paths);
    }
    let mut input = json!({});
    let mut required = vec![];
    for (path, default) in paths {
        if default.is_none() {
            required.push(path.clone());
        }
        let value = match default {
            Some(value) if literal(&value) => value,
            Some(_) => continue,
            None => Value::Null,
        };
        if path.is_empty() {
            if !value.is_null() {
                input = value;
            }
            continue;
        }
        let parts = path[1..]
            .split('/')
            .map(|part| part.replace("~1", "/").replace("~0", "~"))
            .collect::<Vec<_>>();
        let mut node = &mut input;
        for (index, part) in parts.iter().enumerate() {
            if !node.is_object() {
                *node = json!({});
            }
            if index + 1 == parts.len() {
                node.as_object_mut()
                    .unwrap()
                    .insert(part.clone(), value.clone());
            } else {
                node = node
                    .as_object_mut()
                    .unwrap()
                    .entry(part.clone())
                    .or_insert_with(|| json!({}));
            }
        }
    }
    (input, required)
}
pub type Close = Rc<dyn Fn(&mut App)>;
pub enum Request {
    ReadScript,
    WriteScript {
        expected_revision: String,
        source: String,
    },
    Preview {
        code: String,
        input: Value,
    },
    Run {
        id: String,
        input: Value,
    },
    Save {
        expected: Value,
        definition: Value,
    },
}
pub type Reply = Pin<Box<dyn Future<Output = Result<Value, String>>>>;
pub type Handler = Rc<dyn Fn(Request, &App) -> Reply>;
pub struct CodeEditor {
    handler: Handler,
    definition: Value,
    target: Target,
    source: Entity<EditorState>,
    sample: Entity<EditorState>,
    original: String,
    revision: String,
    error: Option<String>,
    output: Option<String>,
    pending: bool,
    loading: bool,
    expression: bool,
    show_preview: bool,
    /// Visual step editor instead of the JSON, for ordinary steps.
    visual: bool,
    form: super::workflow_form::Form,
    on_close: Close,
    _subscriptions: Vec<Subscription>,
}
pub(super) fn step_path(def: &Value, id: &str) -> Option<String> {
    fn walk(list: &Value, path: &str, id: &str) -> Option<String> {
        for (i, step) in list.as_array()?.iter().enumerate() {
            let p = format!("{path}/{i}");
            if step["id"] == id {
                return Some(p);
            }
            for key in ["steps", "then", "else", "catch"] {
                if let Some(found) = walk(&step[key], &format!("{p}/{key}"), id) {
                    return Some(found);
                }
            }
            for (i, b) in step["branches"]
                .as_array()
                .into_iter()
                .flatten()
                .enumerate()
            {
                if let Some(found) = walk(&b["steps"], &format!("{p}/branches/{i}/steps"), id) {
                    return Some(found);
                }
            }
        }
        None
    }
    walk(&def["steps"], "/steps", id)
}
impl CodeEditor {
    pub fn new(
        handler: Handler,
        source_definition: Value,
        target: Target,
        on_close: Close,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Self {
        let definition = &source_definition;
        let step = if let Target::Step(id) = &target {
            step_path(definition, id)
                .and_then(|p| definition.pointer(&p))
                .cloned()
                .unwrap_or_default()
        } else {
            Value::Null
        };
        let expression = step["kind"] == "expression";
        let script = matches!(target, Target::Script);
        let original = if let Target::Run { input, .. } = &target {
            serde_json::to_string_pretty(input).unwrap_or_default()
        } else if script {
            String::new()
        } else if expression {
            // Agents write dense one-liners; open them up for reading. Only
            // whitespace changes, so this is the same expression.
            super::rhai_format::readable(step["code"].as_str().unwrap_or(""))
        } else {
            serde_json::to_string_pretty(if matches!(target, Target::Step(_)) {
                &step
            } else {
                definition
            })
            .unwrap_or_default()
        };
        let language = if expression {
            "rust"
        } else if script {
            "javascript"
        } else {
            "json"
        };
        let source = cx.new(|cx| {
            EditorState::new(window, cx)
                .language(language)
                .soft_wrap(false)
                .default_value(original.clone())
        });
        // The sample starts with the names this step is given, so the shape
        // is clear and only the values need filling in.
        let sample_value = match step["input"].as_object() {
            Some(bindings) if expression && !bindings.is_empty() => serde_json::to_string_pretty(
                &bindings
                    .keys()
                    .map(|k| (k.clone(), Value::Null))
                    .collect::<serde_json::Map<String, Value>>(),
            )
            .unwrap_or_else(|_| "{}".into()),
            _ => "{}".into(),
        };
        let sample = cx.new(|cx| {
            EditorState::new(window, cx)
                .language("json")
                .default_value(sample_value)
        });
        let target_kind = matches!(target, Target::Step(_)).then_some(!expression);
        let mut subscriptions = vec![];
        for input in [&source, &sample] {
            subscriptions.push(cx.subscribe(input, |v, _, e, cx| {
                if matches!(e, InputEvent::Change) {
                    v.error = None;
                    v.output = None;
                    cx.notify();
                }
            }));
        }
        let mut editor = Self {
            handler,
            definition: source_definition,
            target,
            source,
            sample,
            original,
            revision: String::new(),
            error: None,
            output: None,
            pending: false,
            loading: script,
            expression,
            show_preview: false,
            visual: matches!(target_kind, Some(true)),
            form: Default::default(),
            on_close,
            _subscriptions: subscriptions,
        };
        if script {
            editor.load_script(window, cx);
        }
        editor
    }
    fn load_script(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let rx = (self.handler)(Request::ReadScript, cx);
        let handle = window.window_handle();
        cx.spawn(async move |this, cx| {
            let result = rx.await;
            let _ = cx.update_window(handle, |_, window, cx| {
                this.update(cx, |v, cx| {
                    v.loading = false;
                    match result {
                        Ok(value) => {
                            v.original = value["code"].as_str().unwrap_or("").into();
                            v.revision = value["revision"].as_str().unwrap_or("").into();
                            let text = v.original.clone();
                            v.source.update(cx, |s, cx| s.set_value(text, window, cx));
                        }
                        Err(e) => v.error = Some(e),
                    }
                    cx.notify();
                })
            });
        })
        .detach();
    }
    /// The bindings this expression step reads, as `input.name`.
    fn step_inputs(&self) -> Vec<String> {
        let Target::Step(id) = &self.target else {
            return vec![];
        };
        let definition = &self.definition;
        step_path(definition, id)
            .and_then(|p| definition.pointer(&p))
            .and_then(|step| step["input"].as_object())
            .map(|bindings| bindings.keys().cloned().collect())
            .unwrap_or_default()
    }
    /// A preview that read a value the sample doesn't have says which one,
    /// not the engine's "getter is not registered for type '()'".
    fn explain_preview_error(&self, error: String, cx: &App) -> String {
        if !error.contains("type '()'") && !error.contains("type \"()\"") {
            return error;
        }
        let sample =
            serde_json::from_str::<Value>(&self.sample.read(cx).value()).unwrap_or_default();
        let empty: Vec<String> = self
            .step_inputs()
            .into_iter()
            .filter(|name| sample.get(name).is_none_or(Value::is_null))
            .map(|name| format!("input.{name}"))
            .collect();
        let detail = error.lines().next().unwrap_or_default();
        if empty.is_empty() {
            format!("The code read a field of an empty value. Check the sample input.\n{detail}")
        } else {
            format!(
                "The sample has no value for {}. Paste a real one into Sample input (for example, what that step returned), then preview again.\n{detail}",
                empty.join(", ")
            )
        }
    }
    fn preview(&mut self, cx: &mut Context<Self>) {
        let input = match serde_json::from_str::<Value>(&self.sample.read(cx).value()) {
            Ok(v) => v,
            Err(e) => {
                self.error = Some(format!("Sample input: {e}"));
                cx.notify();
                return;
            }
        };
        let source = self.source.read(cx).value().to_string();
        self.pending = true;
        self.error = None;
        self.output = None;
        let rx = (self.handler)(
            Request::Preview {
                code: source,
                input,
            },
            cx,
        );
        cx.spawn(async move |this, cx| {
            let result = rx.await;
            let _ = this.update(cx, |v, cx| {
                v.pending = false;
                match result {
                    Ok(output) => {
                        let pretty =
                            serde_json::to_string_pretty(&output["value"]).unwrap_or_default();
                        let preview: String = pretty.chars().take(32000).collect();
                        v.output = Some(format!(
                            "{} µs · {} operations\n{}{}",
                            output["elapsedUs"],
                            output["operations"],
                            preview,
                            if preview.len() < pretty.len() {
                                "\n… preview truncated"
                            } else {
                                ""
                            }
                        ));
                    }
                    Err(e) => v.error = Some(v.explain_preview_error(e, cx)),
                }
                cx.notify();
            });
        })
        .detach();
    }
    fn save(&mut self, cx: &mut Context<Self>) {
        let source = self.source.read(cx).value().to_string();
        let request = match &self.target {
            Target::Run { required, .. } => {
                let input: Value = match serde_json::from_str(&source) {
                    Ok(input) => input,
                    Err(error) => {
                        self.error = Some(format!("Workflow input: {error}"));
                        cx.notify();
                        return;
                    }
                };
                if let Some(path) = required
                    .iter()
                    .find(|path| input.pointer(path).is_none_or(Value::is_null))
                {
                    self.error = Some(format!(
                        "Provide a value for input{}.",
                        if path.is_empty() {
                            String::new()
                        } else {
                            path.clone()
                        }
                    ));
                    cx.notify();
                    return;
                }
                if serde_json::to_vec(&input).unwrap_or_default().len() > 8192 {
                    self.error = Some("Workflow input exceeds 8 KB".into());
                    cx.notify();
                    return;
                }
                Request::Run {
                    id: self.definition["id"]
                        .as_str()
                        .unwrap_or_default()
                        .to_owned(),
                    input,
                }
            }
            Target::Script => Request::WriteScript {
                expected_revision: self.revision.clone(),
                source,
            },
            target => {
                let mut definition = self.definition.clone();
                let updated = (|| -> Result<(), String> {
                    if let Target::Step(id) = target {
                        let path = step_path(&definition, id).ok_or("Step was removed")?;
                        let step = definition.pointer_mut(&path).unwrap();
                        if self.expression {
                            step["code"] = json!(source);
                        } else {
                            let value: Value =
                                serde_json::from_str(&source).map_err(|e| e.to_string())?;
                            if value["id"] != *id {
                                return Err("Keep this step ID; edit the full definition to rename bindings".into());
                            }
                            *step = value;
                        }
                    } else {
                        definition = serde_json::from_str(&source).map_err(|e| e.to_string())?;
                    }
                    meep_workflows::Workflow::parse(definition.clone())
                        .map_err(|e| e.to_string())?;
                    Ok(())
                })();
                if let Err(e) = updated {
                    self.error = Some(e);
                    cx.notify();
                    return;
                }
                Request::Save {
                    expected: self.definition.clone(),
                    definition,
                }
            }
        };
        self.pending = true;
        self.error = None;
        let rx = (self.handler)(request, cx);
        cx.spawn(async move |this, cx| {
            let result = rx.await;
            let close = this
                .update(cx, |v, cx| {
                    v.pending = false;
                    let close = match result {
                        Ok(value) if value.get("applied").is_none_or(|v| v == true) => {
                            Some(v.on_close.clone())
                        }
                        Ok(value) => {
                            v.error = Some(
                                value["error"]
                                    .as_str()
                                    .unwrap_or("Source could not be applied")
                                    .into(),
                            );
                            None
                        }
                        Err(e) => {
                            v.error = Some(e);
                            None
                        }
                    };
                    cx.notify();
                    close
                })
                .ok()
                .flatten();
            if let Some(close) = close {
                cx.update(|cx| close(cx));
            }
        })
        .detach();
    }
}
impl Render for CodeEditor {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let dirty = self.source.read(cx).value().as_str() != self.original;
        let close = self.on_close.clone();
        let title = match &self.target {
            Target::Definition => "Workflow definition".into(),
            Target::Step(id) => {
                step_title(&self.definition["steps"], id).unwrap_or_else(|| super::human_name(id))
            }
            Target::Script => "View JavaScript source".into(),
            Target::Run { .. } => format!(
                "Run {}",
                self.definition["title"].as_str().unwrap_or("workflow")
            ),
        };
        let step_kind = if let Target::Step(id) = &self.target {
            super::kind_of(&self.definition, id)
        } else {
            None
        };
        let visual_subtitle = step_kind
            .filter(|_| self.visual && !self.expression)
            .map(super::workflow_form::kind_name);
        let subtitle = if let Some(kind) = visual_subtitle {
            kind
        } else if self.expression {
            "Native expression · Rhai"
        } else if matches!(self.target, Target::Script) {
            "JavaScript source"
        } else if matches!(self.target, Target::Run { .. }) {
            "Workflow input · JSON"
        } else {
            "Executable workflow JSON"
        };
        let run = matches!(self.target, Target::Run { .. });
        let (state, tone) = if run {
            ("Input JSON", ui::theme::get(2))
        } else if dirty {
            ("Unsaved changes", ui::theme::get(11))
        } else {
            ("Saved", ui::theme::color(ui::POSITIVE))
        };
        let back = close.clone();
        let mut body = col()
            .size_full()
            .min_h_0()
            .px(px(32.))
            .pt(px(20.))
            .pb(px(24.))
            .gap(px(14.))
            .child(
                back_button("workflow-code-back", "Workflow", cx)
                    .disabled(self.pending)
                    .on_click(move |_, _, cx| back(cx)),
            )
            .child(
                row()
                    .w_full()
                    .gap(px(16.))
                    .flex_wrap()
                    .child(
                        col()
                            .flex_1()
                            .min_w(px(200.))
                            .gap(px(4.))
                            .child(
                                text(title)
                                    .truncate()
                                    .text_size(px(22.))
                                    .line_height(px(28.))
                                    .font_weight(FontWeight::SEMIBOLD),
                            )
                            .child(
                                row()
                                    .gap(px(8.))
                                    .child(label(subtitle).text_size(px(13.)).min_w_0().truncate())
                                    .child(
                                        row()
                                            .flex_none()
                                            .gap(px(5.))
                                            .child(div().size(px(6.)).rounded_full().bg(rgb(tone)))
                                            .child(label(state).text_size(px(12.))),
                                    ),
                            ),
                    )
                    .child(
                        row()
                            .flex_none()
                            .gap(px(6.))
                            .child(ui::copy_button(
                                "workflow-code-copy",
                                "Copy",
                                self.source.read(cx).value().to_string(),
                            ))
                            .child(
                                quiet_button("workflow-code-cancel", cx)
                                    .small()
                                    .h(px(28.))
                                    .px(px(12.))
                                    .rounded(px(14.))
                                    .text_size(px(12.5))
                                    .label("Cancel")
                                    .disabled(self.pending)
                                    .on_click(move |_, _, cx| close(cx)),
                            )
                            .child(
                                settings::primary_pill(
                                    "workflow-code-save",
                                    if run { "Run workflow" } else { "Save" },
                                )
                                .unavailable(self.pending || self.loading || (!dirty && !run))
                                .on_click(cx.listener(|v, _, _, cx| v.save(cx))),
                            ),
                    ),
            );
        if let Some(error) = &self.error {
            body = body.child(ui::error_message("workflow-code-error", error.clone()));
        }
        if let Target::Run { required, .. } = &self.target
            && !required.is_empty()
        {
            body = body.child(label(format!(
                "Provide: {}",
                required
                    .iter()
                    .map(|path| if path.is_empty() {
                        "input".into()
                    } else {
                        format!("input{path}")
                    })
                    .collect::<Vec<String>>()
                    .join(", ")
            )));
        }
        if self.loading {
            return body.child(label("Loading source…"));
        }
        let narrow = window.viewport_size().width < px(1020.);
        if narrow && self.expression {
            let tab = |id: &'static str, title: &'static str, on: bool| {
                div()
                    .id(id)
                    .role(Role::Tab)
                    .aria_label(title)
                    .aria_selected(on)
                    .h_full()
                    .px(px(11.))
                    .flex()
                    .items_center()
                    .rounded(px(12.))
                    .cursor_pointer()
                    .text_size(px(12.))
                    .font_weight(FontWeight::MEDIUM)
                    .text_color(rgb(ui::theme::get(if on { 0 } else { 1 })))
                    .when(on, settings::raised)
                    .child(title)
            };
            body = body.child(
                row()
                    .self_start()
                    .h(px(28.))
                    .p(px(2.))
                    .gap(px(0.))
                    .rounded(px(14.))
                    .bg(ui::ink(0x0c))
                    .child(
                        tab("workflow-code-tab-source", "Code", !self.show_preview).on_click(
                            cx.listener(|v, _, _, cx| {
                                v.show_preview = false;
                                cx.notify();
                            }),
                        ),
                    )
                    .child(
                        tab(
                            "workflow-code-tab-preview",
                            "Preview & sample input",
                            self.show_preview,
                        )
                        .on_click(cx.listener(|v, _, _, cx| {
                            v.show_preview = true;
                            cx.notify();
                        })),
                    ),
            );
        }
        let source_pane = div()
            .id("workflow-code-editor")
            .flex_1()
            .h_full()
            .min_w_0()
            .rounded(px(12.))
            .border_1()
            .border_color(ui::ink(0x12))
            .overflow_hidden()
            .child(
                Editor::new(&self.source)
                    .aria_label("Workflow source code")
                    .readonly(self.pending)
                    .bordered(false)
                    .h(relative(1.))
                    .w_full()
                    .py(px(6.))
                    .text_size(px(12.5)),
            );
        let visual_available = matches!(self.target, Target::Step(_)) && !self.expression;
        if visual_available {
            let mode = |id: &'static str, title: &'static str, on: bool| {
                div()
                    .id(id)
                    .role(Role::Tab)
                    .aria_label(title)
                    .aria_selected(on)
                    .h_full()
                    .px(px(12.))
                    .flex()
                    .items_center()
                    .rounded(px(12.))
                    .cursor_pointer()
                    .text_size(px(12.))
                    .font_weight(FontWeight::MEDIUM)
                    .text_color(rgb(ui::theme::get(if on { 0 } else { 1 })))
                    .when(on, settings::raised)
                    .child(title)
            };
            body = body.child(
                row()
                    .self_start()
                    .h(px(28.))
                    .p(px(2.))
                    .gap(px(0.))
                    .rounded(px(14.))
                    .bg(ui::ink(0x0c))
                    .child(
                        mode("workflow-code-mode-visual", "Visual", self.visual).on_click(
                            cx.listener(|v, _, _, cx| {
                                // Rebuild the fields from whatever the code says now.
                                v.form.reset();
                                v.visual = true;
                                cx.notify();
                            }),
                        ),
                    )
                    .child(
                        mode("workflow-code-mode-code", "Code", !self.visual).on_click(
                            cx.listener(|v, _, _, cx| {
                                v.visual = false;
                                cx.notify();
                            }),
                        ),
                    ),
            );
        }
        let mut panes = row().flex_1().min_h_0().items_start().gap(px(16.));
        if visual_available && self.visual {
            let form = super::workflow_form::render(self, window, cx);
            panes = panes.child(
                div()
                    .id("workflow-step-form")
                    .flex_1()
                    .h_full()
                    .min_w_0()
                    .overflow_y_scroll()
                    .child(div().max_w(px(720.)).pb(px(24.)).child(form)),
            );
        } else if !narrow || !self.expression || !self.show_preview {
            panes = panes.child(source_pane);
        }
        if self.expression && (!narrow || self.show_preview) {
            let heading = |value: &'static str| {
                text(value)
                    .text_size(px(13.))
                    .font_weight(FontWeight::SEMIBOLD)
            };
            let mut side = col()
                .id("workflow-code-preview-panel")
                .w(px(300.))
                .h_full()
                .flex_shrink_0()
                .gap(px(10.))
                .overflow_y_scroll()
                .child(
                    row()
                        .h(px(28.))
                        .child(heading("Sample input").flex_1())
                        .child(
                            settings::pill("workflow-code-preview", "Preview", cx)
                                .disabled(self.pending)
                                .on_click(cx.listener(|v, _, _, cx| v.preview(cx))),
                        ),
                )
                .child(
                    div()
                        .id("workflow-code-sample")
                        .h(px(180.))
                        .rounded(px(10.))
                        .border_1()
                        .border_color(ui::ink(0x12))
                        .overflow_hidden()
                        .child(
                            Editor::new(&self.sample)
                                .aria_label("Expression sample input")
                                .readonly(self.pending)
                                .bordered(false)
                                .h(px(178.))
                                .w_full()
                                .text_size(px(12.)),
                        ),
                )
                .child(label(
                    "Preview runs on this JSON only; the workflow does not run.",
                ));
            if let Some(output) = &self.output {
                side = side.child(heading("Result")).child(
                    div()
                        .w_full()
                        .p(px(10.))
                        .rounded(px(10.))
                        .bg(ui::ink(0x06))
                        .child(code(output.clone()).whitespace_normal()),
                );
            }
            let mut tools = div().flex().flex_wrap().gap(px(4.));
            for name in [
                "left_join",
                "group_by",
                "index_by",
                "sort_by",
                "unique",
                "flatten",
                "pluck",
                "get",
                "merge",
                "pick",
                "omit",
                "take",
                "json",
                "parse_json",
                "unwrap_json",
                "matches",
                "capture",
                "replace_re",
            ] {
                tools = tools.child(
                    code(name)
                        .px(px(6.))
                        .py(px(2.))
                        .rounded(px(5.))
                        .bg(ui::ink(0x08)),
                );
            }
            side = side
                .child(div().h(px(8.)))
                .child(heading("Built-in functions"))
                .child(tools)
                .child(label(
                    "Bound data arrives as input. Functions, closures, loops, objects and arrays all work; null is JSON null.",
                ));
            if narrow {
                side = side.w_full();
            }
            panes = panes.child(side);
        }
        body.child(panes)
    }
}

/// A step's own title, found wherever it is nested.
fn step_title(steps: &Value, id: &str) -> Option<String> {
    super::find_step(steps, id)?
        .get("title")?
        .as_str()
        .filter(|t| !t.is_empty())
        .map(str::to_owned)
}

impl super::workflow_form::Host for CodeEditor {
    fn form(&mut self) -> &mut super::workflow_form::Form {
        &mut self.form
    }
    fn draft(&self, cx: &App) -> Option<Value> {
        self.source
            .read(cx)
            .value()
            .parse::<Value>()
            .ok()
            .filter(Value::is_object)
    }
    fn write(&mut self, step: Value, window: &mut Window, cx: &mut Context<Self>) {
        let text = serde_json::to_string_pretty(&step).unwrap_or_default();
        self.source
            .update(cx, |s, cx| s.set_value(text, window, cx));
        cx.notify();
    }
    fn definition(&self) -> &Value {
        &self.definition
    }
}
