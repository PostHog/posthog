use gpui::{
    AnyElement, ClickEvent, ElementId, InteractiveElement, IntoElement, MouseButton, ParentElement,
    RenderOnce, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, div,
};

use crate::{ActiveTheme as _, StyledExt};

/// A Link element like a `<a>` tag in HTML.
#[derive(IntoElement)]
pub struct Link {
    id: ElementId,
    style: StyleRefinement,
    href: Option<SharedString>,
    disabled: bool,
    on_click: Option<Box<dyn Fn(&ClickEvent, &mut gpui::Window, &mut gpui::App) + 'static>>,
    children: Vec<AnyElement>,
}

impl Link {
    /// Create a new Link element.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            href: None,
            on_click: None,
            disabled: false,
            children: Vec::new(),
        }
    }

    /// Set the href of the link.
    pub fn href(mut self, href: impl Into<SharedString>) -> Self {
        self.href = Some(href.into());
        self
    }

    /// Set the click handler of the link.
    ///
    /// If this set, the handler will be called when the link is clicked.
    /// Otherwise, the link will only open the href if set.
    pub fn on_click(
        mut self,
        handler: impl Fn(&ClickEvent, &mut gpui::Window, &mut gpui::App) + 'static,
    ) -> Self {
        self.on_click = Some(Box::new(handler));
        self
    }

    /// Set the disabled state, default false.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Styled for Link {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Link {
    fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
        self.children.extend(elements)
    }
}

impl RenderOnce for Link {
    fn render(self, _: &mut gpui::Window, cx: &mut gpui::App) -> impl IntoElement {
        let href = self.href.clone();
        let on_click = self.on_click;

        div()
            .id(self.id)
            .text_color(cx.theme().link)
            .text_decoration_1()
            .text_decoration_color(cx.theme().link.opacity(0.5))
            .hover(|this| {
                this.text_color(cx.theme().link.opacity(0.8))
                    .text_decoration_1()
                    .text_decoration_color(cx.theme().link)
            })
            .active(|this| {
                this.text_color(cx.theme().link.opacity(0.6))
                    .text_decoration_1()
                    .text_decoration_color(cx.theme().link)
            })
            .cursor_pointer()
            .refine_style(&self.style)
            .on_mouse_down(MouseButton::Left, |_, _, cx| {
                cx.stop_propagation();
            })
            .on_click({
                move |e, window, cx| {
                    if let Some(href) = &href {
                        cx.open_url(&href.clone());
                    }
                    if let Some(on_click) = &on_click {
                        on_click(e, window, cx);
                    }
                }
            })
            .children(self.children)
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{Context, Modifiers, Render, TestAppContext, div, point, px};

    use super::*;

    struct LinkHarness {
        disabled: bool,
        clicks: Rc<Cell<usize>>,
    }

    impl Render for LinkHarness {
        fn render(&mut self, _: &mut gpui::Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            Link::new("legacy-link")
                .href("https://example.com")
                .disabled(self.disabled)
                .size(px(100.))
                .child(
                    div()
                        .debug_selector(|| "legacy-link-child".into())
                        .child("Visible link"),
                )
                .on_click(move |_, _, _| clicks.set(clicks.get() + 1))
        }
    }

    #[gpui::test]
    fn legacy_link_prepaints_children(cx: &mut TestAppContext) {
        let (cx, _) = harness(cx, false);
        let bounds = cx
            .debug_bounds("legacy-link-child")
            .expect("legacy Link child must participate in layout and prepaint");

        assert!(bounds.size.width > px(0.));
        assert!(bounds.size.height > px(0.));
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (&mut gpui::VisualTestContext, Rc<Cell<usize>>) {
        cx.update(crate::init);
        let clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let clicks = clicks.clone();
            move |_, _| LinkHarness { disabled, clicks }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, clicks)
    }

    #[gpui::test]
    fn legacy_link_preserves_pointer_open_and_callback(cx: &mut TestAppContext) {
        let (cx, clicks) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(cx.opened_url().as_deref(), Some("https://example.com"));
        assert_eq!(clicks.get(), 1);
    }

    #[gpui::test]
    fn legacy_link_preserves_disabled_behavior(cx: &mut TestAppContext) {
        let (cx, clicks) = harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        // `disabled` was historically a stored but behaviorally inert field.
        assert_eq!(cx.opened_url().as_deref(), Some("https://example.com"));
        assert_eq!(clicks.get(), 1);
    }

    #[gpui::test]
    fn legacy_link_remains_pointer_only(cx: &mut TestAppContext) {
        let (cx, clicks) = harness(cx, false);
        cx.simulate_keystrokes("enter space");

        assert_eq!(cx.opened_url(), None);
        assert_eq!(clicks.get(), 0);
    }
}
