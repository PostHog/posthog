//! Application-supplied highlights over the text a [`TextViewState`] renders,
//! and scrolling one of its ranges into view.
//!
//! Ranges address the rendered text, the string plain copy produces: an
//! application searches [`TextViewState::rendered_text`] and hands the ranges
//! it found back. Each range is split into the text leaves it covers (a
//! paragraph, a heading, a code block, a table cell), which paint it as a
//! background behind their glyphs, so a highlight never changes layout. Text
//! outside every leaf (the separators between blocks and cells, custom blocks,
//! HTML blocks, inline objects) is left unpainted.
//!
//! An application that keeps ranges of the Markdown source instead, such as
//! those [`TextViewState::selected_source_range`] returns, converts them with
//! [`RenderedText::range_for_source`], which reads the source position the
//! parser recorded for each rendered character.
//!
//! [`TextViewState`]: super::TextViewState
//! [`TextViewState::rendered_text`]: super::TextViewState::rendered_text
//! [`TextViewState::selected_source_range`]: super::TextViewState::selected_source_range

#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{
    ops::Range,
    sync::{Arc, Mutex, OnceLock},
    time::Duration,
};
#[cfg(target_family = "wasm")]
use web_time::Instant;

use gpui::{Bounds, EntityId, Hsla, Pixels, SharedString};

use super::{
    document::ParsedDocument,
    node::{BlockNode, Paragraph, SourceSegment},
    stream_fade::{TextLeaf, TextLeafKey, text_leaves},
};

/// A snapshot of the text a [`TextViewState`](super::TextViewState) renders,
/// as of one parse of its content.
///
/// Offsets into it are UTF-8 byte offsets. It is the string plain copy
/// produces: `hello **world**` renders as `hello world`, escapes are
/// resolved, and heading markers and list markers are left out. Blocks end
/// with a newline and table cells are joined with a space; those separators
/// belong to no block, so no highlight paints them.
///
/// Two snapshots are equal when they come from the same view and the same
/// parse. Comparing the current [`rendered_text`] with the one last searched
/// tells an observer of the view whether its content changed, so setting
/// highlights, which notifies the view too, does not start another search.
/// The text itself is only built when it is first read, from the parsed
/// document the snapshot holds on to, so drop a snapshot that is no longer
/// needed rather than keeping it past many changes.
///
/// [`rendered_text`]: super::TextViewState::rendered_text
#[derive(Clone)]
pub struct RenderedText {
    owner: EntityId,
    revision: usize,
    document: ParsedDocument,
    index: Arc<OnceLock<RenderedIndex>>,
}

impl std::fmt::Debug for RenderedText {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RenderedText")
            .field("owner", &self.owner)
            .field("revision", &self.revision)
            .finish_non_exhaustive()
    }
}

impl RenderedText {
    /// The text of `document`, whose index `index` holds once built.
    pub(super) fn new(
        owner: EntityId,
        revision: usize,
        document: ParsedDocument,
        index: Arc<OnceLock<RenderedIndex>>,
    ) -> Self {
        Self {
            owner,
            revision,
            document,
            index,
        }
    }

    /// The rendered text.
    pub fn as_str(&self) -> &str {
        &self.index().text
    }

    /// The length of the rendered text, in bytes.
    pub fn len(&self) -> usize {
        self.index().text.len()
    }

    /// Whether the view renders no text.
    pub fn is_empty(&self) -> bool {
        self.index().text.is_empty()
    }

    /// The source this text was rendered from, whose byte ranges
    /// [`range_for_source`](Self::range_for_source) takes.
    ///
    /// It comes from the same parse as the text, so it trails the text last
    /// given to the view until that text's parse lands. Before converting a
    /// range, check that it indexes this source: while text is streamed in,
    /// this source is a prefix of the text the application holds, and after
    /// [`set_text`](super::TextViewState::set_text) it may be different text.
    pub fn source(&self) -> &str {
        &self.document.source
    }

    /// The range of this text rendered from `source`, a UTF-8 byte range of
    /// [`Self::source`].
    ///
    /// This converts a range of the Markdown source, such as one
    /// [`selected_source_range`] returned or one an application stored with
    /// its own data, into the range a [`RangeHighlight`] takes. A character is
    /// rendered from `source` when any of the source it was rendered from lies
    /// in it: all of `&amp;` for `&`, the `\` and the `*` of `\*`, the whole
    /// source of an inline object for its text. Source that renders nothing,
    /// such as emphasis delimiters, heading and list markers, code fences,
    /// table pipes and link destinations, adds nothing, so `**bold**` and
    /// `bold` give the same range.
    ///
    /// The result is the smallest range holding every character rendered from
    /// `source`. When `source` spans blocks, it also holds the separators
    /// between them, which a highlight leaves unpainted. Text the parser
    /// recorded no source position for, such as the text of inline HTML, is
    /// only included when it lies between characters that are.
    ///
    /// Converting the source range a selection of this text reports gives the
    /// selected range back, widened only to whole characters where several
    /// share their source, like the text of an inline object. The separators
    /// between blocks are rendered from no source, so one at either end of the
    /// selection is left out: Select All gives back everything but the line
    /// break after the last block.
    ///
    /// Returns `None` when `source` is empty, reversed, out of bounds, or not on
    /// a character boundary, or when nothing is rendered from it. HTML views
    /// record no source positions, so they always return `None`.
    ///
    /// [`selected_source_range`]: super::TextViewState::selected_source_range
    pub fn range_for_source(&self, source: Range<usize>) -> Option<Range<usize>> {
        let text = self.source();
        if source.start >= source.end
            || source.end > text.len()
            || !text.is_char_boundary(source.start)
            || !text.is_char_boundary(source.end)
        {
            return None;
        }
        self.index().range_for_source(&source)
    }

    pub(super) fn index(&self) -> &RenderedIndex {
        self.index
            .get_or_init(|| RenderedIndex::new(&self.document))
    }
}

impl PartialEq for RenderedText {
    fn eq(&self, other: &Self) -> bool {
        self.owner == other.owner && self.revision == other.revision
    }
}

impl Eq for RenderedText {}

/// A background painted behind one range of a [`RenderedText`].
///
/// It is painted under the text and under the selection, and never changes
/// layout. Where highlights overlap, the later one paints over the earlier.
#[derive(Clone, Debug, PartialEq)]
pub struct RangeHighlight {
    range: Range<usize>,
    background: Hsla,
}

impl RangeHighlight {
    /// A highlight over `range`, in byte offsets of a [`RenderedText`].
    pub fn new(range: Range<usize>, background: impl Into<Hsla>) -> Self {
        Self {
            range,
            background: background.into(),
        }
    }

    pub fn range(&self) -> Range<usize> {
        self.range.clone()
    }

    pub fn background(&self) -> Hsla {
        self.background
    }
}

/// Why setting range highlights or revealing a range was rejected. Existing
/// highlights and reveals stay unchanged.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum RangeHighlightError {
    /// The view renders HTML, which records no source positions to address
    /// its text by.
    Unsupported,
    /// The range at this index, the highlight's or the one revealed, is
    /// reversed, out of bounds, or not on a character boundary.
    InvalidRange(usize),
}

impl std::fmt::Display for RangeHighlightError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unsupported => f.write_str("HTML views do not support ranges of their text"),
            Self::InvalidRange(ix) => write!(f, "range {ix} is not a range of the text"),
        }
    }
}

impl std::error::Error for RangeHighlightError {}

/// The rendered text of one parsed document, and where each text leaf sits
/// in it.
#[derive(Debug, Default)]
pub(super) struct RenderedIndex {
    text: SharedString,
    /// In document order, so by their position in `text`.
    leaves: Vec<LeafSpan>,
    /// Where the text of each top-level block sits, in document order.
    blocks: Vec<Range<usize>>,
    /// Where the pieces of `text` came from in the source, with `rendered` in
    /// offsets of `text`, in the order of `text`. Text the parser recorded no
    /// source position for is in none.
    source_map: Vec<SourceSegment>,
}

#[derive(Debug)]
struct LeafSpan {
    /// Where the leaf's text sits in the rendered text.
    range: Range<usize>,
    key: TextLeafKey,
    /// Inline objects in the leaf's text, in leaf offsets. They paint as
    /// objects rather than as text, so no highlight paints them.
    objects: Vec<Range<usize>>,
}

impl LeafSpan {
    /// `offset` in the leaf's text, moved out of an inline object onto the
    /// text after it, or before it at the end of the leaf. `None` when the
    /// leaf has no text outside its objects.
    fn text_offset_near(&self, offset: usize) -> Option<usize> {
        let object_at = |offset: usize| self.objects.iter().find(|object| object.contains(&offset));
        let mut after = offset;
        while let Some(object) = object_at(after) {
            after = object.end;
        }
        if after < self.range.len() {
            return Some(after);
        }
        let mut before = offset;
        while let Some(object) = object_at(before) {
            before = object.start.checked_sub(1)?;
        }
        Some(before)
    }
}

impl RenderedIndex {
    pub(super) fn new(document: &ParsedDocument) -> Self {
        let mut builder = IndexBuilder::default();
        let mut blocks = Vec::with_capacity(document.blocks.len());
        for block in document.blocks.iter() {
            let start = builder.text.len();
            builder.push_block(block);
            blocks.push(start..builder.text.len());
        }
        let index = Self {
            text: builder.text.into(),
            leaves: builder.leaves,
            blocks,
            source_map: builder.source_map,
        };
        debug_assert_eq!(index.text.as_ref(), document.text());
        index
    }

    /// The leaf ranges `range` paints over, which are none when it covers no
    /// leaf text, or `None` when it is not a range of the text.
    fn resolve(&self, range: &Range<usize>) -> Option<Vec<(TextLeafKey, Range<usize>)>> {
        if range.start > range.end
            || range.end > self.text.len()
            || !self.text.is_char_boundary(range.start)
            || !self.text.is_char_boundary(range.end)
        {
            return None;
        }

        let first = self
            .leaves
            .partition_point(|leaf| leaf.range.end <= range.start);
        let mut pieces = Vec::new();
        for leaf in &self.leaves[first..] {
            if leaf.range.start >= range.end {
                break;
            }
            let end = range.end.min(leaf.range.end) - leaf.range.start;
            let mut cursor = range.start.max(leaf.range.start) - leaf.range.start;
            for object in &leaf.objects {
                if object.start >= end {
                    break;
                }
                if object.end <= cursor {
                    continue;
                }
                if object.start > cursor {
                    pieces.push((leaf.key, cursor..object.start));
                }
                cursor = object.end;
            }
            if cursor < end {
                pieces.push((leaf.key, cursor..end));
            }
        }
        Some(pieces)
    }

    /// Where `range` starts: the line of the first leaf text it covers, or,
    /// when it covers none, as an empty range does, of the leaf text at its
    /// start or last before it in its top-level block, or else that whole
    /// block. `None` when it is not a range of the text, or there is none.
    fn locate(&self, range: &Range<usize>) -> Option<RevealTarget> {
        if let Some((key, leaf_range)) = self.resolve(range)?.into_iter().next() {
            return Some(RevealTarget::Line {
                key,
                offset: leaf_range.start,
            });
        }
        let block_ix = self
            .blocks
            .partition_point(|block| block.end <= range.start)
            .min(self.blocks.len().checked_sub(1)?);
        let block_start = self.blocks[block_ix].start;
        let ix = self
            .leaves
            .partition_point(|leaf| leaf.range.end <= range.start);
        let leaf_offset = match self.leaves.get(ix) {
            Some(leaf) if leaf.range.contains(&range.start) => {
                Some((leaf, range.start - leaf.range.start))
            }
            // A position after the text of a leaf, on the separators after
            // it or at the end of the text, is on the line of the last
            // character before it in its block.
            _ => ix
                .checked_sub(1)
                .and_then(|ix| self.leaves.get(ix))
                .filter(|leaf| leaf.range.start >= block_start)
                .and_then(|leaf| {
                    let (last, _) = self.text[leaf.range.clone()].char_indices().last()?;
                    Some((leaf, last))
                }),
        };
        if let Some((leaf, offset)) = leaf_offset
            && let Some(offset) = leaf.text_offset_near(offset)
        {
            return Some(RevealTarget::Line {
                key: leaf.key,
                offset,
            });
        }
        Some(RevealTarget::Block { ix: block_ix })
    }

    /// The smallest range of the text holding every character whose source
    /// overlaps `source`, a valid, non-empty range of the source.
    fn range_for_source(&self, source: &Range<usize>) -> Option<Range<usize>> {
        self.source_map
            .iter()
            .filter(|segment| {
                segment.source.start < source.end && segment.source.end > source.start
            })
            .map(|segment| {
                if !segment.linear {
                    return segment.rendered.clone();
                }
                let start = segment.source.start.max(source.start) - segment.source.start;
                let end = segment.source.end.min(source.end) - segment.source.start;
                self.text
                    .floor_char_boundary(segment.rendered.start + start)
                    ..self.text.ceil_char_boundary(segment.rendered.start + end)
            })
            .reduce(|found, range| found.start.min(range.start)..found.end.max(range.end))
    }
}

/// Builds the rendered text the way `BlockNode::text` does, recording each
/// leaf, and where its text came from in the source, as it goes.
#[derive(Default)]
struct IndexBuilder {
    text: String,
    leaves: Vec<LeafSpan>,
    source_map: Vec<SourceSegment>,
}

impl IndexBuilder {
    fn push_block(&mut self, block: &BlockNode) {
        let start = self.text.len();
        match block {
            BlockNode::Root { children, .. } | BlockNode::Blockquote { children, .. } => {
                for child in children {
                    self.push_block(child);
                }
            }
            BlockNode::List { children, .. } | BlockNode::ListItem { children, .. } => {
                for child in children {
                    self.push_block(child);
                }
                return;
            }
            BlockNode::Paragraph(paragraph) => {
                self.push_paragraph(
                    paragraph,
                    paragraph.span.map(|span| TextLeafKey::block(span.start)),
                );
            }
            BlockNode::Heading { children, span, .. } => {
                self.push_paragraph(children, span.map(|span| TextLeafKey::block(span.start)));
            }
            BlockNode::Table(table) => {
                let mut ordinal = 0;
                for row in table.children.iter().filter(|row| !row.children.is_empty()) {
                    for (ix, cell) in row.children.iter().enumerate() {
                        if ix > 0 {
                            self.text.push(' ');
                        }
                        self.push_paragraph(
                            &cell.children,
                            table
                                .span
                                .map(|span| TextLeafKey::table_cell(span.start, ordinal)),
                        );
                        ordinal += 1;
                    }
                    self.text.push('\n');
                }
            }
            BlockNode::CodeBlock(code_block) => {
                let code = code_block.code();
                self.push_source_segments(self.text.len(), &code, &code_block.source_segments);
                self.push_leaf(
                    &code,
                    code_block.span.map(|span| TextLeafKey::block(span.start)),
                    Vec::new(),
                );
            }
            BlockNode::Custom { node, .. } => {
                self.push_object_source(self.text.len(), node.as_text(), node.source_range());
                self.text.push_str(node.as_text());
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown => {}
        }
        if self.text.len() > start {
            self.text.push('\n');
        }
    }

    fn push_paragraph(&mut self, paragraph: &Paragraph, key: Option<TextLeafKey>) {
        let start = self.text.len();
        let mut text = String::new();
        let mut objects = Vec::new();
        for child in &paragraph.children {
            let offset = start + text.len();
            if let Some(custom) = &child.custom {
                objects.push(text.len()..text.len() + child.text.len());
                self.push_object_source(offset, &child.text, custom.source_range());
            } else {
                self.push_source_segments(offset, &child.text, &child.source_segments);
            }
            text.push_str(&child.text);
        }
        self.push_leaf(&text, key, objects);
    }

    /// Records `segments` of `text`, which is about to be pushed at `offset`.
    ///
    /// A segment that is empty or does not address `text` maps nothing and is
    /// left out, so a bad one cannot map a range to text it did not render.
    fn push_source_segments(&mut self, offset: usize, text: &str, segments: &[SourceSegment]) {
        self.source_map.extend(
            segments
                .iter()
                .filter(|segment| {
                    !segment.rendered.is_empty()
                        && !segment.source.is_empty()
                        && segment.rendered.end <= text.len()
                        && text.is_char_boundary(segment.rendered.start)
                        && text.is_char_boundary(segment.rendered.end)
                })
                .map(|segment| SourceSegment {
                    rendered: offset + segment.rendered.start..offset + segment.rendered.end,
                    ..segment.clone()
                }),
        );
    }

    /// Records that all of `text`, an object about to be pushed at `offset`,
    /// was rendered from `source`, which maps only as a whole.
    fn push_object_source(&mut self, offset: usize, text: &str, source: Option<Range<usize>>) {
        if let Some(source) = source {
            self.push_source_segments(
                offset,
                text,
                &[SourceSegment {
                    rendered: 0..text.len(),
                    source,
                    linear: false,
                }],
            );
        }
    }

    fn push_leaf(&mut self, text: &str, key: Option<TextLeafKey>, objects: Vec<Range<usize>>) {
        let start = self.text.len();
        self.text.push_str(text);
        if let Some(key) = key
            && !text.is_empty()
        {
            self.leaves.push(LeafSpan {
                range: start..self.text.len(),
                key,
                objects,
            });
        }
    }
}

/// The last cell and source end of each table row. Collect them once so
/// remapping cells neither rescans a table nor recomputes a row's end.
fn table_row_source_ends(blocks: &[BlockNode], rows: &mut Vec<(TextLeafKey, Option<usize>)>) {
    for block in blocks {
        match block {
            BlockNode::Table(table) => {
                let Some(span) = table.span else {
                    continue;
                };
                let mut cell_count = 0;
                for row in &table.children {
                    if row.children.is_empty() {
                        continue;
                    }
                    cell_count += row.children.len();
                    let end = row
                        .children
                        .iter()
                        .filter_map(|cell| paragraph_source_end(&cell.children))
                        .max();
                    rows.push((TextLeafKey::table_cell(span.start, cell_count - 1), end));
                }
            }
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => table_row_source_ends(children, rows),
            _ => {}
        }
    }
}

/// Where the source of `paragraph`'s text ends, when the parser recorded it.
fn paragraph_source_end(paragraph: &Paragraph) -> Option<usize> {
    paragraph
        .children
        .iter()
        .flat_map(|node| {
            node.source_segments
                .iter()
                .map(|segment| segment.source.end)
                .chain(
                    node.custom
                        .as_ref()
                        .and_then(|custom| custom.source_range())
                        .map(|range| range.end),
                )
        })
        .max()
}

/// The highlights each leaf paints, resolved once when they change so
/// rendering only looks up its leaf.
#[derive(Debug, Default)]
pub(crate) struct RangeHighlightFrame {
    /// Sorted by key. A leaf's backgrounds keep the order the application
    /// gave them in, so a later one paints over an earlier one.
    leaves: Vec<(TextLeafKey, Vec<(Range<usize>, Hsla)>)>,
}

impl RangeHighlightFrame {
    /// Validates `highlights` against `text` and resolves them to leaves.
    pub(super) fn new(
        text: &RenderedText,
        highlights: impl IntoIterator<Item = RangeHighlight>,
    ) -> Result<Option<Self>, RangeHighlightError> {
        let mut pieces = Vec::new();
        for (ix, highlight) in highlights.into_iter().enumerate() {
            let leaf_ranges = text
                .index()
                .resolve(&highlight.range)
                .ok_or(RangeHighlightError::InvalidRange(ix))?;
            pieces.extend(
                leaf_ranges
                    .into_iter()
                    .map(|(key, range)| (key, range, highlight.background)),
            );
        }

        // Stable, so each leaf keeps the application's order.
        pieces.sort_by_key(|(key, _, _)| *key);
        let mut leaves: Vec<(TextLeafKey, Vec<(Range<usize>, Hsla)>)> = Vec::new();
        for (key, range, background) in pieces {
            match leaves.last_mut() {
                Some((last, backgrounds)) if *last == key => backgrounds.push((range, background)),
                _ => leaves.push((key, vec![(range, background)])),
            }
        }
        Ok((!leaves.is_empty()).then_some(Self { leaves }))
    }

    /// The backgrounds of leaf `key`, in its rendered byte space.
    pub(crate) fn backgrounds(&self, key: TextLeafKey) -> &[(Range<usize>, Hsla)] {
        self.leaves
            .binary_search_by_key(&key, |(leaf, _)| *leaf)
            .map_or(&[], |ix| self.leaves[ix].1.as_slice())
    }

    /// The highlights that still describe `new`, the document `remap` maps
    /// the old one to: each follows its leaf as far as the leaf's text is
    /// unchanged, and is dropped with a leaf that is gone.
    pub(super) fn remap(&self, remap: &LeafRemap) -> Option<Self> {
        let mut leaves = self
            .leaves
            .iter()
            .filter_map(|(key, backgrounds)| {
                let (new_key, unchanged) = remap.leaf(*key)?;
                let clipped = backgrounds
                    .iter()
                    .filter(|(range, _)| range.start < unchanged)
                    .map(|(range, background)| (range.start..range.end.min(unchanged), *background))
                    .collect::<Vec<_>>();
                (!clipped.is_empty()).then_some((new_key, clipped))
            })
            .collect::<Vec<_>>();
        // Moving keys keeps their order, but stay safe for the binary search.
        leaves.sort_by_key(|(key, _)| *key);
        (!leaves.is_empty()).then_some(Self { leaves })
    }
}

/// Where the text leaves of one parsed document are found in the document
/// parsed after it.
///
/// A block that starts before the first change of the source is found at the
/// same offset, and one after the last change at an offset moved by the
/// change in length; a block that starts between them is gone. A leaf keeps
/// its text up to where it first differs from before.
pub(super) struct LeafRemap<'a> {
    old_len: usize,
    new_len: usize,
    /// With an append, where the block it parsed again starts: every leaf
    /// before it is unchanged.
    tail_start: Option<usize>,
    unchanged_prefix: usize,
    unchanged_suffix: usize,
    old_leaves: Vec<(TextLeafKey, TextLeaf<'a>)>,
    new_leaves: Vec<(TextLeafKey, TextLeaf<'a>)>,
    /// Sorted by each row's last cell. Unneeded for append-only remapping.
    table_rows: Vec<(TextLeafKey, Option<usize>)>,
}

impl<'a> LeafRemap<'a> {
    /// With `tail_only`, `new` was parsed by appending to `old`, which parses
    /// only the last block of `old` again and keeps the others as they were.
    pub(super) fn new(old: &'a ParsedDocument, new: &'a ParsedDocument, tail_only: bool) -> Self {
        let (old_len, new_len) = (old.source.len(), new.source.len());
        // An append starts after the old source, and parses its last block
        // again, or only the new text when that block has no span.
        let tail_start = tail_only.then(|| {
            old.blocks
                .last()
                .and_then(BlockNode::span)
                .map_or(old_len, |span| span.start)
        });
        let (unchanged_prefix, unchanged_suffix) = if tail_only {
            (old_len, 0)
        } else {
            let prefix = old
                .source
                .bytes()
                .zip(new.source.bytes())
                .take_while(|(old, new)| old == new)
                .count();
            let shorter = old_len.min(new_len);
            if prefix == shorter {
                // One source extends the other, as when text is appended.
                (prefix, 0)
            } else {
                // Where the two overlap, as when a deleted block starts like
                // the block after it, the end wins: the blocks after a change
                // keep following their text rather than their offset.
                let suffix = old
                    .source
                    .bytes()
                    .rev()
                    .zip(new.source.bytes().rev())
                    .take_while(|(old, new)| old == new)
                    .count()
                    .min(shorter);
                (prefix.min(shorter - suffix), suffix)
            }
        };

        fn leaves_from(
            document: &ParsedDocument,
            tail_start: Option<usize>,
        ) -> Vec<(TextLeafKey, TextLeaf<'_>)> {
            let mut leaves = Vec::new();
            for block in document.blocks.iter().rev() {
                if let Some(tail_start) = tail_start
                    && block.span().is_none_or(|span| span.start < tail_start)
                {
                    break;
                }
                text_leaves(block, &mut leaves);
            }
            leaves.sort_by_key(|(key, _)| *key);
            leaves
        }

        let mut table_rows = Vec::new();
        if !tail_only {
            table_row_source_ends(&old.blocks, &mut table_rows);
            table_rows.sort_by_key(|(key, _)| *key);
        }

        Self {
            old_len,
            new_len,
            tail_start,
            unchanged_prefix,
            unchanged_suffix,
            old_leaves: leaves_from(old, tail_start),
            new_leaves: leaves_from(new, tail_start),
            table_rows,
        }
    }

    /// Where leaf `key` is in the new document, and how much of its text is
    /// unchanged, or `None` when it is gone.
    pub(super) fn leaf(&self, key: TextLeafKey) -> Option<(TextLeafKey, usize)> {
        if self
            .tail_start
            .is_some_and(|tail_start| key.block_start() < tail_start)
        {
            return Some((key, usize::MAX));
        }
        let new_key = key.moved_to(self.moved(key.block_start())?);
        let old_leaf = Self::find(&self.old_leaves, key)?;
        // A table's cells are only known by their place in it, so after a
        // change inside the table a cell is the same one only when the source
        // of its whole row ends before that change.
        if key.cell_ix().is_some()
            && key.block_start() < self.unchanged_prefix
            && self.tail_start.is_none()
            && self
                .row_source_end(key)
                .is_none_or(|end| end > self.unchanged_prefix)
        {
            return None;
        }
        let new_leaf = Self::find(&self.new_leaves, new_key)?;
        Some((new_key, new_leaf.common_prefix_len(old_leaf)))
    }

    fn row_source_end(&self, key: TextLeafKey) -> Option<usize> {
        let ix = self.table_rows.partition_point(|(last, _)| *last < key);
        let (last, end) = self.table_rows.get(ix)?;
        if last.block_start() != key.block_start() {
            return None;
        }
        *end
    }

    /// Where the block starting at `start` in the old document starts in the
    /// new one.
    fn moved(&self, start: usize) -> Option<usize> {
        if start < self.unchanged_prefix {
            Some(start)
        } else if start >= self.old_len - self.unchanged_suffix {
            Some(start + self.new_len - self.old_len)
        } else {
            None
        }
    }

    fn find<'b>(
        leaves: &'b [(TextLeafKey, TextLeaf<'a>)],
        key: TextLeafKey,
    ) -> Option<&'b TextLeaf<'a>> {
        let ix = leaves.binary_search_by_key(&key, |(leaf, _)| *leaf).ok()?;
        Some(&leaves[ix].1)
    }
}

#[cfg(test)]
mod tests {
    use std::{ops::Range, sync::Arc};

    use gpui::{EntityId, hsla};

    use super::{LeafRemap, RangeHighlight, RangeHighlightFrame, RenderedText, TextLeafKey};
    use crate::text::{
        document::ParsedDocument,
        format,
        node::{BlockNode, CodeBlock, NodeContext, Paragraph},
    };

    fn parse(markdown: &str) -> ParsedDocument {
        format::markdown::parse(markdown, &mut NodeContext::default()).expect("parse Markdown")
    }

    #[test]
    fn table_row_index_keeps_empty_cells_in_their_row() {
        let source = "| a | b |\n|---|---|\n| é |   |\n|   |   |\n| c | d |\n";
        let document = parse(source);
        let remap = LeafRemap::new(&document, &document, false);
        assert_eq!(remap.table_rows.len(), 4);
        let ends = [Some("b"), Some("é"), None, Some("d")];
        for (row, text) in ends.into_iter().enumerate() {
            let expected = text.map(|text| source.find(text).unwrap() + text.len());
            for column in 0..2 {
                let key = TextLeafKey::table_cell(0, row * 2 + column);
                assert_eq!(remap.row_source_end(key), expected, "{key:?}");
            }
        }
        assert_eq!(remap.row_source_end(TextLeafKey::table_cell(0, 8)), None);
    }

    #[test]
    fn table_row_index_finds_nested_tables_without_crossing_between_them() {
        let source = concat!(
            "| a |\n|---|\n| b |\n\n",
            "> | c |\n> |---|\n> | d |\n\n",
            "- | e |\n  |---|\n  | f |\n",
        );
        let document = parse(source);
        let remap = LeafRemap::new(&document, &document, false);
        assert_eq!(remap.table_rows.len(), 6);
        for (header, body) in [("a", "b"), ("c", "d"), ("e", "f")] {
            let start = source.find(&format!("| {header} |")).unwrap();
            for (cell, text) in [header, body].into_iter().enumerate() {
                let key = TextLeafKey::table_cell(start, cell);
                assert_eq!(
                    remap.row_source_end(key),
                    Some(source.find(text).unwrap() + text.len()),
                );
            }
            assert_eq!(
                remap.row_source_end(TextLeafKey::table_cell(start, 2)),
                None
            );
            assert_eq!(
                remap.row_source_end(TextLeafKey::table_cell(start + 1, 0)),
                None
            );
        }
    }

    #[test]
    fn long_and_wide_tables_remap_highlights_by_whole_rows() {
        for (rows, columns) in [(4096, 1), (2, 1024), (64, 16)] {
            let row = format!("|{}\n", " x |".repeat(columns));
            let separator = format!("|{}\n", "---|".repeat(columns));
            let source = format!("{row}{separator}{}", row.repeat(rows));
            let old = parse(&source);
            let mut changed = source.clone();
            // Even unchanged cells earlier in the edited row must lose their
            // highlights, as must the unchanged rows that follow it.
            let edit = row.len() + separator.len() + row.rfind('x').unwrap();
            changed.replace_range(edit..edit + 1, "y");
            let new = parse(&changed);
            let remap = LeafRemap::new(&old, &new, false);
            assert_eq!(remap.table_rows.len(), rows + 1);
            let frame = RangeHighlightFrame {
                leaves: remap
                    .old_leaves
                    .iter()
                    .map(|(key, _)| (*key, vec![(0..1, hsla(0.15, 1., 0.5, 0.4))]))
                    .collect(),
            };
            assert_eq!(frame.leaves.len(), (rows + 1) * columns);
            let kept = frame.remap(&remap).unwrap();
            assert_eq!(kept.leaves.len(), columns);
            for column in 0..columns {
                assert_eq!(
                    kept.backgrounds(TextLeafKey::table_cell(0, column)),
                    &[(0..1, hsla(0.15, 1., 0.5, 0.4))],
                );
            }
        }
    }

    #[test]
    fn append_remapping_does_not_build_a_table_row_index() {
        let source = "| a |\n|---|\n| b |\n\n| c |\n|---|\n| d |\n";
        let old = parse(source);
        let new = parse(&format!("{source}| e |\n"));
        let remap = LeafRemap::new(&old, &new, true);
        assert!(remap.table_rows.is_empty());
        let first = TextLeafKey::table_cell(0, 0);
        assert_eq!(remap.leaf(first), Some((first, usize::MAX)));
        let last_start = source.find("| c |").unwrap();
        for cell in 0..2 {
            let key = TextLeafKey::table_cell(last_start, cell);
            assert_eq!(remap.leaf(key), Some((key, 1)));
        }
    }

    #[test]
    fn a_position_in_an_inline_object_moves_onto_text() {
        use super::{LeafSpan, TextLeafKey};
        // "ab" then two objects of 2 bytes each, then "cd".
        let leaf = |len: usize| LeafSpan {
            range: 10..10 + len,
            key: TextLeafKey::block(0),
            objects: vec![2..4, 4..6],
        };
        assert_eq!(leaf(8).text_offset_near(1), Some(1));
        // Onto the text after the objects.
        assert_eq!(leaf(8).text_offset_near(3), Some(6));
        assert_eq!(leaf(8).text_offset_near(5), Some(6));
        // At the end of the leaf, onto the text before them.
        assert_eq!(leaf(6).text_offset_near(5), Some(1));
    }

    #[test]
    fn range_highlight_requires_a_background() {
        let color = hsla(0.15, 1., 0.5, 0.4);
        let highlight = RangeHighlight::new(2..5, color);
        assert_eq!(highlight.range(), 2..5);
        assert_eq!(highlight.background(), color);
    }

    fn rendered(document: ParsedDocument) -> RenderedText {
        RenderedText::new(EntityId::from(1), 0, document, Arc::default())
    }

    /// The range of `markdown` holding the `nth` (zero-based) occurrence of
    /// `needle`.
    fn nth(markdown: &str, needle: &str, nth: usize) -> Range<usize> {
        let (start, _) = markdown
            .match_indices(needle)
            .nth(nth)
            .unwrap_or_else(|| panic!("{needle:?} occurs {nth} times in {markdown:?}"));
        start..start + needle.len()
    }

    /// The text rendered from `source` of `markdown`.
    fn converted(markdown: &str, source: Range<usize>) -> Option<String> {
        let text = rendered(parse(markdown));
        let range = text.range_for_source(source)?;
        Some(text.as_str()[range].to_string())
    }

    /// The text rendered from the first occurrence of `needle` in `markdown`.
    fn converted_needle(markdown: &str, needle: &str) -> Option<String> {
        converted(markdown, nth(markdown, needle, 0))
    }

    #[test]
    fn source_rendering_nothing_converts_to_none() {
        for (markdown, needle) in [
            ("# Title", "# "),
            ("hello **world**", "**"),
            ("a ~~b~~ c", "~~"),
            ("- item", "- "),
            ("1. item", "1. "),
            ("- [x] done", "[x] "),
            ("> quote", "> "),
            ("```rust\nlet x\n```", "```rust\n"),
            ("```rust\nlet x\n```", "\n```"),
            ("| a | b |\n|---|---|\n| c | d |", "|---|---|"),
            ("| a | b |\n|---|---|\n| c | d |", " | "),
            (
                "see [docs](https://example.com) now",
                "(https://example.com)",
            ),
            ("a ![alt](image.png) b", "![alt](image.png)"),
            ("a\n\n---\n\nb", "---"),
            (
                "para\n\n[ref]: https://example.com",
                "[ref]: https://example.com",
            ),
        ] {
            assert_eq!(
                converted_needle(markdown, needle),
                None,
                "{needle:?} of {markdown:?}"
            );
        }
    }

    #[test]
    fn delimiters_in_a_range_add_nothing() {
        let markdown = "hello **world** and `code`";
        assert_eq!(
            converted(markdown, 0..markdown.len()).as_deref(),
            Some("hello world and code")
        );
        assert_eq!(
            converted_needle(markdown, "**world**").as_deref(),
            Some("world")
        );
        assert_eq!(
            converted_needle(markdown, "o **wor").as_deref(),
            Some("o wor")
        );
        assert_eq!(
            converted_needle(markdown, "`code`").as_deref(),
            Some("code")
        );
        assert_eq!(
            converted_needle("# **Title**", "# **Title**").as_deref(),
            Some("Title")
        );
        assert_eq!(
            converted_needle("see [the docs](https://x.y) now", "[the docs](https://x.y)")
                .as_deref(),
            Some("the docs")
        );
    }

    #[test]
    fn repeated_text_converts_to_the_occurrence_addressed() {
        let markdown = "foo **foo** foo";
        let text = rendered(parse(markdown));
        assert_eq!(text.as_str(), "foo foo foo\n");
        assert_eq!(text.range_for_source(nth(markdown, "foo", 0)), Some(0..3));
        assert_eq!(text.range_for_source(nth(markdown, "foo", 1)), Some(4..7));
        assert_eq!(text.range_for_source(nth(markdown, "foo", 2)), Some(8..11));
    }

    #[test]
    fn fenced_code_backslashes_convert_individually() {
        let markdown = "```\na\\\\b\n```";
        let text = rendered(parse(markdown));
        assert_eq!(text.range_for_source(5..6), Some(1..2));
        assert_eq!(text.range_for_source(6..7), Some(2..3));
        assert_eq!(text.range_for_source(5..7), Some(1..3));
    }

    #[test]
    fn literal_code_escapes_convert_individually() {
        for (markdown, first, second, rendered_start) in [
            ("`a\\\\b`", 2, 3, 1),
            (r"`a\*b`", 2, 3, 1),
            ("    one\n    a\\\\b", 13, 14, 5),
            ("- ```\n  a\\\\b\n  ```", 9, 10, 1),
            ("> ```\n> a\\\\b\n> ```", 9, 10, 1),
            ("```\na\\*b\n```", 5, 6, 1),
            ("```\na\\\\b\r\n```", 5, 6, 1),
            ("```\na\\\\\nb\n```", 5, 6, 1),
        ] {
            let text = rendered(parse(markdown));
            assert_eq!(
                text.range_for_source(first..first + 1),
                Some(rendered_start..rendered_start + 1),
                "{markdown:?}"
            );
            assert_eq!(
                text.range_for_source(second..second + 1),
                Some(rendered_start + 1..rendered_start + 2),
                "{markdown:?}"
            );
        }
        let text = rendered(parse(r"a\*b"));
        assert_eq!(text.range_for_source(1..2), Some(1..2));
        assert_eq!(text.range_for_source(2..3), Some(1..2));
        let text = rendered(parse("```\na\\\\\nb\n```"));
        assert_eq!(text.range_for_source(7..8), Some(3..4));
        assert_eq!(text.range_for_source(8..9), Some(4..5));
    }

    #[test]
    fn a_character_converts_when_any_of_its_source_is_in_the_range() {
        // `&amp;` renders `&`: its name alone still renders that `&`.
        assert_eq!(converted_needle("a &amp; b", "amp").as_deref(), Some("&"));
        assert_eq!(converted_needle("a &amp; b", "&amp;").as_deref(), Some("&"));
        assert_eq!(
            converted_needle("&#65;&#x42;", "&#x42;").as_deref(),
            Some("B")
        );
        // `\*` renders `*`, from either of its characters.
        assert_eq!(converted_needle(r"a \* b", r"\").as_deref(), Some("*"));
        assert_eq!(converted_needle(r"a \* b", "*").as_deref(), Some("*"));
        // Text after an escape that starts a text node still converts
        // character for character.
        assert_eq!(converted_needle(r"\*abc", "b").as_deref(), Some("b"));
        assert_eq!(converted_needle(r"**\*abc**", "*a").as_deref(), Some("*a"));
        // A soft line break renders a space from the newline.
        assert_eq!(converted_needle("soft\nbreak", "\n").as_deref(), Some(" "));
        assert_eq!(
            converted_needle("soft\r\nbreak", "\r\n").as_deref(),
            Some(" ")
        );
        assert_eq!(
            converted_needle("soft\r\nbreak", "\n").as_deref(),
            Some(" ")
        );
    }

    #[test]
    fn a_decoded_entity_converts_only_as_a_whole() {
        // `&acE;` decodes to `∾̳`, whose two characters take as many bytes
        // as the entity's source, but not character for character.
        let markdown = "a &acE; b";
        let text = rendered(parse(markdown));
        assert_eq!(text.as_str(), "a ∾̳ b\n");
        assert_eq!(converted_needle(markdown, "a").as_deref(), Some("a"));
        assert_eq!(converted_needle(markdown, "b").as_deref(), Some("b"));
        assert_eq!(converted_needle(markdown, "cE").as_deref(), Some("∾̳"));
        assert_eq!(converted_needle(markdown, "&acE;").as_deref(), Some("∾̳"));
        assert_eq!(converted_needle(markdown, "a &a").as_deref(), Some("a ∾̳"));
    }

    #[test]
    fn multibyte_text_converts_on_character_boundaries() {
        let markdown = "中文 **粗体** 🎉 é";
        assert_eq!(converted_needle(markdown, "粗").as_deref(), Some("粗"));
        assert_eq!(
            converted_needle(markdown, "文 **粗").as_deref(),
            Some("文 粗")
        );
        assert_eq!(converted_needle(markdown, "🎉").as_deref(), Some("🎉"));
        assert_eq!(converted_needle(markdown, "é").as_deref(), Some("é"));
        // A range splitting a character is not a range of the source.
        let split = nth(markdown, "粗", 0);
        assert_eq!(converted(markdown, split.start..split.start + 1), None);
        assert_eq!(converted(markdown, split.start + 1..split.end), None);
    }

    #[test]
    fn ranges_that_are_not_ranges_of_the_source_convert_to_none() {
        let text = rendered(parse("hello world"));
        assert_eq!(text.range_for_source(3..3), None);
        assert_eq!(text.range_for_source(Range { start: 5, end: 3 }), None);
        assert_eq!(text.range_for_source(0..12), None);
        assert_eq!(text.range_for_source(20..30), None);
        assert_eq!(text.range_for_source(0..11), Some(0..11));

        let empty = rendered(parse(""));
        assert_eq!(empty.source(), "");
        assert_eq!(empty.range_for_source(0..0), None);
    }

    #[test]
    fn a_range_across_blocks_holds_the_separators_between_them() {
        let markdown = "ab\n\ncd\n\n# ef";
        // "ab\ncd\nef\n"
        assert_eq!(
            converted_needle(markdown, "b\n\ncd\n\n# e").as_deref(),
            Some("b\ncd\ne")
        );

        let table = "| a | b |\n|---|---|\n| c | d |";
        assert_eq!(
            converted_needle(table, "b |\n|---|---|\n| c").as_deref(),
            Some("b\nc")
        );
        assert_eq!(converted_needle(table, "c | d").as_deref(), Some("c d"));

        let list = "- one\n- two\n  - three";
        assert_eq!(
            converted_needle(list, "ne\n- two\n  - th").as_deref(),
            Some("ne\ntwo\nth")
        );
    }

    #[test]
    fn code_blocks_convert_their_body() {
        let fenced = "```rust\nlet x = 1;\nlet y = 2;\n```";
        assert_eq!(
            converted_needle(fenced, "x = 1;\nlet y").as_deref(),
            Some("x = 1;\nlet y")
        );
        assert_eq!(
            converted(fenced, 0..fenced.len()).as_deref(),
            Some("let x = 1;\nlet y = 2;")
        );
        let indented = "    let x = 1;\n    let y = 2;";
        assert_eq!(
            converted_needle(indented, "x = 1").as_deref(),
            Some("x = 1")
        );
        let tilde = "~~~\nwavy\n~~~";
        assert_eq!(converted(tilde, 0..tilde.len()).as_deref(), Some("wavy"));
    }

    #[test]
    fn an_image_between_texts_keeps_the_range_contiguous() {
        let markdown = "a ![alt](image.png) b";
        let text = rendered(parse(markdown));
        let range = text.range_for_source(0..markdown.len()).unwrap();
        assert_eq!(&text.as_str()[range], "a  b");
    }

    #[test]
    fn html_text_converts_nothing() {
        let html = "<p>one <b>two</b></p>";
        let document = format::html::parse(html, &mut NodeContext::default()).expect("parse HTML");
        let text = rendered(document);
        assert_eq!(text.source(), html);
        assert!(!text.is_empty());
        for start in 0..html.len() {
            for end in start + 1..=html.len() {
                assert_eq!(text.range_for_source(start..end), None, "{start}..{end}");
            }
        }
    }

    #[test]
    fn custom_blocks_convert_whole() {
        let extensions = crate::text::MarkdownExtensions::default().block_parser(|node, cx| {
            let markdown::mdast::Node::Paragraph(paragraph) = node else {
                return None;
            };
            let [markdown::mdast::Node::Text(text)] = paragraph.children.as_slice() else {
                return None;
            };
            text.value.starts_with('$').then(|| {
                crate::text::MarkdownNode::new("ticker", ())
                    .text(text.value.clone())
                    .markdown(cx.node_source(node).unwrap_or_default())
            })
        });
        let markdown = "before\n\n$TSLA.US\n\nafter";
        let mut cx = NodeContext {
            markdown_extensions: extensions.into(),
            ..NodeContext::default()
        };
        let text = rendered(format::markdown::parse(markdown, &mut cx).unwrap());

        assert_eq!(text.as_str(), "before\n$TSLA.US\nafter\n");
        let ticker = nth(markdown, "$TSLA.US", 0);
        assert_eq!(text.range_for_source(ticker.clone()), Some(7..15));
        // Part of the block's source converts the whole block.
        assert_eq!(
            text.range_for_source(ticker.start + 1..ticker.start + 3),
            Some(7..15)
        );
        assert_eq!(
            text.range_for_source(nth(markdown, "re\n\n$T", 0)),
            Some(4..15)
        );
    }

    /// A block whose text is a leaf, in the order of the rendered text.
    enum LeafNode<'a> {
        Paragraph(&'a Paragraph),
        Code(&'a CodeBlock),
    }

    impl LeafNode<'_> {
        fn text(&self) -> String {
            match self {
                Self::Paragraph(paragraph) => paragraph
                    .children
                    .iter()
                    .map(|child| child.text.as_ref())
                    .collect(),
                Self::Code(code_block) => code_block.code().to_string(),
            }
        }

        /// Selects `range` of its text, as painting a selection does.
        ///
        /// A paragraph paints the run of text before each inline image in
        /// that image's state and the rest in its own, so each state gets its
        /// run and the part of `range` inside it.
        fn select(&self, range: Option<Range<usize>>) {
            match self {
                Self::Paragraph(paragraph) => {
                    let text = self.text();
                    let select_run = |state: &std::sync::Mutex<_>, run: Range<usize>| {
                        let mut state: std::sync::MutexGuard<'_, crate::text::inline::InlineState> =
                            state.lock().unwrap();
                        state.set_text(text[run.clone()].to_string().into());
                        state.selection = range
                            .as_ref()
                            .map(|range| range.start.max(run.start)..range.end.min(run.end))
                            .filter(|selected| selected.start < selected.end)
                            .map(|selected| {
                                (selected.start - run.start..selected.end - run.start).into()
                            });
                    };
                    let (mut run_start, mut offset) = (0, 0);
                    for child in &paragraph.children {
                        assert!(child.custom.is_none(), "inline objects select on their own");
                        if child.image.is_some() {
                            select_run(&child.state, run_start..offset);
                            run_start = offset;
                        }
                        offset += child.text.len();
                    }
                    select_run(&paragraph.state, run_start..offset);
                }
                Self::Code(code_block) => match range {
                    Some(range) => code_block.set_selection(range),
                    None => code_block.clear_selection(),
                },
            }
        }
    }

    /// The blocks holding text, the way `IndexBuilder` walks them.
    fn leaf_nodes<'a>(blocks: &'a [BlockNode], leaves: &mut Vec<LeafNode<'a>>) {
        for block in blocks {
            match block {
                BlockNode::Root { children, .. }
                | BlockNode::Blockquote { children, .. }
                | BlockNode::List { children, .. }
                | BlockNode::ListItem { children, .. } => leaf_nodes(children, leaves),
                BlockNode::Paragraph(paragraph) => leaves.push(LeafNode::Paragraph(paragraph)),
                BlockNode::Heading { children, .. } => leaves.push(LeafNode::Paragraph(children)),
                BlockNode::Table(table) => {
                    for row in &table.children {
                        for cell in &row.children {
                            leaves.push(LeafNode::Paragraph(&cell.children));
                        }
                    }
                }
                BlockNode::CodeBlock(code_block) => leaves.push(LeafNode::Code(code_block)),
                _ => {}
            }
        }
        leaves.retain(|leaf| !leaf.text().is_empty());
    }

    /// Checks that selecting any range of `markdown`'s rendered text that
    /// starts and ends inside text, and converting the source range the
    /// selection reports, gives the selected range back.
    ///
    /// The selection's source range comes from `selected_source_range`, which
    /// maps the other way with code of its own, so the two check each other.
    fn assert_selections_round_trip(markdown: &str) {
        let document = parse(markdown);
        let text = rendered(document.clone());
        // Only a character maps as a whole, or the characters one entity
        // decodes to: a longer piece would widen every range inside it.
        for segment in text
            .index()
            .source_map
            .iter()
            .filter(|segment| !segment.linear)
        {
            let rendered = &text.as_str()[segment.rendered.clone()];
            let source = &markdown[segment.source.clone()];
            assert!(
                rendered.chars().count() == 1 || (source.starts_with('&') && source.ends_with(';')),
                "{markdown:?}: {rendered:?} maps from {source:?} only as a whole"
            );
        }
        let mut leaves = Vec::new();
        leaf_nodes(&document.blocks, &mut leaves);
        let spans = &text.index().leaves;
        assert_eq!(leaves.len(), spans.len(), "leaves of {markdown:?}");
        let leaves = leaves
            .into_iter()
            .zip(spans.iter().map(|span| span.range.clone()))
            .collect::<Vec<_>>();
        for (_, range) in &leaves {
            assert!(text.as_str().is_char_boundary(range.start));
        }

        // Every character boundary inside a leaf, as (leaf, offset in text).
        let boundaries = leaves
            .iter()
            .enumerate()
            .flat_map(|(ix, (_, range))| {
                let leaf_text = &text.as_str()[range.clone()];
                leaf_text
                    .char_indices()
                    .map(|(offset, _)| offset)
                    .chain([leaf_text.len()])
                    .map(move |offset| (ix, range.start + offset))
            })
            .collect::<Vec<_>>();

        for (start_ix, &(first, start)) in boundaries.iter().enumerate() {
            if start == leaves[first].1.end {
                continue;
            }
            for &(last, end) in &boundaries[start_ix + 1..] {
                if end == leaves[last].1.start || end <= start {
                    continue;
                }
                for (ix, (leaf, range)) in leaves.iter().enumerate() {
                    let selected = (first..=last).contains(&ix).then(|| {
                        start.max(range.start) - range.start..end.min(range.end) - range.start
                    });
                    leaf.select(selected);
                }
                let source = document.selected_source_range().unwrap_or_else(|| {
                    panic!("{markdown:?}: selecting {start}..{end} maps to no source")
                });
                // Characters that share their source, like the two an entity
                // can decode to, are only selected together.
                let expected = text
                    .index()
                    .source_map
                    .iter()
                    .filter(|segment| {
                        !segment.linear
                            && segment.rendered.start < end
                            && segment.rendered.end > start
                    })
                    .fold(start..end, |range, segment| {
                        range.start.min(segment.rendered.start)..range.end.max(segment.rendered.end)
                    });
                assert_eq!(
                    text.range_for_source(source.clone()),
                    Some(expected),
                    "{markdown:?}: selecting {:?} ({start}..{end}) reports source {:?} ({source:?})",
                    &text.as_str()[start..end],
                    &markdown[source.clone()],
                );
            }
        }
        for (leaf, _) in &leaves {
            leaf.select(None);
        }
    }

    const ROUND_TRIP_CORPUS: &[&str] = &[
        "plain text",
        "hello **world** and *em* and ~~del~~ and `code`",
        "nested **bold *and italic* text** and ***both***",
        "`` code with ` backtick `` then text",
        "# Heading with **bold**",
        "Setext heading\n===",
        "> quoted **text**\n> continued\n>\n> second paragraph",
        "- item one\n- item **two**\n  - nested *item*\n\n  continued item",
        "3. third\n4. fourth",
        "- [x] done\n- [ ] todo",
        "| a | **b** |\n|---|:---:|\n| c `d` | e |\n| | f |",
        "```rust\nlet x = 1;\n\nlet y = 2;\n```",
        "    indented code\n    more",
        "~~~\ntilde fence\n~~~",
        "a [link](https://example.com \"title\") b",
        "a [reference] b\n\n[reference]: https://example.com",
        "<https://auto.example> and https://gfm.example",
        "soft\nbreak\nlines",
        "hard  \nbreak\\\nagain",
        "trailing spaces   \nnext line",
        "escapes \\* \\_ \\` \\\\ and \\[not a link\\]",
        "\\*starts escaped and **\\*bold** and *\\_em*",
        "entity &acE; as long as its characters",
        "entities &amp; &lt; &#65; &#x42; &copy; end",
        "中文 **粗体** 和 `代码` 🎉 é and e\u{301}",
        "crlf\r\nlines\r\n\r\nnext paragraph",
        "image ![alt](image.png) between",
        "one\n\ntwo\n\n---\n\nthree",
        "# Title\n\nIntro with **bold**.\n\n- first\n- second\n\n| a | b |\n|---|---|\n| c | d |\n\n```\ncode\n```\n\n> quote",
    ];

    #[test]
    fn selections_round_trip_through_source_ranges() {
        for markdown in ROUND_TRIP_CORPUS {
            assert_selections_round_trip(markdown);
        }
    }
}

/// Where a range to reveal starts.
#[derive(Clone, Copy, Debug, PartialEq)]
enum RevealTarget {
    /// A line of a text leaf: the leaf, and the offset in its text.
    Line { key: TextLeafKey, offset: usize },
    /// A whole top-level block, for text that belongs to no leaf.
    Block { ix: usize },
}

/// How long a reveal keeps trying. One that has not been carried out by
/// then, e.g. because its view was not painted, is dropped rather than
/// scrolling long after it was asked for.
const REVEAL_TIMEOUT: Duration = Duration::from_secs(1);

/// How many frames a reveal whose line was laid out but not visible keeps
/// trying, e.g. while an enclosing container scrolls to it.
const REVEAL_ATTEMPTS: usize = 8;

/// Where the line a reveal starts on was laid out in one frame, in window
/// coordinates, and whether it was inside the visible area.
#[derive(Clone, Copy, Debug)]
struct RevealReport {
    line: Bounds<Pixels>,
    visible: bool,
}

/// A range [`TextViewState::reveal_range`](super::TextViewState::reveal_range)
/// is scrolling into view.
///
/// The `Inline` that lays out the start of the range asks the enclosing list
/// to scroll its line into view during prepaint, and reports where the line
/// ended up. The view reads the report once painted, after any list has
/// scrolled, and is done once the line is visible.
#[derive(Debug)]
pub(super) struct PendingReveal {
    target: RevealTarget,
    requested_at: Instant,
    /// What the target's `Inline` reported this frame; `None` when it was not
    /// laid out.
    report: Arc<Mutex<Option<RevealReport>>>,
    attempts: usize,
}

/// How a pending reveal went in one frame.
pub(super) enum RevealProgress {
    /// The line is visible, so the reveal is done.
    Shown,
    /// The line was laid out at these window bounds without being visible.
    Hidden(Bounds<Pixels>),
    /// The line was not laid out.
    NotLaidOut,
}

impl PendingReveal {
    /// The start of `range` in `text`, asked for at `now`, or `None` when
    /// the range is not a range of it.
    pub(super) fn new(text: &RenderedText, range: &Range<usize>, now: Instant) -> Option<Self> {
        Some(Self {
            target: text.index().locate(range)?,
            requested_at: now,
            report: Arc::default(),
            attempts: 0,
        })
    }

    pub(super) fn is_expired(&self, now: Instant) -> bool {
        now.saturating_duration_since(self.requested_at) > REVEAL_TIMEOUT
            || self.attempts >= REVEAL_ATTEMPTS
    }

    /// Whether the reveal is of a whole block rather than a line.
    pub(super) fn is_block(&self) -> bool {
        matches!(self.target, RevealTarget::Block { .. })
    }

    /// The index of the top-level block of `document` the reveal starts in.
    pub(super) fn block_ix(&self, document: &ParsedDocument) -> Option<usize> {
        match self.target {
            RevealTarget::Line { key, .. } => document.blocks.iter().rposition(|block| {
                block
                    .span()
                    .is_some_and(|span| span.start <= key.block_start())
            }),
            RevealTarget::Block { ix } => (ix < document.blocks.len()).then_some(ix),
        }
    }

    /// Whether the line was laid out in the previous frame.
    pub(super) fn was_laid_out(&self) -> bool {
        self.report.lock().is_ok_and(|report| report.is_some())
    }

    /// Starts a frame: forgets the previous report and hands the line to
    /// rendering. A block has no line.
    pub(super) fn request(&self) -> Option<RevealRequest> {
        if let Ok(mut report) = self.report.lock() {
            *report = None;
        }
        let RevealTarget::Line { key, offset } = self.target else {
            return None;
        };
        Some(RevealRequest {
            key,
            offset,
            report: self.report.clone(),
        })
    }

    /// Ends a frame with what the line reported, counting a frame in which
    /// it was laid out but hidden as an attempt.
    pub(super) fn progress(&mut self) -> RevealProgress {
        let report = self.report.lock().ok().and_then(|report| *report);
        match report {
            Some(report) if report.visible => RevealProgress::Shown,
            Some(report) => {
                self.attempts += 1;
                RevealProgress::Hidden(report.line)
            }
            None => RevealProgress::NotLaidOut,
        }
    }

    /// The reveal in the document `remap` maps the old one to, as long as
    /// the text it starts at is unchanged.
    pub(super) fn remap(mut self, remap: &LeafRemap) -> Option<Self> {
        let RevealTarget::Line { key, offset } = self.target else {
            return None;
        };
        let (key, unchanged) = remap.leaf(key)?;
        (offset < unchanged).then_some(())?;
        self.target = RevealTarget::Line { key, offset };
        Some(self)
    }
}

/// The start of a pending reveal, as rendering hands it to the `Inline`
/// that lays that text out.
#[derive(Clone, Debug)]
pub(crate) struct RevealRequest {
    key: TextLeafKey,
    offset: usize,
    report: Arc<Mutex<Option<RevealReport>>>,
}

impl RevealRequest {
    /// The start of the reveal, when it is in `key`'s text between `start`
    /// and `end`, rebased to `start`.
    pub(crate) fn at(
        &self,
        key: Option<TextLeafKey>,
        start: usize,
        end: usize,
    ) -> Option<RevealAt> {
        if key != Some(self.key) {
            return None;
        }
        RevealAt {
            offset: self.offset,
            report: self.report.clone(),
        }
        .rebase(start, end)
    }
}

/// The start of a pending reveal, in the byte space of one run of text.
#[derive(Clone, Debug)]
pub(crate) struct RevealAt {
    offset: usize,
    report: Arc<Mutex<Option<RevealReport>>>,
}

impl RevealAt {
    pub(crate) fn offset(&self) -> usize {
        self.offset
    }

    /// The reveal in the text between `start` and `end`, rebased to `start`,
    /// or `None` when it starts outside it.
    pub(crate) fn rebase(&self, start: usize, end: usize) -> Option<Self> {
        (start..end).contains(&self.offset).then(|| Self {
            offset: self.offset - start,
            report: self.report.clone(),
        })
    }

    /// The reveal moved into the text between `start` and `end` and rebased
    /// to `start`: one before it moves to its first character, one after it
    /// to its end.
    pub(crate) fn clamp(&self, start: usize, end: usize) -> Self {
        Self {
            offset: self.offset.clamp(start, end) - start,
            report: self.report.clone(),
        }
    }

    /// Report where the line the reveal starts on was laid out, in window
    /// coordinates, and whether it was inside the visible area.
    pub(crate) fn report(&self, line: Bounds<Pixels>, visible: bool) {
        if let Ok(mut report) = self.report.lock() {
            *report = Some(RevealReport { line, visible });
        }
    }
}
