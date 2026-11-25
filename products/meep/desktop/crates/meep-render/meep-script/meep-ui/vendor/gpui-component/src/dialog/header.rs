use gpui::{
    AnyElement, App, IntoElement, ParentElement, RenderOnce, StyleRefinement, Styled, Window,
};

use crate::{StyledExt as _, v_flex};

/// Header section of a dialog, typically contains DialogTitle and DialogDescription.
///
/// # Examples
///
/// ```ignore
/// DialogHeader::new()
///     .child(DialogTitle::new().child("Delete Account"))
///     .child(DialogDescription::new().child("This action cannot be undone."))
/// ```
#[derive(IntoElement)]
pub struct DialogHeader {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl DialogHeader {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl ParentElement for DialogHeader {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for DialogHeader {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for DialogHeader {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        v_flex()
            .gap_2()
            .refine_style(&self.style)
            .children(self.children)
    }
}
