use std::collections::HashMap;

use gpui::{ElementId, Hsla, SharedString};

use super::{DiffLinePosition, DiffLineRange, DiffSide};

/// A background that marks source lines in place, without changing the
/// selection, copying or layout.
///
/// Decorations paint above the change background and below inline emphasis,
/// search highlights and text; a selected line shows the selection instead.
/// Where several decorations cover a line, the last supplied one is shown.
#[derive(Clone)]
pub struct DiffDecoration {
    range: DiffLineRange,
    background: Option<Hsla>,
}

impl DiffDecoration {
    /// Marks the lines of `range`.
    ///
    /// A range that ends on the other side covers its start side from
    /// `start` onwards and its end side up to `end`.
    pub fn new(range: DiffLineRange) -> Self {
        Self {
            range,
            background: None,
        }
    }
    /// Sets the background, which defaults to a translucent warning color.
    pub fn with_background(mut self, background: impl Into<Hsla>) -> Self {
        self.background = Some(background.into());
        self
    }
    pub fn range(&self) -> &DiffLineRange {
        &self.range
    }
    /// The background set with [`Self::with_background`].
    pub fn background(&self) -> Option<Hsla> {
        self.background
    }

    fn contains(&self, side: DiffSide, line: usize) -> bool {
        let range = &self.range;
        if range.is_single_side() {
            side == range.side() && (range.start()..=range.end()).contains(&line)
        } else if side == range.side() {
            line >= range.start()
        } else {
            line <= range.end()
        }
    }
}

/// An interactive marker in the lane between the line numbers and the code,
/// such as a comment or diagnostic indicator that opens a details panel.
///
/// The application renders it with [`super::Diff::render_gutter_marker`],
/// usually as a small button, and owns the panel and its focus.
#[derive(Clone)]
pub struct DiffGutterMarker {
    id: ElementId,
    position: DiffLinePosition,
    label: SharedString,
}

impl DiffGutterMarker {
    /// Places a marker beside a source line.
    pub fn new(id: impl Into<ElementId>, position: DiffLinePosition) -> Self {
        Self {
            id: id.into(),
            position,
            label: SharedString::default(),
        }
    }
    /// Sets the accessible label that the rendered marker should announce.
    pub fn with_label(mut self, label: impl Into<SharedString>) -> Self {
        self.label = label.into();
        self
    }
    pub fn id(&self) -> &ElementId {
        &self.id
    }
    pub fn position(&self) -> &DiffLinePosition {
        &self.position
    }
    pub fn label(&self) -> &SharedString {
        &self.label
    }
}

/// Decorations by file path, in supplied order.
#[derive(Default)]
pub(super) struct Decorations {
    files: HashMap<SharedString, Vec<DiffDecoration>>,
}

impl Decorations {
    pub(super) fn new(decorations: impl IntoIterator<Item = DiffDecoration>) -> Self {
        let mut index = Self::default();
        for decoration in decorations {
            index
                .files
                .entry(decoration.range.path().clone())
                .or_default()
                .push(decoration);
        }
        index
    }

    /// The decoration shown on a line: the last supplied one covering it.
    pub(super) fn at(&self, position: &DiffLinePosition) -> Option<&DiffDecoration> {
        self.files
            .get(position.path())?
            .iter()
            .rev()
            .find(|decoration| decoration.contains(position.side(), position.line()))
    }
}

/// Gutter markers by line, keeping the first supplied for each line.
#[derive(Default)]
pub(super) struct GutterMarkers {
    lines: HashMap<DiffLinePosition, DiffGutterMarker>,
}

impl GutterMarkers {
    pub(super) fn new(markers: impl IntoIterator<Item = DiffGutterMarker>) -> Self {
        let mut index = Self::default();
        for marker in markers {
            index.lines.entry(marker.position.clone()).or_insert(marker);
        }
        index
    }

    pub(super) fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }

    pub(super) fn at(&self, position: &DiffLinePosition) -> Option<&DiffGutterMarker> {
        self.lines.get(position)
    }
}
