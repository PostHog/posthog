//! The element behind every [`Plot`]: layout, appear and hover tracking and
//! the overlay the plot returns from [`Plot::tooltip`].
use std::{cell::Cell, rc::Rc};

use gpui::{
    AnyElement, App, Bounds, Element, ElementId, GlobalElementId, Hitbox, HitboxBehavior,
    InspectorElementId, IntoElement, LayoutId, LongPressEvent, MouseMoveEvent, Pixels, Point, Size,
    Style, TouchPhase, Window,
};

use super::{Plot, PlotAppear, appear::track_appear, hover::track_hover};

/// Paints a [`Plot`] filling its container, with appear tracking when the plot
/// has an [`Plot::id`], and hover tracking and the plot's tooltip overlay when
/// it is also [`Plot::interactive`].
///
/// A plot becomes an element through this type:
///
/// ```ignore
/// impl IntoElement for Sparkline {
///     type Element = PlotElement<Self>;
///
///     fn into_element(self) -> Self::Element {
///         PlotElement::new(self)
///     }
/// }
/// ```
///
/// GPUI Component's `#[derive(IntoPlot)]` writes that impl.
pub struct PlotElement<P>(P);

impl<P: Plot + 'static> PlotElement<P> {
    pub fn new(plot: P) -> Self {
        Self(plot)
    }

    /// The last cursor position (plot-relative), shared by `prepaint` and `paint`.
    fn tooltip_cursor(
        global_id: &GlobalElementId,
        window: &mut Window,
    ) -> Rc<Cell<Option<Point<Pixels>>>> {
        window.with_element_state(global_id, |prev, _| {
            let cell: Rc<Cell<Option<Point<Pixels>>>> = prev.unwrap_or_default();
            (cell.clone(), cell)
        })
    }
}

impl<P: Plot + 'static> IntoElement for PlotElement<P> {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl<P: Plot + 'static> Element for PlotElement<P> {
    type RequestLayoutState = ();
    // The occlusion-aware hitbox, the plot's prepainted children and the
    // prepainted tooltip overlay, carried from `prepaint` to `paint`.
    type PrepaintState = (Option<Hitbox>, Vec<AnyElement>, Option<AnyElement>);

    fn id(&self) -> Option<ElementId> {
        // `Some` gives the plot element state: appear motion and, when
        // interactive, tooltips.
        self.0.id()
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let style = Style {
            size: Size::full(),
            ..Default::default()
        };
        (window.request_layout(style, None, cx), ())
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        // Children are laid out here, where `layout_as_root` / `prepaint_at` are legal,
        // and before the early return so plots without an id still get them.
        let children = self.0.prepaint(bounds, window, cx);

        let Some(global_id) = global_id else {
            return (None, children, None);
        };

        let appear = match self.0.appear_generation() {
            Some(generation) => track_appear(global_id, generation, window, cx),
            None => PlotAppear::complete(),
        };
        let appearing = appear.is_appearing();
        self.0.appear(appear, window, cx);

        if !self.0.interactive() {
            return (None, children, None);
        }

        // `Hitbox::is_hovered` is false while an open popup or modal covers the plot.
        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);

        // The cell only gates visibility; the position comes from the live mouse and
        // this frame's bounds so the tooltip does not lag a frame while scrolling.
        let cursor = Self::tooltip_cursor(global_id, window)
            .get()
            .map(|_| window.mouse_position())
            .filter(|mouse| bounds.contains(mouse))
            .map(|mouse| mouse - bounds.origin);
        // No tooltip while the marks draw in: its dots would land on data not
        // painted yet.
        let live = cursor
            .filter(|_| !appearing)
            .and_then(|position| self.0.tooltip_state(position, bounds, cx));

        // The datum under the cursor, or the last one while its hover fades out.
        let hover = track_hover(live, cursor, window, cx);
        self.0
            .hover(hover.as_ref().map(|(hover, _)| hover), window, cx);

        let overlay = hover.and_then(|(hover, cursor)| {
            let mut overlay = self.0.tooltip(hover.state(), cursor, bounds, window, cx)?;
            overlay.prepaint_as_root(bounds.origin, bounds.size.into(), window, cx);
            Some(overlay)
        });

        (Some(hitbox), children, overlay)
    }

    fn paint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.0.paint(bounds, window, cx);

        let (hitbox, children, overlay) = prepaint;
        for child in children.iter_mut() {
            child.paint(window, cx);
        }

        if let (Some(global_id), Some(hitbox)) = (global_id, hitbox.as_ref()) {
            let cell = Self::tooltip_cursor(global_id, window);
            let hitbox = hitbox.clone();
            // Notify only the view painting this plot: `window.refresh()` would drop
            // every sibling view's cache on each pixel of mouse movement.
            let view = window.current_view();

            if cfg!(any(target_os = "ios", target_os = "android")) {
                // A finger has no hover: only a long press opens the tooltip, drags
                // the crosshair, and closes it on lift.
                window.on_mouse_event(
                    move |e: &LongPressEvent, phase, window: &mut Window, cx: &mut App| {
                        if !phase.bubble() {
                            return;
                        }
                        let next = match e.phase {
                            TouchPhase::Started => {
                                if window.default_prevented() || !hitbox.is_hovered(window) {
                                    return;
                                }
                                window.prevent_default();
                                Some(e.start_position - bounds.origin)
                            }
                            TouchPhase::Moved => {
                                if cell.get().is_none() {
                                    return;
                                }
                                Some(e.position - bounds.origin)
                            }
                            TouchPhase::Ended | TouchPhase::Cancelled => None,
                        };
                        if cell.get() != next {
                            cell.set(next);
                            cx.notify(view);
                        }
                    },
                );
            } else {
                // Relayout can move the plot under a still cursor without a move
                // event, so re-derive hover each frame; only a visibility flip needs
                // a corrective frame.
                let next = hitbox
                    .is_hovered(window)
                    .then(|| window.mouse_position() - bounds.origin);
                if cell.get() != next {
                    let visibility_changed = cell.get().is_some() != next.is_some();
                    cell.set(next);
                    if visibility_changed {
                        window.request_animation_frame();
                    }
                }

                window.on_mouse_event(
                    move |e: &MouseMoveEvent, _, window: &mut Window, cx: &mut App| {
                        let next = hitbox
                            .is_hovered(window)
                            .then(|| e.position - bounds.origin);
                        if cell.get() != next {
                            cell.set(next);
                            cx.notify(view);
                        }
                    },
                );
            }
        }

        // Crosshair and dots paint above the plot; the deferred box paints above everything.
        if let Some(overlay) = overlay.as_mut() {
            overlay.paint(window, cx);
        }
    }
}
