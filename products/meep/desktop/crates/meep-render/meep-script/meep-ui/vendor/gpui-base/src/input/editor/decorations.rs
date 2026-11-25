use crate::input::EditorMode;
use std::{collections::BTreeMap, ops::Range};

use gpui::{App, Context, HighlightStyle, Hsla, Pixels, WeakEntity};
use ropey::Rope;
use sum_tree::Bias;

use super::{InputBaseState, RopeExt as _};

/// Geometric presentation for an editor range decoration.
#[non_exhaustive]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum RangeDecorationStyle {
    /// Fill the continuous visual range.
    Fill,
    /// Draw a continuous one-pixel frame around the visual range.
    #[default]
    Frame,
}

/// A geometric decoration over a UTF-8 byte range.
#[derive(Clone, Debug, PartialEq)]
pub struct RangeDecoration {
    range: Range<usize>,
    style: RangeDecorationStyle,
    color: Option<Hsla>,
}

impl RangeDecoration {
    /// Create a frame using the editor foreground color.
    pub fn new(range: Range<usize>) -> Self {
        Self {
            range,
            style: RangeDecorationStyle::default(),
            color: None,
        }
    }

    /// The half-open UTF-8 byte range supplied to this decoration.
    pub fn range(&self) -> &Range<usize> {
        &self.range
    }

    /// The geometric paint style.
    pub fn style(&self) -> RangeDecorationStyle {
        self.style
    }

    /// An application-owned color override, or `None` for the editor fallback.
    pub fn color(&self) -> Option<Hsla> {
        self.color
    }

    /// Choose a fill or frame without changing text layout.
    pub fn with_style(mut self, style: RangeDecorationStyle) -> Self {
        self.style = style;
        self
    }

    /// Override the editor foreground fallback with an application-owned color.
    pub fn with_color(mut self, color: Hsla) -> Self {
        self.color = Some(color);
        self
    }
}

/// A mark that the editor draws in a strip of the gutter, before the line numbers.
///
/// A non-empty range marks every line it touches. This matches Monaco's
/// [`linesDecorationsClassName`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IModelDecorationOptions.html#linesDecorationsClassName)
/// with `isWholeLine`. An empty range marks a line boundary, such as where lines
/// were deleted. When the range is at the start of a line, the mark appears above
/// that line. Otherwise it appears below the line.
///
/// The default is an empty range at the start of the document, a boundary above
/// the first line, in the editor foreground color.
#[non_exhaustive]
#[derive(Clone, Debug, Default, PartialEq)]
pub struct GutterDecoration {
    range: Range<usize>,
    color: Option<Hsla>,
    folded_color: Option<Hsla>,
}

impl GutterDecoration {
    /// Create a mark with the editor foreground color.
    pub fn new(range: Range<usize>) -> Self {
        Self {
            range,
            color: None,
            folded_color: None,
        }
    }

    /// The decoration's half-open range of UTF-8 byte offsets.
    pub fn range(&self) -> &Range<usize> {
        &self.range
    }

    /// The application color override, or `None` to use the editor fallback.
    pub fn color(&self) -> Option<Hsla> {
        self.color
    }

    /// The color for the bar when the range starts inside a fold, or `None` to
    /// use [`Self::color`].
    pub fn folded_color(&self) -> Option<Hsla> {
        self.folded_color
    }

    /// Set the color instead of the editor foreground fallback.
    pub fn with_color(mut self, color: Hsla) -> Self {
        self.color = Some(color);
        self
    }

    /// Set the color for the bar on a fold's row when the range starts inside that fold.
    pub fn with_folded_color(mut self, color: Hsla) -> Self {
        self.folded_color = Some(color);
        self
    }
}

/// The lane that an [`OverviewRulerDecoration`] uses on the vertical scrollbar track.
///
/// This matches Monaco's
/// [`OverviewRulerLane`](https://microsoft.github.io/monaco-editor/typedoc/enums/editor_editor_api.editor.OverviewRulerLane.html).
/// Its convention uses `Left` for version control, `Center` for search results,
/// and `Right` for diagnostics.
#[non_exhaustive]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum OverviewRulerLane {
    /// The left third of the track.
    Left,
    /// The middle third of the track.
    #[default]
    Center,
    /// The right third of the track.
    Right,
    /// The whole width of the track.
    Full,
}

/// A mark that the editor draws on the vertical scrollbar track for a UTF-8 byte range.
///
/// This is the counterpart of Monaco's
/// [`overviewRuler`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IModelDecorationOverviewRulerOptions.html)
/// decoration option. Like a [`GutterDecoration`], an empty range marks a line boundary.
///
/// The default is an empty range at the start of the document in the center lane,
/// in the editor foreground color.
#[non_exhaustive]
#[derive(Clone, Debug, Default, PartialEq)]
pub struct OverviewRulerDecoration {
    range: Range<usize>,
    lane: OverviewRulerLane,
    color: Option<Hsla>,
}

impl OverviewRulerDecoration {
    /// Create a mark in the center lane with the editor foreground color.
    pub fn new(range: Range<usize>) -> Self {
        Self {
            range,
            lane: OverviewRulerLane::default(),
            color: None,
        }
    }

    /// The decoration's half-open range of UTF-8 byte offsets.
    pub fn range(&self) -> &Range<usize> {
        &self.range
    }

    /// The lane that this mark uses on the track.
    pub fn lane(&self) -> OverviewRulerLane {
        self.lane
    }

    /// The application color override, or `None` to use the editor fallback.
    pub fn color(&self) -> Option<Hsla> {
        self.color
    }

    /// Set the lane that this mark uses.
    pub fn with_lane(mut self, lane: OverviewRulerLane) -> Self {
        self.lane = lane;
        self
    }

    /// Set the color instead of the editor foreground fallback.
    pub fn with_color(mut self, color: Hsla) -> Self {
        self.color = Some(color);
        self
    }
}

/// A presentation style applied to a UTF-8 byte range in an input.
///
/// This is the GPUI [`HighlightStyle`] counterpart of Monaco's
/// [`IModelDeltaDecoration`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IModelDeltaDecoration.html).
#[derive(Clone, Debug, PartialEq)]
pub struct TextDecoration {
    pub range: Range<usize>,
    pub style: HighlightStyle,
}

impl TextDecoration {
    /// Create a text decoration from a UTF-8 byte range and a GPUI style.
    pub fn new(range: Range<usize>, style: HighlightStyle) -> Self {
        Self { range, style }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
struct DecorationCollectionId(usize);

/// An independently managed collection of [`TextDecoration`]s.
///
/// This is the GPUI Component counterpart of Monaco's
/// [`IEditorDecorationsCollection`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IEditorDecorationsCollection.html).
#[derive(Clone, Debug)]
pub struct TextDecorationCollection {
    state: WeakEntity<InputBaseState<EditorMode>>,
    id: DecorationCollectionId,
}

impl TextDecorationCollection {
    /// Replace all decorations in this collection.
    ///
    /// This corresponds to Monaco's
    /// [`IEditorDecorationsCollection.set`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IEditorDecorationsCollection.html#set).
    pub fn set(&self, decorations: Vec<TextDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.decorations.set(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Add decorations to this collection.
    ///
    /// This corresponds to Monaco's
    /// [`IEditorDecorationsCollection.append`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IEditorDecorationsCollection.html#append).
    pub fn append(&self, decorations: Vec<TextDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.decorations.append(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Remove all decorations from this collection.
    ///
    /// This corresponds to Monaco's
    /// [`IEditorDecorationsCollection.clear`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IEditorDecorationsCollection.html#clear).
    pub fn clear(&self, cx: &mut App) {
        self.set(Vec::new(), cx);
    }

    /// Return the UTF-8 byte ranges in this collection.
    ///
    /// This corresponds to Monaco's
    /// [`IEditorDecorationsCollection.getRanges`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.IEditorDecorationsCollection.html#getRanges).
    pub fn get_ranges(&self, cx: &App) -> Vec<Range<usize>> {
        self.state
            .read_with(cx, |state, _| {
                state
                    .extras
                    .decorations
                    .get(self.id)
                    .unwrap_or_default()
                    .iter()
                    .map(|decoration| decoration.range.clone())
                    .collect()
            })
            .unwrap_or_default()
    }
}

/// An independently managed collection of geometric range decorations.
///
/// Clones address the same collection. Dropping a handle does not clear it; use
/// [`Self::clear`] to empty it or [`Self::dispose`] to release it permanently.
/// Operations on a disposed collection or a dropped editor are harmless no-ops.
#[derive(Clone, Debug)]
pub struct RangeDecorationCollection {
    state: WeakEntity<InputBaseState<EditorMode>>,
    id: DecorationCollectionId,
}

impl RangeDecorationCollection {
    /// Replace only this owner's decorations, clipping ranges to UTF-8 boundaries.
    pub fn set(&self, decorations: Vec<RangeDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.range_decorations.set(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Append decorations, preserving their paint order.
    pub fn append(&self, decorations: Vec<RangeDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.range_decorations.append(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Empty this collection without invalidating its handles.
    pub fn clear(&self, cx: &mut App) {
        self.set(Vec::new(), cx);
    }

    /// Release this collection, invalidating all of its cloned handles.
    pub fn dispose(&self, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            if state
                .extras
                .range_decorations
                .entries
                .remove(&self.id)
                .is_some()
            {
                cx.notify();
            }
        });
    }

    /// Read tracked UTF-8 byte ranges in insertion order.
    pub fn get_ranges(&self, cx: &App) -> Vec<Range<usize>> {
        self.state
            .read_with(cx, |state, _| {
                state
                    .extras
                    .range_decorations
                    .get(self.id)
                    .unwrap_or_default()
                    .iter()
                    .map(|decoration| decoration.range.clone())
                    .collect()
            })
            .unwrap_or_default()
    }
}

/// An independently managed collection of [`GutterDecoration`] values.
///
/// Each clone refers to the same collection. Dropping a handle does not clear it.
/// Call [`Self::clear`] to empty it or [`Self::dispose`] to release it. Calls after
/// disposal or after the editor is dropped do nothing.
#[non_exhaustive]
#[derive(Clone, Debug)]
pub struct GutterDecorationCollection {
    state: WeakEntity<InputBaseState<EditorMode>>,
    id: DecorationCollectionId,
}

/// A handle that addresses no editor, so every operation on it does nothing. It
/// can stand in for a collection until the editor that owns one exists.
impl Default for GutterDecorationCollection {
    fn default() -> Self {
        Self {
            state: WeakEntity::new_invalid(),
            id: DecorationCollectionId(0),
        }
    }
}

impl GutterDecorationCollection {
    /// Replace this collection's decorations and clip ranges to UTF-8 boundaries.
    pub fn set(&self, decorations: Vec<GutterDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.gutter_decorations.set(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Add decorations to this collection in paint order.
    pub fn append(&self, decorations: Vec<GutterDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state.extras.gutter_decorations.append(self.id, decorations) {
                cx.notify();
            }
        });
    }

    /// Empty this collection and keep its handles usable. The gutter keeps its strip.
    pub fn clear(&self, cx: &mut App) {
        self.set(Vec::new(), cx);
    }

    /// Release this collection. Its cloned handles stop working. The gutter drops
    /// its strip after the last gutter collection is released.
    pub fn dispose(&self, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            if state.extras.gutter_decorations.remove(self.id) {
                cx.notify();
            }
        });
    }

    /// Return tracked UTF-8 byte ranges in insertion order.
    pub fn get_ranges(&self, cx: &App) -> Vec<Range<usize>> {
        self.state
            .read_with(cx, |state, _| {
                state
                    .extras
                    .gutter_decorations
                    .get(self.id)
                    .unwrap_or_default()
                    .iter()
                    .map(|decoration| decoration.range.clone())
                    .collect()
            })
            .unwrap_or_default()
    }
}

/// An independently managed collection of [`OverviewRulerDecoration`] values.
///
/// Each clone refers to the same collection. Dropping a handle does not clear it.
/// Call [`Self::clear`] to empty it or [`Self::dispose`] to release it. Calls after
/// disposal or after the editor is dropped do nothing.
#[non_exhaustive]
#[derive(Clone, Debug)]
pub struct OverviewRulerDecorationCollection {
    state: WeakEntity<InputBaseState<EditorMode>>,
    id: DecorationCollectionId,
}

/// A handle that addresses no editor, so every operation on it does nothing. It
/// can stand in for a collection until the editor that owns one exists.
impl Default for OverviewRulerDecorationCollection {
    fn default() -> Self {
        Self {
            state: WeakEntity::new_invalid(),
            id: DecorationCollectionId(0),
        }
    }
}

impl OverviewRulerDecorationCollection {
    /// Replace this collection's decorations and clip ranges to UTF-8 boundaries.
    pub fn set(&self, decorations: Vec<OverviewRulerDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state
                .extras
                .overview_ruler_decorations
                .set(self.id, decorations)
            {
                cx.notify();
            }
        });
    }

    /// Add decorations to this collection in paint order.
    pub fn append(&self, decorations: Vec<OverviewRulerDecoration>, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            let decorations = normalize(&state.text, decorations);
            if state
                .extras
                .overview_ruler_decorations
                .append(self.id, decorations)
            {
                cx.notify();
            }
        });
    }

    /// Empty this collection and keep its handles usable.
    pub fn clear(&self, cx: &mut App) {
        self.set(Vec::new(), cx);
    }

    /// Release this collection. Its cloned handles stop working.
    pub fn dispose(&self, cx: &mut App) {
        let _ = self.state.update(cx, |state, cx| {
            if state.extras.overview_ruler_decorations.remove(self.id) {
                cx.notify();
            }
        });
    }

    /// Return tracked UTF-8 byte ranges in insertion order.
    pub fn get_ranges(&self, cx: &App) -> Vec<Range<usize>> {
        self.state
            .read_with(cx, |state, _| {
                state
                    .extras
                    .overview_ruler_decorations
                    .get(self.id)
                    .unwrap_or_default()
                    .iter()
                    .map(|decoration| decoration.range.clone())
                    .collect()
            })
            .unwrap_or_default()
    }
}

/// Both text styles and geometric decorations share normalization and edit affinity.
pub(crate) trait TrackedDecoration {
    /// Whether an empty range is a decoration of its own, a line boundary, rather
    /// than nothing. Such a range survives the edits that empty it and stays before
    /// text inserted at its offset.
    const KEEPS_EMPTY: bool = false;

    fn range(&self) -> &Range<usize>;
    fn range_mut(&mut self) -> &mut Range<usize>;
}

impl TrackedDecoration for TextDecoration {
    fn range(&self) -> &Range<usize> {
        &self.range
    }
    fn range_mut(&mut self) -> &mut Range<usize> {
        &mut self.range
    }
}

impl TrackedDecoration for RangeDecoration {
    fn range(&self) -> &Range<usize> {
        &self.range
    }
    fn range_mut(&mut self) -> &mut Range<usize> {
        &mut self.range
    }
}

impl TrackedDecoration for GutterDecoration {
    const KEEPS_EMPTY: bool = true;

    fn range(&self) -> &Range<usize> {
        &self.range
    }
    fn range_mut(&mut self) -> &mut Range<usize> {
        &mut self.range
    }
}

impl TrackedDecoration for OverviewRulerDecoration {
    const KEEPS_EMPTY: bool = true;

    fn range(&self) -> &Range<usize> {
        &self.range
    }
    fn range_mut(&mut self) -> &mut Range<usize> {
        &mut self.range
    }
}

/// A balanced interval index over stable insertion-order entries. Each midpoint
/// stores the maximum end of its subtree, so one document-spanning decoration
/// does not force a scan of every preceding decoration on each frame.
struct DecorationIndex {
    indices: Vec<usize>,
    max_ends: Vec<usize>,
}

impl DecorationIndex {
    fn new<T: TrackedDecoration>(decorations: &[T]) -> Self {
        let mut indices: Vec<_> = (0..decorations.len()).collect();
        indices.sort_unstable_by_key(|&ix| (decorations[ix].range().start, ix));
        let mut index = Self {
            max_ends: vec![0; indices.len()],
            indices,
        };
        index.build(decorations, 0..decorations.len());
        index
    }

    fn build<T: TrackedDecoration>(&mut self, decorations: &[T], span: Range<usize>) -> usize {
        if span.is_empty() {
            return 0;
        }
        let mid = span.start + span.len() / 2;
        let end = decorations[self.indices[mid]]
            .range()
            .end
            .max(self.build(decorations, span.start..mid))
            .max(self.build(decorations, mid + 1..span.end));
        self.max_ends[mid] = end;
        end
    }

    // Returns the number of visited nodes, allowing deterministic complexity tests.
    fn query<T: TrackedDecoration>(
        &self,
        decorations: &[T],
        span: Range<usize>,
        range: &Range<usize>,
        matches: &mut Vec<usize>,
    ) -> usize {
        if span.is_empty() || range.is_empty() {
            return 0;
        }
        // An empty decoration that is kept, a line boundary, touches the range
        // when it lies inside it, including at its start.
        let touches = |end: usize, empty: bool| {
            end > range.start || (T::KEEPS_EMPTY && empty && end == range.start)
        };
        let mid = span.start + span.len() / 2;
        if !touches(self.max_ends[mid], true) {
            return 1;
        }
        let mut visited = 1 + self.query(decorations, span.start..mid, range, matches);
        let ix = self.indices[mid];
        let candidate = decorations[ix].range();
        if candidate.start < range.end {
            if touches(candidate.end, candidate.is_empty()) {
                matches.push(ix);
            }
            visited += self.query(decorations, mid + 1..span.end, range, matches);
        }
        visited
    }
}

struct DecorationEntries<T> {
    decorations: Vec<T>,
    index: DecorationIndex,
}

impl<T: TrackedDecoration> DecorationEntries<T> {
    fn new(decorations: Vec<T>) -> Self {
        let index = DecorationIndex::new(&decorations);
        Self { decorations, index }
    }

    fn reindex(&mut self) {
        self.index = DecorationIndex::new(&self.decorations);
    }
}

pub(crate) struct DecorationCollections<T = TextDecoration> {
    entries: BTreeMap<DecorationCollectionId, DecorationEntries<T>>,
    next_id: usize,
    /// Changes whenever an owner creates, replaces, extends, clears or releases a
    /// collection, so painting can keep work derived from them until then.
    revision: u64,
}

impl<T> Default for DecorationCollections<T> {
    fn default() -> Self {
        Self {
            entries: BTreeMap::new(),
            next_id: 0,
            revision: 0,
        }
    }
}

impl<T: TrackedDecoration> DecorationCollections<T> {
    fn create(&mut self, decorations: Vec<T>) -> DecorationCollectionId {
        let id = DecorationCollectionId(self.next_id);
        self.next_id += 1;
        self.entries.insert(id, DecorationEntries::new(decorations));
        self.revision += 1;
        id
    }

    fn set(&mut self, id: DecorationCollectionId, decorations: Vec<T>) -> bool {
        let Some(current) = self.entries.get_mut(&id) else {
            return false;
        };
        *current = DecorationEntries::new(decorations);
        self.revision += 1;
        true
    }

    fn append(&mut self, id: DecorationCollectionId, decorations: Vec<T>) -> bool {
        let Some(current) = self.entries.get_mut(&id) else {
            return false;
        };
        current.decorations.extend(decorations);
        current.reindex();
        self.revision += 1;
        true
    }

    fn remove(&mut self, id: DecorationCollectionId) -> bool {
        let removed = self.entries.remove(&id).is_some();
        self.revision += u64::from(removed);
        removed
    }

    pub(super) fn revision(&self) -> u64 {
        self.revision
    }

    fn get(&self, id: DecorationCollectionId) -> Option<&[T]> {
        self.entries
            .get(&id)
            .map(|entry| entry.decorations.as_slice())
    }

    pub(super) fn adjust_for_edit(&mut self, edited_range: &Range<usize>, inserted_len: usize) {
        for entry in self.entries.values_mut() {
            let len = entry.decorations.len();
            if len == 0 || entry.index.max_ends[len / 2] <= edited_range.start {
                continue;
            }
            let mut remap = Vec::with_capacity(len);
            let mut retained = 0;
            entry.decorations.retain_mut(|decoration| {
                let range = decoration.range();
                *decoration.range_mut() = if T::KEEPS_EMPTY && range.is_empty() {
                    let offset = adjust_point_for_edit(range.start, edited_range, inserted_len);
                    offset..offset
                } else {
                    adjust_range_for_edit(range, edited_range, inserted_len)
                };
                let keep = T::KEEPS_EMPTY || !decoration.range().is_empty();
                remap.push(if keep { retained } else { usize::MAX });
                retained += usize::from(keep);
                keep
            });
            // Remap removed entries and restore start ordering when empty and
            // non-empty ranges at the same offset move with different affinity.
            entry.index.indices.retain_mut(|ix| {
                *ix = remap[*ix];
                *ix != usize::MAX
            });
            if !entry
                .index
                .indices
                .is_sorted_by_key(|&ix| (entry.decorations[ix].range().start, ix))
            {
                entry
                    .index
                    .indices
                    .sort_unstable_by_key(|&ix| (entry.decorations[ix].range().start, ix));
            }
            entry.index.max_ends.resize(retained, 0);
            entry.index.build(&entry.decorations, 0..retained);
        }
    }

    pub(super) fn clear(&mut self) {
        for entry in self.entries.values_mut() {
            *entry = DecorationEntries::new(Vec::new());
        }
        self.revision += 1;
    }

    /// Whether any collection exists, even an empty one.
    pub(super) fn has_collections(&self) -> bool {
        !self.entries.is_empty()
    }

    pub(super) fn iter(&self) -> impl Iterator<Item = &[T]> {
        self.entries
            .values()
            .map(|entry| entry.decorations.as_slice())
    }

    /// Query visible buffer spans (not the intervening folded-away text).
    /// Rebuilds happen on mutations, never in layout/paint. Preserve owner/item
    /// order after deduplicating ranges crossing multiple visible lines.
    pub(super) fn intersecting(&self, ranges: &[Range<usize>]) -> Vec<&T> {
        let mut result = Vec::new();
        for entry in self.entries.values() {
            let mut matches = Vec::new();
            for range in ranges {
                entry.index.query(
                    &entry.decorations,
                    0..entry.decorations.len(),
                    range,
                    &mut matches,
                );
            }
            matches.sort_unstable();
            matches.dedup();
            result.extend(matches.into_iter().map(|ix| &entry.decorations[ix]));
        }
        result
    }
}

fn adjust_range_for_edit(
    range: &Range<usize>,
    edited_range: &Range<usize>,
    inserted_len: usize,
) -> Range<usize> {
    let removed_len = edited_range.end.saturating_sub(edited_range.start);
    let shift = |offset: usize| {
        if inserted_len >= removed_len {
            offset.saturating_add(inserted_len - removed_len)
        } else {
            offset.saturating_sub(removed_len - inserted_len)
        }
    };

    if edited_range.is_empty() {
        let start = if range.start < edited_range.start {
            range.start
        } else {
            shift(range.start)
        };
        let end = if range.end <= edited_range.start {
            range.end
        } else {
            shift(range.end)
        };
        return start..end;
    }

    let inserted_end = edited_range.start + inserted_len;
    let start = if range.start <= edited_range.start {
        range.start
    } else if range.start >= edited_range.end {
        shift(range.start)
    } else {
        edited_range.start
    };
    let end = if range.end <= edited_range.start {
        range.end
    } else if range.end >= edited_range.end {
        shift(range.end)
    } else {
        inserted_end
    };
    start..end
}

/// A point stays before text inserted at its offset, and a replacement that covers
/// it moves it to where the replacement starts.
fn adjust_point_for_edit(offset: usize, edited_range: &Range<usize>, inserted_len: usize) -> usize {
    if offset <= edited_range.start {
        offset
    } else if offset >= edited_range.end {
        (offset + inserted_len).saturating_sub(edited_range.len())
    } else {
        edited_range.start
    }
}

fn normalize<T: TrackedDecoration>(text: &Rope, decorations: Vec<T>) -> Vec<T> {
    decorations
        .into_iter()
        .filter_map(|mut decoration| {
            let range = decoration.range();
            // Reject reversed ranges before clipping, which could otherwise turn a
            // reversed pair within a multibyte character into a nonempty range, and
            // ranges past the end, which clipping would otherwise turn into a
            // boundary at the end of the document.
            if range.start > range.end
                || range.start > text.len()
                || (range.is_empty() && !T::KEEPS_EMPTY)
            {
                return None;
            }
            let start = text.clip_offset(range.start, Bias::Left);
            let range = if range.is_empty() {
                start..start
            } else {
                start..text.clip_offset(range.end, Bias::Right)
            };
            if range.is_empty() && !T::KEEPS_EMPTY {
                return None;
            }
            *decoration.range_mut() = range;
            Some(decoration)
        })
        .collect()
}

impl InputBaseState<EditorMode> {
    /// Create an independently owned collection of geometric range decorations.
    ///
    /// Ranges use UTF-8 byte offsets and the same tracking as text decorations:
    /// insertion at either edge does not expand the range, insertion inside does,
    /// replacement clips overlapping anchors, and deletion removes empty ranges.
    /// Undo, redo, whole-document replacement and formatting apply these same edit
    /// transforms; decorations themselves are not undo history, so deleted ranges
    /// are not resurrected by undo. Folding changes projection, not stored ranges.
    ///
    /// Fills paint behind frames; within each style, later collections/items paint
    /// over earlier ones. Neither affects text layout, hit testing or focus. The
    /// default color is the editor foreground (12% opacity for fills).
    /// Collections live until explicitly disposed or the editor is dropped.
    pub fn create_range_decorations_collection(
        &mut self,
        decorations: Vec<RangeDecoration>,
        cx: &mut Context<Self>,
    ) -> RangeDecorationCollection {
        let id = self
            .extras
            .range_decorations
            .create(normalize(&self.text, decorations));
        cx.notify();
        RangeDecorationCollection {
            state: cx.entity().downgrade(),
            id,
        }
    }

    /// Create an independently managed collection of text decorations.
    ///
    /// This follows Monaco's
    /// [`createDecorationsCollection`](https://microsoft.github.io/monaco-editor/typedoc/interfaces/editor_editor_api.editor.ICodeEditor.html#createDecorationsCollection)
    /// ownership model. Ranges use UTF-8 byte offsets into [`Self::value`].
    ///
    /// Decoration ranges follow text edits and do not need to be set again
    /// after each change. Insertions at a range boundary do not expand the
    /// range, matching Monaco's
    /// [`NeverGrowsWhenTypingAtEdges`](https://microsoft.github.io/monaco-editor/typedoc/enums/editor_editor_api.editor.TrackedRangeStickiness.html#NeverGrowsWhenTypingAtEdges)
    /// behavior. Decorations are not rendered while the input is masked.
    /// Collections live until their [`InputBaseState`] is dropped.
    ///
    /// Collections are layered in insertion order; the first collection wins
    /// when overlapping decorations set the same [`HighlightStyle`] property.
    /// Callers should avoid conflicting overlaps within one collection.
    pub fn create_decorations_collection(
        &mut self,
        decorations: Vec<TextDecoration>,
        cx: &mut Context<Self>,
    ) -> TextDecorationCollection {
        let decorations = normalize(&self.text, decorations);
        let id = self.extras.decorations.create(decorations);
        cx.notify();
        TextDecorationCollection {
            state: cx.entity().downgrade(),
            id,
        }
    }

    /// Create a collection of gutter marks, such as added, modified, and deleted
    /// lines in a version-control diff.
    ///
    /// Marks draw in a strip before the line numbers. The strip stays reserved while
    /// any gutter collection exists, including an empty collection, so the text does
    /// not shift when marks change. Release every collection to drop the strip. Its
    /// width is [`Self::gutter_decorations_width`].
    ///
    /// Ranges track edits as [range decorations](Self::create_range_decorations_collection)
    /// do, but empty ranges are kept. They stay before text inserted at their offset,
    /// and a range that an edit empties becomes a boundary. A mark whose range starts
    /// inside a fold draws a bar on the fold's row, using its
    /// [folded color](GutterDecoration::with_folded_color), and marks the lines of the
    /// range after the fold as usual. Later collections and
    /// items draw over earlier ones. After you recompute the decorations, call
    /// [`set`](GutterDecorationCollection::set) with the whole collection. Tracking
    /// keeps marks on their lines between updates.
    pub fn create_gutter_decorations_collection(
        &mut self,
        decorations: Vec<GutterDecoration>,
        cx: &mut Context<Self>,
    ) -> GutterDecorationCollection {
        let id = self
            .extras
            .gutter_decorations
            .create(normalize(&self.text, decorations));
        cx.notify();
        GutterDecorationCollection {
            state: cx.entity().downgrade(),
            id,
        }
    }

    /// Create a collection of marks on the vertical scrollbar track, Monaco's
    /// overview ruler.
    ///
    /// Each mark uses its [lane](OverviewRulerLane) at the rows' share of the content
    /// height. It is at least 6 px tall. Touching marks with the same color merge.
    /// Marks draw under Base's scrollbar or one supplied with
    /// [`Self::set_scrollbar_renderer`], so they remain visible while the thumb fades.
    /// Ranges track edits as [gutter decorations](Self::create_gutter_decorations_collection)
    /// do.
    pub fn create_overview_ruler_decorations_collection(
        &mut self,
        decorations: Vec<OverviewRulerDecoration>,
        cx: &mut Context<Self>,
    ) -> OverviewRulerDecorationCollection {
        let id = self
            .extras
            .overview_ruler_decorations
            .create(normalize(&self.text, decorations));
        cx.notify();
        OverviewRulerDecorationCollection {
            state: cx.entity().downgrade(),
            id,
        }
    }

    /// Set the width of the strip that [gutter decorations](Self::create_gutter_decorations_collection)
    /// draw in. The default is 3 px.
    pub fn gutter_decorations_width(mut self, width: Pixels) -> Self {
        self.extras.gutter_decorations_width = width;
        self
    }

    /// Set the width of the strip that gutter decorations draw in.
    pub fn set_gutter_decorations_width(&mut self, width: Pixels, cx: &mut Context<Self>) {
        if self.extras.gutter_decorations_width != width {
            self.extras.gutter_decorations_width = width;
            cx.notify();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn geometric_collections_share_utf8_normalization_and_edit_affinity() {
        let mut collections = DecorationCollections::<RangeDecoration>::default();
        let text = Rope::from("héllo world");
        let first = collections.create(normalize(
            &text,
            vec![
                RangeDecoration::new(2..4),
                RangeDecoration::new(2..1),
                RangeDecoration::new(100..200),
            ],
        ));
        let second = collections.create(normalize(&text, vec![RangeDecoration::new(7..12)]));
        assert_eq!(collections.get(first).unwrap()[0].range(), &(1..4));
        assert_eq!(collections.get(first).unwrap().len(), 1);
        collections.adjust_for_edit(&(1..1), 2);
        assert_eq!(collections.get(first).unwrap()[0].range(), &(3..6));
        collections.adjust_for_edit(&(6..6), 1);
        assert_eq!(collections.get(first).unwrap()[0].range(), &(3..6));
        collections.adjust_for_edit(&(4..4), 2);
        assert_eq!(collections.get(first).unwrap()[0].range(), &(3..8));
        collections.adjust_for_edit(&(3..8), 0);
        assert!(collections.get(first).unwrap().is_empty());
        assert!(!collections.get(second).unwrap().is_empty());
        collections.entries.remove(&first);
        let third = collections.create(vec![]);
        assert_ne!(third, first);
        assert!(!collections.set(first, vec![RangeDecoration::new(0..1)]));
        assert!(collections.get(second).is_some());
    }

    #[test]
    fn gutter_collections_keep_empty_ranges_as_line_boundaries() {
        let mut collections = DecorationCollections::<GutterDecoration>::default();
        let text = Rope::from("one\ntwo\nthree");
        let id = collections.create(normalize(
            &text,
            vec![
                GutterDecoration::new(4..4),
                GutterDecoration::new(8..13),
                GutterDecoration::new(9..8),
                GutterDecoration::new(100..100),
                GutterDecoration::new(100..200),
                GutterDecoration::new(13..13),
            ],
        ));
        let ranges = |collections: &DecorationCollections<GutterDecoration>| {
            collections
                .get(id)
                .unwrap()
                .iter()
                .map(|decoration| decoration.range().clone())
                .collect::<Vec<_>>()
        };
        // Reversed ranges and ranges past the end are dropped; a boundary at the
        // end of the document is kept.
        assert_eq!(ranges(&collections), vec![4..4, 8..13, 13..13]);
        // Text typed at a boundary goes after it.
        collections.adjust_for_edit(&(4..4), 2);
        assert_eq!(ranges(&collections), vec![4..4, 10..15, 15..15]);
        // Deleting the lines a bar covers leaves a boundary where they were.
        collections.adjust_for_edit(&(10..15), 0);
        assert_eq!(ranges(&collections), vec![4..4, 10..10, 10..10]);
        // A replacement covering a boundary moves it to the replacement's start.
        collections.adjust_for_edit(&(2..6), 1);
        assert_eq!(ranges(&collections), vec![2..2, 7..7, 7..7]);
    }

    #[test]
    fn gutter_queries_find_boundaries_inside_the_span() {
        let mut collections = DecorationCollections::<GutterDecoration>::default();
        collections.create(vec![
            GutterDecoration::new(4..4),
            GutterDecoration::new(8..13),
            GutterDecoration::new(13..13),
            GutterDecoration::new(20..20),
        ]);
        let ranges = |query: Range<usize>| {
            collections
                .intersecting(&[query])
                .iter()
                .map(|decoration| decoration.range().clone())
                .collect::<Vec<_>>()
        };
        // A boundary at the span's start is inside it; one at its end is not.
        assert_eq!(ranges(4..13), vec![4..4, 8..13]);
        assert_eq!(ranges(13..21), vec![13..13, 20..20]);
        assert_eq!(ranges(5..8), Vec::<Range<usize>>::new());
    }

    #[test]
    fn gutter_query_keeps_index_order_after_inserting_at_mixed_ranges() {
        let mut collections = DecorationCollections::<GutterDecoration>::default();
        collections.create(vec![
            GutterDecoration::new(4..8),
            GutterDecoration::new(4..8),
            GutterDecoration::new(4..4),
        ]);
        collections.adjust_for_edit(&(4..4), 1);
        let ranges: Vec<_> = collections
            .intersecting(&[4..5])
            .into_iter()
            .map(|decoration| decoration.range().clone())
            .collect();
        assert_eq!(ranges, vec![4..4]);
    }

    #[test]
    fn visible_query_preserves_layers_and_skips_folded_spans() {
        let mut collections = DecorationCollections::<RangeDecoration>::default();
        let first = collections.create(vec![
            RangeDecoration::new(90..100),
            RangeDecoration::new(0..100),
            RangeDecoration::new(40..50), // hidden in a fold
            RangeDecoration::new(0..5),
        ]);
        collections.create(vec![RangeDecoration::new(2..4)]);
        let ranges = |collections: &DecorationCollections<RangeDecoration>| {
            collections
                .intersecting(&[0..5, 90..100])
                .iter()
                .map(|d| d.range().clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(ranges(&collections), vec![90..100, 0..100, 0..5, 2..4]);
        collections.adjust_for_edit(&(0..0), 1);
        assert_eq!(ranges(&collections), vec![91..101, 1..101, 1..6, 3..5]);
        collections.set(first, vec![RangeDecoration::new(50..60)]);
        assert_eq!(ranges(&collections), vec![3..5]);
    }

    #[test]
    fn interval_index_culls_large_collections_even_with_a_spanning_range() {
        let mut decorations: Vec<_> = (0..100_000)
            .map(|ix| RangeDecoration::new(ix * 10..ix * 10 + 5))
            .collect();
        decorations.push(RangeDecoration::new(0..1_000_000));
        let index = DecorationIndex::new(&decorations);
        for query in [
            0..1,
            500_000..500_020,
            999_990..1_000_001,
            1_000_000..1_000_010,
        ] {
            let mut matches = Vec::new();
            let visited = index.query(&decorations, 0..decorations.len(), &query, &mut matches);
            matches.sort_unstable();
            let expected: Vec<_> = decorations
                .iter()
                .enumerate()
                .filter_map(|(ix, d)| {
                    (d.range.start < query.end && d.range.end > query.start).then_some(ix)
                })
                .collect();
            assert_eq!(matches, expected);
            assert!(visited < 100, "visited {visited} nodes for {query:?}");
        }
    }

    #[test]
    fn interval_index_matches_linear_reference_for_overlaps_and_mutations() {
        let mut collections = DecorationCollections::<RangeDecoration>::default();
        let id = collections.create(
            (0..512)
                .map(|ix| {
                    let start = (ix * 37) % 997;
                    RangeDecoration::new(start..start + ix % 61 + 1)
                })
                .collect(),
        );
        for edit in [0..0, 300..450, 900..1100] {
            collections.adjust_for_edit(&edit, 3);
            for start in (0..1100).step_by(13) {
                let query = start..start + 17;
                let expected: Vec<_> = collections
                    .get(id)
                    .unwrap()
                    .iter()
                    .filter(|d| d.range.start < query.end && d.range.end > query.start)
                    .map(|d| d.range.clone())
                    .collect();
                let actual: Vec<_> = collections
                    .intersecting(&[query])
                    .iter()
                    .map(|d| d.range.clone())
                    .collect();
                assert_eq!(actual, expected);
            }
        }
    }

    #[test]
    fn collections_are_independent_and_ranges_are_clipped() {
        let text = Rope::from("héllo");
        let first_style = HighlightStyle {
            font_weight: Some(gpui::FontWeight::BOLD),
            ..Default::default()
        };
        let second_style = HighlightStyle {
            background_color: Some(gpui::red()),
            ..Default::default()
        };
        let mut collections = DecorationCollections::default();

        let first = collections.create(normalize(
            &text,
            vec![TextDecoration::new(2..4, first_style)],
        ));
        let second = collections.create(normalize(
            &text,
            vec![TextDecoration::new(5..100, second_style)],
        ));

        assert_ne!(first, second);
        assert_eq!(
            collections.get(first),
            Some(&[TextDecoration::new(1..4, first_style)][..])
        );
        assert_eq!(
            collections.get(second),
            Some(&[TextDecoration::new(5..6, second_style)][..])
        );

        assert!(collections.append(first, vec![TextDecoration::new(4..5, second_style)]));
        assert_eq!(
            collections.get(first),
            Some(
                &[
                    TextDecoration::new(1..4, first_style),
                    TextDecoration::new(4..5, second_style),
                ][..]
            )
        );

        assert!(collections.set(first, Vec::new()));
        assert_eq!(collections.get(first), Some(&[][..]));
        assert_eq!(
            collections.get(second),
            Some(&[TextDecoration::new(5..6, second_style)][..])
        );
    }

    #[test]
    fn decoration_ranges_follow_text_edits() {
        let style = HighlightStyle::default();
        let mut collections = DecorationCollections::default();
        let collection = collections.create(vec![TextDecoration::new(2..6, style)]);

        collections.adjust_for_edit(&(0..0), 2);
        assert_eq!(
            collections.get(collection),
            Some(&[TextDecoration::new(4..8, style)][..])
        );

        collections.adjust_for_edit(&(6..6), 2);
        assert_eq!(
            collections.get(collection),
            Some(&[TextDecoration::new(4..10, style)][..])
        );

        collections.adjust_for_edit(&(4..10), 3);
        assert_eq!(
            collections.get(collection),
            Some(&[TextDecoration::new(4..7, style)][..])
        );

        assert_eq!(adjust_range_for_edit(&(2..6), &(2..2), 2), 4..8);
        assert_eq!(adjust_range_for_edit(&(2..6), &(6..6), 2), 2..6);
        assert_eq!(adjust_range_for_edit(&(2..6), &(2..6), 3), 2..5);
    }
}
