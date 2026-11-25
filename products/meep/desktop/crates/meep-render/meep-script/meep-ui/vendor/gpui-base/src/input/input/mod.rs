use gpui::{App, Entity, IntoElement, RenderOnce, Window};

use super::{InputBaseState, InputMode};

/// State for a single-line text input.
///
/// This is the shared editing engine in its single-line kind. Multi-line
/// layout, auto-grow, and code-editor configuration do not exist on this type —
/// those methods live on [`super::TextareaState`] and [`super::EditorState`].
pub type InputState = InputBaseState<InputMode>;

/// An unstyled single-line text input.
///
/// Applications that need a fully styled control can wrap this state with
/// their own presentation or use `gpui-component::Input`.
#[derive(IntoElement)]
pub struct Input {
    presentation: super::InlineTokenPresentation,
    state: Entity<InputState>,
}

impl Input {
    pub fn new(state: &Entity<InputState>) -> Self {
        Self {
            state: state.clone(),
            presentation: Default::default(),
        }
    }
    /// The element each atomic token renders as; the input keeps editing and history.
    pub fn token<R: IntoElement>(
        mut self,
        render: impl Fn(&super::InlineTokenContext, &mut Window, &mut App) -> R + 'static,
    ) -> Self {
        self.presentation = self.presentation.token(render);
        self
    }
    /// Open a reference after a completed, unconsumed token click.
    pub fn on_token_click(
        mut self,
        listener: impl Fn(&super::InlineTokenClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.presentation = self.presentation.on_token_click(listener);
        self
    }
    /// Report pointer presence over a token; hover never selects or edits.
    pub fn on_token_hover(
        mut self,
        listener: impl Fn(&super::InlineTokenHoverEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.presentation = self.presentation.on_token_hover(listener);
        self
    }
}

impl RenderOnce for Input {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        self.state.update(cx, |state, _| {
            state.set_token_presentation(self.presentation)
        });
        self.state
    }
}
