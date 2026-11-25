use crate::{ActiveTheme, Disableable, Icon, Selectable, Sizable as _, StyledExt, h_flex};
use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, InteractiveElement, Interactivity, IntoElement,
    MouseButton, MouseDownEvent, MouseMoveEvent, ParentElement, RenderOnce, SharedString, Stateful,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};
use gpui_base::TestSupportExt as _;
use smallvec::SmallVec;
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
enum ListItemMode {
    #[default]
    Entry,
    Separator,
}

impl ListItemMode {
    #[inline]
    fn is_separator(&self) -> bool {
        matches!(self, ListItemMode::Separator)
    }
}

#[derive(IntoElement)]
pub struct ListItem {
    base: Stateful<Div>,
    mode: ListItemMode,
    style: StyleRefinement,
    disabled: bool,
    selected: bool,
    secondary_selected: bool,
    confirmed: bool,
    check_icon: Option<Icon>,
    on_click: Option<Box<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>>,
    on_mouse_down:
        HashMap<MouseButton, Box<dyn Fn(&MouseDownEvent, &mut Window, &mut App) + 'static>>,
    on_mouse_enter: Option<Box<dyn Fn(&MouseMoveEvent, &mut Window, &mut App) + 'static>>,
    suffix: Option<Box<dyn Fn(&mut Window, &mut App) -> AnyElement + 'static>>,
    children: SmallVec<[AnyElement; 2]>,
    accessibility_label: Option<SharedString>,
}

impl ListItem {
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id: ElementId = id.into();
        Self {
            mode: ListItemMode::Entry,
            base: h_flex().id(id),
            style: StyleRefinement::default(),
            disabled: false,
            selected: false,
            secondary_selected: false,
            confirmed: false,
            on_click: None,
            on_mouse_down: HashMap::new(),
            on_mouse_enter: None,
            check_icon: None,
            suffix: None,
            children: SmallVec::new(),
            accessibility_label: None,
        }
    }

    /// Set this list item to as a separator, it not able to be selected.
    pub fn separator(mut self) -> Self {
        self.mode = ListItemMode::Separator;
        self
    }

    /// Set to show check icon, default is None.
    pub fn check_icon(mut self, icon: impl Into<Icon>) -> Self {
        self.check_icon = Some(icon.into());
        self
    }

    /// Set ListItem as the selected item style.
    pub fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    /// Set ListItem as the confirmed item style, it will show a check icon.
    pub fn confirmed(mut self, confirmed: bool) -> Self {
        self.confirmed = confirmed;
        self
    }

    /// Set the accessibility label of the list item.
    ///
    /// Without this, list rows are exposed to assistive technology without a
    /// name — the visible children do not become the item's accessible name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set the suffix element of the input field, for example a clear button.
    pub fn suffix<F, E>(mut self, builder: F) -> Self
    where
        F: Fn(&mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        self.suffix = Some(Box::new(move |window, cx| {
            builder(window, cx).into_any_element()
        }));
        self
    }

    pub fn on_click(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Box::new(handler));
        self
    }

    pub fn on_mouse_down(
        mut self,
        button: MouseButton,
        handler: impl Fn(&MouseDownEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_mouse_down.insert(button, Box::new(handler));
        self
    }

    pub fn on_mouse_enter(
        mut self,
        handler: impl Fn(&MouseMoveEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_mouse_enter = Some(Box::new(handler));
        self
    }
}

impl Disableable for ListItem {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Selectable for ListItem {
    fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn is_selected(&self) -> bool {
        self.selected
    }

    fn secondary_selected(mut self, selected: bool) -> Self {
        self.secondary_selected = selected;
        self
    }
}

impl Styled for ListItem {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for ListItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
        self.children.extend(elements);
    }
}

/// Note: Listeners registered via these traits are not gated by
/// `disabled`/`separator`. The hover style is managed internally, use
/// `on_hover` instead of `.hover()`.
impl InteractiveElement for ListItem {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for ListItem {}

impl RenderOnce for ListItem {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let accessibility_label = self.accessibility_label;
        let is_active = self.confirmed || self.selected || self.secondary_selected;

        let is_selectable = !(self.disabled || self.mode.is_separator());

        // The outline is an absolute child, so it has to repeat the item's own radius.
        let mut outline_style = StyleRefinement::default();
        outline_style.corner_radii = self.style.corner_radii.clone();

        self.base
            .test_support()
            .relative()
            .gap_x_1()
            .py_1()
            .px_3()
            .text_base()
            .text_color(cx.theme().foreground)
            .relative()
            .items_center()
            .justify_between()
            .refine_style(&self.style)
            .when_some(accessibility_label, |this, label| this.aria_label(label))
            .when(is_selectable, |this| {
                this.when_some(self.on_click, |this, on_click| this.on_click(on_click))
                    .when_some(self.on_mouse_enter, |this, on_mouse_enter| {
                        this.on_mouse_move(move |ev, window, cx| (on_mouse_enter)(ev, window, cx))
                    })
                    .map(|this| {
                        self.on_mouse_down
                            .into_iter()
                            .fold(this, |this, (button, handler)| {
                                this.on_mouse_down(button, move |ev, window, cx| {
                                    handler(ev, window, cx)
                                })
                            })
                    })
                    // Register `hover` unconditionally, a conditional registration
                    // leaves a stale hover style behind when the item turns active.
                    .hover(|this| {
                        if is_active {
                            this
                        } else {
                            this.bg(cx.theme().tokens.list_hover)
                        }
                    })
            })
            .when(!is_selectable, |this| {
                this.text_color(cx.theme().muted_foreground)
            })
            .child(
                h_flex()
                    .w_full()
                    .items_center()
                    .justify_between()
                    .gap_x_1()
                    .child(div().w_full().children(self.children))
                    .when_some(self.check_icon, |this, icon| {
                        this.child(
                            div().w_5().items_center().justify_center().when(
                                self.confirmed,
                                |this| {
                                    this.child(icon.small().text_color(cx.theme().muted_foreground))
                                },
                            ),
                        )
                    }),
            )
            .when_some(self.suffix, |this, suffix| this.child(suffix(window, cx)))
            .when(is_selectable && self.selected, |this| {
                let bg = if cx.theme().list.active_highlight {
                    cx.theme().list_active
                } else {
                    cx.theme().accent
                };

                this.bg(bg)
            })
            .when(is_selectable && self.secondary_selected, |this| {
                this.child(
                    div()
                        .absolute()
                        .inset_0()
                        .border_1()
                        .border_color(cx.theme().selection)
                        .refine_style(&outline_style),
                )
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{AppContext as _, Context, Render};

    struct DragPreview;

    impl Render for DragPreview {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
        }
    }

    #[gpui::test]
    fn test_list_item_interactivity(_cx: &mut gpui::TestAppContext) {
        let mut item = ListItem::new("item")
            .on_drag(DragPreview, |_, _, _, cx| cx.new(|_| DragPreview))
            .drag_over::<DragPreview>(|style, _, _, _| style)
            .on_drop(|_: &DragPreview, _, _| {})
            .on_hover(|_, _, _| {});

        assert_eq!(item.interactivity().element_id, Some("item".into()));
    }
}
