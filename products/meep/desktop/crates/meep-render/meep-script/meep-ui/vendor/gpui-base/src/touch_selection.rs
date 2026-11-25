//! Touch selection geometry shared by the input engine and window text
//! selection.
//!
//! A touch selection is one made by a long press. It differs from a pointer
//! selection in what the user needs afterwards: a grab handle at each end to
//! adjust it, since a finger cannot hover an I-beam, and an edit menu next to
//! it, since there is no right click. Base owns the gesture, the handle drag
//! and the menu lifecycle; this module carries what a presentation layer needs
//! to draw them. The handles and the menu themselves are drawn by the styled
//! layer, which also decides how large a handle's touch target is.

use gpui::{Bounds, Hsla, Pixels, Point, Window, fill, point, px, size};

/// One end of a selection, as a touch handle grabs it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum SelectionEdge {
    /// The end before the first selected character.
    Start,
    /// The end after the last selected character.
    End,
}

impl SelectionEdge {
    /// The end that stays put while this one is dragged.
    pub const fn opposite(self) -> Self {
        match self {
            Self::Start => Self::End,
            Self::End => Self::Start,
        }
    }
}

/// Where a touch selection's ends are laid out this frame, and what the
/// gesture is doing to them.
///
/// Each end is the caret line box at that end in window coordinates: zero
/// width, one line tall, at the character boundary. An empty selection has
/// both ends at the caret. Built only by Base; a presentation layer reads it
/// to draw the handles and place the edit menu.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TouchSelectionSnapshot {
    start: Bounds<Pixels>,
    end: Bounds<Pixels>,
    /// Whether each end is inside its owner's viewport. An end scrolled out
    /// of view keeps its geometry, for the drag that holds the other end,
    /// but gets no handle.
    start_visible: bool,
    end_visible: bool,
    menu_open: bool,
    dragging: Option<SelectionEdge>,
}

impl TouchSelectionSnapshot {
    pub(crate) const fn new(start: Bounds<Pixels>, end: Bounds<Pixels>) -> Self {
        Self {
            start,
            end,
            start_visible: true,
            end_visible: true,
            menu_open: false,
            dragging: None,
        }
    }

    pub(crate) const fn with_edge_visible(mut self, edge: SelectionEdge, visible: bool) -> Self {
        match edge {
            SelectionEdge::Start => self.start_visible = visible,
            SelectionEdge::End => self.end_visible = visible,
        }
        self
    }

    pub(crate) const fn with_menu_open(mut self, menu_open: bool) -> Self {
        self.menu_open = menu_open;
        self
    }

    pub(crate) const fn with_dragging(mut self, dragging: Option<SelectionEdge>) -> Self {
        self.dragging = dragging;
        self
    }

    /// The caret line box before the first selected character.
    pub const fn start(&self) -> Bounds<Pixels> {
        self.start
    }

    /// The caret line box after the last selected character.
    pub const fn end(&self) -> Bounds<Pixels> {
        self.end
    }

    /// The caret line box at the given end.
    pub const fn edge(&self, edge: SelectionEdge) -> Bounds<Pixels> {
        match edge {
            SelectionEdge::Start => self.start,
            SelectionEdge::End => self.end,
        }
    }

    /// Whether the given end is in view. A handle is drawn only for an end
    /// that is; the menu anchors to the ends that are.
    pub const fn is_edge_visible(&self, edge: SelectionEdge) -> bool {
        match edge {
            SelectionEdge::Start => self.start_visible,
            SelectionEdge::End => self.end_visible,
        }
    }

    /// Whether the selection is a bare caret, which gets a menu but no handles.
    pub fn is_empty(&self) -> bool {
        self.start == self.end
    }

    /// The smallest box holding the ends in view, for anchoring the edit
    /// menu. `None` when the whole selection is scrolled away.
    pub fn bounds(&self) -> Option<Bounds<Pixels>> {
        match (self.start_visible, self.end_visible) {
            (true, true) => Some(self.start.union(&self.end)),
            (true, false) => Some(self.start),
            (false, true) => Some(self.end),
            (false, false) => None,
        }
    }

    /// Whether the edit menu is open. It closes while a handle is dragged and
    /// reopens when the drag ends.
    pub const fn is_menu_open(&self) -> bool {
        self.menu_open
    }

    /// The end currently being dragged by its handle.
    pub const fn dragging(&self) -> Option<SelectionEdge> {
        self.dragging
    }
}

/// The grab handle at one end of a touch selection: a bar down the caret
/// line with a knob at its outer end, the start's above and the end's below.
///
/// Base paints the handle where it belongs in the paint order — inside the
/// text that owns the selection, so that whatever covers the text covers
/// the handle — and only with the selection's own color. Its shape is the
/// one every platform draws; a styled layer supplies the color.
pub struct TouchHandle;

impl TouchHandle {
    /// How wide the finger may miss the knob and still take it.
    pub const HIT_SIZE: Pixels = px(44.);
    /// The knob's diameter.
    pub const KNOB_SIZE: Pixels = px(10.);
    /// The bar down the caret line.
    pub const BAR_WIDTH: Pixels = px(2.);
    /// Room the knob takes beyond the line, which an edit menu keeps clear.
    pub const EXTENT: Pixels = px(12.);

    /// The touch target, centered on the caret and reaching out past the knob.
    pub fn hit_bounds(edge: SelectionEdge, caret: Bounds<Pixels>) -> Bounds<Pixels> {
        let top = match edge {
            SelectionEdge::Start => caret.top() - Self::EXTENT,
            SelectionEdge::End => caret.top(),
        };
        Bounds::new(
            point(caret.left() - Self::HIT_SIZE / 2., top),
            size(Self::HIT_SIZE, caret.size.height + Self::EXTENT),
        )
    }

    /// Paints the handle for `edge` on the caret line box `caret`.
    pub fn paint(edge: SelectionEdge, caret: Bounds<Pixels>, color: Hsla, window: &mut Window) {
        let bar = Bounds::new(
            point(caret.left() - Self::BAR_WIDTH / 2., caret.top()),
            size(Self::BAR_WIDTH, caret.size.height),
        );
        let knob_top = match edge {
            SelectionEdge::Start => caret.top() - Self::KNOB_SIZE,
            SelectionEdge::End => caret.bottom(),
        };
        let knob = Bounds::new(
            point(caret.left() - Self::KNOB_SIZE / 2., knob_top),
            size(Self::KNOB_SIZE, Self::KNOB_SIZE),
        );
        window.paint_quad(fill(bar, color));
        window.paint_quad(fill(knob, color).corner_radii(Self::KNOB_SIZE / 2.));
    }
}

/// The caret line box at `position`, for reporting a selection end.
pub(crate) fn caret_line_box(position: Point<Pixels>, line_height: Pixels) -> Bounds<Pixels> {
    Bounds::new(position, size(px(0.), line_height))
}

/// Whether a caret line box shows inside `viewport`: its line overlaps the
/// viewport vertically and its x lies within it. A zero-width box never
/// intersects anything, so this is not `Bounds::intersects`.
pub(crate) fn caret_in_view(caret: Bounds<Pixels>, viewport: Bounds<Pixels>) -> bool {
    caret.bottom() > viewport.top()
        && caret.top() < viewport.bottom()
        && caret.left() >= viewport.left()
        && caret.left() <= viewport.right()
}

/// Maps a finger to the text position a handle drag selects.
///
/// The knob a finger holds sits above or below the line, so the finger itself
/// is never over the text it moves. The offset from the finger to the caret
/// box is captured when the drag begins and kept for the rest of it; the
/// mapped point then picks lines exactly as a pointer does, crossing into the
/// line above or below at its edge.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct EdgeDrag {
    edge: SelectionEdge,
    offset: Point<Pixels>,
}

impl EdgeDrag {
    pub(crate) fn begin(edge: SelectionEdge, caret: Bounds<Pixels>, finger: Point<Pixels>) -> Self {
        Self {
            edge,
            offset: caret.center() - finger,
        }
    }

    pub(crate) const fn edge(&self) -> SelectionEdge {
        self.edge
    }

    /// The finger dragged its end past the other one; it now holds that one.
    pub(crate) fn set_edge(&mut self, edge: SelectionEdge) {
        self.edge = edge;
    }

    /// The text position the finger points at.
    pub(crate) fn text_position(&self, finger: Point<Pixels>) -> Point<Pixels> {
        point(finger.x + self.offset.x, finger.y + self.offset.y)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_reports_bounds_and_edges() {
        let start = caret_line_box(point(px(10.), px(20.)), px(16.));
        let end = caret_line_box(point(px(80.), px(52.)), px(16.));
        let snapshot = TouchSelectionSnapshot::new(start, end)
            .with_menu_open(true)
            .with_dragging(Some(SelectionEdge::End));

        assert_eq!(snapshot.edge(SelectionEdge::Start), start);
        assert_eq!(snapshot.edge(SelectionEdge::End), end);
        assert!(!snapshot.is_empty());
        assert!(snapshot.is_menu_open());
        assert_eq!(snapshot.dragging(), Some(SelectionEdge::End));
        assert_eq!(
            snapshot.bounds(),
            Some(Bounds::from_corners(
                point(px(10.), px(20.)),
                point(px(80.), px(68.))
            ))
        );

        let caret = TouchSelectionSnapshot::new(start, start);
        assert!(caret.is_empty());
    }

    #[test]
    fn a_scrolled_away_end_keeps_its_geometry_but_no_handle() {
        let start = caret_line_box(point(px(10.), px(-30.)), px(16.));
        let end = caret_line_box(point(px(80.), px(52.)), px(16.));
        let viewport = Bounds::new(point(px(0.), px(0.)), size(px(200.), px(100.)));
        assert!(!caret_in_view(start, viewport));
        assert!(caret_in_view(end, viewport));

        let snapshot =
            TouchSelectionSnapshot::new(start, end).with_edge_visible(SelectionEdge::Start, false);
        assert!(!snapshot.is_edge_visible(SelectionEdge::Start));
        assert_eq!(snapshot.edge(SelectionEdge::Start), start);
        assert_eq!(snapshot.bounds(), Some(end));

        let gone = snapshot.with_edge_visible(SelectionEdge::End, false);
        assert_eq!(gone.bounds(), None);
    }

    #[test]
    fn edge_drag_keeps_the_finger_offset() {
        let caret = caret_line_box(point(px(100.), px(40.)), px(20.));
        let drag = EdgeDrag::begin(SelectionEdge::End, caret, point(px(102.), px(72.)));
        assert_eq!(drag.edge(), SelectionEdge::End);
        // The finger started 22px below the caret's center; it stays there.
        assert_eq!(
            drag.text_position(point(px(150.), px(90.))),
            point(px(148.), px(68.))
        );
    }
}
