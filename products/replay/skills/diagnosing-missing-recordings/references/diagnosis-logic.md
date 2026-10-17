# Diagnosis logic

This describes the priority-ordered logic for interpreting diagnostic signals.
Evaluate conditions top-to-bottom - the first match is the verdict.

## Contents

- Decision tree
- Verdict descriptions

## Decision tree

```text
$has_recording == true?
  → CAPTURED: recording exists, issue is elsewhere (UI filtering, still processing)

$sdk_debug_recording_script_not_loaded == true?
  → AD_BLOCKED: recorder script failed to load (ad blocker, CSP, reverse proxy, firewall)

$recording_status == 'disabled'?
  → DISABLED: replay turned off in project settings or SDK config

Any trigger status is 'trigger_pending' AND none is 'trigger_matched'?
  → TRIGGER_PENDING: recording gated on trigger that never fired

$session_recording_start_reason == 'sampled_out'?
  → SAMPLED_OUT: excluded by configured sample rate

$recording_status == 'buffering' AND buffer_length == 0 AND flushed_size == 0 (or null)?
  → BUFFERING_EMPTY: SDK initialized but produced no snapshots

$recording_status == 'sampled' OR ($recording_status == 'active' AND flushed_size > 0)?
  → CAPTURED: SDK was actively recording and flushed data (recording should exist, may be processing or deleted by retention)

$recording_status == 'paused'?
  → PAUSED: recording is temporarily paused for this session

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
- Network-level blocking (Pi-hole, corporate proxies, firewalls)
- A custom reverse proxy that does not forward `/static/*`

When `api_host` is a custom reverse proxy, the SDK loads the recorder script from `api_host` + `/static/*`, unless `asset_host` overrides it.
A proxy that forwards only the event paths stops the recorder script, but event capture keeps working.
If events arrive and recordings do not, suspect the proxy before an ad blocker.
Fixes:

- Forward `/static/*` through the proxy, unless `asset_host` is set.
  Replay also needs `/array/*` (remote config) and `/s/` (snapshots, see FLUSH_BLOCKED) on the same proxy
- Set `asset_host` in the SDK config to load scripts from a host that the firewall allows
- Use the [managed reverse proxy](https://posthog.com/docs/advanced/proxy/managed-reverse-proxy)

### DISABLED

Recording is explicitly turned off. Check:

- Project settings (Settings > Session replay)
- SDK initialization config (`session_recording: { enabled: false }`)
- Runtime SDK calls (`posthog.set_config({ disable_session_recording: true })`)

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

### PAUSED

Recording is temporarily paused for this session.
This can happen when:

- The SDK's `pause()` method was called programmatically
- A consent mechanism paused recording pending user opt-in
- The session exceeded a configured maximum duration

### FLUSH_BLOCKED

The SDK is producing snapshots but they're not reaching PostHog.
Distinct from AD_BLOCKED (which is the script itself failing to load) —
here the script loaded and is working, but the `POST /s/` upload is being blocked.
Detecting this requires looking at the trend of buffer/flush signals across multiple
events in the session (see [example 3 in examples.md](./examples.md)).
Typical causes:

- Ad blocker blocking the ingestion endpoint (different from blocking the script)
- A reverse proxy or firewall that does not forward `/s/`, or that rejects large request bodies.
  This applies to custom reverse proxies on PostHog Cloud as well as to self-hosted setups.
  Forward `/s/` with the event paths and allow large request bodies, or use the managed reverse proxy.
- Custom domain mismatch between recorder script and capture endpoint

### UNKNOWN

The available signals don't match any known failure pattern.
This can happen when:

- SDK version is too old to emit diagnostic signals
- Event properties were stripped or modified
- An unusual SDK configuration is in use

Direct the user to the troubleshooting docs for manual investigation.
