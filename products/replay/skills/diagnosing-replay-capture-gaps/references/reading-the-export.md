# Reading a recording export for capture gaps

The export is JSON: `{version, data: {id, person, snapshots[]}}`.
Each snapshot is an rrweb event with `type`, `timestamp` (ms), `windowId`, and `data`.
`windowId` is a number per browser tab or window, assigned in order of appearance.

| `type` | Name                | Use here                                                       |
| ------ | ------------------- | -------------------------------------------------------------- |
| 2      | FullSnapshot        | The player can only start drawing a window after its first one |
| 3      | IncrementalSnapshot | Changes and interactions                                       |
| 4      | Meta                | One per page load: `data.href`                                 |
| 5      | Custom              | SDK lifecycle and config: `data.tag`, `data.payload`           |
| 6      | Plugin              | `rrweb/console@1`, `rrweb/network@1`                           |

Files can be many MB. Always query with `jq`. Set `F` to the attached file path first.

## Lifecycle custom events

posthog-js writes these. Older versions write fewer of them. Mobile SDKs write none.

| Tag                                      | Payload                                             | Meaning                                                                                                                                                                            |
| ---------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$remote_config_received`                | Project replay settings                             | What the server told the SDK. See the config fields below.                                                                                                                         |
| `$session_options`                       | `sessionRecordingOptions`, `activePlugins`          | The rrweb options the recorder started with.                                                                                                                                       |
| `$posthog_config`                        | `config`                                            | The `posthog.init` config.                                                                                                                                                         |
| `$recording_started`                     | `reason`                                            | Why recording started: `recording_initialized`, `sampled`, `url_trigger_matched`, `event_trigger_matched`, `linked_flag_matched`, `sampling_overridden`, `linked_flag_overridden`. |
| `triggerGroupSamplingDecisionMade`       | `group_id`, `group_name`, `sampleRate`, `isSampled` | A trigger group made its sampling decision for this session.                                                                                                                       |
| `recording paused` / `recording resumed` | `reason: 'url blocker'` / `'left blocked url'`      | The URL blocklist matched. Nothing is recorded in between. Expected.                                                                                                               |
| `sessionIdle` / `sessionNoLongerIdle`    | `threshold`, `lastActivityTimestamp`                | No user activity for the idle threshold. No full snapshots while idle. Expected gap.                                                                                               |
| `window hidden` / `window visible`       |                                                     | The tab lost or regained visibility. Expected gap.                                                                                                                                 |
| `browser offline` / `browser online`     |                                                     | Network loss. Data buffered offline is lost if the tab closes first.                                                                                                               |
| `$session_id_change`                     | `sessionId`, `windowId`, `changeReason`             | The session rotated. `changeReason` has `activityTimeout`, `sessionPastMaximumLength`, `noSessionId` (a reset), `crossTabAdoption`.                                                |
| `$session_ending` / `$session_starting`  | `nextSessionId` / `previousSessionId`               | Links this recording to the one before or after it.                                                                                                                                |
| `$pageview`, `$url_changed`              | `href`                                              | Route changes inside a single-page app.                                                                                                                                            |

The recorder also writes warnings into the console stream with the prefix `[SessionRecording]`.

### Config fields in `$remote_config_received`

| Field                                        | Meaning                                                                             |
| -------------------------------------------- | ----------------------------------------------------------------------------------- |
| `enabled`                                    | Replay is on for the project.                                                       |
| `version`                                    | `2` when the project uses trigger groups, `1` for legacy conditions only.           |
| `triggerGroups`                              | Trigger groups. Each has its own conditions and sample rate.                        |
| `sampleRate`                                 | Share of sessions recorded, as a string such as `"0.10"`. `null` means no sampling. |
| `urlTriggers`, `eventTriggers`, `linkedFlag` | Recording waits until one matches.                                                  |
| `triggerMatchType`                           | `any` or `all`: how the triggers combine.                                           |
| `minimumDurationMilliseconds`                | Sessions shorter than this are not kept.                                            |
| `urlBlocklist`                               | URLs where recording pauses.                                                        |

`sampleRate`, `urlTriggers`, `eventTriggers`, `linkedFlag` and `triggerMatchType` are the legacy conditions.
With `version: 2` and a non-empty `triggerGroups`, a current SDK uses the groups, and the legacy conditions are only a fallback for SDKs too old for trigger groups.
`triggerGroupSamplingDecisionMade` events, or `$sdk_debug_replay_remote_trigger_matching_config = 'v2_trigger_groups'` on events, confirm the SDK used the groups.

## Recipes

### Timeline

Page loads, full snapshots, and SDK custom events, in seconds from the start.
Config events are left out because they are long. Read them with the config recipe.

```sh
jq -r '(.data.snapshots | map(.timestamp) | min) as $s
  | .data.snapshots[]
  | select(.type == 2 or .type == 4 or (.type == 5 and (.data.tag | IN("$posthog_config", "$session_options", "$remote_config_received") | not)))
  | [((.timestamp - $s) / 1000 | floor), .windowId,
     (if .type == 2 then "FULL_SNAPSHOT"
      elif .type == 4 then "PAGE_LOAD " + (.data.href // "")
      else .data.tag + " " + ((.data.payload | tostring) | .[0:160]) end)]
  | @tsv' "$F"
```

### Windows

For each window: when it started, when its first full snapshot arrived, how many it has, when it ended, and its pages.
`first_full_s` well after `first_s` means the start of that window cannot play.
`first_full_s: null` means the window never plays.

```sh
jq -c '(.data.snapshots | map(.timestamp) | min) as $s
  | .data.snapshots | group_by(.windowId) | map({
      window: .[0].windowId,
      first_s: (((map(.timestamp) | min) - $s) / 1000 | floor),
      first_full_s: ([.[] | select(.type == 2) | .timestamp] | if length > 0 then ((min - $s) / 1000 | floor) else null end),
      full_snapshots: ([.[] | select(.type == 2)] | length),
      last_s: (((map(.timestamp) | max) - $s) / 1000 | floor),
      pages: ([.[] | select(.type == 4) | .data.href] | unique)
    })' "$F"
```

### Gaps

Stretches of 30 seconds or more with no data at all. Match each one to the timeline.

```sh
jq -c '(.data.snapshots | map(.timestamp) | min) as $s
  | [.data.snapshots[].timestamp] | sort
  | [range(1; length) as $i | {at_s: ((.[$i - 1] - $s) / 1000 | floor), gap_s: ((.[$i] - .[$i - 1]) / 1000 | floor)}]
  | map(select(.gap_s >= 30))' "$F"
```

### Config

Newer posthog-js writes only the replay settings into `$remote_config_received`.
Older versions write the whole remote config, with the replay settings under `sessionRecording`, which is `false` when replay is off.
The first command handles both.

```sh
jq -c '.data.snapshots[] | select(.type == 5 and .data.tag == "$remote_config_received") | .data.payload
  | (if type == "object" and has("sessionRecording") then .sessionRecording else . end)
  | if type == "object"
    then {version, enabled, sampleRate, minimumDurationMilliseconds, triggerMatchType, urlTriggers, eventTriggers, linkedFlag, triggerGroups, urlBlocklist}
    else {sessionRecording: .} end' "$F"
jq -c '.data.snapshots[] | select(.type == 5 and (.data.tag == "$recording_started" or .data.tag == "triggerGroupSamplingDecisionMade")) | {tag: .data.tag, payload: .data.payload}' "$F"
jq -c '.data.snapshots[] | select(.type == 5 and .data.tag == "$posthog_config") | .data.payload.config
  | {disable_session_recording, opt_out_capturing_by_default, cookieless_mode, api_host, persistence, session_recording}' "$F"
```

If the config events appear more than once, compare them. A change mid-session means a new page load picked up new settings, or the app called `posthog.init` again.

### Requests to PostHog during the recording

Only present when network capture is on.
posthog-js leaves its own `/s/`, `/e/`, and `/i/` requests out of network capture, so recording uploads never appear here.
What does appear: `/flags`, the `config.js` remote config, and the recorder script (`posthog-recorder.js` or `recorder.js`) under the API host, which also shows whether a reverse proxy is in use.

```sh
jq -c '(.data.snapshots | map(.timestamp) | min) as $s | .data.snapshots[] | select(.type == 6 and .data.plugin == "rrweb/network@1") | .timestamp as $ts | .data.payload.requests[]
  | select(.name | test("/flags/|/decide/|/config\\.js|recorder(-v2)?\\.js|posthog-recorder\\.js"))
  | {t: ((($ts - $s) / 1000) | floor), status: .responseStatus, type: .initiatorType, url: (.name | .[0:160])}' "$F"
```

To check `/s/` itself, ask the user to open the browser network tab on their site with `?__posthog_debug=true` and look at the `/s/` requests.
A capture endpoint answers 200 to every accepted request, because processing is async.
A 200 does not prove the data was stored. A 3xx, 4xx, or failed `/s/` request does prove it was not.
