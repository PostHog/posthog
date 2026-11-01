---
name: diagnosing-replay-rendering
description: >
  Explains why a session recording plays back wrong by reading the recording's
  exported rrweb JSON (`*-ph-recording.json`) and its config events.
  Use when a user debugs one replay and reports a black, white, or grey screen,
  a blank area, missing styles or unstyled pages, a blank canvas, map, WebGL, or
  WebGPU view, an iframe or embedded widget that does not show, a video that is
  blank or plays audio, a layout that looks different from the real app, or a
  mobile replay (Android, iOS, React Native, Flutter) that is black or only shows
  placeholders. Separates causes the customer can fix in SDK config from player
  bugs PostHog must fix. Not for sessions with no recording, or for parts of a
  session that were never captured.
---

# Diagnosing why a replay renders wrong

The user has a recording open and says it does not look like their app.
Your job is to find what in the recorded data explains the difference, and to say who can fix it.

A replay is a rebuilt DOM, not a video.
The player rebuilds the page from snapshots, then the viewer's browser fetches anything that was not inlined.
So every rendering problem sits in one of three places:

1. **Capture**: the SDK did not record the content (canvas off, element blocked, mask, missing full snapshot).
   The customer fixes it in SDK config. Recordings that already exist stay broken.
2. **Playback assets**: the content was recorded as a reference, and the viewer's browser cannot fetch it now (CORS, expired signed URL, auth).
   The customer fixes it on their asset host.
3. **Player**: the data is complete and correct, and the player draws it wrong.
   PostHog fixes it, and the fix repairs existing recordings.

Say which of the three it is.
That is the most useful sentence in your answer.

## Inputs

| Input                                         | What it holds                                                                                 |
| --------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Attached file ending in `-ph-recording.json`  | The full export: every rrweb snapshot, including the DOM. Can be many MB. Query it with `jq`. |
| `session_recording_data` context item         | A compact timeline (pages, console, network, custom events). It has no DOM.                   |
| The user's prompt                             | Usually names the player time, for example "I am 01:23 into the recording". Start there.      |
| `posthog:session-recording-get`               | Metadata, including `snapshot_source` (`web` or `mobile`) and duration.                       |
| `posthog:execute-sql`                         | Events for the session: `$lib`, `$lib_version`, `$browser`, `$os`, `$current_url`.            |
| `posthog:session-recording-console-logs-list` | Console logs, if the export is not attached.                                                  |

Never print the export whole.
If no export file is attached (it is over 30 MB, or the chat cannot take files), say that DOM-level checks are not possible.
Then work from the timeline, the console logs and SQL.

## Workflow

### Step 1: Pin down the symptom

Get from the prompt what looks wrong, where on the screen, and at what player time.
Convert the player time to a timestamp the way the player does.
Player time 0 is the earlier of the recording's `start_time` (from `session-recording-get`) and the first snapshot's `timestamp`.
Add the offset in ms to that. Do not start from the first snapshot alone, because `start_time` can be earlier.
If the prompt does not say what looks wrong, ask once. Do not guess between "black screen" and "missing styles".

### Step 2: Profile the export and find the platform

Run the overview and config recipes in [reading-the-export.md](./references/reading-the-export.md).

- `$session_options` and `$posthog_config` custom events exist: **web** (posthog-js).
- `img` nodes with `data-posthog-screenshot`, no `$session_options`, or `snapshot_source = mobile`: **mobile**.
  The export already holds mobile wireframes converted to HTML, so you read DOM nodes, not raw wireframes.

Get the SDK name and version with SQL. Many causes depend on a minimum SDK version.
Bound the query by the recording's `start_time` and `end_time`, because `$session_id` alone does not limit the partitions it reads:

```sql
SELECT properties.$lib AS lib, properties.$lib_version AS version, properties.$browser AS browser, properties.$os AS os
FROM events
WHERE $session_id = '<session_id>'
    AND timestamp >= toDateTime('<start_time>') - INTERVAL 10 MINUTE
    AND timestamp <= toDateTime('<end_time>') + INTERVAL 10 MINUTE
GROUP BY lib, version, browser, os
```

### Step 3: Inventory what was captured

Run the inventory program in [reading-the-export.md](./references/reading-the-export.md).
It lists stylesheets that were not inlined, blocked placeholders, canvases and canvas frames, iframes and whether their content arrived, media nodes, shadow hosts, and extension-injected nodes.
Then look at the snapshots around the symptom time: the nearest full snapshot before it, and the mutations after it.

### Step 4: Match the evidence to a cause

Use [web-causes.md](./references/web-causes.md) or [mobile-causes.md](./references/mobile-causes.md).
Each cause lists the evidence that proves it.
Accept a cause only when its evidence is in this recording.
If two causes fit, say so and say which check would separate them.

Check these first. They explain most tickets:

- Web, blank canvas or map: canvas capture off, or WebGPU.
- Web, unstyled page: a `<link>` stylesheet with no `_cssText`, so the player re-fetches it and CORS blocks it.
- Web, blank region the size of an element: `ph-no-capture` or `blockSelector` (an `rr_width` placeholder).
- Web, iframe empty: cross-origin iframe without posthog-js and `recordCrossOriginIframes` in both frames.
- Mobile, black block over a map or web view: privacy masking by default.
- Mobile, grey boxes and no text: wireframe mode on Jetpack Compose or SwiftUI. Use screenshot mode.
- Mobile, one frame that never changes: no full snapshot or screenshots were captured.

### Step 5: When the data looks right, suspect the player

If the recorded DOM, styles and assets all look complete, it is likely a player bug.
Signs: it renders differently in another browser or when you seek instead of playing through, the cursor is missing although mouse events exist, or a style event arrives a few ms after a full snapshot and is ignored.
Say so plainly. Ask the user to report it to PostHog support with the private replay link (not a public share link) and the player time.
Player fixes repair existing recordings. Recorder fixes do not.

### Step 6: Answer

Lead with the verdict in one sentence: capture, playback assets, or player.
Then give:

1. **What happens**: the symptom, at which player times.
2. **Why**: the cause, with the evidence from this recording (event types, timestamps, node attributes, config values).
3. **Fix**: exact SDK option names and values, the minimum SDK version if one applies, the settings path, and a docs link.
4. **What it does not fix**: whether this recording and others like it stay broken.
5. **Confidence**: say what you could not check (for example, no export attached, or a mobile screenshot you could not decode).

Keep customer values that are not needed out of the answer.
The recording can hold personal data in text, URLs and inputs.

## Related skills

- **`diagnosing-replay-capture-gaps`**: parts of the session were never recorded, or the recording starts late or stops
- **`diagnosing-missing-recordings`**: the session has no recording at all
- **`investigating-replay`**: what the user did in the session, errors, and linked issues
