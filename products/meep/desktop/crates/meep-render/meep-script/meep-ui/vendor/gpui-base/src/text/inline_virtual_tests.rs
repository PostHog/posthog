use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

use gpui::{
    AppContext as _, Context, Entity, IntoElement, Modifiers, MouseButton, ParentElement as _,
    Pixels, Render, Styled as _, TestAppContext, VisualTestContext, Window, div, point, px, rems,
};

use super::{InlineElement, MarkdownNode, SelectionFormat, TextView, TextViewState};

const BLOCKS: usize = 24;

struct VirtualInlineRoot {
    view: Entity<TextViewState>,
    prepared_size: Arc<AtomicUsize>,
    font_scale: f32,
    source_format: bool,
}

impl Render for VirtualInlineRoot {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let prepared = self.prepared_size.clone();
        div().w(px(400.)).h(px(200.)).overflow_hidden().text_size(rems(self.font_scale))
            .child(crate::TextSelectionLayer)
            .child(TextView::new(&self.view).scrollable(true)
                .selection_format(if self.source_format { SelectionFormat::Source } else { SelectionFormat::Plain })

                .plugin(crate::text::markdown_ext::TestInlinePlugin::new("math").parse_with(|node, _| {
                    let markdown::mdast::Node::InlineMath(math) = node else { return None };
                    Some(MarkdownNode::new("math", ()).text(format!("{}²", math.value)))
                }).render_with(move |_, context, _, _| {
                    let extent = context.font_size() * (prepared.load(Ordering::Relaxed) as f32 / 16.);
                    let image = Arc::new(gpui::Image::from_bytes(gpui::ImageFormat::Svg,
                        b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"40\" height=\"40\"><path d=\"M0 0L40 40\" stroke=\"black\"/></svg>".to_vec()));
                    Some(InlineElement::new(gpui::img(image).w(extent).h(extent)).with_baseline(extent * 0.75))
                })))
    }
}

fn document() -> String {
    (0..BLOCKS)
        .map(|i| format!("第{i}段 $x$ $y$ English"))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn settle(cx: &mut VisualTestContext) {
    cx.run_until_parked();
    cx.update(|window, cx| window.draw(cx).clear(cx));
    cx.run_until_parked();
}

fn total_height(root: &Entity<VirtualInlineRoot>, cx: &mut VisualTestContext) -> Pixels {
    root.read_with(cx, |root, cx| {
        let list = root.view.read(cx).list_state();
        assert_eq!(list.item_count(), BLOCKS);
        list.max_offset_for_scrollbar().y + list.viewport_bounds().size.height
    })
}

#[gpui::test]
fn inline_virtual_resource_growth_remeasures_all_blocks_and_preserves_copy(
    cx: &mut TestAppContext,
) {
    cx.update(crate::init);
    let prepared = Arc::new(AtomicUsize::new(16));
    let (root, cx) = cx.add_window_view(|_, cx| VirtualInlineRoot {
        view: cx.new(|cx| TextViewState::markdown(&document(), cx)),
        prepared_size: prepared.clone(),
        font_scale: 1.,
        source_format: false,
    });
    settle(cx);
    let before = total_height(&root, cx);
    let bounds = root.read_with(cx, |root, cx| {
        root.view.read(cx).selection_adapter.text_bounds()
    });
    let first = bounds.first().unwrap();
    let last = bounds.last().unwrap();
    let start = point(first.left() + px(0.1), first.top() + first.size.height / 2.);
    let end = point(last.right() - px(0.1), last.top() + last.size.height / 2.);
    cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
    settle(cx);
    cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
    settle(cx);
    root.update(cx, |root, cx| {
        root.view.read(cx).list_state().scroll_to_end();
        cx.notify();
    });
    settle(cx);
    let bounds = root.read_with(cx, |root, cx| {
        root.view.read(cx).selection_adapter.text_bounds()
    });
    let last = bounds.last().unwrap();
    let end = point(last.right() - px(0.1), last.top() + last.size.height / 2.);
    cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
    settle(cx);
    cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
    settle(cx);
    let copy_before = root.read_with(cx, |root, cx| {
        root.view.read(cx).selected_text_in(Some(0..=BLOCKS - 1))
    });
    assert!(
        copy_before.contains("第12段 x² y² English"),
        "offscreen covered blocks must use their logical text"
    );
    prepared.store(96, Ordering::Relaxed);
    root.update(cx, |root, cx| {
        root.view
            .update(cx, |state, cx| state.invalidate_inline_layout(cx))
    });
    settle(cx);
    let after = total_height(&root, cx);
    assert!(after > before * 2., "before={before:?}, after={after:?}");
    assert_eq!(
        root.read_with(cx, |root, cx| root
            .view
            .read(cx)
            .selected_text_in(Some(0..=BLOCKS - 1))),
        copy_before
    );
    root.update(cx, |root, cx| {
        root.source_format = true;
        cx.notify();
    });
    settle(cx);
    let source = root.read_with(cx, |root, cx| {
        root.view.read(cx).selected_text_in(Some(0..=BLOCKS - 1))
    });
    assert!(source.contains("第12段 $x$ $y$ English"));
}

#[gpui::test]
fn inline_virtual_font_and_rem_zoom_remeasure_offscreen_blocks(cx: &mut TestAppContext) {
    cx.update(crate::init);
    let (root, cx) = cx.add_window_view(|_, cx| VirtualInlineRoot {
        view: cx.new(|cx| TextViewState::markdown(&document(), cx)),
        prepared_size: Arc::new(AtomicUsize::new(40)),
        font_scale: 1.,
        source_format: false,
    });
    settle(cx);
    let normal = total_height(&root, cx);
    let mut zoomed = normal;
    for scale in [1.5, 2.] {
        root.update(cx, |root, cx| {
            root.font_scale = scale;
            cx.notify();
        });
        settle(cx);
        zoomed = total_height(&root, cx);
        assert!(
            zoomed > normal * (scale * 0.85),
            "scale={scale}, normal={normal:?}, zoomed={zoomed:?}"
        );
    }
    cx.update(|window, cx| {
        window.set_rem_size(window.rem_size() * 1.5);
        window.refresh();
        cx.notify(root.entity_id());
    });
    settle(cx);
    let rem_zoomed = total_height(&root, cx);
    assert!(
        rem_zoomed > zoomed * 1.3,
        "zoomed={zoomed:?}, rem_zoomed={rem_zoomed:?}"
    );
}
