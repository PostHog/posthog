use std::sync::{Arc, Mutex};
use std::time::Duration;

use gpui::{AsyncApp, Bounds, Context, Pixels, Point, Task, WeakEntity, px};

/// Manages timer-based auto-scrolling during drag interactions.
///
/// Delta convention: positive moves toward the bottom and negative moves
/// toward the top.
pub struct AutoScroll {
    /// Shared between the main thread and the background task.
    /// Writing `None` is the stop signal; the task exits on its next tick.
    shared: Arc<Mutex<Option<Pixels>>>,
    task: Option<Task<()>>,
    /// Last drag position, available to the interaction that owns selection.
    pub last_drag_position: Option<Point<Pixels>>,
}

impl Default for AutoScroll {
    fn default() -> Self {
        Self {
            shared: Arc::new(Mutex::new(None)),
            task: None,
            last_drag_position: None,
        }
    }
}

impl AutoScroll {
    /// Returns the current scroll delta.
    pub fn delta(&self) -> Option<Pixels> {
        *self.shared.lock().unwrap()
    }

    /// Computes the scroll delta for a pointer Y position within the viewport.
    pub fn compute_delta(y: Pixels, bounds: Bounds<Pixels>) -> Option<Pixels> {
        const MIN_SPEED: f32 = 12.0;
        const MAX_SPEED: f32 = 64.0;
        // Trigger starts this far inside the bounds so scrolling works even in
        // full-screen where the mouse can't travel far outside the element.
        const INNER_ZONE: f32 = 16.0;
        // Distance from the bounds edge to reach MAX_SPEED.
        // Total ramp = INNER_ZONE + OUTER_RAMP, giving a single smooth curve
        // with no flat sections or discontinuities.
        const OUTER_RAMP: f32 = 80.0;

        let bottom_trigger = bounds.bottom() - px(INNER_ZONE);
        let top_trigger = bounds.top() + px(INNER_ZONE);

        if y > bottom_trigger {
            let t = ((y - bottom_trigger) / px(INNER_ZONE + OUTER_RAMP)).min(1.0);
            Some(px(MIN_SPEED + t * (MAX_SPEED - MIN_SPEED)))
        } else if y < top_trigger {
            let t = ((top_trigger - y) / px(INNER_ZONE + OUTER_RAMP)).min(1.0);
            Some(px(-(MIN_SPEED + t * (MAX_SPEED - MIN_SPEED))))
        } else {
            None
        }
    }

    /// Updates the scroll delta and starts the background task when needed.
    ///
    /// `tick` is called each frame (~60 fps) with the current delta.
    /// It should perform the actual scroll action for this entity.
    pub fn set<T, F>(&mut self, delta: Option<Pixels>, cx: &mut Context<T>, tick: F)
    where
        T: 'static,
        F: Fn(Pixels, &mut T, &mut Context<T>) + Send + 'static,
    {
        let was_idle = self.task.is_none();
        *self.shared.lock().unwrap() = delta;

        if delta.is_none() {
            self.task = None;
            return;
        }

        if was_idle {
            let shared = Arc::clone(&self.shared);
            self.task = Some(cx.spawn(Self::task_loop(shared, tick)));
        }
    }

    fn task_loop<T, F>(
        shared: Arc<Mutex<Option<Pixels>>>,
        tick: F,
    ) -> impl AsyncFnOnce(WeakEntity<T>, &mut AsyncApp) + 'static
    where
        T: 'static,
        F: Fn(Pixels, &mut T, &mut Context<T>) + Send + 'static,
    {
        async move |this: WeakEntity<T>, cx: &mut AsyncApp| {
            loop {
                cx.background_executor()
                    .timer(Duration::from_millis(16))
                    .await;
                let Some(delta) = *shared.lock().unwrap() else {
                    break;
                };
                let alive = this
                    .update(cx, |state, cx| {
                        tick(delta, state, cx);
                        true
                    })
                    .unwrap_or(false);
                if !alive {
                    break;
                }
            }
        }
    }

    /// Returns whether automatic scrolling is active.
    pub fn is_active(&self) -> bool {
        self.delta().is_some()
    }

    /// Stops automatic scrolling and clears the last drag position.
    pub fn stop(&mut self) {
        *self.shared.lock().unwrap() = None;
        self.task = None;
        self.last_drag_position = None;
    }
}

#[cfg(test)]
mod tests {
    use gpui::{Bounds, point, size};

    use super::*;

    #[test]
    fn delta_uses_dead_zone_and_symmetric_edge_ramps() {
        let bounds = Bounds::new(point(px(0.), px(100.)), size(px(200.), px(100.)));

        assert_eq!(AutoScroll::compute_delta(px(150.), bounds), None);

        let top = AutoScroll::compute_delta(px(80.), bounds).unwrap();
        let bottom = AutoScroll::compute_delta(px(220.), bounds).unwrap();
        assert_eq!(top, -bottom);
        assert!(top < px(-12.));
    }

    #[test]
    fn stop_clears_delta_and_drag_position() {
        let mut scroll = AutoScroll::default();
        *scroll.shared.lock().unwrap() = Some(px(20.));
        scroll.last_drag_position = Some(point(px(1.), px(2.)));

        scroll.stop();

        assert!(!scroll.is_active());
        assert_eq!(scroll.last_drag_position, None);
    }
}
