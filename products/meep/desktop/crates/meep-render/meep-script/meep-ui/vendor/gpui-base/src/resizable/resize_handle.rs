use std::{cell::Cell, rc::Rc};

use gpui::{
    AnyElement, App, Axis, Div, Element, ElementId, Entity, GlobalElementId, Hitbox,
    HitboxBehavior, InteractiveElement, Interactivity, IntoElement, MouseDownEvent, MouseMoveEvent,
    MouseUpEvent, ParentElement as _, Pixels, Point, Render, StatefulInteractiveElement,
    Styled as _, Window, div, prelude::FluentBuilder as _, px,
};

use crate::{AxisExt as _, InteractiveElementExt, TestSupportExt as _, theme::ActiveTheme as _};

pub(crate) const HANDLE_PADDING: Pixels = px(4.);
pub(crate) const HANDLE_SIZE: Pixels = px(1.);

type DragConstructor<T, E> = Box<dyn Fn(&T, &Point<Pixels>, &mut Window, &mut App) -> Entity<E>>;

/// Create a resize handle: a band that resizes whatever it edges when it is
/// dragged.
///
/// Base owns the band -- where it sits, how wide it is, its cursor, and the
/// Idle → Hovered → Pressed → Dragging progression its appearance is told
/// about. What a drag resizes is the caller's. Give the handle a payload with
/// [`ResizeHandle::on_drag`] and follow that payload with
/// [`on_drag_move`](InteractiveElement::on_drag_move), the way a slider thumb
/// does; any other listener -- a double click that restores a default size, a
/// hover that a surrounding drawer has to count as its own -- goes on the
/// handle through the interactive element traits.
///
/// The band occludes. While the pointer is on it nothing behind it reads as
/// hovered, its own container included, so a container that has to know the
/// pointer is still over it listens on the handle as well.
///
/// The band's element id, its `"handle"` group, its occlusion and its drag
/// are base's: an `id`, `group`, hitbox behavior or `on_drag` set through the
/// interactive element traits is replaced when the band is laid out.
///
/// ```ignore
/// resize_handle("sidebar-edge", Axis::Horizontal)
///     .inside(HandleEdge::Trailing)
///     .on_drag(ResizeSidebar, |drag, _, _, cx| cx.new(|_| drag.clone()))
///     .on_double_click(|_, _, cx| restore_default_width(cx))
/// ```
pub fn resize_handle<T: 'static, E: 'static + Render>(
    id: impl Into<ElementId>,
    axis: Axis,
) -> ResizeHandle<T, E> {
    ResizeHandle::new(id, axis)
}

/// Draws the visible part of a resize handle.
///
/// Returning `None` keeps the built-in line, so a renderer can override some
/// handles and leave the rest alone.
pub type ResizeHandleRenderer =
    Rc<dyn Fn(&ResizeHandleContext, &mut Window, &mut App) -> Option<AnyElement>>;

/// What a [`ResizeHandleRenderer`] is told about the handle it is drawing.
///
/// The hit area, the cursor and the drag itself stay with the handle; a
/// renderer only supplies what is painted inside it.
pub struct ResizeHandleContext {
    axis: Axis,
    edge: Option<HandleEdge>,
    state: ResizeHandleState,
}

impl ResizeHandleContext {
    /// The axis the handle resizes along: `Horizontal` for a vertical divider
    /// between two side-by-side panels.
    pub fn axis(&self) -> Axis {
        self.axis
    }

    /// The edge of its container this handle hugs, or `None` for a handle
    /// straddling the boundary it resizes.
    ///
    /// A hugging handle's line is the container's outermost pixel, so anything
    /// a renderer centres on it crosses the boundary; see [`HandleEdge`] for
    /// what the container does with that.
    pub fn edge(&self) -> Option<HandleEdge> {
        self.edge
    }

    /// Whether the pointer currently owns this handle.
    pub fn is_active(&self) -> bool {
        self.state.is_active()
    }

    /// How far the pointer has gone with this handle.
    pub fn state(&self) -> ResizeHandleState {
        self.state
    }
}

/// How far the pointer has gone with a resize handle.
///
/// A drag takes the pointer out of the handle's own band within a pixel or
/// two, so GPUI's hover reads false for most of a drag and cannot stand in for
/// `Dragging`. Base tracks the progression instead, and a renderer reads it
/// through [`ResizeHandleContext::state`].
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ResizeHandleState {
    /// The pointer is somewhere else.
    #[default]
    Idle,
    /// The pointer is over the handle's band.
    Hovered,
    /// The pointer went down on the handle and has not moved since.
    Pressed,
    /// The handle is being dragged.
    Dragging,
}

impl ResizeHandleState {
    /// Whether the pointer owns the handle -- pressed on it, or dragging it.
    pub fn is_active(self) -> bool {
        matches!(self, Self::Pressed | Self::Dragging)
    }
}

/// Which edge of its own container a handle hugs.
///
/// A handle named no edge straddles the boundary it resizes, half its band on
/// either side, which is what a divider between two panels of a group wants.
/// A dock's own edge handle cannot: [`dock_frame`] clips to the dock's box, so
/// the half hanging outside is cut away -- what it paints and what it
/// hit-tests alike, which is why the outer half of a dock's grab band has
/// never actually been grabbable. Naming the edge moves the whole band inside.
///
/// The hairline stays on the boundary itself: it is the container's outermost
/// pixel, the one the neighbour's content butts up against. Moving it inward
/// by even a pixel leaves that pixel of the container showing past the line
/// on one side, or a gap before it on the other, along the whole seam. What a
/// renderer paints on top of the line -- an indicator thicker than the line,
/// centred on it -- overhangs the boundary, and the container's clip takes
/// the outer half off it unless the renderer defers that part. Only that part:
/// a deferred element paints after the whole tree, and no priority puts it
/// beneath the application's own deferred content, so a deferred line would
/// cut straight through a popover opened at the default priority from a panel
/// drawn before this container. A renderer learns which edge it is drawing for
/// from [`ResizeHandleContext::edge`].
///
/// [`dock_frame`]: crate::dock::dock_frame
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HandleEdge {
    /// Where the axis starts: the left edge of a horizontal handle's
    /// container, the top edge of a vertical one's.
    Leading,
    /// Where the axis ends.
    Trailing,
}

/// A band that resizes along one axis when it is dragged, carrying a `T` that
/// the drag renders as an `E`. See [`resize_handle`].
pub struct ResizeHandle<T: 'static, E: 'static + Render> {
    id: ElementId,
    axis: Axis,
    edge: Option<HandleEdge>,
    drag: Option<(T, DragConstructor<T, E>)>,
    appearance: Option<ResizeHandleRenderer>,
    /// The band itself. Listeners a caller attaches through the interactive
    /// element traits land here, on the element the pointer actually hits;
    /// base places and sizes it when it is laid out.
    base: Div,
}

impl<T: 'static, E: 'static + Render> ResizeHandle<T, E> {
    fn new(id: impl Into<ElementId>, axis: Axis) -> Self {
        let id = id.into();
        Self {
            id: id.clone(),
            edge: None,
            drag: None,
            appearance: None,
            axis,
            base: div(),
        }
    }

    /// Hand the painted part of this handle to `appearance`.
    pub fn with_appearance(mut self, appearance: ResizeHandleRenderer) -> Self {
        self.appearance = Some(appearance);
        self
    }

    /// Start a drag carrying `value` when the band is pressed and moved.
    ///
    /// A band takes one drag, and this is it: use this rather than
    /// [`StatefulInteractiveElement::on_drag`], which it shadows.
    ///
    /// GPUI tells drags apart by the type of their payload, so the drag
    /// carries `value` itself, and a caller following it with
    /// [`on_drag_move`](InteractiveElement::on_drag_move) listens for a `T`.
    pub fn on_drag(
        mut self,
        value: T,
        f: impl Fn(&T, &Point<Pixels>, &mut Window, &mut App) -> Entity<E> + 'static,
    ) -> Self {
        self.drag = Some((value, Box::new(f)));
        self
    }

    /// Keep the whole handle inside its container, hugging `edge`, instead of
    /// straddling the boundary it resizes.
    pub fn inside(mut self, edge: HandleEdge) -> Self {
        self.edge = Some(edge);
        self
    }
}

impl<T: 'static, E: 'static + Render> InteractiveElement for ResizeHandle<T, E> {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl<T: 'static, E: 'static + Render> StatefulInteractiveElement for ResizeHandle<T, E> {}

impl<T: 'static, E: 'static + Render> InteractiveElementExt for ResizeHandle<T, E> {}

/// One handle's [`ResizeHandleState`], shared between the element and the
/// mouse listeners it registers.
///
/// The `Rc` is load-bearing. `with_element_state` hands back a clone and a
/// bare `Cell` clones by value, so a listener holding one wrote its progress
/// into a copy that died with the event: the stored state never left `Idle`
/// and `is_active` never once read true.
#[derive(Default, Debug, Clone)]
struct SharedHandleState {
    state: Rc<Cell<ResizeHandleState>>,
}

impl SharedHandleState {
    fn get(&self) -> ResizeHandleState {
        self.state.get()
    }

    /// Reports whether the state actually changed, so a listener repaints the
    /// window only when there is something new to paint.
    fn set(&self, state: ResizeHandleState) -> bool {
        let changed = self.state.get() != state;
        self.state.set(state);
        changed
    }
}

impl<T: 'static, E: 'static + Render> IntoElement for ResizeHandle<T, E> {
    type Element = ResizeHandle<T, E>;
    fn into_element(self) -> Self::Element {
        self
    }
}

impl<T: 'static, E: 'static + Render> Element for ResizeHandle<T, E> {
    type RequestLayoutState = AnyElement;
    /// The band's own hitbox, so the listeners in `paint` can ask whether the
    /// pointer is really on the handle rather than merely within its bounds.
    type PrepaintState = Hitbox;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        let neg_offset = -HANDLE_PADDING;
        let axis = self.axis;
        let edge = self.edge;
        // Sizes are border-box: the extent has to name the whole band, padding
        // included, or the content box resolves to zero and the hairline
        // overflows into the padding, landing wherever the padding happens to
        // push it.
        let hug_extent = HANDLE_SIZE + HANDLE_PADDING;
        let straddle_extent = HANDLE_SIZE + HANDLE_PADDING * 2.;
        // The caller's listeners are already on it; what base adds is where the
        // band goes and what it holds.
        let base = std::mem::replace(&mut self.base, div());
        let drag = self.drag.take();

        window.with_element_state(id.unwrap(), |state, window| {
            let state: SharedHandleState = state.unwrap_or_default();

            let bg_color = handle_color(&cx.theme(), state.get().is_active());

            let mut el = base
                .id(self.id.clone())
                .test_support()
                .occlude()
                .absolute()
                .flex_shrink_0()
                .group("handle")
                .when_some(drag, |this, (value, on_drag)| {
                    this.on_drag(value, move |value, position, window, cx| {
                        on_drag(value, &position, window, cx)
                    })
                })
                .map(|this| match (edge, axis) {
                    // Hugging an edge: the whole band is inside the container,
                    // padded on the inner side only, so the hairline is the
                    // container's outermost pixel -- the seam itself.
                    // FIXME: Improve this to let the scroll bar have px(HANDLE_PADDING)
                    (Some(HandleEdge::Trailing), Axis::Horizontal) => this
                        .cursor_col_resize()
                        .top_0()
                        .right_0()
                        .h_full()
                        .w(hug_extent)
                        .pl(HANDLE_PADDING),
                    (Some(HandleEdge::Leading), Axis::Horizontal) => this
                        .cursor_col_resize()
                        .top_0()
                        .left_0()
                        .h_full()
                        .w(hug_extent)
                        .pr(HANDLE_PADDING),
                    (Some(HandleEdge::Trailing), Axis::Vertical) => this
                        .cursor_row_resize()
                        .bottom_0()
                        .left_0()
                        .w_full()
                        .h(hug_extent)
                        .pt(HANDLE_PADDING),
                    (Some(HandleEdge::Leading), Axis::Vertical) => this
                        .cursor_row_resize()
                        .top_0()
                        .left_0()
                        .w_full()
                        .h(hug_extent)
                        .pb(HANDLE_PADDING),
                    // Straddling the boundary: half the band on either side.
                    (None, Axis::Horizontal) => this
                        .cursor_col_resize()
                        .top_0()
                        .left(neg_offset)
                        .h_full()
                        .w(straddle_extent)
                        .px(HANDLE_PADDING),
                    (None, Axis::Vertical) => this
                        .cursor_row_resize()
                        .top(neg_offset)
                        .left_0()
                        .w_full()
                        .h(straddle_extent)
                        .py(HANDLE_PADDING),
                })
                .child(
                    // A renderer that declines — or is absent — leaves the
                    // built-in line, so overriding one handle never obliges a
                    // caller to redraw them all. What it paints stays in tree
                    // order, under the container's own mask: a divider is
                    // part of the panel it edges, and anything the
                    // application floats over that panel has to cover it.
                    self.appearance
                        .as_ref()
                        .and_then(|appearance| {
                            appearance(
                                &ResizeHandleContext {
                                    axis,
                                    edge,
                                    state: state.get(),
                                },
                                window,
                                cx,
                            )
                        })
                        .unwrap_or_else(|| {
                            div()
                                // The line fills the handle's content box
                                // exactly, so it has nothing to give: a
                                // shrinkable child collapses with it.
                                .flex_none()
                                .bg(bg_color)
                                .group_hover("handle", |this| this.bg(bg_color))
                                .when(axis.is_horizontal(), |this| this.h_full().w(HANDLE_SIZE))
                                .when(axis.is_vertical(), |this| this.w_full().h(HANDLE_SIZE))
                                .into_any_element()
                        }),
                )
                .into_any_element();

            let layout_id = el.request_layout(window, cx);

            ((layout_id, el), state)
        })
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        bounds: gpui::Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        request_layout.prepaint(window, cx);
        // After the child, deliberately. The band's own div occludes, and a
        // hit test stops at the first hitbox that does, so a hitbox inserted
        // before it would sit underneath and never read as hovered. Inserted
        // here it sits directly on top of the band and directly under whatever
        // is painted after this handle -- a sheet's overlay, a toast -- which
        // is exactly the ordering `is_hovered_at` should answer from.
        window.insert_hitbox(bounds, HitboxBehavior::Normal)
    }

    fn paint(
        &mut self,
        id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: gpui::Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        hitbox: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        request_layout.paint(window, cx);

        // Hovered and pressed are answered by the hitbox, not by the bounds.
        // Bounds containment reads true through anything painted over the
        // handle, so a divider under a sheet lit up as the pointer crossed
        // where it lay; the hitbox is occluded by that sheet and says no.
        let hitbox = hitbox.clone();

        window.with_element_state(id.unwrap(), |state: Option<SharedHandleState>, window| {
            let state = state.unwrap_or_default();

            window.on_mouse_event({
                let state = state.clone();
                let hitbox = hitbox.clone();
                move |ev: &MouseDownEvent, phase, window, _| {
                    if phase.bubble()
                        && hitbox.is_hovered_at(ev.position, window)
                        && state.set(ResizeHandleState::Pressed)
                    {
                        window.refresh();
                    }
                }
            });

            window.on_mouse_event({
                let state = state.clone();
                let hitbox = hitbox.clone();
                move |ev: &MouseMoveEvent, phase, window, _| {
                    if !phase.bubble() {
                        return;
                    }

                    // A press that moves is a drag, and stays one until the
                    // button comes back up: by the second frame the pointer is
                    // outside this nine-pixel band, so where it is says nothing
                    // about whether the handle is still being dragged.
                    let next = match state.get() {
                        engaged if engaged.is_active() => ResizeHandleState::Dragging,
                        _ if hitbox.is_hovered_at(ev.position, window) => {
                            ResizeHandleState::Hovered
                        }
                        _ => ResizeHandleState::Idle,
                    };
                    if state.set(next) {
                        window.refresh();
                    }
                }
            });

            window.on_mouse_event({
                let state = state.clone();
                let hitbox = hitbox.clone();
                move |ev: &MouseUpEvent, _, window, _| {
                    if !state.get().is_active() {
                        return;
                    }

                    // Releasing over the handle leaves it hovered. Going
                    // straight to idle there would drop the indicator for one
                    // frame and bring it back under a pointer that never left.
                    let next = if hitbox.is_hovered_at(ev.position, window) {
                        ResizeHandleState::Hovered
                    } else {
                        ResizeHandleState::Idle
                    };
                    if state.set(next) {
                        window.refresh();
                    }
                }
            });

            ((), state)
        });
    }
}

/// What a resize handle paints, given the active theme.
///
/// Projected colors win; without them the handle resolves from the tokens that
/// already mean these two states everywhere else -- `border` for a divider at
/// rest, `ring` for the thing the pointer currently owns. Before this the
/// unprojected answer was `Hsla::default()`, which is transparent, so a
/// consumer with no styled façade had no divider at all.
pub(crate) fn handle_color(theme: &crate::Theme, active: bool) -> gpui::Hsla {
    if active {
        theme
            .resizable
            .active_handle
            .unwrap_or(theme.tokens.colors.ring)
    } else {
        theme.resizable.handle.unwrap_or(theme.tokens.colors.border)
    }
}

#[cfg(test)]
mod tests {
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };

    use gpui::{
        AnyElement, App, AppContext as _, Axis, Bounds, Context, DragMoveEvent, Empty,
        InteractiveElement as _, IntoElement, Modifiers, MouseButton, MouseDownEvent, MouseUpEvent,
        ParentElement as _, Pixels, Render, StatefulInteractiveElement as _, Styled as _,
        TestAppContext, VisualTestContext, Window, deferred, div, hsla, point,
        prelude::FluentBuilder as _, px,
    };

    use super::{
        HandleEdge, ResizeHandleContext, ResizeHandleState, SharedHandleState, handle_color,
        resize_handle,
    };
    use crate::{ElementExt as _, InteractiveElementExt as _, ResizableTheme, Theme};

    /// What a hugging handle's renderer was told and drew, and where the
    /// drawing landed in the frame: under which mask, and before or after a
    /// popover the application deferred from a panel drawn ahead of the dock.
    #[derive(Default)]
    struct Probe {
        edge: Cell<Option<Option<HandleEdge>>>,
        line: Cell<Option<Bounds<Pixels>>>,
        mask: Cell<Option<Bounds<Pixels>>>,
        /// Ticked by every prepaint hook below, in the order the frame reaches
        /// them.
        prepaints: Cell<usize>,
        line_prepainted: Cell<Option<usize>>,
        popover_prepainted: Cell<Option<usize>>,
    }

    impl Probe {
        fn tick(&self) -> usize {
            let n = self.prepaints.get();
            self.prepaints.set(n + 1);
            n
        }
    }

    /// A hairline filling the handle's content box, the way a styled divider
    /// rests.
    fn hairline(axis: Axis, probe: Rc<Probe>) -> AnyElement {
        div()
            .flex_none()
            .map(|line| match axis {
                Axis::Horizontal => line.w(px(1.)).h_full(),
                Axis::Vertical => line.h(px(1.)).w_full(),
            })
            .on_prepaint(move |bounds, window, _| {
                probe.line.set(Some(bounds));
                probe.mask.set(Some(window.content_mask().bounds));
                probe.line_prepainted.set(Some(probe.tick()));
            })
            .into_any_element()
    }

    /// A drag payload for a handle nobody drags in these tests.
    struct NoDrag;

    impl Render for NoDrag {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// A dock-shaped box: 200px along the axis, clipped to itself the way
    /// `dock_frame` is, sitting between two 100px neighbours so both of its
    /// edges are seams. The handle hugs one of them.
    ///
    /// The first neighbour floats a popover across both seams, deferred at the
    /// default priority the way an application's own `deferred(anchored())`
    /// is -- a panel drawn before the dock, opening something over it.
    struct HuggingHarness {
        axis: Axis,
        edge: HandleEdge,
        probe: Rc<Probe>,
    }

    impl Render for HuggingHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let axis = self.axis;
            let probe = self.probe.clone();
            let neighbour = || match axis {
                Axis::Horizontal => div().w(px(100.)).h_full(),
                Axis::Vertical => div().h(px(100.)).w_full(),
            };
            let popover = div()
                .absolute()
                .map(|popover| match axis {
                    Axis::Horizontal => popover.top_0().left(px(50.)).w(px(300.)).h_full(),
                    Axis::Vertical => popover.left_0().top(px(50.)).h(px(300.)).w_full(),
                })
                .on_prepaint({
                    let probe = probe.clone();
                    move |_, _, _| probe.popover_prepainted.set(Some(probe.tick()))
                });
            div()
                .flex()
                .map(|row| match axis {
                    Axis::Horizontal => row.flex_row().w(px(400.)).h(px(100.)),
                    Axis::Vertical => row.flex_col().h(px(400.)).w(px(100.)),
                })
                .child(neighbour().child(deferred(popover)))
                .child(
                    div()
                        .relative()
                        .overflow_hidden()
                        .map(|dock| match axis {
                            Axis::Horizontal => dock.w(px(200.)).h_full(),
                            Axis::Vertical => dock.h(px(200.)).w_full(),
                        })
                        .child(
                            resize_handle::<(), NoDrag>("hugging", axis)
                                .inside(self.edge)
                                .with_appearance(Rc::new(
                                    move |handle: &ResizeHandleContext,
                                          _: &mut Window,
                                          _: &mut App| {
                                        probe.edge.set(Some(handle.edge()));
                                        Some(hairline(handle.axis(), probe.clone()))
                                    },
                                )),
                        ),
                )
                .child(neighbour())
        }
    }

    fn draw_hugging(cx: &mut TestAppContext, axis: Axis, edge: HandleEdge) -> Rc<Probe> {
        let probe = Rc::new(Probe::default());
        let (_, cx) = cx.add_window_view({
            let probe = probe.clone();
            move |_, _| HuggingHarness { axis, edge, probe }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        probe
    }

    /// The seam a hugging handle marks, along its axis.
    ///
    /// The dock spans 100..300 in the harness, so its leading seam is at 100
    /// and its trailing one at 300.
    fn seam(edge: HandleEdge) -> Pixels {
        match edge {
            HandleEdge::Leading => px(100.),
            HandleEdge::Trailing => px(300.),
        }
    }

    fn along(axis: Axis, bounds: Bounds<Pixels>) -> (Pixels, Pixels) {
        match axis {
            Axis::Horizontal => (bounds.left(), bounds.right()),
            Axis::Vertical => (bounds.top(), bounds.bottom()),
        }
    }

    /// A hugging handle's hairline is the container's outermost pixel.
    ///
    /// This is the regression. The line was set one pixel in from the
    /// boundary, to make room for an indicator to overhang it, and along the
    /// whole seam that pixel of the dock showed past the line on one side of
    /// the area and opened a gap before it on the other.
    #[gpui::test]
    fn a_hugging_handle_draws_its_line_on_the_seam(cx: &mut TestAppContext) {
        for axis in [Axis::Horizontal, Axis::Vertical] {
            for edge in [HandleEdge::Leading, HandleEdge::Trailing] {
                let probe = draw_hugging(cx, axis, edge);
                let line = probe.line.get().expect("the renderer was asked to draw");
                let (start, end) = along(axis, line);
                let expected = match edge {
                    HandleEdge::Leading => (seam(edge), seam(edge) + px(1.)),
                    HandleEdge::Trailing => (seam(edge) - px(1.), seam(edge)),
                };
                assert_eq!(
                    (start, end),
                    expected,
                    "{axis:?} {edge:?}: the hairline has to be the pixel against the seam"
                );
            }
        }
    }

    /// A hugging handle's appearance is painted in tree order, under its
    /// container's mask -- beneath whatever the application floats over the
    /// panels around it.
    ///
    /// This is the regression. The appearance was deferred so that an
    /// indicator centred on the hairline would keep the pixel overhanging the
    /// container, and a deferred element paints after the whole tree at a
    /// priority no lower than the default. A popover an application defers
    /// from a panel drawn before the dock -- at that default priority, as
    /// `deferred(anchored())` is -- was painted first, and the dock's divider
    /// ran straight through it.
    #[gpui::test]
    fn a_hugging_handle_paints_beneath_a_popover_deferred_before_it(cx: &mut TestAppContext) {
        for axis in [Axis::Horizontal, Axis::Vertical] {
            for edge in [HandleEdge::Leading, HandleEdge::Trailing] {
                let probe = draw_hugging(cx, axis, edge);
                let line = probe
                    .line_prepainted
                    .get()
                    .expect("the line was prepainted");
                let popover = probe
                    .popover_prepainted
                    .get()
                    .expect("the popover was prepainted");
                assert!(
                    line < popover,
                    "{axis:?} {edge:?}: the line (prepaint #{line}) has to go down before \
                     the popover (#{popover}), or it is painted over it"
                );

                // The dock spans 100..300 along the axis; a deferred line would
                // have been prepainted under the window's mask instead.
                let mask = probe.mask.get().expect("the line was prepainted");
                assert_eq!(
                    along(axis, mask),
                    (px(100.), px(300.)),
                    "{axis:?} {edge:?}: the line is painted under its container's clip"
                );
            }
        }
    }

    /// A renderer is told which edge the handle hugs, so it can keep what it
    /// centres on the line clear of the container's clip itself.
    #[gpui::test]
    fn a_renderer_is_told_the_edge_a_handle_hugs(cx: &mut TestAppContext) {
        for axis in [Axis::Horizontal, Axis::Vertical] {
            for edge in [HandleEdge::Leading, HandleEdge::Trailing] {
                let probe = draw_hugging(cx, axis, edge);
                assert_eq!(probe.edge.get(), Some(Some(edge)), "{axis:?} {edge:?}");
            }
        }
    }

    #[test]
    fn a_listener_writes_its_progress_back_into_the_stored_state() {
        let stored = SharedHandleState::default();
        // What `paint` hands each mouse listener.
        let listener = stored.clone();

        assert!(listener.set(ResizeHandleState::Pressed));

        // The regression this pins down: the state used to be a bare `Cell`,
        // which clones by value, so a listener wrote into a copy that died
        // with the event and the handle never left `Idle`.
        assert_eq!(stored.get(), ResizeHandleState::Pressed);
        assert!(stored.get().is_active());
    }

    #[test]
    fn setting_the_state_it_already_has_asks_for_no_repaint() {
        let state = SharedHandleState::default();

        assert!(state.set(ResizeHandleState::Hovered));
        assert!(!state.set(ResizeHandleState::Hovered));
    }

    #[test]
    fn only_a_held_handle_is_active() {
        assert!(!ResizeHandleState::Idle.is_active());
        assert!(!ResizeHandleState::Hovered.is_active());
        assert!(ResizeHandleState::Pressed.is_active());
        assert!(ResizeHandleState::Dragging.is_active());
    }

    #[gpui::test]
    fn an_unprojected_handle_resolves_from_the_theme_tokens(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let border = hsla(0., 0., 0.5, 1.0);
            let ring = hsla(0.6, 0.5, 0.5, 1.0);
            let theme = Theme::global_mut(cx);
            theme.tokens.colors.border = border;
            theme.tokens.colors.ring = ring;
            theme.resizable = ResizableTheme::default();

            let theme = Theme::global(cx);
            assert_eq!(handle_color(&theme, false), border);
            assert_eq!(handle_color(&theme, true), ring);
            // The point of the change: the default used to be transparent, so
            // a divider with nothing projected onto it was not drawn at all.
            assert_ne!(handle_color(&theme, false), gpui::Hsla::default());
        });
    }

    #[gpui::test]
    fn a_projected_handle_still_wins(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let projected = hsla(0.3, 0.4, 0.5, 1.0);
            let active = hsla(0.9, 0.4, 0.5, 1.0);
            let theme = Theme::global_mut(cx);
            theme.tokens.colors.border = hsla(0., 0., 0.5, 1.0);
            theme.resizable = ResizableTheme {
                handle: Some(projected),
                active_handle: Some(active),
            };

            let theme = Theme::global(cx);
            assert_eq!(handle_color(&theme, false), projected);
            assert_eq!(handle_color(&theme, true), active);
        });
    }

    /// The payload a caller drags a handle with.
    #[derive(Clone)]
    struct Resize;

    impl Render for Resize {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// What the listeners a caller put on a handle, and on its container, heard.
    #[derive(Default)]
    struct Heard {
        container_hovered: Cell<Option<bool>>,
        handle_hovered: Cell<Option<bool>>,
        double_clicks: Cell<usize>,
        drag_moves: RefCell<Vec<Pixels>>,
        /// Every state the appearance was drawn in, repeats collapsed.
        states: RefCell<Vec<ResizeHandleState>>,
    }

    /// A 200px container whose trailing edge a handle hugs, listened to the way
    /// an application's own sidebar would be.
    struct CallerHarness {
        heard: Rc<Heard>,
    }

    impl Render for CallerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let heard = self.heard.clone();
            div().w(px(400.)).h(px(100.)).child(
                div()
                    .id("container")
                    .relative()
                    .w(px(200.))
                    .h_full()
                    .on_hover({
                        let heard = heard.clone();
                        move |hovered: &bool, _, _| heard.container_hovered.set(Some(*hovered))
                    })
                    .on_drag_move({
                        let heard = heard.clone();
                        move |event: &DragMoveEvent<Resize>, _, _| {
                            heard.drag_moves.borrow_mut().push(event.event.position.x)
                        }
                    })
                    .child(
                        resize_handle("edge", Axis::Horizontal)
                            .inside(HandleEdge::Trailing)
                            .with_appearance(Rc::new({
                                let heard = heard.clone();
                                move |handle: &ResizeHandleContext, _: &mut Window, _: &mut App| {
                                    let mut states = heard.states.borrow_mut();
                                    if states.last() != Some(&handle.state()) {
                                        states.push(handle.state());
                                    }
                                    None
                                }
                            }))
                            .on_hover({
                                let heard = heard.clone();
                                move |hovered: &bool, _, _| heard.handle_hovered.set(Some(*hovered))
                            })
                            .on_double_click({
                                let heard = heard.clone();
                                move |_, _, _| {
                                    heard.double_clicks.set(heard.double_clicks.get() + 1)
                                }
                            })
                            .on_drag(Resize, |drag, _, _, cx| cx.new(|_| drag.clone())),
                    ),
            )
        }
    }

    /// Listeners a caller attaches to a handle reach the band, and leave the
    /// progression base reports to the appearance as it was.
    #[gpui::test]
    fn a_callers_listeners_reach_the_band(cx: &mut TestAppContext) {
        let heard = Rc::new(Heard::default());
        let (_, cx) = cx.add_window_view({
            let heard = heard.clone();
            move |_, _| CallerHarness { heard }
        });
        let draw = |cx: &mut VisualTestContext| cx.update(|window, cx| window.draw(cx).clear(cx));
        let press = |cx: &mut VisualTestContext, click_count| {
            cx.simulate_event(MouseDownEvent {
                position: point(px(198.), px(50.)),
                modifiers: Modifiers::default(),
                button: MouseButton::Left,
                click_count,
                first_mouse: false,
            });
        };
        let release = |cx: &mut VisualTestContext, x, click_count| {
            cx.simulate_event(MouseUpEvent {
                position: point(x, px(50.)),
                modifiers: Modifiers::default(),
                button: MouseButton::Left,
                click_count,
            });
        };
        draw(cx);

        // The container spans 0..200, and the band hugs its last five pixels.
        cx.simulate_mouse_move(point(px(100.), px(50.)), None, Modifiers::default());
        draw(cx);
        assert_eq!(heard.container_hovered.get(), Some(true));

        cx.simulate_mouse_move(point(px(198.), px(50.)), None, Modifiers::default());
        draw(cx);
        assert_eq!(heard.handle_hovered.get(), Some(true));
        // The band occludes, so its own container stops reading as hovered.
        assert_eq!(heard.container_hovered.get(), Some(false));

        for click_count in [1, 2] {
            press(cx, click_count);
            draw(cx);
            release(cx, px(198.), click_count);
            draw(cx);
        }
        assert_eq!(heard.double_clicks.get(), 1);

        press(cx, 1);
        draw(cx);
        for x in [px(190.), px(120.)] {
            cx.simulate_mouse_move(
                point(x, px(50.)),
                Some(MouseButton::Left),
                Modifiers::default(),
            );
            draw(cx);
        }
        release(cx, px(120.), 1);
        draw(cx);

        // The drag carries `Resize` itself. When it carried an `Rc<Resize>`,
        // the container's `on_drag_move::<Resize>` never heard a thing.
        assert_eq!(heard.drag_moves.borrow().last(), Some(&px(120.)));
        // A drag is no click, let alone a double one.
        assert_eq!(heard.double_clicks.get(), 1);
        assert_eq!(
            *heard.states.borrow(),
            vec![
                ResizeHandleState::Idle,
                ResizeHandleState::Hovered,
                ResizeHandleState::Pressed,
                ResizeHandleState::Hovered,
                ResizeHandleState::Pressed,
                ResizeHandleState::Hovered,
                ResizeHandleState::Pressed,
                ResizeHandleState::Dragging,
                ResizeHandleState::Idle,
            ]
        );
    }
}
