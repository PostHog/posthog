use super::*;
use crate::input::EditorMode;
use std::ops::Range;

use lsp_types::{CompletionItem, Hover};

#[derive(Clone, Debug, Default)]
pub struct CompletionMenuState {
    pub open: bool,
    pub trigger_start_offset: Option<usize>,
    pub query: String,
    pub items: Vec<CompletionItem>,
    revision: u64,
}

impl CompletionMenuState {
    /// Bumped whenever the content changes.
    ///
    /// A renderer that mirrors this menu compares revisions to decide whether
    /// to rebuild, so it never has to compare the item list itself.
    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub(super) fn bump(&mut self) {
        self.revision = self.revision.wrapping_add(1);
    }
}

#[derive(Clone, Debug, Default)]
pub struct CodeActionMenuState {
    pub open: bool,
    pub items: Vec<CodeActionItem>,
    revision: u64,
}

impl CodeActionMenuState {
    /// Bumped whenever the content changes. See [`CompletionMenuState::revision`].
    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub(super) fn bump(&mut self) {
        self.revision = self.revision.wrapping_add(1);
    }
}

#[derive(Clone, Debug)]
pub struct HoverPopoverState {
    pub symbol_range: Range<usize>,
    pub hover: Hover,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct ContextMenuContent {
    pub(crate) completion: CompletionMenuState,
    pub(crate) code_action: CodeActionMenuState,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputOverlayKind {
    Completion,
    CodeAction,
}

impl InputBaseState<EditorMode> {
    pub fn present_completion_items(
        &mut self,
        trigger_start_offset: usize,
        query: impl Into<String>,
        items: Vec<CompletionItem>,
        cx: &mut Context<Self>,
    ) {
        self.extras
            .context_menu_content
            .completion
            .trigger_start_offset = Some(trigger_start_offset);
        self.extras.context_menu_content.completion.query = query.into();
        self.extras.context_menu_content.completion.items = items;
        self.extras.context_menu_content.completion.open =
            !self.extras.context_menu_content.completion.items.is_empty();
        self.extras.context_menu_content.completion.bump();
        cx.notify();
    }

    pub fn present_code_actions(&mut self, items: Vec<CodeActionItem>, cx: &mut Context<Self>) {
        self.extras.context_menu_content.code_action.items = items;
        self.extras.context_menu_content.code_action.open = !self
            .extras
            .context_menu_content
            .code_action
            .items
            .is_empty();
        self.extras.context_menu_content.code_action.bump();
        cx.notify();
    }

    pub fn present_hover(
        &mut self,
        symbol_range: Range<usize>,
        hover: Hover,
        cx: &mut Context<Self>,
    ) {
        self.extras.hover_popover = Some(HoverPopoverState {
            symbol_range,
            hover,
        });
        cx.notify();
    }

    pub fn present_diagnostic(
        &mut self,
        diagnostic: crate::input::DiagnosticEntry,
        cx: &mut Context<Self>,
    ) {
        self.diagnostic_popover = Some(Rc::new(diagnostic));
        cx.notify();
    }

    pub fn clear_diagnostic_popover(&mut self, cx: &mut Context<Self>) {
        if self.diagnostic_popover.take().is_some() {
            cx.notify();
        }
    }

    pub fn route_overlay_action(
        &mut self,
        action: Box<dyn gpui::Action>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> bool {
        self.handle_action_for_context_menu(action, window, cx)
    }

    pub fn set_overlay_action_handler(
        &mut self,
        handler: impl Fn(
            InputOverlayKind,
            Box<dyn gpui::Action>,
            &mut Window,
            &mut Context<InputBaseState<EditorMode>>,
        ) -> bool
        + 'static,
    ) {
        self.overlay_action_handler = Some(Rc::new(handler));
    }

    pub fn has_overlay_action_handler(&self) -> bool {
        self.overlay_action_handler.is_some()
    }

    pub fn dismiss_completion_overlay(&mut self, cx: &mut Context<Self>) {
        if self.extras.context_menu_content.completion.open {
            self.extras.context_menu_content.completion.open = false;
            cx.notify();
        }
    }

    pub fn dismiss_code_action_overlay(&mut self, cx: &mut Context<Self>) {
        if self.extras.context_menu_content.code_action.open {
            self.extras.context_menu_content.code_action.open = false;
            cx.notify();
        }
    }

    pub fn insert_completion(
        &mut self,
        item: &CompletionItem,
        fallback_range: Range<usize>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let mut range = fallback_range;
        let mut new_text = item.label.clone();
        if let Some(edit) = item.text_edit.as_ref() {
            match edit {
                lsp_types::CompletionTextEdit::Edit(edit) => {
                    new_text.clone_from(&edit.new_text);
                    range = self.text.position_to_offset(&edit.range.start)
                        ..self.text.position_to_offset(&edit.range.end);
                }
                lsp_types::CompletionTextEdit::InsertAndReplace(edit) => {
                    new_text.clone_from(&edit.new_text);
                    range = self.text.position_to_offset(&edit.replace.start)
                        ..self.text.position_to_offset(&edit.replace.end);
                }
            }
        } else if let Some(insert_text) = item.insert_text.as_ref() {
            new_text.clone_from(insert_text);
            range = range.end..range.end;
        }
        self.completion_inserting = true;
        let range = self.range_to_utf16(&range);
        self.replace_text_in_range_silent(Some(range), &new_text, window, cx);
        self.completion_inserting = false;
        self.focus(window, cx);
    }

    #[doc(hidden)]
    pub fn completion_menu_state(&self) -> &CompletionMenuState {
        &self.extras.context_menu_content.completion
    }

    #[doc(hidden)]
    pub fn code_action_menu_state(&self) -> &CodeActionMenuState {
        &self.extras.context_menu_content.code_action
    }

    pub fn hover_popover(&self) -> Option<&HoverPopoverState> {
        self.extras.hover_popover.as_ref()
    }

    pub fn dismiss_lsp_overlays(&mut self, cx: &mut Context<Self>) {
        self.hide_context_menu(cx);
        self.clear_hover_state(cx);
    }
}
