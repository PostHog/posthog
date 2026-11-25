use std::{panic::Location, rc::Rc};

use crate::{InteractiveElementExt as _, StyledExt};

use super::{ScrollableMask, Scrollbar, ScrollbarAxis, ScrollbarHandle};
use gpui::{
    App, Div, Element, ElementId, InteractiveElement, IntoElement, Overflow, ParentElement,
    PointRefinement, RenderOnce, ScrollHandle, Stateful, StatefulInteractiveElement,
    StyleRefinement, Styled, Window, div, prelude::FluentBuilder,
};

/// A trait for elements that can be made scrollable with scrollbars.
///
/// The wrapped element is the scroll area itself, rather than being inserted as
/// a child of a new scroll area.
pub trait ScrollableElement: InteractiveElement + Styled + ParentElement + Element {
    /// Adds a scrollbar to the element.
    #[track_caller]
    fn scrollbar<H: ScrollbarHandle + Clone>(
        self,
        scroll_handle: &H,
        axis: impl Into<ScrollbarAxis>,
    ) -> Self {
        self.child(ScrollbarLayer {
            id: caller_id(),
            axis: axis.into(),
            scroll_handle: Rc::new(scroll_handle.clone()),
        })
    }

    /// Adds a vertical scrollbar to the element.
    #[track_caller]
    fn vertical_scrollbar<H: ScrollbarHandle + Clone>(self, scroll_handle: &H) -> Self {
        self.scrollbar(scroll_handle, ScrollbarAxis::Vertical)
    }

    /// Adds a horizontal scrollbar to the element.
    #[track_caller]
    fn horizontal_scrollbar<H: ScrollbarHandle + Clone>(self, scroll_handle: &H) -> Self {
        self.scrollbar(scroll_handle, ScrollbarAxis::Horizontal)
    }

    /// Almost equivalent to [`StatefulInteractiveElement::overflow_scroll`], but adds scrollbars.
    /// Preserves the source element as the scrollable container.
    #[track_caller]
    fn overflow_scrollbar(self) -> Scrollable<Self> {
        Scrollable::new(self, ScrollbarAxis::Both)
    }

    /// Almost equivalent to [`StatefulInteractiveElement::overflow_x_scroll`], but adds Horizontal scrollbar.
    /// Preserves the source element as the scrollable container.
    #[track_caller]
    fn overflow_x_scrollbar(self) -> Scrollable<Self> {
        Scrollable::new(self, ScrollbarAxis::Horizontal)
    }

    /// Almost equivalent to [`StatefulInteractiveElement::overflow_y_scroll`], but adds Vertical scrollbar.
    /// Preserves the source element as the scrollable container.
    #[track_caller]
    fn overflow_y_scrollbar(self) -> Scrollable<Self> {
        Scrollable::new(self, ScrollbarAxis::Vertical)
    }
}

/// A scrollable element wrapper that renders the original element as the scroll area and overlays scrollbars.
#[derive(IntoElement)]
pub struct Scrollable<E: InteractiveElement + Styled + ParentElement + Element> {
    id: ElementId,
    element: E,
    axis: ScrollbarAxis,
    scroll_bounce: Option<bool>,
}

impl<E> Scrollable<E>
where
    E: InteractiveElement + Styled + ParentElement + Element,
{
    #[track_caller]
    fn new(element: E, axis: impl Into<ScrollbarAxis>) -> Self {
        Self {
            id: caller_id(),
            element,
            axis: axis.into(),
            scroll_bounce: None,
        }
    }

    /// Set a specific element id, default is the [`std::panic::Location::caller`].
    ///
    /// Only needed when one call site creates several scrollables, which would
    /// otherwise share a single scroll position.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }

    /// Bounce at the vertical boundaries. On by default on iOS, Android and
    /// macOS, off elsewhere; horizontal-only areas do not bounce.
    pub fn scroll_bounce(mut self, enabled: bool) -> Self {
        self.scroll_bounce = Some(enabled);
        self
    }
}

impl<E> Styled for Scrollable<E>
where
    E: InteractiveElement + Styled + ParentElement + Element,
{
    fn style(&mut self) -> &mut StyleRefinement {
        self.element.style()
    }
}

impl<E> ParentElement for Scrollable<E>
where
    E: InteractiveElement + Styled + ParentElement + Element,
{
    fn extend(&mut self, elements: impl IntoIterator<Item = gpui::AnyElement>) {
        self.element.extend(elements)
    }
}

impl<E> InteractiveElement for Scrollable<E>
where
    E: InteractiveElement + Styled + ParentElement + Element,
{
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.element.interactivity()
    }

    fn track_focus(mut self, focus: &gpui::FocusHandle) -> Self {
        self.element = self.element.track_focus(focus);
        self
    }
}

impl<E> RenderOnce for Scrollable<E>
where
    E: InteractiveElement + Styled + ParentElement + Element + 'static,
{
    fn render(mut self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let scroll_handle = scroll_handle_for(&self.id, window, cx);

        // Preserve the caller-requested size on the wrapper, while keeping the
        // caller's element as the actual scroll-tracked layout container.
        let root_style = root_style_from(&mut self.element, self.axis);

        let root_id = self.id.clone();
        let area_id = (self.id.clone(), "area");
        let content_id = (self.id.clone(), "content");
        let scrollbar_id = (self.id.clone(), "scrollbar");

        let mut content = self
            .element
            .id(content_id)
            .flex_none()
            .map(|this| match self.axis {
                ScrollbarAxis::Vertical => this.h_auto().min_h_full(),
                ScrollbarAxis::Horizontal => this.w_auto().min_w_full(),
                ScrollbarAxis::Both => this.size_auto().min_size_full(),
            });
        // The wrapper holds the caller's maximum size. Left on the content
        // too, it would cap the content at the area's size on the scrolled
        // axis, so nothing would overflow and the area would not scroll.
        let max_size = &mut content.style().max_size;
        match self.axis {
            ScrollbarAxis::Vertical => max_size.height = None,
            ScrollbarAxis::Horizontal => max_size.width = None,
            ScrollbarAxis::Both => *max_size = Default::default(),
        }

        // Keep the scroll area in the normal flow: its content size must
        // propagate to auto-sized ancestors (e.g. a Dialog that grows with
        // its content). An absolutely positioned scroll area would collapse
        // such ancestors to zero height.
        let scroll_area = div()
            .id(area_id)
            .size_full()
            .flex()
            .track_scroll(&scroll_handle)
            .map(|this| match self.axis {
                ScrollbarAxis::Vertical => this.flex_col().overflow_y_scroll(),
                ScrollbarAxis::Horizontal => this.flex_row().overflow_x_scroll(),
                ScrollbarAxis::Both => this.overflow_scroll(),
            })
            // On a single-axis area gpui otherwise remaps the other axis' delta
            // onto ours, so a purely horizontal swipe scrolls this vertically.
            .lock_scroll_axis()
            .child(content);

        // The wrapper lays the area out as a flex item along the scrolled
        // axis, so the area shrinks to the wrapper's size. Sized by its 100%
        // alone, the area is not held to a maximum size on the wrapper with
        // GPUI Fast: in a column whose height follows its content, inside a
        // row, the area came out as tall as that column and the wrapper
        // clipped the rows past its maximum height instead of scrolling to
        // them.
        div()
            .id(root_id)
            .size_full()
            .refine_style(&root_style)
            .relative()
            .flex()
            .map(|this| match self.axis {
                ScrollbarAxis::Horizontal => this.flex_row(),
                ScrollbarAxis::Vertical | ScrollbarAxis::Both => this.flex_col(),
            })
            .child(
                gpui_base::ScrollBounce::new(
                    (self.id.clone(), "bounce"),
                    &scroll_handle,
                    scroll_area,
                )
                .when_some(self.scroll_bounce, |bounce, on| bounce.enabled(on)),
            )
            // A plain mouse wheel has only a vertical axis, which the locked
            // horizontal area above would ignore.
            .when(self.axis == ScrollbarAxis::Horizontal, |this| {
                this.child(ScrollableMask::vertical_wheel(&scroll_handle))
            })
            .child(render_scrollbar(
                scrollbar_id,
                &scroll_handle,
                self.axis,
                window,
                cx,
            ))
    }
}

impl ScrollableElement for Div {}
impl<E> ScrollableElement for Stateful<E>
where
    E: ParentElement + Styled + Element,
    Self: InteractiveElement,
{
}

#[derive(IntoElement)]
struct ScrollbarLayer<H: ScrollbarHandle + Clone> {
    id: ElementId,
    axis: ScrollbarAxis,
    scroll_handle: Rc<H>,
}

impl<H> RenderOnce for ScrollbarLayer<H>
where
    H: ScrollbarHandle + Clone + 'static,
{
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        render_scrollbar(self.id, self.scroll_handle.as_ref(), self.axis, window, cx)
    }
}

#[inline]
#[track_caller]
fn caller_id() -> ElementId {
    ElementId::CodeLocation(*Location::caller())
}

#[inline]
fn scroll_handle_for(id: &ElementId, window: &mut Window, cx: &mut App) -> ScrollHandle {
    window
        .use_keyed_state(id.clone(), cx, |_, _| ScrollHandle::default())
        .read(cx)
        .clone()
}

/// Copies the outer layout styles from the element, so the wrapper can
/// participate in the parent's layout the same way the source element would.
///
/// A flex item only drops its content-based automatic minimum size when its own
/// overflow is not [`Overflow::Visible`]; otherwise the item refuses to shrink
/// around its content. The scrolled overflow lives on the inner scroll area, so
/// the wrapper has to declare the scrolled axis clipped itself — without it a
/// scroll region used as a flex item pushes its siblings out of the container
/// instead of scrolling, and every call site has to remember `min_h_0()` /
/// `min_w_0()`.
///
/// [`Overflow::Hidden`] rather than a zero minimum: it is the axis' real
/// behavior, it leaves an explicit `min_size` from the caller in charge, and it
/// keeps the region's content size contributing to an auto-sized ancestor such
/// as a Dialog that grows with its body. The mask it installs matches the inner
/// scroll area's own mask, so nothing new is clipped.
#[inline]
fn root_style_from<E>(element: &mut E, axis: ScrollbarAxis) -> StyleRefinement
where
    E: Styled,
{
    let style = element.style();
    StyleRefinement {
        size: style.size.clone(),
        min_size: style.min_size.clone(),
        max_size: style.max_size.clone(),
        flex_grow: style.flex_grow,
        flex_shrink: style.flex_shrink,
        flex_basis: style.flex_basis,
        align_self: style.align_self,
        overflow: PointRefinement {
            x: axis.has_horizontal().then_some(Overflow::Hidden),
            y: axis.has_vertical().then_some(Overflow::Hidden),
        },
        ..Default::default()
    }
}

#[inline]
fn render_scrollbar<H: ScrollbarHandle + Clone>(
    id: impl Into<ElementId>,
    scroll_handle: &H,
    axis: ScrollbarAxis,
    window: &mut Window,
    cx: &mut App,
) -> Div {
    // Do not render scrollbar when inspector is picking elements,
    // to allow us to pick the background elements.
    let is_inspector_picking = window.is_inspector_picking(cx);
    if is_inspector_picking {
        return div();
    }

    div()
        .absolute()
        .inset_0()
        .debug_selector(|| "scrollbar-overlay".to_string())
        .child(
            Scrollbar::new(scroll_handle)
                .id(id)
                .axis(axis)
                .viewport_from_layout(),
        )
}

#[cfg(feature = "test-support")]
impl<E> ScrollableElement for gpui_base::test_support::Observed<E> where
    E: ScrollableElement + Element<PrepaintState = Option<gpui::Hitbox>>
{
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{
        Context, Render, ScrollDelta, ScrollEvent, TestAppContext, VisualTestContext, point, px,
    };

    fn draw(cx: &mut VisualTestContext) {
        cx.run_until_parked();
        cx.update(|window, cx| {
            _ = window.draw(cx);
        });
    }

    fn scroll(cx: &mut VisualTestContext, x: f32, y: f32, dx: f32, dy: f32) {
        cx.simulate_event(ScrollEvent {
            position: point(px(x), px(y)),
            delta: ScrollDelta::Pixels(point(px(dx), px(dy))),
            ..Default::default()
        });
        draw(cx);
    }

    fn row(selector: &'static str, height: f32) -> Div {
        div()
            .h(px(height))
            .flex_shrink_0()
            .debug_selector(move || selector.to_string())
    }

    fn plain_row(height: f32) -> Div {
        div().h(px(height)).flex_shrink_0()
    }

    fn item(selector: &'static str, width: f32) -> Div {
        div()
            .w(px(width))
            .h(px(20.))
            .flex_shrink_0()
            .debug_selector(move || selector.to_string())
    }

    fn plain_item(width: f32) -> Div {
        div().w(px(width)).h(px(20.)).flex_shrink_0()
    }

    struct SizeFullChildTest;

    impl Render for SizeFullChildTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(100.))
                .h(px(100.))
                .overflow_y_scrollbar()
                .child(
                    div()
                        .size_full()
                        .child(crate::v_flex().children((0..4).map(|ix| {
                            div().h(px(50.)).flex_shrink_0().when(ix == 3, |this| {
                                this.debug_selector(|| "last-row".to_string())
                            })
                        }))),
                )
        }
    }

    struct AutoHeightParentTest;

    impl Render for AutoHeightParentTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Mimics Dialog: the panel height is auto (content-driven), the
            // body is flex_1 + overflow_hidden, and the scrollable content
            // should give the panel its intrinsic height.
            // GPUI window roots with auto dimensions stretch to the viewport,
            // so keep the auto-height panel below an explicit viewport root.
            div().size_full().child(
                crate::v_flex()
                    .w(px(200.))
                    .child(
                        crate::v_flex().flex_1().overflow_hidden().child(
                            div().flex_1().overflow_hidden().child(
                                crate::v_flex()
                                    .size_full()
                                    .overflow_y_scrollbar()
                                    .child(plain_row(50.))
                                    .child(plain_row(50.)),
                            ),
                        ),
                    )
                    .child(row("auto-height-footer", 10.)),
            )
        }
    }

    struct MaxHeightParentTest;

    impl Render for MaxHeightParentTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Mimics a Dialog with `max_h`: the panel grows with content up
            // to the max height, then the body starts scrolling.
            crate::v_flex()
                .w(px(200.))
                .max_h(px(100.))
                .child(
                    crate::v_flex().flex_1().overflow_hidden().child(
                        div().flex_1().overflow_hidden().child(
                            crate::v_flex()
                                .size_full()
                                .overflow_y_scrollbar()
                                .child(plain_row(50.))
                                .child(plain_row(50.))
                                .child(row("max-height-last-row", 50.)),
                        ),
                    ),
                )
                .child(row("max-height-footer", 10.))
        }
    }

    #[gpui::test]
    fn auto_height_parent_gets_content_height(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| AutoHeightParentTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        // The two 50px rows should push the footer down to y = 100.
        let footer = cx.debug_bounds("auto-height-footer").unwrap();
        assert_eq!(footer.top(), px(100.));
    }

    #[gpui::test]
    fn max_height_parent_clamps_and_scrolls(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| MaxHeightParentTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        // Content (150) + footer (10) exceeds max_h(100): the footer is
        // pinned at the bottom and the body gets the remaining 90px viewport.
        let footer = cx.debug_bounds("max-height-footer").unwrap();
        assert_eq!(footer.top(), px(90.));

        let last_initial_y = cx.debug_bounds("max-height-last-row").unwrap().origin.y;
        scroll(cx, 10., 10., 0., -50.);
        assert!(cx.debug_bounds("max-height-last-row").unwrap().origin.y < last_initial_y);
    }

    struct MaxHeightScrollableTest;

    impl Render for MaxHeightScrollableTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Six rows of 50px in an area that may grow to 100px, between two
            // blocks in a column as tall as its content, in a row. In such a
            // column the area's full height once came out as the column's,
            // 140px, rather than the 100px of the wrapper around it.
            crate::h_flex().w(px(100.)).child(
                crate::v_flex()
                    .w_full()
                    .child(plain_row(20.))
                    .child(
                        crate::v_flex()
                            .max_h(px(100.))
                            .overflow_y_scrollbar()
                            .child(row("max-size-first-row", 50.))
                            .children((0..4).map(|_| plain_row(50.)))
                            .child(row("max-size-last-row", 50.)),
                    )
                    .child(row("max-size-below", 20.)),
            )
        }
    }

    #[gpui::test]
    fn max_height_scrollable_scrolls_to_its_last_row(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| MaxHeightScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first_row = cx.debug_bounds("max-size-first-row").unwrap();
        let top = first_row.top();
        // The area stops at its maximum height.
        assert_eq!(
            cx.debug_bounds("max-size-below").unwrap().top() - top,
            px(100.)
        );

        let scroll_by = |cx: &mut VisualTestContext, dy: f32| {
            cx.simulate_event(ScrollEvent {
                position: first_row.center(),
                delta: ScrollDelta::Pixels(point(px(0.), px(dy))),
                ..Default::default()
            });
            draw(cx);
        };
        // The rows past it scroll into view, down to the last one, which
        // ends at the area's bottom edge.
        scroll_by(cx, -40.);
        assert_eq!(
            cx.debug_bounds("max-size-first-row").unwrap().top() - top,
            px(-40.)
        );
        scroll_by(cx, -1000.);
        assert_eq!(
            cx.debug_bounds("max-size-last-row").unwrap().bottom() - top,
            px(100.)
        );
    }

    struct MaxWidthScrollableTest;

    impl Render for MaxWidthScrollableTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Six items of 50px in an area that may grow to 100px wide.
            crate::h_flex().h(px(20.)).child(
                crate::h_flex()
                    .max_w(px(100.))
                    .overflow_x_scrollbar()
                    .child(item("max-size-first-item", 50.))
                    .children((0..5).map(|_| plain_item(50.))),
            )
        }
    }

    #[gpui::test]
    fn max_width_scrollable_scrolls_what_overflows_it(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| MaxWidthScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first_item = cx.debug_bounds("max-size-first-item").unwrap();
        cx.simulate_event(ScrollEvent {
            position: first_item.center(),
            delta: ScrollDelta::Pixels(point(px(-40.), px(0.))),
            ..Default::default()
        });
        draw(cx);
        assert_eq!(
            cx.debug_bounds("max-size-first-item").unwrap().left() - first_item.left(),
            px(-40.)
        );
    }

    struct FlexItemScrollableTest;

    impl Render for FlexItemScrollableTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // A fixed-height column of header, flexible scroll area, footer.
            // The content is far taller than the room left for the area, so
            // the area must shrink into the remaining 60px and scroll.
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .child(row("flex-item-header", 20.))
                .child(
                    crate::v_flex()
                        .flex_1()
                        .overflow_y_scrollbar()
                        .children((0..6).map(|ix| {
                            div().h(px(50.)).flex_shrink_0().when(ix == 0, |this| {
                                this.debug_selector(|| "flex-item-first-row".to_string())
                            })
                        })),
                )
                .child(row("flex-item-footer", 20.))
        }
    }

    #[gpui::test]
    fn scrollable_flex_item_shrinks_below_its_content(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| FlexItemScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        // Header and footer stay inside the 100px column, so the area took
        // the 60px left over instead of its content height.
        assert_eq!(cx.debug_bounds("flex-item-header").unwrap().top(), px(0.));
        assert_eq!(cx.debug_bounds("flex-item-footer").unwrap().top(), px(80.));

        // And the shrunken area really scrolls.
        let initial_y = cx.debug_bounds("flex-item-first-row").unwrap().origin.y;
        scroll(cx, 10., 50., 0., -50.);
        assert!(cx.debug_bounds("flex-item-first-row").unwrap().origin.y < initial_y);
    }

    struct HorizontalFlexItemScrollableTest;

    impl Render for HorizontalFlexItemScrollableTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::h_flex()
                .w(px(100.))
                .h(px(40.))
                .child(item("horizontal-flex-item-leading", 20.))
                .child(
                    crate::h_flex()
                        .flex_1()
                        .overflow_x_scrollbar()
                        .children((0..6).map(|ix| {
                            div()
                                .w(px(50.))
                                .h(px(20.))
                                .flex_shrink_0()
                                .when(ix == 0, |this| {
                                    this.debug_selector(|| {
                                        "horizontal-flex-item-first-item".to_string()
                                    })
                                })
                        })),
                )
                .child(item("horizontal-flex-item-trailing", 20.))
        }
    }

    #[gpui::test]
    fn horizontal_scrollable_flex_item_shrinks_below_its_content(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| HorizontalFlexItemScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        assert_eq!(
            cx.debug_bounds("horizontal-flex-item-leading")
                .unwrap()
                .left(),
            px(0.)
        );
        assert_eq!(
            cx.debug_bounds("horizontal-flex-item-trailing")
                .unwrap()
                .left(),
            px(80.)
        );

        let initial_x = cx
            .debug_bounds("horizontal-flex-item-first-item")
            .unwrap()
            .origin
            .x;
        scroll(cx, 50., 10., -50., 0.);
        assert!(
            cx.debug_bounds("horizontal-flex-item-first-item")
                .unwrap()
                .origin
                .x
                < initial_x
        );
    }

    #[gpui::test]
    fn horizontal_scrollable_scrolls_with_a_vertical_mouse_wheel(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| HorizontalFlexItemScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first_item_x = |cx: &mut VisualTestContext| {
            cx.debug_bounds("horizontal-flex-item-first-item")
                .unwrap()
                .origin
                .x
        };
        let initial_x = first_item_x(cx);
        cx.simulate_event(ScrollEvent {
            position: point(px(50.), px(10.)),
            delta: ScrollDelta::Lines(point(0., -1.)),
            ..Default::default()
        });
        draw(cx);
        assert!(first_item_x(cx) < initial_x);
    }

    struct ExplicitMinHeightScrollableTest;

    impl Render for ExplicitMinHeightScrollableTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // An explicit `min_h` is the caller's decision and must survive.
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .child(row("explicit-min-header", 20.))
                .child(
                    crate::v_flex()
                        .flex_1()
                        .min_h(px(70.))
                        .overflow_y_scrollbar()
                        .children((0..6).map(|_| plain_row(50.))),
                )
                .child(row("explicit-min-footer", 20.))
        }
    }

    #[gpui::test]
    fn explicit_min_size_survives_the_scrollable_wrapper(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| ExplicitMinHeightScrollableTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        // The area cannot shrink past the requested 70px, so the footer is
        // pushed to 20 + 70 instead of being clamped into the column.
        assert_eq!(
            cx.debug_bounds("explicit-min-header").unwrap().top(),
            px(0.)
        );
        assert_eq!(
            cx.debug_bounds("explicit-min-footer").unwrap().top(),
            px(90.)
        );
    }

    struct GapLayoutTest;

    struct PaddedScrollbarOverlayTest;

    impl Render for PaddedScrollbarOverlayTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .p(px(20.))
                .overflow_y_scrollbar()
                .children((0..4).map(|_| plain_row(50.)))
        }
    }

    #[gpui::test]
    fn scrollbar_overlay_ignores_content_padding(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| PaddedScrollbarOverlayTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let overlay = cx.debug_bounds("scrollbar-overlay").unwrap();
        assert_eq!(overlay.origin, point(px(0.), px(0.)));
        assert_eq!(overlay.size, gpui::size(px(100.), px(100.)));
    }

    impl Render for GapLayoutTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .gap(px(10.))
                .overflow_y_scrollbar()
                .child(row("first-row", 20.))
                .child(row("second-row", 20.))
        }
    }

    struct IssueGapRegressionTest;

    impl Render for IssueGapRegressionTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().w(px(100.)).h(px(100.)).child(
                crate::v_flex()
                    .flex_1()
                    .gap(px(30.))
                    .overflow_y_scrollbar()
                    .px(px(12.))
                    .pb(px(16.))
                    .children((0..5).map(|ix| {
                        div()
                            .h(px(20.))
                            .flex_shrink_0()
                            .when(ix == 0, |this| {
                                this.debug_selector(|| "issue-first-card".to_string())
                            })
                            .when(ix == 1, |this| {
                                this.debug_selector(|| "issue-second-card".to_string())
                            })
                            .when(ix == 4, |this| {
                                this.debug_selector(|| "issue-last-card".to_string())
                            })
                    })),
            )
        }
    }

    struct HorizontalGapLayoutTest;

    impl Render for HorizontalGapLayoutTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::h_flex()
                .w(px(100.))
                .h(px(40.))
                .gap(px(10.))
                .overflow_x_scrollbar()
                .child(item("horizontal-first-item", 50.))
                .child(item("horizontal-second-item", 50.))
                .child(item("horizontal-last-item", 50.))
        }
    }

    struct OverflowScrollbarVerticalTest;

    impl Render for OverflowScrollbarVerticalTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .gap(px(10.))
                .overflow_scrollbar()
                .child(row("both-axis-vertical-first-row", 50.))
                .child(row("both-axis-vertical-second-row", 50.))
                .child(row("both-axis-vertical-last-row", 50.))
        }
    }

    struct OverflowScrollbarHorizontalTest;

    impl Render for OverflowScrollbarHorizontalTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::h_flex()
                .w(px(100.))
                .h(px(40.))
                .gap(px(10.))
                .overflow_scrollbar()
                .child(item("both-axis-horizontal-first-item", 50.))
                .child(item("both-axis-horizontal-second-item", 50.))
                .child(item("both-axis-horizontal-last-item", 50.))
        }
    }

    struct IndependentScrollablesTest;

    impl Render for IndependentScrollablesTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::h_flex()
                .w(px(220.))
                .h(px(100.))
                .gap(px(20.))
                .child(
                    div().w(px(100.)).h(px(100.)).overflow_y_scrollbar().child(
                        crate::v_flex()
                            .child(plain_row(50.))
                            .child(plain_row(50.))
                            .child(row("left-scrollable-last-row", 50.)),
                    ),
                )
                .child(
                    div().w(px(100.)).h(px(100.)).overflow_y_scrollbar().child(
                        crate::v_flex()
                            .child(plain_row(50.))
                            .child(plain_row(50.))
                            .child(row("right-scrollable-last-row", 50.)),
                    ),
                )
        }
    }

    struct NoOverflowTest;

    impl Render for NoOverflowTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::v_flex()
                .w(px(100.))
                .h(px(100.))
                .gap(px(10.))
                .overflow_y_scrollbar()
                .child(row("no-overflow-first-row", 20.))
                .child(row("no-overflow-second-row", 20.))
        }
    }

    #[gpui::test]
    fn vertical_scrollbar_scrolls_past_a_size_full_child(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| SizeFullChildTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let initial_y = cx.debug_bounds("last-row").unwrap().origin.y;
        scroll(cx, 10., 10., 0., -50.);

        assert!(cx.debug_bounds("last-row").unwrap().origin.y < initial_y);
    }

    #[gpui::test]
    fn vertical_scrollbar_preserves_source_gap(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| GapLayoutTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("first-row").unwrap();
        let second = cx.debug_bounds("second-row").unwrap();
        assert_eq!(second.top() - first.bottom(), px(10.));
    }

    #[gpui::test]
    fn overflow_y_scrollbar_preserves_gap_for_exact_issue_chain(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| IssueGapRegressionTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("issue-first-card").unwrap();
        let second = cx.debug_bounds("issue-second-card").unwrap();
        let last_initial_y = cx.debug_bounds("issue-last-card").unwrap().origin.y;

        assert_eq!(second.top() - first.bottom(), px(30.));
        assert_eq!(first.left(), px(12.));

        scroll(cx, 10., 10., 0., -50.);

        let first_after_scroll = cx.debug_bounds("issue-first-card").unwrap();
        let second_after_scroll = cx.debug_bounds("issue-second-card").unwrap();
        let last_after_scroll_y = cx.debug_bounds("issue-last-card").unwrap().origin.y;

        assert_eq!(
            second_after_scroll.top() - first_after_scroll.bottom(),
            px(30.)
        );
        assert_eq!(first_after_scroll.left(), px(12.));
        assert!(last_after_scroll_y < last_initial_y);
    }

    #[gpui::test]
    fn horizontal_scrollbar_preserves_source_gap_and_scrolls(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| HorizontalGapLayoutTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("horizontal-first-item").unwrap();
        let second = cx.debug_bounds("horizontal-second-item").unwrap();
        let last_initial_x = cx.debug_bounds("horizontal-last-item").unwrap().origin.x;

        assert_eq!(second.left() - first.right(), px(10.));

        scroll(cx, 10., 10., -50., 0.);

        let first_after_scroll = cx.debug_bounds("horizontal-first-item").unwrap();
        let second_after_scroll = cx.debug_bounds("horizontal-second-item").unwrap();
        let last_after_scroll_x = cx.debug_bounds("horizontal-last-item").unwrap().origin.x;

        assert_eq!(
            second_after_scroll.left() - first_after_scroll.right(),
            px(10.)
        );
        assert!(last_after_scroll_x < last_initial_x);
    }

    #[gpui::test]
    fn overflow_scrollbar_preserves_vertical_source_gap(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| OverflowScrollbarVerticalTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("both-axis-vertical-first-row").unwrap();
        let second = cx.debug_bounds("both-axis-vertical-second-row").unwrap();

        assert_eq!(second.top() - first.bottom(), px(10.));
    }

    #[gpui::test]
    fn overflow_scrollbar_preserves_gap_and_scrolls_horizontally(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| OverflowScrollbarHorizontalTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("both-axis-horizontal-first-item").unwrap();
        let second = cx.debug_bounds("both-axis-horizontal-second-item").unwrap();
        let last_initial_x = cx
            .debug_bounds("both-axis-horizontal-last-item")
            .unwrap()
            .origin
            .x;

        assert_eq!(second.left() - first.right(), px(10.));

        scroll(cx, 10., 10., -50., 0.);

        let first_after_scroll = cx.debug_bounds("both-axis-horizontal-first-item").unwrap();
        let second_after_scroll = cx.debug_bounds("both-axis-horizontal-second-item").unwrap();
        let last_after_scroll_x = cx
            .debug_bounds("both-axis-horizontal-last-item")
            .unwrap()
            .origin
            .x;

        assert_eq!(
            second_after_scroll.left() - first_after_scroll.right(),
            px(10.)
        );
        assert!(last_after_scroll_x < last_initial_x);
    }

    #[gpui::test]
    fn multiple_scrollables_keep_independent_scroll_state(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| IndependentScrollablesTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let left_initial = cx.debug_bounds("left-scrollable-last-row").unwrap();
        let right_initial = cx.debug_bounds("right-scrollable-last-row").unwrap();

        scroll(cx, 10., 10., 0., -50.);

        let left_after_scroll = cx.debug_bounds("left-scrollable-last-row").unwrap();
        let right_after_scroll = cx.debug_bounds("right-scrollable-last-row").unwrap();

        assert!(left_after_scroll.top() < left_initial.top());
        assert_eq!(right_after_scroll.top(), right_initial.top());
    }

    #[gpui::test]
    fn vertical_scrollbar_does_not_scroll_when_content_does_not_overflow(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| NoOverflowTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("no-overflow-first-row").unwrap();
        let second = cx.debug_bounds("no-overflow-second-row").unwrap();

        assert_eq!(second.top() - first.bottom(), px(10.));

        scroll(cx, 10., 10., 0., -50.);

        let first_after_scroll = cx.debug_bounds("no-overflow-first-row").unwrap();
        let second_after_scroll = cx.debug_bounds("no-overflow-second-row").unwrap();

        assert_eq!(first_after_scroll.top(), first.top());
        assert_eq!(second_after_scroll.top(), second.top());
        assert_eq!(
            second_after_scroll.top() - first_after_scroll.bottom(),
            px(10.)
        );
    }

    #[gpui::test]
    fn horizontal_scrollbar_does_not_scroll_when_content_does_not_overflow(
        cx: &mut TestAppContext,
    ) {
        struct HorizontalNoOverflowTest;

        impl Render for HorizontalNoOverflowTest {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                crate::h_flex()
                    .w(px(100.))
                    .h(px(40.))
                    .gap(px(10.))
                    .overflow_x_scrollbar()
                    .child(item("no-overflow-first-item", 20.))
                    .child(item("no-overflow-second-item", 20.))
                    .child(plain_item(20.))
            }
        }

        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| HorizontalNoOverflowTest);
        let cx: &mut VisualTestContext = cx;
        draw(cx);

        let first = cx.debug_bounds("no-overflow-first-item").unwrap();
        let second = cx.debug_bounds("no-overflow-second-item").unwrap();

        assert_eq!(second.left() - first.right(), px(10.));

        scroll(cx, 10., 10., -50., 0.);

        let first_after_scroll = cx.debug_bounds("no-overflow-first-item").unwrap();
        let second_after_scroll = cx.debug_bounds("no-overflow-second-item").unwrap();

        assert_eq!(first_after_scroll.left(), first.left());
        assert_eq!(second_after_scroll.left(), second.left());
        assert_eq!(
            second_after_scroll.left() - first_after_scroll.right(),
            px(10.)
        );
    }
    struct IndependentDynamicScrollablesTest;

    impl Render for IndependentDynamicScrollablesTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::v_flex().w(px(100.)).children((0..2).map(|ix| {
                crate::h_flex()
                    .w(px(100.))
                    .h(px(40.))
                    .overflow_x_scrollbar()
                    .id(format!("dynamic-scroll-{ix}"))
                    .child(
                        div()
                            .w(px(200.))
                            .h(px(20.))
                            .flex_shrink_0()
                            .when(ix == 0, |this| {
                                this.debug_selector(|| "dynamic-scroll-first".to_string())
                            })
                            .when(ix == 1, |this| {
                                this.debug_selector(|| "dynamic-scroll-second".to_string())
                            }),
                    )
            }))
        }
    }

    #[gpui::test]
    fn dynamic_scrollables_with_unique_scroll_ids_keep_independent_state(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let (_, cx) = cx.add_window_view(|_, _| IndependentDynamicScrollablesTest);
        let cx: &mut VisualTestContext = cx;

        draw(cx);

        let first_initial = cx.debug_bounds("dynamic-scroll-first").unwrap();

        let second_initial = cx.debug_bounds("dynamic-scroll-second").unwrap();

        // Scroll horizontally inside the first row.
        scroll(cx, 10., 10., -50., 0.);

        let first_after_scroll = cx.debug_bounds("dynamic-scroll-first").unwrap();

        let second_after_scroll = cx.debug_bounds("dynamic-scroll-second").unwrap();

        // First scrollable should move horizontally.
        assert!(first_after_scroll.left() < first_initial.left());

        // Second scrollable must keep its own independent scroll state.
        assert_eq!(second_after_scroll.left(), second_initial.left());
    }
}
