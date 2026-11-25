use std::{panic::Location, sync::Arc};

use gpui::{
    AnyElement, App, Axis, Bounds, ClickEvent, Element, ElementId, Entity, FocusHandle, Focusable,
    GlobalElementId, InspectorElementId, InteractiveElement as _, IntoElement, LayoutId,
    MouseButton, ParentElement, Pixels, Point, RenderOnce, Role, SharedString,
    StatefulInteractiveElement as _, StyleRefinement, Styled, Subscription, Window, div,
    prelude::FluentBuilder as _, px,
};
use gpui_base::spring;
use rust_i18n::t;

use super::{CONTEXT, scroll_mask::CarouselScrollMask, state::CarouselState};
use crate::{
    AxisExt as _, Disableable as _, ElementExt as _, Selectable as _, Sizable as _, Size,
    StyledExt as _, ThemeStyled as _,
    actions::{SelectDown, SelectFirst, SelectLast, SelectLeft, SelectRight, SelectUp},
    button::Button,
    icon::IconName,
    theme::ActiveTheme as _,
};

/// A composable carousel root.
///
/// Add one [`CarouselContent`] and any optional controls as children. Every
/// part must share the same [`CarouselState`].
#[derive(IntoElement)]
pub struct Carousel {
    id: ElementId,
    state: Entity<CarouselState>,
    style: StyleRefinement,
    accessibility_label: SharedString,
    focus_ring_enabled: bool,
    children: Vec<AnyElement>,
}

struct CarouselStateObserver {
    _subscription: Subscription,
}

/// Restores the focus ring once the carousel loses focus, so the next
/// keyboard focus draws it again.
struct CarouselFocusOut {
    _subscription: Subscription,
}

impl Carousel {
    /// Creates a Carousel bound to `state`.
    pub fn new(id: impl Into<ElementId>, state: &Entity<CarouselState>) -> Self {
        Self {
            id: id.into(),
            state: state.clone(),
            style: StyleRefinement::default(),
            accessibility_label: t!("Carousel.label").into(),
            focus_ring_enabled: true,
            children: Vec::new(),
        }
    }

    /// Sets the name announced for the carousel region.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = label.into();
        self
    }
}

impl ParentElement for Carousel {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for Carousel {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl crate::FocusableExt for Carousel {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl RenderOnce for Carousel {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let observed_state = self.state.clone();
        let _observer = window.use_keyed_state(
            ("carousel-state-observer", self.state.entity_id()),
            cx,
            move |_, cx| CarouselStateObserver {
                _subscription: cx.observe(&observed_state, |_, _, cx| cx.notify()),
            },
        );
        let snapshot = self.state.read(cx);
        let axis = snapshot.axis();
        let frame_size = snapshot.frame_size();
        let focus_handle = snapshot.focus_handle(cx);
        let ring_suppressed = snapshot.is_focus_ring_suppressed();
        let _focus_out =
            window.use_keyed_state(("carousel-focus-out", self.state.entity_id()), cx, {
                let state = self.state.clone();
                let focus_handle = focus_handle.clone();
                move |window, cx| CarouselFocusOut {
                    _subscription: window.on_focus_out(&focus_handle, cx, move |_, _, cx| {
                        state.update(cx, |state, _| state.suppress_focus_ring(false));
                    }),
                }
            });
        let is_focused = focus_handle.is_focused(window);
        let focus_visible = is_focused && !ring_suppressed && self.focus_ring_enabled;
        let previous_state = self.state.clone();
        let next_state = self.state.clone();
        let first_state = self.state.clone();
        let last_state = self.state.clone();

        div()
            .id(self.id)
            .relative()
            .flex()
            .flex_col()
            .gap_4()
            .role(Role::Region)
            .aria_label(self.accessibility_label)
            .track_focus(&focus_handle.tab_stop(true))
            .key_context(CONTEXT)
            .on_mouse_down(MouseButton::Left, {
                let state = self.state.clone();
                move |_, window, cx| {
                    // Runs before GPUI moves focus here. A child such as
                    // Button that keeps focus has already prevented the default.
                    if !is_focused && !window.default_prevented() {
                        state.update(cx, |state, _| state.suppress_focus_ring(true));
                    }
                }
            })
            .on_action(
                window.listener_for(&previous_state, move |state, _: &SelectLeft, _, cx| {
                    let handled = axis.is_horizontal() && state.select_previous(cx);
                    if !handled {
                        cx.propagate();
                    }
                }),
            )
            .on_action(
                window.listener_for(&next_state, move |state, _: &SelectRight, _, cx| {
                    let handled = axis.is_horizontal() && state.select_next(cx);
                    if !handled {
                        cx.propagate();
                    }
                }),
            )
            .on_action(
                window.listener_for(&previous_state, move |state, _: &SelectUp, _, cx| {
                    let handled = axis.is_vertical() && state.select_previous(cx);
                    if !handled {
                        cx.propagate();
                    }
                }),
            )
            .on_action(
                window.listener_for(&next_state, move |state, _: &SelectDown, _, cx| {
                    let handled = axis.is_vertical() && state.select_next(cx);
                    if !handled {
                        cx.propagate();
                    }
                }),
            )
            .on_action(
                window.listener_for(&first_state, |state, _: &SelectFirst, _, cx| {
                    if !state.select_first(cx) {
                        cx.propagate();
                    }
                }),
            )
            .on_action(
                window.listener_for(&last_state, |state, _: &SelectLast, _, cx| {
                    if !state.select_last(cx) {
                        cx.propagate();
                    }
                }),
            )
            .children(self.children)
            .when(focus_visible, |this| {
                this.when_some(frame_size, |this, size| {
                    this.child(
                        div()
                            .absolute()
                            .top_0()
                            .left_0()
                            .w(size.width)
                            .h(size.height)
                            .border_1()
                            .border_color(cx.theme().transparent)
                            .rounded(cx.theme().radius)
                            .focus_ring_style(window, cx),
                    )
                })
            })
            .refine_style(&self.style)
    }
}

#[derive(Default, PartialEq)]
struct CarouselGeometry {
    viewport: Bounds<Pixels>,
    frame: Bounds<Pixels>,
    items: Vec<Bounds<Pixels>>,
    has_runway: bool,
    revision: usize,
}

impl CarouselGeometry {
    /// Reads the layout relative to the content `frame` origin.
    ///
    /// Window-space bounds move whenever an ancestor scrolls or shifts the
    /// carousel, while every snap and loop calculation uses only differences
    /// and sizes. Storing frame-relative bounds keeps those moves from being
    /// treated as layout changes.
    fn read(
        state: &CarouselState,
        frame: Bounds<Pixels>,
        has_runway: bool,
        rendered_item_count: usize,
    ) -> Self {
        let handle = state.scroll_handle();
        let item_offset = usize::from(has_runway);
        let origin = frame.origin;
        let relative = |bounds: Bounds<Pixels>| Bounds::new(bounds.origin - origin, bounds.size);
        Self {
            viewport: relative(handle.bounds()),
            frame: Bounds::new(Point::default(), frame.size),
            items: (0..state.item_count().min(rendered_item_count))
                .filter_map(|ix| handle.bounds_for_item(ix + item_offset).map(&relative))
                .collect(),
            has_runway,
            revision: 0,
        }
    }

    /// Compares layouts with a sub-pixel tolerance so float noise from the
    /// frame-relative subtraction does not register as a layout change.
    fn same_layout(&self, other: &Self) -> bool {
        self.has_runway == other.has_runway
            && same_bounds(self.viewport, other.viewport)
            && same_bounds(self.frame, other.frame)
            && self.items.len() == other.items.len()
            && self
                .items
                .iter()
                .zip(&other.items)
                .all(|(left, right)| same_bounds(*left, *right))
    }
}

fn same_bounds(left: Bounds<Pixels>, right: Bounds<Pixels>) -> bool {
    const TOLERANCE: Pixels = px(0.01);
    (left.origin.x - right.origin.x).abs() <= TOLERANCE
        && (left.origin.y - right.origin.y).abs() <= TOLERANCE
        && (left.size.width - right.size.width).abs() <= TOLERANCE
        && (left.size.height - right.size.height).abs() <= TOLERANCE
}

/// The clipped viewport and snap track for Carousel items.
#[derive(IntoElement)]
pub struct CarouselContent {
    state: Entity<CarouselState>,
    style: StyleRefinement,
    track_style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl CarouselContent {
    /// Creates content bound to `state`.
    pub fn new(state: &Entity<CarouselState>) -> Self {
        Self {
            state: state.clone(),
            style: StyleRefinement::default(),
            track_style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }

    /// Sets style overrides for the inner flex track.
    ///
    /// Use this for paired Carousel spacing such as a negative leading margin.
    /// The [`Styled`] implementation applies to the clipped viewport itself.
    pub fn track_style(mut self, style: StyleRefinement) -> Self {
        self.track_style = style;
        self
    }
}

impl ParentElement for CarouselContent {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for CarouselContent {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

/// A layout-transparent proxy that paints one real item in the closest loop
/// cycle. The child keeps its original layout id, so ScrollHandle geometry
/// continues to address logical items without cloning their elements.
struct CarouselLoopItem {
    child: AnyElement,
    index: usize,
    state: Entity<CarouselState>,
}

impl IntoElement for CarouselLoopItem {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for CarouselLoopItem {
    type RequestLayoutState = ();
    type PrepaintState = Point<Pixels>;

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        (self.child.request_layout(window, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let offset = self.state.read(cx).loop_item_offset(self.index);
        window.with_element_offset(offset, |window| {
            self.child.prepaint(window, cx);
        });
        offset
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.child.paint(window, cx);
    }
}

impl RenderOnce for CarouselContent {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let entity_id = self.state.entity_id();
        let snapshot = self.state.read(cx);
        let axis = snapshot.axis();
        let selected_ix = snapshot.selected_index();
        let item_count = snapshot.item_count();
        let handle = snapshot.scroll_handle().clone();
        let interacting = snapshot.is_interacting();
        let motion_revision = snapshot.motion_revision();
        let loop_runway = snapshot.loop_runway();
        let loop_layout_transitioning = snapshot.is_loop_layout_transitioning();
        let state_snap_target = selected_ix.and_then(|ix| snapshot.motion_target_for(ix));

        let geometry = window.use_keyed_state(
            ElementId::NamedChild(
                Arc::new(("carousel-geometry", entity_id).into()),
                "content".into(),
            ),
            cx,
            |_, _| CarouselGeometry::default(),
        );
        let geometry_revision = geometry.read(cx).revision;

        let current = axis_value(handle.offset(), axis);
        let target = if loop_layout_transitioning {
            current
        } else {
            state_snap_target
                .map(|target| axis_value(target, axis))
                .or_else(|| {
                    selected_ix.and_then(|ix| {
                        snap_offset(&handle, axis, ix + usize::from(loop_runway.is_some()))
                    })
                })
                .unwrap_or(current)
        };
        let target = if interacting { current } else { target };
        let snap_spring = cx.theme().motion_tokens().spring_move.with_epsilon(0.5);
        let animated = spring(
            (
                ("carousel-content", entity_id),
                SharedString::from(format!("offset-{motion_revision}-{geometry_revision}")),
            ),
            target.as_f32(),
            snap_spring.with_travel(!interacting),
            window,
            cx,
        );
        let mut offset = handle.offset();
        set_axis_value(&mut offset, axis, px(animated));
        set_axis_value(
            &mut offset,
            if axis.is_horizontal() {
                Axis::Vertical
            } else {
                Axis::Horizontal
            },
            Pixels::ZERO,
        );
        handle.set_offset(offset);
        if !interacting {
            let rendered = offset;
            if let Some(rebased) = self
                .state
                .update(cx, |state, cx| state.settle_loop_motion(rendered, cx))
            {
                offset = rebased;
                handle.set_offset(offset);
            }
        }

        let geometry_state = self.state.clone();
        let viewport_id: ElementId = ("carousel-content", entity_id).into();

        let rendered_item_count = self.children.len();
        let loop_state = self.state.clone();
        let children = self
            .children
            .into_iter()
            .enumerate()
            .map(move |(index, child)| CarouselLoopItem {
                child,
                index,
                state: loop_state.clone(),
            });
        let runway_spacer = |runway: Pixels| {
            div()
                .flex_none()
                .when(axis.is_horizontal(), |this| this.w(runway))
                .when(axis.is_vertical(), |this| this.h(runway))
        };
        let has_runway = loop_runway.is_some();

        div()
            .relative()
            .w_full()
            .flex()
            .when(axis.is_horizontal(), |this| this.flex_row())
            .when(axis.is_vertical(), |this| this.flex_col())
            .refine_style(&self.style)
            .overflow_hidden()
            .child(
                // As a flex child the track grows by its negative leading
                // margin, so the padded items fill the frame on both edges.
                div()
                    .id(viewport_id.clone())
                    .flex_1()
                    .flex()
                    .when(axis.is_horizontal(), |this| {
                        this.flex_row().min_w_0().ml_neg_4()
                    })
                    .when(axis.is_vertical(), |this| {
                        this.flex_col().min_h_0().mt_neg_4()
                    })
                    .track_scroll(&handle)
                    .when_some(loop_runway, |this, runway| {
                        this.child(runway_spacer(runway))
                    })
                    .children(children)
                    .when_some(loop_runway, |this, runway| {
                        this.child(runway_spacer(runway))
                    })
                    .refine_style(&self.track_style),
            )
            .child(CarouselScrollMask::new(axis, &self.state).id(viewport_id))
            .on_prepaint(move |frame, _, cx| {
                let next = CarouselGeometry::read(
                    geometry_state.read(cx),
                    frame,
                    has_runway,
                    rendered_item_count,
                );
                if !geometry.read(cx).same_layout(&next) {
                    geometry_state.update(cx, |state, _| {
                        state.set_geometry_with_runway(
                            next.viewport,
                            next.frame,
                            next.items.clone(),
                            next.has_runway,
                        );
                    });
                    geometry.update(cx, |current, cx| {
                        current.viewport = next.viewport;
                        current.frame = next.frame;
                        current.items = next.items;
                        current.has_runway = next.has_runway;
                        current.revision = current.revision.wrapping_add(1);
                        cx.notify();
                    });
                }
            })
            .when(item_count == 0, |this| this.invisible())
    }
}

/// One logical slide in a [`CarouselContent`].
#[derive(IntoElement)]
pub struct CarouselItem {
    id: ElementId,
    index: usize,
    state: Entity<CarouselState>,
    style: StyleRefinement,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
}

impl CarouselItem {
    /// Creates the item at the zero-based `index` used by `state`.
    pub fn new(id: impl Into<ElementId>, index: usize, state: &Entity<CarouselState>) -> Self {
        Self {
            id: id.into(),
            index,
            state: state.clone(),
            style: StyleRefinement::default(),
            accessibility_label: None,
            children: Vec::new(),
        }
    }

    /// Replaces the generated "Slide N of M" accessibility label.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl ParentElement for CarouselItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for CarouselItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for CarouselItem {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let axis = state.axis();
        let count = state.item_count();
        let label = self.accessibility_label.unwrap_or_else(|| {
            t!(
                "Carousel.slide",
                current = self.index.saturating_add(1),
                total = count
            )
            .into()
        });

        div()
            .id(self.id)
            .role(Role::Group)
            .aria_label(label)
            .aria_position_in_set(self.index.saturating_add(1))
            .aria_size_of_set(count)
            .min_w_0()
            .min_h_0()
            .flex_none()
            .when(axis.is_horizontal(), |this| this.w_full().pl_4())
            .when(axis.is_vertical(), |this| this.h_full().pt_4())
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// A previous-slide control positioned around the Carousel viewport.
#[derive(IntoElement)]
pub struct CarouselPrevious {
    state: Entity<CarouselState>,
    size: Size,
    style: StyleRefinement,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
}

impl CarouselPrevious {
    /// Creates a previous-slide control bound to `state`.
    pub fn new(state: &Entity<CarouselState>) -> Self {
        Self {
            state: state.clone(),
            size: Size::Medium,
            style: StyleRefinement::default(),
            accessibility_label: None,
            children: Vec::new(),
        }
    }

    /// Replaces the generated previous-slide accessibility label and tooltip.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl crate::Sizable for CarouselPrevious {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for CarouselPrevious {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for CarouselPrevious {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for CarouselPrevious {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        carousel_control(
            self.state,
            self.size,
            self.style,
            self.accessibility_label,
            self.children,
            false,
            cx,
        )
    }
}

/// A next-slide control positioned around the Carousel viewport.
#[derive(IntoElement)]
pub struct CarouselNext {
    state: Entity<CarouselState>,
    size: Size,
    style: StyleRefinement,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
}

impl CarouselNext {
    /// Creates a next-slide control bound to `state`.
    pub fn new(state: &Entity<CarouselState>) -> Self {
        Self {
            state: state.clone(),
            size: Size::Medium,
            style: StyleRefinement::default(),
            accessibility_label: None,
            children: Vec::new(),
        }
    }

    /// Replaces the generated next-slide accessibility label and tooltip.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl crate::Sizable for CarouselNext {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for CarouselNext {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for CarouselNext {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for CarouselNext {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        carousel_control(
            self.state,
            self.size,
            self.style,
            self.accessibility_label,
            self.children,
            true,
            cx,
        )
    }
}

fn carousel_control(
    state: Entity<CarouselState>,
    size: Size,
    style: StyleRefinement,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
    next: bool,
    cx: &mut App,
) -> impl IntoElement {
    let snapshot = state.read(cx);
    let axis = snapshot.axis();
    let frame_size = snapshot.frame_size();
    let focus_handle = snapshot.focus_handle(cx);
    let disabled = if next {
        !snapshot.has_next()
    } else {
        !snapshot.has_previous()
    };
    let (name, default_label, icon) = match (axis, next) {
        (Axis::Horizontal, false) => ("previous", t!("Carousel.previous"), IconName::ChevronLeft),
        (Axis::Horizontal, true) => ("next", t!("Carousel.next"), IconName::ChevronRight),
        (Axis::Vertical, false) => ("previous", t!("Carousel.previous"), IconName::ChevronUp),
        (Axis::Vertical, true) => ("next", t!("Carousel.next"), IconName::ChevronDown),
    };
    let label = accessibility_label.unwrap_or_else(|| default_label.into());
    let has_custom_content = !children.is_empty();
    let id = ElementId::NamedChild(
        Arc::new(("carousel-control", state.entity_id()).into()),
        name.into(),
    );

    div()
        .absolute()
        .top_0()
        .left_0()
        .when_some(frame_size, |this, size| this.w(size.width).h(size.height))
        .when(frame_size.is_none(), |this| this.right_0().bottom_0())
        .child(
            Button::new(id)
                .outline()
                .with_size(size)
                .when(!has_custom_content, |this| this.icon(icon))
                .accessibility_label(label.clone())
                .tooltip(label)
                .disabled(disabled)
                .absolute()
                .rounded_full_style(cx)
                .when(axis.is_horizontal() && !next, |this| {
                    this.right_full().mr_4().top_0().bottom_0().my_auto()
                })
                .when(axis.is_horizontal() && next, |this| {
                    this.left_full().ml_4().top_0().bottom_0().my_auto()
                })
                .when(axis.is_vertical() && !next, |this| {
                    this.bottom_full().mb_4().left_0().right_0().mx_auto()
                })
                .when(axis.is_vertical() && next, |this| {
                    this.top_full().mt_4().left_0().right_0().mx_auto()
                })
                .when(!disabled, |this| {
                    this.on_click(move |event, window, cx| {
                        state.update(cx, |state, cx| {
                            if next {
                                state.select_next(cx);
                            } else {
                                state.select_previous(cx);
                            }
                        });
                        focus_after_pointer_click(&state, &focus_handle, event, window, cx);
                    })
                })
                .children(children)
                .refine_style(&style),
        )
}

/// A composable container for Carousel pagination items.
#[derive(IntoElement)]
pub struct CarouselPagination {
    id: ElementId,
    style: StyleRefinement,
    accessibility_label: SharedString,
    children: Vec<AnyElement>,
}

impl CarouselPagination {
    /// Creates an empty pagination container.
    #[track_caller]
    pub fn new() -> Self {
        Self {
            id: ElementId::CodeLocation(*Location::caller()),
            style: StyleRefinement::default(),
            accessibility_label: t!("Carousel.pagination").into(),
            children: Vec::new(),
        }
    }

    /// Sets the name announced for the pagination group.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = label.into();
        self
    }
}

impl ParentElement for CarouselPagination {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for CarouselPagination {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for CarouselPagination {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div()
            .id(self.id)
            .role(Role::Group)
            .aria_label(self.accessibility_label)
            .flex()
            .items_center()
            .justify_center()
            .gap_2()
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// One application-styled pagination control for a Carousel item.
#[derive(IntoElement)]
pub struct CarouselPaginationItem {
    id: ElementId,
    index: usize,
    state: Entity<CarouselState>,
    size: Size,
    style: StyleRefinement,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
}

impl CarouselPaginationItem {
    /// Creates a pagination item for the zero-based `index`.
    pub fn new(id: impl Into<ElementId>, index: usize, state: &Entity<CarouselState>) -> Self {
        Self {
            id: id.into(),
            index,
            state: state.clone(),
            size: Size::XSmall,
            style: StyleRefinement::default(),
            accessibility_label: None,
            children: Vec::new(),
        }
    }

    /// Replaces the generated "Go to slide N" accessibility label.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl crate::Sizable for CarouselPaginationItem {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ParentElement for CarouselPaginationItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for CarouselPaginationItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for CarouselPaginationItem {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let selected = self.state.read(cx).selected_index() == Some(self.index);
        let disabled = self.index >= self.state.read(cx).item_count();
        let focus_handle = self.state.read(cx).focus_handle(cx);
        let label = self.accessibility_label.unwrap_or_else(|| {
            t!(
                "Carousel.go_to_slide",
                current = self.index.saturating_add(1)
            )
            .into()
        });
        let state = self.state;
        let index = self.index;

        Button::new(self.id)
            .compact()
            .with_size(self.size)
            .selected(selected)
            .accessibility_label(label)
            .disabled(disabled)
            .children(self.children)
            .when(!disabled, |this| {
                this.on_click(move |event, window, cx| {
                    state.update(cx, |state, cx| {
                        state.select_index(index, cx);
                    });
                    focus_after_pointer_click(&state, &focus_handle, event, window, cx);
                })
            })
            .refine_style(&self.style)
    }
}

/// Moves keyboard focus to the carousel after a pointer click on one of its
/// controls, so the arrow keys keep working without drawing the ring. A
/// keyboard activation leaves focus on the control.
fn focus_after_pointer_click(
    state: &Entity<CarouselState>,
    focus_handle: &FocusHandle,
    event: &ClickEvent,
    window: &mut Window,
    cx: &mut App,
) {
    if event.is_keyboard() || focus_handle.contains_focused(window, cx) {
        return;
    }
    state.update(cx, |state, _| state.suppress_focus_ring(true));
    window.focus(focus_handle, cx);
}

fn axis_value(point: Point<Pixels>, axis: Axis) -> Pixels {
    if axis.is_horizontal() {
        point.x
    } else {
        point.y
    }
}

fn set_axis_value(point: &mut Point<Pixels>, axis: Axis, value: Pixels) {
    if axis.is_horizontal() {
        point.x = value;
    } else {
        point.y = value;
    }
}

fn snap_offset(handle: &gpui::ScrollHandle, axis: Axis, index: usize) -> Option<Pixels> {
    let viewport = handle.bounds();
    let item = handle.bounds_for_item(index)?;
    let target = if axis.is_horizontal() {
        viewport.left() - item.left()
    } else {
        viewport.top() - item.top()
    };
    let max = axis_value(handle.max_offset(), axis).max(Pixels::ZERO);
    Some(target.clamp(-max, Pixels::ZERO))
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use super::*;
    use gpui::{AppContext as _, Context, Render, VisualTestContext, point};
    use gpui_base::FocusableExt as _;

    #[test]
    fn axis_helpers_only_change_the_requested_coordinate() {
        let mut value = point(px(3.), px(7.));
        set_axis_value(&mut value, Axis::Horizontal, px(11.));
        assert_eq!(value, point(px(11.), px(7.)));
        set_axis_value(&mut value, Axis::Vertical, px(-5.));
        assert_eq!(value, point(px(11.), px(-5.)));
    }

    #[gpui::test]
    fn carousel_controls_accept_semantic_sizes(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2)));

        assert_eq!(CarouselPrevious::new(&state).size, Size::Medium);
        assert_eq!(CarouselNext::new(&state).size, Size::Medium);
        assert_eq!(CarouselPrevious::new(&state).large().size, Size::Large);
        assert_eq!(CarouselNext::new(&state).xsmall().size, Size::XSmall);
        assert_eq!(
            CarouselPaginationItem::new("pagination", 0, &state)
                .small()
                .size,
            Size::Small
        );
    }

    #[gpui::test]
    fn carousel_focus_ring_is_configurable(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2)));

        assert!(Carousel::new("carousel", &state).is_focus_ring_enabled());
        assert!(
            !Carousel::new("carousel", &state)
                .focus_ring(false)
                .is_focus_ring_enabled()
        );
    }

    struct KeyboardHarness {
        state: Entity<CarouselState>,
    }

    impl Render for KeyboardHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().tab_group().child(
                Carousel::new("carousel", &self.state)
                    .w(px(100.))
                    .h(px(100.))
                    .child(
                        CarouselContent::new(&self.state)
                            .h(px(100.))
                            .children((0..3).map(|index| {
                                CarouselItem::new(("carousel-item", index), index, &self.state)
                                    .child(index.to_string())
                            })),
                    ),
            )
        }
    }

    fn assert_contextual_navigation_keys(cx: &mut gpui::TestAppContext, axis: Axis) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(3).with_axis(axis)));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            move |_, _| KeyboardHarness { state }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        cx.update(|window, cx| window.focus_next(cx));
        let (primary, secondary) = if axis.is_horizontal() {
            ("right", "down")
        } else {
            ("down", "right")
        };
        cx.simulate_keystrokes(primary);
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        cx.simulate_keystrokes(secondary);
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        cx.simulate_keystrokes("end");
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(2)
        );
        cx.simulate_keystrokes("home");
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(0)
        );
    }

    #[gpui::test]
    fn horizontal_carousel_dispatches_contextual_navigation_keys(cx: &mut gpui::TestAppContext) {
        assert_contextual_navigation_keys(cx, Axis::Horizontal);
    }

    #[gpui::test]
    fn vertical_carousel_dispatches_contextual_navigation_keys(cx: &mut gpui::TestAppContext) {
        assert_contextual_navigation_keys(cx, Axis::Vertical);
    }

    struct PropagationHarness {
        state: Entity<CarouselState>,
        outer_actions: Rc<Cell<usize>>,
    }

    impl Render for PropagationHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let down = self.outer_actions.clone();
            let left = self.outer_actions.clone();
            let right = self.outer_actions.clone();
            div()
                .tab_group()
                .on_action(move |_: &SelectDown, _, _| down.set(down.get() + 1))
                .on_action(move |_: &SelectLeft, _, _| left.set(left.get() + 1))
                .on_action(move |_: &SelectRight, _, _| right.set(right.get() + 1))
                .child(
                    Carousel::new("carousel", &self.state)
                        .w(px(100.))
                        .h(px(100.))
                        .child(
                            CarouselContent::new(&self.state)
                                .h(px(100.))
                                .children((0..3).map(|index| {
                                    CarouselItem::new(("carousel-item", index), index, &self.state)
                                        .child(index.to_string())
                                })),
                        ),
                )
        }
    }

    #[gpui::test]
    fn unhandled_navigation_keys_reach_ancestors(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(3)));
        let outer_actions = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            let outer_actions = outer_actions.clone();
            move |_, _| PropagationHarness {
                state,
                outer_actions,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|window, cx| window.focus_next(cx));

        cx.simulate_keystrokes("down");
        assert_eq!(outer_actions.get(), 1);

        cx.simulate_keystrokes("left");
        assert_eq!(outer_actions.get(), 2);
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(0)
        );

        cx.simulate_keystrokes("right");
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        assert_eq!(outer_actions.get(), 2);
    }

    #[gpui::test]
    fn track_grows_by_its_leading_margin_so_items_fill_the_frame(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        for axis in [Axis::Horizontal, Axis::Vertical] {
            let state = cx.update(|cx| cx.new(|_| CarouselState::new(3).with_axis(axis)));
            let (_, cx) = cx.add_window_view({
                let state = state.clone();
                move |_, _| KeyboardHarness { state }
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));

            let (track, first_item, frame_size) = state.read_with(cx, |state, _| {
                let handle = state.scroll_handle();
                (
                    handle.bounds(),
                    handle.bounds_for_item(0).unwrap(),
                    state.frame_size().unwrap(),
                )
            });
            assert_eq!(frame_size, gpui::size(px(100.), px(100.)), "{axis:?}");
            let expected = if axis.is_horizontal() {
                Bounds::new(point(px(-16.), px(0.)), gpui::size(px(116.), px(100.)))
            } else {
                Bounds::new(point(px(0.), px(-16.)), gpui::size(px(100.), px(116.)))
            };
            assert_eq!(track, expected, "{axis:?}");
            assert_eq!(first_item, expected, "{axis:?}");
        }
    }

    #[gpui::test]
    fn clicking_a_slide_focuses_the_carousel_for_keyboard_navigation(
        cx: &mut gpui::TestAppContext,
    ) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(3)));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            move |_, _| KeyboardHarness { state }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.update(|window, cx| window.focused(cx).is_none()));

        cx.simulate_click(point(px(50.), px(50.)), gpui::Modifiers::default());
        assert!(cx.update(|window, cx| window.focused(cx).is_some()));

        cx.simulate_keystrokes("right");
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
    }

    struct ControlsHarness {
        state: Entity<CarouselState>,
    }

    impl Render for ControlsHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().tab_group().child(
                Carousel::new("carousel", &self.state)
                    .w(px(100.))
                    .h(px(100.))
                    .child(
                        CarouselContent::new(&self.state)
                            .h(px(100.))
                            .children((0..3).map(|index| {
                                CarouselItem::new(("carousel-item", index), index, &self.state)
                                    .child(index.to_string())
                            })),
                    )
                    .child(CarouselPrevious::new(&self.state))
                    .child(CarouselNext::new(&self.state)),
            )
        }
    }

    #[gpui::test]
    fn clicking_a_control_focuses_the_carousel_for_keyboard_navigation(
        cx: &mut gpui::TestAppContext,
    ) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(3)));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            move |_, _| ControlsHarness { state }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let selected =
            |cx: &mut VisualTestContext| state.read_with(cx, |state, _| state.selected_index());
        let root_focused = |cx: &mut VisualTestContext| {
            cx.update(|window, cx| state.read(cx).focus_handle(cx).is_focused(window))
        };

        // A pointer click on Next moves focus to the carousel.
        cx.simulate_click(point(px(134.), px(50.)), gpui::Modifiers::default());
        assert_eq!(selected(cx), Some(1));
        assert!(root_focused(cx));
        cx.simulate_keystrokes("right");
        assert_eq!(selected(cx), Some(2));

        // Keyboard activation of a control leaves focus on the control.
        cx.simulate_keystrokes("left");
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let keystroke = gpui::Keystroke::parse("enter").unwrap();
        cx.simulate_event(gpui::KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(gpui::KeyUpEvent { keystroke });
        assert_eq!(selected(cx), Some(2));
        assert!(!root_focused(cx));
        assert!(cx.update(|window, cx| window.focused(cx).is_some()));
    }

    #[gpui::test]
    fn carousel_controls_accept_accessibility_labels_and_children(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2)));
        let previous = CarouselPrevious::new(&state)
            .accessibility_label("Previous project")
            .child("Back");
        let next = CarouselNext::new(&state)
            .accessibility_label("Next project")
            .child("Forward");

        assert_eq!(
            previous.accessibility_label.as_deref(),
            Some("Previous project")
        );
        assert_eq!(next.accessibility_label.as_deref(), Some("Next project"));
        assert_eq!(previous.children.len(), 1);
        assert_eq!(next.children.len(), 1);
    }
}
