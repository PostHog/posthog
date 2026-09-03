# Session replay diagnostic signals

These properties are emitted by the PostHog SDK on every event when session replay is configured.
They describe the recording state at the time the event was captured.

**Important:**
Not all SDKs emit all of these properties.
A missing property is not an error, it may simply mean the SDK version is older
or the property isn't relevant on that platform.
Treat `null`/missing values as "unknown", not "false".
This skill works best with the current Posthog-JS SDK.
New diagnostic properties may be added as the SDK evolves.

## Core signals

| Property                          | Type    | Description                                                        |
| --------------------------------- | ------- | ------------------------------------------------------------------ |
| `$has_recording`                  | boolean | Whether PostHog has a stored recording linked to this session      |
| `$recording_status`               | string  | Current SDK recording state                                        |
| `$session_recording_start_reason` | string  | Why recording started (or didn't). There is no `$recording_reason` |

### `$recording_status` values

This is the SDK state at the moment one event was captured, not a verdict on the session.

| Value             | Meaning                                                                                                    |
| ----------------- | ---------------------------------------------------------------------------------------------------------- |
| `active`          | SDK is recording and producing snapshots                                                                   |
| `sampled`         | The session was sampled in for recording                                                                   |
| `paused`          | Recording is suppressed because the page URL is on the project's blocked list                              |
| `buffering`       | SDK initialized but waiting for a trigger, duration threshold, or remote config before producing snapshots |
| `lazy_loading`    | SDK is loading the recorder file. Recording starts once that file takes over                               |
| `awaiting_config` | SDK asked PostHog for fresh replay config and is waiting for it                                            |
| `pending_config`  | Older SDKs' name for `awaiting_config`                                                                     |
| `missing_config`  | The config request failed. Recording stays off until the page reloads                                      |
| `rrweb_error`     | The recorder started and reported an error                                                                 |
| `disabled`        | The recorder is not running. Also the SDK's value before the recorder loads                                |

**`disabled` is the SDK's initial value.** posthog-js reports it from init until the lazily
loaded recorder takes over, so the first events of every page load carry it, and a healthy
project emits it in volume. Read it as "replay is off" only when the session reported
nothing else and `$session_recording_remote_config.enabled` is `false`.

`sampled` and `paused` are not the same signal as `$session_recording_start_reason`. A session
excluded by sampling reports `disabled` as its status and writes no start reason at all. The
status `sampled` means the opposite: the session was sampled in.

### `$session_recording_start_reason` values

Every value describes recording *starting*. The SDK writes this property from one place, which
also fires `$recording_started`, so it can never describe a session that did not record.

| Value                    | Meaning                                                            |
| ------------------------ | ------------------------------------------------------------------ |
| `recording_initialized`  | Recording started as soon as the SDK initialized                   |
| `session_id_changed`     | Recording restarted because the session ID changed                 |
| `sampled`                | Recording started because sampling included this session           |
| `sampling_overridden`    | Recording started because sampling was overridden                  |
| `linked_flag_matched`    | Recording started because a linked feature flag matched            |
| `linked_flag_overridden` | Recording started because the linked flag requirement was overridden |

There is no `sampled_out` value. When sampling drops a session the SDK only logs a console
warning: it writes no start reason, and the status stays `disabled`. So a sampled-out session
is not distinguishable here from one where the recorder never started. Use `$replay_sample_rate`
to judge how likely sampling is.

## Trigger signals

These indicate whether configured recording triggers have fired.

| Property                                       | Type   | Description                      |
| ---------------------------------------------- | ------ | -------------------------------- |
| `$sdk_debug_replay_url_trigger_status`         | string | URL-based trigger state          |
| `$sdk_debug_replay_event_trigger_status`       | string | Event-based trigger state        |
| `$sdk_debug_replay_linked_flag_trigger_status` | string | Feature flag-based trigger state |

### Trigger status values

| Value              | Meaning                                                         |
| ------------------ | --------------------------------------------------------------- |
| `trigger_disabled` | No trigger of this type is configured                           |
| `trigger_pending`  | A trigger is configured but has not yet matched on this session |
| `trigger_matched`  | The trigger fired — recording was allowed to start              |

## Buffer and flush signals

| Property                                   | Type   | Description                             |
| ------------------------------------------ | ------ | --------------------------------------- |
| `$sdk_debug_replay_internal_buffer_length` | number | Number of events in the internal buffer |
| `$sdk_debug_replay_internal_buffer_size`   | number | Size of the internal buffer in bytes    |
| `$sdk_debug_replay_flushed_size`           | number | Total bytes flushed to PostHog so far   |

## Script loading

| Property                                 | Type    | Description                                                                       |
| ---------------------------------------- | ------- | --------------------------------------------------------------------------------- |
| `$sdk_debug_recording_script_not_loaded` | boolean | The recorder script (rrweb) was not loaded — usually caused by ad blockers or CSP |

## Configuration signals

| Property                                           | Type   | Description                                                                                                          |
| -------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------- |
| `$replay_sample_rate`                              | number | The sample rate configured at the time (0.0 to 1.0)                                                                  |
| `$replay_minimum_duration`                         | number | Minimum session duration (ms) before recording is persisted                                                          |
| `$session_recording_remote_config`                 | object | Remote configuration received from PostHog. Its `enabled` field is the proof of whether replay is on for the project |
| `$sdk_debug_replay_remote_trigger_matching_config` | object | Trigger matching configuration from remote config                                                                    |

## SDK metadata

| Property                   | Type   | Description                                                      |
| -------------------------- | ------ | ---------------------------------------------------------------- |
| `$lib`                     | string | SDK library name (e.g., `web`, `posthog-js`)                     |
| `$lib_version`             | string | SDK version (older versions may not emit all diagnostic signals) |
| `$sdk_debug_session_start` | string | When the SDK session started                                     |
