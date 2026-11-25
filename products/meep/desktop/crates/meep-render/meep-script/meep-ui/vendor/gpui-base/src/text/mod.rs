mod document;
pub mod editor_host;
mod editor_seam;
mod format;
mod inline;
mod inline_element;
mod inline_flow;
mod inline_object;
#[cfg(test)]
mod inline_virtual_tests;
mod markdown_ext;
mod node;
mod range_highlight;
pub(crate) mod selection;
mod selection_adapter;
mod state;
mod stream_fade;
mod style;
mod text_view;
mod utils;

use gpui::{App, ElementId, IntoElement, RenderOnce, SharedString, Window};
pub use inline_element::*;
pub use markdown_ext::*;
pub use node::{CodeBlock, TableData};
pub use range_highlight::{RangeHighlight, RangeHighlightError, RenderedText};
pub use state::*;
pub use stream_fade::TextViewMotion;
pub use style::*;
pub use text_view::*;

pub(crate) fn init(cx: &mut App) {
    inline::init(cx);
    state::init(cx);
}

/// Create a new markdown text view with code location as id.
#[track_caller]
pub fn markdown(source: impl Into<SharedString>) -> TextView {
    let id: ElementId = ElementId::CodeLocation(*std::panic::Location::caller());
    TextView::markdown(id, source)
}

/// Create a new html text view with code location as id.
#[track_caller]
pub fn html(source: impl Into<SharedString>) -> TextView {
    let id: ElementId = ElementId::CodeLocation(*std::panic::Location::caller());
    TextView::html(id, source)
}

#[derive(IntoElement, Clone)]
pub enum Text {
    String(SharedString),
    TextView(Box<TextView>),
}

impl From<SharedString> for Text {
    fn from(s: SharedString) -> Self {
        Self::String(s)
    }
}

impl From<&str> for Text {
    fn from(s: &str) -> Self {
        Self::String(SharedString::from(s.to_string()))
    }
}

impl From<String> for Text {
    fn from(s: String) -> Self {
        Self::String(s.into())
    }
}

impl From<TextView> for Text {
    fn from(e: TextView) -> Self {
        Self::TextView(Box::new(e))
    }
}

impl Text {
    /// Set the style for [`TextView`].
    ///
    /// Do nothing if this is `String`.
    pub fn style(self, style: TextViewStyle) -> Self {
        match self {
            Self::String(s) => Self::String(s),
            Self::TextView(e) => Self::TextView(Box::new(e.style(style))),
        }
    }

    /// Get the text content.
    #[doc(hidden)]
    pub fn get_text(&self, cx: &App) -> SharedString {
        match self {
            Self::String(s) => s.clone(),
            Self::TextView(view) => {
                if let Some(state) = &view.state {
                    state.read(cx).source()
                } else {
                    SharedString::default()
                }
            }
        }
    }
}

impl RenderOnce for Text {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        match self {
            Self::String(s) => s.into_any_element(),
            Self::TextView(e) => e.into_any_element(),
        }
    }
}
