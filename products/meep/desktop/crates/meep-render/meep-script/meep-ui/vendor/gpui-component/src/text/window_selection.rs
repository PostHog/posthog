#[cfg(test)]
mod tests {
    use crate::global_state::GlobalState;
    use crate::{
        Placement, Root,
        text::{TextView, TextViewState},
    };
    use gpui::{
        App, AppContext as _, Bounds, Context, Element, ElementId, Entity, FocusHandle,
        GlobalElementId, Hitbox, InspectorElementId, InteractiveElement as _, IntoElement,
        LayoutId, Modifiers, MouseButton, MouseDownEvent, MouseUpEvent, ParentElement as _, Pixels,
        Render, SharedString, Styled as _, StyledText, TestAppContext, VisualTestContext, Window,
        div, point, px, relative,
    };
    use gpui_base::{
        AutoScroll, TextSelection, TextSelectionHandle, TextSelectionRegistration, TextSelectionRun,
    };
    use std::cell::{Cell, RefCell};
    use std::rc::Rc;
    use std::time::Duration;

    struct PlainSelectableText {
        selection: TextSelectionHandle,
        text: SharedString,
        styled_text: StyledText,
        document_order: u64,
    }

    impl PlainSelectableText {
        fn new(selection: TextSelectionHandle, text: impl Into<SharedString>) -> Self {
            let text = text.into();
            Self {
                selection,
                styled_text: StyledText::new(text.clone()),
                text,
                document_order: 0,
            }
        }

        fn document_order(mut self, document_order: u64) -> Self {
            self.document_order = document_order;
            self
        }
    }

    impl IntoElement for PlainSelectableText {
        type Element = Self;

        fn into_element(self) -> Self::Element {
            self
        }
    }

    impl Element for PlainSelectableText {
        type RequestLayoutState = ();
        type PrepaintState = Hitbox;

        fn id(&self) -> Option<ElementId> {
            None
        }

        fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
            None
        }

        fn request_layout(
            &mut self,
            id: Option<&GlobalElementId>,
            inspector_id: Option<&InspectorElementId>,
            window: &mut Window,
            cx: &mut App,
        ) -> (LayoutId, Self::RequestLayoutState) {
            self.styled_text
                .request_layout(id, inspector_id, window, cx)
        }

        fn prepaint(
            &mut self,
            id: Option<&GlobalElementId>,
            inspector_id: Option<&InspectorElementId>,
            bounds: Bounds<Pixels>,
            _: &mut Self::RequestLayoutState,
            window: &mut Window,
            cx: &mut App,
        ) -> Self::PrepaintState {
            self.styled_text
                .prepaint(id, inspector_id, bounds, &mut (), window, cx);
            let hitbox = window.insert_hitbox(bounds, gpui::HitboxBehavior::Normal);
            self.selection.register(
                TextSelectionRegistration::new(hitbox.clone(), bounds)
                    .with_document_order(self.document_order)
                    .with_text_bounds(vec![bounds]),
                window,
                cx,
            );
            hitbox
        }

        fn paint(
            &mut self,
            id: Option<&GlobalElementId>,
            inspector_id: Option<&InspectorElementId>,
            bounds: Bounds<Pixels>,
            _: &mut Self::RequestLayoutState,
            _: &mut Self::PrepaintState,
            window: &mut Window,
            cx: &mut App,
        ) {
            let layout = self.styled_text.layout().clone();
            self.selection.update_runs(
                &[TextSelectionRun::new(self.text.clone(), layout, bounds).with_document_order(0)],
                cx,
            );
            self.styled_text
                .paint(id, inspector_id, bounds, &mut (), &mut (), window, cx);
        }
    }

    struct MixedAdapterView {
        plain_selection: TextSelectionHandle,
        text_view: Entity<TextViewState>,
    }

    impl MixedAdapterView {
        fn new(cx: &mut Context<Self>) -> Self {
            Self {
                plain_selection: TextSelectionHandle::new("", cx),
                text_view: cx.new(|cx| TextViewState::markdown("TextView adapter", cx)),
            }
        }
    }

    impl Render for MixedAdapterView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .pt(px(10.))
                .child(div().h(px(40.)).child(PlainSelectableText::new(
                    self.plain_selection.clone(),
                    "Plain adapter",
                )))
                .child(
                    div()
                        .h(px(40.))
                        .child(TextView::new(&self.text_view).selectable(true)),
                )
        }
    }

    struct BaseOwnedTextViewSelection {
        text_view: Entity<TextViewState>,
    }

    struct CrossRendererVirtualView {
        top_selection: TextSelectionHandle,
        bottom_selection: TextSelectionHandle,
        text_view: Entity<TextViewState>,
        format: crate::text::SelectionFormat,
    }

    impl CrossRendererVirtualView {
        fn new(format: crate::text::SelectionFormat, cx: &mut Context<Self>) -> Self {
            let source = (0..20)
                .map(|ix| format!("**Paragraph{ix}**"))
                .collect::<Vec<_>>()
                .join("\n\n");
            Self {
                top_selection: TextSelectionHandle::new("", cx),
                bottom_selection: TextSelectionHandle::new("", cx),
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
                format,
            }
        }
    }

    impl Render for CrossRendererVirtualView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .pt(px(10.))
                .child(
                    div().h(px(40.)).child(
                        PlainSelectableText::new(self.top_selection.clone(), "Top plain")
                            .document_order(0),
                    ),
                )
                .child(
                    div().h(px(80.)).child(
                        TextView::new(&self.text_view)
                            .selectable(true)
                            .scrollable(true)
                            .selection_format(self.format),
                    ),
                )
                .child(
                    div().h(px(40.)).child(
                        PlainSelectableText::new(self.bottom_selection.clone(), "Bottom plain")
                            .document_order(2),
                    ),
                )
        }
    }

    enum CrossRendererVirtualScenario {
        PlainToVirtualTail,
        VirtualHeadToPlain,
        VirtualInMiddle,
    }

    fn assert_cross_renderer_virtual_export(
        format: crate::text::SelectionFormat,
        scenario: CrossRendererVirtualScenario,
        cx: &mut TestAppContext,
    ) {
        use gpui::ListOffset;

        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(move |window, cx| {
            let content = cx.new(|cx| CrossRendererVirtualView::new(format, cx));
            Root::new(content, window, cx)
        });
        let content = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<CrossRendererVirtualView>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let (bounds, list_state) = content.read_with(cx, |content, cx| {
            let state = content.text_view.read(cx);
            (state.bounds(), state.list_state().clone())
        });
        let top_plain = point(px(1.), bounds.origin.y - px(20.));
        let bottom_plain = point(px(1.), bounds.bottom() + px(20.));

        match scenario {
            CrossRendererVirtualScenario::PlainToVirtualTail => {
                list_state.scroll_to(ListOffset {
                    item_ix: 19,
                    offset_in_item: px(0.),
                });
                cx.update(|window, cx| {
                    let _ = window.draw(cx);
                });
                drag(
                    cx,
                    top_plain,
                    point(bounds.right() - px(1.), bounds.bottom() - px(1.)),
                );
            }
            CrossRendererVirtualScenario::VirtualHeadToPlain => {
                drag(cx, bounds.origin + point(px(1.), px(1.)), bottom_plain);
            }
            CrossRendererVirtualScenario::VirtualInMiddle => {
                drag(cx, top_plain, bottom_plain);
            }
        }

        let text = window_selected_text(cx);
        for ix in 0..20 {
            let expected = if format == crate::text::SelectionFormat::Source {
                format!("**Paragraph{ix}**")
            } else {
                format!("Paragraph{ix}")
            };
            assert!(
                text.contains(&expected),
                "missing {expected:?} for cross-selection virtual selection: {text:?}"
            );
        }
    }

    #[gpui::test]
    fn plain_to_virtual_tail_exports_unpainted_plain_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Plain,
            CrossRendererVirtualScenario::PlainToVirtualTail,
            cx,
        );
    }

    #[gpui::test]
    fn plain_to_virtual_tail_exports_unpainted_source_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Source,
            CrossRendererVirtualScenario::PlainToVirtualTail,
            cx,
        );
    }

    #[gpui::test]
    fn virtual_head_to_plain_exports_unpainted_plain_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Plain,
            CrossRendererVirtualScenario::VirtualHeadToPlain,
            cx,
        );
    }

    #[gpui::test]
    fn virtual_head_to_plain_exports_unpainted_source_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Source,
            CrossRendererVirtualScenario::VirtualHeadToPlain,
            cx,
        );
    }

    #[gpui::test]
    fn middle_virtual_renderer_exports_all_plain_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Plain,
            CrossRendererVirtualScenario::VirtualInMiddle,
            cx,
        );
    }

    #[gpui::test]
    fn middle_virtual_renderer_exports_all_source_blocks(cx: &mut TestAppContext) {
        assert_cross_renderer_virtual_export(
            crate::text::SelectionFormat::Source,
            CrossRendererVirtualScenario::VirtualInMiddle,
            cx,
        );
    }

    impl BaseOwnedTextViewSelection {
        fn new(cx: &mut Context<Self>) -> Self {
            Self {
                text_view: cx.new(|cx| TextViewState::markdown("Single authority", cx)),
            }
        }
    }

    impl Render for BaseOwnedTextViewSelection {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().pt(px(10.)).child(
                div()
                    .h(px(40.))
                    .child(TextView::new(&self.text_view).selectable(true)),
            )
        }
    }

    struct ChatTestView {
        focus_handle: FocusHandle,
        first: Entity<TextViewState>,
        second: Entity<TextViewState>,
        second_selectable: bool,
        /// Top padding above the views. Bumping it shifts the whole content
        /// down, which is the layout-level equivalent of an outer container
        /// scrolling (see `selection_follows_content_when_layout_shifts`).
        top_offset: gpui::Pixels,
        /// Blank gap between the two views, used to anchor a selection in blank
        /// space (the proxy-anchored endpoint path).
        mid_gap: gpui::Pixels,
        first_style: crate::text::TextViewStyle,
    }

    impl ChatTestView {
        fn new(second_selectable: bool, cx: &mut Context<Self>) -> Self {
            Self {
                focus_handle: cx.focus_handle(),
                first: cx.new(|cx| TextViewState::markdown("Hello world", cx)),
                second: cx.new(|cx| TextViewState::markdown("Second message", cx)),
                second_selectable,
                top_offset: px(10.),
                mid_gap: px(0.),
                first_style: crate::text::TextViewStyle::default(),
            }
        }
    }

    impl Render for ChatTestView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // `track_focus` makes the root a focusable container, so GPUI's
            // focus-on-mouse-down marks every press inside it default-prevented.
            // Selection must still start from blank space here (regression
            // guard for `drag_from_blank_space_selects_views_below`), which the
            // `suppress_text_selection` mechanism guarantees because blank-space
            // presses never set that flag.
            div()
                .track_focus(&self.focus_handle)
                .size_full()
                .pt(self.top_offset)
                .child(
                    div().h(px(40.)).child(
                        TextView::new(&self.first)
                            .selectable(true)
                            .style(self.first_style.clone()),
                    ),
                )
                // A blank gap between the two views. It is not over any
                // TextView hitbox, so a press here exercises the blank-space
                // (proxy-anchored) endpoint path.
                .child(div().h(self.mid_gap))
                .child(
                    div()
                        .h(px(40.))
                        .child(TextView::new(&self.second).selectable(self.second_selectable)),
                )
                // A 20px selection below the views that owns its press the way
                // Input/Button do: its bubble-phase handler sets the suppress
                // flag, so a press starting here must not start a selection.
                .child(
                    div()
                        .h(px(20.))
                        .on_mouse_down(MouseButton::Left, |_, _, cx| {
                            GlobalState::suppress_text_selection(cx);
                        }),
                )
        }
    }

    fn setup(
        second_selectable: bool,
        cx: &mut TestAppContext,
    ) -> (Entity<ChatTestView>, &mut VisualTestContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let chat = cx.new(|cx| ChatTestView::new(second_selectable, cx));
            Root::new(chat, window, cx)
        });
        let chat = root.read_with(cx, |root, _| {
            root.view().clone().downcast::<ChatTestView>().unwrap()
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        (chat, cx)
    }

    #[gpui::test]
    fn base_plain_selection_and_text_view_share_one_cross_renderer_selection(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|window, cx| {
            let content = cx.new(MixedAdapterView::new);
            Root::new(content, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_down(
            point(px(1.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(300.), px(70.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(300.), px(70.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let selected = cx.update(|window, cx| TextSelection::selected_text(window, cx));
        assert_eq!(selected.trim(), "Plain adapter\nTextView adapter");
    }

    #[gpui::test]
    fn clearing_base_state_leaves_no_root_owned_text_view_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let content = cx.new(BaseOwnedTextViewSelection::new);
            Root::new(content, window, cx)
        });
        let content = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<BaseOwnedTextViewSelection>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_down(
            point(px(1.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(300.), px(15.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(300.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert_eq!(
            content
                .read_with(cx, |view, cx| view.text_view.read(cx).selected_text())
                .trim(),
            "Single authority"
        );

        cx.update(|window, cx| {
            TextSelection::clear(window, cx);
            let _ = window.draw(cx);
        });

        let selected = content.read_with(cx, |view, cx| view.text_view.read(cx).selected_text());
        assert!(
            selected.is_empty(),
            "TextView retained selection outside the window selection state: {selected:?}"
        );
    }

    #[gpui::test]
    fn base_clear_resets_text_view_before_returning(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let content = cx.new(BaseOwnedTextViewSelection::new);
            Root::new(content, window, cx)
        });
        let content = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<BaseOwnedTextViewSelection>()
                .unwrap()
        });
        let text_view = content.read_with(cx, |content, _| content.text_view.clone());
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            text_view.update(cx, |state, cx| state.select_all(cx));
            TextSelection::clear(window, cx);
            assert_eq!(text_view.read(cx).selected_text(), "");
        });
    }

    #[gpui::test]
    fn base_clear_then_select_all_in_one_effect_keeps_the_new_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let content = cx.new(BaseOwnedTextViewSelection::new);
            Root::new(content, window, cx)
        });
        let content = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<BaseOwnedTextViewSelection>()
                .unwrap()
        });
        let text_view = content.read_with(cx, |content, _| content.text_view.clone());
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            text_view.update(cx, |state, cx| state.select_all(cx));
            TextSelection::clear(window, cx);
            text_view.update(cx, |state, cx| state.select_all(cx));
        });
        cx.run_until_parked();

        let (has_selection, selected) = cx.update(|window, cx| {
            (
                TextSelection::has_selection(window, cx),
                TextSelection::selected_text(window, cx),
            )
        });
        assert!(has_selection);
        assert_eq!(selected.trim(), "Single authority");
    }

    /// A `scrollable(true)` TextView virtualizes its blocks, so a block only
    /// learns its selection once it has been painted. Pressing at the top,
    /// scrolling with the wheel and releasing at the bottom leaves every block
    /// in between unpainted — copying used to drop all of them.
    struct ScrollableTextViewTest {
        text_view: Entity<TextViewState>,
    }

    struct AutoScrollTextViewTest {
        text_view: Entity<TextViewState>,
    }

    struct PaddedReaderAutoScrollTest {
        text_view: Entity<TextViewState>,
    }

    struct PaddedScrollableTextViewTest {
        text_view: Entity<TextViewState>,
    }

    /// Same as [`ScrollableTextViewTest`], but copying yields source.
    struct SourceTextViewTest {
        text_view: Entity<TextViewState>,
    }

    impl Render for SourceTextViewTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div().h(px(60.)).child(
                    TextView::new(&self.text_view)
                        .selectable(true)
                        .scrollable(true)
                        .selection_format(crate::text::SelectionFormat::Source),
                ),
            )
        }
    }

    impl Render for ScrollableTextViewTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div().h(px(60.)).child(
                    TextView::new(&self.text_view)
                        .selectable(true)
                        .scrollable(true),
                ),
            )
        }
    }

    impl Render for AutoScrollTextViewTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div()
                    .debug_selector(|| "scrollable-text-view".into())
                    .h(px(300.))
                    .overflow_hidden()
                    .child(
                        TextView::new(&self.text_view)
                            .flex_none()
                            .px_5()
                            .selectable(true)
                            .scrollable(true),
                    ),
            )
        }
    }

    /// Scroll offset in pixels from the top of the list (positive = scrolled down).
    fn list_scroll_px(text_view: &Entity<TextViewState>, cx: &mut VisualTestContext) -> Pixels {
        text_view.read_with(cx, |state, _| {
            -state.list_state().scroll_px_offset_for_scrollbar().y
        })
    }

    /// Drags from `start` to `edge`, holds for `ticks` auto-scroll frames, and
    /// returns how far the list moved. One 16 ms timer drives the list, so the
    /// distance is bounded by `ticks` times the per-frame delta; a second
    /// writer shows up as an overshoot.
    fn drag_and_hold(
        text_view: &Entity<TextViewState>,
        start: gpui::Point<Pixels>,
        edge: gpui::Point<Pixels>,
        ticks: u32,
        cx: &mut VisualTestContext,
    ) -> Pixels {
        let before = list_scroll_px(text_view, cx);
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_move(edge, Some(MouseButton::Left), Modifiers::default());
        cx.executor()
            .advance_clock(Duration::from_millis(16 * u64::from(ticks)));
        cx.run_until_parked();
        let after = list_scroll_px(text_view, cx);
        cx.simulate_mouse_up(edge, MouseButton::Left, Modifiers::default());
        after - before
    }

    fn assert_auto_scroll_magnitude(moved: Pixels, per_tick: Pixels, ticks: u32, label: &str) {
        let max = per_tick * ticks as f32;
        if per_tick > px(0.) {
            assert!(
                moved > px(0.) && moved <= max,
                "{label}: moved {moved:?}, expected within (0, {max:?}] for {ticks} ticks of {per_tick:?}"
            );
        } else {
            assert!(
                moved < px(0.) && moved >= max,
                "{label}: moved {moved:?}, expected within [{max:?}, 0) for {ticks} ticks of {per_tick:?}"
            );
        }
    }

    #[gpui::test]
    fn held_text_view_drag_auto_scroll_extends_selection(cx: &mut TestAppContext) {
        let source = (0..100)
            .map(|ix| format!("Paragraph {ix} with enough text to select"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| AutoScrollTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let text_view = root.read_with(cx, |root, cx| {
            root.view()
                .clone()
                .downcast::<AutoScrollTextViewTest>()
                .unwrap()
                .read(cx)
                .text_view
                .clone()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let bounds = cx
            .debug_bounds("scrollable-text-view")
            .expect("scrollable TextView bounds");
        // On the first paragraph's line: a drag that neither starts nor
        // lands on text selects nothing, and the edge may sit in a gap.
        let start = point(bounds.left() + px(30.), bounds.top() + px(10.));
        let edge = point(bounds.left() + px(60.), bounds.bottom() - px(2.));
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_move(edge, Some(MouseButton::Left), Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let before = window_selected_text(cx);
        assert!(!before.is_empty(), "the drag must start a text selection");
        // Each tick paints the newly scrolled blocks, with no further mouse moves.
        for _ in 0..12 {
            cx.executor().advance_clock(Duration::from_millis(16));
            cx.run_until_parked();
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
        }
        let after = window_selected_text(cx);
        cx.simulate_mouse_up(edge, MouseButton::Left, Modifiers::default());
        assert!(
            after.len() > before.len(),
            "holding at edge must expand selection: before={before:?}, after={after:?}"
        );
        let stopped_at = list_scroll_px(&text_view, cx);
        cx.executor().advance_clock(Duration::from_millis(64));
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert_eq!(list_scroll_px(&text_view, cx), stopped_at);
        assert_eq!(window_selected_text(cx), after);
    }

    #[gpui::test]
    fn compatibility_text_view_drag_selection_auto_scrolls_both_directions(
        cx: &mut TestAppContext,
    ) {
        use gpui::ListOffset;

        let source = (0..100)
            .map(|ix| format!("Paragraph {ix} with enough text to select"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| AutoScrollTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<AutoScrollTextViewTest>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let bounds = cx
            .debug_bounds("scrollable-text-view")
            .expect("scrollable TextView bounds");
        // The TextView fills the viewport, so the per-frame delta the drag
        // requests is the one measured against the viewport edge.
        const TICKS: u32 = 4;
        let start = point(bounds.left() + px(30.), bounds.top() + px(30.));
        let edge = point(bounds.left() + px(60.), bounds.bottom() - px(2.));
        let per_tick = AutoScroll::compute_delta(edge.y, bounds).expect("edge zone");
        let text_view = view.read_with(cx, |view, _| view.text_view.clone());
        let moved = drag_and_hold(&text_view, start, edge, TICKS, cx);
        assert_auto_scroll_magnitude(moved, per_tick, TICKS, "downward");

        let list_state = text_view.read_with(cx, |state, _| state.list_state().clone());
        list_state.scroll_to(ListOffset {
            item_ix: 99,
            offset_in_item: px(0.),
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let start = point(bounds.left() + px(30.), bounds.bottom() - px(30.));
        let edge = point(bounds.left() + px(60.), bounds.top() + px(2.));
        let per_tick = AutoScroll::compute_delta(edge.y, bounds).expect("edge zone");
        let moved = drag_and_hold(&text_view, start, edge, TICKS, cx);
        assert_auto_scroll_magnitude(moved, per_tick, TICKS, "upward");
    }

    /// The reader layout from the field report: a clipping row that centers a
    /// vertically padded, full-height scrollable TextView. The list's edges
    /// sit inside the padding, so a wheel event synthesized at the clipping
    /// ancestor's edge misses the list hitbox; only the participant path
    /// scrolls it.
    impl Render for PaddedReaderAutoScrollTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div()
                    .debug_selector(|| "reader".into())
                    .flex()
                    .flex_row()
                    .h(px(300.))
                    .min_w(px(0.))
                    .overflow_hidden()
                    .justify_center()
                    .child(
                        TextView::new(&self.text_view)
                            .scrollable(true)
                            .selectable(true)
                            .px_5()
                            .py_3()
                            .h_full()
                            .w_full()
                            .max_w(relative(0.85))
                            .mx_auto(),
                    ),
            )
        }
    }

    #[gpui::test]
    fn padded_reader_text_view_auto_scrolls_at_the_clipping_edge(cx: &mut TestAppContext) {
        let source = (0..100)
            .map(|ix| format!("Paragraph {ix} with enough text to select"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| PaddedReaderAutoScrollTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<PaddedReaderAutoScrollTest>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let reader = cx.debug_bounds("reader").expect("reader bounds");
        let text_view = view.read_with(cx, |view, _| view.text_view.clone());
        let list_bounds = text_view.read_with(cx, |state, _| state.list_state().viewport_bounds());
        assert!(
            list_bounds.bottom() < reader.bottom() - px(2.),
            "the list must end inside the padding: list {list_bounds:?}, reader {reader:?}"
        );

        // Below the list but inside the clipping ancestor: the synthetic wheel
        // is clamped to this band and misses the list hitbox.
        let start = point(reader.center().x, reader.top() + px(40.));
        let edge = point(reader.center().x, reader.bottom() - px(2.));
        let moved = drag_and_hold(&text_view, start, edge, 4, cx);
        assert!(
            moved > px(0.),
            "dragging to the clipping edge must scroll the padded list, moved {moved:?}"
        );
    }

    struct ClippedReaderAutoScrollTest {
        text_view: Entity<TextViewState>,
    }

    // A TextView taller than its clipping ancestor.
    impl Render for ClippedReaderAutoScrollTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                div()
                    .debug_selector(|| "reader".into())
                    .flex()
                    .flex_row()
                    .h(px(300.))
                    .min_w(px(0.))
                    .overflow_hidden()
                    .justify_center()
                    .child(
                        TextView::new(&self.text_view)
                            .scrollable(true)
                            .selectable(true)
                            .h(px(600.))
                            .flex_none()
                            .w_full()
                            .max_w(relative(0.85))
                            .mx_auto(),
                    ),
            )
        }
    }

    #[gpui::test]
    fn clipped_reader_text_view_auto_scrolls_at_the_visible_edge(cx: &mut TestAppContext) {
        let source = (0..100)
            .map(|ix| format!("Paragraph {ix} with enough text to select"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| ClippedReaderAutoScrollTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<ClippedReaderAutoScrollTest>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let reader = cx.debug_bounds("reader").expect("reader bounds");
        let text_view = view.read_with(cx, |view, _| view.text_view.clone());
        let list_bounds = text_view.read_with(cx, |state, _| state.list_state().viewport_bounds());
        assert!(list_bounds.bottom() > reader.bottom() + px(100.));

        // The visible edge is well above the TextView's own bottom.
        let start = point(reader.center().x, reader.top() + px(40.));
        let edge = point(reader.center().x, reader.bottom() - px(2.));
        let moved = drag_and_hold(&text_view, start, edge, 4, cx);
        assert!(
            moved > px(0.),
            "dragging to the clipping edge must scroll the clipped list, moved {moved:?}"
        );
    }

    impl Render for PaddedScrollableTextViewTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                TextView::new(&self.text_view)
                    .selectable(true)
                    .scrollable(true)
                    .h(px(300.))
                    .p(px(100.)),
            )
        }
    }

    #[gpui::test]
    fn padded_scrollable_text_view_uses_content_origin_for_virtual_blocks(cx: &mut TestAppContext) {
        use gpui::ListOffset;

        const BLOCKS: usize = 20;
        let source = (0..BLOCKS)
            .map(|ix| format!("Paragraph{ix}"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| PaddedScrollableTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<PaddedScrollableTextViewTest>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let (text_view, bounds) = view.read_with(cx, |view, cx| {
            let state = view.text_view.read(cx);
            (view.text_view.clone(), state.bounds())
        });

        cx.simulate_mouse_down(
            bounds.origin + point(px(1.), px(1.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        let list_state = text_view.read_with(cx, |state, _| state.list_state().clone());
        list_state.scroll_to(ListOffset {
            item_ix: BLOCKS - 1,
            offset_in_item: px(0.),
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(bounds.right() - px(1.), bounds.bottom() - px(1.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(bounds.right() - px(1.), bounds.bottom() - px(1.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        assert!(
            text.contains("Paragraph0"),
            "first block was skipped: {text:?}"
        );
        assert!(
            text.contains("Paragraph18"),
            "drag did not reach the tail: {text:?}"
        );
    }

    /// [`Paragraph::render`] stores one `InlineState` per run of children
    /// between inline images, so selection offsets belong to a run, not to a
    /// single child. Mapping them against every child made the text before an
    /// image show up again as if it were the text after it.
    struct InlineImageSourceTestView {
        text_view: Entity<TextViewState>,
    }

    impl Render for InlineImageSourceTestView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().pt(px(10.)).child(
                div().h(px(80.)).child(
                    TextView::new(&self.text_view)
                        .selectable(true)
                        .selection_format(crate::text::SelectionFormat::Source),
                ),
            )
        }
    }

    #[gpui::test]
    fn selection_spans_blocks_scrolled_past(cx: &mut TestAppContext) {
        use gpui::{ScrollDelta, ScrollEvent};

        const BLOCKS: usize = 20;

        cx.update(crate::init);
        let source = (0..BLOCKS)
            .map(|ix| format!("Paragraph{ix}"))
            .collect::<Vec<_>>()
            .join("\n\n");
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| ScrollableTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        // Press inside the first block, then wheel-scroll to the end. The
        // blocks scrolled past are never painted while the drag is active.
        cx.simulate_mouse_down(
            point(px(0.), px(1.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        for _ in 0..BLOCKS {
            cx.simulate_event(ScrollEvent {
                position: point(px(10.), px(30.)),
                delta: ScrollDelta::Pixels(point(px(0.), px(-40.))),
                ..Default::default()
            });
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
        }

        // Release over the last visible block.
        cx.simulate_mouse_move(
            point(px(150.), px(58.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(
            point(px(150.), px(58.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        let missing = (0..BLOCKS)
            .filter(|ix| !text.contains(&format!("Paragraph{ix}")))
            .collect::<Vec<_>>();
        assert!(
            missing.is_empty(),
            "blocks scrolled past were dropped: {missing:?} in {text:?}"
        );
    }

    /// Source mode has the same gap to bridge as plain text: a block the
    /// selection spans but that scrolled past without painting reports no
    /// selection of its own, and must still be copied — with its markup.
    #[gpui::test]
    fn source_selection_spans_blocks_scrolled_past(cx: &mut TestAppContext) {
        use gpui::{ScrollDelta, ScrollEvent};

        const BLOCKS: usize = 20;

        cx.update(crate::init);
        let source = (0..BLOCKS)
            .map(|ix| format!("**Paragraph{ix}**"))
            .collect::<Vec<_>>()
            .join("\n\n");
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| SourceTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_down(
            point(px(0.), px(1.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        // Jump the whole document in one go, so the blocks in between never
        // paint at all and cannot leave a stale selection behind.
        cx.simulate_event(ScrollEvent {
            position: point(px(10.), px(30.)),
            delta: ScrollDelta::Pixels(point(px(0.), px(-40.) * BLOCKS as f32)),
            ..Default::default()
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_move(
            point(px(150.), px(58.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(
            point(px(150.), px(58.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        let missing = (0..BLOCKS)
            .filter(|ix| !text.contains(&format!("**Paragraph{ix}**")))
            .collect::<Vec<_>>();
        assert!(
            missing.is_empty(),
            "blocks scrolled past were dropped or lost their markup: {missing:?} in {text:?}"
        );
    }

    #[gpui::test]
    fn shrinking_virtual_selection_drops_blocks_beyond_the_new_cursor(cx: &mut TestAppContext) {
        use gpui::ListOffset;

        const BLOCKS: usize = 20;
        let source = (0..BLOCKS)
            .map(|ix| format!("Paragraph{ix}"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| ScrollableTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<ScrollableTextViewTest>()
                .unwrap()
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_down(
            point(px(0.), px(1.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        let list_state =
            view.read_with(cx, |view, cx| view.text_view.read(cx).list_state().clone());
        list_state.scroll_to(ListOffset {
            item_ix: BLOCKS - 1,
            offset_in_item: px(0.),
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(px(150.), px(30.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let expanded = window_selected_text(cx);
        assert!(
            expanded.contains("Paragraph18"),
            "failed to expand near the last block: {expanded:?}"
        );

        list_state.scroll_to(ListOffset {
            item_ix: 5,
            offset_in_item: px(0.),
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(px(150.), px(10.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(150.), px(10.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        assert!(text.contains("Paragraph5"), "got: {text:?}");
        assert!(
            !text.contains("Paragraph18"),
            "stale blocks beyond the new cursor were copied: {text:?}"
        );
    }

    /// A multi-click selection has to come back as source too. The click stores
    /// the plain word it selected as a shortcut, which has lost its markup.
    #[gpui::test]
    fn source_multi_click_selection_keeps_its_markup(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| SourceTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown("**Hello** world", cx)),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let position = point(px(10.), px(10.));
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        assert_eq!(text.trim(), "**Hello**", "got: {text:?}");
    }

    #[gpui::test]
    fn selection_inside_one_block_leaves_the_rest(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let source = (0..20)
            .map(|ix| format!("Paragraph{ix}"))
            .collect::<Vec<_>>()
            .join("\n\n");
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| ScrollableTextViewTest {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        // Stay inside the first block. The blocks below are on screen and
        // simply not selected, so none of them may be filled in.
        drag(cx, point(px(2.), px(4.)), point(px(40.), px(4.)));

        let text = window_selected_text(cx);
        assert!(!text.trim().is_empty(), "nothing selected");
        assert!(
            !text.contains("Paragraph1"),
            "unselected block was filled in: {text:?}"
        );
    }

    #[gpui::test]
    fn source_format_maps_offsets_per_rendered_run(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| InlineImageSourceTestView {
                text_view: cx.new(|cx| {
                    TextViewState::markdown(
                        "Build **status** ![img](https://example.com/i.svg) after text",
                        cx,
                    )
                }),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        drag(cx, point(px(0.), px(11.)), point(px(600.), px(80.)));

        let text = window_selected_text(cx);
        assert_eq!(
            text.trim(),
            "Build **status** ![img](https://example.com/i.svg) after text"
        );
    }

    fn drag(
        cx: &mut VisualTestContext,
        from: gpui::Point<gpui::Pixels>,
        to: gpui::Point<gpui::Pixels>,
    ) {
        drag_through(cx, &[from, to]);
    }

    fn drag_through(cx: &mut VisualTestContext, points: &[gpui::Point<gpui::Pixels>]) {
        assert!(points.len() >= 2);
        let from = points[0];
        let to = *points.last().unwrap();

        cx.simulate_mouse_down(from, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        for point in &points[1..] {
            cx.simulate_mouse_move(*point, Some(MouseButton::Left), Modifiers::default());
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
        }

        cx.simulate_mouse_up(to, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
    }

    fn window_selected_text(cx: &mut VisualTestContext) -> String {
        cx.update(|window, cx| TextSelection::selected_text(window, cx))
    }

    fn click(
        cx: &mut VisualTestContext,
        position: gpui::Point<gpui::Pixels>,
        modifiers: Modifiers,
    ) {
        cx.simulate_mouse_down(position, MouseButton::Left, modifiers);
        cx.simulate_mouse_up(position, MouseButton::Left, modifiers);
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
    }

    fn shift_modifiers() -> Modifiers {
        Modifiers {
            shift: true,
            ..Modifiers::default()
        }
    }

    struct CachedPanelRoot {
        inner: Entity<CachedInnerPanel>,
    }

    /// Samples, from inside the panel and before the TextView paints, whether
    /// the window still holds the selection the TextView is about to draw from.
    /// That is exactly what its inlines read, so a `false` sample is a frame
    /// painted without the highlight.
    struct SelectionPaintProbe {
        samples: Rc<RefCell<Vec<bool>>>,
    }

    impl IntoElement for SelectionPaintProbe {
        type Element = Self;

        fn into_element(self) -> Self::Element {
            self
        }
    }

    impl Element for SelectionPaintProbe {
        type RequestLayoutState = ();
        type PrepaintState = ();

        fn id(&self) -> Option<ElementId> {
            None
        }

        fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
            None
        }

        fn request_layout(
            &mut self,
            _: Option<&GlobalElementId>,
            _: Option<&InspectorElementId>,
            window: &mut Window,
            cx: &mut App,
        ) -> (LayoutId, Self::RequestLayoutState) {
            (window.request_layout(gpui::Style::default(), None, cx), ())
        }

        fn prepaint(
            &mut self,
            _: Option<&GlobalElementId>,
            _: Option<&InspectorElementId>,
            _: Bounds<Pixels>,
            _: &mut Self::RequestLayoutState,
            _: &mut Window,
            _: &mut App,
        ) -> Self::PrepaintState {
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
            let has_selection = TextSelection::has_selection(window, cx);
            self.samples.borrow_mut().push(has_selection);
        }
    }

    struct CachedInnerPanel {
        text_view: Entity<TextViewState>,
        renders: Rc<Cell<usize>>,
        samples: Rc<RefCell<Vec<bool>>>,
    }

    impl Render for CachedInnerPanel {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            self.renders.set(self.renders.get() + 1);
            div()
                .size_full()
                .debug_selector(|| "cached-text-view".into())
                .child(SelectionPaintProbe {
                    samples: self.samples.clone(),
                })
                .child(TextView::new(&self.text_view).selectable(true))
        }
    }

    impl Render for CachedPanelRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(
                self.inner
                    .clone()
                    .cached(gpui::StyleRefinement::default().size_full()),
            )
        }
    }

    /// A dock panel renders its content through `Entity::cached`, which replays
    /// the recorded frame whenever nothing in it changed: the TextView paints
    /// the same text at the same place without any of its elements running.
    /// Sweeping the participant for the generation it could not stamp cleared
    /// the selection it had just painted, and re-registering it on the next
    /// frame brought the selection back — it blinked, and the window never
    /// stopped redrawing.
    #[gpui::test]
    fn selection_inside_a_cached_view_survives_replayed_frames(cx: &mut TestAppContext) {
        let source = (0..20)
            .map(|ix| format!("Paragraph {ix} with enough text to select"))
            .collect::<Vec<_>>()
            .join("\n\n");
        cx.update(crate::init);
        let renders = Rc::new(Cell::new(0));
        let samples: Rc<RefCell<Vec<bool>>> = Rc::default();
        let panel_renders = renders.clone();
        let panel_samples = samples.clone();
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|cx| CachedPanelRoot {
                inner: cx.new(|cx| CachedInnerPanel {
                    text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
                    renders: panel_renders,
                    samples: panel_samples,
                }),
            });
            Root::new(view, window, cx)
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let bounds = cx
            .debug_bounds("cached-text-view")
            .expect("cached TextView bounds");

        let start = bounds.origin + point(px(30.), px(8.));
        drag(cx, start, start + point(px(60.), px(40.)));
        cx.run_until_parked();

        let selected = window_selected_text(cx);
        assert!(!selected.is_empty(), "the drag must select text");
        let settled = renders.get();
        samples.borrow_mut().clear();

        for frame in 0..8 {
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
            cx.run_until_parked();
            assert_eq!(
                window_selected_text(cx),
                selected,
                "frame {frame} lost the selection painted inside the cached panel"
            );
        }
        // Every frame the panel did repaint must have had the selection to
        // paint; a `false` here is the blink itself.
        assert!(
            samples.borrow().iter().all(|has_selection| *has_selection),
            "the panel repainted without a selection: {:?}",
            samples.borrow()
        );
        assert_eq!(
            renders.get(),
            settled,
            "a settled selection must let the cached panel stay cached"
        );
    }

    #[gpui::test]
    fn shift_click_extends_from_previous_plain_click(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        click(cx, point(px(0.), px(15.)), Modifiers::default());
        click(cx, point(px(300.), px(15.)), shift_modifiers());

        assert_eq!(window_selected_text(cx).trim(), "Hello world");
    }

    #[gpui::test]
    fn shift_click_reuses_anchor_for_repeated_extension(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);
        let anchor = point(px(0.), px(15.));

        click(cx, anchor, Modifiers::default());
        click(cx, point(px(300.), px(15.)), shift_modifiers());
        assert_eq!(window_selected_text(cx).trim(), "Hello world");

        click(cx, anchor, shift_modifiers());
        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn shift_click_keeps_anchor_when_cursor_crosses_it(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);
        let anchor = point(px(20.), px(15.));

        click(cx, anchor, Modifiers::default());
        click(cx, point(px(300.), px(15.)), shift_modifiers());
        assert_eq!(window_selected_text(cx).trim(), "llo world");

        click(cx, point(px(0.), px(15.)), shift_modifiers());
        assert_eq!(window_selected_text(cx).trim(), "He");
    }

    #[gpui::test]
    fn shift_drag_keeps_previous_plain_click_as_anchor(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);
        let modifiers = shift_modifiers();

        click(cx, point(px(0.), px(15.)), Modifiers::default());
        cx.simulate_mouse_down(point(px(20.), px(15.)), MouseButton::Left, modifiers);
        cx.simulate_mouse_move(point(px(300.), px(70.)), Some(MouseButton::Left), modifiers);
        cx.simulate_mouse_up(point(px(300.), px(70.)), MouseButton::Left, modifiers);
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(
            window_selected_text(cx).trim(),
            "Hello world\n\nSecond message"
        );
    }

    #[gpui::test]
    fn shift_click_uses_anchor_established_by_latest_plain_click(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);
        let start = point(px(0.), px(15.));
        let end = point(px(300.), px(15.));
        let new_anchor = point(px(20.), px(15.));

        click(cx, start, Modifiers::default());
        click(cx, end, shift_modifiers());
        assert_eq!(window_selected_text(cx).trim(), "Hello world");

        click(cx, new_anchor, Modifiers::default());
        click(cx, start, shift_modifiers());
        assert_eq!(window_selected_text(cx).trim(), "He");
    }

    #[gpui::test]
    fn shift_click_without_anchor_falls_back_to_plain_click(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        click(cx, point(px(20.), px(15.)), shift_modifiers());

        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn shift_click_extends_across_text_views(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);

        click(cx, point(px(0.), px(15.)), Modifiers::default());
        click(cx, point(px(300.), px(70.)), shift_modifiers());

        let text = window_selected_text(cx);
        assert!(text.contains("Hello world"), "got: {text:?}");
        assert!(text.contains("Second message"), "got: {text:?}");
        let (first_selecting, second_selecting) = cx.update(|_, cx| {
            let chat = chat.read(cx);
            (
                chat.first.read(cx).is_selecting(),
                chat.second.read(cx).is_selecting(),
            )
        });
        assert!(!first_selecting);
        assert!(!second_selecting);
    }

    #[gpui::test]
    fn shift_click_focuses_the_new_endpoint_view(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);

        click(cx, point(px(0.), px(15.)), Modifiers::default());
        click(cx, point(px(300.), px(70.)), shift_modifiers());

        let second_is_focused = cx.update(|window, cx| {
            chat.read(cx)
                .second
                .read(cx)
                .focus_handle()
                .is_focused(window)
        });
        assert!(
            second_is_focused,
            "Shift-click left focus on the anchor view"
        );
    }

    #[gpui::test]
    fn same_size_content_replacement_invalidates_finished_selection(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);

        drag(cx, point(px(0.), px(15.)), point(px(300.), px(15.)));
        assert_eq!(window_selected_text(cx).trim(), "Hello world");

        let first = chat.read_with(cx, |chat, _| chat.first.clone());
        cx.update(|_, cx| {
            first.update(cx, |state, cx| state.set_text("Other words", cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn active_drag_replacement_invalidates_after_mouse_up(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);
        let first = chat.read_with(cx, |chat, _| chat.first.clone());

        cx.simulate_mouse_down(
            point(px(0.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(300.), px(15.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|_, cx| {
            first.update(cx, |state, cx| state.set_text("Other words", cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(
            point(px(300.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn active_drag_append_keeps_compatible_selection(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);
        let first = chat.read_with(cx, |chat, _| chat.first.clone());

        cx.simulate_mouse_down(
            point(px(0.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(300.), px(15.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|_, cx| {
            first.update(cx, |state, cx| state.push_str(" again", cx));
        });
        cx.run_until_parked();
        cx.simulate_mouse_up(
            point(px(300.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let selected = window_selected_text(cx);
        assert!(selected.contains("Hello world"), "selected={selected:?}");
    }

    #[gpui::test]
    fn same_size_style_reflow_keeps_finished_selection(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);
        drag(cx, point(px(0.), px(15.)), point(px(300.), px(15.)));
        assert_eq!(window_selected_text(cx).trim(), "Hello world");

        chat.update(cx, |chat, cx| {
            chat.first_style.heading_base_font_size = px(28.);
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(window_selected_text(cx).trim(), "Hello world");
    }

    #[gpui::test]
    fn shift_click_on_suppressing_control_clears_text_view_selection(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        drag(cx, point(px(0.), px(15.)), point(px(300.), px(70.)));
        assert!(!window_selected_text(cx).is_empty());

        click(cx, point(px(20.), px(100.)), shift_modifiers());

        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn cross_view_drag_merges_text_top_to_bottom(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // From the very start of the first view down into the second view.
        drag(cx, point(px(0.), px(15.)), point(px(300.), px(70.)));

        let text = window_selected_text(cx);
        let first = text.find("Hello world").expect("first view text missing");
        let second = text
            .find("Second message")
            .expect("second view text missing");
        assert!(first < second, "wrong order: {text:?}");
        assert!(text.contains('\n'), "expected newline separator: {text:?}");
    }

    #[gpui::test]
    fn drag_from_blank_space_selects_views_below(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // Start in the blank padding above the first view, enter the second
        // view's rendered text, then drag past its end.
        drag_through(
            cx,
            &[
                point(px(5.), px(2.)),
                point(px(20.), px(70.)),
                point(px(300.), px(70.)),
            ],
        );

        let text = window_selected_text(cx);
        assert!(text.contains("Hello world"), "got: {text:?}");
        assert!(text.contains("Second message"), "got: {text:?}");
    }

    #[gpui::test]
    fn drag_entirely_in_blank_gap_selects_nothing(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);

        // Layout: first [10,50], gap [50,110], second [110,150].
        chat.update(cx, |chat, cx| {
            chat.mid_gap = px(60.);
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        // Drag only inside the gap. The selection never enters either TextView.
        drag(cx, point(px(5.), px(70.)), point(px(300.), px(90.)));

        let text = window_selected_text(cx);
        assert_eq!(text, "", "blank-only drag selected text: {text:?}");
    }

    #[gpui::test]
    fn drag_entirely_in_right_gutter_selects_nothing(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // x=300 is far to the right of the rendered text. Dragging vertically
        // through only that blank gutter must not select nearby TextViews.
        drag(cx, point(px(300.), px(2.)), point(px(300.), px(70.)));

        let text = window_selected_text(cx);
        assert_eq!(text, "", "right-gutter drag selected text: {text:?}");
    }

    #[gpui::test]
    fn selection_follows_content_when_layout_shifts(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);

        // Open a blank gap between the two views so we can anchor a selection
        // in blank space that sits *below* the first view's text and *above*
        // the second. Layout: first [10,50], gap [50,110], second [110,150].
        chat.update(cx, |chat, cx| {
            chat.mid_gap = px(60.);
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        // Anchor in the gap (blank space) and drag down-right into the second
        // view, ending past the end of its text so the whole line is selected.
        // The anchor sits below "Hello world", so only the second view is
        // selected.
        drag_through(
            cx,
            &[
                point(px(0.), px(80.)),
                point(px(20.), px(120.)),
                point(px(300.), px(120.)),
            ],
        );
        let before = window_selected_text(cx);
        assert!(
            before.contains("Second message") && !before.contains("Hello world"),
            "expected only the second view selected, got: {before:?}"
        );

        // Shift the whole content down by 80px — the equivalent of an outer
        // container scrolling. A window-anchored blank endpoint stays at window
        // y=80, which the first view now covers (first moves to ~[90,130]), so
        // the selection drifts to also grab "Hello world". A proxy-anchored
        // endpoint moves with the content and the selection stays stable.
        chat.update(cx, |chat, cx| {
            chat.top_offset = px(90.);
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let after = window_selected_text(cx);
        assert_eq!(before, after, "selection drifted after layout shift");
    }

    #[gpui::test]
    fn suppressed_mouse_down_does_not_start_selection(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // The suppress selection sits below the two views (root pt=10, two 40px
        // view rows -> y in [90, 110)). Pressing inside it makes its bubble
        // handler set the suppress flag, so dragging up across both views must
        // not produce any window selection.
        drag(cx, point(px(20.), px(100.)), point(px(20.), px(15.)));

        let text = window_selected_text(cx);
        assert!(text.is_empty(), "expected no selection, got: {text:?}");
    }

    #[gpui::test]
    fn non_selectable_view_is_excluded(cx: &mut TestAppContext) {
        let (_, cx) = setup(false, cx);

        drag_through(
            cx,
            &[
                point(px(5.), px(2.)),
                point(px(20.), px(15.)),
                point(px(300.), px(15.)),
            ],
        );

        let text = window_selected_text(cx);
        assert!(text.contains("Hello world"), "got: {text:?}");
        assert!(!text.contains("Second message"), "got: {text:?}");
    }

    #[gpui::test]
    fn drag_within_single_view_excludes_others(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // Entirely inside the first view.
        drag(cx, point(px(5.), px(15.)), point(px(60.), px(15.)));

        let text = window_selected_text(cx);
        assert!(!text.contains("Second message"), "got: {text:?}");
        assert!(!text.trim().is_empty(), "expected some selection");
    }

    #[gpui::test]
    fn mouse_down_clears_previous_selection(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        drag(cx, point(px(5.), px(15.)), point(px(300.), px(70.)));
        assert!(!window_selected_text(cx).is_empty());

        // A plain click clears the selection.
        cx.simulate_click(point(px(300.), px(100.)), Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(window_selected_text(cx), "");
    }

    #[gpui::test]
    fn double_click_selects_word_under_root(cx: &mut TestAppContext) {
        let (_, cx) = setup(true, cx);

        // Double-click inside the first view: must trigger the per-view word
        // selection (Inline), not a window-level drag selection.
        let position = point(px(10.), px(15.));
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = window_selected_text(cx);
        assert_eq!(text.trim(), "Hello", "expected word selection: {text:?}");
        assert!(!text.contains("Second message"), "got: {text:?}");
    }

    #[gpui::test]
    fn drag_back_into_anchor_view_clears_other_views(cx: &mut TestAppContext) {
        let (chat, cx) = setup(true, cx);
        let second = chat.read_with(cx, |chat, _| chat.second.clone());

        // Drag from view A down into view B: this is a cross-view selection, so
        // B paints a highlight and `selected_text` reports it.
        cx.simulate_mouse_down(
            point(px(0.), px(15.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(px(300.), px(70.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let text = second.read_with(cx, |state, _| state.selected_text());
        assert!(
            text.contains("Second message"),
            "precondition: B should be selected, got {text:?}"
        );

        // Observe B's re-render requests. A view only drops a stale highlight
        // when it is notified and repaints; this asserts the controller does
        // notify B, independently of whether the test harness happens to
        // repaint B for unrelated reasons.
        let b_notified = Rc::new(Cell::new(false));
        let _subscription = cx.update({
            let b_notified = b_notified.clone();
            let second = second.clone();
            move |_, cx| cx.observe(&second, move |_, _| b_notified.set(true))
        });
        b_notified.set(false);

        // Drag back up inside view A. The drag now lives entirely in A, so
        // `single_view` is Some(A) and the fast path runs. It must still notify
        // B (whose old band crossed B) so B can clear its now-stale highlight.
        //
        // We check this on the in-drag frame, not after mouse-up:
        // `TextSelection::end` notifies every selectable view, which would
        // notify B for an unrelated reason and mask the bug.
        cx.simulate_mouse_move(
            point(px(60.), px(15.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.run_until_parked();

        assert!(
            b_notified.get(),
            "view B was not notified when the drag returned to the anchor view, \
             so its stale highlight would never be repainted away",
        );
    }

    /// A view with a selectable TextView used as Root content. Root mounts the
    /// Dialog/Sheet layers automatically, so a real modal can be opened above it.
    struct ModalScopeTestView {
        focus_handle: FocusHandle,
        base: Entity<TextViewState>,
    }

    impl ModalScopeTestView {
        fn new(cx: &mut Context<Self>) -> Self {
            Self {
                focus_handle: cx.focus_handle(),
                base: cx.new(|cx| TextViewState::markdown("Hello world", cx)),
            }
        }
    }

    impl Render for ModalScopeTestView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().track_focus(&self.focus_handle).size_full().child(
                div()
                    .h(px(40.))
                    .child(TextView::new(&self.base).selectable(true)),
            )
        }
    }

    fn setup_modal(
        cx: &mut TestAppContext,
    ) -> (Entity<ModalScopeTestView>, &mut VisualTestContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(ModalScopeTestView::new);
            Root::new(view, window, cx)
        });
        let view = root.read_with(cx, |root, _| {
            root.view()
                .clone()
                .downcast::<ModalScopeTestView>()
                .unwrap()
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        (view, cx)
    }

    /// Advance past the modal open animation so it reaches its resting position,
    /// then redraw so its TextViews register and their bounds are stable for the
    /// subsequent drag.
    fn settle(cx: &mut VisualTestContext) {
        cx.executor().advance_clock(Duration::from_millis(500));
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
    }

    fn open_dialog_with_text(
        cx: &mut VisualTestContext,
        text: &'static str,
    ) -> Entity<TextViewState> {
        let state = cx.update(|_, cx| cx.new(|cx| TextViewState::markdown(text, cx)));
        let state_for_builder = state.clone();
        cx.update(|window, cx| {
            crate::root::WindowState::update(window, cx, |root, window, cx| {
                root.open_dialog(
                    move |dialog, _, _| {
                        dialog.child(TextView::new(&state_for_builder).selectable(true))
                    },
                    window,
                    cx,
                );
            });
        });
        settle(cx);
        state
    }

    fn open_sheet_with_text(
        cx: &mut VisualTestContext,
        text: &'static str,
    ) -> Entity<TextViewState> {
        let state = cx.update(|_, cx| cx.new(|cx| TextViewState::markdown(text, cx)));
        let state_for_builder = state.clone();
        cx.update(|window, cx| {
            crate::root::WindowState::update(window, cx, |root, window, cx| {
                root.open_sheet_at(
                    Placement::Right,
                    move |sheet, _, _| {
                        sheet.child(TextView::new(&state_for_builder).selectable(true))
                    },
                    window,
                    cx,
                );
            });
        });
        settle(cx);
        state
    }

    #[gpui::test]
    fn drag_inside_dialog_still_selects_its_text(cx: &mut TestAppContext) {
        let (_, cx) = setup_modal(cx);
        let dialog_state = open_dialog_with_text(cx, "Dialog text");

        // A drag entirely within the dialog's TextView must still select (the
        // scope filter must not break in-dialog selection — see #2501).
        let b = dialog_state.read_with(cx, |s, _| s.bounds());
        drag(
            cx,
            point(b.origin.x + px(1.), b.center().y),
            point(b.origin.x + b.size.width + px(80.), b.center().y),
        );

        let text = window_selected_text(cx);
        assert!(
            text.contains("Dialog text"),
            "dialog text was not selectable: {text:?}"
        );
    }

    #[gpui::test]
    fn drag_inside_sheet_still_selects_its_text(cx: &mut TestAppContext) {
        let (_, cx) = setup_modal(cx);
        let sheet_state = open_sheet_with_text(cx, "Sheet text");

        let bounds = sheet_state.read_with(cx, |state, _| state.bounds());
        drag(
            cx,
            point(bounds.origin.x + px(1.), bounds.center().y),
            point(bounds.right() + px(80.), bounds.center().y),
        );

        let text = window_selected_text(cx);
        assert!(
            text.contains("Sheet text"),
            "sheet text was not selectable: {text:?}"
        );
    }

    #[gpui::test]
    fn opening_dialog_clears_base_selection(cx: &mut TestAppContext) {
        let (view, cx) = setup_modal(cx);

        let b = view.read_with(cx, |v, cx| v.base.read(cx).bounds());
        drag(
            cx,
            point(b.origin.x + px(1.), b.center().y),
            point(b.origin.x + b.size.width + px(80.), b.center().y),
        );
        assert!(window_selected_text(cx).contains("Hello world"));

        let _dialog = open_dialog_with_text(cx, "Dialog text");

        let text = window_selected_text(cx);
        assert!(
            !text.contains("Hello world"),
            "base selection was not cleared when the dialog opened: {text:?}"
        );
    }

    /// Regression guard: with a dialog open, a drag that starts in the
    /// dialog's text and leaves it over the overlay must not select the
    /// TextView behind the overlay (#2501 de-guarded both Dialog and Sheet).
    #[gpui::test]
    fn selection_behind_active_dialog_is_excluded(cx: &mut TestAppContext) {
        let (view, cx) = setup_modal(cx);
        let dialog_state = open_dialog_with_text(cx, "Dialog text");

        // Anchor inside the dialog's text, then drag up onto the base view's
        // glyphs (left side; the base view spans the full window width, so its
        // center is far from its text).
        let from = dialog_state.read_with(cx, |s, _| s.bounds().center());
        let to = view.read_with(cx, |v, cx| {
            let b = v.base.read(cx).bounds();
            point(b.origin.x + px(4.), b.center().y)
        });
        drag(cx, from, to);

        let behind = view.read_with(cx, |v, cx| v.base.read(cx).selected_text());
        assert!(
            behind.trim().is_empty(),
            "view behind the dialog overlay was selected: {behind:?}"
        );
    }

    /// The same guard for a Sheet.
    #[gpui::test]
    fn selection_behind_active_sheet_is_excluded(cx: &mut TestAppContext) {
        let (view, cx) = setup_modal(cx);
        let sheet_state = open_sheet_with_text(cx, "Sheet text");

        let from = sheet_state.read_with(cx, |s, _| s.bounds().center());
        let to = view.read_with(cx, |v, cx| {
            let b = v.base.read(cx).bounds();
            point(b.origin.x + px(4.), b.center().y)
        });
        drag(cx, from, to);

        let behind = view.read_with(cx, |v, cx| v.base.read(cx).selected_text());
        assert!(
            behind.trim().is_empty(),
            "view behind the sheet overlay was selected: {behind:?}"
        );
    }
}
