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
- `$recording_status` — SDK state on that one event: `active`, `buffering`, `lazy_loading`,
  `awaiting_config` (older SDKs: `pending_config`), `missing_config`, `rrweb_error`, `disabled`
- `$session_recording_start_reason` — why recording started or didn't (there is no `$recording_reason`)
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

`$recording_status` is a per-event snapshot, not a verdict on the session.
posthog-js reports `disabled` from SDK init until the lazily loaded recorder takes over,
so the first events of every page load say `disabled` on a session that records fine.
Read the whole session, never one row:

```sql
posthog:execute-sql
SELECT
    arraySort(groupUniqArray(properties.$recording_status)) AS all_recording_statuses,
    argMax(properties.$recording_status, timestamp) AS latest_recording_status,
    argMax(properties.$has_recording, timestamp) AS has_recording,
    argMax(properties.$session_recording_start_reason, timestamp) AS start_reason,
    argMax(properties.$session_recording_remote_config, timestamp) AS remote_config,
    max(properties.$sdk_debug_recording_script_not_loaded) AS script_not_loaded,
    argMax(properties.$sdk_debug_replay_url_trigger_status, timestamp) AS url_trigger,
    argMax(properties.$sdk_debug_replay_event_trigger_status, timestamp) AS event_trigger,
    argMax(properties.$sdk_debug_replay_linked_flag_trigger_status, timestamp) AS flag_trigger,
    argMax(properties.$replay_sample_rate, timestamp) AS sample_rate,
    max(properties.$sdk_debug_replay_internal_buffer_length) AS max_buffer_length,
    max(properties.$sdk_debug_replay_flushed_size) AS max_flushed_size,
    argMax(properties.$lib, timestamp) AS sdk_library,
    argMax(properties.$lib_version, timestamp) AS sdk_version
FROM events
WHERE $session_id = '<session_id>'
```

Read `all_recording_statuses` first. `['disabled']` alone is the only shape that can mean
replay is off. Anything else in the array means the recorder got further than a `disabled`
snapshot shows.

### Step 3 — Diagnose the verdict

Use the [diagnosis logic reference](./references/diagnosis-logic.md) to interpret the signals.
The verdicts in priority order:

1. **Recording exists** (`$has_recording = true`) — recording is captured, issue is elsewhere
2. **Ad blocked (script)** (`$sdk_debug_recording_script_not_loaded = true`) — browser extension blocking the recorder script from loading
3. **Recorder error** (`rrweb_error` in the statuses, or `$sdk_debug_replay_rrweb_error` set) — the recorder started and threw
4. **Config pending** (`awaiting_config` / `pending_config` / `missing_config`) — the SDK is waiting for, or failed to load, replay config
5. **Disabled** (`$session_recording_remote_config.enabled = false`) — PostHog returned replay as off. This, not the status string, is the proof. It does not say why: project settings or a recordings quota limit both produce it
6. **URL blocked** (`paused` in the statuses) — the page URL is on the project's blocked URLs list, so recording is suppressed there
7. **Trigger pending** (trigger statuses are `trigger_pending`, none matched) — recording gated on trigger that never fired
8. **Sampled out** — excluded by sample rate. posthog-js writes no start reason when sampling drops a session, so there is no `sampled_out` value to match on. Read it from the recording config the project runs. On trigger groups (V2), `$sdk_debug_replay_matched_recording_trigger_groups` lists each matched group with the sampling decision made for it, so every entry `matched: true, sampled: false` is a definite sampled-out session. Otherwise a dropped session looks like `disabled` with a `$replay_sample_rate` below 1 and no start reason, which lands on **Recorder not started** below with sampling named as a likely cause
9. **Recorder loading** (`lazy_loading` is the furthest status the session reached) — the session ended before the recorder file took over
10. **Buffering empty** (`buffering`, buffer length = 0, nothing flushed) — initialized but no snapshots produced
11. **Recorder not started** (`disabled` is the only status the session reported, and remote config does not say replay is off) — cause is on the page: `disable_session_recording`, an opt-out, or a blocked recorder file
12. **Flush blocked** (buffer length climbs across events while `flushed_size` stays at 0) — snapshots are produced but the `/s/` ingestion endpoint is blocked by an ad blocker or misconfigured reverse proxy. Detecting this requires querying the trend across the session's events — see [example 4 in examples.md](./references/examples.md)
13. **Unknown** — signals don't match a known pattern

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

- All `disabled` **and** remote config reports `enabled: false` → replay is turned off in project settings
- All `disabled` while remote config reports `enabled: true` → the SDK never started the recorder. Look at the page setup, not project settings
- A healthy project shows plenty of `disabled` and `lazy_loading` next to `active`. That mix is the normal shape of a page load, not a fault
- All `disabled` with a low `$replay_sample_rate` and no start reason → sampling is the likely cause, and the sample rate is too aggressive
- Matched trigger groups that all report `sampled: false` → the trigger matched and the group's own sample rate dropped the session
- All `script_not_loaded` → likely a CSP or deployment issue, not just one user's ad blocker

### Step 5 — Provide actionable recommendations

Based on the verdict, recommend specific actions:

| Verdict              | Recommendation                                                                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Ad blocked           | User's browser extension is blocking rrweb. Suggest trying without ad blocker, or using a proxy/custom domain for the recorder script |
| Recorder error       | Report the rrweb error. Ask for the SDK version and the page it happened on                                                           |
| Config pending       | The SDK could not get replay config in time. Check for anything blocking the PostHog config request, including a reverse proxy        |
| Disabled             | PostHog returned replay as off. Check Settings > Session replay first, then billing for a recordings quota limit                      |
| URL blocked          | The page URL is on the blocked URLs list. Review the blocked URLs in Settings > Session replay                                        |
| Trigger pending      | The configured trigger (URL pattern, event, or feature flag) never matched. Review trigger configuration                              |
| Sampled out          | Increase the sample rate in project settings, or use a trigger to guarantee capture for important sessions. Confirm with `$replay_sample_rate`, or with a `sampled: false` entry in `$sdk_debug_replay_matched_recording_trigger_groups` on trigger groups, since the SDK writes no start reason for a dropped session |
| Recorder loading     | The session ended before the recorder file took over. Expected on very short visits. Nothing to change unless it is the common case   |
| Buffering empty      | Page closed before first snapshot. Common with very short sessions or single-page navigations. Consider lowering minimum duration     |
| Recorder not started | Check `disable_session_recording`, opt-out state, and anything blocking the recorder file on the page                                 |
| Unknown              | Direct user to troubleshooting docs: https://posthog.com/docs/session-replay/troubleshooting                                          |

## Examples

See [real-world diagnostic examples](./references/examples.md) showing how signal combinations
map to verdicts. Use these to calibrate your interpretation of query results.

## Tips

- Never report a single event's `$recording_status` as the session's verdict. Report the whole array.
- If `$lib_version` is very old, some diagnostic signals won't be present.
  Note this to the user — upgrading the SDK will provide better diagnostics.
- A session might have events but no recording if the recording was deleted due to retention.
  Check the session's timestamp against the project's retention period.
- If `$has_recording` is true but the user can't find it, check if it's filtered out
  by duration, activity threshold, or playlist filters.

## Related skills

- **`diagnosing-sdk-health`** — an outdated SDK is a common root cause and blunts the diagnostic signals
- **`finding-sessions-to-watch`** — once capture works, pick the sessions worth watching
- **`investigating-replay`** — analyze the recording once it exists
