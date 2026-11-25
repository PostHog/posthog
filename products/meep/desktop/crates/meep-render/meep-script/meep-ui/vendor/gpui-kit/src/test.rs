//! UI integration testing for GPUI Kit components and application views.
//!
//! Render real components in a headless window, simulate clicks, keyboard input
//! and scrolling, then verify state, focus, layout and application callbacks.
//! For example, test that clicking a Checkbox changes the owner's value while
//! a disabled Checkbox rejects the same interaction.
//!
//! `#[gpui_kit::test]` runs the test and provides its GPUI context. This module
//! supplies UI interactions and snapshots; it does not inspect rendered pixels.
//!
//! [`ElementSnapshot`] is immutable. Call [`TestWindowExt::render_frame`] after
//! external changes, or use [`TestAppContextExt::wait_for`] for asynchronous UI.
use crate::{
    AnyWindowHandle, App, AppContext, ElementId, InputEvent, KeyDownEvent, KeyUpEvent, Keystroke,
    Modifiers, ModifiersChangedEvent, MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent,
    Pixels, Point, ScrollDelta, ScrollEvent, TestAppContext, Window, point, px,
};
use std::time::Duration;

mod events;
mod input;
mod query;

pub use events::TestEventExt;
pub use input::TestInput;
pub use query::TestQueryExt;

pub use gpui_base::TestSupportExt;
use gpui_base::test_support as observation;
pub use gpui_base::test_support::ElementSnapshot;

/// Testing operations on GPUI's existing window.
pub trait TestWindowExt {
    /// Requires a target from the last completed frame, with registered paths in errors.
    fn find(&self, id: impl Into<ElementId>) -> ElementSnapshot;
    /// Returns None for an absent target; ambiguous IDs still require a scope.
    fn try_find(&self, id: impl Into<ElementId>) -> Option<ElementSnapshot>;
    /// Returns all registered matches from the last completed frame, including invisible ones.
    /// Ordered by bounds origin (y, then x); equal-origin order is unspecified.
    fn find_all(&self, id: impl Into<ElementId>) -> Vec<ElementSnapshot>;
    /// Restricts queries to a GPUI identity scope; no additional layout wrapper is needed.
    fn within(&mut self, id: impl Into<ElementId>) -> ScopedWindow<'_>;
    /// Invalidates cached facts and completes a frame.
    fn render_frame(&mut self, cx: &mut App);
    fn click(&mut self, id: impl Into<ElementId>, cx: &mut App);
    /// Clicks at a local offset from the target's top-left corner.
    fn click_at(&mut self, id: impl Into<ElementId>, offset: Point<Pixels>, cx: &mut App);
    /// Dispatches modifiers-changed when necessary, then move/down/up, and restores
    /// the previous modifier state with another modifiers-changed event after the click.
    /// Each step renders a frame; caps lock is preserved.
    fn click_with_options(&mut self, id: impl Into<ElementId>, options: ClickOptions, cx: &mut App);
    /// A centered left click with modifiers; restores the previous modifier state.
    fn click_with_modifiers(
        &mut self,
        id: impl Into<ElementId>,
        modifiers: Modifiers,
        cx: &mut App,
    ) {
        self.click_with_options(id, ClickOptions::new().with_modifiers(modifiers), cx);
    }
    fn right_click(&mut self, id: impl Into<ElementId>, cx: &mut App);
    fn double_click(&mut self, id: impl Into<ElementId>, cx: &mut App);
    fn hover(&mut self, id: impl Into<ElementId>, cx: &mut App);
    /// Dispatches a wheel event, preserving GPUI's delta sign and units.
    fn scroll(&mut self, id: impl Into<ElementId>, delta: ScrollDelta, cx: &mut App);
    /// Drags between window-local positions through native pointer dispatch.
    fn drag(&mut self, from: Point<Pixels>, to: Point<Pixels>, cx: &mut App);
    /// Drags between two observed element centers, with native hit testing.
    fn drag_to(&mut self, from: impl Into<ElementId>, to: impl Into<ElementId>, cx: &mut App);
    /// Sends key-down and key-up for a parsed GPUI key, such as "backspace" or "cmd-a".
    /// Enter and Tab run key bindings without additionally inserting text.
    fn press(&mut self, key: &str, cx: &mut App);
    /// Sends text to the current focus; does not focus a target or replace its whole value.
    fn input(&mut self, text: &str, cx: &mut App);
}

/// Click configuration owned by the caller. Defaults to one left click at the center,
/// without modifiers. Offsets are relative to the target's top-left corner.
#[derive(Clone, Copy, Debug)]
pub struct ClickOptions {
    offset: Option<Point<Pixels>>,
    button: MouseButton,
    count: usize,
    modifiers: Modifiers,
}
impl Default for ClickOptions {
    fn default() -> Self {
        Self {
            offset: None,
            button: MouseButton::Left,
            count: 1,
            modifiers: Modifiers::default(),
        }
    }
}
impl ClickOptions {
    /// Creates one centered left click without modifiers.
    pub fn new() -> Self {
        Self::default()
    }
    /// Sets an offset from the target bounds origin; validated when clicking.
    pub fn with_offset(mut self, offset: Point<Pixels>) -> Self {
        self.offset = Some(offset);
        self
    }
    /// Returns the local offset, or `None` for the center.
    pub fn offset(&self) -> Option<Point<Pixels>> {
        self.offset
    }
    /// Sets the mouse button.
    pub fn with_button(mut self, button: MouseButton) -> Self {
        self.button = button;
        self
    }
    /// Returns the mouse button.
    pub fn button(&self) -> MouseButton {
        self.button
    }
    /// Sets the number of clicks. Panics if `count` is zero.
    pub fn with_count(mut self, count: usize) -> Self {
        assert!(count > 0, "click count must be positive");
        self.count = count;
        self
    }
    /// Returns the positive number of clicks.
    pub fn count(&self) -> usize {
        self.count
    }
    /// Sets the modifier state for the click sequence.
    pub fn with_modifiers(mut self, modifiers: Modifiers) -> Self {
        self.modifiers = modifiers;
        self
    }
    /// Returns the modifier state for the click sequence.
    pub fn modifiers(&self) -> Modifiers {
        self.modifiers
    }
}

fn require(window: &Window, scope: &[ElementId], id: &ElementId) -> ElementSnapshot {
    observation::find(window, scope, id).unwrap_or_else(|| {
        panic!("missing ElementId {id:?} in scope {scope:?}. Registered paths: {}. Check the ID, observation, and completed frame.", observation::registered_paths(window))
    })
}

fn target_position(
    window: &Window,
    scope: &[ElementId],
    id: &ElementId,
    offset: Option<Point<Pixels>>,
) -> Point<Pixels> {
    let target = require(window, scope, id);
    assert!(
        target.visible(),
        "ElementId {id:?} is not visible (path {:?})",
        target.path()
    );
    if let Some(offset) = offset {
        let size = target.bounds().size;
        assert!(
            offset.x >= px(0.)
                && offset.y >= px(0.)
                && offset.x < size.width
                && offset.y < size.height,
            "click offset {offset:?} is outside ElementId {id:?} bounds {:?}",
            target.bounds()
        );
        target.bounds().origin + offset
    } else {
        target.bounds().center()
    }
}

fn move_pointer(
    window: &mut Window,
    position: Point<Pixels>,
    pressed_button: Option<MouseButton>,
    modifiers: Modifiers,
    cx: &mut App,
) {
    window.dispatch_event(
        MouseMoveEvent {
            position,
            pressed_button,
            modifiers,
        }
        .to_platform_input(),
        cx,
    );
    window.render_frame(cx);
}

fn mouse_down(
    window: &mut Window,
    position: Point<Pixels>,
    button: MouseButton,
    click_count: usize,
    modifiers: Modifiers,
    cx: &mut App,
) {
    window.dispatch_event(
        MouseDownEvent {
            button,
            position,
            modifiers,
            click_count,
            first_mouse: false,
        }
        .to_platform_input(),
        cx,
    );
    window.render_frame(cx);
}

fn mouse_up(
    window: &mut Window,
    position: Point<Pixels>,
    button: MouseButton,
    click_count: usize,
    modifiers: Modifiers,
    cx: &mut App,
) {
    window.dispatch_event(
        MouseUpEvent {
            button,
            position,
            modifiers,
            click_count,
        }
        .to_platform_input(),
        cx,
    );
    window.render_frame(cx);
}

fn click_target(
    window: &mut Window,
    scope: &[ElementId],
    id: ElementId,
    options: ClickOptions,
    cx: &mut App,
) {
    let ClickOptions {
        offset,
        button,
        count,
        modifiers: _,
    } = options;
    window.render_frame(cx);
    let modifiers = window.modifiers();
    let position = target_position(window, scope, &id, offset);
    move_pointer(window, position, None, modifiers, cx);
    for click_count in 1..=count {
        mouse_down(window, position, button, click_count, modifiers, cx);
        mouse_up(window, position, button, click_count, modifiers, cx);
    }
}

fn change_modifiers(window: &mut Window, modifiers: Modifiers, cx: &mut App) {
    if window.modifiers() != modifiers {
        window.dispatch_event(
            ModifiersChangedEvent {
                modifiers,
                capslock: window.capslock(),
            }
            .to_platform_input(),
            cx,
        );
        window.render_frame(cx);
    }
}

fn click_with_options_target(
    window: &mut Window,
    scope: &[ElementId],
    id: ElementId,
    options: ClickOptions,
    cx: &mut App,
) {
    // Validate before changing modifier state, so a missing target leaves it intact.
    window.render_frame(cx);
    target_position(window, scope, &id, options.offset);
    let previous = window.modifiers();
    change_modifiers(window, options.modifiers, cx);
    click_target(window, scope, id, options, cx);
    change_modifiers(window, previous, cx);
}

fn hover_target(window: &mut Window, scope: &[ElementId], id: ElementId, cx: &mut App) {
    window.render_frame(cx);
    let position = target_position(window, scope, &id, None);
    move_pointer(window, position, None, window.modifiers(), cx);
}

fn scroll_target(
    window: &mut Window,
    scope: &[ElementId],
    id: ElementId,
    delta: ScrollDelta,
    cx: &mut App,
) {
    window.render_frame(cx);
    let position = target_position(window, scope, &id, None);
    move_pointer(window, position, None, window.modifiers(), cx);
    window.dispatch_event(
        ScrollEvent {
            position,
            delta,
            modifiers: window.modifiers(),
            ..Default::default()
        }
        .to_platform_input(),
        cx,
    );
    window.render_frame(cx);
}

fn drag_targets(
    window: &mut Window,
    scope: &[ElementId],
    from: ElementId,
    to: ElementId,
    cx: &mut App,
) {
    window.render_frame(cx);
    let from = target_position(window, scope, &from, None);
    let to = target_position(window, scope, &to, None);
    window.drag(from, to, cx);
}

impl TestWindowExt for Window {
    fn find(&self, id: impl Into<ElementId>) -> ElementSnapshot {
        require(self, &[], &id.into())
    }
    fn try_find(&self, id: impl Into<ElementId>) -> Option<ElementSnapshot> {
        observation::find(self, &[], &id.into())
    }
    fn find_all(&self, id: impl Into<ElementId>) -> Vec<ElementSnapshot> {
        observation::find_all(self, &[], &id.into())
    }
    fn within(&mut self, id: impl Into<ElementId>) -> ScopedWindow<'_> {
        let scope = observation::scope(self, &[], &id.into());
        ScopedWindow {
            window: self,
            scope,
        }
    }
    fn render_frame(&mut self, cx: &mut App) {
        self.refresh();
        self.draw(cx).clear(cx);
    }
    fn click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(self, &[], id.into(), ClickOptions::new(), cx);
    }
    fn click_at(&mut self, id: impl Into<ElementId>, offset: Point<Pixels>, cx: &mut App) {
        click_target(
            self,
            &[],
            id.into(),
            ClickOptions::new().with_offset(offset),
            cx,
        );
    }
    fn click_with_options(
        &mut self,
        id: impl Into<ElementId>,
        options: ClickOptions,
        cx: &mut App,
    ) {
        click_with_options_target(self, &[], id.into(), options, cx);
    }
    fn right_click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(
            self,
            &[],
            id.into(),
            ClickOptions::new().with_button(MouseButton::Right),
            cx,
        );
    }
    fn double_click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(self, &[], id.into(), ClickOptions::new().with_count(2), cx);
    }
    fn hover(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        hover_target(self, &[], id.into(), cx);
    }
    fn scroll(&mut self, id: impl Into<ElementId>, delta: ScrollDelta, cx: &mut App) {
        scroll_target(self, &[], id.into(), delta, cx);
    }
    fn drag_to(&mut self, from: impl Into<ElementId>, to: impl Into<ElementId>, cx: &mut App) {
        drag_targets(self, &[], from.into(), to.into(), cx);
    }
    fn drag(&mut self, from: Point<Pixels>, to: Point<Pixels>, cx: &mut App) {
        self.render_frame(cx);
        let modifiers = self.modifiers();
        move_pointer(self, from, None, modifiers, cx);
        mouse_down(self, from, MouseButton::Left, 1, modifiers, cx);
        for step in 1..=8 {
            let fraction = step as f32 / 8.;
            move_pointer(
                self,
                point(
                    from.x + (to.x - from.x) * fraction,
                    from.y + (to.y - from.y) * fraction,
                ),
                Some(MouseButton::Left),
                modifiers,
                cx,
            );
        }
        mouse_up(self, to, MouseButton::Left, 1, modifiers, cx);
    }
    fn press(&mut self, key: &str, cx: &mut App) {
        let key = Keystroke::parse_with_os(key, cx.platform_info().os)
            .unwrap_or_else(|error| panic!("invalid test keystroke: {error}"));
        self.render_frame(cx);
        press_key(self, key, cx);
        self.render_frame(cx);
    }
    fn input(&mut self, text: &str, cx: &mut App) {
        input_text(self, text, None, cx);
    }
}

/// A borrowed GPUI identity scope, not a new element or layout container.
pub struct ScopedWindow<'a> {
    window: &'a mut Window,
    scope: Vec<ElementId>,
}
impl ScopedWindow<'_> {
    pub fn find(&self, id: impl Into<ElementId>) -> ElementSnapshot {
        require(self.window, &self.scope, &id.into())
    }
    pub fn try_find(&self, id: impl Into<ElementId>) -> Option<ElementSnapshot> {
        observation::find(self.window, &self.scope, &id.into())
    }
    /// All registered descendants, including invisible ones, by current-frame bounds.
    /// Equal-origin order is unspecified.
    pub fn find_all(&self, id: impl Into<ElementId>) -> Vec<ElementSnapshot> {
        observation::find_all(self.window, &self.scope, &id.into())
    }
    pub fn within(&mut self, id: impl Into<ElementId>) -> ScopedWindow<'_> {
        let scope = observation::scope(self.window, &self.scope, &id.into());
        ScopedWindow {
            window: self.window,
            scope,
        }
    }
    pub fn click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(self.window, &self.scope, id.into(), ClickOptions::new(), cx);
    }
    pub fn click_at(&mut self, id: impl Into<ElementId>, offset: Point<Pixels>, cx: &mut App) {
        click_target(
            self.window,
            &self.scope,
            id.into(),
            ClickOptions::new().with_offset(offset),
            cx,
        );
    }
    /// Configurable click inside this scope; restores the previous modifier state.
    pub fn click_with_options(
        &mut self,
        id: impl Into<ElementId>,
        options: ClickOptions,
        cx: &mut App,
    ) {
        click_with_options_target(self.window, &self.scope, id.into(), options, cx);
    }
    /// Centered left click with modifiers; restores the previous modifier state.
    pub fn click_with_modifiers(
        &mut self,
        id: impl Into<ElementId>,
        modifiers: Modifiers,
        cx: &mut App,
    ) {
        self.click_with_options(id, ClickOptions::new().with_modifiers(modifiers), cx);
    }
    pub fn right_click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(
            self.window,
            &self.scope,
            id.into(),
            ClickOptions::new().with_button(MouseButton::Right),
            cx,
        );
    }
    pub fn double_click(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        click_target(
            self.window,
            &self.scope,
            id.into(),
            ClickOptions::new().with_count(2),
            cx,
        );
    }
    pub fn hover(&mut self, id: impl Into<ElementId>, cx: &mut App) {
        hover_target(self.window, &self.scope, id.into(), cx);
    }
    pub fn scroll(&mut self, id: impl Into<ElementId>, delta: ScrollDelta, cx: &mut App) {
        scroll_target(self.window, &self.scope, id.into(), delta, cx);
    }
    /// Both IDs resolve within this scope. Use Window::drag for cross-scope coordinates.
    pub fn drag_to(&mut self, from: impl Into<ElementId>, to: impl Into<ElementId>, cx: &mut App) {
        drag_targets(self.window, &self.scope, from.into(), to.into(), cx);
    }
    /// Dispatches to current focus, requiring an observed focus binding inside this scope.
    /// Does not move focus; click a scoped input first.
    pub fn press(&mut self, key: &str, cx: &mut App) {
        let key = Keystroke::parse_with_os(key, cx.platform_info().os)
            .unwrap_or_else(|error| panic!("invalid test keystroke: {error}"));
        self.window.render_frame(cx);
        require_scope_focus(self.window, &self.scope);
        press_key(self.window, key, cx);
        self.window.render_frame(cx);
    }
    /// Checks scope membership before every character, including after focus-changing handlers.
    pub fn input(&mut self, text: &str, cx: &mut App) {
        input_text(self.window, text, Some(&self.scope), cx);
    }
}

fn require_scope_focus(window: &Window, scope: &[ElementId]) {
    assert!(
        observation::has_observed_focus(window, scope),
        "no observed keyboard focus inside scope {:?}; register the focused control with .test_support().track_focus(&handle) inside this scope before press/input",
        scope
    );
}

fn press_key(window: &mut Window, key: Keystroke, cx: &mut App) {
    // GPUI's simulated IME supplies text for Enter and Tab. Native control
    // keys should only dispatch their bindings: an intentionally propagated
    // submit/completion action must not insert an extra newline afterward.
    let key = if matches!(key.key.as_str(), "enter" | "tab") {
        window.dispatch_event(
            KeyDownEvent {
                keystroke: key.clone(),
                is_held: false,
                prefer_character_input: false,
            }
            .to_platform_input(),
            cx,
        );
        key
    } else {
        let key = key.with_simulated_ime();
        window.dispatch_keystroke(key.clone(), cx);
        key
    };
    // Buttons activate on key-up, so every press must complete the pair even
    // if its key-down handler consumed the event or changed focus.
    window.dispatch_event(KeyUpEvent { keystroke: key }.to_platform_input(), cx);
}

fn input_text(window: &mut Window, text: &str, scope: Option<&[ElementId]>, cx: &mut App) {
    window.render_frame(cx);
    for character in text.chars() {
        if let Some(scope) = scope {
            require_scope_focus(window, scope);
        }
        let text = character.to_string();
        let mut key = Keystroke::parse_with_os(&text, cx.platform_info().os)
            .expect("a Unicode character is a valid GPUI keystroke");
        key.key_char = Some(text);
        window.dispatch_keystroke(key, cx);
        window.render_frame(cx);
    }
}

/// Executor-aware operations which must run outside a borrowed window update.
pub trait TestAppContextExt {
    /// Refreshes frames until the predicate succeeds or the test-clock timeout expires.
    /// Panics with registered paths on timeout. Polls every 10 ms of GPUI test time.
    fn wait_for(
        &mut self,
        window: AnyWindowHandle,
        timeout: Duration,
        predicate: impl FnMut(&mut Window, &mut App) -> bool,
    ) -> impl Future<Output = ()>;
}
impl TestAppContextExt for TestAppContext {
    async fn wait_for(
        &mut self,
        handle: AnyWindowHandle,
        timeout: Duration,
        mut predicate: impl FnMut(&mut Window, &mut App) -> bool,
    ) {
        let mut elapsed = Duration::ZERO;
        loop {
            let (ready, paths) = self
                .update_window(handle, |_, window, cx| {
                    window.render_frame(cx);
                    {
                        let ready = predicate(window, cx);
                        let paths = if !ready && elapsed >= timeout {
                            observation::registered_paths(window)
                        } else {
                            String::new()
                        };
                        (ready, paths)
                    }
                })
                .expect("test window closed while waiting");
            if ready {
                return;
            }
            assert!(
                elapsed < timeout,
                "UI condition timed out after {timeout:?}. Registered paths: {paths}"
            );
            let interval = Duration::from_millis(10).min(timeout - elapsed);
            self.executor().timer(interval).await;
            elapsed += interval;
        }
    }
}
