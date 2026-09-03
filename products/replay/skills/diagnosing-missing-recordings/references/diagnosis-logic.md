# Diagnosis logic

This describes the priority-ordered logic for interpreting diagnostic signals.
Evaluate conditions top-to-bottom - the first match is the verdict.

Evaluate them against the whole session, not one event. `$recording_status` is a per-event
snapshot: posthog-js reports `disabled` until the lazily loaded recorder takes over, so the
first events of every page load carry it. "In statuses" below means the value appears
anywhere in the session's `groupUniqArray(properties.$recording_status)`.

## Contents

- Decision tree
- Verdict descriptions

## Decision tree

```text
$has_recording == true?
  → CAPTURED: recording exists, issue is elsewhere (UI filtering, still processing)

$sdk_debug_recording_script_not_loaded == true?
  → AD_BLOCKED: recorder script failed to load (ad blocker, CSP, network error)

'rrweb_error' in statuses OR $sdk_debug_replay_rrweb_error is set?
  → RECORDER_ERROR: the recorder started and threw

'missing_config' / 'awaiting_config' / 'pending_config' in statuses?
  → CONFIG_PENDING: the SDK is waiting for, or failed to load, replay config

$session_recording_remote_config.enabled == false?
  → DISABLED: replay turned off for the project

Any trigger status is 'trigger_pending' AND none is 'trigger_matched'?
  → TRIGGER_PENDING: recording gated on trigger that never fired

$session_recording_start_reason == 'sampled_out'?
  → SAMPLED_OUT: excluded by configured sample rate

'lazy_loading' is the furthest status the session reached?
  → RECORDER_LOADING: the session ended before the recorder file took over

'buffering' reached AND buffer_length == 0 AND flushed_size == 0 (or null)?
  → BUFFERING_EMPTY: SDK initialized but produced no snapshots

'disabled' is the ONLY status the session reported?
  → RECORDER_NOT_STARTED: the recorder never ran, and the cause is on the page

$recording_status == 'active' AND flushed_size > 0?
  → CAPTURED: SDK was actively recording and flushed data (recording should exist, may be processing or deleted by retention)

Buffer length climbs across the session's events AND flushed_size stays at 0?
  → FLUSH_BLOCKED: snapshots produced but ingestion endpoint blocked
  (requires querying the trend across events, not a single row)

None of the above?
  → UNKNOWN: signals don't match a known pattern
```

## Verdict descriptions

### CAPTURED

The recording exists or was captured.
If the user still can't find it:

- It may still be processing (especially if recent)
- It may be filtered out by duration, activity threshold, or playlist filters
- It may have been deleted due to retention policy

### AD_BLOCKED

The rrweb recorder script was blocked from loading.
This is the most common cause of missing recordings for individual users.
Typical causes:

- Browser ad blocker extensions (uBlock Origin, AdBlock Plus, etc.)
- Corporate content security policies (CSP)
- Network-level blocking (Pi-hole, corporate proxies)

### DISABLED

Replay is turned off for the project. `$session_recording_remote_config.enabled` is `false`,
which is the only proof of this. Fix it in Settings > Session replay.

### RECORDER_NOT_STARTED

`disabled` is the only status the session reported, but replay is on for the project (or the
remote config is absent, so nothing proves it is off). The recorder never ran, and the cause
is on the page. Check:

- SDK initialization config (`session_recording: { enabled: false }`)
- Runtime SDK calls (`posthog.set_config({ disable_session_recording: true })`)
- Consent or opt-out state for the visitor
- Anything blocking the recorder file

### RECORDER_LOADING

The recorder file was still loading when the session ended, so no snapshots were captured.
Short visits and slow networks hit this most. It is not a settings problem, and the same
visitor usually records fine on a longer page view. Only worth acting on when it is the
common shape across a project rather than one session.

### CONFIG_PENDING

The SDK asked PostHog for fresh replay config and started recording only once it arrived.
`missing_config` means the request failed and recording stays off until the page reloads.
Check for anything blocking the PostHog config request, including ad blockers, a content
security policy, or a reverse proxy that does not forward it.

### TRIGGER_PENDING

Recording was configured to only start when a trigger fires (URL pattern match, specific event, or feature flag).
The trigger never matched during this session, so no recording was produced.
Review the trigger configuration to ensure it covers the expected pages/events.

### SAMPLED_OUT

The SDK randomly excluded this session based on the configured sample rate.
This is expected behavior — if the sample rate is 50%, roughly half of sessions won't be recorded.
To capture more sessions, increase the sample rate or use triggers for important flows.

### BUFFERING_EMPTY

The SDK initialized in buffering mode but never produced snapshots.
Common causes:

- Very short session (page closed before first snapshot)
- Minimum duration threshold not met
- Page navigated away before buffer was flushed

### FLUSH_BLOCKED

The SDK is producing snapshots but they're not reaching PostHog.
Distinct from AD_BLOCKED (which is the script itself failing to load) —
here the script loaded and is working, but the `POST /s/` upload is being blocked.
Detecting this requires looking at the trend of buffer/flush signals across multiple
events in the session (see [example 4 in examples.md](./examples.md)).
Typical causes:

- Ad blocker blocking the ingestion endpoint (different from blocking the script)
- Reverse proxy not forwarding `/s/` correctly on self-hosted setups
- Custom domain mismatch between recorder script and capture endpoint

### UNKNOWN

The available signals don't match any known failure pattern.
This can happen when:

- SDK version is too old to emit diagnostic signals
- Event properties were stripped or modified
- An unusual SDK configuration is in use

Direct the user to the troubleshooting docs for manual investigation.
