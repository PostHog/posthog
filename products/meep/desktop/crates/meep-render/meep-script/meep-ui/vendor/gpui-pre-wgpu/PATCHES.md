gpui-pre-wgpu 0.3.11 from crates.io (Apache-2.0).

Match View's existing gpui-pre/Apple rounded-overflow patch. View appends a
32-byte CornerClip to quads, shadows, underlines, monochrome and polychrome
sprites. The unpatched WGPU shader used the upstream shorter stride, silently
reading subsequent records at the wrong offsets and dropping most shapes.

Both WebGPU storage records and WebGL2 texture decoders now match those native
CPU records and apply the same rounded-clip coverage to fragment alpha. Path
sprite compositing carries the clip as the native Metal backend does. Existing
upstream layout assertions are updated. The native Mac app uses Metal and is
unaffected. `crates/view-web/tests/gpu_layout.rs` checks primitive sizes and
validates the WebGPU, WebGL2 and subpixel shader variants through Naga. The
browser suite also samples the sidebar selection fill. Workspace tests compare
reflected Naga record spans against the actual CPU types, independently of the
demo designs.

Packaged benchmark entries are omitted. Upstream package tests refer to fonts
outside the published crate, so regression checks live in the workspace test
above rather than depending on unavailable upstream fixtures.

For the browser WebGPU backend, select PreMultiplied for transparent windows.
wgpu 30's surface capabilities advertise only Opaque, while its own
backend/webgpu.rs::surface_configure explicitly implements PreMultiplied.
The WebGL capability path remains unchanged. Browser smoke checks assert the
actual GPUCanvasContext alphaMode (or WebGL context alpha attribute).
