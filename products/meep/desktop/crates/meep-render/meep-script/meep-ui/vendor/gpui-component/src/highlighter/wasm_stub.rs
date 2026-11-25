//! The highlighter module without tree-sitter: for WASM, or a native build
//! that chose `syntect` or no highlighter at all. Syntax highlighting itself
//! comes from `syntect_backend` when that feature is on; the theme types here
//! are shared either way.
//!
//! Note: diagnostics.rs is available in WASM, only syntax highlighting requires stubs.

use gpui::{HighlightStyle, SharedString};
use std::ops::Range;
use std::time::Duration;

// Syntax highlighter stub. With `syntect` it names highlights for the
// presentations that resolve styles themselves, such as a diff.
pub struct SyntaxHighlighter {
    #[cfg_attr(not(feature = "syntect"), allow(dead_code))]
    language: SharedString,
}

impl SyntaxHighlighter {
    pub fn new(language: impl AsRef<str>) -> Self {
        Self {
            language: language.as_ref().to_owned().into(),
        }
    }

    pub fn highlight(&self, _text: &ropey::Rope) -> Vec<(Range<usize>, HighlightStyle)> {
        Vec::new()
    }

    pub fn styles(
        &self,
        range: &Range<usize>,
        _theme: &HighlightTheme,
    ) -> Vec<(Range<usize>, HighlightStyle)> {
        // If the matched styles is empty, return a default range.
        vec![(range.clone(), HighlightStyle::default())]
    }

    pub fn update(
        &mut self,
        _edit: Option<crate::input::InputEdit>,
        _text: &ropey::Rope,
        _timeout: Option<Duration>,
    ) -> bool {
        // No-op in WASM
        true
    }

    pub(crate) fn capture_names(
        &mut self,
        _text: &ropey::Rope,
    ) -> Vec<(Range<usize>, SharedString)> {
        #[cfg(feature = "syntect")]
        return super::syntect_backend::capture_names(&self.language, &_text.to_string());
        #[cfg(not(feature = "syntect"))]
        Vec::new()
    }

    pub fn edit_tree(&mut self, _edit: Option<crate::input::InputEdit>, _text: &ropey::Rope) {
        // No-op in WASM
    }

    pub fn language(&self) -> &SharedString {
        static EMPTY: SharedString = SharedString::new_static("");
        &EMPTY
    }

    pub fn text(&self) -> &ropey::Rope {
        static EMPTY_ROPE: LazyLock<ropey::Rope> = LazyLock::new(ropey::Rope::new);
        &EMPTY_ROPE
    }

    pub fn tree(&self) -> Option<&crate::input::Tree> {
        None
    }
}

// Language enum stub
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Language {
    Unknown,
}

impl Language {
    pub fn from_str(_name: &str) -> Self {
        Language::Unknown
    }

    pub fn name(&self) -> &'static str {
        "unknown"
    }

    pub fn config(&self) -> GrammarConfig {
        GrammarConfig {
            name: "unknown".into(),
        }
    }

    pub fn all() -> impl Iterator<Item = Self> {
        std::iter::once(Language::Unknown)
    }
}

// Language config stub (without tree_sitter::Language)
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanguageConfig {
    pub name: SharedString,
}

/// Explicit name for grammar resources; editing rules use `input::language_config::LanguageConfig`.
pub type GrammarConfig = LanguageConfig;

impl LanguageConfig {
    pub fn has_grammar(&self) -> bool {
        false
    }
}

// Re-export theme types from registry module (which will be conditionally compiled)
// For WASM, we create minimal stubs here
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_repr::{Deserialize_repr, Serialize_repr};
use std::{
    collections::HashMap,
    sync::{LazyLock, Mutex},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FontStyle {
    Normal,
    Italic,
    Underline,
}

#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq, JsonSchema, Serialize_repr, Deserialize_repr)]
#[repr(u16)]
pub enum FontWeightContent {
    Thin = 100,
    ExtraLight = 200,
    Light = 300,
    Normal = 400,
    Medium = 500,
    Semibold = 600,
    Bold = 700,
    ExtraBold = 800,
    Black = 900,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct ThemeStyle {
    pub color: Option<gpui::Hsla>,
    pub font_style: Option<FontStyle>,
    pub font_weight: Option<FontWeightContent>,
}

impl From<ThemeStyle> for HighlightStyle {
    fn from(style: ThemeStyle) -> Self {
        HighlightStyle {
            color: style.color,
            font_weight: style.font_weight.map(|w| match w {
                FontWeightContent::Thin => gpui::FontWeight::THIN,
                FontWeightContent::ExtraLight => gpui::FontWeight::EXTRA_LIGHT,
                FontWeightContent::Light => gpui::FontWeight::LIGHT,
                FontWeightContent::Normal => gpui::FontWeight::NORMAL,
                FontWeightContent::Medium => gpui::FontWeight::MEDIUM,
                FontWeightContent::Semibold => gpui::FontWeight::SEMIBOLD,
                FontWeightContent::Bold => gpui::FontWeight::BOLD,
                FontWeightContent::ExtraBold => gpui::FontWeight::EXTRA_BOLD,
                FontWeightContent::Black => gpui::FontWeight::BLACK,
            }),
            font_style: style.font_style.map(|s| match s {
                FontStyle::Normal => gpui::FontStyle::Normal,
                FontStyle::Italic => gpui::FontStyle::Italic,
                FontStyle::Underline => gpui::FontStyle::Normal,
            }),
            ..Default::default()
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct SyntaxColors {
    pub attribute: Option<ThemeStyle>,
    pub boolean: Option<ThemeStyle>,
    pub comment: Option<ThemeStyle>,
    pub comment_doc: Option<ThemeStyle>,
    pub constant: Option<ThemeStyle>,
    pub constructor: Option<ThemeStyle>,
    pub embedded: Option<ThemeStyle>,
    pub emphasis: Option<ThemeStyle>,
    #[serde(rename = "emphasis.strong")]
    pub emphasis_strong: Option<ThemeStyle>,
    #[serde(rename = "enum")]
    pub enum_: Option<ThemeStyle>,
    pub function: Option<ThemeStyle>,
    pub hint: Option<ThemeStyle>,
    pub keyword: Option<ThemeStyle>,
    pub label: Option<ThemeStyle>,
    #[serde(rename = "link_text")]
    pub link_text: Option<ThemeStyle>,
    #[serde(rename = "link_uri")]
    pub link_uri: Option<ThemeStyle>,
    pub number: Option<ThemeStyle>,
    pub operator: Option<ThemeStyle>,
    pub predictive: Option<ThemeStyle>,
    pub preproc: Option<ThemeStyle>,
    pub primary: Option<ThemeStyle>,
    pub property: Option<ThemeStyle>,
    pub punctuation: Option<ThemeStyle>,
    #[serde(rename = "punctuation.bracket")]
    pub punctuation_bracket: Option<ThemeStyle>,
    #[serde(rename = "punctuation.delimiter")]
    pub punctuation_delimiter: Option<ThemeStyle>,
    #[serde(rename = "punctuation.list_marker")]
    pub punctuation_list_marker: Option<ThemeStyle>,
    #[serde(rename = "punctuation.special")]
    pub punctuation_special: Option<ThemeStyle>,
    pub string: Option<ThemeStyle>,
    #[serde(rename = "string.escape")]
    pub string_escape: Option<ThemeStyle>,
    #[serde(rename = "string.regex")]
    pub string_regex: Option<ThemeStyle>,
    #[serde(rename = "string.special")]
    pub string_special: Option<ThemeStyle>,
    #[serde(rename = "string.special.symbol")]
    pub string_special_symbol: Option<ThemeStyle>,
    pub tag: Option<ThemeStyle>,
    #[serde(rename = "tag.doctype")]
    pub tag_doctype: Option<ThemeStyle>,
    #[serde(rename = "text.code.span")]
    pub text_code_span: Option<ThemeStyle>,
    #[serde(rename = "text.literal")]
    pub text_literal: Option<ThemeStyle>,
    pub title: Option<ThemeStyle>,
    #[serde(rename = "type")]
    pub type_: Option<ThemeStyle>,
    pub variable: Option<ThemeStyle>,
    #[serde(rename = "variable.special")]
    pub variable_special: Option<ThemeStyle>,
    pub variant: Option<ThemeStyle>,
}

impl SyntaxColors {
    pub fn style(&self, name: &str) -> Option<HighlightStyle> {
        if name.is_empty() {
            return None;
        }

        let style = match name {
            "attribute" => self.attribute,
            "boolean" => self.boolean,
            "comment" => self.comment,
            "comment.doc" => self.comment_doc,
            "constant" => self.constant,
            "constructor" => self.constructor,
            "embedded" => self.embedded,
            "emphasis" => self.emphasis,
            "emphasis.strong" => self.emphasis_strong,
            "enum" => self.enum_,
            "function" => self.function,
            "hint" => self.hint,
            "keyword" => self.keyword,
            "label" => self.label,
            "link_text" => self.link_text,
            "link_uri" => self.link_uri,
            "number" => self.number,
            "operator" => self.operator,
            "predictive" => self.predictive,
            "preproc" => self.preproc,
            "primary" => self.primary,
            "property" => self.property,
            "punctuation" => self.punctuation,
            "punctuation.bracket" => self.punctuation_bracket,
            "punctuation.delimiter" => self.punctuation_delimiter,
            "punctuation.list_marker" => self.punctuation_list_marker,
            "punctuation.special" => self.punctuation_special,
            "string" => self.string,
            "string.escape" => self.string_escape,
            "string.regex" => self.string_regex,
            "string.special" => self.string_special,
            "string.special.symbol" => self.string_special_symbol,
            "tag" => self.tag,
            "tag.doctype" => self.tag_doctype,
            "text.code.span" => self.text_code_span,
            "text.literal" => self.text_literal,
            "title" => self.title,
            "type" => self.type_,
            "variable" => self.variable,
            "variable.special" => self.variable_special,
            "variant" => self.variant,
            _ => None,
        }
        .map(|s| s.into());

        if style.is_some() {
            style
        } else if name.contains('.') {
            name.split('.').next().and_then(|prefix| self.style(prefix))
        } else {
            None
        }
    }

    pub fn style_for_index(&self, index: usize) -> Option<HighlightStyle> {
        const HIGHLIGHT_NAMES: [&str; 41] = [
            "attribute",
            "boolean",
            "comment",
            "comment.doc",
            "constant",
            "constructor",
            "embedded",
            "emphasis",
            "emphasis.strong",
            "enum",
            "function",
            "hint",
            "keyword",
            "label",
            "link_text",
            "link_uri",
            "number",
            "operator",
            "predictive",
            "preproc",
            "primary",
            "property",
            "punctuation",
            "punctuation.bracket",
            "punctuation.delimiter",
            "punctuation.list_marker",
            "punctuation.special",
            "string",
            "string.escape",
            "string.regex",
            "string.special",
            "string.special.symbol",
            "tag",
            "tag.doctype",
            "text.code.span",
            "text.literal",
            "title",
            "type",
            "variable",
            "variable.special",
            "variant",
        ];

        HIGHLIGHT_NAMES.get(index).and_then(|name| self.style(name))
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
pub struct StatusColors {
    // Minimal stub
}

impl StatusColors {
    pub fn error(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn error_background(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn error_border(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn warning(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn warning_background(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn warning_border(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn info(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn info_background(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn info_border(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn success(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn success_background(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn success_border(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn hint(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn hint_background(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn hint_border(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn created(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn modified(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }

    pub fn deleted(&self, _cx: &gpui::App) -> gpui::Hsla {
        gpui::Hsla::default()
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct HighlightThemeStyle {
    pub editor_background: Option<gpui::Hsla>,
    pub editor_foreground: Option<gpui::Hsla>,
    pub editor_active_line: Option<gpui::Hsla>,
    pub editor_line_number: Option<gpui::Hsla>,
    pub editor_active_line_number: Option<gpui::Hsla>,
    pub editor_invisible: Option<gpui::Hsla>,
    #[serde(rename = "editor.gutter.background")]
    pub editor_gutter_background: Option<gpui::Hsla>,
    #[serde(flatten)]
    pub status: StatusColors,
    #[serde(rename = "syntax")]
    pub syntax: SyntaxColors,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct HighlightTheme {
    pub name: String,
    #[serde(default)]
    pub appearance: crate::ThemeMode,
    pub style: HighlightThemeStyle,
}

impl std::ops::Deref for HighlightTheme {
    type Target = SyntaxColors;

    fn deref(&self) -> &Self::Target {
        &self.style.syntax
    }
}

impl HighlightTheme {
    pub fn default_dark() -> std::sync::Arc<Self> {
        use crate::DEFAULT_THEME_COLORS;
        DEFAULT_THEME_COLORS[&crate::ThemeMode::Dark].1.clone()
    }

    pub fn default_light() -> std::sync::Arc<Self> {
        use crate::DEFAULT_THEME_COLORS;
        DEFAULT_THEME_COLORS[&crate::ThemeMode::Light].1.clone()
    }
}

impl gpui_base::input::HighlightStyleResolver for HighlightTheme {
    fn style(&self, name: &str) -> Option<HighlightStyle> {
        self.style.syntax.style(name)
    }
}

// Language registry stub
pub struct LanguageRegistry {
    languages: Mutex<HashMap<SharedString, GrammarConfig>>,
}

impl LanguageRegistry {
    pub fn singleton() -> &'static LazyLock<LanguageRegistry> {
        static INSTANCE: LazyLock<LanguageRegistry> = LazyLock::new(|| LanguageRegistry {
            languages: Mutex::new(HashMap::new()),
        });
        &INSTANCE
    }

    pub fn register(&self, lang: &str, config: &GrammarConfig) {
        self.languages
            .lock()
            .unwrap()
            .insert(lang.to_string().into(), config.clone());
    }

    pub(crate) fn editing_language_name(&self, name: &str) -> SharedString {
        self.languages
            .lock()
            .unwrap()
            .get_key_value(name)
            .map(|(name, _)| name.clone())
            .unwrap_or_else(|| super::language_name(name))
    }

    pub fn languages(&self) -> Vec<SharedString> {
        self.languages.lock().unwrap().keys().cloned().collect()
    }

    pub fn language(&self, name: &str) -> Option<GrammarConfig> {
        self.languages.lock().unwrap().get(name).cloned()
    }
}

#[cfg(test)]
mod registry_compat_tests {
    use super::*;

    #[test]
    fn registrations_preserve_exact_names_without_alias_fallback() {
        let registry = LanguageRegistry {
            languages: Mutex::new(HashMap::new()),
        };
        registry.register(
            "json",
            &LanguageConfig {
                name: "canonical".into(),
            },
        );
        assert!(registry.language("jsonc").is_none());
        registry.register(
            "jsonc",
            &LanguageConfig {
                name: "custom alias".into(),
            },
        );
        registry.register(
            "JSON",
            &LanguageConfig {
                name: "custom uppercase".into(),
            },
        );
        assert_eq!(registry.language("json").unwrap().name, "canonical");
        assert_eq!(registry.language("jsonc").unwrap().name, "custom alias");
        assert_eq!(registry.language("JSON").unwrap().name, "custom uppercase");
        assert!(registry.language("Json").is_none());
        let mut names = registry.languages();
        names.sort();
        assert_eq!(names, vec!["JSON", "json", "jsonc"]);
        assert_eq!(registry.editing_language_name("jsonc"), "jsonc");
        assert_eq!(registry.editing_language_name("JSON"), "JSON");
        assert_eq!(registry.editing_language_name("pyi"), "python");
    }
}
