//! Virtual List for render a large number of differently sized rows/columns.
//!
//! > NOTE: This must ensure each column width or row height.
//!
//! Only visible range are rendered for performance reasons.
//!
//! Inspired by `gpui::uniform_list`.
//! https://github.com/zed-industries/zed/blob/0ae1603610ab6b265bdfbee7b8dbc23c5ab06edc/crates/gpui/src/elements/uniform_list.rs
//!
//! Unlike the `uniform_list`, the each item can have different size.
//!
//! This is useful for more complex layout, for example, a table with different row height.
use std::{
    cell::RefCell,
    ops::{Deref, Range},
    rc::Rc,
};

use gpui::{
    Along, AnyElement, App, AvailableSpace, Axis, Bounds, ContentMask, Context,
    DeferredScrollToItem, Div, Element, ElementId, Entity, GlobalElementId, Half, Hitbox,
    InteractiveElement, IntoElement, IsZero as _, ListSizingBehavior, Pixels, Point, Render,
    ScrollHandle, ScrollStrategy, Size, Stateful, StatefulInteractiveElement, StyleRefinement,
    Styled, Window, div, point, px, size,
};
use smallvec::SmallVec;

use crate::{AxisExt, InteractiveElementExt as _};

struct VirtualListScrollHandleState {
    axis: Axis,
    items_count: usize,
    /// Content bounds size (excluding padding and border) from the last frame.
    last_content_size: Option<Size<Pixels>>,
    pub deferred_scroll_to_item: Option<DeferredScrollToItem>,
}

/// A scroll handle for [`VirtualList`].
///
/// See also [`ScrollHandle`].
#[derive(Clone)]
pub struct VirtualListScrollHandle {
    state: Rc<RefCell<VirtualListScrollHandleState>>,
    base_handle: ScrollHandle,
}

impl From<ScrollHandle> for VirtualListScrollHandle {
    fn from(handle: ScrollHandle) -> Self {
        let mut this = VirtualListScrollHandle::new();
        this.base_handle = handle;
        this
    }
}

impl AsRef<ScrollHandle> for VirtualListScrollHandle {
    fn as_ref(&self) -> &ScrollHandle {
        &self.base_handle
    }
}

impl crate::ScrollbarHandle for VirtualListScrollHandle {
    fn viewport_bounds(&self) -> Bounds<Pixels> {
        self.base_handle.bounds()
    }

    fn offset(&self) -> Point<Pixels> {
        self.base_handle.offset()
    }

    fn set_offset(&self, offset: Point<Pixels>) {
        self.base_handle.set_offset(offset);
    }

    fn content_size(&self) -> Size<Pixels> {
        self.base_handle.content_size()
    }
}

impl Deref for VirtualListScrollHandle {
    type Target = ScrollHandle;

    fn deref(&self) -> &Self::Target {
        &self.base_handle
    }
}

impl VirtualListScrollHandle {
    /// Create a new VirtualListScrollHandle.
    pub fn new() -> Self {
        VirtualListScrollHandle {
            state: Rc::new(RefCell::new(VirtualListScrollHandleState {
                axis: Axis::Vertical,
                items_count: 0,
                last_content_size: None,
                deferred_scroll_to_item: None,
            })),
            base_handle: ScrollHandle::default(),
        }
    }

    /// Get the base scroll handle.
    pub fn base_handle(&self) -> &ScrollHandle {
        &self.base_handle
    }

    /// Scroll to the item at the given index.
    pub fn scroll_to_item(&self, ix: usize, strategy: ScrollStrategy) {
        self.scroll_to_item_with_offset(ix, strategy, 0);
    }

    /// Scroll to the item at the given index, with an additional offset items.
    fn scroll_to_item_with_offset(&self, ix: usize, strategy: ScrollStrategy, offset: usize) {
        let mut state = self.state.borrow_mut();
        state.deferred_scroll_to_item = Some(DeferredScrollToItem {
            item_index: ix,
            strategy,
            offset,
            scroll_strict: false,
        });
    }

    /// Scrolls to the bottom of the list.
    pub fn scroll_to_bottom(&self) {
        let items_count = self.state.borrow().items_count;
        self.scroll_to_item(items_count.saturating_sub(1), ScrollStrategy::Top);
    }
}

/// Create a [`VirtualList`] in vertical direction.
///
/// This is like `uniform_list` in GPUI, but support two axis.
///
/// The `item_sizes` is the size of each row. Only the `height` is used; `width` is inferred
/// by measuring the item selected with [`VirtualList::with_item_to_measure_index`], defaulting
/// to the first item.
///
/// See also [`h_virtual_list`]
#[inline]
pub fn v_virtual_list<R, V>(
    view: Entity<V>,
    id: impl Into<ElementId>,
    item_sizes: Rc<Vec<Size<Pixels>>>,
    f: impl 'static + Fn(&mut V, Range<usize>, &mut Window, &mut Context<V>) -> Vec<R>,
) -> VirtualList
where
    R: IntoElement,
    V: Render,
{
    virtual_list(view, id, Axis::Vertical, item_sizes, f)
}

/// Create a [`VirtualList`] in horizontal direction.
///
/// The `item_sizes` is the size of each column. Only the `width` is used; `height` is inferred
/// by measuring the item selected with [`VirtualList::with_item_to_measure_index`], defaulting
/// to the first item.
///
/// See also [`v_virtual_list`]
#[inline]
pub fn h_virtual_list<R, V>(
    view: Entity<V>,
    id: impl Into<ElementId>,
    item_sizes: Rc<Vec<Size<Pixels>>>,
    f: impl 'static + Fn(&mut V, Range<usize>, &mut Window, &mut Context<V>) -> Vec<R>,
) -> VirtualList
where
    R: IntoElement,
    V: Render,
{
    virtual_list(view, id, Axis::Horizontal, item_sizes, f)
}

#[doc(hidden)]
pub fn virtual_list<R, V>(
    view: Entity<V>,
    id: impl Into<ElementId>,
    axis: Axis,
    item_sizes: Rc<Vec<Size<Pixels>>>,
    f: impl 'static + Fn(&mut V, Range<usize>, &mut Window, &mut Context<V>) -> Vec<R>,
) -> VirtualList
where
    R: IntoElement,
    V: Render,
{
    let id: ElementId = id.into();
    let scroll_handle = VirtualListScrollHandle::new();
    let render_range = move |visible_range, window: &mut Window, cx: &mut App| {
        view.update(cx, |this, cx| {
            f(this, visible_range, window, cx)
                .into_iter()
                .map(|component| component.into_any_element())
                .collect()
        })
    };

    VirtualList {
        id: id.clone(),
        axis,
        base: div()
            .id(id)
            .size_full()
            .overflow_scroll()
            .lock_scroll_axis()
            .track_scroll(&scroll_handle),
        scroll_handle,
        items_count: item_sizes.len(),
        item_sizes,
        render_items: Box::new(render_range),
        sizing_behavior: ListSizingBehavior::default(),
        item_to_measure_index: 0,
    }
}

/// VirtualList component for rendering a large number of differently sized items.
pub struct VirtualList {
    id: ElementId,
    axis: Axis,
    base: Stateful<Div>,
    scroll_handle: VirtualListScrollHandle,
    items_count: usize,
    item_sizes: Rc<Vec<Size<Pixels>>>,
    render_items: Box<
        dyn for<'a> Fn(Range<usize>, &'a mut Window, &'a mut App) -> SmallVec<[AnyElement; 64]>,
    >,
    sizing_behavior: ListSizingBehavior,
    item_to_measure_index: usize,
}

impl Styled for VirtualList {
    fn style(&mut self) -> &mut StyleRefinement {
        self.base.style()
    }
}

impl VirtualList {
    pub fn track_scroll(mut self, scroll_handle: &VirtualListScrollHandle) -> Self {
        self.base = self.base.track_scroll(&scroll_handle);
        self.scroll_handle = scroll_handle.clone();
        self
    }

    /// Set the sizing behavior for the list.
    pub fn with_sizing_behavior(mut self, behavior: ListSizingBehavior) -> Self {
        self.sizing_behavior = behavior;
        self
    }

    /// Set the item index used to infer the list's cross-axis size.
    pub fn with_item_to_measure_index(mut self, index: usize) -> Self {
        self.item_to_measure_index = index;
        self
    }

    /// Specify for table.
    ///
    /// Table is special, because the `scroll_handle` is based on Table head (That is not a virtual list).
    #[doc(hidden)]
    pub fn with_scroll_handle(mut self, scroll_handle: &VirtualListScrollHandle) -> Self {
        self.base = div().id(self.id.clone()).size_full();
        self.scroll_handle = scroll_handle.clone();
        self
    }

    fn scroll_to_deferred_item(
        &self,
        scroll_offset: Point<Pixels>,
        size_layout: &ItemSizeLayout,
        content_bounds: &Bounds<Pixels>,
        scroll_to_item: DeferredScrollToItem,
    ) -> Point<Pixels> {
        let Some(bounds) = size_layout.item_bounds(
            scroll_to_item.item_index + scroll_to_item.offset,
            self.axis,
            content_bounds,
        ) else {
            return scroll_offset;
        };

        let mut scroll_offset = scroll_offset;
        match scroll_to_item.strategy {
            ScrollStrategy::Center => {
                if self.axis.is_vertical() {
                    scroll_offset.y = content_bounds.top() + content_bounds.size.height.half()
                        - bounds.top()
                        - bounds.size.height.half()
                } else {
                    scroll_offset.x = content_bounds.left() + content_bounds.size.width.half()
                        - bounds.left()
                        - bounds.size.width.half()
                }
            }
            _ => {
                // Ref: https://github.com/zed-industries/zed/blob/0d145289e0867a8d5d63e5e1397a5ca69c9d49c3/crates/gpui/src/elements/div.rs#L3026
                if self.axis.is_vertical() {
                    if bounds.top() + scroll_offset.y < content_bounds.top() {
                        scroll_offset.y = content_bounds.top() - bounds.top()
                    } else if bounds.bottom() + scroll_offset.y > content_bounds.bottom() {
                        scroll_offset.y = content_bounds.bottom() - bounds.bottom();
                    }
                } else {
                    if bounds.left() + scroll_offset.x < content_bounds.left() {
                        scroll_offset.x = content_bounds.left() - bounds.left();
                    } else if bounds.right() + scroll_offset.x > content_bounds.right() {
                        scroll_offset.x = content_bounds.right() - bounds.right();
                    }
                }
            }
        }
        self.scroll_handle.set_offset(scroll_offset);
        scroll_offset
    }

    /// Ref from: https://github.com/zed-industries/zed/blob/83f9f9d9e3f5914392cab9a09e3472711a1d7b38/crates/gpui/src/elements/uniform_list.rs#L660
    fn measure_item(
        &self,
        list_width: Option<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> Size<Pixels> {
        if self.items_count == 0 {
            return Size::default();
        }

        let item_ix = self.item_to_measure_index.min(self.items_count - 1);
        let mut items = (self.render_items)(item_ix..item_ix + 1, window, cx);
        let Some(mut item_to_measure) = items.pop() else {
            return Size::default();
        };
        let available_space = size(
            list_width.map_or(AvailableSpace::MinContent, |width| {
                AvailableSpace::Definite(width)
            }),
            AvailableSpace::MinContent,
        );
        item_to_measure.layout_as_root(available_space, window, cx)
    }
}

/// Frame state used by the [VirtualItem].
pub struct VirtualListFrameState {
    /// Visible items to be painted.
    items: SmallVec<[AnyElement; 32]>,
    size_layout: ItemSizeLayout,
}

/// Per-item sizes along the list axis, gap included, and their prefix sums.
///
/// Shared between the element state and the frame state so that carrying
/// them across a frame is a reference count, not a copy of every item.
#[derive(Default, Clone)]
pub struct ItemSizeLayout {
    items_sizes: Rc<Vec<Size<Pixels>>>,
    axis_and_gap: Option<(Axis, Pixels)>,
    content_size: Size<Pixels>,
    sizes: Rc<[Pixels]>,
    origins: Rc<[Pixels]>,
    last_layout_bounds: Bounds<Pixels>,
}

impl ItemSizeLayout {
    /// The bounds of item `ix` in the list's content space: offset from the
    /// content origin along the list axis, filling it on the other.
    fn item_bounds(
        &self,
        ix: usize,
        axis: Axis,
        content_bounds: &Bounds<Pixels>,
    ) -> Option<Bounds<Pixels>> {
        let origin = *self.origins.get(ix)?;
        let item_size = self.sizes[ix];
        Some(match axis {
            Axis::Horizontal => Bounds {
                origin: point(content_bounds.left() + origin, px(0.)),
                size: size(item_size, content_bounds.size.height),
            },
            Axis::Vertical => Bounds {
                origin: point(px(0.), content_bounds.top() + origin),
                size: size(content_bounds.size.width, item_size),
            },
        })
    }
}

/// The items that intersect `viewport` along the list axis, plus one item of
/// overdraw past its end, given each item's origin and size (gap included).
///
/// Both edges are binary searches.
fn visible_range(origins: &[Pixels], sizes: &[Pixels], viewport: Range<Pixels>) -> Range<usize> {
    let count = origins.len();
    // Item ends grow with the index, so the first item ending past `edge` is
    // a partition point over the indices.
    let ends_before = |edge: Pixels| {
        let mut low = 0;
        let mut high = count;
        while low < high {
            let mid = low + (high - low) / 2;
            if origins[mid] + sizes[mid] <= edge {
                low = mid + 1;
            } else {
                high = mid;
            }
        }
        low
    };
    let first = ends_before(viewport.start);
    let past_end = ends_before(viewport.end);
    let last = if past_end == count {
        count
    } else {
        (past_end + 2).min(count)
    };
    first..last.max(first)
}

impl IntoElement for VirtualList {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for VirtualList {
    type RequestLayoutState = VirtualListFrameState;
    type PrepaintState = Option<Hitbox>;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        let rem_size = window.rem_size();
        let font_size = window.text_style().font_size.to_pixels(rem_size);
        let mut size_layout = ItemSizeLayout::default();
        // Measure vertical lists at the last known content width so relative
        // widths and text truncation resolve like the visible rows; an
        // unconstrained measure would turn one long non-wrapping text into a
        // phantom horizontal scroll range.
        let list_width = if self.axis.is_vertical() {
            self.scroll_handle
                .state
                .borrow()
                .last_content_size
                .map(|size| size.width)
                .filter(|width| !width.is_zero())
        } else {
            None
        };
        let longest_item_size = self.measure_item(list_width, window, cx);

        let layout_id = self.base.interactivity().request_layout(
            global_id,
            inspector_id,
            window,
            cx,
            |style, window, cx| {
                size_layout = window.with_element_state(
                    global_id.unwrap(),
                    |state: Option<ItemSizeLayout>, _window| {
                        let mut state = state.unwrap_or(ItemSizeLayout::default());

                        // Including the gap between items for calculate the item size
                        let gap = style
                            .gap
                            .along(self.axis)
                            .to_pixels(font_size.into(), rem_size);

                        if state.items_sizes != self.item_sizes
                            || state.axis_and_gap != Some((self.axis, gap))
                        {
                            state.items_sizes = self.item_sizes.clone();
                            state.axis_and_gap = Some((self.axis, gap));
                            // Prepare each item's size by axis
                            state.sizes = self
                                .item_sizes
                                .iter()
                                .enumerate()
                                .map(|(i, size)| {
                                    let size = size.along(self.axis);
                                    if i + 1 == self.items_count {
                                        size
                                    } else {
                                        size + gap
                                    }
                                })
                                .collect();

                            // Prepare each item's origin by axis
                            let mut cumulative = px(0.);
                            state.origins = state
                                .sizes
                                .iter()
                                .map(|size| {
                                    let origin = cumulative;
                                    cumulative += *size;
                                    origin
                                })
                                .collect();

                            if self.axis.is_horizontal() {
                                state.content_size.width = cumulative;
                            } else {
                                state.content_size.height = cumulative;
                            }
                        }

                        if self.axis.is_horizontal() {
                            state.content_size.height = longest_item_size.height;
                        } else {
                            state.content_size.width = longest_item_size.width;
                        }

                        (state.clone(), state)
                    },
                );

                let axis = self.axis;
                let layout_id =
                    match self.sizing_behavior {
                        ListSizingBehavior::Infer => {
                            window.with_text_style(style.text_style().cloned(), |window| {
                                let size_layout = size_layout.clone();

                                window.request_measured_layout(style, {
                                    move |known_dimensions, available_space, _, _| {
                                        let mut size = Size::default();
                                        if axis.is_horizontal() {
                                            size.width = known_dimensions.width.unwrap_or(
                                                match available_space.width {
                                                    AvailableSpace::Definite(x) => x,
                                                    AvailableSpace::MinContent
                                                    | AvailableSpace::MaxContent => {
                                                        size_layout.content_size.width
                                                    }
                                                },
                                            );
                                            size.height = known_dimensions.height.unwrap_or(
                                                match available_space.height {
                                                    AvailableSpace::Definite(x) => x,
                                                    AvailableSpace::MinContent
                                                    | AvailableSpace::MaxContent => {
                                                        size_layout.content_size.height
                                                    }
                                                },
                                            );
                                        } else {
                                            size.width = known_dimensions.width.unwrap_or(
                                                match available_space.width {
                                                    AvailableSpace::Definite(x) => x,
                                                    AvailableSpace::MinContent
                                                    | AvailableSpace::MaxContent => {
                                                        size_layout.content_size.width
                                                    }
                                                },
                                            );
                                            size.height = known_dimensions.height.unwrap_or(
                                                match available_space.height {
                                                    AvailableSpace::Definite(x) => x,
                                                    AvailableSpace::MinContent
                                                    | AvailableSpace::MaxContent => {
                                                        size_layout.content_size.height
                                                    }
                                                },
                                            );
                                        }

                                        size
                                    }
                                })
                            })
                        }
                        ListSizingBehavior::Auto => window
                            .with_text_style(style.text_style().cloned(), |window| {
                                window.request_layout(style, None, cx)
                            }),
                    };

                layout_id
            },
        );

        (
            layout_id,
            VirtualListFrameState {
                items: SmallVec::new(),
                size_layout,
            },
        )
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&gpui::InspectorElementId>,
        bounds: Bounds<Pixels>,
        layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        layout.size_layout.last_layout_bounds = bounds;

        let style = self
            .base
            .interactivity()
            .compute_style(global_id, None, window, cx);
        let border_widths = style.border_widths.to_pixels(window.rem_size());
        let paddings = style
            .padding
            .to_pixels(bounds.size.into(), window.rem_size());

        let item_sizes = &layout.size_layout.sizes;
        let item_origins = &layout.size_layout.origins;

        let content_bounds = Bounds::from_corners(
            bounds.origin
                + point(
                    border_widths.left + paddings.left,
                    border_widths.top + paddings.top,
                ),
            bounds.bottom_right()
                - point(
                    border_widths.right + paddings.right,
                    border_widths.bottom + paddings.bottom,
                ),
        );

        let axis = self.axis;

        let mut scroll_state = self.scroll_handle.state.borrow_mut();
        scroll_state.axis = axis;
        scroll_state.items_count = self.items_count;
        scroll_state.last_content_size = Some(content_bounds.size);

        let mut scroll_offset = self.scroll_handle.offset();
        if let Some(scroll_to_item) = scroll_state.deferred_scroll_to_item.take() {
            scroll_offset = self.scroll_to_deferred_item(
                scroll_offset,
                &layout.size_layout,
                &content_bounds,
                scroll_to_item,
            );
        }

        scroll_offset = scroll_offset
            .max(&point(
                content_bounds.size.width - layout.size_layout.content_size.width,
                content_bounds.size.height - layout.size_layout.content_size.height,
            ))
            .min(&point(px(0.), px(0.)));
        if scroll_offset != self.scroll_handle.offset() {
            self.scroll_handle.set_offset(scroll_offset);
        }

        self.base.interactivity().prepaint(
            global_id,
            inspector_id,
            bounds,
            layout.size_layout.content_size,
            window,
            cx,
            |_style, _, hitbox, window, cx| {
                if self.items_count > 0 {
                    let min_scroll_offset = content_bounds.size.along(self.axis)
                        - layout.size_layout.content_size.along(self.axis);

                    let is_scrolled = !scroll_offset.along(self.axis).is_zero();
                    if is_scrolled {
                        match self.axis {
                            Axis::Horizontal if scroll_offset.x < min_scroll_offset => {
                                scroll_offset.x = min_scroll_offset;
                                self.scroll_handle.set_offset(scroll_offset);
                            }
                            Axis::Vertical if scroll_offset.y < min_scroll_offset => {
                                scroll_offset.y = min_scroll_offset;
                                self.scroll_handle.set_offset(scroll_offset);
                            }
                            _ => {}
                        }
                    }

                    // The viewport in content space: the scroll offset is
                    // negative, and the leading padding is admitted at the
                    // start so an item under it is still drawn.
                    let viewport = match self.axis {
                        Axis::Horizontal => {
                            -(scroll_offset.x + paddings.left)
                                ..-scroll_offset.x + content_bounds.size.width
                        }
                        Axis::Vertical => {
                            -(scroll_offset.y + paddings.top)
                                ..-scroll_offset.y + content_bounds.size.height
                        }
                    };
                    let visible_range = visible_range(item_origins, item_sizes, viewport);

                    let items = (self.render_items)(visible_range.clone(), window, cx);

                    let content_mask = ContentMask { bounds };
                    window.with_content_mask(Some(content_mask), |window| {
                        for (mut item, ix) in items.into_iter().zip(visible_range.clone()) {
                            let item_origin = match self.axis {
                                Axis::Horizontal => {
                                    content_bounds.origin
                                        + point(item_origins[ix] + scroll_offset.x, scroll_offset.y)
                                }
                                Axis::Vertical => {
                                    content_bounds.origin
                                        + point(scroll_offset.x, item_origins[ix] + scroll_offset.y)
                                }
                            };

                            let available_space = match self.axis {
                                Axis::Horizontal => size(
                                    AvailableSpace::Definite(item_sizes[ix]),
                                    AvailableSpace::Definite(content_bounds.size.height),
                                ),
                                Axis::Vertical => size(
                                    AvailableSpace::Definite(content_bounds.size.width),
                                    AvailableSpace::Definite(item_sizes[ix]),
                                ),
                            };

                            item.layout_as_root(available_space, window, cx);
                            item.prepaint_at(item_origin, window, cx);
                            layout.items.push(item);
                        }
                    });
                }

                hitbox
            },
        )
    }

    fn paint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        inspector_id: Option<&gpui::InspectorElementId>,
        bounds: Bounds<Pixels>,
        layout: &mut Self::RequestLayoutState,
        hitbox: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.base.interactivity().paint(
            global_id,
            inspector_id,
            bounds,
            hitbox.as_ref(),
            window,
            cx,
            |_, window, cx| {
                for item in &mut layout.items {
                    item.paint(window, cx);
                }
            },
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use gpui::{Context, ParentElement as _, TestAppContext, VisualTestContext};

    struct VirtualListHarness {
        axis: Axis,
        item_sizes: Rc<Vec<Size<Pixels>>>,
        scroll_handle: VirtualListScrollHandle,
        visible_ranges: Rc<RefCell<Vec<Range<usize>>>>,
    }

    impl Render for VirtualListHarness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let item_sizes = self.item_sizes.clone();
            let visible_ranges = self.visible_ranges.clone();
            virtual_list(
                cx.entity(),
                "virtual-list-test",
                self.axis,
                self.item_sizes.clone(),
                move |_, visible_range, _, _| {
                    visible_ranges.borrow_mut().push(visible_range.clone());
                    visible_range
                        .map(|ix| div().w(item_sizes[ix].width).h(item_sizes[ix].height))
                        .collect::<Vec<_>>()
                },
            )
            .track_scroll(&self.scroll_handle)
            .w(px(60.))
            .h(px(60.))
        }
    }

    fn exercise_axis(cx: &mut TestAppContext, axis: Axis) {
        let item_size = match axis {
            Axis::Horizontal => size(px(20.), px(10.)),
            Axis::Vertical => size(px(10.), px(20.)),
        };
        let item_sizes = Rc::new(vec![item_size; 20]);
        let scroll_handle = VirtualListScrollHandle::new();
        let visible_ranges = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let item_sizes = item_sizes.clone();
            let scroll_handle = scroll_handle.clone();
            let visible_ranges = visible_ranges.clone();
            move |_, _| VirtualListHarness {
                axis,
                item_sizes,
                scroll_handle,
                visible_ranges,
            }
        });

        cx.update(|window, cx| window.draw(cx).clear(cx));
        let initial_range = visible_ranges.borrow().last().cloned().unwrap();
        assert_eq!(initial_range.start, 0);
        assert!(initial_range.end < item_sizes.len());

        scroll_handle.scroll_to_item(12, ScrollStrategy::Top);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let scrolled_range = visible_ranges.borrow().last().cloned().unwrap();
        assert!(scrolled_range.contains(&12));
        match axis {
            Axis::Horizontal => assert!(scroll_handle.offset().x < px(0.)),
            Axis::Vertical => assert!(scroll_handle.offset().y < px(0.)),
        }
    }

    fn layout(sizes: &[f32]) -> (Vec<Pixels>, Vec<Pixels>) {
        let sizes: Vec<Pixels> = sizes.iter().map(|size| px(*size)).collect();
        let origins = sizes
            .iter()
            .scan(px(0.), |cumulative, size| {
                let origin = *cumulative;
                *cumulative += *size;
                Some(origin)
            })
            .collect();
        (origins, sizes)
    }

    #[test]
    fn visible_range_starts_at_the_first_item_crossing_the_viewport() {
        let (origins, sizes) = layout(&[20.; 10]);
        assert_eq!(visible_range(&origins, &sizes, px(0.)..px(60.)), 0..5);
        assert_eq!(visible_range(&origins, &sizes, px(50.)..px(110.)), 2..7);
    }

    #[test]
    fn visible_range_overdraws_one_item_past_the_viewport_but_not_past_the_end() {
        let (origins, sizes) = layout(&[20.; 10]);
        assert_eq!(visible_range(&origins, &sizes, px(150.)..px(210.)), 7..10);
        assert_eq!(visible_range(&origins, &sizes, px(0.)..px(500.)), 0..10);
    }

    #[test]
    fn visible_range_handles_uneven_sizes() {
        let (origins, sizes) = layout(&[10., 30., 5., 50.]);
        assert_eq!(visible_range(&origins, &sizes, px(12.)..px(44.)), 1..4);
        assert_eq!(visible_range(&origins, &sizes, px(45.)..px(50.)), 3..4);
    }

    #[test]
    fn visible_range_is_empty_without_items_or_past_the_content() {
        let (origins, sizes) = layout(&[]);
        assert_eq!(visible_range(&origins, &sizes, px(0.)..px(60.)), 0..0);
        let (origins, sizes) = layout(&[20.; 10]);
        assert!(visible_range(&origins, &sizes, px(300.)..px(360.)).is_empty());
    }

    #[gpui::test]
    fn vertical_visible_range_and_deferred_scroll_are_preserved(cx: &mut TestAppContext) {
        exercise_axis(cx, Axis::Vertical);
    }

    #[gpui::test]
    fn horizontal_visible_range_and_deferred_scroll_are_preserved(cx: &mut TestAppContext) {
        exercise_axis(cx, Axis::Horizontal);
    }

    /// Three 30 by 10 items, laid out along `axis` with `gap` between them.
    struct GeometryHarness {
        axis: Axis,
        gap: Pixels,
    }

    impl Render for GeometryHarness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            virtual_list(
                cx.entity(),
                "virtual-list-geometry",
                self.axis,
                Rc::new(vec![size(px(30.), px(10.)); 3]),
                |_, visible_range, _, _| {
                    visible_range
                        .map(|ix| {
                            div()
                                .w(px(30.))
                                .h(px(10.))
                                .debug_selector(move || format!("geometry-item-{ix}"))
                        })
                        .collect::<Vec<_>>()
                },
            )
            .gap(self.gap)
            .w(px(120.))
            .h(px(100.))
        }
    }

    /// Where the second item sits relative to the first.
    fn second_item_offset(cx: &mut VisualTestContext) -> Point<Pixels> {
        let first = cx.debug_bounds("geometry-item-0").unwrap().origin;
        let second = cx.debug_bounds("geometry-item-1").unwrap().origin;
        second - first
    }

    #[gpui::test]
    fn changing_the_gap_moves_the_items(cx: &mut TestAppContext) {
        let (view, cx) = cx.add_window_view(|_, _| GeometryHarness {
            axis: Axis::Vertical,
            gap: px(0.),
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(second_item_offset(cx), point(px(0.), px(10.)));

        cx.update(|window, cx| {
            view.update(cx, |harness, cx| {
                harness.gap = px(20.);
                cx.notify();
            });
            window.draw(cx).clear(cx);
        });
        assert_eq!(second_item_offset(cx), point(px(0.), px(30.)));
    }

    #[gpui::test]
    fn changing_the_axis_moves_the_items(cx: &mut TestAppContext) {
        let (view, cx) = cx.add_window_view(|_, _| GeometryHarness {
            axis: Axis::Vertical,
            gap: px(0.),
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(second_item_offset(cx), point(px(0.), px(10.)));

        cx.update(|window, cx| {
            view.update(cx, |harness, cx| {
                harness.axis = Axis::Horizontal;
                cx.notify();
            });
            window.draw(cx).clear(cx);
        });
        assert_eq!(second_item_offset(cx), point(px(30.), px(0.)));
    }

    #[gpui::test]
    fn a_horizontal_list_infers_its_height_from_its_items(cx: &mut TestAppContext) {
        struct InferHarness;

        impl Render for InferHarness {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                div()
                    .flex()
                    .flex_col()
                    .items_start()
                    .w(px(120.))
                    .child(
                        virtual_list(
                            cx.entity(),
                            "virtual-list-infer",
                            Axis::Horizontal,
                            Rc::new(vec![size(px(30.), px(10.)); 3]),
                            |_, visible_range, _, _| {
                                visible_range
                                    .map(|_| div().w(px(30.)).h(px(10.)))
                                    .collect::<Vec<_>>()
                            },
                        )
                        .with_sizing_behavior(ListSizingBehavior::Infer)
                        .w(px(120.))
                        .h_auto()
                        .flex_none(),
                    )
                    .child(div().size(px(1.)).debug_selector(|| "after-list".into()))
            }
        }

        let (_, cx) = cx.add_window_view(|_, _| InferHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        // The list is as tall as its items, not as wide as itself.
        assert_eq!(cx.debug_bounds("after-list").unwrap().top(), px(10.));
    }

    #[gpui::test]
    fn empty_list_draws_without_requesting_items(cx: &mut TestAppContext) {
        let visible_ranges = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let visible_ranges = visible_ranges.clone();
            move |_, _| VirtualListHarness {
                axis: Axis::Vertical,
                item_sizes: Rc::new(Vec::new()),
                scroll_handle: VirtualListScrollHandle::new(),
                visible_ranges,
            }
        });

        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(visible_ranges.borrow().is_empty());
    }
}
