//! Language-specific bracket pairing and indentation rules.

use gpui::SharedString;
use regex::Regex;
use std::sync::Arc;

use super::SyntaxContext;

/// A structural pair, used for indentation and splitting Enter between delimiters.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct BracketPair {
    pub open: SharedString,
    pub close: SharedString,
}

impl BracketPair {
    pub fn new(open: impl Into<SharedString>, close: impl Into<SharedString>) -> Self {
        Self {
            open: open.into(),
            close: close.into(),
        }
    }
}

/// An automatic closing pair and the syntax contexts in which insertion is disabled.
/// Empty delimiters are ignored. Strings support delimiters such as `/*` and `*/`.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct AutoClosingPair {
    pub open: SharedString,
    pub close: SharedString,
    pub not_in: Vec<SyntaxContext>,
}

impl AutoClosingPair {
    pub fn new(open: impl Into<SharedString>, close: impl Into<SharedString>) -> Self {
        Self {
            open: open.into(),
            close: close.into(),
            not_in: Vec::new(),
        }
    }

    pub fn not_in(mut self, contexts: impl IntoIterator<Item = SyntaxContext>) -> Self {
        self.not_in = contexts.into_iter().collect();
        self
    }
}

/// Language indentation patterns, using Rust's `regex` syntax.
/// Patterns are compiled by the caller, so invalid expressions are reported at setup.
/// Applied on Enter: increase matches text before the caret; decrease matches text
/// after it. This does not reformat existing lines or indentation on paste.
#[derive(Debug, Clone, Default)]
#[non_exhaustive]
pub struct IndentationRules {
    pub increase_indent_pattern: Option<Arc<Regex>>,
    pub decrease_indent_pattern: Option<Arc<Regex>>,
}

impl IndentationRules {
    pub fn new(increase: Regex, decrease: Regex) -> Self {
        Self {
            increase_indent_pattern: Some(Arc::new(increase)),
            decrease_indent_pattern: Some(Arc::new(decrease)),
        }
    }
}

/// Declarative language editing rules, independent of editor preferences and parsers.
///
/// Mirrors the supported subset of Monaco's language configuration. `None` for
/// `auto_closing_pairs` uses `brackets`; `Some(vec![])` disables all automatic pairs.
/// Use the builders to configure a default value; additional language capabilities
/// can be added without breaking callers. Tree-sitter queries are configured in
/// the parser implementation, not in these rules.
#[derive(Debug, Clone)]
#[non_exhaustive]
pub struct LanguageConfig {
    pub brackets: Vec<BracketPair>,
    pub auto_closing_pairs: Option<Vec<AutoClosingPair>>,
    /// Automatic insertion is allowed before these characters, whitespace, or EOF.
    pub auto_close_before: SharedString,
    pub indentation_rules: Option<IndentationRules>,
}

impl Default for LanguageConfig {
    fn default() -> Self {
        let brackets = vec![
            BracketPair::new("(", ")"),
            BracketPair::new("[", "]"),
            BracketPair::new("{", "}"),
        ];
        let mut pairs: Vec<_> = brackets
            .iter()
            .map(|p| {
                AutoClosingPair::new(p.open.clone(), p.close.clone())
                    .not_in([SyntaxContext::String, SyntaxContext::Comment])
            })
            .collect();
        pairs.extend(
            [
                AutoClosingPair::new("\"", "\""),
                AutoClosingPair::new("'", "'"),
            ]
            .into_iter()
            .map(|p| p.not_in([SyntaxContext::String, SyntaxContext::Comment])),
        );
        Self {
            brackets,
            auto_closing_pairs: Some(pairs),
            auto_close_before: ";:.,=}])>".into(),
            indentation_rules: None,
        }
    }
}

impl LanguageConfig {
    pub fn brackets(mut self, pairs: impl IntoIterator<Item = BracketPair>) -> Self {
        self.brackets = pairs.into_iter().collect();
        self
    }
    pub fn auto_closing_pairs(mut self, pairs: impl IntoIterator<Item = AutoClosingPair>) -> Self {
        self.auto_closing_pairs = Some(pairs.into_iter().collect());
        self
    }
    pub fn auto_close_before(mut self, characters: impl Into<SharedString>) -> Self {
        self.auto_close_before = characters.into();
        self
    }
    pub fn indentation_rules(mut self, rules: IndentationRules) -> Self {
        self.indentation_rules = Some(rules);
        self
    }

    pub(crate) fn closing_pairs(&self) -> impl Iterator<Item = (&str, &str, &[SyntaxContext])> {
        let configured = self
            .auto_closing_pairs
            .as_ref()
            .into_iter()
            .flatten()
            .map(|p| (p.open.as_ref(), p.close.as_ref(), p.not_in.as_slice()));
        let fallback = self
            .brackets
            .iter()
            .filter(|_| self.auto_closing_pairs.is_none())
            .map(|p| (p.open.as_ref(), p.close.as_ref(), &[][..]));
        configured
            .chain(fallback)
            .filter(|(open, close, _)| !open.is_empty() && !close.is_empty())
    }

    pub(crate) fn opens_indent(&self, text: &str) -> bool {
        self.indentation_rules
            .as_ref()
            .and_then(|r| r.increase_indent_pattern.as_ref())
            .map_or_else(
                || {
                    self.brackets
                        .iter()
                        .any(|p| !p.open.is_empty() && text.trim_end().ends_with(p.open.as_ref()))
                },
                |r| r.is_match(text),
            )
    }

    pub(crate) fn closes_indent(&self, text: &str) -> bool {
        self.indentation_rules
            .as_ref()
            .and_then(|r| r.decrease_indent_pattern.as_ref())
            .is_some_and(|r| r.is_match(text))
    }
}
