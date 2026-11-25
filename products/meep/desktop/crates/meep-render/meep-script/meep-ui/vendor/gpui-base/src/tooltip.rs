use std::{rc::Rc, time::Duration};

use gpui::{
    AnyElement, AnyView, App, Bounds, Context, Div, ElementId, Global, InteractiveElement,
    IntoElement, ParentElement, Pixels, Render, RenderOnce, Role, Stateful,
    StatefulInteractiveElement, Styled, Task, Window, deferred, div, prelude::FluentBuilder as _,
    px,
};

use crate::{Placement, Positioner};

const TOOLTIP_PRIORITY: usize = 200;
const WINDOW_MARGIN: Pixels = px(4.);

type TooltipBuilder = Rc<dyn Fn(&mut Window, &mut App) -> AnyView>;
type TooltipRenderer = Rc<dyn Fn(AnyView, TooltipTransition, &mut Window, &mut App) -> AnyElement>;

/// An unstyled tooltip popup.
///
/// This corresponds to Base UI's `Tooltip.Popup`: it owns the accessible
/// tooltip role and accepts application-owned content and presentation.
#[derive(IntoElement)]
pub struct Tooltip {
    base: Stateful<Div>,
}

impl Tooltip {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).role(Role::Tooltip),
        }
    }
}

impl Styled for Tooltip {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        self.base.style()
    }
}

impl ParentElement for Tooltip {
    fn extend(&mut self, children: impl IntoIterator<Item = AnyElement>) {
        self.base.extend(children);
    }
}

impl RenderOnce for Tooltip {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
    }
}

/// Application-wide timing for tooltips shown through [`TooltipOverlay`].
///
/// Read on every show and hide request, so installing new defaults takes
/// effect in windows that are already open.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TooltipDefaults {
    show_delay: Duration,
    grace_period: Duration,
}

impl Global for TooltipDefaults {}

impl TooltipDefaults {
    /// Creates the Base defaults: a 500 ms show delay and a 300 ms grace period.
    pub fn new() -> Self {
        Self {
            show_delay: Duration::from_millis(500),
            grace_period: Duration::from_millis(300),
        }
    }

    /// Sets how long the pointer must rest on a trigger before its tooltip shows.
    pub fn with_show_delay(mut self, delay: Duration) -> Self {
        self.show_delay = delay;
        self
    }

    /// Sets how long a tooltip stays after the pointer leaves its trigger.
    ///
    /// Entering another trigger within this period switches to its tooltip
    /// without waiting for the show delay.
    pub fn with_grace_period(mut self, period: Duration) -> Self {
        self.grace_period = period;
        self
    }

    /// How long the pointer must rest on a trigger before its tooltip shows.
    pub fn show_delay(&self) -> Duration {
        self.show_delay
    }

    /// How long a tooltip stays after the pointer leaves its trigger.
    pub fn grace_period(&self) -> Duration {
        self.grace_period
    }

    /// Installs these defaults for the whole application.
    pub fn install(self, cx: &mut App) {
        cx.set_global(self);
    }

    /// Returns the installed defaults, or the Base ones when none were.
    pub fn global(cx: &App) -> Self {
        cx.try_global::<Self>().copied().unwrap_or_default()
    }
}

impl Default for TooltipDefaults {
    fn default() -> Self {
        Self::new()
    }
}

/// Content requested by a tooltip trigger.
#[derive(Clone)]
pub struct TooltipRequest {
    build: TooltipBuilder,
    trigger_bounds: Bounds<Pixels>,
    preferred_placement: Option<Placement>,
    show_delay: Option<Duration>,
}

impl TooltipRequest {
    pub fn new(
        trigger_bounds: Bounds<Pixels>,
        build: impl Fn(&mut Window, &mut App) -> AnyView + 'static,
    ) -> Self {
        Self {
            build: Rc::new(build),
            trigger_bounds,
            preferred_placement: None,
            show_delay: None,
        }
    }

    /// Prefers a side for the tooltip, falling back when it does not fit.
    pub fn with_placement(mut self, placement: Placement) -> Self {
        self.preferred_placement = Some(placement);
        self
    }

    #[deprecated(note = "use `with_placement`")]
    pub fn placement(self, placement: Placement) -> Self {
        self.with_placement(placement)
    }

    /// Overrides [`TooltipDefaults::show_delay`] for this trigger.
    pub fn with_show_delay(mut self, delay: Duration) -> Self {
        self.show_delay = Some(delay);
        self
    }
}

/// Presentation transition requested by the Base tooltip lifecycle.
#[derive(Clone, Copy, Debug)]
pub enum TooltipTransition {
    Enter {
        epoch: usize,
    },
    Switch {
        epoch: usize,
        previous: Bounds<Pixels>,
        current: Bounds<Pixels>,
    },
}

/// Per-window tooltip provider and overlay.
///
/// Show requests are ignored on iOS and Android, where touch input must not
/// open hover tooltips. This does not control GPUI's native `.tooltip()` API.
pub struct TooltipOverlay {
    enabled: bool,
    content: Option<TooltipRequest>,
    previous_bounds: Option<Bounds<Pixels>>,
    epoch: usize,
    had_recent_tooltip: bool,
    animation_epoch: usize,
    is_switching: bool,
    show_task: Option<Task<()>>,
    hide_task: Option<Task<()>>,
    renderer: TooltipRenderer,
}

impl TooltipOverlay {
    pub fn new() -> Self {
        Self {
            enabled: !crate::is_mobile(),
            content: None,
            previous_bounds: None,
            epoch: 0,
            had_recent_tooltip: false,
            animation_epoch: 0,
            is_switching: false,
            show_task: None,
            hide_task: None,
            renderer: Rc::new(|view, _, _, _| div().child(view).into_any_element()),
        }
    }

    pub fn render_with(
        mut self,
        renderer: impl Fn(AnyView, TooltipTransition, &mut Window, &mut App) -> AnyElement + 'static,
    ) -> Self {
        self.renderer = Rc::new(renderer);
        self
    }

    fn next_epoch(&mut self) -> usize {
        self.epoch += 1;
        self.epoch
    }

    pub fn request_show(
        &mut self,
        content: TooltipRequest,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // Gate both delayed display and the immediate grace-period switch.
        // Keep this in Base so every managed component shares the policy.
        if !self.enabled {
            return;
        }
        self.hide_task = None;
        let show_delay = content
            .show_delay
            .unwrap_or_else(|| TooltipDefaults::global(cx).show_delay);
        let was_visible = self.content.is_some();
        if was_visible || self.had_recent_tooltip || show_delay.is_zero() {
            self.previous_bounds = self.content.as_ref().map(|content| content.trigger_bounds);
            self.content = Some(content);
            self.show_task = None;
            self.is_switching = was_visible;
            self.animation_epoch += 1;
            cx.notify();
            return;
        }

        let epoch = self.next_epoch();
        self.show_task = Some(cx.spawn_in(window, async move |this, cx| {
            cx.background_executor().timer(show_delay).await;
            let _ = this.update_in(cx, |this, _, cx| {
                if this.epoch == epoch {
                    this.content = Some(content);
                    this.previous_bounds = None;
                    this.is_switching = false;
                    this.animation_epoch += 1;
                    cx.notify();
                }
            });
        }));
    }

    pub fn request_hide(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.show_task = None;
        if self.content.is_none() {
            return;
        }
        let epoch = self.next_epoch();
        let grace_period = TooltipDefaults::global(cx).grace_period;
        self.had_recent_tooltip = true;
        self.hide_task = Some(cx.spawn_in(window, async move |this, cx| {
            cx.background_executor().timer(grace_period).await;
            let _ = this.update_in(cx, |this, _, cx| {
                if this.epoch == epoch {
                    this.content = None;
                    this.previous_bounds = None;
                    this.had_recent_tooltip = false;
                    cx.notify();
                }
            });
        }));
    }

    pub fn hide(&mut self, cx: &mut Context<Self>) {
        let changed = self.content.is_some()
            || self.previous_bounds.is_some()
            || self.had_recent_tooltip
            || self.show_task.is_some()
            || self.hide_task.is_some();
        self.content = None;
        self.previous_bounds = None;
        self.had_recent_tooltip = false;
        self.is_switching = false;
        self.show_task = None;
        self.hide_task = None;
        if changed {
            cx.notify();
        }
    }
}

impl Default for TooltipOverlay {
    fn default() -> Self {
        Self::new()
    }
}

impl Render for TooltipOverlay {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let Some(content) = self.content.as_ref() else {
            return div().into_any_element();
        };
        let view = (content.build)(window, cx);
        let transition = match (self.is_switching, self.previous_bounds) {
            (true, Some(previous)) => TooltipTransition::Switch {
                epoch: self.animation_epoch,
                previous,
                current: content.trigger_bounds,
            },
            _ => TooltipTransition::Enter {
                epoch: self.animation_epoch,
            },
        };
        let rendered = (self.renderer)(view, transition, window, cx);
        deferred(
            TooltipPositioner::new(content.trigger_bounds)
                .when_some(content.preferred_placement, |this, placement| {
                    this.placement(placement)
                })
                .child(rendered),
        )
        .with_priority(TOOLTIP_PRIORITY)
        .into_any_element()
    }
}

/// An unstyled tooltip positioner with viewport-aware flipping and clamping.
///
/// This is a tooltip-named view of [`crate::Positioner`]'s side placement. It
/// adds no element of its own; the shared positioner is what gets rendered.
pub struct TooltipPositioner(Positioner);

impl TooltipPositioner {
    pub fn new(trigger_bounds: Bounds<Pixels>) -> Self {
        Self(Positioner::side(trigger_bounds).margin(WINDOW_MARGIN))
    }

    pub fn placement(mut self, placement: Placement) -> Self {
        self.0 = self.0.placement(placement);
        self
    }
}

impl ParentElement for TooltipPositioner {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.0.extend(elements);
    }
}

impl IntoElement for TooltipPositioner {
    type Element = Positioner;

    fn into_element(self) -> Self::Element {
        self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{AppContext as _, point, size};

    fn bounds(x: f32, y: f32, width: f32, height: f32) -> Bounds<Pixels> {
        Bounds::new(point(px(x), px(y)), size(px(width), px(height)))
    }

    #[gpui::test]
    fn provider_owns_grace_switch_and_dismiss(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| cx.new(|_| TooltipOverlay::new()));
        let cx = cx.add_empty_window();
        cx.update(|window, cx| {
            state.update(cx, |tooltip, cx| {
                tooltip.had_recent_tooltip = true;
                tooltip.request_show(
                    TooltipRequest::new(bounds(0., 0., 20., 20.), |_, _| {
                        panic!("content is not rendered by this lifecycle test")
                    }),
                    window,
                    cx,
                );
            });
        });
        cx.update(|_, cx| assert!(state.read(cx).content.is_some()));

        cx.update(|_, cx| {
            state.update(cx, |tooltip, cx| tooltip.hide(cx));
        });
        cx.update(|_, cx| assert!(state.read(cx).content.is_none()));
    }

    #[gpui::test]
    fn show_delay_follows_defaults_and_request_override(cx: &mut gpui::TestAppContext) {
        cx.update(|cx| {
            TooltipDefaults::new()
                .with_show_delay(Duration::from_millis(100))
                .install(cx)
        });
        // The delayed show updates the overlay in the window it was drawn in.
        let (state, cx) = cx.add_window_view(|_, _| TooltipOverlay::new());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let request = || {
            TooltipRequest::new(bounds(0., 0., 20., 20.), |_, cx| {
                cx.new(|_| gpui::Empty).into()
            })
        };

        cx.update(|window, cx| {
            state.update(cx, |tooltip, cx| {
                tooltip.request_show(request(), window, cx)
            });
        });
        cx.executor().advance_clock(Duration::from_millis(99));
        cx.run_until_parked();
        cx.update(|_, cx| assert!(state.read(cx).content.is_none()));
        cx.executor().advance_clock(Duration::from_millis(1));
        cx.run_until_parked();
        cx.update(|_, cx| assert!(state.read(cx).content.is_some()));

        cx.update(|_, cx| state.update(cx, |tooltip, cx| tooltip.hide(cx)));
        cx.update(|window, cx| {
            state.update(cx, |tooltip, cx| {
                tooltip.request_show(request().with_show_delay(Duration::ZERO), window, cx);
                assert!(tooltip.content.is_some());
                assert!(tooltip.show_task.is_none());
            });
        });
    }

    #[test]
    fn tooltip_priority_exceeds_popup_layer() {
        assert!(TOOLTIP_PRIORITY > crate::POPUP_PRIORITY);
    }

    #[gpui::test]
    fn disabled_provider_ignores_delayed_and_immediate_requests(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| {
            cx.new(|_| TooltipOverlay {
                enabled: false,
                ..TooltipOverlay::new()
            })
        });
        let cx = cx.add_empty_window();
        for had_recent_tooltip in [false, true] {
            cx.update(|window, cx| {
                state.update(cx, |tooltip, cx| {
                    tooltip.had_recent_tooltip = had_recent_tooltip;
                    tooltip.request_show(
                        TooltipRequest::new(bounds(0., 0., 20., 20.), |_, _| {
                            panic!("disabled tooltips must not build content")
                        }),
                        window,
                        cx,
                    );
                    assert!(tooltip.content.is_none());
                    assert!(tooltip.show_task.is_none());
                    assert!(tooltip.hide_task.is_none());
                    assert_eq!(tooltip.animation_epoch, 0);
                });
            });
        }
    }
}
