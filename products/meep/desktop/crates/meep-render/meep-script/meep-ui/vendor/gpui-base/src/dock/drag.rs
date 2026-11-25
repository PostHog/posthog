//! Drag hit-testing and drop geometry for the dock.
//!
//! This module decides *where* a drop would land and what shape a hovering
//! drag session occupies. It draws nothing: the styled drag preview and the
//! rendered drop indicator are appearance and live in `crates/component`.

use std::{
    any::Any,
    cell::Cell,
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

use gpui::{
    Bounds, Context, Empty, IntoElement, Pixels, Point, Render, Size, Window, point, px, size,
};

use crate::Placement;

use super::layout::{NodeId, PanelId};

/// A panel being dragged out of a tab group.
///
/// The panel is carried as a [`PanelId`] rather than a view handle: the base
/// layer has no `PanelView` trait or `TabPanel` entity of its own (those are
/// layered above), and the layout algebra already addresses panels this way
/// (see `insert_panel`/`remove_panel`/`move_panel` in `layout::edit`). A
/// consumer resolves the id back to a view through the dock area's panel
/// map.
#[derive(Clone)]
pub struct DragPanel {
    panel: PanelId,
    source: NodeId,
    drag_offset: Rc<Cell<Point<Pixels>>>,
    preview_size: Rc<Cell<Size<Pixels>>>,
    drag_session_id: u64,
}

static NEXT_DRAG_SESSION_ID: AtomicU64 = AtomicU64::new(1);

/// Stands in for [`DragPanel::drag_session_id`] on host-owned drag items, which
/// carry no session of their own. `NEXT_DRAG_SESSION_ID` starts at 1, so 0 never
/// collides.
pub(crate) const ITEM_DRAG_SESSION_ID: u64 = 0;

impl DragPanel {
    pub fn new(panel: PanelId, source: NodeId) -> Self {
        Self {
            panel,
            source,
            drag_offset: Rc::new(Cell::new(Point::default())),
            preview_size: Rc::new(Cell::new(Size::default())),
            drag_session_id: NEXT_DRAG_SESSION_ID.fetch_add(1, Ordering::Relaxed),
        }
    }

    pub fn panel(&self) -> PanelId {
        self.panel
    }

    /// The tab group this panel was dragged out of.
    pub fn source(&self) -> NodeId {
        self.source
    }

    pub fn drag_offset(&self) -> Point<Pixels> {
        self.drag_offset.get()
    }

    /// Records where inside the panel the drag started, so a preview can be
    /// positioned relative to the cursor.
    pub fn set_drag_offset(&self, offset: Point<Pixels>) {
        self.drag_offset.set(offset);
    }

    /// How large the drag preview is on screen.
    ///
    /// The dock reads it to decide where a drop placeholder flies in from,
    /// which is hit geometry rather than styling; the preview's own size is a
    /// visual decision, so the skin that draws the preview reports it here.
    /// Defaults to zero, which degrades to a placeholder that grows out of the
    /// cursor rather than out of the preview.
    pub fn preview_size(&self) -> Size<Pixels> {
        self.preview_size.get()
    }

    pub fn set_preview_size(&self, size: Size<Pixels>) {
        self.preview_size.set(size);
    }

    pub fn drag_session_id(&self) -> u64 {
        self.drag_session_id
    }
}

impl Render for DragPanel {
    /// Base draws nothing: the styled drag preview is appearance and belongs
    /// to `crates/component`, which reintroduces it as a separate render type.
    fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

/// A host-owned value being dragged over the dock, opaque to the dock itself.
#[derive(Clone, Debug)]
pub struct AnyDrag {
    value: Arc<dyn Any>,
}

impl AnyDrag {
    pub fn new(value: impl Any) -> Self {
        Self {
            value: Arc::new(value),
        }
    }

    pub fn value(&self) -> &Arc<dyn Any> {
        &self.value
    }
}

/// Where a host-owned drag landed: a tab group, and the edge it resolved.
///
/// A split layout has no free coordinates, so the container reports the group
/// and the placement instead of a position. `placement` is `None` for the
/// centre zone, meaning merge into the group rather than split.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DropTarget {
    node: NodeId,
    placement: Option<Placement>,
}

impl DropTarget {
    pub(crate) fn new(node: NodeId, placement: Option<Placement>) -> Self {
        Self { node, placement }
    }

    pub fn node(&self) -> NodeId {
        self.node
    }

    pub fn placement(&self) -> Option<Placement> {
        self.placement
    }
}

/// What the skin should draw while a drag hovers a group.
///
/// It carries geometry over time — where the placeholder comes from, where it
/// settles, and which run of the animation this is — but not the tween. Easing
/// and duration are styling and belong to the skin that draws it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DropIndicator {
    bounds: Bounds<Pixels>,
    placement: Option<Placement>,
    from: DropPlaceholderBounds,
    to: DropPlaceholderBounds,
    drag_session_id: u64,
    epoch: u64,
}

impl DropIndicator {
    pub(crate) fn new(
        bounds: Bounds<Pixels>,
        placement: Option<Placement>,
        from: DropPlaceholderBounds,
        to: DropPlaceholderBounds,
        drag_session_id: u64,
        epoch: u64,
    ) -> Self {
        Self {
            bounds,
            placement,
            from,
            to,
            drag_session_id,
            epoch,
        }
    }

    /// The hovered group's content bounds, in window coordinates.
    pub fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }

    /// `None` means the drop merges into the tab group.
    pub fn placement(&self) -> Option<Placement> {
        self.placement
    }

    /// Where the placeholder starts, relative to [`Self::bounds`].
    pub fn from(&self) -> DropPlaceholderBounds {
        self.from
    }

    /// Where the placeholder settles, relative to [`Self::bounds`].
    pub fn to(&self) -> DropPlaceholderBounds {
        self.to
    }

    /// Which drag session this indicator belongs to. Host-owned drag items
    /// share [`ITEM_DRAG_SESSION_ID`].
    pub fn drag_session_id(&self) -> u64 {
        self.drag_session_id
    }

    /// Bumped on every restart, so an animation keyed on it replays instead of
    /// resuming when the target placement changes.
    pub fn epoch(&self) -> u64 {
        self.epoch
    }
}

/// The bounds a drop placeholder should occupy within a tab group, given
/// where the drop would land.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DropPlaceholderBounds {
    origin: Point<Pixels>,
    size: Size<Pixels>,
}

impl DropPlaceholderBounds {
    pub(crate) fn new(origin: Point<Pixels>, size: Size<Pixels>) -> Self {
        Self { origin, size }
    }

    pub fn for_placement(bounds: Bounds<Pixels>, placement: Option<Placement>) -> Self {
        let half_width = bounds.size.width * 0.5;
        let half_height = bounds.size.height * 0.5;

        match placement {
            Some(Placement::Left) => Self {
                origin: Point::default(),
                size: size(half_width, bounds.size.height),
            },
            Some(Placement::Right) => Self {
                origin: point(half_width, px(0.)),
                size: size(half_width, bounds.size.height),
            },
            Some(Placement::Top) => Self {
                origin: Point::default(),
                size: size(bounds.size.width, half_height),
            },
            Some(Placement::Bottom) => Self {
                origin: point(px(0.), half_height),
                size: size(bounds.size.width, half_height),
            },
            None => Self {
                origin: Point::default(),
                size: bounds.size,
            },
        }
    }

    pub fn origin(&self) -> Point<Pixels> {
        self.origin
    }

    pub fn size(&self) -> Size<Pixels> {
        self.size
    }
}

/// Which split zone `position` falls into within `bounds`, or `None` for the
/// centre zone (merge into the tab group rather than split).
pub fn split_placement_at(bounds: Bounds<Pixels>, position: Point<Pixels>) -> Option<Placement> {
    if position.x < bounds.left() + bounds.size.width * 0.35 {
        Some(Placement::Left)
    } else if position.x > bounds.left() + bounds.size.width * 0.65 {
        Some(Placement::Right)
    } else if position.y < bounds.top() + bounds.size.height * 0.35 {
        Some(Placement::Top)
    } else if position.y > bounds.top() + bounds.size.height * 0.65 {
        Some(Placement::Bottom)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use gpui::point;

    use super::*;

    #[test]
    fn drop_placeholder_bounds_cover_each_target_placement() {
        let bounds = gpui::Bounds {
            origin: point(px(120.), px(80.)),
            size: gpui::size(px(400.), px(300.)),
        };

        assert_eq!(
            DropPlaceholderBounds::for_placement(bounds, Some(Placement::Left)),
            DropPlaceholderBounds {
                origin: point(px(0.), px(0.)),
                size: gpui::size(px(200.), px(300.)),
            }
        );
        assert_eq!(
            DropPlaceholderBounds::for_placement(bounds, Some(Placement::Right)),
            DropPlaceholderBounds {
                origin: point(px(200.), px(0.)),
                size: gpui::size(px(200.), px(300.)),
            }
        );
        assert_eq!(
            DropPlaceholderBounds::for_placement(bounds, Some(Placement::Top)),
            DropPlaceholderBounds {
                origin: point(px(0.), px(0.)),
                size: gpui::size(px(400.), px(150.)),
            }
        );
        assert_eq!(
            DropPlaceholderBounds::for_placement(bounds, Some(Placement::Bottom)),
            DropPlaceholderBounds {
                origin: point(px(0.), px(150.)),
                size: gpui::size(px(400.), px(150.)),
            }
        );
        assert_eq!(
            DropPlaceholderBounds::for_placement(bounds, None),
            DropPlaceholderBounds {
                origin: point(px(0.), px(0.)),
                size: gpui::size(px(400.), px(300.)),
            }
        );
    }

    #[test]
    fn split_placement_follows_the_cursor_zone() {
        let bounds = gpui::Bounds {
            origin: point(px(120.), px(80.)),
            size: gpui::size(px(400.), px(300.)),
        };
        // 35% / 65% of 400x300 from origin (120, 80).
        let at = |x: f32, y: f32| split_placement_at(bounds, point(px(x), px(y)));

        assert_eq!(at(130., 230.), Some(Placement::Left));
        assert_eq!(at(510., 230.), Some(Placement::Right));
        assert_eq!(at(320., 90.), Some(Placement::Top));
        assert_eq!(at(320., 370.), Some(Placement::Bottom));
        assert_eq!(at(320., 230.), None, "centre merges into the tab group");
    }

    #[test]
    fn split_placement_prefers_horizontal_in_the_corners() {
        let bounds = gpui::Bounds {
            origin: Point::default(),
            size: gpui::size(px(400.), px(300.)),
        };

        // Top-left corner satisfies both Left and Top; x is tested first.
        assert_eq!(
            split_placement_at(bounds, point(px(10.), px(10.))),
            Some(Placement::Left)
        );
        assert_eq!(
            split_placement_at(bounds, point(px(390.), px(290.))),
            Some(Placement::Right)
        );
    }

    #[test]
    fn split_placement_boundaries_fall_into_the_centre() {
        let bounds = gpui::Bounds {
            origin: Point::default(),
            size: gpui::size(px(400.), px(300.)),
        };

        // Comparisons are strict, so the threshold itself is the centre zone.
        assert_eq!(split_placement_at(bounds, point(px(140.), px(150.))), None);
        assert_eq!(split_placement_at(bounds, point(px(260.), px(150.))), None);
        assert_eq!(split_placement_at(bounds, point(px(200.), px(105.))), None);
        assert_eq!(split_placement_at(bounds, point(px(200.), px(195.))), None);
    }
}
