---
name: diagnosing-replay-capture-gaps
description: >
  Explains why part of one session recording was not captured, by reading the
  exported rrweb JSON (`*-ph-recording.json`) and the SDK lifecycle and config
  events inside it.
  Use when a user debugs one replay and asks why it starts late, stops early,
  only shows the first or landing page, stops after cookie consent or a page
  navigation, has blank stretches or gaps, is shorter than the real visit, is
  split across sessions, or shows "the first N minutes can't be played".
  Not for sessions with no recording, or recordings that stopped across the
  project: use diagnosing-missing-recordings for those.
---

# Diagnosing gaps in what a replay captured

The user has one recording open and something is missing: the start, the end, a page, or a stretch in the middle.
The recording itself is the best evidence.
posthog-js writes its config, its start reason, and its lifecycle (pauses, idle, session changes, page loads) into the recording as custom events.

Your job is to separate three things:

1. **Expected gaps**: the SDK did what it was configured to do (sampling, triggers, URL blocklist, idle, hidden tab, minimum duration).
2. **Lost data**: the SDK recorded, but data did not reach PostHog (tab closed before upload, blocked `/s/` requests, a proxy that breaks `/s/`).
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

Run the recipes in [reading-the-export.md](./references/reading-the-export.md).
Set `START_MS` from the recording's `start_time` first, so the recipes print player time. The player starts at `start_time` when that is earlier than the first snapshot.

- **Timeline**: page loads (Meta), full snapshots, and SDK custom events, in seconds of player time, with window ids.
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
- A window whose first full snapshot is much later than its first non-Custom event: the start was lost. That is the "first N can't be played" banner.
  Custom events alone before the full snapshot do not count. A backdated `sessionIdle` opens the window over an idle span, and the SDK records nothing while idle.
- A window that ends at the last interaction before a navigation, with no later Meta and no `$pageview` or `$url_changed` event: the next page was not captured.

### Step 3: Compare with what the user actually did

Events show pages and actions that the recording lacks.
Bound both queries by time, because `$session_id` alone does not limit the partitions it reads.
Take `<start>` and `<end>` from `session-recording-get`, or from the first and last snapshot timestamps.
A session lasts at most 24 hours, so a one-day buffer on each side keeps events from before the recording started.

First, the pages and SDK states the session has:

```sql
SELECT
    properties.$current_url AS url,
    properties.$lib AS lib,
    properties.$lib_version AS lib_version,
    properties.$recording_status AS recording_status,
    groupUniqArray(properties.$session_recording_start_reason) AS start_reasons,
    groupUniqArray(event) AS event_types,
    count() AS events,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE $session_id = '<session_id>'
    AND timestamp >= toDateTime('<start>') - INTERVAL 1 DAY
    AND timestamp <= toDateTime('<end>') + INTERVAL 1 DAY
    AND event IN ('$pageview', '$screen', '$pageleave', '$autocapture', '$exception')
GROUP BY url, lib, lib_version, recording_status
ORDER BY last_seen ASC
LIMIT 500
```

Each row covers every event for one URL and SDK state, so a long session does not push pages out of the result.
The rows are not a timeline. A page the user visited twice is one row, with `first_seen` from the first visit and `last_seen` from the last.
If the query returns 500 rows, the result is cut off: narrow the time range.

Then, the order of pages and how the session ended, newest first:

```sql
SELECT
    timestamp,
    event,
    properties.$current_url AS url,
    properties.$lib AS lib,
    properties.$recording_status AS recording_status
FROM events
WHERE $session_id = '<session_id>'
    AND timestamp >= toDateTime('<start>') - INTERVAL 1 DAY
    AND timestamp <= toDateTime('<end>') + INTERVAL 1 DAY
    AND event IN ('$pageview', '$screen', '$pageleave')
ORDER BY timestamp DESC
LIMIT 100
```

- Events on URLs that the recording does not cover: those pages were not recorded. A single-page app changes route without a page load, so compare against Meta `href` values **and** the `href` of `$pageview` and `$url_changed` custom events, and check that snapshots continue around that time. Only then check `$lib_version` on the unrecorded events. A different version or `$lib` means a different app or init.
- `recording_status` that changes from one page to the next in the second query (for example to `disabled`, `paused`, or `buffering`) shows where the SDK stopped.
- Events that continue after the recording's last snapshot: the user was still there, so the recording stopped early. Read the last page and its `recording_status` from the top rows of the second query.
- No client events at all after a point (only server-side `$lib` values): the client SDK stopped loading.

### Step 4: Match to a cause

Use [causes.md](./references/causes.md).
Each cause lists the evidence that proves it.
Accept a cause only when its evidence is in this recording or in the events.
If the evidence points outside what you can see (proxy config, an ad blocker on the user's device), say so and say how the user can check.

### Step 5: Answer

Lead with one sentence: expected by config, data lost on the way, or never recorded.
Then give:

1. **What is missing**: which part of this recording, by player time.
2. **Why**: the cause, with the custom events, timestamps, and config values that prove it.
3. **Fix**: the setting path or SDK option and value, the minimum SDK version if one applies, and a docs link.
4. **What cannot be recovered**: data that never reached PostHog is gone.

If the user also asks about a session with no recording, or recordings that stopped across the project, hand off to the `diagnosing-missing-recordings` skill.

Do not quote personal data from the recording (URLs with tokens, emails, input values) unless the user needs it.

## Related skills

- **`diagnosing-missing-recordings`**: a session has no recording, or recordings are missing project-wide
- **`diagnosing-replay-rendering`**: the recording was captured but plays back wrong
- **`investigating-replay`**: what the user did in the session
