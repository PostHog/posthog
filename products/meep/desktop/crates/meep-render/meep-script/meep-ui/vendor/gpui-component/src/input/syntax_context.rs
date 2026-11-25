use std::rc::Rc;

#[cfg(feature = "tree-sitter")]
use gpui_base::input::Rope;
use gpui_base::input::SyntaxContextProvider;

/// A syntax-context provider for `language`, or `None` when no grammar is
/// compiled in (unknown language, plain text, or feature disabled).
#[cfg(feature = "tree-sitter")]
pub(crate) fn syntax_context_provider(language: &str) -> Option<Rc<dyn SyntaxContextProvider>> {
    use crate::highlighter::LanguageRegistry;

    let grammar = LanguageRegistry::singleton().grammar(language).ok()?;
    TreeSitterSyntaxContext::new(grammar)
        .map(|provider| Rc::new(provider) as Rc<dyn SyntaxContextProvider>)
}

/// No tree-sitter support: no provider, engine falls back to heuristics.
#[cfg(not(feature = "tree-sitter"))]
pub(crate) fn syntax_context_provider(_language: &str) -> Option<Rc<dyn SyntaxContextProvider>> {
    None
}

/// Tree-sitter backed syntax context for editing decisions.
///
/// Caches the tree for unchanged text and classifies an offset by
/// walking the named node and its ancestors for `string` / `comment` kinds.
/// Generic across grammars: no per-language queries needed for this coarse
/// classification.
#[cfg(feature = "tree-sitter")]
struct TreeSitterSyntaxContext {
    parser: std::cell::RefCell<tree_sitter::Parser>,
    /// The last queried text and its tree, or `None` when that text's parse
    /// ran out of budget. Cloning a `Rope` shares its storage, so the cache
    /// holds no second copy of the document.
    tree: std::cell::RefCell<Option<(Rope, Option<tree_sitter::Tree>)>>,
}

#[cfg(feature = "tree-sitter")]
impl TreeSitterSyntaxContext {
    /// Synchronous parse budget per query; mirrors the highlighter's sync path.
    const PARSE_BUDGET: std::time::Duration = std::time::Duration::from_millis(5);

    fn new(language: tree_sitter::Language) -> Option<Self> {
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).ok()?;
        Some(Self {
            parser: std::cell::RefCell::new(parser),
            tree: std::cell::RefCell::new(None),
        })
    }

    /// Whether the comment starting at `start` opens with `#` or `//`.
    fn starts_line_comment(text: &Rope, start: usize) -> bool {
        match text.get_byte(start) {
            Some(b'#') => true,
            Some(b'/') => text.get_byte(start + 1) == Some(b'/'),
            _ => false,
        }
    }

    fn classify(kind: &str) -> Option<gpui_base::input::SyntaxContext> {
        let lower = kind.to_lowercase();
        if lower == "interpolation" || lower == "template_substitution" {
            Some(gpui_base::input::SyntaxContext::Code)
        } else if lower.contains("comment") {
            Some(gpui_base::input::SyntaxContext::Comment)
        } else if lower.contains("string") {
            Some(gpui_base::input::SyntaxContext::String)
        } else {
            None
        }
    }
}

#[cfg(feature = "tree-sitter")]
impl SyntaxContextProvider for TreeSitterSyntaxContext {
    fn context_at(&self, text: &Rope, offset: usize) -> gpui_base::input::SyntaxContext {
        use std::ops::ControlFlow;

        let offset = offset.min(text.len());
        let mut cached = self.tree.borrow_mut();
        if cached
            .as_ref()
            .is_none_or(|(cached_text, _)| cached_text != text)
        {
            let start = std::time::Instant::now();
            let mut progress = |_: &tree_sitter::ParseState| -> ControlFlow<()> {
                if start.elapsed() > Self::PARSE_BUDGET {
                    ControlFlow::Break(())
                } else {
                    ControlFlow::Continue(())
                }
            };
            let options = tree_sitter::ParseOptions::new().progress_callback(&mut progress);
            let mut parser = self.parser.borrow_mut();
            // No InputEdit is available here, so an old tree cannot be reused
            // after the source changes.
            let tree = parser.parse_with_options(
                &mut |byte_offset, _| crate::highlighter::parse_input_bytes(text, byte_offset),
                None,
                Some(options),
            );
            if tree.is_none() {
                // A timed-out parse must not resume against a different source.
                parser.reset();
            }
            // Remember a timed-out text too, so repeated queries on it answer
            // `Code` at once instead of spending the budget again.
            *cached = Some((text.clone(), tree));
        }
        let Some((_, Some(tree))) = cached.as_ref() else {
            return gpui_base::input::SyntaxContext::Code;
        };
        let mut node = tree.root_node().descendant_for_byte_range(offset, offset);
        // At the very end the range may match nothing; try the last byte.
        if node.is_none() && offset > 0 {
            node = tree
                .root_node()
                .descendant_for_byte_range(offset - 1, offset - 1);
        }
        let mut current = node;
        while let Some(n) = current {
            if n.is_named() {
                if let Some(context) = Self::classify(n.kind()) {
                    // String delimiters delimit the scope: inserting at its start
                    // is outside, while inserting before its end is inside.
                    if context == gpui_base::input::SyntaxContext::String
                        && offset == n.start_byte()
                        && matches!(
                            n.kind(),
                            "string"
                                | "string_literal"
                                | "raw_string_literal"
                                | "template_string"
                                | "string_start"
                        )
                    {
                        return gpui_base::input::SyntaxContext::Code;
                    }
                    return context;
                }
            }
            current = n.parent();
        }
        // A zero-width query at a line comment's end may select the enclosing
        // node. Insertion there still extends the comment, unlike insertion
        // after a block comment's closing delimiter.
        if offset > 0 && !matches!(text.byte(offset - 1), b'\n' | b'\r') {
            let mut previous = tree
                .root_node()
                .descendant_for_byte_range(offset - 1, offset);
            while let Some(node) = previous {
                if node.end_byte() == offset
                    && Self::classify(node.kind()) == Some(gpui_base::input::SyntaxContext::Comment)
                {
                    if node.kind() == "line_comment"
                        || (node.kind() == "comment"
                            && Self::starts_line_comment(text, node.start_byte()))
                    {
                        return gpui_base::input::SyntaxContext::Comment;
                    }
                }
                previous = node.parent();
            }
        }
        gpui_base::input::SyntaxContext::Code
    }
}

#[cfg(all(test, feature = "tree-sitter"))]
mod tests {
    use super::*;

    fn json_provider() -> Rc<dyn SyntaxContextProvider> {
        syntax_context_provider("json").expect("json grammar must be compiled in")
    }

    #[cfg(all(feature = "tree-sitter-python", feature = "tree-sitter-rust"))]
    #[test]
    fn comment_end_tracks_insertion_context() {
        use gpui_base::input::{Rope, SyntaxContext};
        for (language, source, offset, expected) in [
            ("python", "# note", 6, SyntaxContext::Comment),
            ("python", "# note\n", 6, SyntaxContext::Comment),
            ("python", "# note\n", 7, SyntaxContext::Code),
            ("rust", "// note", 7, SyntaxContext::Comment),
            ("rust", "/// note\n", 8, SyntaxContext::Comment),
            ("rust", "/// note\n", 9, SyntaxContext::Code),
            ("rust", "/* note */", 10, SyntaxContext::Code),
        ] {
            let provider = syntax_context_provider(language).unwrap();
            assert_eq!(
                provider.context_at(&Rope::from_str(source), offset),
                expected,
                "{source:?} at {offset}"
            );
        }
    }

    #[cfg(feature = "tree-sitter-cmake")]
    #[test]
    fn closed_bracket_comment_is_not_a_line_comment() {
        use gpui_base::input::{Rope, SyntaxContext};
        let provider = syntax_context_provider("cmake").unwrap();
        let text = Rope::from_str("#[[ note ]]");
        assert_eq!(provider.context_at(&text, text.len()), SyntaxContext::Code);
    }

    #[test]
    fn json_string_content_is_string_context() {
        use gpui_base::input::{Rope, SyntaxContext};

        let provider = json_provider();
        // {"key": "value"} — offset inside "value".
        let text = Rope::from_str(r#"{"key": "value"}"#);
        assert_eq!(
            provider.context_at(&text, 10),
            SyntaxContext::String,
            "inside string literal"
        );
    }

    #[test]
    fn json_punctuation_is_code_context() {
        use gpui_base::input::{Rope, SyntaxContext};

        let provider = json_provider();
        let text = Rope::from_str(r#"{"key": "value"}"#);
        assert_eq!(
            provider.context_at(&text, 0),
            SyntaxContext::Code,
            "opening brace"
        );
        assert_eq!(
            provider.context_at(&text, 7),
            SyntaxContext::Code,
            "colon between pairs"
        );
    }

    #[test]
    fn test_changed_source_matches_fresh_provider() {
        use gpui_base::input::{Rope, SyntaxContext};
        let provider = json_provider();
        let old = Rope::from_str(r#"{"key": "value"}"#);
        assert_eq!(provider.context_at(&old, 10), SyntaxContext::String);
        let new = Rope::from_str(r#"{"key": 1234567}"#);
        let fresh = json_provider().context_at(&new, 10);
        assert_eq!(fresh, SyntaxContext::Code);
        assert_eq!(provider.context_at(&new, 10), fresh);
    }

    #[test]
    fn unknown_language_has_no_provider() {
        assert!(syntax_context_provider("not-a-language").is_none());
    }
}
