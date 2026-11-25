use crate::{
    InteractiveElementExt as _, Selectable, Sizable,
    actions::{Cancel, SelectLeft, SelectRight},
    button::{Button, ButtonVariants},
    global_state::GlobalState,
    h_flex,
    menu::PopupMenu,
    scroll::ScrollableMask,
};
use gpui::{
    App, AppContext as _, ClickEvent, Context, DismissEvent, Entity, FocusHandle, Focusable,
    InteractiveElement as _, IntoElement, KeyBinding, MouseButton, OwnedMenu, ParentElement,
    Render, Role, ScrollHandle, SharedString, StatefulInteractiveElement, Styled, Subscription,
    Window, anchored, deferred, div, prelude::FluentBuilder, px,
};

const CONTEXT: &str = "AppMenuBar";
pub fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
        KeyBinding::new("left", SelectLeft, Some(CONTEXT)),
        KeyBinding::new("right", SelectRight, Some(CONTEXT)),
    ]);
}

/// The application menu bar, for Windows and Linux.
pub struct AppMenuBar {
    menus: Vec<Entity<AppMenu>>,
    selected_index: Option<usize>,
    action_context: Option<FocusHandle>,
    scroll_handle: ScrollHandle,
}

impl AppMenuBar {
    /// Create a new app menu bar.
    pub fn new(cx: &mut App) -> Entity<Self> {
        cx.new(|cx| {
            let mut this = Self {
                selected_index: None,
                action_context: None,
                menus: Vec::new(),
                scroll_handle: ScrollHandle::new(),
            };
            this.reload(cx);
            this
        })
    }

    /// Reload the menus from the app.
    pub fn reload(&mut self, cx: &mut Context<Self>) {
        let menu_bar = cx.entity();
        let menus: Vec<OwnedMenu> = GlobalState::global(cx)
            .app_menus()
            .iter()
            .cloned()
            .collect();
        self.menus = menus
            .iter()
            .enumerate()
            .map(|(ix, menu)| AppMenu::new(ix, menu, menu_bar.clone(), cx))
            .collect();
        self.selected_index = None;
        self.action_context = None;
        cx.notify();
    }

    fn on_move_left(&mut self, _: &SelectLeft, window: &mut Window, cx: &mut Context<Self>) {
        let Some(selected_index) = self.selected_index else {
            return;
        };

        let new_ix = if selected_index == 0 {
            self.menus.len().saturating_sub(1)
        } else {
            selected_index.saturating_sub(1)
        };
        self.set_selected_index(Some(new_ix), window, cx);
    }

    fn on_move_right(&mut self, _: &SelectRight, window: &mut Window, cx: &mut Context<Self>) {
        let Some(selected_index) = self.selected_index else {
            return;
        };

        let new_ix = if selected_index + 1 >= self.menus.len() {
            0
        } else {
            selected_index + 1
        };
        self.set_selected_index(Some(new_ix), window, cx);
    }

    fn on_cancel(&mut self, _: &Cancel, window: &mut Window, cx: &mut Context<Self>) {
        self.set_selected_index(None, window, cx);
    }

    fn set_selected_index(
        &mut self,
        ix: Option<usize>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.selected_index.is_none() && ix.is_some() {
            self.action_context = window.focused(cx);
        } else if ix.is_none() {
            if let Some(action_context) = self.action_context.as_ref() {
                action_context.focus(window, cx);
            }
            self.action_context = None;
        }

        self.selected_index = ix;
        cx.notify();
    }

    #[inline]
    fn has_activated_menu(&self) -> bool {
        self.selected_index.is_some()
    }
}

impl Render for AppMenuBar {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .relative()
            .size_full()
            .child(
                h_flex()
                    .id("app-menu-bar")
                    .role(Role::MenuBar)
                    .key_context(CONTEXT)
                    .on_action(cx.listener(Self::on_move_left))
                    .on_action(cx.listener(Self::on_move_right))
                    .on_action(cx.listener(Self::on_cancel))
                    .size_full()
                    .gap_x_1()
                    .overflow_x_scroll()
                    .lock_scroll_axis()
                    .track_scroll(&self.scroll_handle)
                    .children(self.menus.clone()),
            )
            .child(ScrollableMask::vertical_wheel(&self.scroll_handle))
    }
}

/// A menu in the menu bar.
pub(super) struct AppMenu {
    menu_bar: Entity<AppMenuBar>,
    ix: usize,
    name: SharedString,
    menu: OwnedMenu,
    popup_menu: Option<Entity<PopupMenu>>,

    _subscription: Option<Subscription>,
}

impl AppMenu {
    pub(super) fn new(
        ix: usize,
        menu: &OwnedMenu,
        menu_bar: Entity<AppMenuBar>,
        cx: &mut App,
    ) -> Entity<Self> {
        let name = menu.name.clone();
        cx.new(|_| Self {
            ix,
            menu_bar,
            name,
            menu: menu.clone(),
            popup_menu: None,
            _subscription: None,
        })
    }

    /// Whether this menu's popup is the one the menu bar currently has open.
    fn is_open(&self, cx: &App) -> bool {
        self.menu_bar.read(cx).selected_index == Some(self.ix)
    }

    fn build_popup_menu(
        &mut self,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Entity<PopupMenu> {
        let action_context = self.menu_bar.read(cx).action_context.clone();
        let popup_menu = match self.popup_menu.as_ref() {
            None => {
                let items = self.menu.items.clone();
                let popup_menu = PopupMenu::build(window, cx, |menu, window, cx| {
                    menu.with_menu_items(items, window, cx)
                });
                popup_menu.update(cx, |menu, cx| {
                    menu.set_action_context(action_context.clone(), cx);
                });
                self._subscription =
                    Some(cx.subscribe_in(&popup_menu, window, Self::handle_dismiss));
                self.popup_menu = Some(popup_menu.clone());

                popup_menu
            }
            Some(menu) => {
                menu.update(cx, |menu, cx| {
                    menu.set_action_context(action_context.clone(), cx);
                });
                menu.clone()
            }
        };

        let focus_handle = popup_menu.read(cx).focus_handle(cx);
        if !focus_handle.contains_focused(window, cx) {
            focus_handle.focus(window, cx);
        }

        popup_menu
    }

    fn handle_dismiss(
        &mut self,
        _: &Entity<PopupMenu>,
        _: &DismissEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self._subscription.take();
        self.popup_menu.take();
        self.menu_bar.update(cx, |state, cx| {
            state.on_cancel(&Cancel, window, cx);
        });
    }

    fn handle_trigger_click(
        &mut self,
        event: &ClickEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if matches!(event, ClickEvent::Mouse(_)) {
            return;
        }

        self.toggle(window, cx);
    }

    fn toggle(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let is_open = self.is_open(cx);
        _ = self.menu_bar.update(cx, |state, cx| {
            let new_ix = if is_open { None } else { Some(self.ix) };
            state.set_selected_index(new_ix, window, cx);
        });
    }

    fn handle_hover(&mut self, hovered: &bool, window: &mut Window, cx: &mut Context<Self>) {
        if !*hovered {
            return;
        }

        let has_activated_menu = self.menu_bar.read(cx).has_activated_menu();
        if !has_activated_menu {
            return;
        }

        _ = self.menu_bar.update(cx, |state, cx| {
            state.set_selected_index(Some(self.ix), window, cx);
        });
    }
}

impl Render for AppMenu {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let is_open = self.is_open(cx);

        div()
            .id(self.ix)
            .relative()
            .child(
                Button::new("menu")
                    .small()
                    .py_0p5()
                    .compact()
                    .ghost()
                    .label(self.name.clone())
                    .open(is_open)
                    .on_mouse_down(
                        MouseButton::Left,
                        window.listener_for(&cx.entity(), move |this, _, window, cx| {
                            // Stop propagation to avoid dragging the window.
                            window.prevent_default();
                            cx.stop_propagation();
                            this.toggle(window, cx);
                        }),
                    )
                    .on_click(cx.listener(Self::handle_trigger_click)),
            )
            .on_hover(cx.listener(Self::handle_hover))
            .when(is_open, |this| {
                this.child(deferred(
                    anchored()
                        .anchor(gpui::Anchor::TopLeft)
                        .snap_to_window_with_margin(px(8.))
                        .child(
                            div()
                                .size_full()
                                .occlude()
                                .top_1()
                                .child(self.build_popup_menu(window, cx)),
                        ),
                ))
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use gpui::TestAppContext;

    struct TestRoot {
        menu_bar: Entity<AppMenuBar>,
        first_focus: FocusHandle,
        second_focus: FocusHandle,
    }

    impl Render for TestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .child(div().id("first").track_focus(&self.first_focus))
                .child(div().id("second").track_focus(&self.second_focus))
                .child(self.menu_bar.clone())
        }
    }

    #[gpui::test]
    fn preserves_action_context_while_switching_menus(cx: &mut TestAppContext) {
        let (root, cx) = cx.add_window_view(|window, cx| {
            let first_focus = cx.focus_handle();
            let second_focus = cx.focus_handle();
            first_focus.focus(window, cx);

            TestRoot {
                menu_bar: cx.new(|_| AppMenuBar {
                    menus: Vec::new(),
                    selected_index: None,
                    action_context: None,
                    scroll_handle: ScrollHandle::new(),
                }),
                first_focus,
                second_focus,
            }
        });

        let (menu_bar, first_focus, second_focus) = root.read_with(cx, |root, _| {
            (
                root.menu_bar.clone(),
                root.first_focus.clone(),
                root.second_focus.clone(),
            )
        });

        menu_bar.update_in(cx, |menu_bar, window, cx| {
            menu_bar.set_selected_index(Some(0), window, cx);
            assert_eq!(menu_bar.action_context.as_ref(), Some(&first_focus));

            second_focus.focus(window, cx);
            menu_bar.set_selected_index(Some(1), window, cx);
            assert_eq!(menu_bar.action_context.as_ref(), Some(&first_focus));

            menu_bar.set_selected_index(None, window, cx);
            assert!(menu_bar.action_context.is_none());
            assert_eq!(window.focused(cx).as_ref(), Some(&first_focus));

            second_focus.focus(window, cx);
            menu_bar.set_selected_index(Some(0), window, cx);
            assert_eq!(menu_bar.action_context.as_ref(), Some(&second_focus));
        });
    }
}
