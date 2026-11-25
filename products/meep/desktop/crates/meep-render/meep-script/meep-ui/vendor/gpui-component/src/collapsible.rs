use gpui::{
    AnyElement, App, ElementId, IntoElement, ParentElement, RenderOnce, StyleRefinement, Styled,
    Window,
};
use gpui_base::spring;

use crate::{ActiveTheme as _, StyledExt};

/// An interactive element which expands/collapses.
#[derive(IntoElement)]
pub struct Collapsible {
    base: gpui_base::Collapsible,
    style: StyleRefinement,
    motion_id: Option<ElementId>,
    open: bool,
}

impl Collapsible {
    /// Creates a new `Collapsible` instance.
    pub fn new() -> Self {
        Self {
            base: gpui_base::Collapsible::new(),
            style: StyleRefinement::default(),
            motion_id: None,
            open: false,
        }
    }

    /// Sets whether the collapsible is open. default is false.
    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self.base = self.base.open(open);
        self
    }

    /// Enables a reversible measured reveal under a stable identity.
    pub fn motion_id(mut self, id: impl Into<ElementId>) -> Self {
        self.motion_id = Some(id.into());
        self
    }

    /// Sets the content of the collapsible.
    ///
    /// If `open` is false, content will be hidden.
    pub fn content(mut self, content: impl IntoElement) -> Self {
        self.base = self.base.content(content);
        self
    }
}

impl Styled for Collapsible {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Collapsible {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.base.extend(elements);
    }
}

impl RenderOnce for Collapsible {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let base = match self.motion_id {
            Some(id) => {
                let progress = spring(
                    (id.clone(), "reveal"),
                    if self.open { 1.0 } else { 0.0 },
                    cx.theme().motion_tokens().spring_control,
                    window,
                    cx,
                );
                self.base.reveal(id, progress)
            }
            None => self.base,
        };
        base.v_flex().refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use gpui::{Context, InteractiveElement as _, Render, TestAppContext, div, px};

    use super::*;
    use crate::Theme;

    struct Harness(bool);

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Collapsible::new()
                .open(self.0)
                .child(
                    div()
                        .debug_selector(|| "collapsible-trigger".into())
                        .size(px(10.)),
                )
                .content(
                    div()
                        .debug_selector(|| "collapsible-content".into())
                        .size(px(10.)),
                )
        }
    }

    #[gpui::test]
    fn facade_preserves_vertical_layout_and_visibility(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, _| Harness(true));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let trigger = cx.debug_bounds("collapsible-trigger").unwrap();
        let content = cx.debug_bounds("collapsible-content").unwrap();
        assert!(trigger.origin.y < content.origin.y);

        let (_, cx) = cx.add_window_view(|_, _| Harness(false));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.debug_bounds("collapsible-trigger").is_some());
        assert!(cx.debug_bounds("collapsible-content").is_none());
    }

    #[gpui::test]
    fn motion_id_keeps_closed_content_mounted_for_reversible_reveal(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));

        struct MotionHarness;

        impl Render for MotionHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                Collapsible::new()
                    .motion_id("details-motion")
                    .open(false)
                    .content(
                        div()
                            .debug_selector(|| "motion-content".into())
                            .size(px(10.)),
                    )
            }
        }

        let (_, cx) = cx.add_window_view(|_, _| MotionHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.debug_bounds("motion-content").is_some());
    }
}
