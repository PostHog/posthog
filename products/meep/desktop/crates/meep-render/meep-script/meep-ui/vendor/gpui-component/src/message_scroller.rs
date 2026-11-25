use std::{ops::Range, time::Duration};

use gpui::{
    AnyElement, App, Context, ElementId, Entity, FollowMode, Hsla, InteractiveElement as _,
    IntoElement, ListAlignment, ListOffset, ListState, ParentElement as _, RenderOnce, Role,
    SharedString, StatefulInteractiveElement as _, StyleRefinement, Styled, Window, div,
    linear_color_stop, linear_gradient, list, prelude::FluentBuilder as _, px, rems,
};
use gpui_base::motion::{Transition, transition};

use crate::{ActiveTheme as _, Disableable as _, IconName, StyledExt as _, button::Button};
use crate::{button::ButtonVariants as _, scroll::ScrollableElement as _};

const LIST_OVERDRAW: gpui::Pixels = px(400.);
const JUMP_BUTTON_TRANSITION: Duration = Duration::from_millis(200);
const BOTTOM_FADE_TRANSITION: Duration = Duration::from_millis(200);

/// The entity-owned scrolling state for a [`MessageScroller`].
///
/// The state owns only GPUI's virtual-list bookkeeping. Message data remains
/// with the caller and is read by the row renderer passed to
/// [`MessageScroller::new`].
pub struct MessageScrollerState {
    list_state: ListState,
}

impl MessageScrollerState {
    /// Create a state for `item_count` rows and enable tail following.
    ///
    /// The constructor receives the entity context so the list's scroll
    /// handler can safely defer its entity update until GPUI has released the
    /// list's internal borrow.
    pub fn new(item_count: usize, cx: &mut Context<Self>) -> Self {
        let list_state = ListState::new(item_count, ListAlignment::Top, LIST_OVERDRAW);
        list_state.set_follow_mode(FollowMode::Tail);

        let weak_state = cx.weak_entity();
        list_state.set_scroll_handler(move |_, _, cx| {
            let weak_state = weak_state.clone();

            cx.defer(move |cx| {
                let _ = weak_state.update(cx, |_, cx| cx.notify());
            });
        });

        Self { list_state }
    }

    /// Return the current number of rows known by the virtual list.
    pub fn item_count(&self) -> usize {
        self.list_state.item_count()
    }

    /// Return whether the user has scrolled away from the latest content.
    pub fn is_scrolled_up(&self) -> bool {
        self.list_state.max_offset_for_scrollbar().y > px(0.)
            && !self.list_state.is_following_tail()
            && !self.list_state.is_scrolled_to_end().unwrap_or(false)
    }

    /// Return whether the list is actively following its tail.
    pub fn is_following_tail(&self) -> bool {
        self.list_state.is_following_tail()
    }

    /// Return the row at the top of the viewport and how far into it the list
    /// is scrolled.
    ///
    /// Wheel, trackpad, and scrollbar scrolls and [`Self::scroll_to_item`]
    /// update it at once. [`Self::scroll_to_end`] and tail following settle it
    /// when the list next lays out; right after `scroll_to_end`, `item_ix` is
    /// [`Self::item_count`] until then.
    pub fn logical_scroll_top(&self) -> ListOffset {
        self.list_state.logical_scroll_top()
    }

    /// Reset the list to `item_count` rows.
    pub fn reset(&mut self, item_count: usize, cx: &mut Context<Self>) {
        self.list_state.reset(item_count);
        self.list_state.set_follow_mode(FollowMode::Tail);
        cx.notify();
    }

    /// Replace `old_range` with `count` new rows.
    ///
    /// Returns `false` when the range is outside the current list and leaves
    /// the state unchanged.
    pub fn splice(
        &mut self,
        old_range: Range<usize>,
        count: usize,
        cx: &mut Context<Self>,
    ) -> bool {
        if !self.valid_range(&old_range) {
            return false;
        }

        let neighbor = old_range.start.checked_sub(1);
        let touches_start = old_range.start == 0;
        self.list_state.splice(old_range, count);

        // The default row wrapper pads every row except the last, so a row
        // whose "last" status may have flipped carries a stale measured
        // height. Remeasure the new last row and the survivor next to the
        // splice.
        if let Some(last) = self.list_state.item_count().checked_sub(1) {
            self.list_state.remeasure_items(last..last + 1);
            if let Some(neighbor) = neighbor.filter(|neighbor| *neighbor != last) {
                self.list_state.remeasure_items(neighbor..neighbor + 1);
            }
        }

        // A surviving former first row may have lost its list inset, or a
        // surviving row may have become the first after a removal.
        if touches_start {
            for index in [0, count] {
                if index < self.list_state.item_count() {
                    self.list_state.remeasure_items(index..index + 1);
                }
            }
        }

        cx.notify();
        true
    }

    /// Append `count` rows to the end of the list.
    pub fn append(&mut self, count: usize, cx: &mut Context<Self>) -> bool {
        let item_count = self.list_state.item_count();
        self.splice(item_count..item_count, count, cx)
    }

    /// Prepend `count` rows while preserving the current scroll anchor.
    pub fn prepend(&mut self, count: usize, cx: &mut Context<Self>) -> bool {
        self.splice(0..0, count, cx)
    }

    /// Mark all rows for remeasurement while preserving a proportional anchor.
    pub fn remeasure(&mut self, cx: &mut Context<Self>) {
        self.list_state.remeasure();
        cx.notify();
    }

    /// Mark rows in `range` for remeasurement while preserving an item anchor.
    ///
    /// Returns `false` when the range is outside the current list.
    pub fn remeasure_items(&mut self, range: Range<usize>, cx: &mut Context<Self>) -> bool {
        if !self.valid_range(&range) {
            return false;
        }

        self.list_state.remeasure_items(range);
        cx.notify();
        true
    }

    /// Scroll to the row at `index`, if it exists.
    pub fn scroll_to_item(&mut self, index: usize, cx: &mut Context<Self>) -> bool {
        if index >= self.list_state.item_count() {
            return false;
        }

        self.list_state.scroll_to(ListOffset {
            item_ix: index,
            offset_in_item: px(0.),
        });
        cx.notify();
        true
    }

    /// Resume tail following and scroll to the latest row.
    pub fn scroll_to_end(&mut self, cx: &mut Context<Self>) {
        self.list_state.set_follow_mode(FollowMode::Tail);
        self.list_state.scroll_to_end();
        cx.notify();
    }

    fn valid_range(&self, range: &Range<usize>) -> bool {
        range.start <= range.end && range.end <= self.list_state.item_count()
    }
}

/// A virtualized message list with optional scrollbar and jump-to-latest UI.
#[derive(IntoElement)]
pub struct MessageScroller {
    id: ElementId,
    state: Entity<MessageScrollerState>,
    renderer: Box<dyn FnMut(usize, &mut Window, &mut App) -> AnyElement + 'static>,
    style: StyleRefinement,
    content_style: StyleRefinement,
    list_style: StyleRefinement,
    row_style: StyleRefinement,
    jump_button_style: StyleRefinement,
    jump_button_renderer: Option<Box<dyn FnOnce(Button) -> Button>>,
    jump_button_transition: Duration,
    bottom_fade: Option<Hsla>,
    scrollbar: bool,
    jump_button: bool,
    jump_button_label: SharedString,
}

impl MessageScroller {
    /// Create a message scroller with a renderer for each row.
    pub fn new<E>(
        id: impl Into<ElementId>,
        state: Entity<MessageScrollerState>,
        renderer: impl FnMut(usize, &mut Window, &mut App) -> E + 'static,
    ) -> Self
    where
        E: IntoElement,
    {
        let mut renderer = renderer;
        Self {
            id: id.into(),
            state,
            renderer: Box::new(move |index, window, cx| {
                renderer(index, window, cx).into_any_element()
            }),
            style: StyleRefinement::default(),
            content_style: StyleRefinement::default(),
            list_style: StyleRefinement::default(),
            row_style: StyleRefinement::default(),
            jump_button_style: StyleRefinement::default(),
            jump_button_renderer: None,
            jump_button_transition: JUMP_BUTTON_TRANSITION,
            bottom_fade: None,
            scrollbar: true,
            jump_button: true,
            jump_button_label: "Jump to latest".into(),
        }
    }

    /// Enable or disable the virtual-list scrollbar.
    pub fn scrollbar(mut self, scrollbar: bool) -> Self {
        self.scrollbar = scrollbar;
        self
    }

    /// Enable or disable the built-in jump-to-latest button.
    pub fn jump_button(mut self, jump_button: bool) -> Self {
        self.jump_button = jump_button;
        self
    }

    /// Set the label used by the built-in jump-to-latest button.
    pub fn with_jump_button_label(mut self, label: impl Into<SharedString>) -> Self {
        self.jump_button_label = label.into();
        self
    }

    /// Refine the viewport that contains the list and scrollbar.
    pub fn with_content_style(mut self, style: StyleRefinement) -> Self {
        self.content_style = style;
        self
    }

    /// Refine the GPUI list element used to render rows.
    pub fn with_list_style(mut self, style: StyleRefinement) -> Self {
        self.list_style = style;
        self
    }

    /// Refine the full-width wrapper around every rendered row.
    pub fn with_row_style(mut self, style: StyleRefinement) -> Self {
        self.row_style = style;
        self
    }

    /// Refine the built-in jump-to-latest button after its defaults.
    pub fn with_jump_button_style(mut self, style: StyleRefinement) -> Self {
        self.jump_button_style = style;
        self
    }

    /// Customize the built-in jump button without replacing its scroll action.
    ///
    /// The callback receives the fully configured Button, so its variant,
    /// semantic size, icon, tooltip, or instance styling may be adjusted.
    pub fn with_jump_button_renderer(
        mut self,
        renderer: impl FnOnce(Button) -> Button + 'static,
    ) -> Self {
        self.jump_button_renderer = Some(Box::new(renderer));
        self
    }

    /// Set how long the built-in jump button takes to enter or leave.
    ///
    /// A zero duration disables its transition. Reduced-motion preferences
    /// always adopt the final state immediately.
    pub fn with_jump_button_transition(mut self, duration: Duration) -> Self {
        self.jump_button_transition = duration;
        self
    }

    /// Fade the transcript's bottom edge into `color`.
    ///
    /// A partially visible row melts into the surface behind the scroller
    /// instead of clipping mid-line. The fade shows only while the reader is
    /// away from the live edge — at the bottom nothing is clipped. Pass the
    /// color of that surface; the fade is off by default and sits under the
    /// jump button.
    pub fn with_bottom_fade(mut self, color: impl Into<Hsla>) -> Self {
        self.bottom_fade = Some(color.into());
        self
    }
}

impl Styled for MessageScroller {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageScroller {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let root_id = self.id.clone();
        let (list_state, scrolled_up) = {
            let state = self.state.read(cx);
            (state.list_state.clone(), state.is_scrolled_up())
        };
        let show_jump_button = self.jump_button && scrolled_up;
        let jump_button_visibility = if self.jump_button {
            transition(
                (root_id.clone(), "jump-button-visibility"),
                if show_jump_button { 1. } else { 0. },
                Transition::new(self.jump_button_transition),
                window,
                cx,
            )
        } else {
            0.
        };
        // At the live edge nothing is clipped below, so a visible fade would
        // suggest more content than there is.
        let bottom_fade_visibility = if self.bottom_fade.is_some() {
            transition(
                (root_id.clone(), "bottom-fade-visibility"),
                if scrolled_up { 1. } else { 0. },
                Transition::new(BOTTOM_FADE_TRANSITION),
                window,
                cx,
            )
        } else {
            0.
        };
        let tokens = cx.theme().semantic_tokens();
        let row_style = self.row_style;
        let jump_button_style = self.jump_button_style;
        let jump_button_renderer = self.jump_button_renderer;
        let mut renderer = self.renderer;

        // GPUI's `list` lays rows out at the full list width and offsets them
        // only by vertical padding, so the horizontal component of the list
        // style must be carried by every row wrapper instead.
        //
        // The vertical padding rides on the rows as well. A list measures its
        // scroll extent from its items alone, so a list that carries padding
        // of its own reports a scroll range that stops short of its end: the
        // scrollbar thumb can never reach the last row, the tail never
        // resumes, and the list never reports itself as scrolled to the end.
        // Padding on the rows is part of the content, so the extent covers
        // it.
        let mut list_style = self.list_style;
        let row_inset_left = list_style.padding.left.take();
        let row_inset_right = list_style.padding.right.take();
        let row_inset_top = list_style.padding.top.take();
        let row_inset_bottom = list_style.padding.bottom.take();

        // Read the count outside the row closure: the list holds a mutable
        // borrow of its state while rendering rows, so the closure must not
        // borrow it again. The count is stable within one render pass.
        let item_count = list_state.item_count();
        let list = list(list_state.clone(), move |index, window, cx| {
            div()
                .w_full()
                .when(index == 0, |this| match row_inset_top {
                    Some(top) => this.pt(top),
                    None => this.pt_2(),
                })
                .when(index + 1 == item_count, |this| match row_inset_bottom {
                    Some(bottom) => this.pb(bottom),
                    None => this.pb_2(),
                })
                .child(
                    div()
                        .w_full()
                        .min_w_0()
                        .px_3()
                        .when(index + 1 < item_count, |this| this.pb_8())
                        .when_some(row_inset_left, |this, left| this.pl(left))
                        .when_some(row_inset_right, |this, right| this.pr(right))
                        .refine_style(&row_style)
                        .child(renderer(index, window, cx)),
                )
                .into_any_element()
        })
        .size_full()
        .min_h_0()
        .refine_style(&list_style);

        let viewport = div()
            .id((root_id.clone(), "viewport"))
            // Announce appended rows as a log region, like shadcn's
            // `role="log"` transcript content.
            .role(Role::Log)
            .size_full()
            .min_h_0()
            .min_w_0()
            .child(
                // The bounce scrolls the list itself, past the list's own
                // scroll handler; tell the state, as that handler would.
                gpui_base::ScrollBounce::new((root_id.clone(), "bounce"), &list_state, list)
                    .on_scroll({
                        let state = self.state.downgrade();
                        move |_, cx| {
                            let _ = state.update(cx, |_, cx| cx.notify());
                        }
                    }),
            )
            // The fade sits above the rows but below the scrollbar and the
            // jump button, so neither control is washed out by it.
            .when_some(
                self.bottom_fade.filter(|_| bottom_fade_visibility > 0.),
                |this, color| {
                    this.child(
                        div()
                            .absolute()
                            .left_0()
                            .right_0()
                            .bottom_0()
                            .h(rems(3.))
                            .opacity(bottom_fade_visibility)
                            .bg(linear_gradient(
                                180.,
                                linear_color_stop(color.opacity(0.), 0.),
                                linear_color_stop(color, 1.),
                            )),
                    )
                },
            )
            .when(self.scrollbar, |this| this.vertical_scrollbar(&list_state))
            .refine_style(&self.content_style);

        div()
            .id(root_id.clone())
            .relative()
            .size_full()
            .min_h_0()
            .overflow_hidden()
            .child(viewport)
            .when(self.jump_button && jump_button_visibility > 0., |this| {
                let state = self.state.clone();

                this.child(
                    div()
                        .absolute()
                        .left_0()
                        .right_0()
                        .bottom(rems(0.5 + jump_button_visibility * 0.5))
                        .flex()
                        .justify_center()
                        .opacity(jump_button_visibility)
                        .child(
                            // No explicit width or height: Button sizes an
                            // icon-only button as a square on its own, and a
                            // renderer that adds a label or another semantic
                            // size must be able to change the layout.
                            Button::new((root_id, "jump-to-latest"))
                                .secondary()
                                .icon(IconName::ArrowDown)
                                .tooltip(self.jump_button_label)
                                .rounded(cx.theme().radius_full())
                                .border_1()
                                .border_color(tokens.colors.border)
                                .bg(tokens.colors.background)
                                .text_color(tokens.colors.foreground)
                                .refine_style(&jump_button_style)
                                .on_click(move |_, _, cx| {
                                    state.update(cx, |state, cx| state.scroll_to_end(cx));
                                })
                                .when_some(jump_button_renderer, |button, renderer| {
                                    renderer(button)
                                })
                                .when(!show_jump_button, |button| button.disabled(true)),
                        ),
                )
            })
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Sizable as _;
    use gpui::AppContext as _;

    #[gpui::test]
    fn test_message_scroller_state_builder(cx: &mut gpui::TestAppContext) {
        let state = cx.new(|cx| MessageScrollerState::new(3, cx));

        cx.update(|cx| {
            assert_eq!(state.read(cx).item_count(), 3);
            assert!(!state.read(cx).is_scrolled_up());
            assert!(state.read(cx).is_following_tail());

            state.update(cx, |state, cx| {
                assert!(!state.scroll_to_item(3, cx));
                assert!(state.append(2, cx));
                assert_eq!(state.item_count(), 5);
                assert!(state.prepend(1, cx));
                assert_eq!(state.item_count(), 6);
                assert!(!state.splice(5..7, 0, cx));
                assert!(state.remeasure_items(0..6, cx));
                assert!(!state.remeasure_items(6..7, cx));
                assert!(state.scroll_to_item(2, cx));
                assert!(!state.is_scrolled_up());
                assert!(!state.is_following_tail());
                state.scroll_to_end(cx);
                assert!(state.is_following_tail());
                state.reset(2, cx);
                assert_eq!(state.item_count(), 2);
                assert!(state.is_following_tail());
            });
        });
    }

    struct ScrollerHarness {
        state: Entity<MessageScrollerState>,
    }

    impl gpui::Render for ScrollerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size(px(400.)).child(
                MessageScroller::new("messages", self.state.clone(), |_, _, _| div().h(px(40.)))
                    .scrollbar(false)
                    .jump_button(false),
            )
        }
    }

    #[gpui::test]
    fn test_logical_scroll_top_reports_the_row_at_the_top(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let state = cx.new(|cx| MessageScrollerState::new(30, cx));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            move |_, _| ScrollerHarness { state }
        });
        let draw = |cx: &mut gpui::VisualTestContext| {
            cx.run_until_parked();
            cx.update(|window, cx| {
                _ = window.draw(cx);
            });
        };
        let top = |cx: &mut gpui::VisualTestContext| {
            cx.update(|_, cx| state.read(cx).logical_scroll_top())
        };
        draw(cx);

        // Following the tail, layout settles on the row the tail starts on.
        let tail = top(cx);
        assert!(
            tail.item_ix > 0 && tail.item_ix < 30,
            "the row at the top while following the tail: {tail:?}"
        );

        cx.update(|_, cx| state.update(cx, |state, cx| state.scroll_to_item(10, cx)));
        draw(cx);
        assert_eq!(top(cx).item_ix, 10);

        // A wheel scroll by one row: its 40px and the 32px gap after it.
        cx.simulate_event(gpui::ScrollEvent {
            position: gpui::point(px(200.), px(200.)),
            delta: gpui::ScrollDelta::Pixels(gpui::point(px(0.), px(-72.))),
            ..Default::default()
        });
        let after_wheel = top(cx);
        assert_eq!(
            (after_wheel.item_ix, after_wheel.offset_in_item),
            (11, px(0.))
        );
    }

    /// A scrollbar drag to the bottom of the track must reach the end of the
    /// content: the thumb's range is the list's scroll extent, and an extent
    /// that stops short of the end leaves the reader above the last row,
    /// with the tail-follow off and the jump button showing.
    #[gpui::test]
    fn the_scrollbar_drag_range_reaches_the_end_of_the_content(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let state = cx.new(|cx| MessageScrollerState::new(10, cx));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            move |_, _| ScrollerHarness { state }
        });
        let draw = |cx: &mut gpui::VisualTestContext| {
            cx.run_until_parked();
            cx.update(|window, cx| {
                _ = window.draw(cx);
            });
        };
        draw(cx);

        // Drag the thumb to the bottom of the track: the scrollbar maps that
        // to the largest offset it reports for the list.
        cx.update(|_, cx| {
            let list_state = state.read(cx).list_state.clone();
            list_state.scrollbar_drag_started();
            let max = list_state.max_offset_for_scrollbar().y;
            list_state.set_offset_from_scrollbar(gpui::point(px(0.), -max));
            list_state.scrollbar_drag_ended();
        });

        cx.update(|_, cx| {
            let list_state = state.read(cx).list_state.clone();
            assert_eq!(
                list_state.is_scrolled_to_end(),
                Some(true),
                "the drag must land on the end of the content"
            );
            assert!(
                list_state.is_following_tail(),
                "the drag to the end must resume the tail"
            );
            assert!(
                !state.read(cx).is_scrolled_up(),
                "the jump-to-latest button must hide at the end of the content"
            );
        });
    }

    struct PaddedScrollerHarness {
        state: Entity<MessageScrollerState>,
        list_style: StyleRefinement,
    }

    impl gpui::Render for PaddedScrollerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size(px(400.)).child(
                MessageScroller::new("messages", self.state.clone(), |_, _, _| div().h(px(40.)))
                    .scrollbar(false)
                    .jump_button(false)
                    .with_list_style(self.list_style.clone())
                    .with_row_style(StyleRefinement::default().pt(px(6.)).pb(px(6.))),
            )
        }
    }

    /// A custom list padding must ride on the first and the last row, the
    /// way the list's own padding does. Carried by every row it would give
    /// every message the list's padding instead of giving it to the list.
    #[gpui::test]
    fn a_custom_list_padding_rides_on_the_first_and_the_last_row(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);

        let first = cx.new(|cx| MessageScrollerState::new(10, cx));
        let second = cx.new(|cx| MessageScrollerState::new(10, cx));
        let third = cx.new(|cx| MessageScrollerState::new(10, cx));

        let extent = |cx: &mut gpui::TestAppContext,
                      state: Entity<MessageScrollerState>,
                      list_style: StyleRefinement| {
            let (_, context) = cx.add_window_view({
                let state = state.clone();
                move |_, _| PaddedScrollerHarness { state, list_style }
            });
            context.run_until_parked();
            context.update(|window, cx| {
                _ = window.draw(cx);
                state.read(cx).list_state.max_offset_for_scrollbar().y
            })
        };

        let first_extent = extent(
            cx,
            first,
            StyleRefinement::default().pt(px(20.)).pb(px(40.)),
        );
        let second_extent = extent(
            cx,
            second,
            StyleRefinement::default().pt(px(20.)).pb(px(20.)),
        );
        let third_extent = extent(
            cx,
            third,
            StyleRefinement::default().pt(px(40.)).pb(px(20.)),
        );

        // The bottom inset rides on the last row only, so the content grows
        // by the difference between the two bottom insets, not once per row.
        assert_eq!(
            first_extent - second_extent,
            px(20.),
            "the bottom inset must ride on the last row only"
        );
        // The top inset rides on the first row only.
        assert_eq!(
            third_extent - second_extent,
            px(20.),
            "the top inset must ride on the first row only"
        );
    }

    #[gpui::test]
    fn test_message_scroller_builder(cx: &mut gpui::TestAppContext) {
        let state = cx.new(|cx| MessageScrollerState::new(0, cx));
        let scroller = MessageScroller::new("message-scroller", state, |_, _, _| div())
            .scrollbar(false)
            .jump_button(false)
            .with_jump_button_label("Latest")
            .with_content_style(StyleRefinement::default())
            .with_list_style(StyleRefinement::default())
            .with_row_style(StyleRefinement::default())
            .with_jump_button_style(StyleRefinement::default())
            .with_jump_button_renderer(|button| button.large())
            .with_jump_button_transition(Duration::from_millis(300))
            .with_bottom_fade(gpui::white());

        assert!(!scroller.scrollbar);
        assert!(!scroller.jump_button);
        assert_eq!(scroller.jump_button_label, "Latest");
        assert!(scroller.jump_button_renderer.is_some());
        assert_eq!(scroller.jump_button_transition, Duration::from_millis(300));
        assert_eq!(scroller.bottom_fade, Some(gpui::white()));
    }
}
