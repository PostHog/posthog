use std::{ops::Range, rc::Rc};

use gpui::{
    Along, AnyElement, App, AppContext, Axis, Bounds, Context, Element, ElementId, Empty, Entity,
    EventEmitter, InteractiveElement as _, IntoElement, IsZero as _, MouseMoveEvent, MouseUpEvent,
    ParentElement, Pixels, Render, RenderOnce, Style, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder,
};

use crate::{AxisExt, ElementExt, StyledExt as _, h_flex, resizable::PANEL_MIN_SIZE, v_flex};

use super::{ResizableState, ResizeHandleRenderer, resizable_panel, resize_handle};

pub enum ResizablePanelEvent {
    Resized,
}

#[derive(Clone)]
pub(crate) struct DragPanel;
impl Render for DragPanel {
    fn render(&mut self, _: &mut Window, _: &mut Context<'_, Self>) -> impl IntoElement {
        Empty
    }
}

/// A group of resizable panels.
#[derive(IntoElement)]
pub struct ResizablePanelGroup {
    id: ElementId,
    state: Option<Entity<ResizableState>>,
    axis: Axis,
    size: Option<Pixels>,
    children: Vec<ResizablePanel>,
    on_resize: Rc<dyn Fn(&Entity<ResizableState>, &mut Window, &mut App)>,
    handle_appearance: Option<ResizeHandleRenderer>,
}

impl ResizablePanelGroup {
    /// Create a new resizable panel group.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            axis: Axis::Horizontal,
            children: vec![],
            state: None,
            size: None,
            on_resize: Rc::new(|_, _, _| {}),
            handle_appearance: None,
        }
    }

    /// Hand the painted part of every divider in this group to `appearance`.
    ///
    /// The hit area, the cursor and the drag stay here; a renderer that
    /// returns `None` for a given handle leaves the built-in line on it.
    pub fn with_handle_appearance(mut self, appearance: ResizeHandleRenderer) -> Self {
        self.handle_appearance = Some(appearance);
        self
    }

    /// Bind yourself to a resizable state entity.
    ///
    /// If not provided, it will handle its own state internally.
    pub fn with_state(mut self, state: &Entity<ResizableState>) -> Self {
        self.state = Some(state.clone());
        self
    }

    /// Set the axis of the resizable panel group, default is horizontal.
    pub fn axis(mut self, axis: Axis) -> Self {
        self.axis = axis;
        self
    }

    /// Add a panel to the group.
    ///
    /// - The `axis` will be set to the same axis as the group.
    /// - The `initial_size` will be set to the average size of all panels if not provided.
    /// - The `group` will be set to the group entity.
    pub fn child(mut self, panel: impl Into<ResizablePanel>) -> Self {
        self.children.push(panel.into());
        self
    }

    /// Add multiple panels to the group.
    pub fn children<I>(mut self, panels: impl IntoIterator<Item = I>) -> Self
    where
        I: Into<ResizablePanel>,
    {
        self.children = panels.into_iter().map(|panel| panel.into()).collect();
        self
    }

    /// Set size of the resizable panel group
    ///
    /// - When the axis is horizontal, the size is the height of the group.
    /// - When the axis is vertical, the size is the width of the group.
    pub fn size(mut self, size: Pixels) -> Self {
        self.size = Some(size);
        self
    }

    /// Set the callback to be called when the panels are resized.
    ///
    /// ## Callback arguments
    ///
    /// - Entity<ResizableState>: The state of the ResizablePanelGroup.
    pub fn on_resize(
        mut self,
        on_resize: impl Fn(&Entity<ResizableState>, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_resize = Rc::new(on_resize);
        self
    }
}

impl<T> From<T> for ResizablePanel
where
    T: Into<AnyElement>,
{
    fn from(value: T) -> Self {
        resizable_panel().child(value.into())
    }
}

impl From<ResizablePanelGroup> for ResizablePanel {
    fn from(value: ResizablePanelGroup) -> Self {
        resizable_panel().child(value)
    }
}

impl EventEmitter<ResizablePanelEvent> for ResizablePanelGroup {}

impl RenderOnce for ResizablePanelGroup {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.unwrap_or(
            window.use_keyed_state(self.id.clone(), cx, |_, _| ResizableState::default()),
        );
        let container = if self.axis.is_horizontal() {
            h_flex()
        } else {
            v_flex()
        };

        // Sync panels to the state
        let panels_count = self.children.len();
        state.update(cx, |state, cx| {
            state.sync_panels_count(self.axis, panels_count, cx);
        });

        container
            .id(self.id)
            .size_full()
            // The group only distributes space along its own axis, so a caller
            // supplied size can only mean the cross axis.
            .when_some(self.size, |this, size| match self.axis {
                Axis::Horizontal => this.h(size),
                Axis::Vertical => this.w(size),
            })
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, mut panel)| {
                        panel.panel_ix = ix;
                        panel.axis = self.axis;
                        panel.state = Some(state.clone());
                        panel.handle_appearance = self.handle_appearance.clone();
                        panel
                    }),
            )
            .on_prepaint({
                let state = state.clone();
                move |bounds, window, cx| {
                    // The same bounds as last frame change nothing; updating
                    // the state for them would mark it changed every frame.
                    if state.read(cx).bounds == bounds {
                        return;
                    }
                    state.update(cx, |state, cx| {
                        let size_changed =
                            state.bounds.size.along(self.axis) != bounds.size.along(self.axis);

                        state.bounds = bounds;

                        if size_changed {
                            state.adjust_to_container_size(cx);
                            // The adjustment lands after this frame's layout has
                            // already been computed, and a notify raised during a
                            // draw only records the view as dirty without scheduling
                            // a frame for it. Defer the notify so it runs once the
                            // draw has finished and can schedule the settling frame.
                            // Otherwise that frame stays pending until some later
                            // input repaints the window, and the divider appears to
                            // jump on hover.
                            let state = cx.entity();
                            window.defer(cx, move |_, cx| {
                                state.update(cx, |_, cx| cx.notify());
                            });
                        }
                    })
                }
            })
            .child(ResizePanelGroupElement {
                state: state.clone(),
                axis: self.axis,
                on_resize: self.on_resize.clone(),
            })
    }
}

/// A resizable panel inside a [`ResizablePanelGroup`].
///
/// Implements [`Styled`], so call sites can override the panel's
/// rendered styles. User overrides are applied **between** the panel's
/// flex defaults and its size management — the caller can override the
/// internal `flex_grow: 1` (e.g. via `.flex_none()`) and add their own
/// padding / colors / borders, while the panel's runtime size
/// constraints (`min_w`/`max_w`/`flex_basis` driven by `ResizableState`)
/// always win.
///
/// A common override is `.flex_none()`: the panel sets `flex_grow: 1`
/// internally, so a sized panel that should hold its width when a
/// sibling collapses needs to opt out of growth via `.flex_none()`.
///
/// To keep a panel's size when the group's container resizes, use
/// [`ResizablePanel::fixed`].
///
/// ```ignore
/// h_resizable("layout")
///     .child(resizable_panel().size(px(220.)).flex_none().child(sidebar))
///     .child(resizable_panel().child(content))                // flex
///     .child(resizable_panel().size(px(280.)).flex_none().child(metadata))
/// ```
///
/// **Reserved styles**: do not call these from outside — they fight the
/// panel's own layout management:
/// - `.flex_basis(...)` — driven by `ResizableState`, not by the caller.
/// - `.absolute()` — would remove the panel from the resizable's flex flow.
/// - `.overflow_hidden()` — may clip the resize handle, which is positioned
///   absolute at `left: -4px` of each panel after the first.
#[derive(IntoElement)]
pub struct ResizablePanel {
    axis: Axis,
    panel_ix: usize,
    state: Option<Entity<ResizableState>>,
    /// Initial size is the size that the panel has when it is created.
    initial_size: Option<Pixels>,
    /// size range limit of this panel.
    size_range: Range<Pixels>,
    children: Vec<AnyElement>,
    visible: bool,
    style: StyleRefinement,
    handle_appearance: Option<ResizeHandleRenderer>,
    fixed: bool,
}

impl ResizablePanel {
    /// Create a new resizable panel.
    pub(super) fn new() -> Self {
        Self {
            panel_ix: 0,
            initial_size: None,
            state: None,
            size_range: (PANEL_MIN_SIZE..Pixels::MAX),
            axis: Axis::Horizontal,
            children: vec![],
            visible: true,
            style: StyleRefinement::default(),
            handle_appearance: None,
            fixed: false,
        }
    }

    /// Set the visibility of the panel, default is true.
    pub fn visible(mut self, visible: bool) -> Self {
        self.visible = visible;
        self
    }

    /// Set the initial size of the panel.
    pub fn size(mut self, size: impl Into<Pixels>) -> Self {
        self.initial_size = Some(size.into());
        self
    }

    /// Set the size range to limit panel resize.
    ///
    /// Default is [`PANEL_MIN_SIZE`] to [`Pixels::MAX`].
    pub fn size_range(mut self, range: impl Into<Range<Pixels>>) -> Self {
        self.size_range = range.into();
        self
    }

    /// Keep this panel's size when the group's container resizes.
    ///
    /// When the container grows or shrinks, the other panels share the
    /// difference in proportion to their sizes, so a sidebar or an inspector
    /// keeps the width the user gave it. Dragging its own handle still resizes
    /// it. It needs a [`Self::size`], and at least one panel in the group
    /// should not be fixed.
    pub fn fixed(mut self) -> Self {
        self.fixed = true;
        self
    }
}

impl Styled for ResizablePanel {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for ResizablePanel {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for ResizablePanel {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        if !self.visible {
            return div().id(("resizable-panel", self.panel_ix));
        }

        let state = self
            .state
            .expect("BUG: The `state` in ResizablePanel should be present.");
        let panel_state = state
            .read(cx)
            .panels
            .get(self.panel_ix)
            .expect("BUG: The `index` of ResizablePanel should be one of in `state`.");
        let size_range = self.size_range.clone();
        // A fixed panel needs a size to keep; without one it lays out as usual.
        let fixed = self.fixed && self.initial_size.is_some();

        div()
            .id(("resizable-panel", self.panel_ix))
            .flex()
            .flex_grow_1()
            .size_full()
            .relative()
            // Apply caller style overrides here — between the flex defaults
            // above and the size management below. This lets callers cancel
            // the unconditional `.flex_grow_1()` (via `.flex_none()`, the load-
            // bearing case for sized panels next to a collapsing sibling) and
            // add their own padding / colors / borders, while keeping the
            // panel's runtime size constraints (min/max + `flex_basis` driven
            // by `ResizableState`) authoritative.
            .refine_style(&self.style)
            .when(self.axis.is_vertical(), |this| {
                this.min_h(size_range.start).max_h(size_range.end)
            })
            .when(self.axis.is_horizontal(), |this| {
                this.min_w(size_range.start).max_w(size_range.end)
            })
            // 1. initial_size is None, to use auto size.
            // 2. initial_size is Some and size is none, to use the initial size of the panel for first time render.
            // 3. initial_size is Some and size is Some, use `size`.
            .when(self.initial_size.is_none(), |this| this.flex_shrink_1())
            .when_some(self.initial_size, |this, initial_size| {
                // The `self.size` is None, that mean the initial size for the panel,
                // so we need set `flex_shrink_0` To let it keep the initial size.
                this.when(
                    panel_state.size.is_none() && !initial_size.is_zero(),
                    |this| this.flex_none(),
                )
                .flex_basis(initial_size)
            })
            .map(|this| match panel_state.size {
                Some(size) => this.flex_basis(size.min(size_range.end).max(size_range.start)),
                None => this,
            })
            // A fixed panel neither grows nor shrinks with the container, so
            // the first frame of a resize already has its size. Not
            // `flex_none`, which also resets the basis set above.
            .when(fixed, |this| this.flex_grow_0().flex_shrink_0())
            .on_prepaint({
                let state = state.clone();
                move |bounds, _, cx| {
                    if !state.read(cx).panel_size_changes(
                        self.panel_ix,
                        bounds,
                        &self.size_range,
                        fixed,
                    ) {
                        return;
                    }
                    state.update(cx, |state, cx| {
                        state.update_panel_size(self.panel_ix, bounds, self.size_range, fixed, cx)
                    })
                }
            })
            .children(self.children)
            .when(self.panel_ix > 0, |this| {
                let ix = self.panel_ix - 1;
                this.child(
                    resize_handle(("resizable-handle", ix), self.axis)
                        .when_some(self.handle_appearance.clone(), |handle, appearance| {
                            handle.with_appearance(appearance)
                        })
                        .on_drag(DragPanel, move |drag_panel, _, _, cx| {
                            cx.stop_propagation();
                            // Set current resizing panel ix
                            state.update(cx, |state, _| {
                                state.resizing_panel_ix = Some(ix);
                            });
                            cx.new(|_| drag_panel.clone())
                        }),
                )
            })
    }
}

struct ResizePanelGroupElement {
    state: Entity<ResizableState>,
    on_resize: Rc<dyn Fn(&Entity<ResizableState>, &mut Window, &mut App)>,
    axis: Axis,
}

impl IntoElement for ResizePanelGroupElement {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for ResizePanelGroupElement {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<gpui::ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        (window.request_layout(Style::default(), None, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _window: &mut Window,
        _cx: &mut App,
    ) -> Self::PrepaintState {
        ()
    }

    fn paint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        _: &mut App,
    ) {
        window.on_mouse_event({
            let state = self.state.clone();
            let axis = self.axis;
            move |e: &MouseMoveEvent, phase, window, cx| {
                if !phase.bubble() {
                    return;
                }
                let Some(ix) = state.read(cx).resizing_panel_ix else {
                    return;
                };

                state.update(cx, |state, cx| {
                    let panel = state.panels.get(ix).expect("BUG: invalid panel index");

                    match axis {
                        Axis::Horizontal => state.resize_panel_at_handle(
                            ix,
                            e.position.x - panel.bounds.left(),
                            window,
                            cx,
                        ),
                        Axis::Vertical => state.resize_panel_at_handle(
                            ix,
                            e.position.y - panel.bounds.top(),
                            window,
                            cx,
                        ),
                    }
                    cx.notify();
                })
            }
        });

        // When any mouse up, stop dragging
        window.on_mouse_event({
            let state = self.state.clone();
            let on_resize = self.on_resize.clone();
            move |_: &MouseUpEvent, phase, window, cx| {
                if state.read(cx).resizing_panel_ix.is_none() {
                    return;
                }
                if phase.bubble() {
                    state.update(cx, |state, cx| state.done_resizing(cx));
                    on_resize(&state, window, cx);
                }
            }
        })
    }
}
