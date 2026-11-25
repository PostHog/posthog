use gpui::{App, Entity, KeyDownEvent, Window};

use super::QuestionnaireState;

/// Routes a key press to the questionnaire's behavior and reports whether it
/// was consumed. The skin installs it on the root; the contract — arrows move
/// between answers and items, Enter confirms a filled answer, a bare letter or
/// digit activates a shortcut — lives here so a different skin keeps it.
pub fn handle_key_down(
    state: &Entity<QuestionnaireState>,
    event: &KeyDownEvent,
    window: &mut Window,
    cx: &mut App,
) {
    if window.default_prevented()
        || event.is_held
        || event.prefer_character_input
        || event.keystroke.is_ime_in_progress()
    {
        return;
    }

    let modifiers = event.keystroke.modifiers;
    let key = event.keystroke.key.as_str();
    let input_focused = state.read(cx).is_current_input_focused(window);
    let input_has_text = input_focused && state.read(cx).current_input_has_text(cx);
    let single_radio_focused = {
        let state = state.read(cx);
        state
            .current_item()
            .and_then(|item| state.item_state(item))
            .is_some_and(|item| !item.is_multiple())
            && state.focused_current_choice(window).is_some()
    };

    let handled = if key == "enter"
        && modifiers.secondary(cx)
        && modifiers.number_of_modifiers() == 1
    {
        state.update(cx, |state, cx| state.confirm_current(window, cx))
    } else if modifiers.number_of_modifiers() != 0 {
        false
    } else if input_focused {
        match key {
            "enter" if focused_answer_is_filled(state, window, cx) => {
                state.update(cx, |state, cx| state.confirm_current(window, cx))
            }
            "up" if !input_has_text => {
                state.update(cx, |state, cx| state.focus_previous_answer(window, cx))
            }
            "down" if !input_has_text => {
                state.update(cx, |state, cx| state.focus_next_answer(window, cx))
            }
            _ => false,
        }
    } else {
        match key {
            "up" => {
                state.update(cx, |state, cx| state.focus_previous_answer(window, cx))
                    || (single_radio_focused
                        && state.update(cx, |state, cx| state.move_current_radio(-1, window, cx)))
            }
            "down" => {
                state.update(cx, |state, cx| state.focus_next_answer(window, cx))
                    || (single_radio_focused
                        && state.update(cx, |state, cx| state.move_current_radio(1, window, cx)))
            }
            "left" if single_radio_focused => {
                state.update(cx, |state, cx| state.move_current_radio(-1, window, cx))
            }
            "right" if single_radio_focused => {
                state.update(cx, |state, cx| state.move_current_radio(1, window, cx))
            }
            "left" => state.update(cx, |state, cx| state.go_previous(window, cx)),
            "right" if state.read(cx).navigation_state().is_confirmable() => {
                state.update(cx, |state, cx| state.go_next(window, cx))
            }
            "right" => false,
            "enter" if focused_answer_is_filled(state, window, cx) => {
                state.update(cx, |state, cx| state.confirm_current(window, cx))
            }
            "enter" => false,
            _ => state.update(cx, |state, cx| state.activate_shortcut(key, window, cx)),
        }
    };

    if handled {
        window.prevent_default();
    }
}

fn focused_answer_is_filled(state: &Entity<QuestionnaireState>, window: &Window, cx: &App) -> bool {
    let state = state.read(cx);
    let Some(item) = state.current_item() else {
        return false;
    };
    if state.is_current_input_focused(window) {
        return state
            .answer(item)
            .is_some_and(|answer| answer.freeform().is_some());
    }
    state
        .focused_current_choice(window)
        .and_then(|value| state.choice_state(item, value))
        .is_some_and(|choice| choice.is_selected())
}
