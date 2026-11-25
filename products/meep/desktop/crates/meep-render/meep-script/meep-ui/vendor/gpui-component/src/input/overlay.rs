use std::collections::HashMap;
use std::rc::Rc;

use gpui::{AnyElement, App, Entity, EntityId, Global, IntoElement, WeakEntity, Window};
use ropey::Rope;

use super::{
    InputBaseState, InputModeKind,
    popovers::{CodeActionMenu, CompletionMenu, DiagnosticPopover, HoverPopover},
    search::SearchPanel,
};
use gpui_base::input::CompletionHighlighter;

struct InputOverlayRegistry<M: OverlayMode> {
    hosts: HashMap<EntityId, (WeakEntity<InputBaseState<M>>, InputOverlayHost<M>)>,
}

impl<M: OverlayMode> Default for InputOverlayRegistry<M> {
    fn default() -> Self {
        Self {
            hosts: HashMap::default(),
        }
    }
}

impl<M: OverlayMode> Global for InputOverlayRegistry<M> {}

struct InputOverlayHost<M: OverlayMode> {
    search: Entity<SearchPanel<M>>,
    search_signature: SearchSignature,
    /// The language-feature popovers. Only a code editor has them.
    lsp: Option<LspOverlays>,
}

/// Identifies one version of the search session, as the search panel shows it.
///
/// Everything the panel renders from is here, so an unchanged frame compares
/// equal and rebuilds nothing. `activation_revision` is what separates "the
/// session is open" from "the user just asked for search again": re-invoking an
/// open session leaves every other field alone, and without the revision the
/// second request would compare equal and be dropped.
#[derive(PartialEq, Eq, Default)]
struct SearchSignature {
    open: bool,
    replace_mode: bool,
    query: String,
    anchor_offset: Option<usize>,
    activation_revision: u64,
}

/// Identifies one version of an overlay's content.
///
/// Sync runs on every frame, so the check for "did this change" must not touch
/// the content itself: the completion list can hold hundreds of items, each
/// with its own documentation. The engine bumps a revision when it swaps the
/// content, and the popovers are keyed by cheap identity instead — a revision,
/// an `Rc` pointer, or a range.
#[derive(PartialEq, Eq, Default)]
struct OverlaySignature {
    open: bool,
    revision: u64,
}

/// The popovers driven by language features: completion, code actions, hover
/// and diagnostics. They belong to a code editor, so they are built and synced
/// by [`OverlayMode`], where the state's kind is concrete.
pub(crate) struct LspOverlays {
    completion: Entity<CompletionMenu>,
    code_actions: Entity<CodeActionMenu>,
    hover: Option<Entity<HoverPopover>>,
    diagnostic: Option<Entity<DiagnosticPopover>>,
    completion_signature: OverlaySignature,
    code_action_signature: OverlaySignature,
    hover_signature: Option<std::ops::Range<usize>>,
    diagnostic_signature: Option<std::rc::Rc<gpui_base::input::DiagnosticEntry>>,
    /// Highlighter last copied onto the completion menu.
    ///
    /// Compared by `Rc` identity, so swapping the host's closure repaints an
    /// open menu without rebuilding its items.
    completion_highlight: Option<Rc<CompletionHighlighter>>,
}

/// What the state read out of the engine for one sync pass.
///
/// Deliberately free of content: only what is needed to decide whether a
/// popover is shown and whether it changed. The content is read from the state
/// again, on the frames where it actually did.
pub(crate) struct LspSnapshot {
    completion: OverlaySignature,
    completion_start: Option<usize>,
    code_action: OverlaySignature,
    hover: Option<std::ops::Range<usize>>,
    diagnostic: Option<std::rc::Rc<gpui_base::input::DiagnosticEntry>>,
    cursor: usize,
}

impl LspSnapshot {
    fn has_overlay(&self) -> bool {
        self.completion.open
            || self.code_action.open
            || self.hover.is_some()
            || self.diagnostic.is_some()
    }
}

/// What the UI layer needs from each kind of input.
///
/// The UI layer is generic over the mode, so it cannot name the editor's state
/// type. This trait is the seam: the code-editor implementation is the only one
/// that builds language-feature popovers, and inside it the state is an
/// `Entity<EditorState>`, which those popovers take.
///
/// Entirely internal: nothing public is generic over the mode any more.
pub(crate) trait OverlayMode: InputModeKind + Sized {
    /// Reads the language-feature state this mode shows, if any.
    fn lsp_snapshot(_state: &InputBaseState<Self>, _cx: &App) -> Option<LspSnapshot> {
        None
    }

    /// Installs the routing that lets an open menu consume actions first.
    fn install_action_handler(_state: &Entity<InputBaseState<Self>>, _cx: &mut App) {}

    fn build_lsp(
        _state: &Entity<InputBaseState<Self>>,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Option<LspOverlays> {
        None
    }

    fn sync_lsp(
        _lsp: &mut LspOverlays,
        _state: &Entity<InputBaseState<Self>>,
        _snapshot: &LspSnapshot,
        _window: &mut Window,
        _cx: &mut App,
    ) {
    }
}

impl OverlayMode for crate::input::InputMode {}
impl OverlayMode for crate::input::TextareaMode {}

impl OverlayMode for crate::input::EditorMode {
    fn install_action_handler(state: &Entity<InputBaseState<Self>>, cx: &mut App) {
        let id = state.entity_id();
        state.update(cx, move |state, _| {
            state.set_overlay_action_handler(move |kind, action, window, cx| {
                let menus = cx
                    .try_global::<InputOverlayRegistry<Self>>()
                    .and_then(|registry| registry.hosts.get(&id))
                    .and_then(|(_, host)| host.lsp.as_ref())
                    .map(|lsp| (lsp.completion.clone(), lsp.code_actions.clone()));
                let Some((completion, code_actions)) = menus else {
                    return false;
                };
                match kind {
                    gpui_base::input::InputOverlayKind::Completion => {
                        completion.update(cx, |menu, cx| menu.handle_action(action, window, cx))
                    }
                    gpui_base::input::InputOverlayKind::CodeAction => {
                        code_actions.update(cx, |menu, cx| menu.handle_action(action, window, cx))
                    }
                }
            });
        });
    }

    fn lsp_snapshot(state: &InputBaseState<Self>, _cx: &App) -> Option<LspSnapshot> {
        let completion = state.completion_menu_state();
        let code_actions = state.code_action_menu_state();
        Some(LspSnapshot {
            completion: OverlaySignature {
                open: completion.open,
                revision: completion.revision(),
            },
            completion_start: completion.trigger_start_offset,
            code_action: OverlaySignature {
                open: code_actions.open,
                revision: code_actions.revision(),
            },
            hover: state
                .hover_popover()
                .map(|popover| popover.symbol_range.clone()),
            diagnostic: state.diagnostic_popover(),
            cursor: state.cursor(),
        })
    }

    fn build_lsp(
        state: &Entity<InputBaseState<Self>>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<LspOverlays> {
        Some(LspOverlays {
            completion: CompletionMenu::new(state.clone(), window, cx),
            code_actions: CodeActionMenu::new(state.clone(), window, cx),
            hover: None,
            diagnostic: None,
            completion_signature: OverlaySignature::default(),
            code_action_signature: OverlaySignature::default(),
            hover_signature: None,
            diagnostic_signature: None,
            completion_highlight: None,
        })
    }

    fn sync_lsp(
        lsp: &mut LspOverlays,
        state: &Entity<InputBaseState<Self>>,
        snapshot: &LspSnapshot,
        window: &mut Window,
        cx: &mut App,
    ) {
        let cursor = snapshot.cursor;

        let highlight = state.read(cx).lsp().completion_highlighter().clone();
        if lsp
            .completion_highlight
            .as_ref()
            .is_none_or(|current| !Rc::ptr_eq(current, &highlight))
        {
            lsp.completion_highlight = Some(highlight.clone());
            lsp.completion
                .update(cx, |menu, cx| menu.set_highlight(highlight, cx));
        }

        if snapshot.completion != lsp.completion_signature {
            lsp.completion_signature = OverlaySignature {
                open: snapshot.completion.open,
                revision: snapshot.completion.revision,
            };
            let open = snapshot.completion.open;
            let start = snapshot.completion_start;
            // Read the items only now, on a frame where they changed.
            let (query, items) = {
                let menu = state.read(cx).completion_menu_state();
                (menu.query.clone(), menu.items.clone())
            };
            lsp.completion.update(cx, |menu, cx| {
                if open {
                    menu.update_query(start.unwrap_or(cursor), query);
                    menu.show(cursor, items, window, cx);
                } else {
                    menu.hide(cx);
                }
            });
        }

        if snapshot.code_action != lsp.code_action_signature {
            lsp.code_action_signature = OverlaySignature {
                open: snapshot.code_action.open,
                revision: snapshot.code_action.revision,
            };
            let open = snapshot.code_action.open;
            let items = state.read(cx).code_action_menu_state().items.clone();
            lsp.code_actions.update(cx, |menu, cx| {
                if open {
                    menu.show(cursor, items, window, cx);
                } else {
                    menu.hide(cx);
                }
            });
        }

        // A hover popover is anchored to one symbol, so a new range means new
        // content and the same range means the same content.
        if snapshot.hover != lsp.hover_signature {
            lsp.hover_signature = snapshot.hover.clone();
            let popover = state
                .read(cx)
                .hover_popover()
                .map(|popover| (popover.symbol_range.clone(), popover.hover.clone()));
            lsp.hover = popover.map(|(symbol_range, hover)| {
                HoverPopover::new(state.clone(), symbol_range, &hover, cx)
            });
        }

        // The engine hands out the diagnostic behind an `Rc`, so pointer
        // identity already answers "is this the same entry".
        let diagnostic_changed = match (&snapshot.diagnostic, &lsp.diagnostic_signature) {
            (Some(new), Some(old)) => !std::rc::Rc::ptr_eq(new, old),
            (None, None) => false,
            _ => true,
        };
        if diagnostic_changed {
            lsp.diagnostic_signature = snapshot.diagnostic.clone();
            lsp.diagnostic = snapshot
                .diagnostic
                .as_deref()
                .map(|entry| DiagnosticPopover::new(entry, state.clone(), cx));
        }
    }
}

#[derive(Default)]
pub(super) struct InputOverlays {
    pub search: Option<AnyElement>,
    pub floating: Vec<AnyElement>,
}

impl InputOverlays {
    #[cfg(test)]
    fn len(&self) -> usize {
        usize::from(self.search.is_some()) + self.floating.len()
    }

    #[cfg(test)]
    fn is_empty(&self) -> bool {
        self.search.is_none() && self.floating.is_empty()
    }
}

impl<M: OverlayMode> InputOverlayHost<M> {
    fn new(state: Entity<InputBaseState<M>>, window: &mut Window, cx: &mut App) -> Self {
        Self {
            search: SearchPanel::new(state.clone(), window, cx),
            search_signature: SearchSignature::default(),
            lsp: M::build_lsp(&state, window, cx),
        }
    }

    fn sync(
        &mut self,
        state: &Entity<InputBaseState<M>>,
        window: &mut Window,
        cx: &mut App,
    ) -> InputOverlays {
        let snapshot = M::lsp_snapshot(state.read(cx), cx);
        let (search_open, replace_mode, activation_revision, search_session) = {
            let state = state.read(cx);
            let search = state.search_session();
            (
                search.open,
                search.replace_mode,
                state.search_activation_revision(),
                search.clone(),
            )
        };

        let panel_replace_mode = self.search.read(cx).replace_mode();
        self.search
            .update(cx, |panel, _| panel.sync_session(&search_session));

        let search_signature = SearchSignature {
            open: search_open,
            replace_mode,
            query: search_session.query.clone(),
            anchor_offset: search_session.anchor_offset,
            activation_revision,
        };
        if search_signature != self.search_signature {
            // The panel writes query and replacement-mode changes back into the
            // session. Re-showing it for that echo would select the query or steal
            // focus from replacement, so preserve changes the panel already holds.
            // External mode changes still move focus out of a hidden replace field.
            let was = &self.search_signature;
            let query_echo = search_open
                && was.open
                && (was.replace_mode == search_signature.replace_mode
                    || panel_replace_mode == search_signature.replace_mode)
                && was.anchor_offset == search_signature.anchor_offset
                && was.activation_revision == search_signature.activation_revision
                && self.search.read(cx).query(cx) == search_session.query;
            self.search_signature = search_signature;
            if !query_echo {
                self.search.update(cx, |panel, cx| {
                    if search_open {
                        let selected = Rope::from(search_session.query.clone());
                        let visible = search_session.anchor_offset.map(|offset| offset..offset);
                        panel.show_with_focus(
                            &selected,
                            replace_mode,
                            visible,
                            !cfg!(test),
                            window,
                            cx,
                        );
                    } else {
                        panel.hide_with_focus(!cfg!(test), window, cx);
                    }
                });
            }
        }

        if let (Some(lsp), Some(snapshot)) = (self.lsp.as_mut(), snapshot.as_ref()) {
            M::sync_lsp(lsp, state, snapshot, window, cx);
        }

        let search = search_open.then(|| self.search.clone().into_any_element());
        let mut floating = Vec::with_capacity(4);
        if let (Some(lsp), Some(snapshot)) = (self.lsp.as_ref(), snapshot.as_ref()) {
            if snapshot.completion.open {
                floating.push(lsp.completion.clone().into_any_element());
            }
            if snapshot.code_action.open {
                floating.push(lsp.code_actions.clone().into_any_element());
            }
            if let Some(hover) = lsp.hover.as_ref() {
                floating.push(hover.clone().into_any_element());
            }
            if let Some(diagnostic) = lsp.diagnostic.as_ref() {
                floating.push(diagnostic.clone().into_any_element());
            }
        }
        InputOverlays { search, floating }
    }
}

pub(super) fn render_overlays<M: OverlayMode>(
    state: &Entity<InputBaseState<M>>,
    window: &mut Window,
    cx: &mut App,
) -> InputOverlays {
    M::install_action_handler(state, cx);
    let has_overlay = {
        let state = state.read(cx);
        state.search_session().open
            || M::lsp_snapshot(state, cx).is_some_and(|lsp| lsp.has_overlay())
    };
    if !has_overlay {
        if cx.has_global::<InputOverlayRegistry<M>>() {
            let registry = cx.global_mut::<InputOverlayRegistry<M>>();
            registry.hosts.remove(&state.entity_id());
            registry
                .hosts
                .retain(|_, (owner, _)| owner.upgrade().is_some());
        }
        return InputOverlays::default();
    }

    if !cx.has_global::<InputOverlayRegistry<M>>() {
        cx.set_global(InputOverlayRegistry::<M>::default());
    }

    let id = state.entity_id();
    let mut host = cx
        .global_mut::<InputOverlayRegistry<M>>()
        .hosts
        .remove(&id)
        .map(|(_, host)| host)
        .unwrap_or_else(|| InputOverlayHost::new(state.clone(), window, cx));
    let overlays = host.sync(state, window, cx);
    cx.global_mut::<InputOverlayRegistry<M>>()
        .hosts
        .insert(id, (state.downgrade(), host));
    overlays
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{AppContext as _, Render, SharedString, div};
    use gpui_base::input::CodeActionItem;
    use gpui_base::input::DiagnosticEntry;
    use lsp_types::{CodeAction, CompletionItem, Hover, HoverContents, MarkedString};

    struct OverlayProbe {
        state: Entity<crate::input::EditorState>,
    }

    impl Render for OverlayProbe {
        fn render(
            &mut self,
            _window: &mut Window,
            _cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            div()
        }
    }

    /// Asking for search again, while it is already open, must re-select the query.
    ///
    /// Re-invoking search leaves every other part of the session identical, so a
    /// sync keyed only on that state reads it as an unchanged frame and drops the
    /// request: the field keeps whatever caret the user left in it and the
    /// shortcut looks dead. `activation_revision` is what carries the second
    /// request through, and the echo guard below it is what must survive that.
    #[gpui::test]
    fn reopening_search_reselects_the_query(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (probe, cx) = cx.add_window_view(|window, cx| OverlayProbe {
            state: cx.new(|cx| crate::input::EditorState::new(window, cx).searchable(true)),
        });
        let state = probe.read_with(cx, |probe, _| probe.state.clone());

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_value("foo bar foo", window, cx);
                state.set_selected_range(0..3, cx);
                state.open_search(false, cx);
            });

            let mut host = InputOverlayHost::new(state.clone(), window, cx);
            host.sync(&state, window, cx);

            let search_input = host.search.read(cx).search_input().clone();
            assert_eq!(search_input.read(cx).value(), "foo");
            assert_eq!(
                search_input.read(cx).selected_range(),
                0..3,
                "opening search selects the query it seeded the field with"
            );

            // The user drops the caret into the field. An untouched frame must
            // leave it there — this is the echo guard, and a fix that reshows the
            // panel on every frame would fail here instead of silently annoying.
            search_input.update(cx, |input, cx| input.unselect(window, cx));
            host.sync(&state, window, cx);
            assert!(
                search_input.read(cx).selected_range().is_empty(),
                "an unchanged frame must not touch the field"
            );

            // The shortcut again, with the session already open and nothing else
            // about it moved.
            state.update(cx, |state, cx| state.open_search(false, cx));
            host.sync(&state, window, cx);
            assert_eq!(
                search_input.read(cx).selected_range(),
                0..3,
                "re-invoking search must select the query again"
            );
        });
    }

    /// Reopening search must preserve navigation already owned by Base.
    ///
    /// Closing and reopening Find keeps the previous occurrence in browsers.
    /// Neither Base reopening the session nor the styled panel echoing its
    /// retained query may reset the current match to zero.
    #[gpui::test]
    fn reopening_search_panel_preserves_the_previous_match(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (probe, cx) = cx.add_window_view(|window, cx| OverlayProbe {
            state: cx.new(|cx| crate::input::EditorState::new(window, cx).searchable(true)),
        });
        let state = probe.read_with(cx, |probe, _| probe.state.clone());

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_value("foo bar foo baz foo", window, cx);
                state.open_search(false, cx);
                state.set_search_query("foo", true, cx);
                assert_eq!(state.next_search_match(cx), Some(8..11));
                assert_eq!(state.search_session().matcher.current_match_index(), 1);
                state.close_search(cx);
                state.open_search(false, cx);
                assert_eq!(state.search_session().matcher.current_match_index(), 1);
            });

            let mut host = InputOverlayHost::new(state.clone(), window, cx);
            host.sync(&state, window, cx);

            state.read_with(cx, |state, _| {
                assert_eq!(state.search_session().matcher.current_match_index(), 1);
                assert_eq!(state.search_session().matcher.label(), "2/3");
            });

            state.update(cx, |state, cx| {
                assert_eq!(state.next_search_match(cx), Some(16..19));
            });
        });
    }

    /// A frame that changed nothing must not rebuild the popovers.
    ///
    /// Sync runs every frame, so the change check has to be cheap and stable.
    /// It is keyed on a revision the engine bumps when it swaps the content;
    /// forgetting to bump, or comparing the content itself again, both show up
    /// here.
    #[gpui::test]
    fn unchanged_content_keeps_the_overlay_signature(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (probe, cx) = cx.add_window_view(|window, cx| OverlayProbe {
            state: cx.new(|cx| crate::input::EditorState::new(window, cx).language("sql")),
        });
        let state = probe.read_with(cx, |probe, _| probe.state.clone());

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.present_completion_items(
                    0,
                    "f",
                    vec![CompletionItem {
                        label: "foo".into(),
                        ..Default::default()
                    }],
                    cx,
                );
            });

            let mut host = InputOverlayHost::new(state.clone(), window, cx);
            host.sync(&state, window, cx);
            let after_first = host.lsp.as_ref().unwrap().completion_signature.revision;

            // A second pass over untouched content.
            host.sync(&state, window, cx);
            assert_eq!(
                host.lsp.as_ref().unwrap().completion_signature.revision,
                after_first,
                "an unchanged frame must not bump the signature"
            );

            // Swapping the items must be noticed.
            state.update(cx, |state, cx| {
                state.present_completion_items(
                    0,
                    "f",
                    vec![CompletionItem {
                        label: "bar".into(),
                        ..Default::default()
                    }],
                    cx,
                );
            });
            host.sync(&state, window, cx);
            assert_ne!(
                host.lsp.as_ref().unwrap().completion_signature.revision,
                after_first,
                "new items must be noticed"
            );
        });
    }

    #[gpui::test]
    fn facade_materializes_all_base_overlay_sessions(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (probe, cx) = cx.add_window_view(|window, cx| OverlayProbe {
            state: cx.new(|cx| {
                crate::input::EditorState::new(window, cx)
                    .language("sql")
                    .searchable(true)
                    .replaceable(true)
            }),
        });
        let state = probe.read_with(cx, |probe, _| probe.state.clone());
        cx.update(|window, cx| {
            assert!(render_overlays(&state, window, cx).is_empty());
            assert!(state.read(cx).has_overlay_action_handler());
            state.update(cx, |state, cx| {
                state.set_value("foo bar foo", window, cx);
                state.set_selected_range(4..7, cx);
                state.open_search(true, cx);
                assert_eq!(state.search_session().query, "bar");
                assert!(state.search_session().replace_mode);
                state.present_completion_items(
                    0,
                    "f",
                    vec![CompletionItem {
                        label: "foo".into(),
                        ..Default::default()
                    }],
                    cx,
                );
                state.present_code_actions(
                    vec![CodeActionItem {
                        provider_id: SharedString::from("test"),
                        action: CodeAction {
                            title: "Fix".into(),
                            ..Default::default()
                        },
                    }],
                    cx,
                );
                state.present_hover(
                    0..1,
                    Hover {
                        contents: HoverContents::Scalar(MarkedString::String("docs".into())),
                        range: None,
                    },
                    cx,
                );
                state.present_diagnostic(DiagnosticEntry::default(), cx);
            });

            let mut host = InputOverlayHost::new(state.clone(), window, cx);
            let overlays = host.sync(&state, window, cx);
            assert!(overlays.search.is_some());
            assert_eq!(overlays.floating.len(), 4);
            assert_eq!(overlays.len(), 5);
            assert_eq!(render_overlays(&state, window, cx).len(), 5);
            assert!(
                cx.global::<InputOverlayRegistry<crate::input::EditorMode>>()
                    .hosts
                    .contains_key(&state.entity_id())
            );

            state.update(cx, |state, cx| {
                assert!(state.route_overlay_action(Box::new(super::super::Escape), window, cx));
                assert!(!state.completion_menu_state().open);
                state.dismiss_code_action_overlay(cx);
                state.close_search(cx);
                state.clear_hover_state(cx);
                state.clear_diagnostic_popover(cx);
            });
            assert!(host.sync(&state, window, cx).is_empty());
            assert!(render_overlays(&state, window, cx).is_empty());
            assert!(
                !cx.global::<InputOverlayRegistry<crate::input::EditorMode>>()
                    .hosts
                    .contains_key(&state.entity_id())
            );
        });

        let dropped_owner = cx.update(|window, cx| {
            let ephemeral = cx.new(|cx| {
                crate::input::EditorState::new(window, cx)
                    .language("sql")
                    .searchable(true)
            });
            ephemeral.update(cx, |state, cx| state.open_search(false, cx));
            assert_eq!(render_overlays(&ephemeral, window, cx).len(), 1);
            ephemeral.update(cx, |state, cx| state.close_search(cx));
            assert!(render_overlays(&ephemeral, window, cx).is_empty());
            assert!(
                !cx.global::<InputOverlayRegistry<crate::input::EditorMode>>()
                    .hosts
                    .contains_key(&ephemeral.entity_id())
            );
            let owner = ephemeral.downgrade();
            drop(ephemeral);
            owner
        });
        cx.run_until_parked();
        assert!(dropped_owner.upgrade().is_none());
    }
}
