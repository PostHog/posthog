---
name: investigating-replay
description: >
  Investigates a session recording by gathering metadata, person profile,
  same-session events, and linked error tracking issues in one pass.
  Use when a user provides a recording or session ID and wants to understand
  what happened — who the user was, what they did, what errors occurred,
  and whether there are related error tracking issues. Replaces the manual
  chain of session-recording-get, persons-retrieve, execute-sql, and
  query-error-tracking-issues-list.
---

# Investigating a session recording

When a user asks "what happened in this session?" or provides a recording/session ID
to investigate, gather all relevant context in parallel rather than making them
ask for each piece.

## Available tools

| Tool                                         | Purpose                                                    |
| -------------------------------------------- | ---------------------------------------------------------- |
| `posthog:session-recording-get`              | Recording metadata (duration, counts, status)              |
| `posthog:persons-retrieve`                   | Person profile (properties, distinct IDs)                  |
| `posthog:execute-sql`                        | Query events, errors, and page views in session            |
| `posthog:query-error-tracking-issues-list`   | Find error tracking issues linked to the session           |
| `posthog:vision-observations-list`           | Check for an existing Replay Vision AI summary             |
| `posthog:vision-observations-retrieve`       | Read one observation in full (`scanner_result`)            |
| `posthog:vision-scanners-inline-scan-create` | Generate an AI summary of the session (slow, optional)     |
| `posthog:vision-scanners-list`               | Find saved summarizer scanners (`scanner_type=summarizer`) |
| `posthog:vision-scanners-scan-session`       | Run a saved summarizer scanner on the session (slow)       |

## Workflow

### Step 1 — Get recording metadata and person profile

Start with the recording to get metadata and the person's distinct ID:

```json
posthog:session-recording-get
{
  "id": "<session_id>"
}
```

The recording `id` and the event `$session_id` are the same value. It selects the
recording here and the same-session events in Step 2. The response includes
`distinct_id`, `person`, `start_time`, `end_time`, duration, interaction counts,
console error counts, and viewing status. Use the `distinct_id` to fetch
the full person profile:

```json
posthog:persons-retrieve
{
  "id": "<person_uuid_from_recording>"
}
```

### Step 2 — Query same-session events

Use the recording `id` from Step 1 as the `$session_id` value. Get the timeline
of what the user did during the session:

```sql
posthog:execute-sql
SELECT
    timestamp,
    event,
    properties.$current_url AS url,
    properties.$browser AS browser,
    properties.$os AS os,
    properties.$device_type AS device_type,
    properties.$screen_width AS screen_width
FROM events
WHERE $session_id = '<session_id>'
ORDER BY timestamp ASC
LIMIT 200
```

For sessions with many events, focus on the most informative ones:

```sql
posthog:execute-sql
SELECT
    timestamp,
    event,
    properties.$current_url AS url,
    if(event = '$exception', properties.$exception_values[1], null) AS exception_message,
    if(event = '$exception', properties.$exception_types[1], null) AS exception_type
FROM events
WHERE $session_id = '<session_id>'
    AND event IN ('$pageview', '$pageleave', '$autocapture', '$exception', '$rageclick')
ORDER BY timestamp ASC
LIMIT 100
```

#### No rows? Recover the event session ID

The recording `id` is the session ID. No rows means the session's events were
ingested without it. Find candidates from the person's events in the recording
window, padded by 100 seconds like the replay events query. `person_id` covers
all of the person's distinct IDs:

```sql
posthog:execute-sql
SELECT
    properties.$session_id AS session_id,
    count() AS event_count,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE person_id = '<person_uuid>'
    AND timestamp >= toDateTime('<start_time>') - INTERVAL 100 SECOND
    AND timestamp <= toDateTime('<end_time>') + INTERVAL 100 SECOND
    AND properties.$session_id IS NOT NULL
GROUP BY session_id
ORDER BY event_count DESC
LIMIT 10
```

Continue only when one session ID clearly matches. Use it for the Step 2 and
Step 3 queries only. The replay URL and all Replay Vision calls take the
recording `id`.

### Step 3 — Check for linked error tracking issues

If the recording has console errors or exceptions, find related error tracking issues:

```sql
posthog:execute-sql
SELECT DISTINCT
    properties.$exception_fingerprint AS fingerprint,
    properties.$exception_types[1] AS type,
    properties.$exception_values[1] AS message,
    count() AS occurrences
FROM events
WHERE $session_id = '<session_id>'
    AND event = '$exception'
GROUP BY fingerprint, type, message
ORDER BY occurrences DESC
LIMIT 10
```

If fingerprints are found, search for the corresponding error tracking issues
to provide links and status:

```json
posthog:query-error-tracking-issues-list
{
  "searchQuery": "<exception_type or message>"
}
```

### Step 4 — Synthesize the investigation

Present the findings as a coherent narrative:

1. **Who** — person properties (name, email, country, plan, etc.)
2. **What** — sequence of pages visited and key actions taken
3. **Problems** — exceptions, console errors, rage clicks, and their frequency
4. **Related issues** — linked error tracking issues with their status (active/resolved)
5. **Context** — session duration, device/browser, activity score

### Optional: AI summary via Replay Vision

If the user wants a deeper analysis without reading through events manually,
offer a Replay Vision summary. Follow "check-then-scan" — don't scan blindly,
a scanner can only observe a given session once.

1. **Check for an existing summary.** A scheduled scanner may already have one:

   ```json
   posthog:vision-observations-list
   {
     "session_id": "<session_id>"
   }
   ```

   The rows come back narrowed to `id`, `session_id`, `status`, `summary_line` and
   `scanner_id`. Look for one whose `status` is `succeeded`, then read it in full with
   `vision-observations-retrieve` for that `id`: its `scanner_snapshot.scanner_type`
   tells you whether it is a `summarizer`, and `scanner_result.model_output` carries
   `title`, `summary`, `intent`, `outcome`, `friction_points` and `keywords`. If you
   find one, you are done — no new scan needed.

2. **Generate one** with an inline scan. Pass this exact config: inline scans are
   keyed by a fingerprint of the whole config, so the config below reuses the same
   scanner row the player's Summarize button uses on its built-in prompt, while a
   different prompt or `length` mints a separate scanner and a separate summary.

   ```json
   posthog:vision-scanners-inline-scan-create
   {
     "session_ids": ["<session_id>"],
     "scanner_type": "summarizer",
     "prompt": "Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
     "scanner_config": { "length": "medium" }
   }
   ```

   Leave `model` out so the server default applies. Warn the user this is async and
   takes several minutes (rasterize + LLM). Nothing is scheduled and there is
   nothing to clean up: the scanner an inline scan mints never sweeps on its own. A
   400 here usually means the organization has not approved AI data processing yet.

3. **Read `results[0].scan_outcome` before polling.** `started` means poll
   `vision-observations-list` (step 1) until the new observation reaches `succeeded`.
   `already_scanned` means a terminal observation already exists — read it via step 1,
   and if its status is `failed` or `ineligible` say so rather than polling. A null
   `scan_id` or `skipped_quota` means nothing ran: report the quota, do not poll.

### The project already has a summarizer scanner

Use an inline scan for a one-off summary even then. Only reach for a saved scanner
when the user wants that scanner's own prompt rather than the built-in one:

```json
posthog:vision-scanners-list
{
  "scanner_type": "summarizer"
}
```

Show the user the scanners (name + prompt), ask which to use, then run it against
the session and poll `vision-observations-list` until the observation reaches
`succeeded`:

```json
posthog:vision-scanners-scan-session
{
  "id": "<scanner_id>",
  "session_id": "<session_id>"
}
```

Never create a scanner to answer a single question — `vision-scanners-create`
leaves a scheduled sweep behind that the inline scan does not.

## Tips

- Run steps 1-3 in parallel when possible — they're independent queries.
- If the recording has very few events, the session was likely very short.
  Note this rather than suggesting something is broken.
- Console error count from the recording metadata is a good signal for whether
  to dig into exceptions. If it's 0, skip step 3.
- The `start_url` from the recording tells you where the user's journey began —
  use this to frame the narrative.
- If `person` is null on the recording, the user was anonymous.
  Person properties won't be available, but events still are.

## Related skills

- **`finding-sessions-to-watch`** — choose which sessions are worth investigating in the first place
- **`finding-replay-for-issue`** — start from an error tracking issue and find its linked recordings
- **`diagnosing-missing-recordings`** — when a recording that should exist doesn't
- **`creating-replay-vision-scanners`** — automate this kind of watching as a scheduled scanner
