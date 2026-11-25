//! Syntax highlighting from syntect and bat's syntax collection.
//!
//! The lighter of the two highlighters: about two hundred languages for a few
//! megabytes, where the full tree-sitter set costs tens. It is regex-based and
//! line-oriented, so there is no syntax tree behind it — folding is by braces
//! and editing decisions use the default `Code` context. An application that
//! needs a structural editor enables `tree-sitter` instead.
//!
//! Syntect names what it matched with TextMate scopes (`keyword.control.rust`,
//! `string.quoted.double`). Those are mapped onto the highlight names the
//! theme already defines (`keyword`, `string`), so colors keep following the
//! application's theme rather than a syntect theme.

use std::{
    cell::RefCell, collections::HashMap, ops::Range, rc::Rc, sync::LazyLock, time::Duration,
};

use gpui::{HighlightStyle, SharedString, Task};
use gpui_base::input::{
    EditorState, FoldRange, HighlightStyleResolver, InputEdit, InputHighlighter,
    InputHighlighterFactory,
};
use ropey::Rope;
use syntect::{
    parsing::{ParseState, Scope, ScopeStack, SyntaxReference, SyntaxSet},
    util::LinesWithEndings,
};

/// Deserializing the syntax set takes tens of milliseconds, so it happens once,
/// on the first highlight, and is shared by every highlighter after that.
static SYNTAXES: LazyLock<SyntaxSet> = LazyLock::new(two_face::syntax::extra_newlines);

/// Documents up to this size are reparsed on the keystroke; larger ones keep
/// their shifted highlights until a background parse catches up.
const SYNC_PARSE_MAX_BYTES: usize = 64 * 1024;
const PARSE_DEBOUNCE: Duration = Duration::from_millis(150);

/// Highlight names, ordered and non-overlapping.
type Highlights = Vec<(Range<usize>, &'static str)>;

pub(crate) fn input_highlighter_factory() -> InputHighlighterFactory {
    Rc::new(|language| {
        find_syntax(language)
            .map(|syntax| Box::new(SyntectInputHighlighter::new(language, syntax)) as _)
    })
}

/// Styles for one code block of a text view, or nothing for a language
/// syntect does not know.
pub(crate) fn highlight_code(
    language: &str,
    code: &str,
    resolver: &dyn HighlightStyleResolver,
) -> Vec<(Range<usize>, HighlightStyle)> {
    let Some(syntax) = find_syntax(language) else {
        return Vec::new();
    };
    resolve_styles(&parse(syntax, code), &(0..code.len()), resolver)
}

/// Highlight names for `text`, for presentations that resolve styles later.
pub(crate) fn capture_names(language: &str, text: &str) -> Vec<(Range<usize>, SharedString)> {
    let Some(syntax) = find_syntax(language) else {
        return Vec::new();
    };
    parse(syntax, text)
        .into_iter()
        .map(|(range, name)| (range, SharedString::new_static(name)))
        .collect()
}

/// The syntax for a code fence or editor language name.
///
/// Syntect matches a token against extensions and syntax names. Most of the
/// names the rest of the library uses are already one of those; the few that
/// are not are spelled here the way syntect knows them.
fn find_syntax(language: &str) -> Option<&'static SyntaxReference> {
    let syntaxes = &*SYNTAXES;
    let canonical = super::language_name(language);
    let alias = match canonical.as_ref() {
        "text" => return None,
        "csharp" => "cs",
        "make" => "Makefile",
        "markdown_inline" => "md",
        "embedded_template" | "ejs" => "erb",
        other => other,
    };
    [language, canonical.as_ref(), alias]
        .into_iter()
        .find_map(|token| syntaxes.find_syntax_by_token(token))
        .filter(|syntax| syntax.name != "Plain Text")
}

/// Runs syntect over `text` and keeps the spans that map to a highlight name.
fn parse(syntax: &SyntaxReference, text: &str) -> Highlights {
    let syntaxes = &*SYNTAXES;
    let mut parser = ParseState::new(syntax);
    let mut scopes = ScopeStack::new();
    let mut names = HashMap::<Scope, Option<&'static str>>::new();
    let mut highlights = Highlights::new();
    let mut offset = 0;

    let mut push = |range: Range<usize>, scopes: &ScopeStack, highlights: &mut Highlights| {
        if range.is_empty() {
            return;
        }
        // The innermost scope that names something wins, so the quotes of a
        // string — `punctuation.definition.string` inside `string` — color as
        // the string rather than as punctuation.
        let name = scopes
            .scopes
            .iter()
            .rev()
            .find_map(|scope| *names.entry(*scope).or_insert_with(|| semantic_name(*scope)));
        if let Some(name) = name {
            match highlights.last_mut() {
                Some((last, last_name)) if last.end == range.start && *last_name == name => {
                    last.end = range.end;
                }
                _ => highlights.push((range, name)),
            }
        }
    };

    for line in LinesWithEndings::from(text) {
        // A line syntect cannot parse keeps the scopes it started with; the
        // next line starts over from them rather than losing the document.
        if let Ok(operations) = parser.parse_line(line, syntaxes) {
            let mut cursor = 0;
            for (index, operation) in operations {
                push(offset + cursor..offset + index, &scopes, &mut highlights);
                let _ = scopes.apply(&operation);
                cursor = index;
            }
            push(
                offset + cursor..offset + line.len(),
                &scopes,
                &mut highlights,
            );
        }
        offset += line.len();
    }
    highlights
}

/// The theme's highlight name for a TextMate scope, or `None` to let an
/// enclosing scope decide.
fn semantic_name(scope: Scope) -> Option<&'static str> {
    let scope = scope.build_string();
    let is = |prefix: &str| {
        scope == prefix
            || scope
                .strip_prefix(prefix)
                .is_some_and(|rest| rest.starts_with('.'))
    };

    let name = if is("punctuation.definition.string")
        || is("punctuation.definition.comment")
        || is("invalid")
        || is("meta")
        || is("source")
        || is("text")
    {
        // Delimiters belong to what they delimit; the rest are containers
        // with no color of their own.
        return None;
    } else if is("comment.block.documentation") || is("comment.line.documentation") {
        "comment.doc"
    } else if is("comment") {
        "comment"
    } else if is("constant.character.escape") {
        "string.escape"
    } else if is("string.regexp") {
        "string.regex"
    } else if is("string") {
        "string"
    } else if is("constant.numeric") {
        "number"
    } else if is("constant.language.boolean") {
        "boolean"
    } else if is("constant") || is("support.constant") || is("entity.name.constant") {
        "constant"
    } else if is("keyword.operator") {
        "operator"
    } else if is("keyword.control.import") || is("meta.preprocessor") {
        "preproc"
    } else if is("keyword") || is("storage.modifier") {
        "keyword"
    } else if is("storage.type") {
        // `fn`, `class` and `let` are declarations, `int` and `bool` are types.
        if [
            "class",
            "enum",
            "function",
            "impl",
            "interface",
            "module",
            "namespace",
            "struct",
            "trait",
            "type",
            "let",
            "var",
            "const",
        ]
        .iter()
        .any(|word| scope.contains(word))
        {
            "keyword"
        } else {
            "type"
        }
    } else if is("entity.name.function")
        || is("support.function")
        || is("variable.function")
        || is("meta.function-call")
    {
        "function"
    } else if is("entity.name.type")
        || is("entity.name.class")
        || is("entity.name.struct")
        || is("entity.name.enum")
        || is("entity.name.trait")
        || is("entity.name.interface")
        || is("entity.other.inherited-class")
        || is("support.type")
        || is("support.class")
    {
        "type"
    } else if is("entity.name.tag") {
        "tag"
    } else if is("entity.other.attribute-name") {
        "attribute"
    } else if is("entity.name.label") {
        "label"
    } else if is("entity.name.section") || is("markup.heading") {
        "title"
    } else if is("variable.language") {
        "variable.special"
    } else if is("variable.other.member")
        || is("variable.other.property")
        || is("support.variable.property")
        || is("meta.mapping.key")
    {
        "property"
    } else if is("variable") {
        "variable"
    } else if is("markup.bold") {
        "emphasis.strong"
    } else if is("markup.italic") {
        "emphasis"
    } else if is("markup.underline.link") {
        "link_uri"
    } else if is("markup.raw") {
        "text.literal"
    } else if is("markup.list") {
        "punctuation.list_marker"
    } else if is("punctuation.section") || is("punctuation.definition.block") {
        "punctuation.bracket"
    } else if is("punctuation.separator") || is("punctuation.terminator") {
        "punctuation.delimiter"
    } else if is("punctuation") {
        "punctuation"
    } else {
        return None;
    };
    Some(name)
}

/// Turns the highlights overlapping `range` into gap-free style runs.
///
/// `highlights` is ordered and non-overlapping, so the first candidate is found
/// by binary search instead of scanning the whole document on every frame.
fn resolve_styles(
    highlights: &[(Range<usize>, &'static str)],
    range: &Range<usize>,
    resolver: &dyn HighlightStyleResolver,
) -> Vec<(Range<usize>, HighlightStyle)> {
    let first = highlights.partition_point(|(highlight, _)| highlight.end <= range.start);
    let mut runs = Vec::new();
    let mut cursor = range.start;

    for (highlight, name) in &highlights[first..] {
        if highlight.start >= range.end {
            break;
        }
        let start = highlight.start.max(range.start);
        let end = highlight.end.min(range.end);
        if start >= end || end <= cursor {
            continue;
        }
        if cursor < start {
            runs.push((cursor..start, HighlightStyle::default()));
        }
        runs.push((start..end, resolver.style(name).unwrap_or_default()));
        cursor = end;
    }

    if cursor < range.end {
        runs.push((cursor..range.end, HighlightStyle::default()));
    }
    runs
}

/// Moves the highlights after an edit by its length and drops the ones it
/// touched, so the text that did not change keeps its colors while a
/// background parse catches up.
fn shift(highlights: &mut Highlights, edit: &InputEdit) {
    let delta = edit.new_end_byte as isize - edit.old_end_byte as isize;
    highlights.retain_mut(|(range, _)| {
        if range.end <= edit.start_byte {
            true
        } else if range.start >= edit.old_end_byte {
            range.start = range.start.saturating_add_signed(delta);
            range.end = range.end.saturating_add_signed(delta);
            true
        } else {
            false
        }
    });
}

struct SyntectInputHighlighter {
    language: SharedString,
    syntax: &'static SyntaxReference,
    highlights: Rc<RefCell<Highlights>>,
    folds: Rc<RefCell<Vec<FoldRange>>>,
    parse_task: Option<Task<()>>,
}

impl SyntectInputHighlighter {
    fn new(language: &str, syntax: &'static SyntaxReference) -> Self {
        Self {
            language: language.to_owned().into(),
            syntax,
            highlights: Rc::default(),
            folds: Rc::default(),
            parse_task: None,
        }
    }
}

impl InputHighlighter for SyntectInputHighlighter {
    fn language(&self) -> SharedString {
        self.language.clone()
    }

    fn update(
        &mut self,
        edit: Option<InputEdit>,
        text: &Rope,
        folding: bool,
        window: &mut gpui::Window,
        cx: &mut gpui::Context<EditorState>,
    ) {
        if let Some(edit) = edit {
            shift(&mut self.highlights.borrow_mut(), &edit);
        }

        if text.len() <= SYNC_PARSE_MAX_BYTES {
            // Syntect has no incremental mode: a small document is reparsed
            // whole, which is quicker than any bookkeeping to avoid it.
            self.parse_task = None;
            let text = text.to_string();
            *self.highlights.borrow_mut() = parse(self.syntax, &text);
            *self.folds.borrow_mut() = if folding {
                brace_fold_ranges(&text)
            } else {
                Vec::new()
            };
            return;
        }

        let syntax = self.syntax;
        let highlights = self.highlights.clone();
        let folds = self.folds.clone();
        let text = text.clone();
        // Replacing the task drops the previous one, which cancels a parse
        // still waiting out its debounce.
        self.parse_task = Some(cx.spawn_in(window, async move |entity, cx| {
            cx.background_executor().timer(PARSE_DEBOUNCE).await;
            let (parsed, folded) = cx
                .background_executor()
                .spawn(async move {
                    let text = text.to_string();
                    let folded = if folding {
                        brace_fold_ranges(&text)
                    } else {
                        Vec::new()
                    };
                    (parse(syntax, &text), folded)
                })
                .await;
            *highlights.borrow_mut() = parsed;
            *folds.borrow_mut() = folded.clone();
            let _ = entity.update(cx, |state, cx| {
                state.apply_highlighter_fold_candidates(folded, cx);
            });
        }));
    }

    fn styles(
        &self,
        range: &Range<usize>,
        resolver: &dyn HighlightStyleResolver,
    ) -> Vec<(Range<usize>, HighlightStyle)> {
        resolve_styles(&self.highlights.borrow(), range, resolver)
    }

    fn fold_ranges(&self, _: &Rope) -> Vec<FoldRange> {
        self.folds.borrow().clone()
    }
}

/// Fold candidates from matching braces outside strings and line comments.
///
/// Without a syntax tree this is the structure most languages share; a
/// language that nests by indentation alone gets no candidates.
fn brace_fold_ranges(text: &str) -> Vec<FoldRange> {
    let mut starts = Vec::new();
    let mut ranges = Vec::new();

    for (line_number, line) in text.lines().enumerate() {
        let mut chars = line.chars().peekable();
        let mut quote = None;
        let mut escaped = false;
        while let Some(character) = chars.next() {
            match quote {
                Some(open) => {
                    if escaped {
                        escaped = false;
                    } else if character == '\\' {
                        escaped = true;
                    } else if character == open {
                        quote = None;
                    }
                }
                None => match character {
                    '/' if chars.peek() == Some(&'/') => break,
                    '#' => break,
                    '"' | '\'' | '`' => quote = Some(character),
                    '{' => starts.push(line_number),
                    '}' => {
                        if let Some(start) = starts.pop()
                            && line_number.saturating_sub(start) >= 2
                        {
                            ranges.push(FoldRange::new(start, line_number));
                        }
                    }
                    _ => {}
                },
            }
        }
    }
    ranges.sort_by_key(|range| range.start_line);
    ranges.dedup_by_key(|range| range.start_line);
    ranges
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(language: &str, code: &str) -> Vec<(&'static str, String)> {
        let syntax = find_syntax(language).expect("a known language");
        parse(syntax, code)
            .into_iter()
            .map(|(range, name)| (name, code[range].to_owned()))
            .collect()
    }

    #[test]
    fn common_fence_names_find_a_syntax() {
        for language in [
            "rust",
            "rs",
            "toml",
            "typescript",
            "ts",
            "tsx",
            "javascript",
            "js",
            "python",
            "py",
            "bash",
            "sh",
            "yaml",
            "yml",
            "json",
            "jsonc",
            "markdown",
            "md",
            "go",
            "c",
            "cpp",
            "csharp",
            "java",
            "kotlin",
            "swift",
            "ruby",
            "html",
            "css",
            "sql",
            "diff",
            "make",
            "dockerfile",
            "zig",
            "lua",
            "php",
        ] {
            assert!(
                find_syntax(language).is_some(),
                "`{language}` has no syntax"
            );
        }
        assert!(
            find_syntax("text").is_none(),
            "plain text is not highlighted"
        );
        assert!(find_syntax("no-such-language").is_none());
    }

    #[test]
    fn scopes_map_onto_the_themes_highlight_names() {
        let toml = names(
            "toml",
            "[package]\nname = \"demo\" # the name\nversion = 1\n",
        );
        assert!(
            toml.contains(&("string", "\"demo\"".to_owned())),
            "{toml:?}"
        );
        assert!(
            toml.iter()
                .any(|(name, text)| *name == "comment" && text.contains("the name"))
        );
        assert!(toml.contains(&("number", "1".to_owned())), "{toml:?}");

        let rust = names("rust", "fn main() { let x = 42; }\n");
        assert!(rust.contains(&("keyword", "fn".to_owned())), "{rust:?}");
        assert!(rust.contains(&("function", "main".to_owned())), "{rust:?}");
        assert!(rust.contains(&("number", "42".to_owned())), "{rust:?}");
    }

    #[test]
    fn style_runs_cover_the_range_without_gaps() {
        struct Named;
        impl HighlightStyleResolver for Named {
            fn style(&self, _: &str) -> Option<HighlightStyle> {
                Some(HighlightStyle::default())
            }
        }
        let runs = resolve_styles(&[(2..4, "keyword"), (6..8, "string")], &(0..10), &Named);
        let ranges: Vec<_> = runs.into_iter().map(|(range, _)| range).collect();
        assert_eq!(ranges, vec![0..2, 2..4, 4..6, 6..8, 8..10]);
    }

    #[test]
    fn an_edit_shifts_later_highlights_and_drops_touched_ones() {
        let mut highlights: Highlights =
            vec![(0..2, "keyword"), (4..6, "string"), (8..10, "number")];
        shift(
            &mut highlights,
            &InputEdit {
                start_byte: 5,
                old_end_byte: 5,
                new_end_byte: 8,
                start_position: gpui_base::input::Point::new(0, 0),
                old_end_position: gpui_base::input::Point::new(0, 0),
                new_end_position: gpui_base::input::Point::new(0, 0),
            },
        );
        assert_eq!(highlights, vec![(0..2, "keyword"), (11..13, "number")]);
    }

    #[test]
    fn braces_outside_strings_and_comments_fold() {
        let folds = brace_fold_ranges("fn a() {\n  let s = \"{\";\n  // }\n}\n");
        assert_eq!(folds, vec![FoldRange::new(0, 3)]);
    }
}
