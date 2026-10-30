---
name: diagnosing-replay-capture-gaps
description: >
  Explains why part of a session recording was not captured, and what the
  recording's own config says about why other sessions are not recorded, by
  reading the exported rrweb JSON (`*-ph-recording.json`).
  Use when a user debugs one replay and asks why it starts late, stops early,
  only shows the first or landing page, stops after cookie consent or a page
  navigation, has blank stretches or gaps, is shorter than the real visit, is
  split across sessions, or shows "the first N minutes can't be played". Also
  use when the user asks why recordings stopped or why only some users or pages
  get recorded, and has one recording to start from. Reads sampling, triggers,
  minimum duration, URL blocklist, and init config from the recording.
  For a session with no recording at all, use diagnosing-missing-recordings.
---

# Diagnosing gaps in what a replay captured

The user has one recording open and something is missing: the start, the end, a page, a stretch in the middle, or other sessions that should have been recorded.
The recording itself is the best evidence.
posthog-js writes its config, its start reason, and its lifecycle (pauses, idle, session changes, page loads) into the recording as custom events.

Your job is to separate three things:

1. **Expected gaps**: the SDK did what it was configured to do (sampling, triggers, URL blocklist, idle, hidden tab, minimum duration).
2. **Lost data**: the SDK recorded, but data did not reach PostHog (tab closed before upload, blocked `/s/` requests, a proxy that breaks `/s/`, billing limits).
3. **Not recorded at all**: the SDK never ran or never started on those pages (a second app with replay off, recorder script blocked, init removed).

Name which one it is, and back it with timestamps from this recording.

## Inputs

| Input                                        | What it holds                                                                                              |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Attached file ending in `-ph-recording.json` | The full export, with every custom event and snapshot. Query it with `jq`. Never print it whole.           |
| `session_recording_data` context item        | A compact timeline: page loads, console, network, custom events. Use it when no file is attached.          |
| `posthog:execute-sql`                        | The session's events and SDK diagnostic properties. Shows pages the user visited that the recording lacks. |
| `posthog:session-recording-get`              | Metadata: start and end time, duration, active seconds, `snapshot_source`.                                 |

## Workflow

### Step 1: Build the lifecycle timeline

Run the recipes in [reading-the-export.md](./references/reading-the-export.md):

- **Timeline**: page loads (Meta), full snapshots, and SDK custom events, in seconds from the start, with window ids.
- **Windows**: for each `windowId`, the first event, the first full snapshot, and the last event.
- **Gaps**: stretches of 30 seconds or more with no data.
- **Config**: `$remote_config_received`, `$recording_started`, `triggerGroupSamplingDecisionMade`, and the replay-related keys of `$posthog_config`.

Mobile SDKs do not write these custom events. For mobile, use the windows and gaps recipes and the SQL in Step 3.

### Step 2: Explain each gap from the timeline

Read the custom events around each gap. The [lifecycle tags table](./references/reading-the-export.md#lifecycle-custom-events) says what each one means.

- `sessionIdle` before a gap and `sessionNoLongerIdle` after it: the user was inactive. Expected. The SDK takes no snapshots while idle.
- `window hidden` / `window visible`: the user was in another tab or app. Expected.
- `recording paused` with `reason: url blocker`: the page matched the URL blocklist. Expected.
- `browser offline`: data was buffered offline and may be lost if the tab closed.
- `$session_id_change` or `$session_ending`: the rest is in another recording. `nextSessionId` names it.
- A window whose first full snapshot is much later than its first event: the start was lost. That is the "first N can't be played" banner.
- A window that ends at the last interaction before a navigation, with no next Meta: the next page was not captured.

### Step 3: Compare with what the user actually did

Events show pages and actions that the recording lacks:

```sql
SELECT
    timestamp,
    event,
    properties.$current_url AS url,
    properties.$recording_status AS recording_status,
    properties.$session_recording_start_reason AS start_reason,
    properties.$sdk_debug_replay_flushed_size AS flushed_size,
    properties.$lib AS lib,
    properties.$lib_version AS lib_version
FROM events
WHERE $session_id = '<session_id>'
    AND event IN ('$pageview', '$screen', '$pageleave', '$autocapture', '$exception')
ORDER BY timestamp ASC
LIMIT 300
```

- Events on URLs with no Meta `href` in the recording: those pages were not recorded. Check `$lib_version` on them. A different version or `$lib` means a different app or init.
- `recording_status` that changes during the session (for example to `disabled`, `paused`, or `buffering`) shows where the SDK stopped.
- No client events at all after a point (only server-side `$lib` values): the client SDK stopped loading.

### Step 4: Match to a cause

Use [causes.md](./references/causes.md).
Each cause lists the evidence that proves it.
Accept a cause only when its evidence is in this recording or in the events.
If the evidence points outside what you can see (billing limit, proxy config, an ad blocker on the user's device), say so and say how the user can check.

### Step 5: Generalize to sessions that were not recorded

The config in this recording applies to every session on the same site and SDK version.
Use it to answer "why only some sessions":

- `sampleRate` below 1, or `triggerGroupSamplingDecisionMade.sampleRate`: most sessions are left out on purpose.
- `urlTriggers`, `eventTriggers`, or `linkedFlag`: sessions that never match are not recorded. Check the patterns for typos.
- `minimumDurationMilliseconds`: shorter sessions are dropped.
- `urlBlocklist`: those pages never record.

For a specific session with no recording, hand off to the `diagnosing-missing-recordings` skill.

### Step 6: Answer

Lead with one sentence: expected by config, data lost on the way, or never recorded.
Then give:

1. **What is missing**: which part of this recording, by player time.
2. **Why**: the cause, with the custom events, timestamps, and config values that prove it.
3. **Fix**: the setting path or SDK option and value, the minimum SDK version if one applies, and a docs link.
4. **What it means for other sessions**: from the config in Step 5.
5. **What cannot be recovered**: data that never reached PostHog, or that was dropped by a billing limit, is gone.

Do not quote personal data from the recording (URLs with tokens, emails, input values) unless the user needs it.

## Related skills

- **`diagnosing-missing-recordings`**: a session has no recording, or recordings are missing project-wide
- **`diagnosing-replay-rendering`**: the recording was captured but plays back wrong
- **`investigating-replay`**: what the user did in the session
