use gpui::{
    AnyElement, App, IntoElement, ParentElement, RenderOnce, StyleRefinement, Styled, Window,
};
use gpui_base::DialogDescription as BaseDialogDescription;

use crate::{ActiveTheme as _, StyledExt as _};

/// Description element for a dialog header.
///
/// Typically used inside a DialogHeader component to provide additional context.
///
/// # Examples
///
/// ```ignore
/// DialogDescription::new("This action cannot be undone.")
/// ```
#[derive(IntoElement)]
pub struct DialogDescription {
    base: BaseDialogDescription,
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl DialogDescription {
    pub fn new() -> Self {
        Self {
            base: BaseDialogDescription::new(),
            style: StyleRefinement::default(),
            children: vec![],
        }
    }
}

impl ParentElement for DialogDescription {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for DialogDescription {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for DialogDescription {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        self.base
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .refine_style(&self.style)
            .children(self.children)
    }
}
