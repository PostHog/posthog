//! Semantic design tokens shared by application-owned components.
//!
//! These tokens describe visual roles and scales. They intentionally do not
//! contain component names such as `button`, `table`, or `sidebar`.

use gpui::{BoxShadow, FontWeight, Hsla, Pixels, SharedString, hsla, point, px, rgb};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct SemanticThemeTokens {
    pub colors: ColorTokens,
    pub radius: RadiusTokens,
    pub spacing: SpacingTokens,
    pub typography: TypographyTokens,
    pub shadow: ShadowTokens,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct ColorTokens {
    pub background: Hsla,
    pub foreground: Hsla,
    pub surface: Hsla,
    pub surface_foreground: Hsla,
    pub primary: Hsla,
    pub primary_foreground: Hsla,
    pub secondary: Hsla,
    pub secondary_foreground: Hsla,
    pub muted: Hsla,
    pub muted_foreground: Hsla,
    pub accent: Hsla,
    pub accent_foreground: Hsla,
    pub destructive: Hsla,
    pub destructive_foreground: Hsla,
    pub border: Hsla,
    pub input: Hsla,
    pub ring: Hsla,
    /// Background painted behind selected text.
    ///
    /// Selection quads are painted under the glyphs, so this is a translucent
    /// wash that leaves the text legible. It carries a serde default so
    /// palettes written before the token existed still load.
    #[serde(default = "ColorTokens::default_selection")]
    pub selection: Hsla,
}

impl Default for ColorTokens {
    fn default() -> Self {
        Self::light()
    }
}

impl ColorTokens {
    /// Default light palette, aligned with gpui-component's Default Light theme.
    pub fn light() -> Self {
        Self {
            background: hsla(0., 0., 1., 1.),
            foreground: hsla(0., 0., 0.039, 1.),
            surface: hsla(0., 0., 1., 1.),
            surface_foreground: hsla(0., 0., 0.039, 1.),
            primary: hsla(0., 0., 0.09, 1.),
            primary_foreground: hsla(0., 0., 0.98, 1.),
            secondary: hsla(0., 0., 0.898, 1.),
            secondary_foreground: hsla(0., 0., 0.09, 1.),
            muted: hsla(0., 0., 0.961, 1.),
            muted_foreground: hsla(0., 0., 0.451, 1.),
            accent: hsla(0., 0., 0.961, 1.),
            accent_foreground: hsla(0., 0., 0.09, 1.),
            destructive: hsla(0., 0.842, 0.602, 1.),
            destructive_foreground: hsla(0., 0., 0.98, 1.),
            border: hsla(0., 0., 0.898, 1.),
            input: hsla(0., 0., 0.898, 1.),
            ring: hsla(0., 0., 0.639, 1.),
            selection: Hsla::from(rgb(0x55a0fc)).alpha(0.3),
        }
    }

    /// Default dark palette, aligned with gpui-component's Default Dark theme.
    pub fn dark() -> Self {
        Self {
            background: hsla(0., 0., 0.039, 1.),
            foreground: hsla(0., 0., 0.98, 1.),
            surface: hsla(0., 0., 0.039, 1.),
            surface_foreground: hsla(0., 0., 0.98, 1.),
            primary: hsla(0., 0., 0.98, 1.),
            primary_foreground: hsla(0., 0., 0.09, 1.),
            secondary: hsla(0., 0., 0.149, 1.),
            secondary_foreground: hsla(0., 0., 0.98, 1.),
            muted: hsla(0., 0., 0.149, 1.),
            muted_foreground: hsla(0., 0., 0.639, 1.),
            accent: hsla(0., 0., 0.149, 1.),
            accent_foreground: hsla(0., 0., 0.98, 1.),
            destructive: hsla(0., 0.906, 0.708, 1.),
            destructive_foreground: hsla(0., 0.722, 0.506, 1.),
            border: hsla(0., 0., 0.149, 1.),
            input: hsla(0., 0., 47. / 255., 1.),
            ring: hsla(0., 0., 0.451, 1.),
            selection: Hsla::from(rgb(0x1d4ed8)).alpha(0.3),
        }
    }

    /// The selection color a palette falls back to when it predates the token.
    fn default_selection() -> Hsla {
        Self::light().selection
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct RadiusTokens {
    pub none: Pixels,
    pub sm: Pixels,
    pub md: Pixels,
    pub lg: Pixels,
    pub xl: Pixels,
    pub full: Pixels,
}

impl Default for RadiusTokens {
    fn default() -> Self {
        Self {
            none: px(0.),
            sm: px(3.),
            md: px(6.),
            lg: px(8.),
            xl: px(12.),
            full: px(9999.),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct SpacingTokens {
    pub xxs: Pixels,
    pub xs: Pixels,
    pub sm: Pixels,
    pub md: Pixels,
    pub lg: Pixels,
    pub xl: Pixels,
    pub xxl: Pixels,
}

impl Default for SpacingTokens {
    fn default() -> Self {
        Self {
            xxs: px(2.),
            xs: px(4.),
            sm: px(8.),
            md: px(12.),
            lg: px(16.),
            xl: px(24.),
            xxl: px(32.),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct TextStyleToken {
    pub size: Pixels,
    pub line_height: Pixels,
    pub weight: FontWeight,
}

impl Default for TextStyleToken {
    /// The body text style, matching [`TypographyTokens::md`].
    fn default() -> Self {
        text_style(16., 24.)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct TypographyTokens {
    pub sans: SharedString,
    pub mono: SharedString,
    pub xs: TextStyleToken,
    pub sm: TextStyleToken,
    pub md: TextStyleToken,
    pub lg: TextStyleToken,
    pub xl: TextStyleToken,
    pub mono_md: TextStyleToken,
}

impl Default for TypographyTokens {
    fn default() -> Self {
        Self {
            sans: ".SystemUIFont".into(),
            mono: default_mono_font_family(),
            xs: text_style(12., 16.),
            sm: text_style(14., 20.),
            md: text_style(16., 24.),
            lg: text_style(18., 28.),
            xl: text_style(20., 28.),
            mono_md: text_style(13., 20.),
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct ShadowTokens {
    pub sm: Vec<BoxShadow>,
    pub md: Vec<BoxShadow>,
    pub lg: Vec<BoxShadow>,
}

impl ShadowTokens {
    pub fn elevations(color: Hsla) -> Self {
        Self {
            sm: vec![box_shadow(0., 1., 2., 0., color)],
            md: vec![box_shadow(0., 4., 8., -2., color)],
            lg: vec![box_shadow(0., 12., 24., -4., color)],
        }
    }
}

fn text_style(size: f32, line_height: f32) -> TextStyleToken {
    TextStyleToken {
        size: px(size),
        line_height: px(line_height),
        weight: FontWeight::NORMAL,
    }
}

fn default_mono_font_family() -> SharedString {
    if cfg!(target_os = "macos") {
        "Menlo".into()
    } else if cfg!(target_os = "windows") {
        "Consolas".into()
    } else {
        "DejaVu Sans Mono".into()
    }
}

fn box_shadow(x: f32, y: f32, blur: f32, spread: f32, color: Hsla) -> BoxShadow {
    BoxShadow {
        color,
        offset: point(px(x), px(y)),
        blur_radius: px(blur),
        spread_radius: px(spread),
        inset: false,
    }
}

#[cfg(test)]
mod tests {
    use super::ColorTokens;

    #[test]
    fn default_colors_are_the_light_palette_and_both_palettes_are_readable() {
        let light = ColorTokens::light();
        let dark = ColorTokens::dark();

        assert_eq!(ColorTokens::default(), light);
        assert_eq!(light.background.l, 1.);
        assert!(light.foreground.l < light.background.l);
        assert!(dark.background.l < dark.foreground.l);
        assert_eq!(light.primary.a, 1.);
        assert_eq!(dark.primary.a, 1.);
    }
}
