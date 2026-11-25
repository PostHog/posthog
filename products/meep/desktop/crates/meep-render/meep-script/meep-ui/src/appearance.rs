//! Reusable native previews for palette selection.
use crate::components::{column as col, row};
use gpui_kit::*;
fn bar(width: f32, color: u32) -> Div {
    div()
        .w(px(width))
        .h(px(4.))
        .rounded(px(2.))
        .bg(gpui_kit::rgb(color))
}
/// The app in miniature, drawn in a palette: sidebar, selection, text, action.
pub fn thumbnail(p: [u32; 14]) -> Div {
    row()
        .gap_0()
        .w_full()
        .h(px(68.))
        .rounded(px(5.))
        .border_1()
        .border_color(gpui_kit::rgb(p[5]))
        .bg(gpui_kit::rgb(p[3]))
        .overflow_hidden()
        .child(
            col()
                .w(px(44.))
                .h_full()
                .flex_shrink_0()
                .p(px(7.))
                .gap(px(3.))
                .bg(gpui_kit::rgb(p[6]))
                .child(div().p(px(3.)).child(bar(18., p[2])))
                .child(
                    div()
                        .p(px(3.))
                        .rounded(px(3.))
                        .bg(gpui_kit::rgb(p[7]))
                        .child(bar(22., p[0])),
                )
                .child(div().p(px(3.)).child(bar(14., p[2]))),
        )
        .child(
            col()
                .flex_1()
                .min_w_0()
                .h_full()
                .p(px(10.))
                .gap(px(6.))
                .child(bar(40., p[0]))
                .child(bar(64., p[2]))
                .child(bar(52., p[2]))
                .child(div().flex_1())
                .child(
                    row().justify_end().child(
                        div()
                            .w(px(26.))
                            .h(px(9.))
                            .rounded(px(3.))
                            .bg(gpui_kit::rgb(p[10])),
                    ),
                ),
        )
}

use gpui_kit::{assets::IconName as Glyph, component::Icon, prelude::FluentBuilder};
pub fn preview(p: [u32; 14], wide: bool) -> Div {
    let c = |i: usize| gpui_kit::rgb(p[i]);
    let ink = |alpha: u32| gpui_kit::rgba((p[0] << 8) | alpha);
    let tint = |i: usize, alpha: u32| gpui_kit::rgba((p[i] << 8) | alpha);
    let sheet = |el: Div| {
        el.bg(c(3))
            .rounded(px(9.))
            .border_1()
            .border_color(ink(0x14))
            .shadow(vec![BoxShadow {
                color: rgba(0x0000000d).into(),
                offset: point(px(0.), px(1.)),
                blur_radius: px(3.),
                spread_radius: px(0.),
                inset: false,
            }])
            .overflow_hidden()
    };
    // The window's own controls, then the sidebar's two buttons.
    let lights = row()
        .h(px(26.))
        .px(px(10.))
        .gap(px(5.))
        .children(
            [0xff5f57u32, 0xfebc2e, 0x28c840]
                .map(|color| div().size(px(7.)).rounded_full().bg(gpui_kit::rgb(color))),
        )
        .child(div().flex_1())
        .child(Icon::new(Glyph::PanelLeft).size(px(10.)).text_color(c(1)))
        .child(div().w(px(6.)))
        .child(Icon::new(Glyph::Plus).size(px(10.)).text_color(c(1)));
    let mut views = col().px(px(6.)).gap(px(1.));
    for (name, glyph, hue, selected) in [
        ("Reading list", Glyph::BookOpen, 11, true),
        ("Pull requests", Glyph::GitPullRequest, 12, false),
        ("Journal", Glyph::NotebookPen, 9, false),
        ("Inbox", Glyph::Inbox, 10, false),
    ] {
        views = views.child(
            row()
                .h(px(22.))
                .px(px(5.))
                .gap(px(6.))
                .rounded(px(5.))
                .when(selected, |el| el.bg(c(7)))
                .child(
                    div()
                        .size(px(13.))
                        .flex_none()
                        .rounded(px(3.5))
                        .bg(tint(hue, 0x26))
                        .flex()
                        .items_center()
                        .justify_center()
                        .child(Icon::new(glyph).size(px(8.)).text_color(c(hue))),
                )
                .child(div().child(name).text_size(px(10.)).text_color(c(0))),
        );
    }
    let sidebar = col()
        .w(px(118.))
        .h_full()
        .flex_none()
        .child(lights)
        .child(div().h(px(6.)))
        .child(views)
        .child(div().flex_1())
        .child(
            row()
                .h(px(24.))
                .px(px(11.))
                .gap(px(6.))
                .child(
                    Icon::new(Glyph::SlidersHorizontal)
                        .size(px(9.))
                        .text_color(c(1)),
                )
                .child(div().child("Settings").text_size(px(10.)).text_color(c(0))),
        )
        .child(div().h(px(4.)));
    let mut list = col().w_full();
    for (n, (title, meta)) in [
        ("Designing quiet software", "READ-1 · Medium"),
        ("A field guide to typography", "READ-2 · Long"),
        ("The details are the design", "READ-3 · Short"),
    ]
    .into_iter()
    .enumerate()
    {
        list = list.child(
            col()
                .py(px(6.))
                .gap(px(1.))
                .when(n > 0, |el| el.border_t_1().border_color(c(5)))
                .child(div().child(title).text_size(px(10.5)).text_color(c(0)))
                .child(div().child(meta).text_size(px(9.)).text_color(c(1))),
        );
    }
    let page = sheet(col())
        .flex_1()
        .min_w_0()
        .h_full()
        .px(px(18.))
        .py(px(14.))
        .gap(px(8.))
        .child(
            col()
                .gap(px(1.))
                .child(
                    div()
                        .child("Reading list")
                        .text_size(px(15.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_color(c(0)),
                )
                .child(div().child("6 items").text_size(px(9.5)).text_color(c(1))),
        )
        .child(list);
    let agent = sheet(col())
        .w(px(150.))
        .h_full()
        .flex_none()
        .child(
            row()
                .h(px(26.))
                .px(px(10.))
                .border_b_1()
                .border_color(c(5))
                .child(
                    div()
                        .child("Refine the list")
                        .text_size(px(9.5))
                        .font_weight(FontWeight::MEDIUM)
                        .text_color(c(0)),
                ),
        )
        .child(
            col()
                .flex_1()
                .p(px(9.))
                .gap(px(7.))
                .child(
                    div()
                        .self_end()
                        .max_w(px(118.))
                        .px(px(8.))
                        .py(px(5.))
                        .rounded(px(8.))
                        .bg(c(4))
                        .text_size(px(9.))
                        .text_color(c(0))
                        .child("Make it quieter and easier to scan."),
                )
                .child(
                    div()
                        .child("Done. Metadata is quieter and each title has more room.")
                        .text_size(px(9.))
                        .line_height(px(13.))
                        .text_color(c(0)),
                ),
        )
        .child(
            row()
                .m(px(7.))
                .h(px(30.))
                .px(px(8.))
                .rounded(px(8.))
                .border_1()
                .border_color(c(5))
                .child(
                    div()
                        .child("Work on this view…")
                        .flex_1()
                        .text_size(px(9.))
                        .text_color(c(2)),
                )
                .child(
                    div()
                        .size(px(16.))
                        .rounded(px(5.))
                        .bg(c(10))
                        .flex()
                        .items_center()
                        .justify_center()
                        .child(Icon::new(Glyph::ArrowUp).size(px(9.)).text_color(c(13))),
                ),
        );
    row()
        .gap_0()
        .w_full()
        .h(px(236.))
        .items_stretch()
        .rounded(px(12.))
        .bg(c(6))
        .border_1()
        .border_color(ink(0x14))
        .overflow_hidden()
        .child(sidebar)
        .child(
            row()
                .flex_1()
                .min_w_0()
                .h_full()
                .gap(px(5.))
                .py(px(5.))
                .pr(px(5.))
                .child(page)
                .when(wide, |el| el.child(agent)),
        )
}
