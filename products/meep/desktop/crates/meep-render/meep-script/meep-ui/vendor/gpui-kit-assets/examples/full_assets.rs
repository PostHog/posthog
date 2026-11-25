#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

// Native-only binary size measurement: WASM assets are fetched from an endpoint.
#[cfg(not(target_family = "wasm"))]
use gpui::AssetSource;
#[cfg(not(target_family = "wasm"))]
fn main() {
    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "icons/search.svg".into());
    // Keep the bytes observable so release size measurements include the SVG payload.
    println!(
        "{}",
        std::hint::black_box(gpui_kit_assets::AllAssets.load(&path).unwrap().unwrap()).len()
    );
}

#[cfg(target_family = "wasm")]
fn main() {}
