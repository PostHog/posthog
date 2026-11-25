use gpui::{
    App, ClickEvent, InteractiveElement, OngoingScroll, Pixels, Point, Stateful,
    StatefulInteractiveElement, TouchPhase, Window,
};

/// gpui delimits scroll gestures with `std::time::Instant`, which is
/// unimplemented on wasm32: the first wheel event over an axis-locked scroll
/// area panics with "time not implemented on this platform" and takes the whole
/// application down, leaving the canvas unresponsive. Losing the axis lock in
/// the browser is by far the lesser cost, so the locks below are no-ops there.
pub trait OngoingScrollExt {
    /// Locks a wheel delta to the axis its gesture started on, where the
    /// platform supports it.
    fn lock_axis(&mut self, delta: &mut Point<Pixels>, touch_phase: TouchPhase);
}

impl OngoingScrollExt for OngoingScroll {
    fn lock_axis(&mut self, delta: &mut Point<Pixels>, touch_phase: TouchPhase) {
        #[cfg(target_family = "wasm")]
        let _ = (delta, touch_phase);
        #[cfg(not(target_family = "wasm"))]
        self.filter(delta, touch_phase);
    }
}

pub trait InteractiveElementExt: InteractiveElement {
    /// Locks scrolling to the gesture's dominant axis, where the platform
    /// supports it. See [`OngoingScrollExt`] for why this is a no-op on wasm32.
    fn lock_scroll_axis(self) -> Self
    where
        Self: Sized + StatefulInteractiveElement,
    {
        #[cfg(target_family = "wasm")]
        {
            self
        }
        #[cfg(not(target_family = "wasm"))]
        {
            self.restrict_scroll_to_axis()
        }
    }

    /// Set the listener for a double click event.
    fn on_double_click(
        mut self,
        listener: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self
    where
        Self: Sized,
    {
        self.interactivity().on_click(move |event, window, cx| {
            if event.click_count() == 2 {
                listener(event, window, cx);
            }
        });
        self
    }
}

impl<E: InteractiveElement> InteractiveElementExt for Stateful<E> {}
