# Web rendering causes

Each cause lists its symptom, the evidence in the export, the fix, and whether existing recordings recover.
The causes are ordered by how often they reach support.
Recipes are in [reading-the-export.md](./reading-the-export.md).

## Canvas, map, WebGL, or WebGPU content is blank

**Symptom:** a black or empty map, chart, 3D view, game, or editor. The rest of the page is fine.

**Evidence:**

- `canvases` in the inventory is not empty.
- Canvas capture is off: `$remote_config_received.payload.recordCanvas` is false or missing, and `$session_options.payload.sessionRecordingOptions.recordCanvas` is not true.
- Or capture is on, but `canvas_ids_with_frames` does not include the blank canvas, and the canvas has no `rr_dataURL`.
- Library class names hint at the renderer, for example `maplibregl-canvas` or `mapboxgl-canvas`.

**Causes and fixes:**

| Cause                                             | Fix                                                                                                                                                         |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Canvas capture is off. It is off by default.      | Turn on canvas capture in the project's replay settings. Optionally set `session_recording.captureCanvas` (`canvasFps`, `canvasQuality`) in `posthog.init`. |
| The canvas uses WebGPU.                           | Not supported. No workaround except a WebGL fallback in the app.                                                                                            |
| WebGL context without a preserved drawing buffer. | Frames can capture blank. Create the context with `preserveDrawingBuffer: true` if the app allows it.                                                       |
| Frames exist but at low rate or quality.          | Capture samples about 4 frames a second at most, through `toDataURL`. Raise `canvasFps` and `canvasQuality`, and expect some lag.                           |

Canvas content cannot be masked by DOM selectors.
Recordings made while capture was off stay blank.
Docs: https://posthog.com/docs/session-replay/canvas-recording

## Page is unstyled, or partly styled

**Symptom:** raw HTML, stacked blocks, default fonts, missing icons. Sometimes only in some recordings.

**Evidence:**

- `stylesheets_not_inlined` lists `<link rel=stylesheet>` hrefs. The player fetches those from the viewer's browser at playback.
- The hrefs are on another origin than the page (CDN, asset host), or behind auth, or have since been deleted by a new deploy (hashed file names).
- Shadow DOM: a `<link>` inside a shadow root that points to another origin, with no `_cssText`.

**Fix:**

- Allow the PostHog app origin (`https://us.posthog.com` or `https://eu.posthog.com`) in the asset host's CORS rules.
- Add `crossorigin="anonymous"` to `<link>` stylesheet tags, with an `Access-Control-Allow-Origin` header on the asset host. Without it, the browser does not let the recorder read `cssRules`, so it cannot inline them.
- For styles that change per deploy, keep old asset versions available, or make sure the recorder can inline them (same-origin or CORS-enabled).
- Intranet or VPN-only asset hosts cannot be reached from the player. Inlining is the only fix.

Fixing CORS on the asset host also repairs existing recordings whose assets are still online, because the player fetches them again.
Docs: https://posthog.com/docs/session-replay/troubleshooting#ensure-your-website-permits-posthog-cors and https://posthog.com/docs/session-replay/troubleshooting#adjust-the-crossorigin-attribute-on-stylesheets

## A region is an empty box

**Symptom:** a blank rectangle the size of an element, or an element that is missing.

**Evidence:** `blocked_placeholders` lists the element, with its class and `rr_width`/`rr_height`.
The class is usually `ph-no-capture`, or matches `blockClass` / `blockSelector` in `$session_options` or `$posthog_config`.

**Fix:** this is privacy blocking working as configured. Remove the class or narrow the selector if the content is safe to record.
`ph-no-capture` blocks the element for every PostHog instance on the page.
To hide text but keep layout, use masking (`ph-mask`, `maskTextSelector`) instead of blocking.
Docs: https://posthog.com/docs/session-replay/privacy

## Iframe or embedded widget does not show

**Symptom:** an empty frame where a booking widget, payment form, embedded app, or chat sits.

**Evidence:** an entry in `iframes` with `content_captured: false`.
Check `recordCrossOriginIframes` in `$session_options.payload.sessionRecordingOptions`.
A frame on another origin played as a separate window shows up as a second `windowId` with its own Meta `href`.

**Fix:**

- Same-origin iframes record with no extra option when posthog-js is on the parent page and in the iframe.
- Cross-origin iframes need posthog-js loaded inside the iframe, and `session_recording: { recordCrossOriginIframes: true }` in **both** the parent and the child config. Both domains must be authorized in the project, and the CSP must allow the framing.
- Third-party widgets (scheduling, payments, chat) cannot be recorded, because the customer cannot add posthog-js inside them. Track their events instead.
- posthog-js 1.417.1 had a regression that stopped recording in cross-origin children. Upgrade both frames to 1.433.4 or later.

Docs: https://posthog.com/docs/session-replay/iframes

## Video is blank, or replay plays audio

**Symptom:** a `<video>` shows nothing, shows browser controls that the real site hides, or the viewer hears the page's audio.

**Evidence:** `media` lists the nodes and their `src`. `media_interaction_events` counts play and pause events.

The recorder does not capture video pixels.
The player re-creates the `<video>` or `<audio>` element with the same `src`, and the viewer's browser loads it.

| Cause                                                                                            | Fix                                                                                            |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Signed or expiring URL (`Expires=`, `Signature=`, `Key-Pair-Id=`, `X-Amz-Expires` in the `src`). | None for old recordings. Longer-lived URLs help future ones.                                   |
| Media behind auth or CORS.                                                                       | Allow the PostHog app origin on the media host.                                                |
| `blob:` or `MediaSource` URL.                                                                    | Not replayable. The blob only existed in the user's tab.                                       |
| The viewer hears audio.                                                                          | Block the element: `ph-no-capture`, or `session_recording: { blockSelector: 'audio, video' }`. |

## Something from a browser extension covers the page

**Symptom:** a popup, toolbar, or list that the real app does not have, often covering the content. The cursor moves over it.

**Evidence:** `extension_refs` is not empty, or nodes appended to `<body>` or `<html>` that the site does not own (translation lists, password-manager icons, ad-blocker overlays).
The CSS that hides them lives in the extension and is not recorded, so they show in replay.
The `chrome-extension-stripped` custom event means the player already removed known extensions.

**Fix:** none on the customer side. Tell the user it is the end user's extension, not their app.
If it hides the app in many recordings, report it to PostHog support so the player can strip it.

## Element looks frozen or out of date

**Symptom:** an animation or progress bar stops, or an element keeps an old state.

**Evidence:** console entries starting with `[SessionRecording] Too many mutations on node`.
The recorder rate limits attribute changes per node (for example, SVG animations that update every frame) and drops the extra ones.
Also `[SessionRecording] Dropped an oversized DOM mutation`, after which the recording resyncs with a full snapshot.

**Fix:** avoid per-frame style updates on DOM elements, or block the animated element.
Docs: https://posthog.com/docs/session-replay/troubleshooting#element-looks-frozen-because-of-rapid-dom-changes

## Overlapping or duplicated DOM

**Symptom:** two versions of a section drawn on top of each other, or content that never existed on the real page.

**Evidence:** mutations that reference parent ids not in any earlier full snapshot or add, often after a large subtree swap. CSP violation messages in the console stream can be a hint.

**Cause:** the recorder missed some mutations. That stretch cannot be recovered.
Ask for the SDK version and recommend the current posthog-js. Report the private link if it happens on a current version.

## URL in the player does not change during the session

**Symptom:** the player's URL bar shows the landing page for the whole session of a single-page app.

**Evidence:** no `$pageview` or `$url_changed` custom events after the first one. `$posthog_config.payload.config.capture_pageview` is `false`, or `defaults` is old or unset.

**Fix:** `capture_pageview: 'history_change'`, or a current `defaults` date in `posthog.init`.
Docs: https://posthog.com/tutorials/single-page-app-pageviews

## Player bugs

The data is fine and the player draws it wrong.
PostHog fixes these, and the fixes repair existing recordings.
Do not send the customer to change their SDK for these.

Signs:

- Renders correctly in one browser and wrong in another (Safari is the usual outlier). Seeking to a time and playing through to it give different results.
- Shadow DOM components lose their styles, so they look like a mobile layout: an AdoptedStyleSheet event (source 15) arrives a few ms after a full snapshot, for a node with `isShadowHost`.
- No cursor, although MouseMove (source 1) and MouseInteraction (source 2) events exist.
- Playback glitches only at high speed.
- MP4 export looks unstyled while the in-app player is fine.

Ask the user to report it with the private replay link and the player time. Public share links do not carry the debug data.
