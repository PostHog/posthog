#[cfg(test)]
use crate::highlighter::HighlightTheme;
use crate::highlighter::LanguageRegistry;

use anyhow::{Context, Result, anyhow};
use gpui::{HighlightStyle, SharedString};
use gpui_base::input::RopeExt as _;
use ropey::{ChunkCursor, Rope};
use std::sync::Arc;
use std::time::{Duration, Instant};
use std::{
    collections::{BTreeSet, HashMap},
    ops::{ControlFlow, Range},
};
use sum_tree::Bias;
use tree_sitter::{
    InputEdit, ParseOptions, Parser, Point, Query, QueryCursor, StreamingIterator, Tree,
};

const MAX_INJECTION_RANGES: usize = 4096;
const MAX_INJECTION_BYTES: usize = 512 * 1024;
const MAX_INJECTION_LANGUAGE_BYTES: usize = 64;
/// Parse attempts, not resulting layers: a failed parse still spends budget.
/// Matches past it keep host highlighting but get no injected tokens.
const MAX_NON_COMBINED_INJECTION_PARSES: usize = 512;
const INJECTION_PARSE_TIMEOUT: Duration = Duration::from_millis(20);

/// A syntax highlighter that supports incremental parsing, multiline text,
/// and caching of highlight results.
#[allow(unused)]
pub struct SyntaxHighlighter {
    language: SharedString,
    query: Option<Query>,
    /// The full injections query. This is used to build injection layers during parsing.
    injections_query: Option<Arc<Query>>,

    locals_pattern_index: usize,
    highlights_pattern_index: usize,
    // highlight_indices: Vec<Option<Highlight>>,
    non_local_variable_patterns: Vec<bool>,
    injection_content_capture_index: Option<u32>,
    injection_language_capture_index: Option<u32>,
    local_scope_capture_index: Option<u32>,
    local_def_capture_index: Option<u32>,
    local_def_value_capture_index: Option<u32>,
    local_ref_capture_index: Option<u32>,

    /// The last parsed source text.
    text: Rope,
    parser: Parser,
    /// The last parsed tree.
    tree: Option<Tree>,

    /// Parsed injection trees.
    /// These are built once in update() and queried multiple times in match_styles().
    injection_layers: Vec<InjectionLayer>,
}

/// A parsed injection layer.
/// Stores the parsed tree and the ranges it covers.
pub(crate) struct InjectionLayer {
    pub(crate) language_name: SharedString,
    highlight_query: Arc<Query>,
    pub(crate) ranges: Vec<tree_sitter::Range>,
    pub(crate) byte_range: Range<usize>,
    pub(crate) tree: Tree,
    /// Whether this layer parses the ranges of every match combined.
    pub(crate) combined: bool,
}

/// Data needed to compute injection layers on a background thread.
pub(crate) struct InjectionParseData {
    pub(crate) query: Arc<Query>,
    pub(crate) content_capture_index: Option<u32>,
    pub(crate) language_capture_index: Option<u32>,
    /// Old injection layers, edited to match the text being parsed, whose
    /// trees are reused as the old trees of the new layers.
    pub(crate) old_layers: Vec<ReusableInjectionLayer>,
}

pub(crate) struct ReusableInjectionLayer {
    pub(crate) language_name: SharedString,
    highlight_query: Arc<Query>,
    pub(crate) ranges: Vec<tree_sitter::Range>,
    pub(crate) tree: Tree,
    pub(crate) combined: bool,
}

impl From<InjectionLayer> for ReusableInjectionLayer {
    fn from(layer: InjectionLayer) -> Self {
        Self {
            language_name: layer.language_name,
            highlight_query: layer.highlight_query,
            ranges: layer.ranges,
            tree: layer.tree,
            combined: layer.combined,
        }
    }
}

struct TextProvider<'a>(&'a Rope);
struct ByteChunks<'a> {
    cursor: ChunkCursor<'a>,
    node_start: usize,
    node_end: usize,
    at_first: bool,
}
impl<'a> tree_sitter::TextProvider<&'a [u8]> for TextProvider<'a> {
    type I = ByteChunks<'a>;

    fn text(&mut self, node: tree_sitter::Node) -> Self::I {
        let range = node.byte_range();
        let cursor = self.0.chunk_cursor_at(range.start);

        ByteChunks {
            cursor,
            node_start: range.start,
            node_end: range.end,
            at_first: true,
        }
    }
}

impl<'a> Iterator for ByteChunks<'a> {
    type Item = &'a [u8];

    fn next(&mut self) -> Option<Self::Item> {
        if !self.at_first {
            if !self.cursor.next() {
                return None;
            }
        }
        self.at_first = false;

        let chunk_byte_start = self.cursor.byte_offset();
        if chunk_byte_start >= self.node_end {
            return None;
        }

        let chunk = self.cursor.chunk().as_bytes();

        // Slice the chunk to only include bytes within the node's range.
        let start_in_chunk = self.node_start.saturating_sub(chunk_byte_start);
        let end_in_chunk = (self.node_end - chunk_byte_start).min(chunk.len());

        if start_in_chunk >= end_in_chunk {
            return None;
        }

        Some(&chunk[start_in_chunk..end_in_chunk])
    }
}

/// Answer a tree-sitter read request at byte `offset`.
///
/// Tree-sitter reads bytes, not chars: a stale tree or stale included ranges
/// can ask for an offset inside a multi-byte character. Slicing `&str` there
/// panics, and a panic inside tree-sitter's `extern "C"` read callback aborts
/// the process, so the chunk is sliced as bytes.
pub(crate) fn parse_input_bytes(text: &Rope, offset: usize) -> &[u8] {
    if offset >= text.len() {
        return &[];
    }

    let (chunk, chunk_byte_ix) = text.chunk(offset);
    &chunk.as_bytes()[offset - chunk_byte_ix..]
}

fn injection_range_len(range: &tree_sitter::Range) -> usize {
    range.end_byte.saturating_sub(range.start_byte)
}

fn injection_ranges_byte_count(ranges: &[tree_sitter::Range]) -> usize {
    ranges.iter().map(injection_range_len).sum()
}

fn bounding_byte_range(ranges: &[tree_sitter::Range]) -> Option<Range<usize>> {
    let start = ranges.iter().map(|r| r.start_byte).min()?;
    let end = ranges.iter().map(|r| r.end_byte).max()?;
    Some(start..end)
}

fn injection_ranges_within_limits(ranges: &[tree_sitter::Range]) -> bool {
    ranges.len() <= MAX_INJECTION_RANGES
        && injection_ranges_byte_count(ranges) <= MAX_INJECTION_BYTES
}

/// Read a captured injection language without ever allocating an unbounded
/// amount of source text. Language identifiers in fenced code blocks are tiny;
/// longer captures cannot name a registered language and are ignored.
///
/// The range comes from a tree that can be stale relative to `text`; one that
/// no longer lands on char boundaries cannot name a language either.
fn captured_injection_language(text: &Rope, range: Range<usize>) -> Option<SharedString> {
    if range.end > text.len()
        || range.start >= range.end
        || range.end.saturating_sub(range.start) > MAX_INJECTION_LANGUAGE_BYTES
        || !text.is_char_boundary(range.start)
        || !text.is_char_boundary(range.end)
    {
        return None;
    }

    let language = text.slice(range).to_string();
    let language = language.trim();
    (!language.is_empty()).then(|| SharedString::from(language.to_string()))
}

/// Combined markdown inline injections are parsed as one tree with
/// `set_included_ranges`. If we include only the inline nodes that contain
/// trigger bytes, the parser sees those ranges as adjacent and can merge a
/// closing backtick from one list item with an opening backtick from the next.
/// Re-inserting the separator bytes between retained inline ranges preserves
/// the original boundaries.
///
/// The separator bytes count against the same `MAX_INJECTION_RANGES` /
/// `MAX_INJECTION_BYTES` budget as the content ranges, so on a very large
/// document the tail ranges may be dropped here even though `push_limited`
/// already admitted them.
fn normalize_combined_injection_ranges(
    language_name: &SharedString,
    ranges: Vec<tree_sitter::Range>,
) -> Vec<tree_sitter::Range> {
    if language_name.as_ref() != "markdown_inline" || ranges.len() <= 1 {
        return ranges;
    }

    let mut normalized = Vec::with_capacity(ranges.len().min(MAX_INJECTION_RANGES));
    let mut byte_count = 0usize;
    let mut previous_range: Option<tree_sitter::Range> = None;

    for range in ranges {
        let mut pending_ranges = Vec::with_capacity(2);
        if let Some(previous) = previous_range {
            if previous.end_byte < range.start_byte {
                pending_ranges.push(tree_sitter::Range {
                    start_byte: previous.end_byte,
                    end_byte: range.start_byte,
                    start_point: previous.end_point,
                    end_point: range.start_point,
                });
            }
        }
        pending_ranges.push(range);

        let pending_len = pending_ranges
            .iter()
            .map(injection_range_len)
            .sum::<usize>();
        if normalized.len().saturating_add(pending_ranges.len()) > MAX_INJECTION_RANGES
            || byte_count.saturating_add(pending_len) > MAX_INJECTION_BYTES
        {
            break;
        }

        byte_count += pending_len;
        normalized.extend(pending_ranges);
        previous_range = Some(range);
    }

    normalized
}

fn should_include_injection_range(
    language_name: &SharedString,
    range: &tree_sitter::Range,
    text: &Rope,
) -> bool {
    if language_name.as_ref() != "markdown_inline" {
        return true;
    }

    markdown_inline_range_has_trigger(text, range.start_byte..range.end_byte)
}

/// Returns whether an inline range contains any byte that could start a
/// Markdown inline construct, so plain prose ranges skip the injected parse.
///
/// The byte set must stay a superset of the trigger characters for every node
/// captured by `languages/markdown_inline/highlights.scm` (emphasis, code
/// spans, links, images, autolinks). If that query gains a construct with a new
/// trigger character (e.g. GFM bare autolinks), add it here or the construct
/// will silently lose highlighting.
///
/// The range comes from a tree that can be stale relative to `text`, so it is
/// clipped to the text's char boundaries before slicing.
fn markdown_inline_range_has_trigger(text: &Rope, range: Range<usize>) -> bool {
    let start = text.clip_offset(range.start, Bias::Left);
    let end = text.clip_offset(range.end, Bias::Right).max(start);
    text.slice(start..end).bytes().any(|byte| {
        matches!(
            byte,
            b'*' | b'_' | b'`' | b'[' | b']' | b'(' | b')' | b'<' | b'>' | b'!' | b'~' | b'$'
        )
    })
}

#[derive(Debug, Default, Clone)]
struct HighlightSummary {
    count: usize,
    start: usize,
    end: usize,
    min_start: usize,
    max_end: usize,
}

/// The highlight item, the range is offset of the token in the tree.
#[derive(Debug, Default, Clone)]
struct HighlightItem {
    /// The byte range of the highlight in the text.
    range: Range<usize>,
    /// The highlight name, like `function`, `string`, `comment`, etc.
    name: SharedString,
}

impl HighlightItem {
    pub fn new(range: Range<usize>, name: impl Into<SharedString>) -> Self {
        Self {
            range,
            name: name.into(),
        }
    }
}

impl sum_tree::Item for HighlightItem {
    type Summary = HighlightSummary;
    fn summary(&self, _cx: &()) -> Self::Summary {
        HighlightSummary {
            count: 1,
            start: self.range.start,
            end: self.range.end,
            min_start: self.range.start,
            max_end: self.range.end,
        }
    }
}

impl sum_tree::Summary for HighlightSummary {
    type Context<'a> = &'a ();
    fn zero(_: Self::Context<'_>) -> Self {
        HighlightSummary {
            count: 0,
            start: usize::MIN,
            end: usize::MAX,
            min_start: usize::MAX,
            max_end: usize::MIN,
        }
    }

    fn add_summary(&mut self, other: &Self, _: Self::Context<'_>) {
        self.min_start = self.min_start.min(other.min_start);
        self.max_end = self.max_end.max(other.max_end);
        self.start = other.start;
        self.end = other.end;
        self.count += other.count;
    }
}

impl<'a> sum_tree::Dimension<'a, HighlightSummary> for usize {
    fn zero(_: &()) -> Self {
        0
    }

    fn add_summary(&mut self, _: &'a HighlightSummary, _: &()) {}
}

impl<'a> sum_tree::Dimension<'a, HighlightSummary> for Range<usize> {
    fn zero(_: &()) -> Self {
        Default::default()
    }

    fn add_summary(&mut self, summary: &'a HighlightSummary, _: &()) {
        self.start = summary.start;
        self.end = summary.end;
    }
}

impl SyntaxHighlighter {
    /// Create a new SyntaxHighlighter for the given language.
    pub fn new(lang: &str) -> Self {
        match Self::build_for_language(&lang) {
            Ok(result) => result,
            Err(err) => {
                tracing::warn!(
                    "SyntaxHighlighter init failed, fallback to use `text`, {}",
                    err
                );
                Self::build_for_language("text").unwrap()
            }
        }
    }

    /// Build an inert highlighter that never parses and creates no styles,
    /// for languages without a grammar.
    fn build_inert(language: SharedString) -> Self {
        Self {
            language,
            query: None,
            injections_query: None,
            locals_pattern_index: 0,
            highlights_pattern_index: 0,
            non_local_variable_patterns: Vec::new(),
            injection_content_capture_index: None,
            injection_language_capture_index: None,
            local_scope_capture_index: None,
            local_def_capture_index: None,
            local_def_value_capture_index: None,
            local_ref_capture_index: None,
            text: Rope::new(),
            parser: Parser::new(),
            tree: None,
            injection_layers: Vec::new(),
        }
    }

    /// Build the highlighter for the given language.
    ///
    /// https://github.com/tree-sitter/tree-sitter/blob/v0.26.8/crates/highlight/src/highlight.rs#L339
    fn build_for_language(lang: &str) -> Result<Self> {
        let Some(config) = LanguageRegistry::singleton().language(&lang) else {
            return Err(anyhow!(
                "language {:?} is not registered in `LanguageRegistry`",
                lang
            ));
        };

        // Languages without a parser (neither a statically linked grammar nor a
        // registered parser factory) default to a highlighter that never parses
        // and creates no styles.
        if !LanguageRegistry::singleton().has_parser(lang) {
            return Ok(Self::build_inert(config.name.clone()));
        }

        let (mut parser, grammar) = LanguageRegistry::singleton().parser(lang)?;
        parser
            .set_language(&grammar)
            .context("parse set_language")?;

        // Concatenate the query strings, keeping track of the start offset of each section.
        let mut query_source = String::new();
        query_source.push_str(&config.injections);
        let locals_query_offset = query_source.len();
        query_source.push_str(&config.locals);
        let highlights_query_offset = query_source.len();
        query_source.push_str(&config.highlights);

        // Construct a single query by concatenating the three query strings, but record the
        // range of pattern indices that belong to each individual string.
        let mut query = Query::new(&grammar, &query_source).context("new query")?;

        let mut locals_pattern_index = 0;
        let mut highlights_pattern_index = 0;
        for i in 0..(query.pattern_count()) {
            let pattern_offset = query.start_byte_for_pattern(i);
            if pattern_offset < highlights_query_offset {
                if pattern_offset < highlights_query_offset {
                    highlights_pattern_index += 1;
                }
                if pattern_offset < locals_query_offset {
                    locals_pattern_index += 1;
                }
            }
        }

        let injections_query = if !config.injections.is_empty() {
            Query::new(&grammar, &config.injections).ok().map(Arc::new)
        } else {
            None
        };

        // Injection layers are computed separately during parsing, so do not
        // emit injection captures from the main highlight query.
        for pattern_index in 0..locals_pattern_index {
            query.disable_pattern(pattern_index);
        }

        // Find all of the highlighting patterns that are disabled for nodes that
        // have been identified as local variables.
        let non_local_variable_patterns = (0..query.pattern_count())
            .map(|i| {
                query
                    .property_predicates(i)
                    .iter()
                    .any(|(prop, positive)| !*positive && prop.key.as_ref() == "local")
            })
            .collect();

        // Store the numeric ids for all of the special captures.
        let injection_content_capture_index = injections_query.as_ref().and_then(|q| {
            q.capture_names()
                .iter()
                .position(|name| *name == "injection.content")
                .map(|i| i as u32)
        });
        let injection_language_capture_index = injections_query.as_ref().and_then(|q| {
            q.capture_names()
                .iter()
                .position(|name| *name == "injection.language")
                .map(|i| i as u32)
        });
        let mut local_def_capture_index = None;
        let mut local_def_value_capture_index = None;
        let mut local_ref_capture_index = None;
        let mut local_scope_capture_index = None;
        for (i, name) in query.capture_names().iter().enumerate() {
            let i = Some(i as u32);
            match *name {
                "local.definition" => local_def_capture_index = i,
                "local.definition-value" => local_def_value_capture_index = i,
                "local.reference" => local_ref_capture_index = i,
                "local.scope" => local_scope_capture_index = i,
                _ => {}
            }
        }

        // let highlight_indices = vec![None; query.capture_names().len()];

        Ok(Self {
            language: config.name.clone(),
            query: Some(query),
            injections_query,

            locals_pattern_index,
            highlights_pattern_index,
            non_local_variable_patterns,
            injection_content_capture_index,
            injection_language_capture_index,
            local_scope_capture_index,
            local_def_capture_index,
            local_def_value_capture_index,
            local_ref_capture_index,
            text: Rope::new(),
            parser,
            tree: None,
            injection_layers: Vec::new(),
        })
    }

    pub fn is_empty(&self) -> bool {
        self.text.len() == 0
    }

    /// Get the parsed tree (if available)
    pub fn tree(&self) -> Option<&Tree> {
        self.tree.as_ref()
    }

    /// Apply only the structural `edit` to the existing tree and update the stored text,
    /// without re-parsing.
    pub fn edit_tree(&mut self, edit: Option<InputEdit>, text: &Rope) {
        if let (Some(edit), Some(tree)) = (edit, self.tree.as_mut()) {
            tree.edit(&edit);
        }
        self.edit_injection_layers(edit.as_ref());
        self.text = text.clone();
    }

    /// Keep the injection layers in step with `edit`, the way `Tree::edit`
    /// keeps a tree, so the next injection pass reuses their trees instead of
    /// parsing every layer after the edit from scratch. Without an edit the
    /// layers no longer describe the text and are dropped.
    fn edit_injection_layers(&mut self, edit: Option<&InputEdit>) {
        let Some(edit) = edit else {
            self.injection_layers.clear();
            return;
        };

        for layer in &mut self.injection_layers {
            layer.tree.edit(edit);
            for range in &mut layer.ranges {
                edit.edit_range(range);
            }
            if let Some(byte_range) = bounding_byte_range(&layer.ranges) {
                layer.byte_range = byte_range;
            }
        }
    }

    /// Returns the language name for this highlighter.
    pub fn language(&self) -> &SharedString {
        &self.language
    }

    /// Returns a reference to the current text.
    pub fn text(&self) -> &Rope {
        &self.text
    }

    /// Highlight the given text, returning a map from byte ranges to highlight captures.
    ///
    /// Uses incremental parsing by `edit` to efficiently update the highlighter's state.
    /// When `timeout` is `Some`, aborts if parsing exceeds the given duration
    /// and returns `false`. On timeout the old tree is preserved so highlighting
    /// still works with stale data, but `self.text` is updated so that the
    /// caller can send the current text to a background parse.
    /// When `timeout` is `None`, parsing runs to completion and always returns `true`.
    pub fn update(
        &mut self,
        edit: Option<InputEdit>,
        text: &Rope,
        timeout: Option<Duration>,
    ) -> bool {
        self.update_edits(edit.as_slice(), text, timeout)
    }

    /// Like [`Self::update`] for several edits, in the order they were applied
    /// to reach `text`: the tree takes every edit, then reparses once. No
    /// edits means the change is unknown, as `None` does for `update`.
    pub(crate) fn update_edits(
        &mut self,
        edits: &[InputEdit],
        text: &Rope,
        timeout: Option<Duration>,
    ) -> bool {
        if self.text.eq(text) {
            return true;
        }

        // If there's no grammar for the language, just update the text.
        if self.parser.language().is_none() {
            self.text = text.clone();
            return true;
        }

        let full_edit;
        let edits = if edits.is_empty() {
            self.edit_injection_layers(None);
            full_edit = [InputEdit {
                start_byte: 0,
                old_end_byte: 0,
                new_end_byte: text.len(),
                start_position: Point::new(0, 0),
                old_end_position: Point::new(0, 0),
                new_end_position: Point::new(0, 0),
            }];
            &full_edit[..]
        } else {
            for edit in edits {
                self.edit_injection_layers(Some(edit));
            }
            edits
        };

        let mut old_tree = self
            .tree
            .take()
            .unwrap_or(self.parser.parse("", None).unwrap());
        for edit in edits {
            old_tree.edit(edit);
        }

        let mut timed_out = false;
        let start = Instant::now();
        let mut progress = |_: &tree_sitter::ParseState| -> ControlFlow<()> {
            let Some(budget) = timeout else {
                return ControlFlow::Continue(());
            };

            if start.elapsed() > budget {
                timed_out = true;
                return ControlFlow::Break(()); // Cancel execution
            }

            ControlFlow::Continue(())
        };

        let options = ParseOptions::new().progress_callback(&mut progress);
        let new_tree = self.parser.parse_with_options(
            &mut move |offset, _| parse_input_bytes(text, offset),
            Some(&old_tree),
            Some(options),
        );

        if timed_out || new_tree.is_none() {
            // Restore the old tree so highlighting continues with stale data.
            self.tree = Some(old_tree);
            self.text = text.clone();
            return false;
        }

        let new_tree = new_tree.unwrap();
        self.tree = Some(new_tree.clone());
        self.text = text.clone();
        self.parse_injection_layers(&new_tree);
        true
    }

    /// Returns the data needed to compute injection layers on a background thread.
    /// Returns `None` if this language has no injections.
    pub(crate) fn injection_parse_data(&self) -> Option<InjectionParseData> {
        let query = self.injections_query.clone()?;
        Some(InjectionParseData {
            query,
            content_capture_index: self.injection_content_capture_index,
            language_capture_index: self.injection_language_capture_index,
            old_layers: self
                .injection_layers
                .iter()
                .map(|layer| ReusableInjectionLayer {
                    language_name: layer.language_name.clone(),
                    highlight_query: layer.highlight_query.clone(),
                    ranges: layer.ranges.clone(),
                    tree: layer.tree.clone(),
                    combined: layer.combined,
                })
                .collect(),
        })
    }

    /// Compute injection layers from a freshly-parsed main tree.
    /// This is pure computation with no side effects and is safe to run on a
    /// background thread.
    pub(crate) fn compute_injection_layers(
        data: InjectionParseData,
        tree: &Tree,
        text: &Rope,
    ) -> Vec<InjectionLayer> {
        struct CombinedRanges {
            ranges: Vec<tree_sitter::Range>,
            byte_count: usize,
        }

        impl CombinedRanges {
            /// Ranges are already filtered by `should_include_injection_range`
            /// before being pushed here; this only enforces the count/byte caps.
            fn push_limited(&mut self, ranges: Vec<tree_sitter::Range>) {
                for range in ranges {
                    if self.ranges.len() >= MAX_INJECTION_RANGES {
                        break;
                    }

                    let range_len = injection_range_len(&range);
                    if self.byte_count.saturating_add(range_len) > MAX_INJECTION_BYTES {
                        break;
                    }

                    self.byte_count += range_len;
                    self.ranges.push(range);
                }
            }
        }

        fn sort_ranges(ranges: &mut [tree_sitter::Range]) {
            ranges.sort_unstable_by(|a, b| {
                a.start_byte
                    .cmp(&b.start_byte)
                    .then_with(|| a.end_byte.cmp(&b.end_byte))
            });
        }

        fn ranges_cache_key(ranges: &[tree_sitter::Range]) -> Vec<(usize, usize)> {
            ranges.iter().map(|r| (r.start_byte, r.end_byte)).collect()
        }

        fn resolve_language(
            language_name: &str,
            query_cache: &mut HashMap<SharedString, Arc<Query>>,
        ) -> Option<(SharedString, Arc<Query>)> {
            let config = LanguageRegistry::singleton().language(language_name)?;
            if let Some(query) = query_cache.get(&config.name) {
                return Some((config.name, query.clone()));
            }

            let grammar = LanguageRegistry::singleton().grammar(language_name).ok()?;
            let query = match Query::new(&grammar, &config.highlights) {
                Ok(query) => Arc::new(query),
                Err(error) => {
                    tracing::error!(
                        "failed to build injection query for {:?}: {:?}",
                        config.name,
                        error
                    );
                    return None;
                }
            };
            query_cache.insert(config.name.clone(), query.clone());
            Some((config.name, query))
        }

        let root_node = tree.root_node();
        let mut cursor = QueryCursor::new();
        let mut matches = cursor.matches(&data.query, root_node, TextProvider(text));

        let mut combined_ranges: HashMap<SharedString, CombinedRanges> = HashMap::new();
        // Old layers were edited along with the text, so a non-combined layer
        // whose content did not change keeps exactly the same ranges.
        let old_layer_trees: HashMap<_, _> = data
            .old_layers
            .iter()
            .filter(|layer| !layer.combined)
            .map(|layer| {
                (
                    (layer.language_name.clone(), ranges_cache_key(&layer.ranges)),
                    &layer.tree,
                )
            })
            .collect();
        // A combined layer spans many matches, so an edit anywhere in them
        // changes its ranges. Tree-sitter accepts an edited old tree whose
        // included ranges differ and reparses only where they changed.
        let old_combined_trees: HashMap<SharedString, &Tree> = data
            .old_layers
            .iter()
            .filter(|layer| layer.combined)
            .map(|layer| (layer.language_name.clone(), &layer.tree))
            .collect();
        // Query objects are relatively expensive. Reuse one Arc per language
        // from the previous parse and compile only languages present in this
        // document, rather than eagerly retaining every registered grammar.
        let mut highlight_queries: HashMap<SharedString, Arc<Query>> = data
            .old_layers
            .iter()
            .map(|layer| (layer.language_name.clone(), layer.highlight_query.clone()))
            .collect();
        // Cache raw names as well as canonical queries. Otherwise every fence with the
        // same info string would lock the registry and clone its language configuration.
        let mut resolved_languages: HashMap<SharedString, Option<(SharedString, Arc<Query>)>> =
            HashMap::new();
        let mut new_layers = Vec::new();
        let mut non_combined_parses = 0usize;
        while let Some(query_match) = matches.next() {
            let mut language_name: Option<SharedString> = None;
            let mut combined = false;
            for prop in data.query.property_settings(query_match.pattern_index) {
                match prop.key.as_ref() {
                    "injection.language" => {
                        language_name = prop
                            .value
                            .as_ref()
                            .map(|v| SharedString::from(v.to_string()));
                    }
                    "injection.combined" => combined = true,
                    _ => {}
                }
            }

            // Skip rather than break, so later combined ranges are still collected.
            if !combined && non_combined_parses >= MAX_NON_COMBINED_INJECTION_PARSES {
                continue;
            }

            if language_name.is_none() {
                language_name = query_match
                    .captures
                    .iter()
                    .find(|cap| Some(cap.index) == data.language_capture_index)
                    .and_then(|capture| {
                        captured_injection_language(text, capture.node.byte_range())
                    });
            }

            let Some(raw_language_name) = language_name else {
                continue;
            };
            let resolved_language =
                if let Some(resolved) = resolved_languages.get(&raw_language_name) {
                    resolved.clone()
                } else {
                    let resolved = resolve_language(&raw_language_name, &mut highlight_queries);
                    resolved_languages.insert(raw_language_name, resolved.clone());
                    resolved
                };
            let Some((language_name, highlight_query)) = resolved_language else {
                continue;
            };

            let mut ranges = query_match
                .captures
                .iter()
                .filter(|cap| Some(cap.index) == data.content_capture_index)
                .map(|capture| capture.node.range())
                .collect::<Vec<_>>();

            if ranges.is_empty() {
                continue;
            }
            ranges.retain(|range| should_include_injection_range(&language_name, range, text));
            if ranges.is_empty() {
                continue;
            }
            sort_ranges(&mut ranges);

            if combined {
                combined_ranges
                    .entry(language_name.clone())
                    .or_insert_with(|| CombinedRanges {
                        ranges: Vec::new(),
                        byte_count: 0,
                    })
                    .push_limited(ranges);
            } else {
                if !injection_ranges_within_limits(&ranges) {
                    continue;
                }

                non_combined_parses += 1;
                let old_tree = old_layer_trees
                    .get(&(language_name.clone(), ranges_cache_key(&ranges)))
                    .copied();
                if let Some(layer) = Self::parse_injection_layer(
                    &language_name,
                    highlight_query,
                    ranges,
                    old_tree,
                    false,
                    text,
                ) {
                    new_layers.push(layer);
                }
            }
        }

        for (language_name, combined) in combined_ranges {
            let mut ranges = combined.ranges;
            if ranges.is_empty() {
                continue;
            }
            sort_ranges(&mut ranges);
            ranges = normalize_combined_injection_ranges(&language_name, ranges);
            if ranges.is_empty() {
                continue;
            }
            let old_tree = old_combined_trees.get(&language_name).copied();
            let Some(highlight_query) = highlight_queries.get(&language_name).cloned() else {
                continue;
            };
            if let Some(layer) = Self::parse_injection_layer(
                &language_name,
                highlight_query,
                ranges,
                old_tree,
                true,
                text,
            ) {
                new_layers.push(layer);
            }
        }
        new_layers.sort_by_key(|layer| layer.byte_range.start);
        new_layers
    }

    /// Parse one injection layer over the given included ranges.
    /// `old_tree`, when given, has been edited to match `text`.
    fn parse_injection_layer(
        language_name: &SharedString,
        highlight_query: Arc<Query>,
        ranges: Vec<tree_sitter::Range>,
        old_tree: Option<&Tree>,
        combined: bool,
        text: &Rope,
    ) -> Option<InjectionLayer> {
        let (mut parser, grammar) = LanguageRegistry::singleton().parser(language_name).ok()?;
        parser.set_language(&grammar).ok()?;
        parser.set_included_ranges(&ranges).ok()?;
        let parse_start = Instant::now();
        let mut timed_out = false;
        let mut progress = |_: &tree_sitter::ParseState| -> ControlFlow<()> {
            if parse_start.elapsed() > INJECTION_PARSE_TIMEOUT {
                timed_out = true;
                ControlFlow::Break(())
            } else {
                ControlFlow::Continue(())
            }
        };
        let options = ParseOptions::new().progress_callback(&mut progress);

        let new_tree = parser.parse_with_options(
            &mut |offset, _| parse_input_bytes(text, offset),
            old_tree,
            Some(options),
        )?;
        if timed_out {
            return None;
        }

        let byte_range = bounding_byte_range(&ranges)?;
        Some(InjectionLayer {
            language_name: language_name.clone(),
            highlight_query,
            ranges,
            byte_range,
            tree: new_tree,
            combined,
        })
    }

    /// Apply a tree that was parsed on a background thread.
    ///
    /// `injection_layers` must also be pre-computed in the background via
    /// [`compute_injection_layers`] to avoid blocking the main thread.
    pub(crate) fn apply_background_tree(
        &mut self,
        tree: Tree,
        text: &Rope,
        injection_layers: Vec<InjectionLayer>,
    ) {
        // Only apply if the text still matches what was parsed.
        if !self.text.eq(text) {
            return;
        }

        self.tree = Some(tree);
        self.injection_layers = injection_layers;
    }

    /// Parse injection layers after the main tree is updated.
    /// pattern: parse once in update, query many times in render.
    fn parse_injection_layers(&mut self, tree: &Tree) {
        let Some(query) = self.injections_query.clone() else {
            self.injection_layers.clear();
            return;
        };
        // The old layers are replaced below, so move them instead of cloning.
        let data = InjectionParseData {
            query,
            content_capture_index: self.injection_content_capture_index,
            language_capture_index: self.injection_language_capture_index,
            old_layers: std::mem::take(&mut self.injection_layers)
                .into_iter()
                .map(ReusableInjectionLayer::from)
                .collect(),
        };
        self.injection_layers = Self::compute_injection_layers(data, tree, &self.text);
    }

    /// Match the visible ranges of nodes in the Tree for highlighting.
    fn match_styles(&self, range: Range<usize>) -> Vec<HighlightItem> {
        let mut highlights = vec![];
        let mut injection_highlights = vec![];
        let Some(tree) = &self.tree else {
            return highlights;
        };

        let Some(query) = &self.query else {
            return highlights;
        };

        let root_node = tree.root_node();
        let source = &self.text;

        // Query pre-parsed injection layers.
        let mut last_layer_start = 0;
        for layer in &self.injection_layers {
            debug_assert!(layer.byte_range.start >= last_layer_start);
            last_layer_start = layer.byte_range.start;

            if layer.byte_range.end <= range.start {
                continue;
            }

            // Layers are sorted by start byte in compute_injection_layers.
            if layer.byte_range.start >= range.end {
                break;
            }

            let query = &layer.highlight_query;

            let mut query_cursor = QueryCursor::new();
            query_cursor.set_byte_range(range.clone());

            let mut matches =
                query_cursor.matches(query, layer.tree.root_node(), TextProvider(&self.text));

            let mut last_end = 0usize;
            while let Some(m) = matches.next() {
                let allow_overlapping_captures = query
                    .property_settings(m.pattern_index)
                    .iter()
                    .any(|prop| prop.key.as_ref() == "highlight.allow-overlap");

                for cap in m.captures {
                    let node_range = cap.node.start_byte()..cap.node.end_byte();

                    if !allow_overlapping_captures && node_range.start < last_end {
                        continue;
                    }

                    if let Some(highlight_name) = query.capture_names().get(cap.index as usize) {
                        if !allow_overlapping_captures {
                            last_end = node_range.end;
                        }
                        injection_highlights.push(HighlightItem::new(
                            node_range,
                            SharedString::from(highlight_name.to_string()),
                        ));
                    }
                }
            }
        }

        let mut query_cursor = QueryCursor::new();
        query_cursor.set_byte_range(range.clone());

        let mut matches = query_cursor.matches(query, root_node, TextProvider(source));

        while let Some(query_match) = matches.next() {
            for cap in query_match.captures {
                let node = cap.node;

                let Some(highlight_name) = query.capture_names().get(cap.index as usize) else {
                    continue;
                };

                let node_range: Range<usize> = node.start_byte()..node.end_byte();
                let highlight_name = SharedString::from(highlight_name.to_string());

                // Merge near range and same highlight name
                let last_item = highlights.last();
                let last_range = last_item.map(|item| &item.range).unwrap_or(&(0..0));
                let last_highlight_name = last_item.map(|item| item.name.clone());

                if last_range == &node_range {
                    // case:
                    // last_range: 213..220, last_highlight_name: Some("property")
                    // last_range: 213..220, last_highlight_name: Some("string")
                    highlights.push(HighlightItem::new(
                        node_range,
                        last_highlight_name.unwrap_or(highlight_name),
                    ));
                } else {
                    highlights.push(HighlightItem::new(node_range, highlight_name.clone()));
                }
            }
        }

        // Injected languages are more specific than the host language. Keep
        // them last so their colors win over broad Markdown captures such as
        // `fenced_code_block @text.literal`.
        highlights.extend(injection_highlights);

        // DO NOT REMOVE THIS PRINT, it's useful for debugging
        // for item in highlights {
        //     println!("item: {:?}", item);
        // }

        highlights
    }

    /// Parses `text` without reusing a tree from unrelated text and returns
    /// every capture in precedence order: later captures override earlier ones.
    ///
    /// Injected languages are skipped: building their layers compiles a query
    /// on every parse, which dominates the cost of many short fragments.
    pub(crate) fn capture_names(&mut self, text: &Rope) -> Vec<(Range<usize>, SharedString)> {
        self.tree = None;
        self.text = Rope::new();
        self.injection_layers.clear();
        let injections_query = self.injections_query.take();
        self.update(None, text, None);
        self.injections_query = injections_query;
        self.match_styles(0..text.len())
            .into_iter()
            .map(|item| (item.range, item.name))
            .collect()
    }

    /// Returns the syntax highlight styles for a range of text.
    ///
    /// The argument `range` is the range of bytes in the text to highlight.
    ///
    /// Returns a vector of tuples where each tuple contains:
    /// - A byte range relative to the text
    /// - The corresponding highlight style for that range
    ///
    /// # Example
    ///
    /// ```no_run
    /// # mod gpui_kit { pub extern crate gpui_component as component; }
    /// use gpui_kit::component::highlighter::{HighlightTheme, SyntaxHighlighter};
    /// use ropey::Rope;
    ///
    /// let code = "fn main() {\n    println!(\"Hello\");\n}";
    /// let rope = Rope::from_str(code);
    /// let mut highlighter = SyntaxHighlighter::new("rust");
    /// highlighter.update(None, &rope, None);
    ///
    /// let theme = HighlightTheme::default_dark();
    /// let range = 0..code.len();
    /// let styles = highlighter.styles(&range, &*theme);
    /// ```
    pub fn styles(
        &self,
        range: &Range<usize>,
        theme: &dyn gpui_base::input::HighlightStyleResolver,
    ) -> Vec<(Range<usize>, HighlightStyle)> {
        let mut styles = vec![];
        let start_offset = range.start;

        let highlights = self.match_styles(range.clone());

        // let mut iter_count = 0;
        for item in highlights {
            // iter_count += 1;
            let node_range = &item.range;
            let name = &item.name;

            // Avoid start larger than end
            let mut node_range = node_range.start.max(range.start)..node_range.end.min(range.end);
            if node_range.start > node_range.end {
                node_range.end = node_range.start;
            }
            // The tree can be stale while a background reparse is pending
            // (sync-parse timeout, or the large-text `edit_tree` path), so
            // node offsets may fall inside multi-byte characters of the
            // current text. Snap to char boundaries — text shaping panics on
            // a mid-char style boundary.
            node_range = self.text.clip_offset(node_range.start, Bias::Left)
                ..self.text.clip_offset(node_range.end, Bias::Right);
            if node_range.is_empty() {
                continue;
            }

            styles.push((node_range, theme.style(name.as_ref()).unwrap_or_default()));
        }

        // If the matched styles is empty, return a default range.
        if styles.len() == 0 {
            return vec![(start_offset..range.end, HighlightStyle::default())];
        }

        let styles = unique_styles(&range, styles);

        // NOTE: DO NOT remove this comment, it is used for debugging.
        // for style in &styles {
        //     println!("---- style: {:?} - {:?}", style.0, style.1.color);
        // }
        // println!("--------------------------------");

        styles
    }
}

/// To merge intersection ranges, let the subsequent range cover
/// the previous overlapping range and split the previous range.
///
/// From:
///
/// AA
///   BBB
///    CCCCC
///      DD
///         EEEE
///
/// To:
///
/// AABCCDDCEEEE
pub(crate) fn unique_styles(
    total_range: &Range<usize>,
    styles: Vec<(Range<usize>, HighlightStyle)>,
) -> Vec<(Range<usize>, HighlightStyle)> {
    let styles: Vec<_> = styles
        .into_iter()
        .filter(|(range, _)| !range.is_empty())
        .collect();

    if styles.is_empty() {
        return styles;
    }

    // Create intervals: (position, is_start, style_index)
    let mut intervals: Vec<(usize, bool, usize)> = Vec::with_capacity(styles.len() * 2 + 2);
    for (i, (range, _)) in styles.iter().enumerate() {
        intervals.push((range.start, true, i));
        intervals.push((range.end, false, i));
    }

    intervals.push((total_range.start, true, usize::MAX));
    intervals.push((total_range.end, false, usize::MAX));

    // Sort by position, with ends before starts at same position
    // This ensures we close ranges before opening new ones at the same position
    intervals.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));

    // Track significant intervals (where style ranges end) for merging decisions
    let mut significant_intervals: BTreeSet<usize> = BTreeSet::new();
    for (range, _) in &styles {
        significant_intervals.insert(range.end);
    }

    let mut result: Vec<(Range<usize>, HighlightStyle)> = Vec::new();
    let mut active_styles: Vec<usize> = Vec::new();
    let mut last_pos = total_range.start;

    for (pos, is_start, style_idx) in intervals {
        // Skip total_range boundaries in active set management
        let is_boundary = style_idx == usize::MAX;

        if pos > last_pos {
            let interval = last_pos..pos;
            let combined_style = if active_styles.is_empty() {
                HighlightStyle::default()
            } else {
                let mut combined = HighlightStyle::default();
                for &idx in &active_styles {
                    merge_highlight_style(&mut combined, &styles[idx].1);
                }
                combined
            };
            result.push((interval, combined_style));
        }

        if !is_boundary {
            if is_start {
                active_styles.push(style_idx);
            } else {
                active_styles.retain(|&i| i != style_idx);
            }
        }

        last_pos = pos;
    }

    // Merge adjacent ranges with the same style, but not across significant boundaries
    let mut merged: Vec<(Range<usize>, HighlightStyle)> = Vec::with_capacity(result.len());
    for (range, style) in result {
        if let Some((last_range, last_style)) = merged.last_mut() {
            if last_range.end == range.start
                && *last_style == style
                && !significant_intervals.contains(&range.start)
            {
                // Merge adjacent ranges with same style, but not across significant boundaries
                last_range.end = range.end;
                continue;
            }
        }
        merged.push((range, style));
    }

    merged
}

/// Merge other style (Other on top)
fn merge_highlight_style(style: &mut HighlightStyle, other: &HighlightStyle) {
    if let Some(color) = other.color {
        style.color = Some(color);
    }
    if let Some(font_weight) = other.font_weight {
        style.font_weight = Some(font_weight);
    }
    if let Some(font_style) = other.font_style {
        style.font_style = Some(font_style);
    }
    if let Some(background_color) = other.background_color {
        style.background_color = Some(background_color);
    }
    if let Some(underline) = other.underline {
        style.underline = Some(underline);
    }
    if let Some(strikethrough) = other.strikethrough {
        style.strikethrough = Some(strikethrough);
    }
    if let Some(fade_out) = other.fade_out {
        style.fade_out = Some(fade_out);
    }
}

#[cfg(test)]
mod tests {
    use gpui::Hsla;

    use super::*;
    use crate::Colorize as _;

    fn color_style(color: Hsla) -> HighlightStyle {
        let mut style = HighlightStyle::default();
        style.color = Some(color);
        style
    }

    #[test]
    fn test_parse_input_bytes_inside_multibyte_char() {
        // Stale trees make tree-sitter read from offsets inside a character;
        // the read callback must return bytes instead of panicking.
        let rope = Rope::from("let s = \"你好\";");
        let start = "let s = \"".len();
        assert_eq!(
            parse_input_bytes(&rope, start + 1),
            &"你好\";".as_bytes()[1..]
        );
        assert_eq!(parse_input_bytes(&rope, rope.len()), b"");
        assert_eq!(parse_input_bytes(&rope, rope.len() + 4), b"");
    }

    #[test]
    fn test_injection_ranges_inside_multibyte_char() {
        // Injection ranges come from a tree that can be stale relative to the
        // text, so they may start or end inside a character (#3315).
        let rope = Rope::from("# 你\n*a*");
        let inside = "# ".len() + 1;

        assert!(!markdown_inline_range_has_trigger(
            &rope,
            inside..inside + 1
        ));
        assert!(markdown_inline_range_has_trigger(&rope, inside..rope.len()));
        assert!(markdown_inline_range_has_trigger(
            &rope,
            inside..rope.len() + 4
        ));
        assert!(!markdown_inline_range_has_trigger(
            &rope,
            rope.len() + 1..rope.len() + 4
        ));

        assert_eq!(captured_injection_language(&rope, inside..rope.len()), None);
        assert_eq!(
            captured_injection_language(&rope, "# ".len()..inside + 2),
            Some("你".into())
        );
    }

    #[test]
    fn test_plain_text_never_parses() {
        // "text" has no grammar, the highlighter shouldn't parse.
        let mut highlighter = SyntaxHighlighter::new("text");
        let rope = Rope::from("hello {\"a\": 1}\nworld");
        assert!(highlighter.update(None, &rope, None));
        assert!(highlighter.tree().is_none());
        assert_eq!(highlighter.text().to_string(), rope.to_string());

        let theme = HighlightTheme::default_dark();
        let styles = highlighter.styles(&(0..rope.len()), theme.as_ref());
        assert_eq!(styles, vec![(0..rope.len(), HighlightStyle::default())]);

        // Unregistered languages fall back to plain text.
        let mut highlighter = SyntaxHighlighter::new("no-such-language");
        assert!(highlighter.update(None, &rope, None));
        assert!(highlighter.tree().is_none());
    }

    /// While a background reparse is pending (sync-parse timeout, or the
    /// large-text `edit_tree` path), `styles()` serves ranges from a stale
    /// tree. Those must still land on char boundaries of the current text,
    /// or text shaping panics on multi-byte characters.
    #[cfg(feature = "tree-sitter-languages")]
    #[test]
    fn test_stale_tree_styles_snap_to_char_boundaries() {
        let mut highlighter = SyntaxHighlighter::new("markdown");
        let old = Rope::from("# hello world\n*emphasis* and `code` here\n");
        assert!(highlighter.update(None, &old, None));
        assert!(highlighter.tree().is_some());

        // Swap the text without reparsing: the tree is now stale and its node
        // offsets point into the middle of the new text's CJK characters.
        let new = Rope::from("# 你好，世界\n你好，*世界* 与 `代码`\n");
        highlighter.edit_tree(None, &new);

        let theme = HighlightTheme::default_dark();
        let styles = highlighter.styles(&(0..new.len()), theme.as_ref());
        assert!(!styles.is_empty());
        for (range, _) in &styles {
            assert!(
                new.is_char_boundary(range.start) && new.is_char_boundary(range.end),
                "style range {range:?} is not on char boundaries of the current text"
            );
        }
    }

    #[cfg(feature = "tree-sitter-languages")]
    fn has_highlight_covering(
        highlights: &[HighlightItem],
        source: &str,
        text: &str,
        highlight_name: &str,
    ) -> bool {
        let start = source.find(text).expect("text should exist in source");
        let end = start + text.len();
        highlights.iter().any(|item| {
            item.name.as_ref() == highlight_name
                && item.range.start <= start
                && item.range.end >= end
        })
    }

    #[track_caller]
    fn assert_unique_styles(
        range: Range<usize>,
        left: Vec<(Range<usize>, HighlightStyle)>,
        right: Vec<(Range<usize>, HighlightStyle)>,
    ) {
        fn color_name(c: Option<Hsla>) -> String {
            match c {
                Some(c) => {
                    if c == gpui::red() {
                        "red".to_string()
                    } else if c == gpui::green() {
                        "green".to_string()
                    } else if c == gpui::blue() {
                        "blue".to_string()
                    } else {
                        c.to_hex()
                    }
                }
                None => "clean".to_string(),
            }
        }

        let left = unique_styles(&range, left);
        if left.len() != right.len() {
            println!("\n---------------------------------------------");
            for (range, style) in left.iter() {
                println!("({:?}, {})", range, color_name(style.color));
            }
            println!("---------------------------------------------");
            panic!("left {} styles, right {} styles", left.len(), right.len());
        }
        for (left, right) in left.into_iter().zip(right) {
            if left.1.color != right.1.color || left.0 != right.0 {
                panic!(
                    "\n left: ({:?}, {})\nright: ({:?}, {})\n",
                    left.0,
                    color_name(left.1.color),
                    right.0,
                    color_name(right.1.color)
                );
            }
        }
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_html_style_injects_css_highlights() {
        let html = r#"<style>
.card { color: #336699; }
</style>
"#;

        let rope = Rope::from_str(html);
        let mut highlighter = SyntaxHighlighter::new("html");
        highlighter.update(None, &rope, None);

        let highlights = highlighter.match_styles(0..html.len());

        assert!(
            has_highlight_covering(&highlights, html, "color", "property"),
            "CSS property names inside style elements should be highlighted"
        );
        assert!(
            has_highlight_covering(&highlights, html, "#336699", "string.special"),
            "CSS color values inside style elements should be highlighted"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_html_script_injects_javascript_highlights() {
        let html = r#"<script>
const answer = 42;
console.log(answer);
</script>
"#;

        let rope = Rope::from_str(html);
        let mut highlighter = SyntaxHighlighter::new("html");
        highlighter.update(None, &rope, None);

        let highlights = highlighter.match_styles(0..html.len());

        assert!(
            has_highlight_covering(&highlights, html, "const", "keyword"),
            "JavaScript keywords inside script elements should be highlighted"
        );
        assert!(
            has_highlight_covering(&highlights, html, "answer", "variable"),
            "JavaScript identifiers inside script elements should be highlighted"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_kotlin_highlights_string_templates() {
        let kotlin = "fun greet(name: String) = \"hi $name, ${name.length}\"\n";

        let rope = Rope::from_str(kotlin);
        let mut highlighter = SyntaxHighlighter::new("kotlin");
        highlighter.update(None, &rope, None);

        let highlights = highlighter.match_styles(0..kotlin.len());

        assert!(
            has_highlight_covering(&highlights, kotlin, "fun", "keyword"),
            "Kotlin keywords should be highlighted"
        );
        assert!(
            has_highlight_covering(&highlights, kotlin, "$", "punctuation.special"),
            "A string template's `$` should be highlighted"
        );
        assert!(
            has_highlight_covering(&highlights, kotlin, "${", "punctuation.special"),
            "A string template's `${{` should be highlighted"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_fenced_code_injects_captured_language() {
        let markdown = "```rs\nfn first() {}\n```\n\n```rust\nfn second() {}\n```\n";
        let rope = Rope::from_str(markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");

        assert!(highlighter.update(None, &rope, None));

        let rust_layers = highlighter
            .injection_layers
            .iter()
            .filter(|layer| layer.language_name.as_ref() == "rust")
            .collect::<Vec<_>>();
        assert_eq!(rust_layers.len(), 2);
        assert!(
            Arc::ptr_eq(
                &rust_layers[0].highlight_query,
                &rust_layers[1].highlight_query
            ),
            "fences using the same canonical language should share one highlight query"
        );

        let highlights = highlighter.match_styles(0..markdown.len());
        for function in ["first", "second"] {
            assert!(
                has_highlight_covering(&highlights, markdown, function, "function"),
                "Rust function {function:?} should be highlighted inside its fence"
            );
        }

        let theme = HighlightTheme::default_dark();
        let styles = highlighter.styles(&(0..markdown.len()), theme.as_ref());
        let keyword_start = markdown.find("fn first").unwrap();
        let keyword_color = theme.style("keyword").and_then(|style| style.color);
        assert!(styles.iter().any(|(range, style)| {
            range.start <= keyword_start
                && range.end >= keyword_start + 2
                && style.color == keyword_color
        }));
    }

    /// Injection layers are edited along with the text and reused as old
    /// trees. Every edit must highlight exactly like a from-scratch parse.
    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_incremental_injection_layers_match_fresh_parse() {
        fn point_at(text: &str, offset: usize) -> Point {
            let before = &text[..offset];
            let row = before.matches('\n').count();
            let column = offset - before.rfind('\n').map_or(0, |ix| ix + 1);
            Point::new(row, column)
        }

        let mut source = String::from(
            "# Title\n\nSome *emphasis* and `code`.\n\n```rust\nfn first() {}\n```\n\n\
             More **bold** text.\n\n```html\n<b>x</b>\n```\n",
        );
        let mut highlighter = SyntaxHighlighter::new("markdown");
        assert!(highlighter.update(None, &Rope::from_str(&source), None));

        let theme = HighlightTheme::default_dark();
        for (target, replacement) in [
            // Before every layer, shifting all of them.
            ("# Title", "# Longer title"),
            // Inside a fence.
            ("fn first", "fn renamed_first"),
            // Inside the combined inline text.
            ("*emphasis*", "*more emphasis*"),
            // Adds a new inline range to the combined layer.
            ("text.", "text with `span`."),
            // Inside the last fence, adding a line.
            ("<b>x</b>", "<i>y</i>\n<b>x</b>"),
            // A deletion before every layer.
            ("# Longer title\n\n", ""),
        ] {
            let start = source.find(target).expect("target should exist in source");
            let end = start + target.len();
            let new_source = format!("{}{}{}", &source[..start], replacement, &source[end..]);
            let new_end = start + replacement.len();
            let edit = InputEdit {
                start_byte: start,
                old_end_byte: end,
                new_end_byte: new_end,
                start_position: point_at(&source, start),
                old_end_position: point_at(&source, end),
                new_end_position: point_at(&new_source, new_end),
            };
            source = new_source;

            let rope = Rope::from_str(&source);
            assert!(highlighter.update(Some(edit), &rope, None));
            let mut fresh = SyntaxHighlighter::new("markdown");
            assert!(fresh.update(None, &rope, None));
            assert_eq!(
                highlighter.styles(&(0..rope.len()), theme.as_ref()),
                fresh.styles(&(0..rope.len()), theme.as_ref()),
                "styles differ after replacing {target:?} with {replacement:?}"
            );
        }
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_unknown_fence_language_does_not_allocate_layer() {
        let markdown = "```not-a-registered-language\nplain content\n```\n";
        let rope = Rope::from_str(markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");

        assert!(highlighter.update(None, &rope, None));
        assert!(
            highlighter
                .injection_layers
                .iter()
                .all(|layer| { layer.language_name.as_ref() != "not-a-registered-language" })
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_fenced_code_highlights_blocks_beyond_previous_limit() {
        const FENCE_COUNT: usize = 384;
        const _: () = assert!(FENCE_COUNT <= MAX_NON_COMBINED_INJECTION_PARSES);
        let markdown = (0..FENCE_COUNT)
            .map(|i| format!("```rust\nfn function_{i}() {{}}\n```\n"))
            .collect::<String>();
        let rope = Rope::from_str(&markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");

        assert!(highlighter.update(None, &rope, None));
        assert_eq!(highlighter.injection_layers.len(), FENCE_COUNT);
        assert!(
            highlighter
                .injection_layers
                .iter()
                .all(|layer| layer.language_name.as_ref() == "rust")
        );

        let highlights = highlighter.match_styles(0..markdown.len());
        assert!(has_highlight_covering(
            &highlights,
            &markdown,
            "function_383",
            "function"
        ));
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_fenced_code_injection_layers_are_bounded() {
        const FENCE_COUNT: usize = MAX_NON_COMBINED_INJECTION_PARSES + 128;
        // The paragraph trails the fences so the combined match is only reached
        // once the non-combined budget is already exhausted.
        let markdown = format!(
            "{}\nparagraph *inline*\n",
            (0..FENCE_COUNT)
                .map(|i| format!("```rust\nfn function_{i}() {{}}\n```\n"))
                .collect::<String>()
        );
        let rope = Rope::from_str(&markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");

        assert!(highlighter.update(None, &rope, None));
        assert_eq!(
            highlighter
                .injection_layers
                .iter()
                .filter(|layer| layer.language_name.as_ref() == "rust")
                .count(),
            MAX_NON_COMBINED_INJECTION_PARSES
        );
        assert!(
            highlighter
                .injection_layers
                .iter()
                .any(|layer| layer.language_name.as_ref() == "markdown_inline"),
            "the non-combined budget should not starve combined injection layers"
        );

        let highlights = highlighter.match_styles(0..markdown.len());
        assert!(has_highlight_covering(
            &highlights,
            &markdown,
            "function_0",
            "function"
        ));
        assert!(
            !has_highlight_covering(
                &highlights,
                &markdown,
                &format!("function_{}", FENCE_COUNT - 1),
                "function"
            ),
            "fences past the budget keep host highlighting but get no injected tokens"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_php_combined_injection_closing_tags() {
        let php_code = r#"<?php
$x = 1;
?>
<html>
<body>
  <h1><?php echo "Hello"; ?></h1>
  <ul>
    <?php foreach ($items as $item): ?>
      <li><?php echo $item; ?></li>
    <?php endforeach; ?>
  </ul>
</body>
</html>
"#;

        let rope = Rope::from_str(php_code);
        let mut highlighter = SyntaxHighlighter::new("php");
        highlighter.update(None, &rope, None);

        let full_range = 0..php_code.len();
        let highlights = highlighter.match_styles(full_range);

        // Verify all closing HTML tags are highlighted
        let closing_tags = ["</h1>", "</li>", "</ul>", "</body>", "</html>"];
        for tag in closing_tags {
            let pos = php_code.find(tag).unwrap();
            let tag_name_start = pos + 2; // after "</"
            let tag_name_end = tag_name_start + tag.len() - 3; // before ">"

            let has_highlight = highlights
                .iter()
                .any(|item| item.range.start <= tag_name_start && item.range.end >= tag_name_end);

            assert!(
                has_highlight,
                "closing tag {} at byte {} should be highlighted",
                tag, pos
            );
        }
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_inline_injection_layers_are_bounded() {
        let markdown = (0..(MAX_INJECTION_RANGES + 1024))
            .map(|i| format!("paragraph {i} *x*\n\n"))
            .collect::<String>();
        let rope = Rope::from_str(markdown.as_str());
        let mut highlighter = SyntaxHighlighter::new("markdown");

        assert!(highlighter.update(None, &rope, None));
        assert!(
            highlighter.injection_layers.len() <= 1,
            "markdown_inline should be combined instead of one layer per inline node"
        );

        if let Some(layer) = highlighter
            .injection_layers
            .iter()
            .find(|layer| layer.language_name.as_ref() == "markdown_inline")
        {
            assert!(layer.ranges.len() <= MAX_INJECTION_RANGES);
            assert!(injection_ranges_byte_count(&layer.ranges) <= MAX_INJECTION_BYTES);
        }

        let plain_markdown = (0..1024)
            .map(|i| format!("paragraph {i} plain\n\n"))
            .collect::<String>();
        let plain_rope = Rope::from_str(plain_markdown.as_str());
        let mut plain_highlighter = SyntaxHighlighter::new("markdown");

        assert!(plain_highlighter.update(None, &plain_rope, None));
        assert!(
            plain_highlighter
                .injection_layers
                .iter()
                .all(|layer| layer.language_name.as_ref() != "markdown_inline"),
            "plain inline ranges should not create markdown_inline injection layers"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_markdown_inline_code_spans_in_list_items() {
        let markdown = "- `one`\n- `two`\n- `three`\n\nLater `four`\n";
        let rope = Rope::from_str(markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");
        highlighter.update(None, &rope, None);

        let highlights = highlighter.match_styles(0..markdown.len());
        for text in ["one", "two", "three", "four"] {
            assert!(
                has_highlight_covering(&highlights, markdown, text, "text.code.span"),
                "{text:?} should be highlighted as a code span"
            );
        }

        let prose_start = markdown.find("Later").unwrap();
        let prose_end = prose_start + "Later".len();
        assert!(
            !highlights.iter().any(|item| {
                item.name.as_ref() == "text.code.span"
                    && item.range.start <= prose_start
                    && item.range.end >= prose_end
            }),
            "plain prose after the list should not be highlighted as a code span"
        );
    }

    #[test]
    #[cfg(feature = "tree-sitter-languages")]
    fn test_highlight_allow_overlap_property_combines_nested_captures() {
        let markdown = "This has **_bold and italic_** and **bold _with_ italic** text.";
        let rope = Rope::from_str(markdown);
        let mut highlighter = SyntaxHighlighter::new("markdown");
        highlighter.update(None, &rope, None);

        let theme = HighlightTheme::default_dark();
        let styles = highlighter.styles(&(0..markdown.len()), theme.as_ref());
        for text in ["bold and italic", "with"] {
            let start = markdown.find(text).unwrap();
            let end = start + text.len();

            assert!(
                styles.iter().any(|(range, style)| {
                    range.start <= start
                        && range.end >= end
                        && style.font_weight == Some(gpui::FontWeight::BOLD)
                        && style.font_style == Some(gpui::FontStyle::Italic)
                }),
                "{text:?} should combine bold and italic styles"
            );
        }

        let highlights = highlighter.match_styles(0..markdown.len());
        let delimiter_start = markdown.find("_with_").unwrap();
        let delimiter_end = delimiter_start + "_".len();

        assert!(
            highlights.iter().any(|item| {
                item.name.as_ref() == "punctuation.delimiter"
                    && item.range.start <= delimiter_start
                    && item.range.end >= delimiter_end
            }),
            "overlap-enabled captures should not hide nested delimiter highlights"
        );
    }

    #[test]
    fn test_unique_styles() {
        let red = color_style(gpui::red());
        let green = color_style(gpui::green());
        let blue = color_style(gpui::blue());
        let clean = HighlightStyle::default();

        assert_unique_styles(
            0..65,
            vec![
                (2..10, clean),
                (2..10, clean),
                (5..11, red),
                (2..6, clean),
                (10..15, green),
                (15..30, clean),
                (29..35, blue),
                (35..40, green),
                (45..60, blue),
            ],
            vec![
                (0..5, clean),
                (5..6, red),
                (6..10, red),
                (10..11, green),
                (11..15, green),
                (15..29, clean),
                (29..30, blue),
                (30..35, blue),
                (35..40, green),
                (40..45, clean),
                (45..60, blue),
                (60..65, clean),
            ],
        );

        assert_unique_styles(
            0..10,
            vec![(2..2, red), (4..6, green)],
            vec![(0..4, clean), (4..6, green), (6..10, clean)],
        );
    }
}
