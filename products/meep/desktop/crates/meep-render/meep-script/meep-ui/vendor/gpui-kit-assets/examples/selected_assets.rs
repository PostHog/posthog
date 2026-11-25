#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use gpui::AssetSource;
gpui_kit_assets::icon_assets!(AppAssets, [Search, Check]);
fn main() {
    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "icons/search.svg".into());
    // Keep the bytes observable so release size measurements include the SVG payload.
    println!(
        "{}",
        std::hint::black_box(AppAssets.load(&path).unwrap().unwrap()).len()
    );
}
