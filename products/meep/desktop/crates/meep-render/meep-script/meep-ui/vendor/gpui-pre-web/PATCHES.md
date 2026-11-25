gpui-pre-web 0.3.11 from crates.io (Apache-2.0).

Add `WebPlatform::new_with_system_font`, with the same constructor parameters
as `new_with_backend_and_font_fallback` plus a system-font family. Existing
constructors retain their behavior. The preview selects the original Inter
family. The existing `font_fallback` argument controls eligible Canvas glyphs
(emoji/CJK), not the `.SystemUIFont` mapping, which was hardcoded to IBM Plex
Sans. Setting the component theme alone still panics on GPUI's default font
metrics before the themed subtree lays out. No renamed font files or aliases.

Honor background appearance through WgpuRenderer::update_transparency and retain
the selected appearance on WebWindow, rather than forcing an opaque canvas.
