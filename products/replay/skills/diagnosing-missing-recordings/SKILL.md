---
name: diagnosing-missing-recordings
description: >
  Diagnoses why a session recording is missing or was not captured.
  Use when a user asks why a session has no replay, why recordings aren't appearing,
  or wants to troubleshoot session replay capture issues for a specific session ID
  or across their project. Covers SDK diagnostic signals, project settings,
  sampling, triggers, ad blockers, and quota/billing scenarios.
---

# Diagnosing missing session recordings

When a user asks "why wasn't this session recorded?" or "why don't I have any recordings?",
follow this workflow to systematically diagnose the cause.

## Available tools

| Tool                                    | Purpose                                               |
| --------------------------------------- | ----------------------------------------------------- |
| `posthog:execute-sql`                   | Query session event properties for diagnostic signals |
| `posthog:session-recording-get`         | Check if a recording actually exists for the session  |
| `posthog:query-session-recordings-list` | Search for recordings matching criteria               |

## Diagnostic signals

The PostHog SDK emits diagnostic properties on every event that explain the recording state.
See the [diagnostic signals reference](./references/diagnostic-signals.md) for the full list.

The key signals are:

- `$has_recording` — whether PostHog has a stored recording for this session
- `$recording_status` — SDK state: `active`, `buffering`, `disabled`, `sampled`, `paused`
- `$session_recording_start_reason` — why recording started or didn't
- `$sdk_debug_recording_script_not_loaded` — recorder script blocked (ad blocker)
- `$sdk_debug_replay_*_trigger_status` — trigger states (URL, event, linked flag)
- `$replay_sample_rate` — configured sample rate at capture time

## Workflow

### Step 1 — Check if the recording exists

If the user provides a session ID, first check whether a recording actually exists:

```json
posthog:session-recording-get
{
  "id": "<session_id>"
}
```

If this returns data, the recording exists — the issue is likely UI/filtering, not capture.
If it returns 404, proceed to diagnose why.

### Step 2 — Query diagnostic signals from events

Query the most recent event for the session to get SDK diagnostic properties:

```sql
posthog:execute-sql
SELECT
    properties.$has_recording AS has_recording,
    properties.$recording_status AS recording_status,
    properties.$session_recording_start_reason AS start_reason,
    properties.$sdk_debug_recording_script_not_loaded AS script_not_loaded,
    properties.$sdk_debug_replay_url_trigger_status AS url_trigger,
    properties.$sdk_debug_replay_event_trigger_status AS event_trigger,
    properties.$sdk_debug_replay_linked_flag_trigger_status AS flag_trigger,
    properties.$replay_sample_rate AS sample_rate,
    properties.$sdk_debug_replay_internal_buffer_length AS buffer_length,
    properties.$sdk_debug_replay_flushed_size AS flushed_size,
    properties.$lib AS sdk_library,
    properties.$lib_version AS sdk_version
FROM events
WHERE $session_id = '<session_id>'
ORDER BY timestamp DESC
LIMIT 1
```

### Step 3 — Diagnose the verdict

Use the [diagnosis logic reference](./references/diagnosis-logic.md) to interpret the signals.
The verdicts in priority order:

1. **Recording exists** (`$has_recording = true`) — recording is captured, issue is elsewhere
2. **Ad blocked (script)** (`$sdk_debug_recording_script_not_loaded = true`) — browser extension blocking the recorder script from loading
3. **Disabled** (`$recording_status = 'disabled'`) — replay turned off in settings or SDK config
4. **Trigger pending** (trigger statuses are `trigger_pending`, none matched) — recording gated on trigger that never fired
5. **Sampled out** (`$session_recording_start_reason = 'sampled_out'`) — excluded by sample rate
6. **Buffering empty** (`$recording_status = 'buffering'`, buffer length = 0, nothing flushed) — initialized but no snapshots produced
7. **Flush blocked** (buffer length climbs across events while `flushed_size` stays at 0) — snapshots are produced but the `/s/` ingestion endpoint is blocked by an ad blocker or misconfigured reverse proxy. Detecting this requires querying the trend across the session's events — see [example 3 in examples.md](./references/examples.md)
8. **Unknown** — signals don't match a known pattern

### Step 4 — Check project-level settings (if no session ID)

When the user asks about recordings missing project-wide (no specific session),
query for recent sessions to check the pattern:

```sql
posthog:execute-sql
SELECT
    $session_id,
    properties.$recording_status AS recording_status,
    properties.$session_recording_start_reason AS start_reason,
    properties.$sdk_debug_recording_script_not_loaded AS script_not_loaded,
    properties.$replay_sample_rate AS sample_rate
FROM events
WHERE event = '$pageview'
    AND timestamp > now() - INTERVAL 1 DAY
GROUP BY
    $session_id,
    recording_status,
    start_reason,
    script_not_loaded,
    sample_rate
ORDER BY max(timestamp) DESC
LIMIT 10
```

Look for patterns:

- All `disabled` → replay is turned off in project settings
- All `sampled_out` with low sample rate → sample rate too aggressive
- All `script_not_loaded` → likely a CSP or deployment issue, not just one user's ad blocker
- Mix of statuses → per-session issue, dig into specifics

### Step 5 — Provide actionable recommendations

Based on the verdict, recommend specific actions:

| Verdict         | Recommendation                                                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Ad blocked      | User's browser extension is blocking rrweb. Suggest trying without ad blocker, or using a proxy/custom domain for the recorder script |
| Disabled        | Check project replay settings — recording may be turned off. Link to Settings > Session replay                                        |
| Trigger pending | The configured trigger (URL pattern, event, or feature flag) never matched. Review trigger configuration                              |
| Sampled out     | Increase the sample rate in project settings, or use a trigger to guarantee capture for important sessions                            |
| Buffering empty | Page closed before first snapshot. Common with very short sessions or single-page navigations. Consider lowering minimum duration     |
| Unknown         | Direct user to troubleshooting docs: https://posthog.com/docs/session-replay/troubleshooting                                          |

## Examples

See [real-world diagnostic examples](./references/examples.md) showing how signal combinations
map to verdicts. Use these to calibrate your interpretation of query results.

## Tips

- If `$lib_version` is very old, some diagnostic signals won't be present.
  Note this to the user — upgrading the SDK will provide better diagnostics.
- A session might have events but no recording if the recording was deleted due to retention.
  Check the session's timestamp against the project's retention period.
- If `$has_recording` is true but the user can't find it, check if it's filtered out
  by duration, activity threshold, or playlist filters.
