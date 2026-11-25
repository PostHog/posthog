use anyhow::Result;
use gpui::{
    App, Context, HighlightStyle, Hitbox, MouseDownEvent, Task, UnderlineStyle, Window, px,
};
use ropey::Rope;
use std::{ops::Range, rc::Rc};

use crate::input::{EditorMode, GoToDefinition, InputBaseState, RopeExt};

/// Definition provider
///
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_definition
pub trait DefinitionProvider {
    /// textDocument/definition
    ///
    /// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_definition
    fn definitions(
        &self,
        _text: &Rope,
        _offset: usize,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Task<Result<Vec<lsp_types::LocationLink>>>;
}

#[derive(Clone, Default)]
pub(crate) struct HoverDefinition {
    /// The range of the symbol that triggered the hover.
    symbol_range: Range<usize>,
    pub(crate) locations: Rc<Vec<lsp_types::LocationLink>>,
}

impl HoverDefinition {
    pub(crate) fn update(
        &mut self,
        symbol_range: Range<usize>,
        locations: Vec<lsp_types::LocationLink>,
    ) {
        self.clear();
        self.symbol_range = symbol_range;
        self.locations = Rc::new(locations);
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.locations.is_empty()
    }

    pub(crate) fn clear(&mut self) {
        self.symbol_range = 0..0;
        self.locations = Rc::new(vec![]);
    }

    pub(crate) fn is_same(&self, offset: usize) -> bool {
        self.symbol_range.contains(&offset)
    }
}

impl InputBaseState<EditorMode> {
    pub(crate) fn handle_hover_definition(
        &mut self,
        offset: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(provider) = self.extras.lsp.definition_provider.clone() else {
            return;
        };

        if self.extras.hover_definition.is_same(offset) {
            return;
        }

        // Currently not implemented.
        let task = provider.definitions(&self.text, offset, window, cx);
        let mut symbol_range = self.text.word_range(offset).unwrap_or(offset..offset);
        let editor = cx.entity();
        self.extras.lsp._hover_task = cx.spawn_in(window, async move |_, cx| {
            let locations = task.await?;

            _ = editor.update(cx, |editor, cx| {
                if locations.is_empty() {
                    editor.extras.hover_definition.clear();
                } else {
                    if let Some(location) = locations.first() {
                        if let Some(range) = location.origin_selection_range {
                            let start = editor.text.position_to_offset(&range.start);
                            let end = editor.text.position_to_offset(&range.end);
                            symbol_range = start..end;
                        }
                    }

                    editor
                        .extras
                        .hover_definition
                        .update(symbol_range.clone(), locations.clone());
                }
                cx.notify();
            });

            Ok(())
        });
    }

    pub(crate) fn on_action_go_to_definition(
        &mut self,
        _: &GoToDefinition,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let offset = self.cursor();
        // A keyboard action must also work before the symbol has been hovered.
        let Some(provider) = self.extras.lsp.definition_provider.clone() else {
            return;
        };
        let text = self.text.clone();
        let response = provider.definitions(&text, offset, window, cx);
        let blur_subscription = cx.on_blur(&self.focus_handle, window, |editor, _, _| {
            editor.extras.lsp._definition_task = Task::ready(Ok(()));
        });
        self.extras.lsp._definition_task = cx.spawn_in(window, async move |editor, cx| {
            let _blur_subscription = blur_subscription;
            let locations = response.await?;
            editor.update_in(cx, |editor, window, cx| {
                if editor.cursor() != offset
                    || editor.text != text
                    || !editor.focus_handle.is_focused(window)
                {
                    return;
                }
                if let Some(location) = locations.first() {
                    editor.go_to_definition(location, window, cx);
                }
            })?;
            Ok(())
        });
    }

    /// Return true if handled.
    pub(crate) fn handle_click_hover_definition(
        &mut self,
        event: &MouseDownEvent,
        offset: usize,
        window: &mut Window,
        cx: &mut Context<InputBaseState<EditorMode>>,
    ) -> bool {
        if !event.modifiers.secondary(cx) || event.modifiers.alt {
            return false;
        }

        if self.extras.hover_definition.is_empty() {
            return false;
        };
        if !self.extras.hover_definition.is_same(offset) {
            return false;
        }

        let Some(location) = self.extras.hover_definition.locations.first().cloned() else {
            return false;
        };

        self.go_to_definition(&location, window, cx);

        true
    }

    pub(crate) fn go_to_definition(
        &mut self,
        location: &lsp_types::LocationLink,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let external = location
            .target_uri
            .scheme()
            .map(|s| s.as_str() == "https" || s.as_str() == "http")
            == Some(true);

        // Give the host a chance to show the document first (window/showDocument),
        // e.g. to open virtual/external documents (stdlib docs) in an app window.
        if let Some(handler) = self.extras.lsp.show_document.clone() {
            let params = lsp_types::ShowDocumentParams {
                uri: location.target_uri.clone(),
                external: Some(external),
                take_focus: Some(true),
                selection: Some(location.target_selection_range),
            };
            if handler(&params, window, cx) {
                return;
            }
        }

        if external {
            cx.open_url(&location.target_uri.to_string());
        } else {
            // Move to the location.
            let target_range = location.target_selection_range;
            let start = self.text.position_to_offset(&target_range.start);
            let end = self.text.position_to_offset(&target_range.end);

            self.move_to(start, None, cx);
            self.select_to(end, cx);
        }
    }
}

/// These read the editor's own state; they sit here rather than on the element
/// because the element has nothing to do with the answer.
impl InputBaseState<EditorMode> {
    /// The range highlighted while Cmd-hovering a symbol, with its style.
    pub(crate) fn hover_definition_style(&self) -> Option<(Range<usize>, HighlightStyle)> {
        let editor = self;
        if editor.extras.hover_definition.is_empty() {
            return None;
        };

        let mut highlight_style = editor.editor_style.highlight_styles.style("link_text")?;

        highlight_style.underline = Some(UnderlineStyle {
            thickness: px(1.),
            ..UnderlineStyle::default()
        });

        Some((
            editor.extras.hover_definition.symbol_range.clone(),
            highlight_style,
        ))
    }

    /// The hitbox that makes a Cmd-hovered symbol clickable.
    pub(crate) fn hover_definition_hitbox(&self, window: &mut Window) -> Option<Hitbox> {
        let editor = self;
        if editor.extras.hover_definition.is_empty() {
            return None;
        };

        let Some(bounds) = editor.range_to_bounds(&editor.extras.hover_definition.symbol_range)
        else {
            return None;
        };

        Some(window.insert_hitbox(bounds, gpui::HitboxBehavior::Normal))
    }
}
