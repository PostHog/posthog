//! Individual native input steps for gestures spanning several UI updates.
use super::TestWindowExt;
use crate::{
    App, InputEvent, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, ModifiersChangedEvent,
    MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent, Pixels, Point, Window,
};

/// Dispatches individual native events, completing a frame after each step.
/// Pointer events retain the window's current modifiers. Keyboard events do not
/// insert IME text; use `TestWindowExt::input` for text entry. Parsed key
/// modifiers combine with the currently held modifiers without changing them.
pub trait TestEventExt {
    /// Moves the pointer, optionally with a mouse button held.
    fn pointer_move(
        &mut self,
        position: Point<Pixels>,
        pressed_button: Option<MouseButton>,
        cx: &mut App,
    );
    /// Presses a mouse button at a window-local position.
    fn pointer_down(&mut self, position: Point<Pixels>, button: MouseButton, cx: &mut App);
    /// Releases a mouse button at a window-local position.
    fn pointer_up(&mut self, position: Point<Pixels>, button: MouseButton, cx: &mut App);
    /// Changes keyboard modifiers while preserving caps lock.
    fn change_modifiers(&mut self, modifiers: Modifiers, cx: &mut App);
    /// Dispatches a parsed key-down; `is_held` marks an auto-repeat event.
    fn key_down(&mut self, key: &str, is_held: bool, cx: &mut App);
    /// Dispatches a parsed key-up, independently of the preceding key-down.
    fn key_up(&mut self, key: &str, cx: &mut App);
}

fn parse_key(key: &str, cx: &App) -> Keystroke {
    Keystroke::parse_with_os(key, cx.platform_info().os)
        .unwrap_or_else(|error| panic!("invalid test keystroke: {error}"))
}

impl TestEventExt for Window {
    fn pointer_move(
        &mut self,
        position: Point<Pixels>,
        pressed_button: Option<MouseButton>,
        cx: &mut App,
    ) {
        self.render_frame(cx);
        self.dispatch_event(
            MouseMoveEvent {
                position,
                pressed_button,
                modifiers: self.modifiers(),
            }
            .to_platform_input(),
            cx,
        );
        self.render_frame(cx);
    }
    fn pointer_down(&mut self, position: Point<Pixels>, button: MouseButton, cx: &mut App) {
        self.render_frame(cx);
        self.dispatch_event(
            MouseDownEvent {
                button,
                position,
                modifiers: self.modifiers(),
                click_count: 1,
                first_mouse: false,
            }
            .to_platform_input(),
            cx,
        );
        self.render_frame(cx);
    }
    fn pointer_up(&mut self, position: Point<Pixels>, button: MouseButton, cx: &mut App) {
        self.render_frame(cx);
        self.dispatch_event(
            MouseUpEvent {
                button,
                position,
                modifiers: self.modifiers(),
                click_count: 1,
            }
            .to_platform_input(),
            cx,
        );
        self.render_frame(cx);
    }
    fn change_modifiers(&mut self, modifiers: Modifiers, cx: &mut App) {
        self.render_frame(cx);
        self.dispatch_event(
            ModifiersChangedEvent {
                modifiers,
                capslock: self.capslock(),
            }
            .to_platform_input(),
            cx,
        );
        self.render_frame(cx);
    }
    fn key_down(&mut self, key: &str, is_held: bool, cx: &mut App) {
        let mut keystroke = parse_key(key, cx);
        self.render_frame(cx);
        keystroke.modifiers |= self.modifiers();
        self.dispatch_event(
            KeyDownEvent {
                keystroke,
                is_held,
                prefer_character_input: false,
            }
            .to_platform_input(),
            cx,
        );
        self.render_frame(cx);
    }
    fn key_up(&mut self, key: &str, cx: &mut App) {
        let mut keystroke = parse_key(key, cx);
        self.render_frame(cx);
        keystroke.modifiers |= self.modifiers();
        self.dispatch_event(KeyUpEvent { keystroke }.to_platform_input(), cx);
        self.render_frame(cx);
    }
}
