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
