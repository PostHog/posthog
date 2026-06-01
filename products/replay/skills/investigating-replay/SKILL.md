---
name: investigating-replay
description: >
  Investigates a session recording by gathering metadata, person profile,
  same-session events, and linked error tracking issues in one pass.
  Use when a user provides a recording or session ID and wants to understand
  what happened — who the user was, what they did, what errors occurred,
  and whether there are related error tracking issues. Replaces the manual
  chain of session-recording-get, persons-retrieve, execute-sql, and
  error-tracking-issues-list.
---

# Investigating a session recording

When a user asks "what happened in this session?" or provides a recording/session ID
to investigate, gather all relevant context in parallel rather than making them
ask for each piece.

## Available tools

| Tool                                  | Purpose                                          |
| ------------------------------------- | ------------------------------------------------ |
| `posthog:session-recording-get`       | Recording metadata (duration, counts, status)    |
| `posthog:persons-retrieve`            | Person profile (properties, distinct IDs)        |
| `posthog:execute-sql`                 | Query events, errors, and page views in session  |
| `posthog:error-tracking-issues-list`  | Find error tracking issues linked to the session |
| `posthog:session-recording-summarize` | AI-generated summary (slow, ~5 min, optional)    |

## Workflow

### Step 1 — Get recording metadata and person profile

Start with the recording to get metadata and the person's distinct ID:

```json
posthog:session-recording-get
{
  "id": "<recording_id>"
}
```

The response includes `distinct_id`, `person`, duration, interaction counts,
console error counts, and viewing status. Use the `distinct_id` to fetch
the full person profile:

```json
posthog:persons-retrieve
{
  "id": "<person_uuid_from_recording>"
}
```

### Step 2 — Query same-session events

Get the timeline of what the user did during the session:

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
    if(event = '$exception', properties.$exception_message, null) AS exception_message,
    if(event = '$exception', properties.$exception_type, null) AS exception_type
FROM events
WHERE $session_id = '<session_id>'
    AND event IN ('$pageview', '$pageleave', '$autocapture', '$exception', '$rageclick')
ORDER BY timestamp ASC
LIMIT 100
```

### Step 3 — Check for linked error tracking issues

If the recording has console errors or exceptions, find related error tracking issues:

```sql
posthog:execute-sql
SELECT DISTINCT
    properties.$exception_fingerprint AS fingerprint,
    properties.$exception_type AS type,
    properties.$exception_message AS message,
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
posthog:error-tracking-issues-list
{
  "search": "<exception_type or message>"
}
```

### Step 4 — Synthesize the investigation

Present the findings as a coherent narrative:

1. **Who** — person properties (name, email, country, plan, etc.)
2. **What** — sequence of pages visited and key actions taken
3. **Problems** — exceptions, console errors, rage clicks, and their frequency
4. **Related issues** — linked error tracking issues with their status (active/resolved)
5. **Context** — session duration, device/browser, activity score

### Optional: AI summary

If the user wants a deeper analysis without reading through events manually,
offer `session-recording-summarize`. Warn that first-time summaries take ~5 minutes:

```json
posthog:session-recording-summarize
{
  "session_ids": ["<session_id>"]
}
```

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
