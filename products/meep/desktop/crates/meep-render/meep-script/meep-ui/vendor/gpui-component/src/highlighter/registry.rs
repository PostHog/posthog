use gpui::{App, FontWeight, HighlightStyle, Hsla, SharedString};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_repr::{Deserialize_repr, Serialize_repr};
use std::{
    collections::HashMap,
    ops::Deref,
    sync::{
        Arc, LazyLock, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};

use anyhow::Result;

use crate::{ActiveTheme, DEFAULT_THEME_COLORS, ThemeMode, highlighter::languages};

pub(super) const HIGHLIGHT_NAMES: [&str; 41] = [
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanguageConfig {
    pub name: SharedString,
    pub language: Option<tree_sitter::Language>,
    pub injection_languages: Vec<SharedString>,
    pub highlights: SharedString,
    pub injections: SharedString,
    pub locals: SharedString,
}

/// Explicit name for grammar resources; editing rules use `input::language_config::LanguageConfig`.
pub type GrammarConfig = LanguageConfig;

impl LanguageConfig {
    pub fn new(
        name: impl Into<SharedString>,
        language: tree_sitter::Language,
        injection_languages: Vec<SharedString>,
        highlights: &str,
        injections: &str,
        locals: &str,
    ) -> Self {
        Self {
            name: name.into(),
            language: Some(language),
            injection_languages,
            highlights: SharedString::from(highlights.to_string()),
            injections: SharedString::from(injections.to_string()),
            locals: SharedString::from(locals.to_string()),
        }
    }

    /// A plain text language without a grammar, it will never be parsed.
    pub fn plain(name: impl Into<SharedString>) -> Self {
        Self {
            name: name.into(),
            language: None,
            injection_languages: vec![],
            highlights: SharedString::default(),
            injections: SharedString::default(),
            locals: SharedString::default(),
        }
    }

    /// Whether this language has a grammar to parse with.
    pub fn has_grammar(&self) -> bool {
        self.language.is_some()
    }
}

/// Theme for Tree-sitter Highlight
///
/// https://docs.rs/tree-sitter-highlight/0.26.8/tree_sitter_highlight/
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FontStyle {
    Normal,
    Italic,
    Underline,
}

impl From<FontStyle> for gpui::FontStyle {
    fn from(style: FontStyle) -> Self {
        match style {
            FontStyle::Normal => gpui::FontStyle::Normal,
            FontStyle::Italic => gpui::FontStyle::Italic,
            FontStyle::Underline => gpui::FontStyle::Normal,
        }
    }
}

#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq, Serialize_repr, Deserialize_repr, JsonSchema)]
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

impl From<FontWeightContent> for FontWeight {
    fn from(value: FontWeightContent) -> Self {
        match value {
            FontWeightContent::Thin => FontWeight::THIN,
            FontWeightContent::ExtraLight => FontWeight::EXTRA_LIGHT,
            FontWeightContent::Light => FontWeight::LIGHT,
            FontWeightContent::Normal => FontWeight::NORMAL,
            FontWeightContent::Medium => FontWeight::MEDIUM,
            FontWeightContent::Semibold => FontWeight::SEMIBOLD,
            FontWeightContent::Bold => FontWeight::BOLD,
            FontWeightContent::ExtraBold => FontWeight::EXTRA_BOLD,
            FontWeightContent::Black => FontWeight::BLACK,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
pub struct ThemeStyle {
    color: Option<Hsla>,
    font_style: Option<FontStyle>,
    font_weight: Option<FontWeightContent>,
}

impl From<ThemeStyle> for HighlightStyle {
    fn from(style: ThemeStyle) -> Self {
        HighlightStyle {
            color: style.color,
            font_weight: style.font_weight.map(Into::into),
            font_style: style.font_style.map(Into::into),
            ..Default::default()
        }
    }
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
        } else {
            // Fallback `keyword.modifier` to `keyword`
            if name.contains(".") {
                if let Some(prefix) = name.split(".").next() {
                    return self.style(prefix);
                }

                None
            } else {
                None
            }
        }
    }

    #[inline]
    pub fn style_for_index(&self, index: usize) -> Option<HighlightStyle> {
        HIGHLIGHT_NAMES.get(index).and_then(|name| self.style(name))
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
pub struct StatusColors {
    #[serde(rename = "error")]
    error: Option<Hsla>,
    #[serde(rename = "error.background")]
    error_background: Option<Hsla>,
    #[serde(rename = "error.border")]
    error_border: Option<Hsla>,
    #[serde(rename = "warning")]
    warning: Option<Hsla>,
    #[serde(rename = "warning.background")]
    warning_background: Option<Hsla>,
    #[serde(rename = "warning.border")]
    warning_border: Option<Hsla>,
    #[serde(rename = "info")]
    info: Option<Hsla>,
    #[serde(rename = "info.background")]
    info_background: Option<Hsla>,
    #[serde(rename = "info.border")]
    info_border: Option<Hsla>,
    #[serde(rename = "success")]
    success: Option<Hsla>,
    #[serde(rename = "success.background")]
    success_background: Option<Hsla>,
    #[serde(rename = "success.border")]
    success_border: Option<Hsla>,
    #[serde(rename = "hint")]
    hint: Option<Hsla>,
    #[serde(rename = "hint.background")]
    hint_background: Option<Hsla>,
    #[serde(rename = "hint.border")]
    hint_border: Option<Hsla>,
    #[serde(rename = "created")]
    created: Option<Hsla>,
    #[serde(rename = "modified")]
    modified: Option<Hsla>,
    #[serde(rename = "deleted")]
    deleted: Option<Hsla>,
}

impl StatusColors {
    #[inline]
    pub fn error(&self, cx: &App) -> Hsla {
        self.error.unwrap_or(cx.theme().red)
    }

    #[inline]
    pub fn error_background(&self, cx: &App) -> Hsla {
        let bg = cx.theme().background;
        self.error_background
            .unwrap_or(bg.blend(self.error(cx).alpha(0.2)))
    }

    #[inline]
    pub fn error_border(&self, cx: &App) -> Hsla {
        self.error_border.unwrap_or(self.error(cx))
    }

    #[inline]
    pub fn warning(&self, cx: &App) -> Hsla {
        self.warning.unwrap_or(cx.theme().yellow)
    }

    #[inline]
    pub fn warning_background(&self, cx: &App) -> Hsla {
        let bg = cx.theme().background;
        self.warning_background
            .unwrap_or(bg.blend(self.warning(cx).alpha(0.2)))
    }

    #[inline]
    pub fn warning_border(&self, cx: &App) -> Hsla {
        self.warning_border.unwrap_or(self.warning(cx))
    }

    #[inline]
    pub fn info(&self, cx: &App) -> Hsla {
        self.info.unwrap_or(cx.theme().blue)
    }

    #[inline]
    pub fn info_background(&self, cx: &App) -> Hsla {
        let bg = cx.theme().background;
        self.info_background
            .unwrap_or(bg.blend(self.info(cx).alpha(0.2)))
    }

    #[inline]
    pub fn info_border(&self, cx: &App) -> Hsla {
        self.info_border.unwrap_or(self.info(cx))
    }

    #[inline]
    pub fn success(&self, cx: &App) -> Hsla {
        self.success.unwrap_or(cx.theme().green)
    }

    #[inline]
    pub fn success_background(&self, cx: &App) -> Hsla {
        let bg = cx.theme().background;
        self.success_background
            .unwrap_or(bg.blend(self.success(cx).alpha(0.2)))
    }

    #[inline]
    pub fn success_border(&self, cx: &App) -> Hsla {
        self.success_border.unwrap_or(self.success(cx))
    }

    #[inline]
    pub fn hint(&self, cx: &App) -> Hsla {
        self.hint.unwrap_or(cx.theme().cyan)
    }

    #[inline]
    pub fn hint_background(&self, cx: &App) -> Hsla {
        let bg = cx.theme().background;
        self.hint_background
            .unwrap_or(bg.blend(self.hint(cx).alpha(0.2)))
    }

    #[inline]
    pub fn hint_border(&self, cx: &App) -> Hsla {
        self.hint_border.unwrap_or(self.hint(cx))
    }

    /// The color for something new, such as an added file or line in version
    /// control. Uses `success` when the theme has no `created` value.
    #[inline]
    pub fn created(&self, cx: &App) -> Hsla {
        self.created.unwrap_or_else(|| self.success(cx))
    }

    /// The color for something changed, such as a modified line in version
    /// control. Uses `warning` when the theme has no `modified` value.
    #[inline]
    pub fn modified(&self, cx: &App) -> Hsla {
        self.modified.unwrap_or_else(|| self.warning(cx))
    }

    /// The color for something removed, such as a deleted line in version
    /// control. Uses `error` when the theme has no `deleted` value.
    #[inline]
    pub fn deleted(&self, cx: &App) -> Hsla {
        self.deleted.unwrap_or_else(|| self.error(cx))
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct HighlightThemeStyle {
    #[serde(rename = "editor.background")]
    pub editor_background: Option<Hsla>,
    #[serde(rename = "editor.foreground")]
    pub editor_foreground: Option<Hsla>,
    #[serde(rename = "editor.active_line.background")]
    pub editor_active_line: Option<Hsla>,
    #[serde(rename = "editor.line_number")]
    pub editor_line_number: Option<Hsla>,
    #[serde(rename = "editor.active_line_number")]
    pub editor_active_line_number: Option<Hsla>,
    #[serde(rename = "editor.invisible")]
    pub editor_invisible: Option<Hsla>,
    /// Optional background color for the gutter (line-number column).
    /// Falls back to [`Self::editor_background`] when unset.
    #[serde(rename = "editor.gutter.background")]
    pub editor_gutter_background: Option<Hsla>,
    #[serde(flatten)]
    pub status: StatusColors,
    #[serde(rename = "syntax")]
    pub syntax: SyntaxColors,
}

/// Theme for Tree-sitter Highlight from JSON theme file.
///
/// This json is compatible with the Zed theme format.
///
/// https://zed.dev/docs/extensions/languages#syntax-highlighting
#[derive(Debug, Clone, PartialEq, Eq, Hash, JsonSchema, Serialize, Deserialize)]
#[non_exhaustive]
pub struct HighlightTheme {
    pub name: String,
    #[serde(default)]
    pub appearance: ThemeMode,
    pub style: HighlightThemeStyle,
}

impl Deref for HighlightTheme {
    type Target = SyntaxColors;

    fn deref(&self) -> &Self::Target {
        &self.style.syntax
    }
}

impl HighlightTheme {
    pub fn default_dark() -> Arc<Self> {
        DEFAULT_THEME_COLORS[&ThemeMode::Dark].1.clone()
    }

    pub fn default_light() -> Arc<Self> {
        DEFAULT_THEME_COLORS[&ThemeMode::Light].1.clone()
    }
}

impl gpui_base::input::HighlightStyleResolver for HighlightTheme {
    fn style(&self, name: &str) -> Option<HighlightStyle> {
        self.style.syntax.style(name)
    }
}

/// A factory that produces a fresh Tree-sitter parser and grammar for a language.
///
/// Dynamic grammars (for example WASM-compiled parsers loaded at runtime) register
/// a factory here; when the highlighter needs to parse a buffer it prefers the
/// factory over the statically linked grammar.
pub type LanguageParserFactory =
    Arc<dyn Fn() -> Result<(tree_sitter::Parser, tree_sitter::Language)> + Send + Sync>;

/// Registry for code highlighter languages.
pub struct LanguageRegistry {
    languages: Mutex<HashMap<SharedString, GrammarConfig>>,
    parser_factories: Mutex<HashMap<SharedString, LanguageParserFactory>>,
    /// Bumped by every registration; see [`Self::generation`].
    generation: AtomicU64,
}

impl LanguageRegistry {
    /// Returns the singleton instance of the `LanguageRegistry` with default languages and themes.
    pub fn singleton() -> &'static LazyLock<LanguageRegistry> {
        static INSTANCE: LazyLock<LanguageRegistry> = LazyLock::new(|| LanguageRegistry {
            languages: Mutex::new(
                languages::Language::all()
                    .map(|language| (language.name().into(), language.config()))
                    .collect(),
            ),
            parser_factories: Mutex::new(HashMap::new()),
            generation: AtomicU64::new(0),
        });
        &INSTANCE
    }

    /// Registers a new language configuration to the registry.
    pub fn register(&self, lang: &str, config: &GrammarConfig) {
        self.languages
            .lock()
            .unwrap()
            .insert(lang.to_string().into(), config.clone());
        self.generation.fetch_add(1, Ordering::Relaxed);
    }

    /// Registers a parser factory for a dynamically loaded language.
    ///
    /// The factory takes precedence over the language's statically linked grammar
    /// whenever a buffer in that language is parsed.
    pub fn register_parser_factory(&self, lang: &str, factory: LanguageParserFactory) {
        self.parser_factories
            .lock()
            .unwrap()
            .insert(lang.to_string().into(), factory);
        self.generation.fetch_add(1, Ordering::Relaxed);
    }

    /// A counter that changes whenever a language or parser factory is
    /// registered, so caches of highlighted output can tell when a language
    /// they could not resolve before may now resolve.
    pub(crate) fn generation(&self) -> u64 {
        self.generation.load(Ordering::Relaxed)
    }

    /// Returns a fresh parser and grammar for `name`, preferring a registered
    /// parser factory over the statically linked grammar.
    pub(crate) fn parser(
        &self,
        name: &str,
    ) -> Result<(tree_sitter::Parser, tree_sitter::Language)> {
        let config = self
            .language(name)
            .ok_or_else(|| anyhow::anyhow!("language {name:?} is not registered"))?;
        // Bind the clone in its own statement so the guard is dropped before
        // calling the factory. Otherwise a factory that re-enters the registry
        // self-deadlocks on the non-reentrant mutex, every call is serialized
        // behind the factory, and a panicking factory poisons the singleton.
        let factory = self
            .parser_factories
            .lock()
            .unwrap()
            .get(&config.name)
            .cloned();
        if let Some(factory) = factory {
            return factory();
        }

        let language = config
            .language
            .ok_or_else(|| anyhow::anyhow!("language {name:?} has no grammar"))?;
        Ok((tree_sitter::Parser::new(), language))
    }

    /// Returns whether `name` can produce a parser, either through a registered
    /// parser factory or a statically linked grammar.
    pub(crate) fn has_parser(&self, name: &str) -> bool {
        let Some(config) = self.language(name) else {
            return false;
        };

        config.language.is_some()
            || self
                .parser_factories
                .lock()
                .unwrap()
                .contains_key(&config.name)
    }

    /// Returns the grammar for `name`, preferring a registered parser factory.
    pub(crate) fn grammar(&self, name: &str) -> Result<tree_sitter::Language> {
        Ok(self.parser(name)?.1)
    }

    pub(crate) fn editing_language_name(&self, name: &str) -> SharedString {
        self.languages
            .lock()
            .unwrap()
            .get_key_value(name)
            .map(|(name, _)| name.clone())
            .unwrap_or_else(|| super::language_name(name))
    }

    /// Returns a list of all registered language names.
    pub fn languages(&self) -> Vec<SharedString> {
        self.languages.lock().unwrap().keys().cloned().collect()
    }

    /// Returns the language configuration for the given language name.
    pub fn language(&self, name: &str) -> Option<GrammarConfig> {
        let languages = self.languages.lock().unwrap();
        languages.get(name).cloned().or_else(|| {
            languages::Language::from_name(name)
                .and_then(|language| languages.get(language.name()).cloned())
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::highlighter::GrammarConfig;

    #[test]
    fn registrations_preserve_exact_names_before_alias_fallback() {
        let registry = super::LanguageRegistry {
            languages: std::sync::Mutex::new(std::collections::HashMap::new()),
            parser_factories: std::sync::Mutex::new(std::collections::HashMap::new()),
            generation: std::sync::atomic::AtomicU64::new(0),
        };
        registry.register("json", &GrammarConfig::plain("canonical"));
        assert_eq!(registry.language("jsonc").unwrap().name, "canonical");
        registry.register("jsonc", &GrammarConfig::plain("custom alias"));
        registry.register("JSON", &GrammarConfig::plain("custom uppercase"));
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

    #[cfg(not(feature = "tree-sitter-typescript"))]
    #[test]
    fn custom_canonical_registration_does_not_enable_disabled_aliases() {
        let registry = super::LanguageRegistry {
            languages: std::sync::Mutex::new(std::collections::HashMap::new()),
            parser_factories: std::sync::Mutex::new(std::collections::HashMap::new()),
            generation: std::sync::atomic::AtomicU64::new(0),
        };
        registry.register("typescript", &GrammarConfig::plain("typescript"));
        assert!(registry.language("ts").is_none());
        registry.register("ts", &GrammarConfig::plain("custom"));
        assert_eq!(registry.language("ts").unwrap().name, "custom");
    }

    #[test]
    fn public_language_lookup_retains_case_sensitive_aliases() {
        use super::languages::Language;
        assert_eq!(Language::from_str("jsonc"), Language::Json);
        assert_eq!(Language::from_str("JSON"), Language::Plain);
        assert_eq!(Language::from_str("pyi"), Language::Plain);
        #[cfg(feature = "tree-sitter-typescript")]
        {
            assert_eq!(Language::from_str("typescript"), Language::TypeScript);
            assert_eq!(Language::from_str("ts"), Language::TypeScript);
        }
    }

    #[test]
    fn test_registry() {
        use super::LanguageRegistry;
        let registry = LanguageRegistry::singleton();
        registry.register(
            "foo",
            &GrammarConfig::new("foo", tree_sitter_json::LANGUAGE.into(), vec![], "", "", ""),
        );

        assert!(registry.language("foo").is_some());
        assert!(registry.language("json").is_some());
        assert!(registry.language("text").is_some());
        assert!(registry.language("unknown").is_none());

        #[cfg(feature = "tree-sitter-rust")]
        {
            assert!(registry.language("rust").is_some());
            assert!(registry.language("rs").is_some());
        }
        #[cfg(not(feature = "tree-sitter-rust"))]
        {
            assert!(registry.language("rust").is_none());
            assert!(registry.language("rs").is_none());
        }

        #[cfg(feature = "tree-sitter-javascript")]
        {
            assert!(registry.language("javascript").is_some());
            assert!(registry.language("js").is_some());
        }
        #[cfg(not(feature = "tree-sitter-javascript"))]
        {
            assert!(registry.language("javascript").is_none());
            assert!(registry.language("js").is_none());
        }
    }

    #[test]
    fn dynamic_language_uses_registered_parser_factory() {
        use std::sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        };

        use super::LanguageRegistry;

        let registry = LanguageRegistry::singleton();
        let called = Arc::new(AtomicBool::new(false));
        registry.register(
            "__dynamic_json__",
            &GrammarConfig::new(
                "__dynamic_json__",
                tree_sitter_json::LANGUAGE.into(),
                vec![],
                "",
                "",
                "",
            ),
        );
        registry.register_parser_factory("__dynamic_json__", {
            let called = called.clone();
            Arc::new(move || {
                called.store(true, Ordering::Relaxed);
                Ok((
                    tree_sitter::Parser::new(),
                    tree_sitter_json::LANGUAGE.into(),
                ))
            })
        });

        let (_, language) = registry.parser("__dynamic_json__").unwrap();

        assert!(called.load(Ordering::Relaxed));
        assert_eq!(language, tree_sitter_json::LANGUAGE.into());
    }

    #[test]
    fn factory_only_language_highlights_without_static_grammar() {
        use std::sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        };

        use super::LanguageRegistry;
        use crate::highlighter::SyntaxHighlighter;

        let registry = LanguageRegistry::singleton();
        let called = Arc::new(AtomicBool::new(false));
        // No statically linked grammar: `language` is `None`, so the grammar can
        // only come from the registered factory.
        registry.register(
            "__dynamic_factory_only__",
            &GrammarConfig::plain("__dynamic_factory_only__"),
        );
        assert!(
            !registry
                .language("__dynamic_factory_only__")
                .unwrap()
                .has_grammar()
        );
        registry.register_parser_factory("__dynamic_factory_only__", {
            let called = called.clone();
            Arc::new(move || {
                called.store(true, Ordering::Relaxed);
                Ok((
                    tree_sitter::Parser::new(),
                    tree_sitter_json::LANGUAGE.into(),
                ))
            })
        });

        let highlighter = SyntaxHighlighter::new("__dynamic_factory_only__");

        assert!(called.load(Ordering::Relaxed));
        assert_eq!(highlighter.language().as_ref(), "__dynamic_factory_only__");
    }
}
