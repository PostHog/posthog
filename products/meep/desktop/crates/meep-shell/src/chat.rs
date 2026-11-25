//! Transcript and composer for a topic or standalone conversation.
use super::*;
use gpui_kit::component::{
    Disableable,
    input::{Enter, InputEvent, TextareaState},
};

pub use crate::transcript::{ActivityIndicator, TranscriptHost, TranscriptRow};

/// A conversation with an editable draft. Use [`TranscriptHost::chat_transcript`]
/// to render its history and [`ChatHost::chat_composer`] to render the editor.
pub trait ChatHost: TranscriptHost {
    /// Editor state retained by the host between renders.
    fn chat_input(&self) -> &Entity<TextareaState>;

    /// Submit the current draft. The host clears it when the submission succeeds.
    fn send_chat(&mut self, window: &mut Window, cx: &mut Context<Self>);

    /// Render the editor. Enter or the send button submits a nonblank draft,
    /// and Shift+Enter inserts a line break.
    fn chat_composer(&self, window: &mut Window, cx: &mut Context<Self>) -> Div {
        let input = self.chat_input();
        window.use_keyed_state(("chat-input-events", input.entity_id()), cx, |_, cx| {
            input.update(cx, |editor, cx| editor.set_submit_on_enter(true, cx));
            cx.subscribe(input, |_: &mut Subscription, _, event, cx| {
                if matches!(
                    event,
                    InputEvent::Change | InputEvent::Focus | InputEvent::Blur
                ) {
                    cx.notify();
                }
            })
        });
        let state = input.read(cx);
        composer::surface(state.focus_handle(cx).contains_focused(window, cx))
            .on_action(cx.listener(|this, action: &Enter, window, cx| {
                if !action.shift && !this.chat_input().read(cx).value().trim().is_empty() {
                    this.send_chat(window, cx);
                }
            }))
            .child(composer::input(input, "Ask, or tell it what to do"))
            .child(
                row().justify_end().child(
                    composer::submit("send-chat-message", "Send message")
                        .disabled(state.value().trim().is_empty())
                        .on_click(cx.listener(|this, _, window, cx| this.send_chat(window, cx))),
                ),
            )
    }
}
