use crate::root::WindowState;
use std::{
    cell::RefCell,
    rc::{Rc, Weak},
    time::Duration,
};

use gpui::{
    Action, AnyElement, AnyView, App, AppContext, Bounds, Context, ElementId, GlobalElementId,
    IntoElement, MouseButton, ParentElement, Pixels, Render, SharedString,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, div, prelude::FluentBuilder, px,
};
pub use gpui_base::TooltipDefaults;
use gpui_base::{
    Tooltip as BaseTooltip, TooltipOverlay as BaseTooltipOverlay,
    TooltipRequest as BaseTooltipRequest, TooltipTransition as BaseTooltipTransition,
};

use crate::{
    ActiveTheme, Placement, StyledExt,
    animation::{EffectTransition, ease_in_out_cubic, ease_out_cubic},
    kbd::Kbd,
    text::Text,
};

pub(crate) fn init(_cx: &mut App) {
    // No app-level init needed — TooltipOverlay is per-window via Root.
}

// ── Tooltip view (unchanged API) ────────────────────────────────────────────

enum TooltipContext {
    Text(Text),
    Element(Box<dyn Fn(&mut Window, &mut App) -> AnyElement>),
}

/// A Tooltip element that can display text or custom content,
/// with optional key binding information.
pub struct Tooltip {
    style: StyleRefinement,
    content: TooltipContext,
    key_binding: Option<Kbd>,
    action: Option<(Box<dyn Action>, Option<SharedString>)>,
}

impl Tooltip {
    /// Create a Tooltip with a text content.
    pub fn new(text: impl Into<Text>) -> Self {
        Self {
            style: StyleRefinement::default(),
            content: TooltipContext::Text(text.into()),
            key_binding: None,
            action: None,
        }
    }

    /// Create a Tooltip with a custom element.
    pub fn element<E, F>(builder: F) -> Self
    where
        E: IntoElement,
        F: Fn(&mut Window, &mut App) -> E + 'static,
    {
        Self {
            style: StyleRefinement::default(),
            key_binding: None,
            action: None,
            content: TooltipContext::Element(Box::new(move |window, cx| {
                builder(window, cx).into_any_element()
            })),
        }
    }

    /// Set Action to display key binding information for the tooltip if it exists.
    pub fn action(mut self, action: &dyn Action, context: Option<&str>) -> Self {
        self.action = Some((action.boxed_clone(), context.map(SharedString::new)));
        self
    }

    /// Set KeyBinding information for the tooltip.
    pub fn key_binding(mut self, key_binding: Option<Kbd>) -> Self {
        self.key_binding = key_binding;
        self
    }

    /// Build the tooltip and return it as an `AnyView`.
    pub fn build(self, _: &mut Window, cx: &mut App) -> AnyView {
        cx.new(|_| self).into()
    }
}

impl FluentBuilder for Tooltip {}
impl Styled for Tooltip {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl Render for Tooltip {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let key_binding = if let Some(key_binding) = &self.key_binding {
            Some(key_binding.clone())
        } else {
            if let Some((action, context)) = &self.action {
                Kbd::binding_for_action(
                    action.as_ref(),
                    context.as_ref().map(|s| s.as_ref()),
                    window,
                )
            } else {
                None
            }
        };

        div().child(
            // Wrap in a child, to ensure the left margin is applied to the tooltip
            BaseTooltip::new("tooltip-popup")
                .h_flex()
                .font_family(cx.theme().font_family.clone())
                .m_3()
                .bg(cx.theme().tokens.popover)
                .text_color(cx.theme().popover_foreground)
                .bg(cx.theme().tokens.popover)
                .border_1()
                .border_color(cx.theme().border)
                .shadow_md()
                .rounded(cx.theme().radius)
                .justify_between()
                .py_0p5()
                .px_2()
                .text_sm()
                .gap_3()
                .refine_style(&self.style)
                .map(|this| {
                    this.child(div().map(|this| match self.content {
                        TooltipContext::Text(ref text) => this.child(text.clone()),
                        TooltipContext::Element(ref builder) => this.child(builder(window, cx)),
                    }))
                })
                .when_some(key_binding, |this, kbd| {
                    this.child(
                        div()
                            .text_xs()
                            .flex_shrink_0()
                            .text_color(cx.theme().muted_foreground)
                            .child(kbd.appearance(false)),
                    )
                }),
        )
    }
}

// ── Managed tooltip system ──────────────────────────────────────────────────

/// Duration of the slide-down enter animation.
const ENTER_DURATION: Duration = Duration::from_millis(150);
/// Duration of the position-slide animation when switching tooltips.
const SLIDE_DURATION: Duration = Duration::from_millis(200);
pub(crate) fn render_tooltip(
    content_view: AnyView,
    transition: BaseTooltipTransition,
    _: &mut Window,
    _: &mut App,
) -> AnyElement {
    div().child(content_view).map(|element| match transition {
        BaseTooltipTransition::Switch {
            epoch,
            previous,
            current,
        } => {
            let same_row = (current.origin.y - previous.origin.y).abs() < px(10.);
            if !same_row {
                return element.into_any_element();
            }
            let dx = current.center().x - previous.center().x;
            EffectTransition::new(SLIDE_DURATION)
                .ease(ease_in_out_cubic)
                .slide_x(-dx, px(0.))
                .apply(
                    element,
                    ElementId::NamedInteger("tooltip-slide".into(), epoch as u64),
                )
                .into_any_element()
        }
        BaseTooltipTransition::Enter { epoch } => EffectTransition::new(ENTER_DURATION)
            .ease(ease_out_cubic)
            .slide_y(px(4.), px(0.))
            .fade(0.0, 1.0)
            .apply(
                element,
                ElementId::NamedInteger("tooltip-enter".into(), epoch as u64),
            )
            .into_any_element(),
    })
}

// ── Extension trait for managed tooltips ─────────────────────────────────────

// ── Shared tooltip state for components ─────────────────────────────────────

/// Shared tooltip state that components (Button, Switch, Checkbox, Radio, etc.)
/// can embed to get `.tooltip()` support with minimal boilerplate.
#[derive(Default)]
pub(crate) struct ComponentTooltip {
    pub text: Option<(
        SharedString,
        Option<(Rc<Box<dyn Action>>, Option<SharedString>)>,
    )>,
    pub builder: Option<Rc<dyn Fn(&mut Window, &mut App) -> AnyView>>,
    pub show_delay: Option<Duration>,
}

impl ComponentTooltip {
    /// Apply this tooltip to a `Stateful<Div>` (or any `ManagedTooltipExt` element).
    pub fn apply<E: ManagedTooltipExt>(self, el: E) -> E {
        let show_delay = self.show_delay;
        if let Some(builder) = self.builder {
            el.managed_tooltip_with(None, show_delay, move |window, cx| builder(window, cx))
        } else if let Some((text, action)) = self.text {
            el.managed_tooltip_with(None, show_delay, move |window, cx| {
                Tooltip::new(text.clone())
                    .when_some(action.clone(), |this, (action, context)| {
                        this.action(
                            action.boxed_clone().as_ref(),
                            context.as_ref().map(|c| c.as_ref()),
                        )
                    })
                    .build(window, cx)
            })
        } else {
            el
        }
    }
}

// ── Internal managed tooltip trait ──────────────────────────────────────────

#[derive(Default)]
struct TooltipLifetime(Rc<()>);

#[derive(Default)]
struct TooltipTrigger {
    id: Option<GlobalElementId>,
    lifetime: Weak<()>,
    bounds: Bounds<Pixels>,
}

pub(crate) trait ManagedTooltipExt:
    StatefulInteractiveElement + crate::ElementExt + Sized
{
    fn managed_tooltip(
        self,
        build_tooltip: impl Fn(&mut Window, &mut App) -> AnyView + 'static,
    ) -> Self {
        self.managed_tooltip_with(None, None, build_tooltip)
    }

    fn managed_tooltip_at(
        self,
        placement: Placement,
        build_tooltip: impl Fn(&mut Window, &mut App) -> AnyView + 'static,
    ) -> Self {
        self.managed_tooltip_with(Some(placement), None, build_tooltip)
    }

    fn managed_tooltip_with(
        self,
        preferred_placement: Option<Placement>,
        show_delay: Option<Duration>,
        build_tooltip: impl Fn(&mut Window, &mut App) -> AnyView + 'static,
    ) -> Self {
        let build_tooltip = Rc::new(build_tooltip);
        let trigger = Rc::new(RefCell::new(TooltipTrigger::default()));
        let trigger_writer = trigger.clone();

        self.on_prepaint(move |bounds, window, _| {
            let id = window.with_global_id("managed-tooltip-trigger".into(), |id, _| id.clone());
            // GPUI retains keyed element state for cached subtrees too, and
            // drops it after a frame that no longer contains the trigger.
            let lifetime = window.with_element_state(&id, |state: Option<TooltipLifetime>, _| {
                let state = state.unwrap_or_default();
                (Rc::downgrade(&state.0), state)
            });
            *trigger_writer.borrow_mut() = TooltipTrigger {
                id: Some(id),
                lifetime,
                bounds,
            };
        })
        .on_hover({
            let trigger = trigger.clone();
            let build_tooltip = build_tooltip.clone();
            move |hovered, window, cx| {
                let trigger = trigger.borrow();
                let Some(id) = trigger.id.as_ref() else {
                    return;
                };
                let bounds = trigger.bounds;
                // A press keeps the tooltip dismissed until the pointer leaves
                // the trigger. This also drops the hover-enter that a click
                // removing the trigger dispatches to the stale frame.
                if *hovered && WindowState::is_tooltip_trigger_pressed(bounds, window, cx) {
                    return;
                }
                if let Some(overlay) = WindowState::tooltip_overlay_for_trigger(
                    id,
                    trigger.lifetime.clone(),
                    *hovered,
                    window,
                    cx,
                ) {
                    if *hovered {
                        overlay.update(cx, |o: &mut BaseTooltipOverlay, cx| {
                            let build = build_tooltip.clone();
                            let request = BaseTooltipRequest::new(bounds, move |window, cx| {
                                build(window, cx)
                            });
                            let request = match preferred_placement {
                                Some(placement) => request.with_placement(placement),
                                None => request,
                            };
                            let request = match show_delay {
                                Some(delay) => request.with_show_delay(delay),
                                None => request,
                            };
                            o.request_show(request, window, cx);
                        });
                    } else {
                        overlay.update(cx, |o: &mut BaseTooltipOverlay, cx| {
                            o.request_hide(window, cx);
                        });
                    }
                }
            }
        })
        .on_mouse_down(MouseButton::Left, move |_, window, cx| {
            WindowState::press_tooltip_trigger(trigger.borrow().bounds, window, cx);
            if let Some(overlay) = WindowState::tooltip_overlay(window, cx) {
                overlay.update(cx, |overlay, cx| {
                    overlay.hide(cx);
                });
            }
        })
    }
}

impl<E: StatefulInteractiveElement + crate::ElementExt> ManagedTooltipExt for E {}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc, time::Duration};

    use gpui::{
        AppContext as _, Context, Entity, InputEvent as _, InteractiveElement as _, IntoElement,
        MouseButton, MouseMoveEvent, MouseUpEvent, ParentElement as _, Render,
        StatefulInteractiveElement as _, Styled as _, TestAppContext, VisualTestContext, Window,
        div, point, prelude::FluentBuilder as _, px,
    };

    use super::ManagedTooltipExt as _;
    use crate::Root;

    // Distinct scene markers let assertions observe retained tooltip output
    // without requiring its renderer to run on every frame.
    const TOOLTIP_COLORS: [u32; 2] = [0x7a135e, 0x136b7a];

    fn assert_tooltip_painted(cx: &mut VisualTestContext, index: usize, shown: bool) {
        draw(cx);
        let painted = cx.update(|window, _| {
            let marker: gpui::Background = gpui::rgb(TOOLTIP_COLORS[index]).into();
            window
                .painted_quads()
                .iter()
                .any(|quad| quad.background == marker)
        });
        assert_eq!(
            painted, shown,
            "tooltip {index} visibility in the rendered scene"
        );
    }

    /// A trigger that removes itself when clicked, like a button that
    /// replaces the view it sits in.
    struct Probe {
        shown: bool,
        removes_on_click: bool,
        builds: Rc<Cell<usize>>,
    }

    impl Render for Probe {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let builds = self.builds.clone();
            div().size_full().when(self.shown, |this| {
                this.child(
                    div()
                        .id("trigger")
                        .absolute()
                        .left(px(10.))
                        .top(px(10.))
                        .w(px(100.))
                        .h(px(30.))
                        .managed_tooltip(move |_, cx| {
                            builds.set(builds.get() + 1);
                            cx.new(|_| super::Tooltip::new("tip").bg(gpui::rgb(TOOLTIP_COLORS[0])))
                                .into()
                        })
                        .on_click(cx.listener(|this, _, _, cx| {
                            if this.removes_on_click {
                                this.shown = false;
                            }
                            cx.notify();
                        })),
                )
            })
        }
    }

    fn open(
        cx: &mut TestAppContext,
        removes_on_click: bool,
        builds: Rc<Cell<usize>>,
    ) -> (VisualTestContext, Entity<Probe>) {
        cx.update(|cx| {
            crate::init(cx);
            // These tests cover tooltip lifetime, not intermediate fade frames.
            cx.set_reduce_motion(true);
        });
        let probe = cx.new(|_| Probe {
            shown: true,
            removes_on_click,
            builds,
        });
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                cx.new(|cx| Root::new(probe.clone(), window, cx))
            })
            .unwrap()
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        draw(&mut cx);
        (cx, probe)
    }

    /// Presses at `at` and releases a pixel away, as most real clicks do.
    fn click_with_drift(cx: &mut VisualTestContext, at: gpui::Point<gpui::Pixels>) {
        let drift = point(at.x + px(1.), at.y);
        cx.simulate_mouse_down(at, MouseButton::Left, Default::default());
        cx.simulate_mouse_move(drift, Some(MouseButton::Left), Default::default());
        cx.simulate_mouse_up(drift, MouseButton::Left, Default::default());
    }

    fn draw(cx: &mut VisualTestContext) {
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        })
    }

    /// Lets any show delay or grace period run out, then draws.
    fn wait(cx: &mut VisualTestContext) {
        cx.executor().advance_clock(Duration::from_secs(1));
        cx.run_until_parked();
        draw(cx);
    }

    struct AdjacentTriggers;

    impl Render for AdjacentTriggers {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().children((0..2).map(|index| {
                div()
                    .id(("trigger", index))
                    .absolute()
                    .left(px(10. + index as f32 * 100.))
                    .top(px(10.))
                    .w(px(100.))
                    .h(px(30.))
                    .managed_tooltip(move |_, cx| {
                        cx.new(|_| super::Tooltip::new("tip").bg(gpui::rgb(TOOLTIP_COLORS[index])))
                            .into()
                    })
            }))
        }
    }

    fn open_adjacent_triggers(
        cx: &mut TestAppContext,
    ) -> (VisualTestContext, Entity<AdjacentTriggers>) {
        cx.update(|cx| {
            crate::init(cx);
            // These tests cover tooltip lifetime, not intermediate fade frames.
            cx.set_reduce_motion(true);
        });
        let probe = cx.new(|_| AdjacentTriggers);
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                cx.new(|cx| Root::new(probe.clone(), window, cx))
            })
            .unwrap()
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        draw(&mut cx);
        (cx, probe)
    }

    fn assert_tooltip_shown(cx: &mut VisualTestContext, index: usize) {
        assert_tooltip_painted(cx, index, true);
        assert_tooltip_painted(cx, 1 - index, false);
    }

    #[gpui::test]
    fn tooltips_switch_in_both_directions(cx: &mut TestAppContext) {
        let (mut cx, probe) = open_adjacent_triggers(cx);
        for (step, index) in [0, 1, 0].into_iter().enumerate() {
            let at = point(px(50. + index as f32 * 100.), px(25.));
            cx.simulate_mouse_move(at, None, Default::default());
            if step > 0 {
                draw(&mut cx);
                assert_tooltip_shown(&mut cx, index);
            }
            wait(&mut cx);
            assert_tooltip_shown(&mut cx, index);
            // Rebuilding the triggers must preserve ownership for hover-leave.
            cx.update(|_, cx| probe.update(cx, |_, cx| cx.notify()));
            draw(&mut cx);
        }
        cx.simulate_mouse_move(point(px(300.), px(300.)), None, Default::default());
        wait(&mut cx);
        assert_tooltip_painted(&mut cx, 0, false);
        assert_tooltip_painted(&mut cx, 1, false);
    }

    #[gpui::test]
    fn leaving_a_trigger_does_not_cancel_the_next_tooltip_delay(cx: &mut TestAppContext) {
        for (source, destination) in [(0, 1), (1, 0)] {
            let (mut cx, _) = open_adjacent_triggers(cx);
            cx.simulate_mouse_move(
                point(px(50. + source as f32 * 100.), px(25.)),
                None,
                Default::default(),
            );
            cx.executor().advance_clock(Duration::from_millis(100));
            cx.run_until_parked();
            cx.simulate_mouse_move(
                point(px(50. + destination as f32 * 100.), px(25.)),
                None,
                Default::default(),
            );
            wait(&mut cx);
            assert_tooltip_shown(&mut cx, destination);
        }
    }

    /// A press dismisses the tooltip, and it stays dismissed while the
    /// pointer stays on the trigger; leaving and coming back shows it again.
    #[gpui::test]
    fn a_press_dismisses_the_tooltip_until_the_pointer_leaves(cx: &mut TestAppContext) {
        let builds = Rc::new(Cell::new(0));
        let (mut cx, _) = open(cx, false, builds.clone());
        let at = point(px(50.), px(25.));
        cx.simulate_mouse_move(at, None, Default::default());
        wait(&mut cx);
        assert!(builds.get() > 0, "the hovered trigger shows its tooltip");

        // Hover reads false while the button is held, so the move after the
        // release is a hover-enter that must not show the tooltip.
        click_with_drift(&mut cx, at);
        cx.simulate_mouse_move(point(px(52.), px(25.)), None, Default::default());
        wait(&mut cx);
        assert_tooltip_painted(&mut cx, 0, false);

        cx.simulate_mouse_move(point(px(300.), px(300.)), None, Default::default());
        wait(&mut cx);
        cx.simulate_mouse_move(at, None, Default::default());
        wait(&mut cx);
        assert_tooltip_painted(&mut cx, 0, true);
    }

    /// A pointer move that lands between the release and the next frame is
    /// dispatched to the old frame, where the trigger is still hovered, so it
    /// used to request the tooltip again. The trigger is gone from the next
    /// frame, nothing ever sent the hover-leave, and the tooltip appeared
    /// after the show delay and stayed.
    #[gpui::test]
    fn clicking_a_trigger_away_does_not_leave_its_tooltip(cx: &mut TestAppContext) {
        let builds = Rc::new(Cell::new(0));
        let (mut cx, _) = open(cx, true, builds.clone());

        let at = point(px(50.), px(25.));
        cx.simulate_mouse_move(at, None, Default::default());
        draw(&mut cx);
        wait(&mut cx);
        draw(&mut cx);
        assert!(builds.get() > 0, "the hovered trigger shows its tooltip");

        // Press, drift a pixel while held, release, and drift again before
        // the next frame is drawn.
        cx.simulate_mouse_down(at, MouseButton::Left, Default::default());
        let drift = point(px(51.), px(25.));
        cx.simulate_mouse_move(drift, Some(MouseButton::Left), Default::default());
        // One update, so no frame is drawn between the two: the test
        // platform otherwise draws a dirty window after every event.
        cx.update(|window, cx| {
            window.dispatch_event(
                MouseUpEvent {
                    button: MouseButton::Left,
                    position: drift,
                    modifiers: Default::default(),
                    click_count: 1,
                }
                .to_platform_input(),
                cx,
            );
            window.dispatch_event(
                MouseMoveEvent {
                    position: point(px(52.), px(25.)),
                    pressed_button: None,
                    modifiers: Default::default(),
                }
                .to_platform_input(),
                cx,
            );
        });
        draw(&mut cx);
        wait(&mut cx);

        let before = builds.get();
        draw(&mut cx);
        assert_eq!(
            builds.get(),
            before,
            "no tooltip may be shown for a trigger the click removed"
        );
    }

    /// A trigger that a click removed never reports a hover-leave, so the
    /// press must end when the pointer moves away, or a trigger later shown
    /// at the same bounds would lose its tooltip.
    #[gpui::test]
    fn a_press_on_a_removed_trigger_ends_when_the_pointer_moves_away(cx: &mut TestAppContext) {
        let builds = Rc::new(Cell::new(0));
        let (mut cx, probe) = open(cx, true, builds.clone());
        let at = point(px(50.), px(25.));
        cx.simulate_mouse_move(at, None, Default::default());
        wait(&mut cx);

        cx.simulate_click(at, Default::default());
        wait(&mut cx);
        cx.simulate_mouse_move(point(px(300.), px(300.)), None, Default::default());
        wait(&mut cx);

        cx.update(|_, cx| {
            probe.update(cx, |probe, cx| {
                probe.shown = true;
                cx.notify();
            })
        });
        wait(&mut cx);
        let before = builds.get();
        cx.simulate_mouse_move(at, None, Default::default());
        wait(&mut cx);
        draw(&mut cx);
        assert!(
            builds.get() > before,
            "the trigger shown again has its tooltip"
        );
    }

    struct Buttons {
        shown: [bool; 2],
        delay: Duration,
    }

    impl Render for Buttons {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().children((0..2).filter_map(|index| {
                self.shown[index].then(|| {
                    crate::button::Button::new(("button", index))
                        .absolute()
                        .left(px(10. + index as f32 * 100.))
                        .top(px(10.))
                        .w(px(80.))
                        .h(px(30.))
                        .label(if index == 0 { "A" } else { "B" })
                        .tooltip(if index == 0 { "First" } else { "Second" })
                        .tooltip_show_delay(self.delay)
                })
            }))
        }
    }

    struct CachedButtons(Entity<Buttons>);

    impl Render for CachedButtons {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                self.0
                    .clone()
                    .cached(gpui::StyleRefinement::default().size_full()),
            )
        }
    }

    fn open_buttons(
        cx: &mut TestAppContext,
        shown: [bool; 2],
        delay: Duration,
    ) -> (VisualTestContext, Entity<Buttons>, Rc<Cell<usize>>) {
        cx.update(|cx| {
            crate::init(cx);
            // These tests cover tooltip lifetime, not intermediate fade frames.
            cx.set_reduce_motion(true);
        });
        let buttons = cx.new(|_| Buttons { shown, delay });
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                let content = cx.new(|_| CachedButtons(buttons.clone()));
                cx.new(|cx| Root::new(content, window, cx))
            })
            .unwrap()
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        draw(&mut cx);
        let builds = Rc::new(Cell::new(0));
        cx.update(|window, cx| {
            let builds = builds.clone();
            // Observe the real Button's overlay without changing Base's public
            // API or adding test-only markup to the production Tooltip.
            super::WindowState::tooltip_overlay(window, cx)
                .unwrap()
                .update(cx, |overlay, _| {
                    *overlay =
                        std::mem::take(overlay).render_with(move |view, transition, window, cx| {
                            builds.set(builds.get() + 1);
                            div()
                                .bg(gpui::rgb(TOOLTIP_COLORS[0]))
                                .child(super::render_tooltip(view, transition, window, cx))
                                .into_any_element()
                        });
                });
        });
        (cx, buttons, builds)
    }

    #[gpui::test]
    fn removing_button_hides_visible_tooltip(cx: &mut TestAppContext) {
        let (mut cx, buttons, _) = open_buttons(cx, [true, false], Duration::ZERO);
        cx.simulate_mouse_move(point(px(50.), px(25.)), None, Default::default());
        wait(&mut cx);
        assert_tooltip_painted(&mut cx, 0, true);
        // A redraw reusing the cached button subtree preserves the owner.
        draw(&mut cx);
        assert_tooltip_painted(&mut cx, 0, true);
        cx.update(|_, cx| {
            buttons.update(cx, |buttons, cx| {
                buttons.shown[0] = false;
                cx.notify();
            })
        });
        draw(&mut cx);
        cx.run_until_parked();
        assert_tooltip_painted(&mut cx, 0, false);
    }

    #[gpui::test]
    fn removing_button_cancels_pending_tooltip(cx: &mut TestAppContext) {
        let (mut cx, buttons, builds) = open_buttons(cx, [true, false], Duration::from_millis(500));
        cx.simulate_mouse_move(point(px(50.), px(25.)), None, Default::default());
        draw(&mut cx);
        // Finish the hover frame and drain its deferred cleanup before removal,
        // without advancing the pending tooltip's show delay.
        cx.run_until_parked();
        assert_eq!(builds.get(), 0, "tooltip is still pending");
        cx.update(|_, cx| {
            buttons.update(cx, |buttons, cx| {
                buttons.shown[0] = false;
                cx.notify();
            })
        });
        draw(&mut cx);
        cx.run_until_parked();
        wait(&mut cx);
        assert_eq!(
            builds.get(),
            0,
            "a removed trigger must never build its tooltip"
        );
        assert_tooltip_painted(&mut cx, 0, false);
    }

    #[gpui::test]
    fn pending_button_shows_after_deferred_work_drains(cx: &mut TestAppContext) {
        let (mut cx, _, builds) = open_buttons(cx, [true, false], Duration::from_millis(500));
        cx.simulate_mouse_move(point(px(50.), px(25.)), None, Default::default());
        draw(&mut cx);
        cx.run_until_parked();
        assert_eq!(builds.get(), 0, "tooltip is still pending");
        wait(&mut cx);
        assert!(
            builds.get() > 0,
            "a surviving trigger builds its delayed tooltip"
        );
        assert_tooltip_painted(&mut cx, 0, true);
    }

    #[gpui::test]
    fn removing_old_button_preserves_new_tooltip(cx: &mut TestAppContext) {
        let (mut cx, buttons, _) = open_buttons(cx, [true, true], Duration::ZERO);
        cx.simulate_mouse_move(point(px(50.), px(25.)), None, Default::default());
        wait(&mut cx);
        cx.simulate_mouse_move(point(px(150.), px(25.)), None, Default::default());
        wait(&mut cx);
        assert_tooltip_painted(&mut cx, 0, true);
        cx.update(|_, cx| {
            buttons.update(cx, |buttons, cx| {
                buttons.shown[0] = false;
                cx.notify();
            })
        });
        draw(&mut cx);
        cx.run_until_parked();
        assert_tooltip_painted(&mut cx, 0, true);
    }
}
