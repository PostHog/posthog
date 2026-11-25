//! Shared live semantic palette for app chrome and script views.
use std::cell::Cell;
pub const NAMES: [&str; 14] = [
    "ink",
    "secondary",
    "tertiary",
    "canvas",
    "inset",
    "rule",
    "chrome",
    "selected",
    "danger",
    "positive",
    "accent",
    "orange",
    "purple",
    "accentForeground",
];
pub const DEFAULT: [u32; 14] = [
    0x252525, 0x6b6b6b, 0x929292, 0xffffff, 0xf5f5f5, 0xebebeb, 0xf6f6f6, 0xe9e9e9, 0xa33932,
    0x248a3d, 0x0a66d8, 0xc2610c, 0x7b45c4, 0xffffff,
];
thread_local! { static PALETTE: Cell<[u32; 14]> = const { Cell::new(DEFAULT) }; }
pub fn set(palette: [u32; 14]) {
    PALETTE.with(|p| p.set(palette));
}
pub fn get(index: usize) -> u32 {
    PALETTE.with(|p| p.get()[index])
}
pub fn color(default: u32) -> u32 {
    DEFAULT
        .iter()
        .position(|v| *v == default)
        .map(get)
        .unwrap_or(default)
}
pub fn named(name: &str) -> Option<u32> {
    NAMES.iter().position(|n| *n == name).map(get)
}

/// The native material and control appearance follow the selected surface.
pub fn is_dark() -> bool {
    let color = get(3);
    ((color >> 16) & 255) + ((color >> 8) & 255) + (color & 255) < 384
}

/// Curated colors for compact status marks in sidebar hover cards.
pub fn marker_color(name: &str) -> Option<u32> {
    match name {
        "secondary" | "accent" | "positive" | "danger" | "orange" | "purple" => named(name),
        _ => None,
    }
}
