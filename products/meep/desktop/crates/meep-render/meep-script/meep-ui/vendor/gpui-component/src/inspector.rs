use std::{collections::HashMap, fmt::Write as _, rc::Rc, sync::OnceLock};

use anyhow::Result;
use gpui::{
    AnyElement, App, AppContext, Context, DivInspectorState, Entity, Inspector, InspectorElementId,
    InteractiveElement as _, IntoElement, KeyBinding, ParentElement as _, Refineable as _, Render,
    SharedString, StyleRefinement, Styled, Subscription, Task, Window, actions, div,
    inspector_reflection::FunctionReflection, prelude::FluentBuilder, px,
};
use lsp_types::{
    CompletionItem, CompletionItemKind, CompletionResponse, CompletionTextEdit, Diagnostic,
    DiagnosticSeverity, Position, TextEdit,
};
use ropey::Rope;

use crate::{
    ActiveTheme, IconName, Selectable, Sizable, TITLE_BAR_HEIGHT,
    alert::Alert,
    button::{Button, ButtonVariants},
    clipboard::Clipboard,
    description_list::DescriptionList,
    h_flex,
    input::{CompletionProvider, Editor, EditorState, InputEvent, RopeExt, TabSize},
    link::Link,
    v_flex,
};

actions!(inspector, [ToggleInspector]);

/// Initialize the inspector and register the action to toggle it.
pub(crate) fn init(cx: &mut App) {
    cx.bind_keys(vec![
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-alt-i", ToggleInspector, None),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-shift-i", ToggleInspector, None),
    ]);

    cx.on_action(|_: &ToggleInspector, cx| {
        let Some(active_window) = cx.active_window() else {
            return;
        };

        cx.defer(move |cx| {
            _ = active_window.update(cx, |_, window, cx| {
                window.toggle_inspector(cx);
            });
        });
    });

    cx.register_inspector_element(|window, cx| {
        let div_inspector = cx.new(|cx| DivInspector::new(window, cx));
        move |id, state: &DivInspectorState, window: &mut Window, cx: &mut App| {
            div_inspector.update(cx, |this, cx| {
                this.update_inspected_element(id, state.clone(), window, cx);
                this.render(window, cx).into_any_element()
            })
        }
    });

    cx.set_inspector_renderer(Box::new(render_inspector));
}

struct InspectorEditor {
    /// The input state for the editor.
    state: Entity<EditorState>,
    /// Error to display from parsing the input, or if serialization errors somehow occur.
    error: Option<SharedString>,
    /// Whether the editor is currently being edited.
    editing: bool,
}

pub struct DivInspector {
    inspector_id: Option<InspectorElementId>,
    inspector_state: Option<DivInspectorState>,
    rust_state: InspectorEditor,
    json_state: InspectorEditor,
    /// Initial style before any edits
    initial_style: StyleRefinement,
    /// Part of the initial style that could not be converted to Rust code
    unconvertible_style: StyleRefinement,
    _subscriptions: Vec<Subscription>,
}

impl DivInspector {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let lsp_provider = Rc::new(LspProvider {});

        let json_input_state = cx.new(|cx| {
            EditorState::new(window, cx)
                .language("json")
                .line_number(false)
        });

        let rust_input_state = cx.new(|cx| {
            EditorState::new(window, cx)
                .language("rust")
                .line_number(false)
                .tab_size(TabSize {
                    tab_size: 4,
                    hard_tabs: false,
                })
        });
        rust_input_state.update(cx, |state, cx| {
            state.lsp_mut().completion_provider = Some(lsp_provider.clone());
            cx.notify();
        });

        let _subscriptions = vec![
            cx.subscribe_in(
                &json_input_state,
                window,
                |this: &mut DivInspector, state, event: &InputEvent, window, cx| match event {
                    InputEvent::Change => {
                        let new_style = state.read(cx).value();
                        this.edit_json(new_style.as_str(), window, cx);
                    }
                    _ => {}
                },
            ),
            cx.subscribe_in(
                &rust_input_state,
                window,
                |this: &mut DivInspector, state, event: &InputEvent, window, cx| match event {
                    InputEvent::Change => {
                        let new_style = state.read(cx).value();
                        this.edit_rust(new_style.as_str(), window, cx);
                    }
                    _ => {}
                },
            ),
        ];

        let rust_state = InspectorEditor {
            state: rust_input_state,
            error: None,
            editing: false,
        };

        let json_state = InspectorEditor {
            state: json_input_state,
            error: None,
            editing: false,
        };

        Self {
            inspector_id: None,
            inspector_state: None,
            rust_state,
            json_state,
            initial_style: Default::default(),
            unconvertible_style: Default::default(),
            _subscriptions,
        }
    }

    pub fn update_inspected_element(
        &mut self,
        inspector_id: InspectorElementId,
        state: DivInspectorState,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // Skip updating if the inspector ID hasn't changed
        if self.inspector_id.as_ref() == Some(&inspector_id) {
            return;
        }

        let initial_style = state.base_style.as_ref();
        self.initial_style = initial_style.clone();
        self.json_state.editing = false;
        self.update_json_from_style(initial_style, window, cx);
        self.rust_state.editing = false;
        let rust_style = self.update_rust_from_style(initial_style, window, cx);
        self.unconvertible_style = initial_style.subtract(&rust_style);
        self.inspector_id = Some(inspector_id);
        self.inspector_state = Some(state);
        cx.notify();
    }

    fn edit_json(&mut self, code: &str, window: &mut Window, cx: &mut Context<Self>) {
        if !self.json_state.editing {
            self.json_state.editing = true;
            return;
        }

        match serde_json::from_str::<StyleRefinement>(code) {
            Ok(new_style) => {
                self.json_state.error = None;
                self.rust_state.error = None;
                self.rust_state.editing = false;
                let rust_style = self.update_rust_from_style(&new_style, window, cx);
                self.unconvertible_style = new_style.subtract(&rust_style);
                self.update_element_style(new_style, window, cx);
            }
            Err(e) => {
                self.json_state.error = Some(e.to_string().trim_end().to_string().into());
                window.refresh();
            }
        }
    }

    fn edit_rust(&mut self, code: &str, window: &mut Window, cx: &mut Context<Self>) {
        if !self.rust_state.editing {
            self.rust_state.editing = true;
            return;
        }

        let (new_style, diagnostics) = rust_to_style(self.unconvertible_style.clone(), code);
        self.rust_state.state.update(cx, |state, cx| {
            if let Some(set) = state.diagnostics_mut() {
                set.clear();
                set.extend(diagnostics);
            }
            cx.notify();
        });
        self.json_state.error = None;
        self.json_state.editing = false;
        self.update_json_from_style(&new_style, window, cx);
        self.update_element_style(new_style, window, cx);
    }

    fn update_element_style(
        &self,
        style: StyleRefinement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        window.with_inspector_state::<DivInspectorState, _>(
            self.inspector_id.as_ref(),
            cx,
            |state, _window| {
                if let Some(state) = state {
                    *state.base_style = style;
                }
            },
        );
        window.refresh();
    }

    fn reset_style(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.rust_state.editing = false;
        let rust_style = self.update_rust_from_style(&self.initial_style, window, cx);
        self.unconvertible_style = self.initial_style.subtract(&rust_style);
        self.json_state.editing = false;
        self.update_json_from_style(&self.initial_style, window, cx);
        if let Some(state) = self.inspector_state.as_mut() {
            *state.base_style = self.initial_style.clone();
        }
    }

    fn update_json_from_style(
        &self,
        style: &StyleRefinement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.json_state.state.update(cx, |state, cx| {
            state.set_value(style_to_json(style), window, cx);
        });
    }

    fn update_rust_from_style(
        &self,
        style: &StyleRefinement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> StyleRefinement {
        self.rust_state.state.update(cx, |state, cx| {
            let (rust_code, rust_style) = style_to_rust(style);
            state.set_value(rust_code, window, cx);
            rust_style
        })
    }
}

fn style_to_json(style: &StyleRefinement) -> String {
    serde_json::to_string_pretty(style).unwrap_or_else(|e| format!("{{ \"error\": \"{}\" }}", e))
}

struct StyleMethods {
    table: Vec<(Box<StyleRefinement>, FunctionReflection<StyleRefinement>)>,
    map: HashMap<&'static str, FunctionReflection<StyleRefinement>>,
}

impl StyleMethods {
    fn get() -> &'static Self {
        static STYLE_METHODS: OnceLock<StyleMethods> = OnceLock::new();
        STYLE_METHODS.get_or_init(|| {
            let table: Vec<_> = [
                gpui_base::styled_ext_reflection_methods::<StyleRefinement>(),
                gpui::styled_reflection::methods::<StyleRefinement>(),
            ]
            .into_iter()
            .flatten()
            .map(|method| (Box::new(method.invoke(StyleRefinement::default())), method))
            .collect();
            let map = table
                .iter()
                .map(|(_, method)| (method.name, method.clone()))
                .collect();

            Self { table, map }
        })
    }
}

fn style_to_rust(input_style: &StyleRefinement) -> (String, StyleRefinement) {
    let methods: Vec<_> = StyleMethods::get()
        .table
        .iter()
        .filter_map(|(style, method)| {
            if input_style.is_superset_of(style) {
                Some(method)
            } else {
                None
            }
        })
        .collect();
    let mut code = "fn build() -> Div {\n    div()\n".to_string();
    let mut style = StyleRefinement::default();
    for method in methods {
        let before_invoke = style.clone();
        style = method.invoke(style);
        if style != before_invoke {
            _ = write!(code, "        .{}()\n", method.name);
        }
    }
    code.push_str("}");
    (code, style)
}

fn rust_to_style(mut style: StyleRefinement, source: &str) -> (StyleRefinement, Vec<Diagnostic>) {
    let rope = Rope::from(source);
    let Some(begin) = source.find("div()").map(|i| i + "div()".len()) else {
        let start_pos = Position::new(0, 0);
        let end_pos = rope.offset_to_position(rope.len());

        return (
            style,
            vec![Diagnostic {
                range: lsp_types::Range::new(start_pos, end_pos),
                severity: Some(DiagnosticSeverity::ERROR),
                message: "expected `div()`".into(),
                ..Default::default()
            }],
        );
    };

    let mut methods = vec![];
    let mut offset = 0;
    let mut method_offset = 0;
    let mut method = String::new();
    for line in rope.iter_lines() {
        if line.to_string().trim().starts_with("//") {
            offset += line.len() + 1;
            continue;
        }

        for c in line.chars() {
            offset += c.len_utf8();
            if offset < begin {
                continue;
            }

            if c.is_ascii_alphanumeric() || c == '_' {
                method.push(c);
                method_offset = offset;
            } else {
                if !method.is_empty() {
                    methods.push((method_offset, method.clone()));
                }
                method.clear();
            }
        }

        // +1 \n
        offset += 1;
    }

    let mut diagnostics = vec![];
    let style_methods = StyleMethods::get();

    for (offset, method) in methods {
        match style_methods.map.get(method.as_str()) {
            Some(method_reflection) => style = method_reflection.invoke(style),
            None => {
                let message = format!("unknown method `{}`", method);
                let start = rope.offset_to_position(offset.saturating_sub(method.len()));
                let end = rope.offset_to_position(offset);
                let diagnostic = lsp_types::Diagnostic {
                    range: lsp_types::Range::new(start, end),
                    severity: Some(DiagnosticSeverity::ERROR),
                    message,
                    ..Default::default()
                };

                diagnostics.push(diagnostic);
            }
        }
    }

    (style, diagnostics)
}

impl Render for DivInspector {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        v_flex().size_full().gap_y_4().text_sm().when_some(
            self.inspector_state.as_ref(),
            |this, state| {
                this.child(
                    DescriptionList::new()
                        .columns(1)
                        .label_width(px(110.))
                        .bordered(false)
                        .item("Origin", format!("{}", state.bounds.origin), 1)
                        .item("Size", format!("{}", state.bounds.size), 1)
                        .item("Content Size", format!("{}", state.content_size), 1),
                )
                .child(
                    v_flex()
                        .flex_1()
                        .h_2_5()
                        .gap_y_3()
                        .child(
                            h_flex()
                                .justify_between()
                                .gap_x_2()
                                .child("Rust Styles")
                                .child(Button::new("rust-reset").label("Reset").small().on_click(
                                    cx.listener(|this, _, window, cx| {
                                        this.reset_style(window, cx);
                                    }),
                                )),
                        )
                        .child(
                            v_flex()
                                .flex_1()
                                .gap_y_1()
                                .font_family(cx.theme().mono_font_family.clone())
                                .text_size(cx.theme().mono_font_size)
                                .child(Editor::new(&self.rust_state.state).h(gpui::relative(1.)))
                                .when_some(self.rust_state.error.clone(), |this, err| {
                                    this.child(Alert::error("rust-error", err).text_xs())
                                }),
                        ),
                )
                .child(
                    v_flex()
                        .flex_1()
                        .gap_y_3()
                        .h_2_5()
                        .flex_shrink_0()
                        .child(
                            h_flex()
                                .gap_x_2()
                                .child(div().flex_1().child("JSON Styles"))
                                .child(Button::new("json-reset").label("Reset").small().on_click(
                                    cx.listener(|this, _, window, cx| {
                                        this.reset_style(window, cx);
                                    }),
                                )),
                        )
                        .child(
                            v_flex()
                                .flex_1()
                                .gap_y_1()
                                .font_family(cx.theme().mono_font_family.clone())
                                .text_size(cx.theme().mono_font_size)
                                .child(Editor::new(&self.json_state.state).h(gpui::relative(1.)))
                                .when_some(self.json_state.error.clone(), |this, err| {
                                    this.child(Alert::error("json-error", err).text_xs())
                                }),
                        ),
                )
            },
        )
    }
}

fn render_inspector(
    inspector: &mut Inspector,
    window: &mut Window,
    cx: &mut Context<Inspector>,
) -> AnyElement {
    let inspector_element_id = inspector.active_element_id();
    let source_location =
        inspector_element_id.map(|id| SharedString::new(format!("{}", id.path.source_location)));
    let element_global_id = inspector_element_id.map(|id| format!("{}", id.path.global_id));

    v_flex()
        .id("inspector")
        .font_family(cx.theme().font_family.clone())
        .size_full()
        .bg(cx.theme().tokens.background)
        .border_l_1()
        .border_color(cx.theme().border)
        .text_color(cx.theme().foreground)
        .child(
            h_flex()
                .w_full()
                .justify_between()
                .gap_2()
                .h(TITLE_BAR_HEIGHT)
                .line_height(TITLE_BAR_HEIGHT)
                .overflow_x_hidden()
                .px_2()
                .border_b_1()
                .border_color(cx.theme().title_bar_border)
                .bg(cx.theme().tokens.title_bar)
                .child(
                    h_flex()
                        .gap_2()
                        .text_sm()
                        .child(
                            Button::new("inspect")
                                .icon(IconName::Inspector)
                                .selected(inspector.is_picking())
                                .toggled(inspector.is_picking())
                                .small()
                                .ghost()
                                .on_click(cx.listener(|this, _, window, _| {
                                    this.start_picking();
                                    window.refresh();
                                })),
                        )
                        .child("Inspector"),
                )
                .child(
                    Button::new("close")
                        .icon(IconName::Close)
                        .small()
                        .ghost()
                        .on_click(|_, window, cx| {
                            window.dispatch_action(Box::new(ToggleInspector), cx);
                        }),
                ),
        )
        .child(
            v_flex()
                .flex_1()
                .p_3()
                .gap_y_3()
                .text_sm()
                .when_some(source_location, |this, source_location| {
                    this.child(
                        h_flex()
                            .gap_x_2()
                            .text_sm()
                            .child(
                                Link::new("source-location")
                                    .href(format!("file://{}", source_location))
                                    .child(source_location.clone())
                                    .flex_1()
                                    .overflow_x_hidden(),
                            )
                            .child(Clipboard::new("copy-source-location").value(source_location)),
                    )
                })
                .children(element_global_id)
                .children(inspector.render_inspector_states(window, cx)),
        )
        .into_any_element()
}

struct LspProvider {}

impl CompletionProvider for LspProvider {
    fn completions(
        &self,
        rope: &ropey::Rope,
        offset: usize,
        _: lsp_types::CompletionContext,
        _: &mut Window,
        cx: &mut App,
    ) -> Task<Result<CompletionResponse>> {
        let mut left_offset = 0;
        while left_offset < 100 {
            match rope.char_at(offset.saturating_sub(left_offset)) {
                Some('.') => {
                    break;
                }
                None => break,
                _ => {}
            }
            left_offset += 1;
        }
        let start = offset.saturating_sub(left_offset);
        let trigger_character = rope.slice(start..offset).to_string();
        if !trigger_character.starts_with('.') {
            return Task::ready(Ok(CompletionResponse::Array(vec![])));
        }

        let start_pos = rope.offset_to_position(start);
        let end_pos = rope.offset_to_position(offset);

        cx.background_spawn(async move {
            let styles = StyleMethods::get()
                .map
                .iter()
                .filter_map(|(name, method)| {
                    let prefix = &trigger_character[1..];
                    if name.starts_with(&prefix) {
                        Some(CompletionItem {
                            label: name.to_string(),
                            filter_text: Some(prefix.to_string()),
                            kind: Some(CompletionItemKind::METHOD),
                            detail: Some("()".to_string()),
                            documentation: method
                                .documentation
                                .as_ref()
                                .map(|doc| lsp_types::Documentation::String(doc.to_string())),
                            text_edit: Some(CompletionTextEdit::Edit(TextEdit {
                                range: lsp_types::Range {
                                    start: start_pos,
                                    end: end_pos,
                                },
                                new_text: format!(".{}()", name),
                            })),
                            ..Default::default()
                        })
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>();

            Ok(CompletionResponse::Array(styles))
        })
    }

    fn is_completion_trigger(&self, _: usize, _: &str, _: &mut App) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use gpui::{AbsoluteLength, DefiniteLength, Length, rems};
    use indoc::indoc;
    use lsp_types::Position;

    #[test]
    fn test_rust_to_style() {
        let (style, diagnostics) = super::rust_to_style(
            Default::default(),
            indoc! {r#"
            fn build() -> Div {
                div()
                    .p_1()
                    // This is a comment
                    .mx_2()
            }
            "#},
        );
        assert_eq!(diagnostics, vec![]);
        assert_eq!(
            style.padding.left,
            Some(DefiniteLength::Absolute(AbsoluteLength::Rems(rems(0.25))))
        );
        assert_eq!(
            style.margin.left,
            Some(Length::Definite(DefiniteLength::Absolute(
                AbsoluteLength::Rems(rems(0.5))
            )))
        );

        let (_, diagnostics) = super::rust_to_style(
            Default::default(),
            indoc! {r#"
            fn build() -> Div {
                div()
                    .p_1()
                    // This is a comment
                    .unknown_method
                    .bad_method()
            }
            "#},
        );

        assert_eq!(diagnostics.len(), 2);
        assert_eq!(diagnostics[0].message, "unknown method `unknown_method`");
        assert_eq!(diagnostics[0].range.start, Position::new(4, 9));
        assert_eq!(diagnostics[0].range.end, Position::new(4, 23));
        assert_eq!(diagnostics[1].message, "unknown method `bad_method`");
        assert_eq!(diagnostics[1].range.start, Position::new(5, 9));
        assert_eq!(diagnostics[1].range.end, Position::new(5, 19));
    }
}
