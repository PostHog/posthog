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

| Property                          | Type    | Description                                                   |
| --------------------------------- | ------- | ------------------------------------------------------------- |
| `$has_recording`                  | boolean | Whether PostHog has a stored recording linked to this session |
| `$recording_status`               | string  | Current SDK recording state                                   |
| `$session_recording_start_reason` | string  | Why recording started (or didn't)                             |

### `$recording_status` values

| Value       | Meaning                                                                                                    |
| ----------- | ---------------------------------------------------------------------------------------------------------- |
| `active`    | SDK is recording and producing snapshots                                                                   |
| `buffering` | SDK initialized but waiting for a trigger, duration threshold, or remote config before producing snapshots |
| `disabled`  | Recording is turned off — either in project settings or via SDK config at runtime                          |
| `sampled`   | This session was included by the configured replay sample rate — recording started                         |
| `paused`    | Recording is temporarily paused for this session                                                           |

### `$session_recording_start_reason` values

| Value                   | Meaning                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| `recording_initialized` | Recording started as soon as the SDK initialized                         |
| `sampling_override`     | Recording started because the session was included by the sampling rules |
| `sampled_out`           | Recording was prevented because the session was excluded by sampling     |
| `linked_flag_match`     | Recording started because a linked feature flag matched                  |

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

| Property                                           | Type   | Description                                                 |
| -------------------------------------------------- | ------ | ----------------------------------------------------------- |
| `$replay_sample_rate`                              | number | The sample rate configured at the time (0.0 to 1.0)         |
| `$replay_minimum_duration`                         | number | Minimum session duration (ms) before recording is persisted |
| `$session_recording_remote_config`                 | object | Remote configuration received from PostHog                  |
| `$sdk_debug_replay_remote_trigger_matching_config` | object | Trigger matching configuration from remote config           |

## SDK metadata

| Property                   | Type   | Description                                                      |
| -------------------------- | ------ | ---------------------------------------------------------------- |
| `$lib`                     | string | SDK library name (e.g., `web`, `posthog-js`)                     |
| `$lib_version`             | string | SDK version (older versions may not emit all diagnostic signals) |
| `$sdk_debug_session_start` | string | When the SDK session started                                     |
