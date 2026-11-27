//! Actual sidebar tile and emoji renderer, shared with native View.
use gpui_kit::{prelude::FluentBuilder, *};
/// Return the foreground and background RGB colors for a named tile palette.
pub fn inks(color: &str) -> (u32, u32) {
    match color {
        "orange" => (0xE5562B, 0xF7B79E),
        "teal" => (0x0E5A57, 0xA8CF8E),
        "ink" => (0x203B63, 0xA9C8EA),
        "plum" => (0x6A2C5B, 0xEBB0CB),
        "mustard" => (0xB97E12, 0xF4DD9C),
        "moss" => (0x3F5F2A, 0xCFE0A2),
        "brick" => (0x9A3826, 0xEDC7A9),
        _ => (0x373D49, 0xC8CDD6),
    }
}

pub fn tile_edge() -> Rgba {
    match meep_ui::theme::is_dark() {
        true => rgba(0xffffff29),
        false => rgba(0x00000040),
    }
}

fn soft_edge() -> Rgba {
    if meep_ui::theme::is_dark() {
        rgba(0xffffff1f)
    } else {
        rgba(0x00000029)
    }
}

fn drop_shadow() -> Vec<BoxShadow> {
    vec![BoxShadow {
        color: rgba(if meep_ui::theme::is_dark() {
            0x00000080
        } else {
            0x00000026
        })
        .into(),
        offset: point(px(0.), px(0.5)),
        blur_radius: px(1.),
        spread_radius: px(0.),
        inset: false,
    }]
}

pub fn relief(tile: Div, size: f32, radius: f32) -> Div {
    let (shine, shade) = if meep_ui::theme::is_dark() {
        (0xffffff33, 0x00000038)
    } else {
        (0xffffffa6, 0x0000001a)
    };
    let ring = |offset: f32, color: Rgba| {
        div()
            .absolute()
            .left_0()
            .top(px(offset))
            .size_full()
            .rounded(px(radius))
            .border(px(1.))
            .border_color(color)
    };
    let tile = tile.relative().overflow_hidden().shadow(drop_shadow());
    if size < 20. {
        tile.child(ring(0., soft_edge()))
    } else {
        tile.child(ring(1., rgba(shine)))
            .child(ring(-1., rgba(shade)))
            .child(ring(0., tile_edge()))
    }
}

fn mix(color: u32, toward: u32, amount: f32) -> u32 {
    let channel = |shift: u32| {
        let a = ((color >> shift) & 0xff) as f32;
        let b = ((toward >> shift) & 0xff) as f32;
        ((a + (b - a) * amount).round() as u32) << shift
    };
    channel(16) | channel(8) | channel(0)
}

pub fn disc(size: f32, background: u32, content: impl IntoElement) -> Div {
    let (light, shade) = if meep_ui::theme::is_dark() {
        (0.18, 0.26)
    } else {
        (0.4, 0.24)
    };
    let k = if size < 20. { 0.6 } else { 1. };
    div()
        .flex_none()
        .size(px(size))
        .rounded_full()
        .shadow(drop_shadow())
        .bg(linear_gradient(
            180.,
            linear_color_stop(rgb(mix(background, 0xffffff, light * k)), 0.),
            linear_color_stop(rgb(mix(background, 0x000000, shade * k)), 0.75),
        ))
        .p(px(1.))
        .child(
            div()
                .size_full()
                .rounded_full()
                .bg(rgb(background))
                .flex()
                .items_center()
                .justify_center()
                .child(content),
        )
}

const TRAFFIC_LIGHTS: [u32; 3] = [0xff5f57, 0xfebc2e, 0x28c840];

pub fn window(emoji: &str, color: &str, width: f32) -> Div {
    let (_, tint) = inks(color);
    let k = width / 34.;
    let (edge, radius, bar, dot) = (1., 6. * k, 7. * k, 3. * k);
    let titlebar = div()
        .flex()
        .items_center()
        .flex_none()
        .h(px(bar - edge))
        .pl(px(4.5 * k - edge))
        .gap(px(1.8 * k))
        .children(TRAFFIC_LIGHTS.map(|c| div().size(px(dot)).rounded_full().bg(rgb(c))));
    let body = div()
        .relative()
        .flex_1()
        .rounded_b(px(radius - edge))
        .bg(rgb(tint))
        .when(width >= 24., |v| {
            v.child(
                div()
                    .absolute()
                    .top_0()
                    .left_0()
                    .right_0()
                    .h(px(1.))
                    .bg(rgba(if meep_ui::theme::is_dark() {
                        0x00000052
                    } else {
                        0x0000001c
                    })),
            )
        })
        .flex()
        .items_center()
        .justify_center()
        .child(
            div()
                .child(SharedString::from(emoji.to_owned()))
                .text_size(px(13. * k))
                .line_height(px(13. * k)),
        );
    div()
        .flex_none()
        .relative()
        .shadow(drop_shadow())
        .w(px(width))
        .h(px(30. * k))
        .rounded(px(radius))
        .border(px(edge))
        .border_color(if width < 20. {
            soft_edge()
        } else {
            tile_edge()
        })
        .bg(rgb(match meep_ui::theme::is_dark() {
            true => 0x3a3a3c,
            false => 0xfafafa,
        }))
        .flex()
        .flex_col()
        .when(width >= 30., |v| {
            v.child(
                div()
                    .absolute()
                    .top_0()
                    .left(px(radius - edge))
                    .right(px(radius - edge))
                    .h(px(edge))
                    .bg(rgba(if meep_ui::theme::is_dark() {
                        0xffffff1f
                    } else {
                        0xffffffd9
                    })),
            )
        })
        .child(titlebar)
        .child(body)
}

/// Render an emoji on a rounded tile of the given size.
pub fn icon(emoji: &str, color: &str, size: f32) -> Div {
    let (_, light) = inks(color);
    relief(
        div()
            .flex_none()
            .size(px(size))
            .rounded(px(size * 0.27))
            .bg(rgb(light))
            .flex()
            .items_center()
            .justify_center()
            .child(
                div()
                    .child(SharedString::from(emoji.to_owned()))
                    .text_size(px(size * 0.7))
                    .line_height(px(size)),
            ),
        size,
        size * 0.27,
    )
}
