//! Unstyled plotting: scales, shapes, axes, grids, labels, and the element and
//! hover tracking behind every [`Plot`].
//!
//! Colors are always handed in by the caller. A styled layer supplies chart
//! defaults, the tooltip overlay, and hover and appear timing through
//! [`PlotMotion`].
mod appear;
mod axis;
mod element;
mod grid;
mod hover;
pub mod label;
mod path_cache;
pub mod scale;
pub mod shape;

use std::{fmt::Debug, ops::Add, time::Duration};

use gpui::{
    AnyElement, App, Bounds, ElementId, IntoElement, Path, PathBuilder, Pixels, Point, Window,
    point, px,
};

use crate::{Spring, motion::Transition};

pub use appear::{PlotAppear, PlotAppearScope};
#[allow(deprecated)]
pub use axis::AXIS_GAP;
pub use axis::{AxisLabelPlacement, AxisLabelSide, AxisText, PlotAxis, axis_gutter};
pub use element::PlotElement;
pub use grid::Grid;
pub use hover::{PlotHover, TooltipState, hover_progress, is_hover_entering, pointer_spring};
pub use label::PlotLabel;
pub use path_cache::{PathCache, PathCaches, ShapeKey};
pub use scale::PlotValue;

/// The timing of a plot's motion: how its data marks appear when it is first
/// painted, how its hover progress fades in and out, and the spring a pointer
/// follows the hovered datum with.
///
/// Base installs no motion of its own: every duration defaults to zero, so the
/// hover appears, fades and glides at once. Product timing belongs to the
/// styled layer, which projects it through [`crate::PlotTheme`].
#[derive(Clone)]
pub struct PlotMotion {
    pointer: Spring,
    enter: Transition,
    exit: Transition,
    appear: Transition,
}

impl Default for PlotMotion {
    fn default() -> Self {
        Self {
            pointer: Spring::new(Duration::ZERO),
            enter: Transition::new(Duration::ZERO),
            exit: Transition::new(Duration::ZERO),
            appear: Transition::new(Duration::ZERO),
        }
    }
}

impl PlotMotion {
    /// The spring a crosshair, highlight band or hover dot follows the hovered
    /// datum with.
    pub fn with_pointer(mut self, pointer: Spring) -> Self {
        self.pointer = pointer;
        self
    }

    /// How the hover fades in when the cursor lands on a datum.
    pub fn with_enter(mut self, enter: Transition) -> Self {
        self.enter = enter;
        self
    }

    /// How the hover fades out after the cursor leaves.
    pub fn with_exit(mut self, exit: Transition) -> Self {
        self.exit = exit;
        self
    }

    /// How a plot's data marks appear the first time it is painted; see
    /// [`PlotAppear`].
    pub fn with_appear(mut self, appear: Transition) -> Self {
        self.appear = appear;
        self
    }

    pub fn pointer(&self) -> Spring {
        self.pointer
    }

    pub fn enter(&self) -> &Transition {
        &self.enter
    }

    pub fn exit(&self) -> &Transition {
        &self.exit
    }

    pub fn appear(&self) -> &Transition {
        &self.appear
    }
}

pub trait Plot: IntoElement {
    /// Lay out and place the child elements this plot hosts (e.g. element labels).
    ///
    /// Called during the element's prepaint phase, so implementations may use
    /// [`AnyElement::layout_as_root`] / [`AnyElement::prepaint_at`] to measure and
    /// position children — neither is legal from [`Plot::paint`]. The returned
    /// elements are painted right after `paint`, below the tooltip overlay.
    ///
    /// Runs before [`Plot::tooltip_state`] and [`Plot::tooltip`], so anything
    /// resolved here can be reused by them.
    ///
    /// The default returns no children.
    fn prepaint(
        &mut self,
        _bounds: Bounds<Pixels>,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Vec<AnyElement> {
        vec![]
    }

    fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App);

    /// A stable element id that keeps this plot's state across frames.
    ///
    /// Return `Some(id)` to opt in to appear motion and, unless
    /// [`Plot::interactive`] says otherwise, tooltips and hover motion; the id
    /// must be unique among sibling elements. Returning `None` (the default for
    /// a hand-written plot) leaves the plot a pure element that neither appears
    /// nor tracks hover.
    ///
    /// The charts in GPUI Component always return `Some`: their id defaults to the
    /// source location they were constructed at, and `id` renames it.
    fn id(&self) -> Option<ElementId> {
        None
    }

    /// Whether a plot with an [`Plot::id`] tracks hover and shows its tooltip.
    ///
    /// `false` keeps the id's state — appear motion and path caches — without
    /// the hitbox, hover tracking or overlay. The default is `true`, so a plot
    /// opts in to tooltips by returning an id.
    fn interactive(&self) -> bool {
        true
    }

    /// Receive how far the plot's data marks have appeared this frame, before
    /// [`Plot::hover`] and [`Plot::paint`] run.
    ///
    /// Called on every frame the plot has an [`Plot::id`]; see [`PlotAppear`].
    /// Without an [`Plot::appear_generation`] the appear is always complete.
    /// The default ignores it.
    fn appear(&mut self, _appear: PlotAppear, _window: &mut Window, _cx: &mut App) {}

    /// Opt in to appear motion: `Some` draws the plot in the first time its
    /// id is painted, and again whenever the value changes, such as when a
    /// chart switches to another symbol or period.
    ///
    /// The default, `None`, tracks no appear, keeps no state for it and asks
    /// for no frames, so a plot that does not draw in costs nothing.
    fn appear_generation(&self) -> Option<u64> {
        None
    }

    /// Map the cursor to the tooltip state to display.
    ///
    /// `position` is the cursor position relative to the plot's top-left origin (already
    /// origin-subtracted), and `bounds` is the painted area. Return the [`TooltipState`]
    /// to display (highlighted index, crosshair point, dots), or `None` to show
    /// nothing. Only called while the cursor is inside `bounds`.
    ///
    /// The default returns `None`.
    fn tooltip_state(
        &self,
        _position: Point<Pixels>,
        _bounds: Bounds<Pixels>,
        _cx: &App,
    ) -> Option<TooltipState> {
        None
    }

    /// Receive the hovered datum this frame, before [`Plot::tooltip`] and
    /// [`Plot::paint`] run.
    ///
    /// `hover` carries the [`TooltipState`] the cursor resolved to, and it
    /// lingers after the cursor leaves while [`PlotHover::progress`] eases back to
    /// zero, so a hover-driven presentation can fade out over the last datum
    /// instead of vanishing. `None` means nothing is hovered and nothing is
    /// fading.
    ///
    /// Called on every frame the plot has an [`Plot::id`], so this is where a
    /// plot samples its hover motion ([`crate::motion::transition`],
    /// [`PlotHover::glide`]) and keeps the result for the other two methods.
    /// The default ignores the hover.
    fn hover(&mut self, _hover: Option<&PlotHover>, _window: &mut Window, _cx: &mut App) {}

    /// Render the tooltip overlay for the active [`TooltipState`].
    ///
    /// `cursor` is the live cursor position (relative to the plot origin) and `bounds` is the
    /// plot's painted area, so the tooltip box can follow the cursor (pass `cursor` and
    /// `bounds.size` to the styled layer's tooltip). Return the overlay element; it is
    /// painted absolutely positioned above the plot graphics but below sibling content
    /// drawn after the plot (a box that may overflow the plot should `deferred` itself).
    /// The default returns `None`.
    ///
    /// Also called while the hover fades out, with the lingering `state` and the
    /// last `cursor`; the overlay renders within the plot's element scope, so it can
    /// fade with [`hover_progress`].
    fn tooltip(
        &self,
        _state: &TooltipState,
        _cursor: Point<Pixels>,
        _bounds: Bounds<Pixels>,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }
}

/// How a [`Line`](shape::Line) or [`Area`](shape::Area) connects its points,
/// like d3's curve factories.
#[derive(Clone, Copy, Debug, Default, Hash, PartialEq, Eq)]
pub enum Curve {
    /// A smooth curve through every point (`d3.curveNatural`).
    #[default]
    Natural,
    /// Straight segments between points (`d3.curveLinear`).
    Linear,
    /// A step that holds each value until the next point (`d3.curveStepAfter`).
    StepAfter,
}

pub fn origin_point<T>(x: T, y: T, origin: Point<T>) -> Point<T>
where
    T: Default + Clone + Debug + PartialEq + Add<Output = T>,
{
    point(x, y) + origin
}

pub fn polygon<T>(points: &[Point<T>], bounds: &Bounds<Pixels>) -> Option<Path<Pixels>>
where
    T: Default + Clone + Copy + Debug + Into<f32> + PartialEq,
{
    let mut path = PathBuilder::stroke(px(1.));
    let points = &points
        .iter()
        .map(|p| {
            point(
                px(p.x.into() + bounds.origin.x.as_f32()),
                px(p.y.into() + bounds.origin.y.as_f32()),
            )
        })
        .collect::<Vec<_>>();
    path.add_polygon(points, false);
    path.build().ok()
}
