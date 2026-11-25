use gpui::{
    AnyElement, App, InteractiveElement as _, IntoElement, ParentElement, RenderOnce,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, div, relative,
};

use crate::{
    ActiveTheme as _, StyledExt as _,
    button::Button,
    dialog::{Confirm, DialogDispatchAnchor},
    h_flex,
};

/// Footer section of a dialog, typically contains action buttons.
///
/// # Examples
///
/// ```ignore
/// DialogFooter::new()
///     .child(DialogClose::new().trigger(|button| button.label("Cancel")))
///     .child(Button::new("confirm").label("Confirm"))
/// ```
#[derive(IntoElement)]
pub struct DialogFooter {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl DialogFooter {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl ParentElement for DialogFooter {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for DialogFooter {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for DialogFooter {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        h_flex()
            .gap_2()
            .justify_end()
            .line_height(relative(1.25))
            .rounded_b(cx.theme().radius_lg)
            .refine_style(&self.style)
            .children(self.children)
    }
}

pub trait DialogFooterButton {
    fn is_cancel(&self) -> bool {
        false
    }

    fn is_action(&self) -> bool {
        false
    }
}
#[derive(IntoElement)]
pub struct DialogClose {
    base: gpui_base::DialogClose,
}

impl DialogClose {
    pub fn new() -> Self {
        Self {
            base: gpui_base::DialogClose::new(),
        }
    }

    /// Styles a close button whose accessibility and activation are owned by Base.
    pub fn trigger<E: IntoElement>(mut self, build: impl FnOnce(Button) -> E) -> Self {
        self.base = self
            .base
            .trigger(|button| build(Button::new("close").with_base(button)));
        self
    }
}

impl ParentElement for DialogClose {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.base.extend(elements);
    }
}

impl RenderOnce for DialogClose {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div().size_full().child(self.base)
    }
}

#[derive(IntoElement)]
pub struct DialogAction {
    children: Vec<AnyElement>,
}

impl DialogAction {
    pub fn new() -> Self {
        Self {
            children: Vec::new(),
        }
    }
}

impl ParentElement for DialogAction {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for DialogAction {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let anchor = DialogDispatchAnchor::new("dialog-action-anchor", window, cx);
        div()
            .size_full()
            .id("dialog-action")
            .child(anchor.element())
            .on_click(move |_, window, cx| {
                anchor.dispatch(&Confirm { secondary: false }, window, cx)
            })
            .children(self.children)
    }
}
