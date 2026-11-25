use crate::TestSupportExt as _;
use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, FocusHandle, InteractiveElement as _, IntoElement, KeyBinding,
    MouseButton, ParentElement, Pixels, RenderOnce, StyleRefinement, Styled, Window, anchored, div,
    point, prelude::FluentBuilder as _, px,
};

use crate::{FocusTrapElement as _, StyledExt as _, actions::Cancel};

const CONTEXT: &str = "Sheet";

type CloseHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;
type CloseRequest = Rc<dyn Fn(&mut Window, &mut App)>;

fn close(request: &CloseRequest, notify: &CloseHandler, window: &mut Window, cx: &mut App) {
    let event = ClickEvent::default();
    request(window, cx);
    notify(&event, window, cx);
}

pub fn init(cx: &mut App) {
    cx.bind_keys([KeyBinding::new("escape", Cancel, Some(CONTEXT))]);
}

/// An unstyled modal sheet host.
///
/// Applications provide the overlay and surface. The host owns focus trapping,
/// Escape handling, overlay dismissal, and close callback ordering.
#[derive(IntoElement)]
pub struct Sheet {
    base: gpui::Div,
    style: StyleRefinement,
    focus: FocusHandle,
    overlay_interactive: bool,
    overlay_closable: bool,
    dismiss_before_y: Option<Pixels>,
    overlay: Option<AnyElement>,
    surface: Option<AnyElement>,
    request_close: CloseRequest,
    on_close: CloseHandler,
}

impl Sheet {
    pub fn new(cx: &mut App) -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            focus: cx.focus_handle(),
            overlay_interactive: true,
            overlay_closable: true,
            dismiss_before_y: None,
            overlay: None,
            surface: None,
            request_close: Rc::new(|_, _| {}),
            on_close: Rc::new(|_, _, _| {}),
        }
    }

    pub fn overlay(mut self, overlay: impl IntoElement) -> Self {
        self.overlay = Some(overlay.into_any_element());
        self
    }

    pub fn surface(mut self, surface: impl IntoElement) -> Self {
        self.surface = Some(surface.into_any_element());
        self
    }

    pub fn overlay_closable(mut self, closable: bool) -> Self {
        self.overlay_closable = closable;
        self
    }

    #[doc(hidden)]
    pub fn overlay_interactive(mut self, interactive: bool) -> Self {
        self.overlay_interactive = interactive;
        self
    }

    pub fn on_close(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_close = Rc::new(handler);
        self
    }

    #[doc(hidden)]
    pub fn focus_handle(mut self, focus: FocusHandle) -> Self {
        self.focus = focus;
        self
    }

    #[doc(hidden)]
    pub fn dismiss_before_y(mut self, y: Pixels) -> Self {
        self.dismiss_before_y = Some(y);
        self
    }

    #[doc(hidden)]
    pub fn request_close(mut self, handler: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.request_close = Rc::new(handler);
        self
    }
}

impl Styled for Sheet {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Sheet {
    fn render(self, window: &mut Window, _: &mut App) -> impl IntoElement {
        let viewport = window.viewport_size();
        let request_close = self.request_close;
        let on_close = self.on_close;
        let escape_request = request_close.clone();
        let escape_notify = on_close.clone();

        anchored().position(point(px(0.), px(0.))).child(
            self.base
                .id("sheet-host")
                .test_support()
                .absolute()
                .top_0()
                .left_0()
                .w(viewport.width)
                .h(viewport.height)
                .key_context(CONTEXT)
                .track_focus(&self.focus)
                .focus_trap("sheet", &self.focus)
                .on_action(move |_: &Cancel, window, cx| {
                    cx.propagate();
                    close(&escape_request, &escape_notify, window, cx);
                })
                .when_some(self.overlay, |this, overlay| {
                    let request_close = request_close.clone();
                    let on_close = on_close.clone();
                    let dismiss_before_y = self.dismiss_before_y;
                    let overlay_interactive = self.overlay_interactive;
                    let overlay_closable = self.overlay_closable;
                    this.child(overlay).child(div().absolute().inset_0().when(
                        overlay_interactive,
                        |this| {
                            this.on_any_mouse_down(move |event, window, cx| {
                                if !overlay_interactive {
                                    return;
                                }
                                if dismiss_before_y.is_some_and(|top| event.position.y < top) {
                                    return;
                                }
                                cx.stop_propagation();
                                if overlay_closable && event.button == MouseButton::Left {
                                    close(&request_close, &on_close, window, cx);
                                }
                            })
                        },
                    ))
                })
                .children(self.surface)
                .refine_style(&self.style),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Context, Render, point, px};
    use std::{cell::RefCell, rc::Rc};

    struct Harness {
        closable: bool,
        cutoff: Option<Pixels>,
        focus: FocusHandle,
        events: Rc<RefCell<Vec<&'static str>>>,
    }

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let requested = self.events.clone();
            let closed = self.events.clone();
            Sheet::new(cx)
                .focus_handle(self.focus.clone())
                .overlay_closable(self.closable)
                .request_close(move |_, _| requested.borrow_mut().push("request"))
                .on_close(move |_, _, _| closed.borrow_mut().push("closed"))
                .overlay(div().absolute().inset_0().occlude())
                .surface(
                    div()
                        .absolute()
                        .right_0()
                        .top_0()
                        .h_full()
                        .w(px(80.))
                        .occlude(),
                )
                .when_some(self.cutoff, |this, cutoff| this.dismiss_before_y(cutoff))
        }
    }

    fn harness(
        cx: &mut gpui::TestAppContext,
        closable: bool,
    ) -> (&mut gpui::VisualTestContext, Rc<RefCell<Vec<&'static str>>>) {
        cx.update(crate::init);
        let focus = cx.update(|cx| cx.focus_handle());
        let events = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let events = events.clone();
            let focus = focus.clone();
            move |_, _| Harness {
                closable,
                cutoff: None,
                focus,
                events,
            }
        });
        cx.update(|window, cx| focus.focus(window, cx));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, events)
    }

    #[gpui::test]
    fn overlay_close_requests_then_notifies(cx: &mut gpui::TestAppContext) {
        let (cx, events) = harness(cx, true);
        cx.simulate_click(point(px(20.), px(20.)), Default::default());
        assert_eq!(&*events.borrow(), &["request", "closed"]);
    }

    #[gpui::test]
    fn non_closable_overlay_does_not_request_close(cx: &mut gpui::TestAppContext) {
        let (cx, events) = harness(cx, false);
        cx.simulate_click(point(px(20.), px(20.)), Default::default());
        assert!(events.borrow().is_empty());
    }

    #[gpui::test]
    fn escape_uses_the_same_close_order_and_registers_focus_trap(cx: &mut gpui::TestAppContext) {
        let (cx, events) = harness(cx, true);
        assert!(cx.update(|window, cx| crate::active_focus_trap(window, cx).is_some()));
        cx.dispatch_action(Cancel);
        assert_eq!(&*events.borrow(), &["request", "closed"]);
    }

    #[gpui::test]
    fn pointer_above_the_dismiss_cutoff_is_ignored(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let focus = cx.update(|cx| cx.focus_handle());
        let events = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let focus = focus.clone();
            let events = events.clone();
            move |_, _| Harness {
                closable: true,
                cutoff: Some(px(50.)),
                focus,
                events,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_click(point(px(20.), px(20.)), Default::default());
        assert!(events.borrow().is_empty());
        cx.simulate_click(point(px(20.), px(80.)), Default::default());
        assert_eq!(&*events.borrow(), &["request", "closed"]);
    }
}
