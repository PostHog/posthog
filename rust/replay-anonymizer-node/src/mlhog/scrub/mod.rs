// Copied from MLHog prep/labeling/src/scrub/mod.rs — bench-only. The v1-only submodules
// (`canvas`, `dom`, `value` — they need the v1 typed event tree / simd-json OwnedValue) and the
// test module are not ported; v2 only imports assets, blur, css, text and url.

pub mod assets;
pub mod blur;
pub mod css;
pub mod text;
pub mod url;
