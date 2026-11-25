# GPUI view capture

`gpui-pre`, `gpui-pre-macos`, and `gpui-pre-apple` are pinned to 0.3.11.
The local patch exposes their existing `render_to_image` → Metal offscreen
readback path in normal builds. Only the API, its image/Metal imports, the
offscreen helper and pixel readback helper have been ungated; test-support is
not enabled in the shipping app. Upstream licenses remain in each directory.

The host bounds requests, redraws before capture, rejects obscured or stale
views, crops inward to the view canvas, and encodes/resizes off the UI thread.
This captures GPUI pixels, not AppKit-owned glass/menu/window chrome. No desktop
capture, Screen Recording permission, external process, or screenshot file is
involved. All patched renderer sources are included in the live runtime ABI
fingerprint, so mismatched generated modules cannot load.

Also patched: `PathPromptOptions` has a `show_hidden` field, which the macOS
open panel applies with `setShowsHiddenFiles`. Connector file grants are often
dot folders (`~/.kube`), so their pickers list hidden items.
