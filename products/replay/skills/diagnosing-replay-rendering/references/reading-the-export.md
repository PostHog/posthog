# Reading a recording export for rendering problems

The export is JSON with this shape:

```json
{
  "version": "2023-04-28",
  "data": {
    "id": "<session id>",
    "person": { "...": "..." },
    "snapshots": [{ "type": 2, "timestamp": 1790000000000, "windowId": 1, "data": {} }]
  }
}
```

`snapshots` are rrweb events, already processed by the player.
Each has `type`, `timestamp` (ms), `windowId` (one number per browser tab or window), and `data`.
Mobile recordings are already converted to HTML, so you read DOM nodes for them too.

Files can be many MB. Always query with `jq`. Never print the file or a whole full snapshot.

## Event types

| `type` | Name                | What it holds                                           |
| ------ | ------------------- | ------------------------------------------------------- |
| 2      | FullSnapshot        | The whole DOM at one moment, in `data.node`             |
| 3      | IncrementalSnapshot | One change. `data.source` says which kind (table below) |
| 4      | Meta                | Page load: `data.href`, `data.width`, `data.height`     |
| 5      | Custom              | SDK events: `data.tag`, `data.payload`                  |
| 6      | Plugin              | `data.plugin` is `rrweb/console@1` or `rrweb/network@1` |

| `data.source` | Name              | Relevant for                                                  |
| ------------- | ----------------- | ------------------------------------------------------------- |
| 0             | Mutation          | `adds`, `removes`, `texts`, `attributes`. New iframes, modals |
| 1             | MouseMove         | Cursor                                                        |
| 2             | MouseInteraction  | Clicks and touches                                            |
| 3             | Scroll            |                                                               |
| 4             | ViewportResize    | Layout that changes size                                      |
| 7             | MediaInteraction  | Video and audio play, pause, seek                             |
| 8             | StyleSheetRule    | CSS-in-JS rules                                               |
| 9             | CanvasMutation    | Canvas frames. `data.id` is the canvas node id                |
| 13            | StyleDeclaration  |                                                               |
| 15            | AdoptedStyleSheet | Shadow DOM and constructable stylesheets                      |

## Node attributes that matter

A serialized node has `type` (0 document, 2 element, 3 text), `id`, `tagName`, `attributes`, `childNodes`, and sometimes `isShadowHost`.

| Attribute                              | Meaning                                                                                           |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `_cssText` on `<link>`                 | The recorder inlined the stylesheet. Without it, the player re-fetches `href` at playback.        |
| `rr_width`, `rr_height`                | The element was blocked (`ph-no-capture`, `blockClass`, `blockSelector`). Played as an empty box. |
| `rr_dataURL` on `<canvas>`             | A canvas frame captured in the full snapshot.                                                     |
| `rr_mediaState`, `rr_mediaCurrentTime` | Media state. The player re-fetches `src` and plays it in the viewer's browser.                    |
| `data-posthog-screenshot` on `<img>`   | Mobile screenshot mode. The `src` is a PNG data URI of the whole screen.                          |

## Custom events from posthog-js

Mobile SDKs do not write these. Their absence on mobile is normal.

| Tag                         | Payload                                                                                                                                              |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$session_options`          | `sessionRecordingOptions` (rrweb options: `recordCanvas`, `recordCrossOriginIframes`, `blockClass`, `inlineStylesheet`, masking) and `activePlugins` |
| `$remote_config_received`   | Project replay settings: `recordCanvas`, `canvasFps`, `canvasQuality`, `masking`, `networkPayloadCapture`                                            |
| `$posthog_config`           | The full `posthog.init` config, in `config`. Look at `config.session_recording`                                                                      |
| `$pageview`, `$url_changed` | Route changes, with `href`                                                                                                                           |
| `chrome-extension-stripped` | Added by the player when it removed known extension nodes from a full snapshot                                                                       |

The recorder writes its own warnings into the console stream with the prefix `[SessionRecording]`.
For example, "Too many mutations on node" means attribute changes on that node were rate limited.

## Recipes

Set `F` to the attached file path first.

### Overview

```sh
jq -c '{
  session: .data.id,
  snapshots: (.data.snapshots | length),
  duration_s: (((.data.snapshots | map(.timestamp) | max) - (.data.snapshots | map(.timestamp) | min)) / 1000 | floor),
  windows: ([.data.snapshots[].windowId] | unique),
  types: ([.data.snapshots[].type] | group_by(.) | map({(.[0] | tostring): length}) | add),
  sources: ([.data.snapshots[] | select(.type == 3) | .data.source] | group_by(.) | map({(.[0] | tostring): length}) | add),
  tags: ([.data.snapshots[] | select(.type == 5) | .data.tag] | group_by(.) | map({(.[0]): length}) | add),
  plugins: ([.data.snapshots[] | select(.type == 6) | .data.plugin] | group_by(.) | map({(.[0]): length}) | add)
}' "$F"
```

### Recorder config

```sh
jq -c '.data.snapshots[] | select(.type == 5 and (.data.tag == "$session_options" or .data.tag == "$remote_config_received")) | {tag: .data.tag, payload: .data.payload}' "$F"
jq -c '.data.snapshots[] | select(.type == 5 and .data.tag == "$posthog_config") | .data.payload.config | {session_recording, capture_pageview, defaults, api_host}' "$F"
```

### Inventory of captured content

Save as `inventory.jq` and run `jq -f inventory.jq "$F"`.
It reads nodes from full snapshots and from mutation adds.

```jq
def nodes: [.data.snapshots[]
  | if .type == 2 then .data.node
    elif .type == 3 and .data.source == 0 then (.data.adds // [])[].node
    else empty end
  | .. | objects | select(has("type") and has("id"))];
def incr($src): [.data.snapshots[] | select(.type == 3 and .data.source == $src)];
(nodes) as $n
| ([.data.snapshots[] | select(.type == 3 and .data.source == 0) | (.data.adds // [])[] | .parentId] | unique) as $mutation_parents
| {
    full_snapshots: [.data.snapshots[] | select(.type == 2)] | length,
    stylesheets_not_inlined: [$n[] | select(.tagName == "link" and (.attributes.rel // "" | test("stylesheet")) and (.attributes._cssText | not)) | .attributes.href] | unique | .[0:10],
    stylesheets_inlined: [$n[] | select(.tagName == "link" and .attributes._cssText)] | length,
    blocked_placeholders: [$n[] | select(.attributes.rr_width) | {tag: .tagName, class: .attributes.class, w: .attributes.rr_width, h: .attributes.rr_height}] | unique | .[0:10],
    canvases: [$n[] | select(.tagName == "canvas") | {id, class: .attributes.class, has_data_url: (.attributes.rr_dataURL != null)}] | unique_by(.id) | .[0:10],
    canvas_ids_with_frames: [incr(9)[] | .data.id] | unique,
    iframes: [$n[] | select(.tagName == "iframe") | {id, src: (.attributes.src // "" | .[0:120]), content_captured: ((.childNodes // [] | length > 0) or (.id as $i | $mutation_parents | index($i) != null))}] | unique_by(.id) | .[0:10],
    media: [$n[] | select(.tagName == "video" or .tagName == "audio") | {tag: .tagName, src: ((.attributes.src // .attributes.rr_src // "") | .[0:160]), state: .attributes.rr_mediaState}] | unique | .[0:10],
    media_interaction_events: incr(7) | length,
    shadow_hosts: [$n[] | select(.isShadowHost) | .tagName] | unique,
    adopted_stylesheet_events: incr(15) | length,
    extension_refs: [$n[] | select((.attributes // {}) | tostring | test("chrome-extension://|moz-extension://|safari-web-extension://")) | .tagName] | unique,
    mobile_screenshots: [$n[] | select(.attributes["data-posthog-screenshot"])] | length,
    images: [$n[] | select(.tagName == "img")] | length,
    text_nodes: [$n[] | select(.type == 3 and ((.textContent // "") | test("\\S")))] | length
  }
```

### What happened around the symptom

Lists events within 5 seconds of a player offset `OFFSET_S`, with times relative to the start.

```sh
jq -c --argjson off "$OFFSET_S" '(.data.snapshots | map(.timestamp) | min) as $s
  | .data.snapshots[]
  | ((.timestamp - $s) / 1000) as $t
  | select($t >= $off - 5 and $t <= $off + 5)
  | {t: ($t * 10 | floor / 10), w: .windowId, type, source: .data.source?, tag: .data.tag?, plugin: .data.plugin?}' "$F"
```

### Find the node with an id

```sh
jq -c --argjson id "$NODE_ID" 'first(.data.snapshots[] | (.data.node?, (.data.adds? // [])[]?.node) | .. | objects | select(.id? == $id)) | {tagName, attributes: (.attributes | with_entries(.value |= (tostring | .[0:200])))}' "$F"
```

### Failed network requests

Only present when network capture is on.
For `fetch` and `xmlhttprequest`, `responseStatus` 0 means the request never got a response.
For other initiator types (`link`, `script`, `img`, `iframe`, `css`), 0 is normal for a cross-origin resource without a `Timing-Allow-Origin` header, so the recipe leaves those out.

```sh
jq -c '(.data.snapshots | map(.timestamp) | min) as $s | .data.snapshots[] | select(.type == 6 and .data.plugin == "rrweb/network@1") | .timestamp as $ts | .data.payload.requests[] | select((.responseStatus // 200) >= 400 or (.responseStatus == 0 and (.initiatorType == "fetch" or .initiatorType == "xmlhttprequest"))) | {t: ((($ts - $s) / 1000) | floor), status: .responseStatus, type: .initiatorType, url: (.name | .[0:160])}' "$F"
```

These are requests the user's browser made while recording.
A stylesheet or image that fails for the viewer at playback does not show up here.

### Look at a mobile screenshot

The `src` of a `data-posthog-screenshot` image is a base64 PNG.
If you can run Python, decode one near the symptom time and look at it, or measure how much of it is solid black.
Masks are painted into the image, so a black block in the PNG is a mask, not missing data.
