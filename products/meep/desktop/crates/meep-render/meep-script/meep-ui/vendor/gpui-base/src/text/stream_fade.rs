//! Fades streamed text in: the rendered characters an update adds start
//! transparent and reach full color over [`TextViewMotion::stream_fade`],
//! as one chunk, or word by word (character by character for CJK) when
//! [`TextViewMotion::stream_fade_stagger`] separates them. An update too
//! large to light up within one fade goes back to fading as one chunk -- see
//! [`TextViewMotion::stagger_step`].
//!
//! The tracker compares rendered text, not source, so `**bo` completing into
//! bold `bold` fades the changed glyphs rather than mapping source bytes.

#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{ops::Range, sync::Arc, time::Duration};
#[cfg(target_family = "wasm")]
use web_time::Instant;

use gpui::{ElementId, SharedString};

use super::{
    document::ParsedDocument,
    node::{BlockNode, InlineNode, Paragraph},
};
use crate::motion::{Easing, Timing};

/// Motion policy of a text view. Base plays it; every duration defaults to
/// zero, so an unstyled view adopts new content at once.
#[derive(Clone, Debug)]
pub struct TextViewMotion {
    stream_fade: Duration,
    stream_fade_stagger: Duration,
    stream_fade_easing: Easing,
}

impl Default for TextViewMotion {
    fn default() -> Self {
        Self {
            stream_fade: Duration::ZERO,
            stream_fade_stagger: Duration::ZERO,
            stream_fade_easing: Easing::default(),
        }
    }
}

impl TextViewMotion {
    /// How long the text an update appends takes to reach full color.
    pub fn with_stream_fade(mut self, duration: Duration) -> Self {
        self.stream_fade = duration;
        self
    }

    /// How much later each further word of one update starts fading than
    /// the word before it; zero fades the update as one chunk. A long update
    /// is compressed so its last word starts within one [`Self::stream_fade`].
    pub fn with_stream_fade_stagger(mut self, stagger: Duration) -> Self {
        self.stream_fade_stagger = stagger;
        self
    }

    /// The curve the appended text fades in along.
    pub fn with_stream_fade_easing(mut self, easing: Easing) -> Self {
        self.stream_fade_easing = easing;
        self
    }

    pub fn stream_fade(&self) -> Duration {
        self.stream_fade
    }

    pub fn stream_fade_stagger(&self) -> Duration {
        self.stream_fade_stagger
    }

    pub fn stream_fade_easing(&self) -> &Easing {
        &self.stream_fade_easing
    }

    /// The start offset between consecutive words of an update `words` long: the stagger as
    /// asked, or nothing.
    ///
    /// Staggering only reads as words arriving one after another while the whole update lights
    /// up well within one [`Self::stream_fade`]. Once the last word would start later than
    /// that, what is left is a sweep drawn across text that appeared at once -- and an update
    /// that large (`stream_fade / stream_fade_stagger` words and up) was not typed anyway.
    /// Squeezing the step to fit only makes the sweep faster, so drop it instead and let the
    /// update fade as one chunk.
    fn stagger_step(&self, words: usize) -> Duration {
        if words < 2 {
            return Duration::ZERO;
        }
        let span = self.stream_fade_stagger.as_nanos() * (words as u128 - 1);
        if span > self.stream_fade.as_nanos() {
            return Duration::ZERO;
        }
        self.stream_fade_stagger
    }
}

/// Identifies one run of rendered text across re-parses: the source start of
/// the block that owns it, plus the cell ordinal inside a table.
///
/// Keys order as their leaves appear in the document.
#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub(crate) struct TextLeafKey {
    block_start: usize,
    ordinal: usize,
}

/// The key as an element id, for a leaf that needs element state or an
/// accessibility identity: unique per leaf, and allocation-free, as it is
/// built every frame.
impl From<TextLeafKey> for ElementId {
    fn from(key: TextLeafKey) -> Self {
        let mut bytes = [0; 20];
        bytes[..8].copy_from_slice(&(key.block_start as u64).to_le_bytes());
        bytes[8..16].copy_from_slice(&(key.ordinal as u64).to_le_bytes());
        ElementId::OpaqueId(bytes)
    }
}

impl TextLeafKey {
    pub(crate) fn block(start: usize) -> Self {
        Self {
            block_start: start,
            ordinal: 0,
        }
    }

    pub(crate) fn table_cell(table_start: usize, ordinal: usize) -> Self {
        Self {
            block_start: table_start,
            ordinal: ordinal + 1,
        }
    }

    pub(crate) fn block_start(&self) -> usize {
        self.block_start
    }

    /// The index of the table cell the leaf is, among all the cells of its
    /// table, or `None` when it is not a cell.
    pub(crate) fn cell_ix(&self) -> Option<usize> {
        self.ordinal.checked_sub(1)
    }

    /// The same leaf in its block moved to start at `block_start`.
    pub(crate) fn moved_to(self, block_start: usize) -> Self {
        Self {
            block_start,
            ordinal: self.ordinal,
        }
    }
}

/// Rendered byte ranges with the [`gpui::HighlightStyle::fade_out`] factor
/// each one paints with this frame: `1.0` transparent, `0.0` opaque.
pub(crate) type FadeRanges = Vec<(Range<usize>, f32)>;

/// One frame's fade factors, resolved once per render so node rendering only
/// looks up its leaf.
#[derive(Debug, Default)]
pub(crate) struct StreamFadeFrame {
    leaves: Vec<(TextLeafKey, FadeRanges)>,
}

impl StreamFadeFrame {
    pub(crate) fn fades(&self, key: TextLeafKey) -> Option<&[(Range<usize>, f32)]> {
        self.leaves
            .iter()
            .find(|(leaf, _)| *leaf == key)
            .map(|(_, fades)| fades.as_slice())
    }
}

struct FadeSegment {
    range: Range<usize>,
    started_at: Instant,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum PendingUpdate {
    #[default]
    None,
    /// Every update since the last parse extended the text, which was
    /// `origin` bytes long before the first of them.
    Extend {
        origin: usize,
    },
    Replace,
}

/// Tracks which rendered text arrived recently and samples its fade.
#[derive(Default)]
pub(super) struct StreamFadeTracker {
    motion: TextViewMotion,
    pending: PendingUpdate,
    segments: Vec<(TextLeafKey, Vec<FadeSegment>)>,
}

impl StreamFadeTracker {
    pub(super) fn set_motion(&mut self, motion: TextViewMotion) {
        if motion.stream_fade.is_zero() {
            self.segments.clear();
            self.pending = PendingUpdate::None;
        }
        self.motion = motion;
    }

    pub(super) fn is_enabled(&self) -> bool {
        !self.motion.stream_fade.is_zero()
    }

    /// The next update extends the current text, which is `len` bytes long.
    pub(super) fn note_extend(&mut self, len: usize) {
        if !self.is_enabled() {
            return;
        }
        self.pending = match self.pending {
            PendingUpdate::None => PendingUpdate::Extend { origin: len },
            PendingUpdate::Extend { origin } => PendingUpdate::Extend {
                origin: origin.min(len),
            },
            PendingUpdate::Replace => PendingUpdate::Replace,
        };
    }

    /// The next update replaces the current text.
    pub(super) fn note_replace(&mut self) {
        if self.is_enabled() {
            self.pending = PendingUpdate::Replace;
        }
    }

    /// Forgets the noted update after its parse failed.
    pub(super) fn discard_pending(&mut self) {
        self.pending = PendingUpdate::None;
    }

    /// Records what `new` renders that `old` did not, for the updates noted
    /// since the last call, as segments that start fading at `now`.
    ///
    /// Only blocks the extension reaches are compared, walking both documents
    /// from the tail, so a chunk landing at the end of a long document costs
    /// one paragraph, not the document.
    pub(super) fn record(&mut self, old: &ParsedDocument, new: &ParsedDocument, now: Instant) {
        let pending = std::mem::take(&mut self.pending);
        if !self.is_enabled() {
            self.segments.clear();
            return;
        }
        let origin = match pending {
            PendingUpdate::None => return,
            PendingUpdate::Replace => {
                self.segments.clear();
                return;
            }
            PendingUpdate::Extend { origin } => origin,
        };

        let mut affected = Vec::new();
        for block in new.blocks.iter().rev() {
            if block.span().is_some_and(|span| span.end <= origin) {
                break;
            }
            text_leaves(block, &mut affected);
        }
        let Some(first_start) = affected.iter().map(|(key, _)| key.block_start).min() else {
            return;
        };

        let mut previous = Vec::new();
        for block in old.blocks.iter().rev() {
            if block.span().is_some_and(|span| span.end < first_start) {
                break;
            }
            text_leaves(block, &mut previous);
        }

        for (key, leaf) in affected {
            let len = leaf.len();
            let prefix = previous
                .iter()
                .find(|(previous_key, _)| *previous_key == key)
                .map_or(0, |(_, old_leaf)| leaf.common_prefix_len(old_leaf));
            let segments = match self.segments.iter().position(|(k, _)| *k == key) {
                Some(ix) => &mut self.segments[ix].1,
                None => {
                    self.segments.push((key, Vec::new()));
                    &mut self.segments.last_mut().expect("just pushed").1
                }
            };
            // Text past the divergence is repainted, so its earlier fade no
            // longer describes what is on screen.
            segments.retain_mut(|segment| {
                segment.range.end = segment.range.end.min(prefix);
                segment.range.start < segment.range.end
            });
            if prefix >= len {
                continue;
            }
            if self.motion.stream_fade_stagger.is_zero() {
                segments.push(FadeSegment {
                    range: prefix..len,
                    started_at: now,
                });
                continue;
            }
            let words = fade_units(leaf.chunks(), prefix, len);
            let step = self.motion.stagger_step(words.len());
            for (ix, range) in words.into_iter().enumerate() {
                segments.push(FadeSegment {
                    range,
                    started_at: now + step * ix as u32,
                });
            }
        }
        self.segments.retain(|(_, segments)| !segments.is_empty());
    }

    /// Samples every unfinished segment at `now`, dropping the finished ones.
    /// `None` means nothing is fading, so no frame needs to follow.
    pub(super) fn frame(
        &mut self,
        now: Instant,
        reduce_motion: bool,
    ) -> Option<Arc<StreamFadeFrame>> {
        if self.segments.is_empty() {
            return None;
        }
        if reduce_motion || !self.is_enabled() {
            self.segments.clear();
            return None;
        }
        let timing =
            Timing::new(self.motion.stream_fade).ease(self.motion.stream_fade_easing.clone());
        let mut leaves = Vec::with_capacity(self.segments.len());
        self.segments.retain_mut(|(key, segments)| {
            let mut fades = Vec::with_capacity(segments.len());
            segments.retain(|segment| {
                let sample = timing.sample(now.saturating_duration_since(segment.started_at));
                if sample.finished {
                    return false;
                }
                let fade_out = (1.0 - sample.directed_progress).clamp(0.0, 1.0);
                fades.push((segment.range.clone(), fade_out));
                true
            });
            if fades.is_empty() {
                return false;
            }
            leaves.push((*key, fades));
            true
        });
        (!leaves.is_empty()).then(|| Arc::new(StreamFadeFrame { leaves }))
    }
}

/// A block's rendered text, in the byte space its highlights use.
pub(super) enum TextLeaf<'a> {
    Paragraph(&'a Paragraph),
    Code(SharedString),
}

enum Chunks<'a> {
    Paragraph(std::slice::Iter<'a, InlineNode>),
    Code(Option<&'a str>),
}

impl<'a> Iterator for Chunks<'a> {
    type Item = &'a str;

    fn next(&mut self) -> Option<&'a str> {
        match self {
            Self::Paragraph(nodes) => nodes.next().map(|node| node.text.as_ref()),
            Self::Code(code) => code.take(),
        }
    }
}

impl TextLeaf<'_> {
    fn chunks(&self) -> Chunks<'_> {
        match self {
            Self::Paragraph(paragraph) => Chunks::Paragraph(paragraph.children.iter()),
            Self::Code(code) => Chunks::Code(Some(code.as_ref())),
        }
    }

    fn len(&self) -> usize {
        self.chunks().map(str::len).sum()
    }

    /// The length of the rendered text `self` shares with `old`, on a char
    /// boundary of `self`.
    pub(super) fn common_prefix_len(&self, old: &Self) -> usize {
        let prefix = common_prefix_len(self.chunks(), old.chunks());
        floor_char_boundary(self.chunks(), prefix)
    }
}

pub(super) fn text_leaves<'a>(block: &'a BlockNode, out: &mut Vec<(TextLeafKey, TextLeaf<'a>)>) {
    match block {
        BlockNode::Paragraph(paragraph) => {
            if let Some(span) = paragraph.span {
                out.push((
                    TextLeafKey::block(span.start),
                    TextLeaf::Paragraph(paragraph),
                ));
            }
        }
        BlockNode::Heading {
            children,
            span: Some(span),
            ..
        } => out.push((
            TextLeafKey::block(span.start),
            TextLeaf::Paragraph(children),
        )),
        BlockNode::CodeBlock(code_block) => {
            if let Some(span) = code_block.span {
                out.push((
                    TextLeafKey::block(span.start),
                    TextLeaf::Code(code_block.code()),
                ));
            }
        }
        BlockNode::Table(table) => {
            if let Some(span) = table.span {
                let cells = table.children.iter().flat_map(|row| row.children.iter());
                for (ordinal, cell) in cells.enumerate() {
                    out.push((
                        TextLeafKey::table_cell(span.start, ordinal),
                        TextLeaf::Paragraph(&cell.children),
                    ));
                }
            }
        }
        BlockNode::Root { children, .. }
        | BlockNode::Blockquote { children, .. }
        | BlockNode::List { children, .. }
        | BlockNode::ListItem { children, .. } => {
            for child in children {
                text_leaves(child, out);
            }
        }
        _ => {}
    }
}

/// Compares chunk by chunk with slice equality, descending to bytes only at
/// the first chunk pair that differs.
fn common_prefix_len<'a>(
    mut a: impl Iterator<Item = &'a str>,
    mut b: impl Iterator<Item = &'a str>,
) -> usize {
    let (mut a_rest, mut b_rest): (&[u8], &[u8]) = (&[], &[]);
    let mut len = 0;
    loop {
        if a_rest.is_empty() {
            match a.next() {
                Some(chunk) => a_rest = chunk.as_bytes(),
                None => return len,
            }
            continue;
        }
        if b_rest.is_empty() {
            match b.next() {
                Some(chunk) => b_rest = chunk.as_bytes(),
                None => return len,
            }
            continue;
        }
        let step = a_rest.len().min(b_rest.len());
        if a_rest[..step] != b_rest[..step] {
            return len
                + a_rest
                    .iter()
                    .zip(b_rest)
                    .take_while(|(x, y)| x == y)
                    .count();
        }
        len += step;
        a_rest = &a_rest[step..];
        b_rest = &b_rest[step..];
    }
}

/// Splits `start..end` of the rendered text into the units that fade one
/// after another: a word together with the whitespace after it, or one CJK
/// character, since CJK text has no spaces to reveal it by.
fn fade_units<'a>(
    chunks: impl Iterator<Item = &'a str>,
    start: usize,
    end: usize,
) -> Vec<Range<usize>> {
    let mut units = Vec::new();
    let mut unit_start = start;
    let mut unit_has_glyph = false;
    let mut previous: Option<char> = None;
    let mut offset = 0;
    for chunk in chunks {
        if offset + chunk.len() <= start {
            offset += chunk.len();
            previous = chunk.chars().next_back();
            continue;
        }
        for (ix, c) in chunk.char_indices() {
            let position = offset + ix;
            if position >= end {
                break;
            }
            if position >= start {
                let starts_unit = unit_has_glyph
                    && !c.is_whitespace()
                    && (is_cjk(c) || previous.is_some_and(|p| p.is_whitespace() || is_cjk(p)));
                if starts_unit && position > unit_start {
                    units.push(unit_start..position);
                    unit_start = position;
                    unit_has_glyph = false;
                }
                unit_has_glyph |= !c.is_whitespace();
            }
            previous = Some(c);
        }
        offset += chunk.len();
        if offset >= end {
            break;
        }
    }
    if unit_start < end {
        units.push(unit_start..end);
    }
    units
}

fn is_cjk(c: char) -> bool {
    matches!(
        u32::from(c),
        0x3040..=0x30FF // Hiragana, Katakana
            | 0x3400..=0x4DBF // CJK Unified Ideographs Extension A
            | 0x4E00..=0x9FFF // CJK Unified Ideographs
            | 0xAC00..=0xD7AF // Hangul syllables
            | 0xF900..=0xFAFF // CJK Compatibility Ideographs
            | 0x20000..=0x2FA1F // CJK Unified Ideographs Extensions B and later
    )
}

fn floor_char_boundary<'a>(chunks: impl Iterator<Item = &'a str>, offset: usize) -> usize {
    let mut start = 0;
    for chunk in chunks {
        let end = start + chunk.len();
        if offset < end {
            let mut local = offset - start;
            while !chunk.is_char_boundary(local) {
                local -= 1;
            }
            return start + local;
        }
        start = end;
    }
    offset
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn common_prefix_spans_chunk_boundaries() {
        assert_eq!(
            common_prefix_len(["ab", "cd"].into_iter(), ["abc", "d"].into_iter()),
            4
        );
        assert_eq!(
            common_prefix_len(["ab", "cd"].into_iter(), ["abc", "x"].into_iter()),
            3
        );
        assert_eq!(
            common_prefix_len(["", "ab"].into_iter(), ["a", "", "b", "c"].into_iter()),
            2
        );
        assert_eq!(common_prefix_len(["ab"].into_iter(), [].into_iter()), 0);
    }

    #[test]
    fn fade_units_are_words_with_their_trailing_space() {
        let text = ["hello", " one two", "  three"];
        assert_eq!(
            fade_units(text.into_iter(), 5, 20),
            vec![5..10, 10..15, 15..20]
        );
        // A unit that is only whitespace joins the word after it.
        assert_eq!(fade_units(["a  b"].into_iter(), 1, 4), vec![1..4]);
        assert_eq!(
            fade_units(["abc"].into_iter(), 3, 3),
            Vec::<Range<usize>>::new()
        );
    }

    #[test]
    fn fade_units_split_cjk_by_character() {
        assert_eq!(
            fade_units(["你好，世界 ok"].into_iter(), 0, 18),
            vec![0..3, 3..6, 6..9, 9..12, 12..16, 16..18]
        );
        // Latin before CJK starts a unit at the script change.
        assert_eq!(fade_units(["ab中"].into_iter(), 0, 5), vec![0..2, 2..5]);
    }

    #[test]
    fn stagger_holds_while_the_update_lights_up_within_one_fade() {
        let motion = TextViewMotion::default()
            .with_stream_fade(Duration::from_millis(600))
            .with_stream_fade_stagger(Duration::from_millis(100));
        assert_eq!(motion.stagger_step(1), Duration::ZERO);
        assert_eq!(motion.stagger_step(3), Duration::from_millis(100));
        // The 7th word starts at 600 ms, exactly one fade in -- still the stagger as asked.
        assert_eq!(motion.stagger_step(7), Duration::from_millis(100));
    }

    #[test]
    fn an_update_too_large_to_light_up_in_one_fade_fades_as_one_chunk() {
        let motion = TextViewMotion::default()
            .with_stream_fade(Duration::from_millis(600))
            .with_stream_fade_stagger(Duration::from_millis(100));
        // An 8th word would start past the fade: that is a sweep, not typing.
        assert_eq!(motion.stagger_step(8), Duration::ZERO);
        assert_eq!(motion.stagger_step(200), Duration::ZERO);
        // Without a stagger nothing changes -- every update was already one chunk.
        let plain = TextViewMotion::default().with_stream_fade(Duration::from_millis(600));
        assert_eq!(plain.stagger_step(200), Duration::ZERO);
    }

    #[test]
    fn prefix_never_splits_a_character() {
        // "中" and "串" share their first UTF-8 byte.
        let new = "a中";
        let old = "a串";
        let prefix = common_prefix_len([new].into_iter(), [old].into_iter());
        assert!(prefix > 1 && !new.is_char_boundary(prefix));
        assert_eq!(floor_char_boundary([new].into_iter(), prefix), 1);
        assert_eq!(floor_char_boundary(["a", "中"].into_iter(), 4), 4);
    }
}
