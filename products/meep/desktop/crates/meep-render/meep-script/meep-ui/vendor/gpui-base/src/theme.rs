use gpui::{App, Global};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{
    PlotMotion, ScrollbarMode, ScrollbarMotion, ScrollbarStyles, SemanticThemeTokens,
    input::CursorBlink,
};

/// Application-wide defaults for Base behavior modules.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum ThemeAppearance {
    #[default]
    Light,
    Dark,
}

/// Construct with [`Theme::default`] and assign fields; new fields may be
/// added without a breaking change.
#[derive(Clone, Default)]
#[non_exhaustive]
pub struct Theme {
    pub appearance: ThemeAppearance,
    pub tokens: SemanticThemeTokens,
    pub scrollbar: ScrollbarTheme,
    pub resizable: ResizableTheme,
    pub plot: PlotTheme,
    /// Application-wide caret blink behavior.
    pub cursor_blink: CursorBlink,
}

impl Global for Theme {}

impl Theme {
    pub fn global(cx: &App) -> Self {
        cx.try_global::<Self>().cloned().unwrap_or_default()
    }

    pub fn global_mut(cx: &mut App) -> &mut Self {
        if !cx.has_global::<Self>() {
            cx.set_global(Self::default());
        }
        cx.global_mut::<Self>()
    }
}

/// Access to the active base theme through an application context.
pub(crate) trait ActiveTheme {
    fn theme(&self) -> Theme;
}

impl ActiveTheme for App {
    #[inline(always)]
    fn theme(&self) -> Theme {
        Theme::global(self)
    }
}

/// Global defaults used by [`crate::Scrollbar`].
///
/// `motion` defaults to motionless. Styled layers project their own timing;
/// Base never installs a fade or slide of its own.
#[derive(Clone, Default)]
pub struct ScrollbarTheme {
    mode: ScrollbarMode,
    motion: ScrollbarMotion,
    styles: ScrollbarStyles,
}

impl ScrollbarTheme {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_mode(mut self, mode: ScrollbarMode) -> Self {
        self.mode = mode;
        self
    }

    pub fn with_motion(mut self, motion: ScrollbarMotion) -> Self {
        self.motion = motion;
        self
    }

    pub fn with_styles(mut self, styles: ScrollbarStyles) -> Self {
        self.styles = styles;
        self
    }

    pub fn mode(&self) -> ScrollbarMode {
        self.mode
    }

    pub fn motion(&self) -> ScrollbarMotion {
        self.motion
    }

    pub fn styles(&self) -> &ScrollbarStyles {
        &self.styles
    }
}

/// Global defaults used by [`crate::plot`].
///
/// `motion` defaults to motionless. Styled layers project their own timing;
/// Base never installs a fade or glide of its own.
#[derive(Clone, Default)]
pub struct PlotTheme {
    motion: PlotMotion,
}

impl PlotTheme {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_motion(mut self, motion: PlotMotion) -> Self {
        self.motion = motion;
        self
    }

    pub fn motion(&self) -> &PlotMotion {
        &self.motion
    }
}

/// Global visual defaults used by resizable panel handles.
///
/// `None` means *unset*, not invisible: a handle with nothing projected onto it
/// resolves from the active [`SemanticThemeTokens`] -- `border` at rest, `ring`
/// while dragging -- which are the tokens those two states already mean
/// everywhere else.
///
/// These were plain colors, so the Base default was `Hsla::default()`: fully
/// transparent. That reads as a deliberate choice next to a styled façade,
/// which projects its own values and never sees it, and as a missing divider
/// to anything that does not -- and a consumer with no façade has no way to
/// project anything. Making them optional keeps the projection exactly as it
/// was while giving the unprojected case an answer.
#[derive(Clone, Copy, Default)]
#[non_exhaustive]
pub struct ResizableTheme {
    pub handle: Option<gpui::Hsla>,
    pub active_handle: Option<gpui::Hsla>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scrollbar_theme_supports_builder_construction() {
        let mode = ScrollbarMode::Hover;
        let motion = ScrollbarMotion::default().with_enter(std::time::Duration::from_millis(120));
        let styles = ScrollbarStyles::default();
        let theme = ScrollbarTheme::new()
            .with_mode(mode)
            .with_motion(motion)
            .with_styles(styles);

        assert_eq!(theme.mode(), mode);
        assert_eq!(theme.motion(), motion);
        let _ = theme.styles();
    }
}
