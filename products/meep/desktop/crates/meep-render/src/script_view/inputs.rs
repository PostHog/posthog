//! Native text fields inside script views. They are retained GPUI entities
//! keyed by element, so the caret, selection and IME state survive every
//! render, and they report typing back to the script.
use super::*;
use crate::block_editor::{BlockEditor, BlockEditorEvent};

/// A retained native text field: single line or multiline.
#[derive(Clone)]
pub(super) enum Editor {
    Line(Entity<InputState>),
    Area(Entity<TextareaState>),
    Date(Entity<DatePickerState>, bool),
    Time(Entity<TimeFieldState>),
    /// A block editor: its document is blocks, reported as JSON.
    Blocks(Entity<BlockEditor>),
}
impl Editor {
    pub(super) fn value(&self, cx: &App) -> String {
        match self {
            Self::Line(state) => state.read(cx).value().to_string(),
            Self::Area(state) => state.read(cx).value().to_string(),
            Self::Date(state, with_time) => state
                .read(cx)
                .date_time()
                .start()
                .map(|d| {
                    d.format(if *with_time {
                        "%Y-%m-%dT%H:%M"
                    } else {
                        "%Y-%m-%d"
                    })
                    .to_string()
                })
                .unwrap_or_default(),
            Self::Time(state) => state.read(cx).time().format("%H:%M").to_string(),
            Self::Blocks(state) => state.read(cx).markdown(),
        }
    }
    pub(super) fn set_value(&self, value: String, window: &mut Window, cx: &mut App) {
        match self {
            Self::Line(state) => state.update(cx, |s, cx| s.set_value(value, window, cx)),
            Self::Area(state) => state.update(cx, |s, cx| s.set_value(value, window, cx)),
            Self::Date(state, with_time) => {
                let parsed = if *with_time {
                    chrono::NaiveDateTime::parse_from_str(&value, "%Y-%m-%dT%H:%M").ok()
                } else {
                    chrono::NaiveDate::parse_from_str(&value, "%Y-%m-%d")
                        .ok()
                        .and_then(|d| d.and_hms_opt(0, 0, 0))
                };
                state.update(cx, |s, cx| {
                    s.set_date_time(PickerDateTime::Single(parsed), window, cx)
                });
            }
            Self::Time(state) => {
                if let Ok(time) = chrono::NaiveTime::parse_from_str(&value, "%H:%M") {
                    state.update(cx, |s, cx| s.set_time(time, window, cx));
                }
            }
            Self::Blocks(state) => state.update(cx, |s, cx| s.set_markdown(&value, cx)),
        }
    }
    pub(super) fn focus(&self, window: &mut Window, cx: &mut App) {
        let handle = match self {
            Self::Line(state) => state.read(cx).focus_handle(cx),
            Self::Area(state) => state.read(cx).focus_handle(cx),
            Self::Date(state, _) => state.read(cx).focus_handle(cx),
            Self::Time(state) => state.read(cx).focus_handle(cx),
            Self::Blocks(state) => state.read(cx).focus_handle(),
        };
        handle.focus(window, cx);
    }
}

pub(super) struct Slot {
    pub(super) editor: Editor,
    pub(super) value: String,
    pub(super) on_change: Option<u32>,
    pub(super) on_submit: Option<u32>,
    submit_on_enter: bool,
    /// A block editor's document as the script last gave it or was told it.
    blocks: Value,
    pub(super) _subscription: Subscription,
}

impl ScriptView {
    /// A block editor's document changed (debounced by the editor): the
    /// script gets the blocks once typing pauses.
    fn blocks_event(&mut self, key: &str, cx: &mut Context<Self>) {
        if self.context.is_retired() {
            return;
        }
        let Some(slot) = self.inputs.get_mut(key) else {
            return;
        };
        let Editor::Blocks(editor) = &slot.editor else {
            return;
        };
        self.inputs_synced = None;
        let (blocks, markdown) = {
            let editor = editor.read(cx);
            (editor.to_json(), editor.markdown())
        };
        slot.blocks = blocks.clone();
        slot.value = markdown;
        // Debounced, and a script-set document can trigger it: not a gesture.
        if let Some(handler) = slot.on_change {
            self.invoke(handler, blocks, false, cx);
        }
    }
    pub(super) fn input_event(&mut self, key: &str, event: &InputEvent, cx: &mut Context<Self>) {
        if self.context.is_retired() {
            return;
        }
        let Some(slot) = self.inputs.get_mut(key) else {
            return;
        };
        self.inputs_synced = None;
        let value = slot.editor.value(cx);
        let handler = match event {
            InputEvent::Change if value != slot.value => {
                slot.value = value.clone();
                slot.on_change
            }
            InputEvent::PressEnter { shift: true, .. }
                if matches!(slot.editor, Editor::Area(_)) =>
            {
                None
            }
            InputEvent::PressEnter { .. } => slot.on_submit,
            _ => None,
        };
        if let Some(handler) = handler {
            self.invoke(handler, json!(value), true, cx);
        }
    }
    /// Text fields are retained GPUI entities keyed by `id` (or position), so
    /// the caret, selection and IME state survive every re-render.
    pub(super) fn prepare_inputs(
        &mut self,
        tree: &Tree,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let mut seen = Vec::new();
        for node in &tree.fields {
            let multiline = node.kind == "textarea";
            let p = &node.p;
            let key = node.key.to_string();
            if self
                .inputs
                .get(&key)
                .is_some_and(|slot| match (&slot.editor, node.kind) {
                    (Editor::Line(_), "input")
                    | (Editor::Area(_), "textarea")
                    | (Editor::Time(_), "time_picker")
                    | (Editor::Blocks(_), "block_editor") => false,
                    (Editor::Date(_, with_time), "date_picker") => {
                        *with_time != (p["withTime"] == true)
                    }
                    _ => true,
                })
            {
                self.inputs.remove(&key);
            }
            if !self.inputs.contains_key(&key) {
                let placeholder = p["placeholder"].as_str().unwrap_or("").to_owned();
                let subscribed = key.clone();
                let (editor, subscription) = if node.kind == "block_editor" {
                    let state = cx.new(|cx| BlockEditor::new(window, cx));
                    let subscription = cx
                        .subscribe(&state, move |this, _, _: &BlockEditorEvent, cx| {
                            this.blocks_event(&subscribed, cx)
                        });
                    (Editor::Blocks(state), subscription)
                } else if node.kind == "date_picker" {
                    let with_time = p["withTime"] == true;
                    let state = cx.new(|cx| {
                        let state = DatePickerState::new(window, cx);
                        if with_time {
                            state.time_precision(TimePrecision::Minute)
                        } else {
                            state
                        }
                    });
                    let subscription =
                        cx.subscribe(&state, move |this, _, _: &DatePickerEvent, cx| {
                            this.input_event(&subscribed, &InputEvent::Change, cx)
                        });
                    (Editor::Date(state, with_time), subscription)
                } else if node.kind == "time_picker" {
                    let state = cx.new(|cx| TimeFieldState::new(window, cx));
                    let subscription =
                        cx.subscribe(&state, move |this, _, _: &TimeFieldEvent, cx| {
                            this.input_event(&subscribed, &InputEvent::Change, cx)
                        });
                    (Editor::Time(state), subscription)
                } else if multiline {
                    let rows = p["rows"].as_u64().unwrap_or(4).clamp(1, 40) as usize;
                    let state = cx.new(|cx| {
                        TextareaState::new(window, cx)
                            .rows(rows)
                            .submit_on_enter(p["submitOnEnter"] == true)
                            .placeholder(placeholder)
                    });
                    let subscription = cx.subscribe(&state, move |this, _, event, cx| {
                        this.input_event(&subscribed, event, cx)
                    });
                    (Editor::Area(state), subscription)
                } else {
                    let masked = p["masked"] == true;
                    let state = cx.new(|cx| {
                        InputState::new(window, cx)
                            .placeholder(placeholder)
                            .masked(masked)
                    });
                    let subscription = cx.subscribe(&state, move |this, _, event, cx| {
                        this.input_event(&subscribed, event, cx)
                    });
                    (Editor::Line(state), subscription)
                };
                self.inputs.insert(
                    key.clone(),
                    Slot {
                        editor,
                        value: String::new(),
                        on_change: None,
                        on_submit: None,
                        submit_on_enter: p["submitOnEnter"] == true,
                        blocks: Value::Null,
                        _subscription: subscription,
                    },
                );
            }
            let slot = self.inputs.get_mut(&key).unwrap();
            let placeholder = p["placeholder"].as_str().unwrap_or_default();
            match &slot.editor {
                Editor::Line(input)
                    if input.read(cx).presentation().placeholder().as_ref() != placeholder =>
                {
                    input.update(cx, |input, cx| {
                        input.set_placeholder(placeholder.to_owned(), window, cx)
                    });
                }
                Editor::Area(input)
                    if input.read(cx).presentation().placeholder().as_ref() != placeholder =>
                {
                    input.update(cx, |input, cx| {
                        input.set_placeholder(placeholder.to_owned(), window, cx)
                    });
                }
                _ => {}
            }
            let submit_on_enter = p["submitOnEnter"] == true;
            if slot.submit_on_enter != submit_on_enter {
                if let Editor::Area(state) = &slot.editor {
                    state.update(cx, |state, cx| {
                        state.set_submit_on_enter(submit_on_enter, cx)
                    });
                }
                slot.submit_on_enter = submit_on_enter;
            }
            slot.on_change = handler(p, "onChange");
            slot.on_submit = if multiline && p["submitOnEnter"] != true {
                None
            } else {
                handler(p, "onSubmit")
            };
            if let Editor::Blocks(editor) = &slot.editor {
                let editor = editor.clone();
                let read_only = self.context.is_retired() || p["readOnly"] == true;
                let placeholder = p["placeholder"]
                    .as_str()
                    .map(|s| SharedString::from(s.to_owned()));
                // Controlled like a text field: the document is replaced only
                // when the script gives a value it was not just told about.
                let reset = if p["value"].is_array() && p["value"] != slot.blocks {
                    slot.blocks = p["value"].clone();
                    Some(Ok(p["value"].clone()))
                } else if let Some(markdown) = p["markdown"].as_str()
                    && !p["value"].is_array()
                    && markdown != slot.value
                {
                    slot.value = markdown.to_owned();
                    Some(Err(markdown.to_owned()))
                } else {
                    None
                };
                editor.update(cx, |e, cx| {
                    e.set_read_only(read_only, cx);
                    e.set_placeholder(placeholder, cx);
                    match reset {
                        Some(Ok(value)) => e.set_json(&value, cx),
                        Some(Err(markdown)) => e.set_markdown(&markdown, cx),
                        None => {}
                    }
                });
                seen.push(key);
                continue;
            }
            // Controlled value: only push it into the field when the script
            // changed it (for example clearing after submit), never echo typing.
            if let Some(value) = p["value"].as_str()
                && value != slot.value
            {
                slot.value = value.to_owned();
                slot.editor.set_value(value.to_owned(), window, cx);
            }
            seen.push(key);
        }
        self.inputs.retain(|key, _| seen.contains(key));
    }
}

impl Build {
    /// A block editor: the retained editor, sized by the element's style.
    #[inline(never)]
    pub(super) fn block_editor(&self, node: &Rc<Node>) -> AnyElement {
        match self.inputs.get(node.key.as_ref()) {
            Some(Editor::Blocks(editor)) => style(
                div()
                    .w_full()
                    .min_h_0()
                    .flex()
                    .flex_col()
                    .child(editor.clone()),
                node,
            )
            .into_any_element(),
            _ => ui::error("BlockEditor needs a stable id outside List rows").into_any_element(),
        }
    }
}
