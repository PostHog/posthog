use std::sync::Arc;

use gpui::{
    App, ElementId, Entity, IntoElement, ParentElement as _, RenderOnce, StyleRefinement, Styled,
    Window, div, prelude::FluentBuilder as _, px,
};
use rust_i18n::t;

use crate::{
    Disableable, IconName, Selectable as _, Sizable, Size, StyledExt as _,
    button::{Button, ButtonVariants as _},
};

use super::{SpeechIndicator, SpeechState, SpeechStatus};

/// The button that starts and stops a [`SpeechState`]'s session.
///
/// Shows a microphone at rest and, pressed, a [`SpeechIndicator`] while
/// capturing: bars that move with the voice, turning into a stop glyph under
/// the pointer or while the button has keyboard focus. A click toggles the
/// session. While the final result is pending it shows a spinner and ignores
/// clicks.
///
/// Renders nothing when the state has no recognizer on this platform, unless
/// [`Self::show_when_unsupported`] is set, and renders disabled while the
/// recognizer reports itself unavailable.
#[derive(IntoElement)]
pub struct SpeechButton {
    id: ElementId,
    state: Entity<SpeechState>,
    size: Size,
    disabled: bool,
    show_when_unsupported: bool,
    style: StyleRefinement,
}

impl SpeechButton {
    /// A button for `state`.
    pub fn new(state: &Entity<SpeechState>) -> Self {
        Self {
            id: ("speech-button", state.entity_id()).into(),
            state: state.clone(),
            size: Size::default(),
            disabled: false,
            show_when_unsupported: false,
            style: StyleRefinement::default(),
        }
    }

    /// Render a disabled button, instead of nothing, when the state has no
    /// recognizer on this platform. Default `false`.
    pub fn show_when_unsupported(mut self, show: bool) -> Self {
        self.show_when_unsupported = show;
        self
    }
}

impl Sizable for SpeechButton {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for SpeechButton {
    /// Refines the button, e.g. its size or corner radius, to match the
    /// controls around it.
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Disableable for SpeechButton {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl RenderOnce for SpeechButton {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        // Kept here rather than in the Button so that keyboard focus can show
        // the stop glyph, which the indicator otherwise reveals only under
        // the pointer.
        let focus_handle = window
            .use_keyed_state(
                ElementId::NamedChild(Arc::new(self.id.clone()), "focus".into()),
                cx,
                |_, cx| cx.focus_handle(),
            )
            .read(cx)
            .clone();
        let keyboard_focused = focus_handle.is_focused(window) && window.last_input_was_keyboard();

        let state = self.state.read(cx);
        let status = state.status();
        let supported = state.has_recognizer();
        if !supported && !self.show_when_unsupported {
            return div().into_any_element();
        }
        // A running session stays stoppable even if the recognizer turns
        // unavailable mid-way.
        let available = status.is_active() || state.is_available(cx);
        let capturing = status.is_capturing();
        let label = if !available {
            t!("Speech.Unavailable")
        } else if capturing {
            t!("Speech.Stop")
        } else {
            t!("Speech.Start")
        };

        let stopping = status == SpeechStatus::Stopping;

        Button::new(self.id)
            .ghost()
            .with_size(self.size)
            .track_focus(&focus_handle)
            .map(|this| {
                if capturing && !keyboard_focused {
                    // With a child instead of an icon the button sizes to its
                    // content, so give it the icon button's square and let the
                    // indicator fill it.
                    let (side, icon) = match self.size {
                        Size::Size(side) => (side, Size::Size(side * 0.75)),
                        Size::XSmall => (px(20.), Size::XSmall),
                        Size::Small => (px(24.), Size::Small),
                        size => (px(32.), size),
                    };
                    this.size(side)
                        .p_0()
                        .child(SpeechIndicator::new(&self.state).with_size(icon))
                } else {
                    this.icon(if capturing || stopping {
                        IconName::Square
                    } else {
                        IconName::Mic
                    })
                }
            })
            .selected(capturing)
            .loading(stopping)
            .disabled(self.disabled || !available)
            .tooltip(label.clone())
            .accessibility_label(label)
            .refine_style(&self.style)
            .on_click({
                let state = self.state.clone();
                move |_, _, cx| state.update(cx, |state, cx| state.toggle(cx))
            })
            .into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use gpui::{AppContext as _, TestAppContext};

    use super::*;

    #[gpui::test]
    fn test_speech_button_builder(cx: &mut TestAppContext) {
        let state = cx.update(|cx| cx.new(|cx| SpeechState::new(cx).system_fallback(false)));
        let button = SpeechButton::new(&state)
            .small()
            .disabled(true)
            .show_when_unsupported(true);

        assert_eq!(button.size, Size::Small);
        assert!(button.disabled);
        assert!(button.show_when_unsupported);
        assert_eq!(
            button.id,
            ElementId::from(("speech-button", state.entity_id()))
        );
    }
}
