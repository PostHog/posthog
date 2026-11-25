use std::rc::Rc;

use gpui::{
    Action, AnyElement, App, AppContext, Context, DismissEvent, Empty, Entity, EventEmitter,
    Half as _, InteractiveElement as _, IntoElement, ParentElement, Pixels, Render, RenderOnce,
    Styled, StyledText, Subscription, WeakEntity, Window, deferred, div, prelude::FluentBuilder,
    px, relative,
};
use gpui_base::TestSupportExt as _;
pub(crate) use gpui_base::input::CodeActionItem;

const MAX_MENU_WIDTH: Pixels = px(320.);
const MAX_MENU_HEIGHT: Pixels = px(480.);

use crate::{
    ActiveTheme, IndexPath, Selectable, actions, h_flex,
    input::{
        self, EditorState,
        popovers::{CaretAnchoredPopup, editor_popover},
    },
    list::{List, ListDelegate, ListEvent, ListState},
};

struct MenuDelegate {
    menu: Entity<CodeActionMenu>,
    items: Vec<Rc<CodeActionItem>>,
    selected_ix: usize,
}

impl MenuDelegate {
    fn set_items(&mut self, items: Vec<CodeActionItem>) {
        self.items = items.into_iter().map(Rc::new).collect();
        self.selected_ix = 0;
    }

    fn selected_item(&self) -> Option<&Rc<CodeActionItem>> {
        self.items.get(self.selected_ix)
    }
}

#[derive(IntoElement)]
struct MenuItem {
    ix: usize,
    item: Rc<CodeActionItem>,
    children: Vec<AnyElement>,
    selected: bool,
}

impl MenuItem {
    fn new(ix: usize, item: Rc<CodeActionItem>) -> Self {
        Self {
            ix,
            item,
            children: vec![],
            selected: false,
        }
    }
}
impl Selectable for MenuItem {
    fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn is_selected(&self) -> bool {
        self.selected
    }
}

impl ParentElement for MenuItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl RenderOnce for MenuItem {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let item = self.item;

        let highlights = vec![];

        h_flex()
            .id(self.ix)
            .gap_2()
            .p_1()
            .text_xs()
            .line_height(relative(1.))
            .rounded(cx.theme().radius.half())
            .hover(|this| this.bg(cx.theme().accent.opacity(0.8)))
            .when(self.selected, |this| {
                this.bg(cx.theme().tokens.accent)
                    .text_color(cx.theme().accent_foreground)
            })
            .child(
                div().child(StyledText::new(item.action.title.clone()).with_highlights(highlights)),
            )
            .children(self.children)
    }
}

impl EventEmitter<DismissEvent> for MenuDelegate {}

impl ListDelegate for MenuDelegate {
    type Item = MenuItem;

    fn items_count(&self, _: usize, _: &gpui::App) -> usize {
        self.items.len()
    }

    fn render_item(
        &mut self,
        ix: crate::IndexPath,
        _: &mut Window,
        _: &mut Context<ListState<Self>>,
    ) -> Option<Self::Item> {
        let item = self.items.get(ix.row)?;
        Some(MenuItem::new(ix.row, item.clone()))
    }

    fn set_selected_index(
        &mut self,
        ix: Option<crate::IndexPath>,
        _: &mut Window,
        cx: &mut Context<ListState<Self>>,
    ) {
        self.selected_ix = ix.map(|i| i.row).unwrap_or(0);
        cx.notify();
    }

    fn confirm(&mut self, _: bool, window: &mut Window, cx: &mut Context<ListState<Self>>) {
        let Some(item) = self.selected_item() else {
            return;
        };

        self.menu.update(cx, |this, cx| {
            this.select_item(&item, window, cx);
        });
    }
}

/// A context menu for code completions and code actions.
pub struct CodeActionMenu {
    offset: usize,
    state: WeakEntity<EditorState>,
    list: Entity<ListState<MenuDelegate>>,
    open: bool,

    _subscriptions: Vec<Subscription>,
}

impl CodeActionMenu {
    /// Creates a new `CompletionMenu` with the given offset and completion items.
    ///
    /// NOTE: This element should not call from EditorState::new, unless that will stack overflow.
    pub(crate) fn new(
        state: Entity<EditorState>,
        window: &mut Window,
        cx: &mut App,
    ) -> Entity<Self> {
        cx.new(|cx| {
            let view = cx.entity();
            let menu = MenuDelegate {
                menu: view,
                items: vec![],
                selected_ix: 0,
            };

            let list = cx.new(|cx| ListState::new(menu, window, cx));

            let _subscriptions =
                vec![
                    cx.subscribe(&list, |this: &mut Self, _, ev: &ListEvent, cx| {
                        match ev {
                            ListEvent::Confirm(_) => {
                                this.hide(cx);
                            }
                            _ => {}
                        }
                        cx.notify();
                    }),
                ];

            Self {
                offset: 0,
                state: state.downgrade(),
                list,
                open: false,
                _subscriptions,
            }
        })
    }

    fn select_item(&mut self, item: &CodeActionItem, window: &mut Window, cx: &mut Context<Self>) {
        let state = self.state.clone();
        let item = item.clone();

        cx.spawn_in(window, {
            async move |_, cx| {
                state.update_in(cx, |state, window, cx| {
                    state.perform_code_action(&item, window, cx);
                })
            }
        })
        .detach();

        self.hide(cx);
    }

    pub(crate) fn handle_action(
        &mut self,
        action: Box<dyn Action>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> bool {
        if !self.open {
            return false;
        }

        cx.propagate();
        if input::Enter::is_primary(&*action) {
            self.on_action_enter(window, cx);
        } else if action.partial_eq(&input::Escape) {
            self.on_action_escape(window, cx);
        } else if action.partial_eq(&input::MoveUp) {
            self.on_action_up(window, cx);
        } else if action.partial_eq(&input::MoveDown) {
            self.on_action_down(window, cx);
        } else {
            return false;
        }

        true
    }

    fn on_action_enter(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(item) = self.list.read(cx).delegate().selected_item().cloned() else {
            return;
        };
        self.select_item(&item, window, cx);
    }

    fn on_action_escape(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        self.hide(cx);
    }

    fn on_action_up(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.list.update(cx, |this, cx| {
            this.on_action_select_prev(&actions::SelectUp, window, cx)
        });
    }

    fn on_action_down(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.list.update(cx, |this, cx| {
            this.on_action_select_next(&actions::SelectDown, window, cx)
        });
    }

    /// Hide the completion menu and reset the trigger start offset.
    pub(crate) fn hide(&mut self, cx: &mut Context<Self>) {
        self.open = false;
        let state = self.state.clone();
        cx.spawn(async move |_, cx| {
            let _ = state.update(cx, |state, cx| state.dismiss_code_action_overlay(cx));
        })
        .detach();
        cx.notify();
    }

    pub(crate) fn show(
        &mut self,
        offset: usize,
        items: impl Into<Vec<CodeActionItem>>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let items = items.into();
        self.offset = offset;
        self.open = true;
        self.list.update(cx, |this, cx| {
            this.delegate_mut().set_items(items);
            this.set_selected_index(Some(IndexPath::new(0)), window, cx);
        });

        cx.notify();
    }
}

impl Render for CodeActionMenu {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if !self.open {
            return Empty.into_any_element();
        }

        if self.list.read(cx).delegate().items.is_empty() {
            self.open = false;
            return Empty.into_any_element();
        }

        // The anchor is resolved in the popup's deferred prepaint from the
        // input's current-frame geometry; the content below is built there.
        let list = self.list.clone();
        let menu = cx.weak_entity();

        deferred(CaretAnchoredPopup::new(
            self.state.clone(),
            move |anchor, window, cx| {
                let max_width = MAX_MENU_WIDTH.min(window.bounds().size.width - anchor.x);

                // A flex root measures to its contents; a block root would
                // stretch its outside-click hitbox across the viewport.
                div()
                    .flex()
                    .child(
                        editor_popover("code-action-menu", cx)
                            .test_support()
                            .max_w(max_width)
                            .min_w(px(120.))
                            .child(List::new(&list).max_h(MAX_MENU_HEIGHT)),
                    )
                    .on_mouse_down_out({
                        let menu = menu.clone();
                        move |_, _, cx: &mut App| {
                            if let Some(menu) = menu.upgrade() {
                                menu.update(cx, |menu, cx| menu.hide(cx));
                            }
                        }
                    })
                    .into_any_element()
            },
        ))
        .with_priority(gpui_base::POPUP_PRIORITY)
        .into_any_element()
    }
}
