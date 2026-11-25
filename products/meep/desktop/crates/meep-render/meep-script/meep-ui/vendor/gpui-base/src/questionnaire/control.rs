use gpui::{
    ElementId, Entity, InteractiveElement as _, SharedString, StatefulInteractiveElement as _,
    prelude::FluentBuilder as _,
};

use super::QuestionnaireState;
use crate::{Checkbox, CheckboxState, Radio};

/// The answer control for one choice, wired to the questionnaire's behavior.
///
/// A multiple-answer item hands back a `Checkbox` and a single-answer item a
/// `Radio`, each already carrying its checked state, disabled state,
/// accessibility name, position in set, focus handle, confirm key and change
/// handler. Activation goes through [`QuestionnaireState::choose`], so a
/// `Radio` confirms its item once chosen. The skin decides what the control
/// looks like and what it contains.
// The value is handed straight to the caller's `match` and dropped into an
// element; boxing either variant would buy an allocation on every choice to
// even out a difference that never outlives one render.
#[allow(clippy::large_enum_variant)]
pub enum QuestionnaireChoiceControl {
    Checkbox(Checkbox),
    Radio(Radio),
}

impl QuestionnaireChoiceControl {
    /// Returns `None` when the item or the choice is not part of the schema.
    pub fn new(
        state: &Entity<QuestionnaireState>,
        item: impl Into<SharedString>,
        value: impl Into<SharedString>,
        id: impl Into<ElementId>,
        cx: &gpui::App,
    ) -> Option<Self> {
        let item = item.into();
        let value = value.into();
        let snapshot = state.read(cx);
        let choice = snapshot.choice_state(&item, &value)?;
        let multiple = snapshot.item_state(&item)?.is_multiple();
        let definition = snapshot.choice_definition(&item, &value)?;
        let label = definition.accessibility_label().clone();
        let description = definition.description().cloned();
        let position = snapshot.choice_position(&item, &value);
        let focus_handle = snapshot.choice_focus_handle(&item, &value).cloned();
        let selected = choice.is_selected();
        let disabled = choice.is_disabled();

        // Enter confirms an answer that is already selected; an unselected
        // control keeps Enter for activation.
        let confirm_state = state.clone();
        let confirm =
            move |event: &gpui::KeyDownEvent, window: &mut gpui::Window, cx: &mut gpui::App| {
                if selected
                    && !window.default_prevented()
                    && !event.is_held
                    && event.keystroke.key == "enter"
                    && event.keystroke.modifiers.number_of_modifiers() == 0
                    && confirm_state.update(cx, |state, cx| state.confirm_current(window, cx))
                {
                    window.prevent_default();
                }
            };

        let id = id.into();
        Some(if multiple {
            let change_state = state.clone();
            let change_item = item.clone();
            let change_value = value.clone();
            Self::Checkbox(
                Checkbox::new(id)
                    .state(if selected {
                        CheckboxState::Checked
                    } else {
                        CheckboxState::Unchecked
                    })
                    .disabled(disabled)
                    .accessibility_label(label)
                    .when_some(description, |this, description| {
                        this.aria_description(description)
                    })
                    .when_some(position, |this, (position, total)| {
                        this.aria_position_in_set(position).aria_size_of_set(total)
                    })
                    .when_some(focus_handle, |this, focus_handle| {
                        this.track_focus(&focus_handle)
                    })
                    .capture_key_down(confirm)
                    .on_change(move |_, _, window, cx| {
                        let _ = change_state.update(cx, |state, cx| {
                            state.choose(&change_item, &change_value, window, cx)
                        });
                    }),
            )
        } else {
            let change_state = state.clone();
            Self::Radio(
                Radio::new(id)
                    .checked(selected)
                    .disabled(disabled)
                    .accessibility_label(label)
                    .when_some(description, |this, description| {
                        this.aria_description(description)
                    })
                    .when_some(position, |this, (position, total)| {
                        this.set_position(position, total)
                    })
                    .when_some(focus_handle, |this, focus_handle| {
                        this.track_focus(&focus_handle)
                    })
                    .capture_key_down(confirm)
                    // `on_change` would leave a checked radio inert, but
                    // choosing the selected answer again still confirms it.
                    .when(!disabled, |this| {
                        this.on_click(move |_, window, cx| {
                            let _ = change_state
                                .update(cx, |state, cx| state.choose(&item, &value, window, cx));
                        })
                    }),
            )
        })
    }
}
