use gpui::{App, Context, Pixels, Subscription, Task, px};
use instant::Duration;
use web_time::Instant;

static INTERVAL: Duration = Duration::from_millis(500);
static PAUSE_DELAY: Duration = Duration::from_millis(300);

pub(super) const CURSOR_WIDTH: Pixels = px(1.);

/// Application-wide caret visibility policy.
///
/// The default blinks every 500 ms without an idle timeout.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CursorBlink {
    interval: Duration,
    idle_timeout: Option<Duration>,
}

impl CursorBlink {
    /// Keep the focused caret visible without a timer.
    pub const fn steady() -> Self {
        Self {
            interval: Duration::ZERO,
            idle_timeout: None,
        }
    }

    /// Alternate visible and hidden phases of `interval` each; zero means steady.
    pub const fn blinking(interval: Duration) -> Self {
        Self {
            interval,
            idle_timeout: None,
        }
    }

    /// Stop blinking, with the caret visible, once `timeout` has passed since
    /// the last focus, edit or cursor movement.
    pub const fn with_idle_timeout(mut self, timeout: Duration) -> Self {
        self.idle_timeout = Some(timeout);
        self
    }

    /// The duration of each visible or hidden phase, or `None` when steady.
    pub fn interval(&self) -> Option<Duration> {
        (!self.interval.is_zero()).then_some(self.interval)
    }

    /// The time since the last activity after which blinking stops.
    pub fn idle_timeout(&self) -> Option<Duration> {
        self.interval().and(self.idle_timeout)
    }

    /// Whether the focused caret stays visible without blinking.
    pub fn is_steady(&self) -> bool {
        self.interval.is_zero()
    }

    /// Collapse every steady spelling to one value, so a change between them
    /// is not mistaken for a policy change.
    fn normalized(self) -> Self {
        if self.is_steady() {
            Self::steady()
        } else {
            self
        }
    }
}

impl Default for CursorBlink {
    fn default() -> Self {
        Self::blinking(INTERVAL)
    }
}

fn cursor_blink(cx: &App) -> CursorBlink {
    cx.try_global::<crate::Theme>()
        .map(|theme| theme.cursor_blink)
        .unwrap_or_default()
        .normalized()
}

pub(crate) struct BlinkCursor {
    visible: bool,
    paused: bool,
    epoch: usize,
    last_activity: Option<Instant>,
    policy: CursorBlink,
    _task: Task<()>,
    _policy_subscription: Subscription,
}

impl BlinkCursor {
    pub(crate) fn new(cx: &mut Context<Self>) -> Self {
        Self {
            visible: false,
            paused: false,
            epoch: 0,
            last_activity: None,
            policy: cursor_blink(cx),
            _task: Task::ready(()),
            _policy_subscription: cx.observe_global::<crate::Theme>(|this, cx| {
                let policy = cursor_blink(cx);
                if policy == this.policy {
                    return;
                }
                this.policy = policy;
                if this.last_activity.is_some() {
                    this.epoch = this.epoch.wrapping_add(1);
                    this.set_visible(true, cx);
                    this.schedule(cx);
                }
            }),
        }
    }

    pub(crate) fn start(&mut self, cx: &mut Context<Self>) {
        self.epoch = self.epoch.wrapping_add(1);
        self.last_activity = Some(cx.background_executor().now());
        self.paused = false;
        self.set_visible(true, cx);
        self.schedule(cx);
    }

    pub(crate) fn stop(&mut self, cx: &mut Context<Self>) {
        self.epoch = self.epoch.wrapping_add(1);
        self.last_activity = None;
        self.paused = false;
        self._task = Task::ready(());
        self.set_visible(false, cx);
    }

    pub(crate) fn pause(&mut self, cx: &mut Context<Self>) {
        if self.last_activity.is_none() {
            return;
        }

        self.epoch = self.epoch.wrapping_add(1);
        self.last_activity = Some(cx.background_executor().now());
        self.paused = true;
        self.set_visible(true, cx);
        self.schedule(cx);
    }

    pub(crate) fn visible(&self) -> bool {
        self.visible
    }

    fn set_visible(&mut self, visible: bool, cx: &mut Context<Self>) {
        if self.visible != visible {
            self.visible = visible;
            cx.notify();
        }
    }

    fn blink_delay(&self, cx: &App) -> Option<Duration> {
        let last_activity = self.last_activity?;
        let interval = self.policy.interval()?;

        let elapsed = cx.background_executor().now() - last_activity;
        let delay = if self.paused && elapsed < PAUSE_DELAY {
            PAUSE_DELAY - elapsed
        } else {
            interval
        };

        match self.policy.idle_timeout() {
            Some(timeout) if elapsed >= timeout => None,
            Some(timeout) => Some(delay.min(timeout - elapsed)),
            None => Some(delay),
        }
    }

    fn schedule(&mut self, cx: &mut Context<Self>) {
        self._task = Task::ready(());
        let Some(delay) = self.blink_delay(cx) else {
            self.paused = false;
            self.set_visible(true, cx);
            return;
        };

        let epoch = self.epoch;
        let timer = cx.background_executor().timer(delay);
        self._task = cx.spawn(async move |this, cx| {
            timer.await;
            _ = this.update(cx, |this, cx| {
                if epoch != this.epoch {
                    return;
                }

                if this.blink_delay(cx).is_some() {
                    this.paused = false;
                    this.set_visible(!this.visible, cx);
                }
                this.schedule(cx);
            });
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{AppContext as _, Entity, TestAppContext};
    use std::{cell::Cell, rc::Rc};

    fn set_cursor_blink(policy: CursorBlink, cx: &mut App) {
        crate::Theme::global_mut(cx).cursor_blink = policy;
    }

    #[test]
    fn test_cursor_blink_builder() {
        let policy = CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_secs(5));
        assert_eq!(policy.interval(), Some(INTERVAL));
        assert_eq!(policy.idle_timeout(), Some(Duration::from_secs(5)));
        assert!(!policy.is_steady());
        assert_eq!(CursorBlink::default(), CursorBlink::blinking(INTERVAL));

        let steady = CursorBlink::blinking(Duration::ZERO).with_idle_timeout(INTERVAL);
        assert!(steady.is_steady());
        assert_eq!(steady.interval(), None);
        assert_eq!(steady.idle_timeout(), None);
        assert_eq!(steady.normalized(), CursorBlink::steady());
    }

    fn advance(cx: &mut TestAppContext, duration: Duration) {
        cx.run_until_parked();
        cx.executor().advance_clock(duration);
        cx.run_until_parked();
    }

    fn assert_idle(cursor: &Entity<BlinkCursor>, visible: bool, cx: &mut TestAppContext) {
        cx.run_until_parked();
        let notifications = Rc::new(Cell::new(0usize));
        let count = notifications.clone();
        let _observer = cx.update(|cx| cx.observe(cursor, move |_, _| count.set(count.get() + 1)));

        advance(cx, Duration::from_secs(3));

        assert_eq!(cursor.read_with(cx, |cursor, _| cursor.visible()), visible);
        assert!(cursor.read_with(cx, |cursor, _| cursor._task.is_ready()));
        assert_eq!(notifications.get(), 0);
    }

    #[gpui::test]
    fn repeated_pauses_keep_cursor_visible_until_idle(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        // Only a focused input blinks, and only a blinking cursor pauses.
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        for _ in 0..5 {
            cursor.update(cx, |cursor, cx| cursor.pause(cx));
            cx.run_until_parked();
            cx.executor().advance_clock(Duration::from_millis(200));
            cx.run_until_parked();
            assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        }
        cx.executor().advance_clock(Duration::from_millis(100));
        cx.run_until_parked();
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        cx.executor().advance_clock(INTERVAL);
        cx.run_until_parked();
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn starting_a_blinking_cursor_keeps_it_visible(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);

        // Clicking into an input starts the cursor from `focus` and again from
        // the focus observer; the second start must not hide the new cursor.
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));

        // The restart drops the first cycle's timer, so the cursor stays
        // visible for a full interval before it blinks off.
        cx.executor()
            .advance_clock(INTERVAL - Duration::from_millis(1));
        cx.run_until_parked();
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        cx.executor().advance_clock(Duration::from_millis(1));
        cx.run_until_parked();
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn pausing_a_cursor_that_is_not_blinking_does_not_start_it(cx: &mut TestAppContext) {
        // Never focused, so `start` was never called: the epoch is still zero.
        let cursor = cx.new(BlinkCursor::new);

        // What a programmatic `set_value` on an unfocused input does.
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        cx.run_until_parked();
        cx.executor().advance_clock(PAUSE_DELAY);
        cx.run_until_parked();
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        let notifies = Rc::new(Cell::new(0usize));
        let counter = notifies.clone();
        let _observer =
            cx.update(|cx| cx.observe(&cursor, move |_, _| counter.set(counter.get() + 1)));
        cx.run_until_parked();

        cx.executor().advance_clock(INTERVAL * 6);
        cx.run_until_parked();

        assert_eq!(
            notifies.get(),
            0,
            "a cursor that was never started is blinking, and every blink repaints the view"
        );
    }

    #[gpui::test]
    fn blurring_a_paused_cursor_leaves_the_next_focus_blinking(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();

        // Typing pauses the blink, then the input is blurred before the pause
        // elapses: tabbing away right after a keystroke does exactly this.
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        cx.run_until_parked();
        cursor.update(cx, |cursor, cx| cursor.stop(cx));
        cx.run_until_parked();
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        // Focusing again shows the cursor and blinks it, rather than leaving a
        // stale pause to swallow the start.
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        cx.executor().advance_clock(INTERVAL);
        cx.run_until_parked();
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn stopping_a_paused_cursor_ends_the_blink_loop(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        cx.run_until_parked();
        cursor.update(cx, |cursor, cx| cursor.stop(cx));
        cx.run_until_parked();

        let notifications = Rc::new(Cell::new(0usize));
        let count = notifications.clone();
        let _observer = cx.update(|cx| cx.observe(&cursor, move |_, _| count.set(count.get() + 1)));
        cx.run_until_parked();

        cx.executor().advance_clock(Duration::from_secs(3));
        cx.run_until_parked();

        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        assert_eq!(notifications.get(), 0, "a stopped cursor kept blinking");

        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn stopping_a_blinking_cursor_ends_the_blink_loop(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cx.run_until_parked();
        cursor.update(cx, |cursor, cx| cursor.stop(cx));
        cx.run_until_parked();

        let notifications = Rc::new(Cell::new(0usize));
        let count = notifications.clone();
        let _observer = cx.update(|cx| cx.observe(&cursor, move |_, _| count.set(count.get() + 1)));
        cx.run_until_parked();

        cx.executor().advance_clock(Duration::from_secs(3));
        cx.run_until_parked();

        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        assert_eq!(notifications.get(), 0, "a stopped cursor kept blinking");
    }

    #[gpui::test]
    fn idle_timeout_stops_between_blinks_and_activity_restarts_it(cx: &mut TestAppContext) {
        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_millis(750)),
                cx,
            )
        });
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));

        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(249));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(1));
        assert_idle(&cursor, true, cx);

        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        advance(cx, PAUSE_DELAY);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(450));
        assert_idle(&cursor, true, cx);

        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn idle_timeout_includes_the_typing_pause(cx: &mut TestAppContext) {
        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_millis(200)),
                cx,
            )
        });
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, Duration::from_millis(100));
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        advance(cx, Duration::from_millis(199));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        assert!(!cursor.read_with(cx, |cursor, _| cursor._task.is_ready()));
        advance(cx, Duration::from_millis(1));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn steady_and_zero_durations_never_schedule_blinks(cx: &mut TestAppContext) {
        for policy in [
            CursorBlink::steady(),
            CursorBlink::blinking(Duration::ZERO),
            CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::ZERO),
        ] {
            cx.update(|cx| set_cursor_blink(policy, cx));
            let cursor = cx.new(BlinkCursor::new);
            cursor.update(cx, |cursor, cx| cursor.start(cx));
            assert_idle(&cursor, true, cx);
            cursor.update(cx, |cursor, cx| cursor.pause(cx));
            assert_idle(&cursor, true, cx);
        }
    }

    #[gpui::test]
    fn policy_changes_resume_idle_cursors_without_resetting_activity(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        cx.update(|cx| set_cursor_blink(CursorBlink::steady(), cx));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_secs(1));

        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(Duration::from_millis(100))
                    .with_idle_timeout(Duration::from_secs(1)),
                cx,
            )
        });
        assert!(cursor.read_with(cx, |cursor, _| cursor._task.is_ready()));

        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(Duration::from_millis(100))
                    .with_idle_timeout(Duration::from_secs(2)),
                cx,
            )
        });
        advance(cx, Duration::from_millis(100));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(400));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        assert!(cursor.read_with(cx, |cursor, _| cursor._task.is_ready()));

        cx.update(|cx| set_cursor_blink(CursorBlink::blinking(Duration::from_millis(100)), cx));
        advance(cx, Duration::from_millis(100));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn changing_the_interval_restarts_the_visible_phase_and_cancels_old_blinks(
        cx: &mut TestAppContext,
    ) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, Duration::from_millis(250));

        cx.update(|cx| set_cursor_blink(CursorBlink::blinking(Duration::from_secs(1)), cx));
        advance(cx, Duration::from_millis(250));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(749));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(1));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        cx.update(|cx| set_cursor_blink(CursorBlink::steady(), cx));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn unchanged_policy_preserves_the_phase_and_idle_deadline(cx: &mut TestAppContext) {
        let policy = CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_millis(750));
        cx.update(|cx| set_cursor_blink(policy, cx));
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        cx.update(|cx| set_cursor_blink(policy, cx));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(249));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(1));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn unrelated_theme_changes_preserve_the_blink_phase_and_idle_deadline(cx: &mut TestAppContext) {
        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_millis(750)),
                cx,
            );
        });
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        cx.update(|cx| crate::Theme::global_mut(cx).appearance = crate::ThemeAppearance::Dark);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(249));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(1));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn policy_changes_preserve_the_remaining_typing_pause(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        advance(cx, Duration::from_millis(100));

        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(Duration::from_millis(200))
                    .with_idle_timeout(Duration::from_millis(400)),
                cx,
            )
        });
        advance(cx, Duration::from_millis(199));
        assert!(cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(1));
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));
        advance(cx, Duration::from_millis(100));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn steady_policy_cancels_the_typing_pause(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        cursor.update(cx, |cursor, cx| cursor.pause(cx));
        advance(cx, Duration::from_millis(100));
        cx.update(|cx| set_cursor_blink(CursorBlink::steady(), cx));
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn unfocused_cursors_ignore_policy_changes(cx: &mut TestAppContext) {
        let never_focused = cx.new(BlinkCursor::new);
        let blurred = cx.new(BlinkCursor::new);
        blurred.update(cx, |cursor, cx| cursor.start(cx));
        blurred.update(cx, |cursor, cx| cursor.pause(cx));
        blurred.update(cx, |cursor, cx| cursor.stop(cx));

        for policy in [CursorBlink::steady(), CursorBlink::default()] {
            cx.update(|cx| set_cursor_blink(policy, cx));
            assert_idle(&never_focused, false, cx);
            assert_idle(&blurred, false, cx);
        }

        blurred.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!blurred.read_with(cx, |cursor, _| cursor.visible()));
    }

    #[gpui::test]
    fn shortening_the_timeout_stops_a_hidden_cursor_immediately(cx: &mut TestAppContext) {
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        advance(cx, INTERVAL);
        assert!(!cursor.read_with(cx, |cursor, _| cursor.visible()));

        cx.update(|cx| {
            set_cursor_blink(
                CursorBlink::blinking(INTERVAL).with_idle_timeout(Duration::from_millis(400)),
                cx,
            )
        });
        assert_idle(&cursor, true, cx);
    }

    #[gpui::test]
    fn initialization_preserves_an_application_policy(cx: &mut TestAppContext) {
        cx.update(|cx| set_cursor_blink(CursorBlink::steady(), cx));
        cx.update(crate::init);
        let cursor = cx.new(BlinkCursor::new);
        cursor.update(cx, |cursor, cx| cursor.start(cx));
        assert_idle(&cursor, true, cx);
    }
}
