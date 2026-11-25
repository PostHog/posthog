use std::{rc::Rc, sync::Arc};

use gpui::{Background, BoxShadow, FontWeight, Hsla, SharedString, px};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::highlighter::{HighlightTheme, HighlightThemeStyle};

use super::color::{
    try_parse_background, try_parse_background_clamped, try_parse_color, try_parse_theme_color,
};
use super::{Colorize, SemanticThemeTokens, Theme, ThemeColor, ThemeMode, ThemeToken, ThemeTokens};

fn try_parse_theme_token(value: &str) -> anyhow::Result<ThemeToken> {
    Ok(ThemeToken::new(
        try_parse_theme_color(value)?,
        try_parse_background(value)?,
    ))
}

/// Represents a theme configuration.
#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct ThemeSet {
    /// The name of the theme set.
    pub name: SharedString,
    /// The author of the theme.
    pub author: Option<SharedString>,
    /// The URL of the theme.
    pub url: Option<SharedString>,
    /// The theme list of the theme set.
    #[serde(rename = "themes")]
    pub themes: Vec<ThemeConfig>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct ThemeConfig {
    /// Whether this theme is the default theme.
    pub is_default: bool,
    /// The name of the theme.
    pub name: SharedString,
    /// The mode of the theme, default is light.
    pub mode: ThemeMode,

    /// The base font size, default is 16.
    #[serde(rename = "font.size")]
    pub font_size: Option<f32>,
    /// The base font family, default is system font: `.SystemUIFont`.
    #[serde(rename = "font.family")]
    pub font_family: Option<SharedString>,
    /// The monospace font family, default is platform specific:
    /// - macOS: `Menlo`
    /// - Windows: `Consolas`
    /// - Linux: `DejaVu Sans Mono`
    ///
    /// The default falls back to an installed monospace font, then to
    /// `.SystemUIFont`, when the machine lacks it. A family named here is used
    /// as-is, so name one that is installed or embedded with `add_fonts`.
    #[serde(rename = "mono_font.family")]
    pub mono_font_family: Option<SharedString>,
    /// The monospace font size, default is 13.
    #[serde(rename = "mono_font.size")]
    pub mono_font_size: Option<f32>,

    /// The border radius for general elements, default is 6.
    #[serde(rename = "radius")]
    pub radius: Option<usize>,
    /// The border radius for large elements like Dialogs and Notifications, default is 8.
    #[serde(rename = "radius.lg")]
    pub radius_lg: Option<usize>,
    /// Set shadows in the theme, for example the Input and Button, default is true.
    #[serde(rename = "shadow")]
    pub shadow: Option<bool>,

    /// The colors of the theme.
    pub colors: ThemeConfigColors,
    /// The highlight theme, this part is combilbility with `style` section in Zed theme.
    ///
    /// https://github.com/zed-industries/zed/blob/f50041779dcfd7a76c8aec293361c60c53f02d51/assets/themes/ayu/ayu.json#L9
    pub highlight: Option<HighlightThemeStyle>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticThemeConfig {
    pub colors: SemanticColorConfig,
    pub radius: SemanticRadiusConfig,
    pub spacing: SemanticSpacingConfig,
    pub typography: SemanticTypographyConfig,
    pub shadow: SemanticShadowConfig,
}

/// Standalone semantic theme configuration file.
///
/// This wrapper is intentionally separate from [`ThemeConfig`] so adding
/// semantic tokens does not change the legacy public struct shape.
#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticThemeConfigFile {
    pub tokens: SemanticThemeConfig,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticColorConfig {
    pub background: Option<SharedString>,
    pub foreground: Option<SharedString>,
    pub surface: Option<SharedString>,
    pub surface_foreground: Option<SharedString>,
    pub primary: Option<SharedString>,
    pub primary_foreground: Option<SharedString>,
    pub secondary: Option<SharedString>,
    pub secondary_foreground: Option<SharedString>,
    pub muted: Option<SharedString>,
    pub muted_foreground: Option<SharedString>,
    pub accent: Option<SharedString>,
    pub accent_foreground: Option<SharedString>,
    pub destructive: Option<SharedString>,
    pub destructive_foreground: Option<SharedString>,
    pub border: Option<SharedString>,
    pub input: Option<SharedString>,
    pub ring: Option<SharedString>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticRadiusConfig {
    pub none: Option<f32>,
    pub sm: Option<f32>,
    pub md: Option<f32>,
    pub lg: Option<f32>,
    pub xl: Option<f32>,
    pub full: Option<f32>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticSpacingConfig {
    pub xxs: Option<f32>,
    pub xs: Option<f32>,
    pub sm: Option<f32>,
    pub md: Option<f32>,
    pub lg: Option<f32>,
    pub xl: Option<f32>,
    pub xxl: Option<f32>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticTextStyleConfig {
    pub size: Option<f32>,
    pub line_height: Option<f32>,
    pub weight: Option<FontWeight>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticTypographyConfig {
    pub sans: Option<SharedString>,
    pub mono: Option<SharedString>,
    pub xs: SemanticTextStyleConfig,
    pub sm: SemanticTextStyleConfig,
    pub md: SemanticTextStyleConfig,
    pub lg: SemanticTextStyleConfig,
    pub xl: SemanticTextStyleConfig,
    pub mono_md: SemanticTextStyleConfig,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default)]
#[non_exhaustive]
pub struct SemanticShadowConfig {
    pub sm: Option<Vec<BoxShadow>>,
    pub md: Option<Vec<BoxShadow>>,
    pub lg: Option<Vec<BoxShadow>>,
}

impl SemanticThemeConfig {
    pub(crate) fn apply_to(&self, tokens: &mut SemanticThemeTokens) {
        macro_rules! apply_color {
            ($field:ident) => {
                if let Some(value) = &self.colors.$field
                    && let Ok(value) = try_parse_color(value)
                {
                    tokens.colors.$field = value;
                }
            };
        }
        apply_color!(background);
        apply_color!(foreground);
        apply_color!(surface);
        apply_color!(surface_foreground);
        apply_color!(primary);
        apply_color!(primary_foreground);
        apply_color!(secondary);
        apply_color!(secondary_foreground);
        apply_color!(muted);
        apply_color!(muted_foreground);
        apply_color!(accent);
        apply_color!(accent_foreground);
        apply_color!(destructive);
        apply_color!(destructive_foreground);
        apply_color!(border);
        apply_color!(input);
        apply_color!(ring);

        macro_rules! apply_pixels {
            ($config:expr, $tokens:expr, $($field:ident),+ $(,)?) => {
                $(if let Some(value) = $config.$field { $tokens.$field = px(value); })+
            };
        }
        apply_pixels!(self.radius, tokens.radius, none, sm, md, lg, xl, full);
        apply_pixels!(self.spacing, tokens.spacing, xxs, xs, sm, md, lg, xl, xxl);

        if let Some(value) = &self.typography.sans {
            tokens.typography.sans = value.clone();
        }
        if let Some(value) = &self.typography.mono {
            tokens.typography.mono = value.clone();
        }
        apply_text_style(&self.typography.xs, &mut tokens.typography.xs);
        apply_text_style(&self.typography.sm, &mut tokens.typography.sm);
        apply_text_style(&self.typography.md, &mut tokens.typography.md);
        apply_text_style(&self.typography.lg, &mut tokens.typography.lg);
        apply_text_style(&self.typography.xl, &mut tokens.typography.xl);
        apply_text_style(&self.typography.mono_md, &mut tokens.typography.mono_md);

        if let Some(value) = &self.shadow.sm {
            tokens.shadow.sm = value.clone();
        }
        if let Some(value) = &self.shadow.md {
            tokens.shadow.md = value.clone();
        }
        if let Some(value) = &self.shadow.lg {
            tokens.shadow.lg = value.clone();
        }
    }
}

fn apply_text_style(config: &SemanticTextStyleConfig, token: &mut gpui_base::TextStyleToken) {
    if let Some(value) = config.size {
        token.size = px(value);
    }
    if let Some(value) = config.line_height {
        token.line_height = px(value);
    }
    if let Some(value) = config.weight {
        token.weight = value;
    }
}

#[derive(Debug, Default, Clone, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct ThemeConfigColors {
    /// Used for accents such as hover background on MenuItem, ListItem, etc.
    #[serde(rename = "accent.background")]
    pub accent: Option<SharedString>,
    /// Used for accent text color.
    #[serde(rename = "accent.foreground")]
    pub accent_foreground: Option<SharedString>,
    /// Accordion background color.
    #[serde(rename = "accordion.background")]
    pub accordion: Option<SharedString>,
    /// Default background color.
    #[serde(rename = "background")]
    pub background: Option<SharedString>,
    /// Default border color
    #[serde(rename = "border")]
    pub border: Option<SharedString>,
    /// Default Button background color.
    #[serde(rename = "button.background")]
    pub button: Option<SharedString>,
    /// Default Button active background color.
    #[serde(rename = "button.active.background")]
    pub button_active: Option<SharedString>,
    /// Default Button text color.
    #[serde(rename = "button.foreground")]
    pub button_foreground: Option<SharedString>,
    /// Default Button hover background color.
    #[serde(rename = "button.hover.background")]
    pub button_hover: Option<SharedString>,
    /// Button danger background color, fallback to `danger`.
    #[serde(rename = "button.danger.background")]
    pub button_danger: Option<SharedString>,
    /// Button danger active background color, fallback to `danger_active`.
    #[serde(rename = "button.danger.active.background")]
    pub button_danger_active: Option<SharedString>,
    /// Button danger text color, fallback to `danger_foreground`.
    #[serde(rename = "button.danger.foreground")]
    pub button_danger_foreground: Option<SharedString>,
    /// Button danger hover background color, fallback to `danger_hover`.
    #[serde(rename = "button.danger.hover.background")]
    pub button_danger_hover: Option<SharedString>,
    /// Button info background color, fallback to `info`.
    #[serde(rename = "button.info.background")]
    pub button_info: Option<SharedString>,
    /// Button info active background color, fallback to `info_active`.
    #[serde(rename = "button.info.active.background")]
    pub button_info_active: Option<SharedString>,
    /// Button info text color, fallback to `info_foreground`.
    #[serde(rename = "button.info.foreground")]
    pub button_info_foreground: Option<SharedString>,
    /// Button info hover background color, fallback to `info_hover`.
    #[serde(rename = "button.info.hover.background")]
    pub button_info_hover: Option<SharedString>,
    /// Button primary background color, fallback to `primary`.
    #[serde(rename = "button.primary.background")]
    pub button_primary: Option<SharedString>,
    /// Button primary active background color, fallback to `primary_active`.
    #[serde(rename = "button.primary.active.background")]
    pub button_primary_active: Option<SharedString>,
    /// Button primary text color, fallback to `primary_foreground`.
    #[serde(rename = "button.primary.foreground")]
    pub button_primary_foreground: Option<SharedString>,
    /// Button primary hover background color, fallback to `primary_hover`.
    #[serde(rename = "button.primary.hover.background")]
    pub button_primary_hover: Option<SharedString>,
    /// Button secondary background color, fallback to `secondary`.
    #[serde(rename = "button.secondary.background")]
    pub button_secondary: Option<SharedString>,
    /// Button secondary active background color, fallback to `secondary_active`.
    #[serde(rename = "button.secondary.active.background")]
    pub button_secondary_active: Option<SharedString>,
    /// Button secondary text color, fallback to `secondary_foreground`.
    #[serde(rename = "button.secondary.foreground")]
    pub button_secondary_foreground: Option<SharedString>,
    /// Button secondary hover background color, fallback to `secondary_hover`.
    #[serde(rename = "button.secondary.hover.background")]
    pub button_secondary_hover: Option<SharedString>,
    /// Button success background color, fallback to `success`.
    #[serde(rename = "button.success.background")]
    pub button_success: Option<SharedString>,
    /// Button success active background color, fallback to `success_active`.
    #[serde(rename = "button.success.active.background")]
    pub button_success_active: Option<SharedString>,
    /// Button success text color, fallback to `success_foreground`.
    #[serde(rename = "button.success.foreground")]
    pub button_success_foreground: Option<SharedString>,
    /// Button success hover background color, fallback to `success_hover`.
    #[serde(rename = "button.success.hover.background")]
    pub button_success_hover: Option<SharedString>,
    /// Button warning background color, fallback to `warning`.
    #[serde(rename = "button.warning.background")]
    pub button_warning: Option<SharedString>,
    /// Button warning active background color, fallback to `warning_active`.
    #[serde(rename = "button.warning.active.background")]
    pub button_warning_active: Option<SharedString>,
    /// Button warning text color, fallback to `warning_foreground`.
    #[serde(rename = "button.warning.foreground")]
    pub button_warning_foreground: Option<SharedString>,
    /// Button warning hover background color, fallback to `warning_hover`.
    #[serde(rename = "button.warning.hover.background")]
    pub button_warning_hover: Option<SharedString>,
    /// Background color for GroupBox.
    #[serde(rename = "group_box.background")]
    pub group_box: Option<SharedString>,
    /// Text color for GroupBox.
    #[serde(rename = "group_box.foreground")]
    pub group_box_foreground: Option<SharedString>,
    /// Title text color for GroupBox.
    #[serde(rename = "group_box.title.foreground")]
    pub group_box_title_foreground: Option<SharedString>,
    /// Input caret color (Blinking cursor).
    #[serde(rename = "caret")]
    pub caret: Option<SharedString>,
    /// Chart 1 color.
    #[serde(rename = "chart.1")]
    pub chart_1: Option<SharedString>,
    /// Chart 2 color.
    #[serde(rename = "chart.2")]
    pub chart_2: Option<SharedString>,
    /// Chart 3 color.
    #[serde(rename = "chart.3")]
    pub chart_3: Option<SharedString>,
    /// Chart 4 color.
    #[serde(rename = "chart.4")]
    pub chart_4: Option<SharedString>,
    /// Chart 5 color.
    #[serde(rename = "chart.5")]
    pub chart_5: Option<SharedString>,
    /// Bullish color for candlestick charts (upward price movement).
    #[serde(rename = "chart.bullish")]
    pub chart_bullish: Option<SharedString>,
    /// Bearish color for candlestick charts (downward price movement).
    #[serde(rename = "chart.bearish")]
    pub chart_bearish: Option<SharedString>,
    /// Chart grid line color.
    #[serde(rename = "chart.grid")]
    pub chart_grid: Option<SharedString>,
    /// Danger background color.
    #[serde(rename = "danger.background")]
    pub danger: Option<SharedString>,
    /// Danger active background color.
    #[serde(rename = "danger.active.background")]
    pub danger_active: Option<SharedString>,
    /// Danger text color.
    #[serde(rename = "danger.foreground")]
    pub danger_foreground: Option<SharedString>,
    /// Danger hover background color.
    #[serde(rename = "danger.hover.background")]
    pub danger_hover: Option<SharedString>,
    /// Description List label background color.
    #[serde(rename = "description_list.label.background")]
    pub description_list_label: Option<SharedString>,
    /// Description List label foreground color.
    #[serde(rename = "description_list.label.foreground")]
    pub description_list_label_foreground: Option<SharedString>,
    /// Drag border color.
    #[serde(rename = "drag.border")]
    pub drag_border: Option<SharedString>,
    /// Drop target background color.
    #[serde(rename = "drop_target.background")]
    pub drop_target: Option<SharedString>,
    /// Default text color.
    #[serde(rename = "foreground")]
    pub foreground: Option<SharedString>,
    /// Info background color.
    #[serde(rename = "info.background")]
    pub info: Option<SharedString>,
    /// Info active background color.
    #[serde(rename = "info.active.background")]
    pub info_active: Option<SharedString>,
    /// Info text color.
    #[serde(rename = "info.foreground")]
    pub info_foreground: Option<SharedString>,
    /// Info hover background color.
    #[serde(rename = "info.hover.background")]
    pub info_hover: Option<SharedString>,
    /// Border color for inputs such as Input, Select, etc.
    #[serde(rename = "input.border")]
    pub input: Option<SharedString>,
    /// Link text color.
    #[serde(rename = "link")]
    pub link: Option<SharedString>,
    /// Active link text color.
    #[serde(rename = "link.active")]
    pub link_active: Option<SharedString>,
    /// Hover link text color.
    #[serde(rename = "link.hover")]
    pub link_hover: Option<SharedString>,
    /// Background color for List and ListItem.
    #[serde(rename = "list.background")]
    pub list: Option<SharedString>,
    /// Background color for active ListItem.
    #[serde(rename = "list.active.background")]
    pub list_active: Option<SharedString>,
    /// Border color for active ListItem.
    #[serde(rename = "list.active.border")]
    pub list_active_border: Option<SharedString>,
    /// Stripe background color for even ListItem.
    #[serde(rename = "list.even.background")]
    pub list_even: Option<SharedString>,
    /// Background color for List header.
    #[serde(rename = "list.head.background")]
    pub list_head: Option<SharedString>,
    /// Hover background color for ListItem.
    #[serde(rename = "list.hover.background")]
    pub list_hover: Option<SharedString>,
    /// Muted backgrounds such as Skeleton and Switch.
    #[serde(rename = "muted.background")]
    pub muted: Option<SharedString>,
    /// Muted text color, as used in disabled text.
    #[serde(rename = "muted.foreground")]
    pub muted_foreground: Option<SharedString>,
    /// Background color for Popover.
    #[serde(rename = "popover.background")]
    pub popover: Option<SharedString>,
    /// Text color for Popover.
    #[serde(rename = "popover.foreground")]
    pub popover_foreground: Option<SharedString>,
    /// Primary background color.
    #[serde(rename = "primary.background")]
    pub primary: Option<SharedString>,
    /// Active primary background color.
    #[serde(rename = "primary.active.background")]
    pub primary_active: Option<SharedString>,
    /// Primary text color.
    #[serde(rename = "primary.foreground")]
    pub primary_foreground: Option<SharedString>,
    /// Hover primary background color.
    #[serde(rename = "primary.hover.background")]
    pub primary_hover: Option<SharedString>,
    /// Progress bar background color.
    #[serde(rename = "progress.bar.background")]
    pub progress_bar: Option<SharedString>,
    /// Used for focus ring.
    #[serde(rename = "ring")]
    pub ring: Option<SharedString>,
    /// Scrollbar background color.
    #[serde(rename = "scrollbar.background")]
    pub scrollbar: Option<SharedString>,
    /// Scrollbar thumb background color.
    #[serde(rename = "scrollbar.thumb.background")]
    pub scrollbar_thumb: Option<SharedString>,
    /// Scrollbar thumb hover background color.
    #[serde(rename = "scrollbar.thumb.hover.background")]
    pub scrollbar_thumb_hover: Option<SharedString>,
    /// Secondary background color.
    #[serde(rename = "secondary.background")]
    pub secondary: Option<SharedString>,
    /// Active secondary background color.
    #[serde(rename = "secondary.active.background")]
    pub secondary_active: Option<SharedString>,
    /// Secondary text color, used for secondary Button text color or secondary text.
    #[serde(rename = "secondary.foreground")]
    pub secondary_foreground: Option<SharedString>,
    /// Hover secondary background color.
    #[serde(rename = "secondary.hover.background")]
    pub secondary_hover: Option<SharedString>,
    /// Input selection background color.
    #[serde(rename = "selection.background")]
    pub selection: Option<SharedString>,
    /// Sidebar background color.
    #[serde(rename = "sidebar.background")]
    pub sidebar: Option<SharedString>,
    /// Sidebar accent background color.
    #[serde(rename = "sidebar.accent.background")]
    pub sidebar_accent: Option<SharedString>,
    /// Sidebar accent text color.
    #[serde(rename = "sidebar.accent.foreground")]
    pub sidebar_accent_foreground: Option<SharedString>,
    /// Sidebar border color.
    #[serde(rename = "sidebar.border")]
    pub sidebar_border: Option<SharedString>,
    /// Sidebar text color.
    #[serde(rename = "sidebar.foreground")]
    pub sidebar_foreground: Option<SharedString>,
    /// Sidebar primary background color.
    #[serde(rename = "sidebar.primary.background")]
    pub sidebar_primary: Option<SharedString>,
    /// Sidebar primary text color.
    #[serde(rename = "sidebar.primary.foreground")]
    pub sidebar_primary_foreground: Option<SharedString>,
    /// Skeleton background color.
    #[serde(rename = "skeleton.background")]
    pub skeleton: Option<SharedString>,
    /// Slider bar background color.
    #[serde(rename = "slider.background")]
    pub slider_bar: Option<SharedString>,
    /// Slider thumb background color.
    #[serde(rename = "slider.thumb.background")]
    pub slider_thumb: Option<SharedString>,
    /// Success background color.
    #[serde(rename = "success.background")]
    pub success: Option<SharedString>,
    /// Success text color.
    #[serde(rename = "success.foreground")]
    pub success_foreground: Option<SharedString>,
    /// Success hover background color.
    #[serde(rename = "success.hover.background")]
    pub success_hover: Option<SharedString>,
    /// Success active background color.
    #[serde(rename = "success.active.background")]
    pub success_active: Option<SharedString>,
    /// Switch background color.
    #[serde(rename = "switch.background")]
    pub switch: Option<SharedString>,
    /// Switch thumb background color.
    #[serde(rename = "switch.thumb.background")]
    pub switch_thumb: Option<SharedString>,
    /// Tab background color.
    #[serde(rename = "tab.background")]
    pub tab: Option<SharedString>,
    /// Tab active background color.
    #[serde(rename = "tab.active.background")]
    pub tab_active: Option<SharedString>,
    /// Tab active text color.
    #[serde(rename = "tab.active.foreground")]
    pub tab_active_foreground: Option<SharedString>,
    /// TabBar background color.
    #[serde(rename = "tab_bar.background")]
    pub tab_bar: Option<SharedString>,
    /// TabBar segmented background color.
    #[serde(rename = "tab_bar.segmented.background")]
    pub tab_bar_segmented: Option<SharedString>,
    /// Tab text color.
    #[serde(rename = "tab.foreground")]
    pub tab_foreground: Option<SharedString>,
    /// Table background color.
    #[serde(rename = "table.background")]
    pub table: Option<SharedString>,
    /// Table active item background color.
    #[serde(rename = "table.active.background")]
    pub table_active: Option<SharedString>,
    /// Table active item border color.
    #[serde(rename = "table.active.border")]
    pub table_active_border: Option<SharedString>,
    /// Stripe background color for even TableRow.
    #[serde(rename = "table.even.background")]
    pub table_even: Option<SharedString>,
    /// Table header background color.
    #[serde(rename = "table.head.background")]
    pub table_head: Option<SharedString>,
    /// Table header text color.
    #[serde(rename = "table.head.foreground")]
    pub table_head_foreground: Option<SharedString>,
    /// Table footer background color.
    #[serde(rename = "table.foot.background")]
    pub table_foot: Option<SharedString>,
    /// Table footer text color.
    #[serde(rename = "table.foot.foreground")]
    pub table_foot_foreground: Option<SharedString>,
    /// Table item hover background color.
    #[serde(rename = "table.hover.background")]
    pub table_hover: Option<SharedString>,
    /// Table row border color.
    #[serde(rename = "table.row.border")]
    pub table_row_border: Option<SharedString>,
    /// TitleBar background color, use for Window title bar.
    #[serde(rename = "title_bar.background")]
    pub title_bar: Option<SharedString>,
    /// TitleBar border color.
    #[serde(rename = "title_bar.border")]
    pub title_bar_border: Option<SharedString>,
    /// StatusBar background color, use for the bottom status bar.
    #[serde(rename = "status_bar.background")]
    pub status_bar: Option<SharedString>,
    /// StatusBar border color.
    #[serde(rename = "status_bar.border")]
    pub status_bar_border: Option<SharedString>,
    /// Warning background color.
    #[serde(rename = "warning.background")]
    pub warning: Option<SharedString>,
    /// Warning active background color.
    #[serde(rename = "warning.active.background")]
    pub warning_active: Option<SharedString>,
    /// Warning hover background color.
    #[serde(rename = "warning.hover.background")]
    pub warning_hover: Option<SharedString>,
    /// Warning foreground color.
    #[serde(rename = "warning.foreground")]
    pub warning_foreground: Option<SharedString>,
    /// Overlay background color.
    #[serde(rename = "overlay")]
    pub overlay: Option<SharedString>,
    /// Window border color.
    ///
    /// # Platform specific:
    ///
    /// This is only works on Linux, other platforms we can't change the window border color.
    #[serde(rename = "window.border")]
    pub window_border: Option<SharedString>,

    /// Base blue color.
    #[serde(rename = "base.blue")]
    blue: Option<String>,
    /// Base light blue color.
    #[serde(rename = "base.blue.light")]
    blue_light: Option<String>,
    /// Base cyan color.
    #[serde(rename = "base.cyan")]
    cyan: Option<String>,
    /// Base light cyan color.
    #[serde(rename = "base.cyan.light")]
    cyan_light: Option<String>,
    /// Base green color.
    #[serde(rename = "base.green")]
    green: Option<String>,
    /// Base light green color.
    #[serde(rename = "base.green.light")]
    green_light: Option<String>,
    /// Base magenta color.
    #[serde(rename = "base.magenta")]
    magenta: Option<String>,
    #[serde(rename = "base.magenta.light")]
    magenta_light: Option<String>,
    /// Base red color.
    #[serde(rename = "base.red")]
    red: Option<String>,
    /// Base light red color.
    #[serde(rename = "base.red.light")]
    red_light: Option<String>,
    /// Base yellow color.
    #[serde(rename = "base.yellow")]
    yellow: Option<String>,
    /// Base light yellow color.
    #[serde(rename = "base.yellow.light")]
    yellow_light: Option<String>,
}

impl ThemeColor {
    /// Create a new `ThemeColor` from a `ThemeConfig`.
    pub(crate) fn apply_config(
        &mut self,
        config: &ThemeConfig,
        default_theme: &ThemeColor,
    ) -> ThemeTokens {
        let colors = config.colors.clone();
        let default_tokens = ThemeTokens::from(default_theme);
        let mut tokens = default_tokens;

        macro_rules! apply_color {
            ($config_field:ident) => {
                if let Some(value) = &colors.$config_field {
                    self.$config_field =
                        try_parse_color(value).unwrap_or(default_theme.$config_field);
                } else {
                    self.$config_field = default_theme.$config_field;
                }
                tokens.$config_field = self.$config_field.into();
            };
            // With fallback
            ($config_field:ident, fallback = $fallback:expr) => {
                let fallback: gpui::Hsla = ($fallback).into();
                if let Some(value) = &colors.$config_field {
                    self.$config_field = try_parse_color(value).unwrap_or(fallback);
                } else {
                    self.$config_field = fallback;
                }
                tokens.$config_field = self.$config_field.into();
            };
        }

        macro_rules! apply_background_color {
            ($config_field:ident) => {
                let token = if let Some(value) = &colors.$config_field {
                    if let Ok(token) = try_parse_theme_token(&value) {
                        token
                    } else {
                        default_tokens.$config_field
                    }
                } else {
                    default_tokens.$config_field
                };
                self.$config_field = token.color;
                tokens.$config_field = token;
            };
            ($config_field:ident, fallback = $fallback:expr) => {
                let fallback: ThemeToken = ($fallback).into();
                let token = if let Some(value) = &colors.$config_field {
                    if let Ok(token) = try_parse_theme_token(&value) {
                        token
                    } else {
                        fallback
                    }
                } else {
                    fallback
                };
                self.$config_field = token.color;
                tokens.$config_field = token;
            };
        }

        apply_background_color!(background);

        // Base colors for fallback
        apply_color!(red);
        apply_color!(
            red_light,
            fallback = self.background.blend(self.red.opacity(0.8))
        );
        apply_color!(green);
        apply_color!(
            green_light,
            fallback = self.background.blend(self.green.opacity(0.8))
        );
        apply_color!(blue);
        apply_color!(
            blue_light,
            fallback = self.background.blend(self.blue.opacity(0.8))
        );
        apply_color!(magenta);
        apply_color!(
            magenta_light,
            fallback = self.background.blend(self.magenta.opacity(0.8))
        );
        apply_color!(yellow);
        apply_color!(
            yellow_light,
            fallback = self.background.blend(self.yellow.opacity(0.8))
        );
        apply_color!(cyan);
        apply_color!(
            cyan_light,
            fallback = self.background.blend(self.cyan.opacity(0.8))
        );

        apply_color!(border);
        apply_color!(foreground);
        apply_color!(input, fallback = self.border);
        apply_background_color!(muted);
        apply_color!(
            muted_foreground,
            fallback = self.muted.blend(self.foreground.opacity(0.7))
        );

        // Button colors
        let active_darken = if config.mode.is_dark() { 0.2 } else { 0.1 };
        let hover_opacity = 0.9;
        let transparent = gpui::transparent_black();
        let button_background = if config.mode.is_dark() {
            self.input.mix_oklab(transparent, 0.3)
        } else {
            self.background
        };
        apply_background_color!(button, fallback = button_background);
        apply_color!(button_foreground, fallback = self.foreground);
        apply_background_color!(
            button_hover,
            fallback = self.input.mix_oklab(transparent, 0.5)
        );
        apply_background_color!(
            button_active,
            fallback = self.input.mix_oklab(transparent, 0.7)
        );
        apply_background_color!(primary);
        apply_color!(primary_foreground, fallback = self.foreground);
        apply_background_color!(
            primary_hover,
            fallback = self.background.blend(self.primary.opacity(hover_opacity))
        );
        apply_background_color!(
            primary_active,
            fallback = self.primary.darken(active_darken)
        );
        apply_background_color!(button_primary, fallback = tokens.primary);
        apply_color!(
            button_primary_foreground,
            fallback = self.primary_foreground
        );
        apply_background_color!(button_primary_hover, fallback = tokens.primary_hover);
        apply_background_color!(button_primary_active, fallback = tokens.primary_active);
        apply_background_color!(secondary);
        apply_color!(secondary_foreground, fallback = self.foreground);
        apply_background_color!(
            secondary_hover,
            fallback = self.background.blend(self.secondary.opacity(hover_opacity))
        );
        apply_background_color!(
            secondary_active,
            fallback = self.secondary.darken(active_darken)
        );
        apply_background_color!(button_secondary, fallback = tokens.secondary);
        apply_color!(
            button_secondary_foreground,
            fallback = self.secondary_foreground
        );
        apply_background_color!(button_secondary_hover, fallback = tokens.secondary_hover);
        apply_background_color!(button_secondary_active, fallback = tokens.secondary_active);
        apply_background_color!(success, fallback = self.green);
        apply_color!(success_foreground, fallback = self.primary_foreground);
        apply_background_color!(
            success_hover,
            fallback = self.background.blend(self.success.opacity(hover_opacity))
        );
        apply_background_color!(
            success_active,
            fallback = self.success.darken(active_darken)
        );
        apply_background_color!(
            button_success,
            fallback = self.success.mix_oklab(transparent, 0.2)
        );
        apply_color!(button_success_foreground, fallback = self.success);
        apply_background_color!(
            button_success_hover,
            fallback = self.success.mix_oklab(transparent, 0.3)
        );
        apply_background_color!(
            button_success_active,
            fallback = self.success.mix_oklab(transparent, 0.4)
        );
        apply_background_color!(info, fallback = self.cyan);
        apply_color!(info_foreground, fallback = self.primary_foreground);
        apply_background_color!(
            info_hover,
            fallback = self.background.blend(self.info.opacity(hover_opacity))
        );
        apply_background_color!(info_active, fallback = self.info.darken(active_darken));
        apply_background_color!(
            button_info,
            fallback = self.info.mix_oklab(transparent, 0.2)
        );
        apply_color!(button_info_foreground, fallback = self.info);
        apply_background_color!(
            button_info_hover,
            fallback = self.info.mix_oklab(transparent, 0.3)
        );
        apply_background_color!(
            button_info_active,
            fallback = self.info.mix_oklab(transparent, 0.4)
        );
        apply_background_color!(warning, fallback = self.yellow);
        apply_color!(warning_foreground, fallback = self.primary_foreground);
        apply_background_color!(
            warning_hover,
            fallback = self.background.blend(self.warning.opacity(0.9))
        );
        apply_background_color!(
            warning_active,
            fallback = self.background.blend(self.warning.darken(active_darken))
        );
        apply_background_color!(
            button_warning,
            fallback = self.warning.mix_oklab(transparent, 0.2)
        );
        apply_color!(button_warning_foreground, fallback = self.warning);
        apply_background_color!(
            button_warning_hover,
            fallback = self.warning.mix_oklab(transparent, 0.3)
        );
        apply_background_color!(
            button_warning_active,
            fallback = self.warning.mix_oklab(transparent, 0.4)
        );

        // Other colors
        apply_background_color!(accent, fallback = tokens.secondary);
        apply_color!(accent_foreground, fallback = self.foreground);
        apply_background_color!(accordion, fallback = tokens.background);
        apply_background_color!(
            group_box,
            fallback = self
                .background
                .blend(
                    self.secondary
                        .opacity(if config.mode.is_dark() { 0.3 } else { 0.4 })
                )
        );
        apply_color!(group_box_foreground, fallback = self.foreground);
        apply_color!(caret, fallback = self.primary);
        apply_color!(chart_1, fallback = self.blue.lighten(0.4));
        apply_color!(chart_2, fallback = self.blue.lighten(0.2));
        apply_color!(chart_3, fallback = self.blue);
        apply_color!(chart_4, fallback = self.blue.darken(0.2));
        apply_color!(chart_5, fallback = self.blue.darken(0.4));
        apply_color!(chart_bullish, fallback = self.green);
        apply_color!(chart_bearish, fallback = self.red);
        apply_color!(chart_grid, fallback = self.border.opacity(0.6));
        apply_background_color!(danger, fallback = self.red);
        apply_background_color!(danger_active, fallback = self.danger.darken(active_darken));
        apply_color!(danger_foreground, fallback = self.primary_foreground);
        apply_background_color!(
            danger_hover,
            fallback = self.background.blend(self.danger.opacity(0.9))
        );
        apply_background_color!(
            button_danger,
            fallback = self.danger.mix_oklab(transparent, 0.2)
        );
        apply_color!(button_danger_foreground, fallback = self.danger);
        apply_background_color!(
            button_danger_hover,
            fallback = self.danger.mix_oklab(transparent, 0.3)
        );
        apply_background_color!(
            button_danger_active,
            fallback = self.danger.mix_oklab(transparent, 0.4)
        );
        apply_background_color!(
            description_list_label,
            fallback = self.background.blend(self.border.opacity(0.2))
        );
        apply_color!(
            description_list_label_foreground,
            fallback = self.muted_foreground
        );
        apply_color!(drag_border, fallback = self.primary.opacity(0.65));
        apply_background_color!(drop_target, fallback = self.primary.opacity(0.2));
        apply_color!(link, fallback = self.primary);
        apply_color!(link_active, fallback = self.link);
        apply_color!(link_hover, fallback = self.link);
        apply_background_color!(list, fallback = tokens.background);
        apply_background_color!(
            list_active,
            fallback = self.background.blend(self.primary.opacity(0.1))
        );
        apply_color!(
            list_active_border,
            fallback = self.background.blend(self.primary.opacity(0.6))
        );
        apply_background_color!(list_even, fallback = tokens.list);
        apply_background_color!(list_head, fallback = tokens.list);
        apply_background_color!(list_hover, fallback = self.accent.opacity(0.6));
        apply_background_color!(popover, fallback = tokens.background);
        apply_color!(popover_foreground, fallback = self.foreground);
        apply_background_color!(progress_bar, fallback = tokens.primary);
        apply_color!(ring, fallback = self.blue);
        apply_background_color!(scrollbar, fallback = tokens.background);
        apply_background_color!(scrollbar_thumb, fallback = tokens.accent);
        apply_background_color!(scrollbar_thumb_hover, fallback = tokens.scrollbar_thumb);
        apply_background_color!(selection, fallback = tokens.primary);
        apply_background_color!(
            sidebar,
            fallback = self.background.blend(self.border.opacity(0.15))
        );
        apply_background_color!(sidebar_accent, fallback = tokens.accent);
        apply_color!(sidebar_accent_foreground, fallback = self.accent_foreground);
        apply_color!(sidebar_border, fallback = self.border);
        apply_color!(sidebar_foreground, fallback = self.foreground);
        apply_background_color!(sidebar_primary, fallback = tokens.primary);
        apply_color!(
            sidebar_primary_foreground,
            fallback = self.primary_foreground
        );
        apply_background_color!(skeleton, fallback = tokens.secondary);
        apply_background_color!(slider_bar, fallback = tokens.primary);
        apply_background_color!(slider_thumb, fallback = self.primary_foreground);
        apply_background_color!(switch, fallback = tokens.secondary_active);
        apply_background_color!(switch_thumb, fallback = tokens.background);
        apply_background_color!(tab, fallback = tokens.background);
        apply_background_color!(tab_active, fallback = tokens.background);
        apply_color!(tab_active_foreground, fallback = self.foreground);
        apply_background_color!(tab_bar, fallback = tokens.background);
        apply_background_color!(tab_bar_segmented, fallback = tokens.secondary);
        apply_color!(tab_foreground, fallback = self.foreground);
        apply_background_color!(table, fallback = tokens.list);
        apply_background_color!(table_active, fallback = tokens.list_active);
        apply_color!(table_active_border, fallback = self.list_active_border);
        apply_background_color!(table_even, fallback = tokens.list_even);
        apply_background_color!(table_head, fallback = tokens.list_head);
        apply_color!(table_head_foreground, fallback = self.muted_foreground);
        apply_background_color!(table_foot, fallback = tokens.list_head);
        apply_color!(table_foot_foreground, fallback = self.muted_foreground);
        apply_background_color!(table_hover, fallback = tokens.list_hover);
        apply_color!(table_row_border, fallback = self.border);
        apply_background_color!(title_bar, fallback = tokens.background);
        apply_color!(title_bar_border, fallback = self.border);
        apply_background_color!(status_bar, fallback = tokens.title_bar);
        apply_color!(status_bar_border, fallback = self.title_bar_border);
        apply_background_color!(overlay);
        apply_color!(window_border, fallback = self.border);

        // TODO: Apply default fallback colors to highlight.

        // Ensure opacity for list_active, table_active, selection.
        let clamp_alpha = |raw: Option<&str>, color: Hsla, background: Background, max: f32| {
            let base = color.a;
            let target = base.min(max);
            let color = color.alpha(target);
            let background = raw
                .and_then(|value| try_parse_background_clamped(value, max).ok())
                .unwrap_or_else(|| {
                    let factor = if base > 0. { target / base } else { 1. };
                    background.opacity(factor)
                });
            (color, ThemeToken::new(color, background))
        };

        (self.list_active, tokens.list_active) = clamp_alpha(
            colors.list_active.as_deref(),
            self.list_active,
            tokens.list_active.background,
            0.2,
        );
        (self.table_active, tokens.table_active) = clamp_alpha(
            colors.table_active.as_deref(),
            self.table_active,
            tokens.table_active.background,
            0.2,
        );
        (self.selection, tokens.selection) = clamp_alpha(
            colors.selection.as_deref(),
            self.selection,
            tokens.selection.background,
            0.3,
        );

        tokens
    }
}

impl Theme {
    /// Apply the given theme configuration to the current theme.
    pub fn apply_config(&mut self, config: &Rc<ThemeConfig>) {
        if config.mode.is_dark() {
            self.dark_theme = config.clone();
        } else {
            self.light_theme = config.clone();
        }
        if let Some(style) = &config.highlight {
            let highlight_theme = Arc::new(HighlightTheme {
                name: config.name.to_string(),
                appearance: config.mode,
                style: style.clone(),
            });
            self.highlight_theme = highlight_theme.clone();
        }

        let default_colors = if config.mode.is_dark() {
            ThemeColor::dark()
        } else {
            ThemeColor::light()
        };

        if let Some(font_size) = config.font_size {
            self.font_size = px(font_size);
        }
        if let Some(font_family) = &config.font_family {
            self.font_family = font_family.clone();
        }
        if let Some(mono_font_family) = &config.mono_font_family {
            self.mono_font_family = mono_font_family.clone();
        }
        if let Some(mono_font_size) = config.mono_font_size {
            self.mono_font_size = px(mono_font_size);
        }
        if let Some(radius) = config.radius {
            self.radius = px(radius as f32);
        }
        if let Some(radius_lg) = config.radius_lg {
            self.radius_lg = px(radius_lg as f32);
        }
        if let Some(shadow) = config.shadow {
            self.shadow = shadow;
        }

        self.tokens = self.colors.apply_config(&config, &default_colors);
        self.mode = config.mode;
    }
}

#[cfg(test)]
mod tests {
    use gpui::{linear_color_stop, linear_gradient, px};

    use crate::{Colorize as _, Theme, ThemeConfig, ThemeMode, ThemeSet, try_parse_color};

    #[test]
    fn test_semantic_theme_config_parses_and_roundtrips() {
        let value = serde_json::json!({
            "name": "Semantic",
            "mode": "dark",
            "tokens": {
                "colors": {
                    "surface": "#111827",
                    "surface_foreground": "#f9fafb",
                    "primary": "#2563eb",
                    "destructive": "#dc2626"
                },
                "radius": { "sm": 2.0, "md": 6.0, "lg": 10.0 },
                "spacing": { "xs": 4.0, "md": 12.0, "xl": 24.0 },
                "typography": {
                    "sans": "Inter",
                    "md": { "size": 15.0, "line_height": 22.0 }
                }
            }
        });
        let config: super::SemanticThemeConfigFile = serde_json::from_value(value).unwrap();
        let serialized = serde_json::to_string(&config).unwrap();
        let reparsed: super::SemanticThemeConfigFile = serde_json::from_str(&serialized).unwrap();
        let semantic = reparsed.tokens;

        assert_eq!(semantic.colors.surface.as_deref(), Some("#111827"));
        assert_eq!(semantic.colors.destructive.as_deref(), Some("#dc2626"));
        assert_eq!(semantic.radius.lg, Some(10.0));
        assert_eq!(semantic.spacing.xl, Some(24.0));
        assert_eq!(semantic.typography.sans.as_deref(), Some("Inter"));
        assert_eq!(semantic.typography.md.line_height, Some(22.0));

        let mut theme = Theme::default();
        let resolved = theme.apply_semantic_config_str(&serialized).unwrap();
        assert_eq!(theme.primary, try_parse_color("#2563eb").unwrap());
        assert_eq!(resolved.spacing.xl, px(24.));
        assert_eq!(resolved.typography.md.line_height, px(22.));
    }

    #[test]
    fn test_semantic_tokens_override_legacy_generic_fields_only() {
        let config = serde_json::from_value::<super::SemanticThemeConfigFile>(serde_json::json!({
            "tokens": {
                "colors": { "primary": "#2563eb", "destructive": "#b91c1c" },
                "spacing": { "md": 14.0 },
                "typography": { "md": { "size": 15.0 } }
            }
        }))
        .unwrap();
        let mut theme = Theme::default();
        let component_color = theme.button_primary;
        let resolved = theme.apply_semantic_config(&config.tokens);

        assert_eq!(theme.primary, try_parse_color("#2563eb").unwrap());
        assert_eq!(theme.danger, try_parse_color("#b91c1c").unwrap());
        assert_eq!(theme.button_primary, component_color);
        assert_eq!(resolved.spacing.md, px(14.));
        assert_eq!(resolved.typography.md.size, px(15.));
    }

    #[test]
    fn test_legacy_config_without_semantic_tokens_is_unchanged() {
        let config = serde_json::from_value::<ThemeConfig>(serde_json::json!({
            "name": "Legacy",
            "mode": "light",
            "radius": 7,
            "colors": { "primary.background": "#7c3aed" }
        }))
        .unwrap();
        let mut theme = Theme::default();
        theme.apply_config(&std::rc::Rc::new(config));
        assert_eq!(theme.primary, try_parse_color("#7c3aed").unwrap());
        assert_eq!(theme.radius, px(7.));
        assert_eq!(theme.semantic_tokens().spacing, Default::default());
    }

    #[test]
    fn test_apply_config_reads_the_chart_colors() {
        let config = serde_json::from_value::<ThemeConfig>(serde_json::json!({
            "name": "Palette",
            "mode": "light",
            "colors": {
                "chart.1": "#111111",
                "chart.2": "not a color",
                "chart.3": "#333333",
                "chart.bullish": "#00ff00",
                "chart.bearish": "#ff0000",
                "chart.grid": "#eeeeee"
            }
        }))
        .unwrap();

        let mut theme = Theme::default();
        theme.apply_config(&std::rc::Rc::new(config));

        // The keys match the fields; an unparsable or missing one falls back
        // to the ramp of the base blue.
        assert_eq!(theme.chart_1, try_parse_color("#111111").unwrap());
        assert_eq!(theme.chart_2, theme.blue.lighten(0.2));
        assert_eq!(theme.chart_3, try_parse_color("#333333").unwrap());
        assert_eq!(theme.chart_4, theme.blue.darken(0.2));
        assert_eq!(theme.chart_5, theme.blue.darken(0.4));
        assert_eq!(theme.tokens.chart_3.color, theme.chart_3);
        assert_eq!(theme.chart_bullish, try_parse_color("#00ff00").unwrap());
        assert_eq!(theme.chart_bearish, try_parse_color("#ff0000").unwrap());
        assert_eq!(theme.chart_grid, try_parse_color("#eeeeee").unwrap());

        theme.apply_config(&std::rc::Rc::new(ThemeConfig::default()));
        assert_eq!(theme.chart_grid, theme.border.opacity(0.6));
    }

    #[test]
    fn test_apply_config_preserves_gradient_background_and_solid_color_fallback() {
        let config = serde_json::from_value::<ThemeConfig>(serde_json::json!({
            "name": "Gradient",
            "mode": "light",
            "colors": {
                "primary.background": "linear-gradient(135deg, #4F46E5, #06B6D4)",
                "button.primary.hover.background": "linear-gradient(to right, red-500 25%, blue-600 75%)"
            }
        }))
        .unwrap();

        let mut theme = Theme::default();
        theme.apply_config(&std::rc::Rc::new(config));

        let primary_from = try_parse_color("#4F46E5").unwrap();
        let primary_to = try_parse_color("#06B6D4").unwrap();
        assert_eq!(theme.primary, primary_from);
        assert_eq!(theme.tokens.primary.color, primary_from);
        assert_eq!(
            theme.tokens.primary.background,
            linear_gradient(
                135.,
                linear_color_stop(primary_from, 0.),
                linear_color_stop(primary_to, 1.)
            )
        );
        assert_eq!(
            theme.tokens.button_primary.background,
            theme.tokens.primary.background
        );
        assert_eq!(
            theme.tokens.button_primary_hover.background,
            linear_gradient(
                90.,
                linear_color_stop(crate::red_500(), 0.25),
                linear_color_stop(crate::blue_600(), 0.75)
            )
        );
        assert_eq!(theme.mode, ThemeMode::Light);
    }

    #[test]
    fn test_aurora_theme_parses_gradient_backgrounds() {
        let theme_set =
            serde_json::from_str::<ThemeSet>(include_str!("../../../../themes/aurora.json"))
                .unwrap();
        assert_eq!(theme_set.themes.len(), 1);
        assert!(theme_set.themes.iter().all(|theme| !theme.mode.is_dark()));

        let light = theme_set
            .themes
            .iter()
            .find(|theme| theme.name.as_ref() == "Aurora Light")
            .unwrap();
        let mut theme = Theme::default();
        theme.apply_config(&std::rc::Rc::new(light.clone()));

        assert_ne!(
            theme.tokens.button_primary.background,
            theme.button_primary.into()
        );
        assert_eq!(theme.tokens.background.background, theme.background.into());
        assert_eq!(theme.button_primary, try_parse_color("#1E293B").unwrap());
        assert_eq!(theme.background, try_parse_color("#FFFFFF").unwrap());
        assert_ne!(
            theme.tokens.progress_bar.background,
            theme.progress_bar.into()
        );
        assert_ne!(
            theme.tokens.scrollbar_thumb.background,
            theme.scrollbar_thumb.into()
        );
        assert_ne!(theme.tokens.switch.background, theme.switch.into());
        assert_ne!(
            theme.tokens.switch_thumb.background,
            theme.switch_thumb.into()
        );
        assert_ne!(theme.tokens.title_bar.background, theme.title_bar.into());
        assert_ne!(theme.tokens.status_bar.background, theme.status_bar.into());
    }

    #[test]
    fn test_apply_config_clamps_highlight_alpha_per_gradient_stop() {
        let config = serde_json::from_value::<ThemeConfig>(serde_json::json!({
            "name": "Highlight",
            "mode": "light",
            "colors": {
                // Solid above the cap: must be capped to 0.2, not attenuated twice.
                "list.active.background": "#3b82f6",
                // Gradient with a faint `from` stop and an opaque `to` stop: the
                // `to` stop must be clamped independently, not left at full alpha.
                "table.active.background": "linear-gradient(#bfdbfe33, #3b82f6)",
                // Gradient with a transparent `from` stop: the opaque `to` stop
                // must still be clamped (the `base == 0` factor fallback used to
                // leave it untouched).
                "selection.background": "linear-gradient(#3b82f600, #3b82f6)",
            }
        }))
        .unwrap();

        let mut theme = Theme::default();
        theme.apply_config(&std::rc::Rc::new(config));

        // Solid: representative color and rendered background both capped at 0.2.
        let blue = try_parse_color("#3b82f6").unwrap();
        assert_eq!(theme.list_active, blue.alpha(0.2));
        assert_eq!(theme.tokens.list_active.background, blue.alpha(0.2).into());

        // Gradient: the opaque `to` stop is clamped to 0.2, not left fully opaque.
        let faint = try_parse_color("#bfdbfe33").unwrap();
        assert_eq!(
            theme.tokens.table_active.background,
            linear_gradient(
                180.,
                linear_color_stop(faint.alpha(faint.a.min(0.2)), 0.),
                linear_color_stop(blue.alpha(0.2), 1.),
            )
        );

        // Gradient: a transparent `from` stop stays transparent while the opaque
        // `to` stop is still clamped to 0.3 (selection cap).
        let clear = try_parse_color("#3b82f600").unwrap();
        assert_eq!(
            theme.tokens.selection.background,
            linear_gradient(
                180.,
                linear_color_stop(clear.alpha(clear.a.min(0.3)), 0.),
                linear_color_stop(blue.alpha(0.3), 1.),
            )
        );
    }
}
