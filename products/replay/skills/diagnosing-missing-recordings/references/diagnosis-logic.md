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
  → AD_BLOCKED: recorder script failed to load (ad blocker, CSP, network error)

$recording_status == 'disabled' AND recording works on some hosts but not others?
  → DOMAIN_NOT_AUTHORIZED: the host is missing from the authorized domains list

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
- Network-level blocking (Pi-hole, corporate proxies)

### DOMAIN_NOT_AUTHORIZED

A project can list authorized domains for session replay.
When that list is not empty, PostHog only sends a replay config to requests whose
`Origin` or `Referer` is on the list. On every other host the SDK reports
`$recording_status = 'disabled'`, events keep flowing as usual, and no recording is made.

This looks the same as replay being turned off, so tell them apart by host:
a project-wide "off" switch disables every host, an authorized domains list disables
only the hosts that are missing from it.

```sql
posthog:execute-sql
SELECT
    properties.$host AS host,
    properties.$recording_status AS recording_status,
    count() AS events
FROM events
WHERE timestamp > now() - INTERVAL 1 DAY
GROUP BY host, recording_status
ORDER BY host, events DESC
```

Mixed statuses across hosts point at the allowlist. Read the list in
Settings > Session replay > Authorized domains, and compare it against the hosts that
report `disabled`. The `/flags` and `/config` responses also carry
`sessionRecordingDisabledReason: "domain_not_allowed"` when this is the cause.

Note the list holds domains, not URLs, and it accepts wildcards such as
`https://*.example.com`. A bare `https://example.com` entry does not cover its subdomains.

To fix it, add the missing domain to the list, or empty the list to authorize every domain.

### DISABLED

Recording is explicitly turned off. Check:

- Project settings (Settings > Session replay)
- SDK initialization config (`session_recording: { enabled: false }`)
- Runtime SDK calls (`posthog.set_config({ disable_session_recording: true })`)

If only some hosts are affected, read DOMAIN_NOT_AUTHORIZED above first.

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
- Reverse proxy not forwarding `/s/` correctly on self-hosted setups
- Custom domain mismatch between recorder script and capture endpoint

### UNKNOWN

The available signals don't match any known failure pattern.
This can happen when:

- SDK version is too old to emit diagnostic signals
- Event properties were stripped or modified
- An unusual SDK configuration is in use

Direct the user to the troubleshooting docs for manual investigation.
