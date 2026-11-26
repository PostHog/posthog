//! Actual sidebar tile and emoji renderer, shared with native View.
use gpui_kit::*;
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
        .flex_1()
        .rounded_b(px(radius - edge))
        .bg(rgb(tint))
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
        .w(px(width))
        .h(px(30. * k))
        .rounded(px(radius))
        .border(px(edge))
        .border_color(tile_edge())
        .bg(rgb(match meep_ui::theme::is_dark() {
            true => 0x3a3a3c,
            false => 0xfafafa,
        }))
        .flex()
        .flex_col()
        .child(titlebar)
        .child(body)
}

/// Render an emoji on a rounded tile of the given size.
pub fn icon(emoji: &str, color: &str, size: f32) -> Div {
    let (_, light) = inks(color);
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
        )
}
