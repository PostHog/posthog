use std::rc::Rc;

use gpui::{
    Anchor, AnyElement, App, Context, ElementId, InteractiveElement as _, IntoElement,
    ParentElement, RenderOnce, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};
use gpui_base::HoverCard as BaseHoverCard;
pub use gpui_base::HoverCardState;
use instant::Duration;

use crate::{StyledExt as _, popover::Popover};

/// A hover card element that displays content when hovering over a trigger element.
///
/// Similar to Popover but triggered by mouse hover instead of click, with configurable delays
/// for showing and hiding the content. On iOS and Android, tapping the trigger
/// toggles the card and tapping outside dismisses it; hover delays are ignored.
#[derive(IntoElement)]
pub struct HoverCard {
    id: ElementId,
    style: StyleRefinement,
    /// Style for the trigger container, the element laid out in the parent
    /// and measured to anchor the card.
    trigger_style: Option<StyleRefinement>,
    anchor: Anchor,
    trigger: Option<Box<dyn FnOnce(&mut Window, &App) -> AnyElement + 'static>>,
    content: Option<
        Rc<
            dyn Fn(&mut HoverCardState, &mut Window, &mut Context<HoverCardState>) -> AnyElement
                + 'static,
        >,
    >,
    children: Vec<AnyElement>,
    open_delay: Duration,
    close_delay: Duration,
    appearance: bool,
    on_open_change: Option<Rc<dyn Fn(&bool, &mut Window, &mut App)>>,
}

impl HoverCard {
    /// Create a new HoverCard.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            trigger_style: None,
            anchor: Anchor::TopCenter,
            trigger: None,
            content: None,
            children: vec![],
            open_delay: Duration::from_secs_f64(0.6),
            close_delay: Duration::from_secs_f64(0.3),
            appearance: true,
            on_open_change: None,
        }
    }

    /// Set the anchor corner of the hover card, default is [`Anchor::TopCenter`].
    pub fn anchor(mut self, anchor: impl Into<Anchor>) -> Self {
        self.anchor = anchor.into();
        self
    }

    /// Set the trigger element of the hover card.
    pub fn trigger<T>(mut self, trigger: T) -> Self
    where
        T: IntoElement + 'static,
    {
        self.trigger = Some(Box::new(|_, _| trigger.into_any_element()));
        self
    }

    /// Set the style for the trigger container.
    ///
    /// The container is the element laid out in the parent and measured to
    /// anchor the card, so this is where `w_full` or `flex_1` must go for the
    /// trigger to fill its slot.
    pub fn trigger_style(mut self, style: StyleRefinement) -> Self {
        self.trigger_style = Some(style);
        self
    }

    /// Set the content builder of the hover card.
    pub fn content<F, E>(mut self, content: F) -> Self
    where
        F: Fn(&mut HoverCardState, &mut Window, &mut Context<HoverCardState>) -> E + 'static,
        E: IntoElement + 'static,
    {
        self.content = Some(Rc::new(move |state, window, cx| {
            content(state, window, cx).into_any_element()
        }));
        self
    }

    /// Set the delay before showing the hover card, default is 600ms.
    pub fn open_delay(mut self, duration: Duration) -> Self {
        self.open_delay = duration;
        self
    }

    /// Set the delay before hiding the hover card, default is 300ms.
    pub fn close_delay(mut self, duration: Duration) -> Self {
        self.close_delay = duration;
        self
    }

    /// Set whether to apply default appearance styles, default is `true`.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }

    /// Set a callback to be called when the open state changes.
    pub fn on_open_change<F>(mut self, callback: F) -> Self
    where
        F: Fn(&bool, &mut Window, &mut App) + 'static,
    {
        self.on_open_change = Some(Rc::new(callback));
        self
    }
}

impl Styled for HoverCard {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for HoverCard {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for HoverCard {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let Some(trigger) = self.trigger else {
            return div().id("empty").into_any_element();
        };

        let anchor = self.anchor;
        let appearance = self.appearance;
        let content = self.content;
        let children = self.children;
        let style = self.style;
        let trigger_style = self.trigger_style;

        BaseHoverCard::new(self.id)
            .anchor(anchor)
            .open_delay(self.open_delay)
            .close_delay(self.close_delay)
            .trigger((trigger)(window, cx))
            .content(move |state, window, cx| {
                Popover::render_popover_content(anchor, appearance, window, cx)
                    .overflow_hidden()
                    .when_some(content, |this, content| {
                        this.child((content)(state, window, cx))
                    })
                    .children(children)
                    .refine_style(&style)
            })
            .when_some(self.on_open_change, |this, callback| {
                this.on_open_change(move |open, window, cx| callback(open, window, cx))
            })
            .when_some(trigger_style, |this, style| this.refine_style(&style))
            .into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{button::Button, h_flex};
    use gpui::{Context, Render, point, px};

    struct TriggerStyleHarness {
        styled: bool,
    }

    impl Render for TriggerStyleHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Keep the trigger clear of the popup's window margin so the
            // content position reflects only the trigger container's bounds.
            div().size_full().child(
                h_flex()
                    .absolute()
                    .left(px(100.))
                    .top(px(100.))
                    .w(px(200.))
                    .child(
                        HoverCard::new("trigger-style-hover-card")
                            .appearance(false)
                            .open_delay(Duration::ZERO)
                            .anchor(Anchor::TopRight)
                            .when(self.styled, |this| {
                                this.trigger_style(StyleRefinement::default().w_full())
                            })
                            .trigger(Button::new("styled-trigger").size(px(40.)))
                            .child(
                                div()
                                    .debug_selector(|| "styled-content".into())
                                    .size(px(20.)),
                            ),
                    ),
            )
        }
    }

    /// `trigger_style` styles the container the parent lays out and the card
    /// is anchored to. Applied to anything nested inside it, `w_full` would
    /// resolve against a container that only wraps its content.
    #[gpui::test]
    fn trigger_style_is_applied_to_the_trigger_container(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, _| TriggerStyleHarness { styled: false });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_move(point(px(110.), px(110.)), None, Default::default());
        cx.run_until_parked();
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            window.draw(cx).clear(cx);
        });
        // Unstyled: the container wraps the 40px trigger, so the content's right
        // edge meets the trigger's right edge at 140px.
        assert_eq!(
            cx.debug_bounds("styled-content").unwrap().top_right().x,
            px(140.)
        );

        cx.update(|window, cx| {
            view.update(cx, |view, cx| {
                view.styled = true;
                cx.notify();
            });
            window.draw(cx).clear(cx);
            window.draw(cx).clear(cx);
        });
        // `w_full` stretches the container across the 200px row, and the card
        // follows the container's right edge at 300px.
        assert_eq!(
            cx.debug_bounds("styled-content").unwrap().top_right().x,
            px(300.)
        );
    }
}
