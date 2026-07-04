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

| Tool                                       | Purpose                                                  |
| ------------------------------------------ | -------------------------------------------------------- |
| `posthog:session-recording-get`            | Recording metadata (duration, counts, status)            |
| `posthog:persons-retrieve`                 | Person profile (properties, distinct IDs)                |
| `posthog:execute-sql`                      | Query events, errors, and page views in session          |
| `posthog:query-error-tracking-issues-list` | Find error tracking issues linked to the session         |
| `posthog:vision-observations-list`         | Check for an existing Replay Vision AI summary           |
| `posthog:vision-scanners-list`             | Find summarizer scanners (`scanner_type=summarizer`)     |
| `posthog:vision-scanners-scan-session`     | Run a summarizer scanner on the session (slow, optional) |
| `posthog:vision-scanners-create`           | Create a temporary summarizer scanner (ask first)        |
| `posthog:vision-scanners-delete`           | Delete a temporary scanner after summarizing             |

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
    -- Exception details live in the array-shaped $exception_values/$exception_types
    -- (1-indexed in ClickHouse); fall back to the legacy singular fields, which are
    -- unset on most $exception events.
    if(event = '$exception', coalesce(JSONExtractString(properties.$exception_values, 1), properties.$exception_message), null) AS exception_message,
    if(event = '$exception', coalesce(JSONExtractString(properties.$exception_types, 1), properties.$exception_type), null) AS exception_type
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
    -- The legacy singular $exception_type/$exception_message are unset on most
    -- $exception events; read the array-shaped fields first (1-indexed), then fall back.
    coalesce(JSONExtractString(properties.$exception_types, 1), properties.$exception_type) AS type,
    coalesce(JSONExtractString(properties.$exception_values, 1), properties.$exception_message) AS message,
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

   Look for an observation where `scanner_snapshot.scanner_type` is `summarizer`
   and `status` is `succeeded`. If found, read `scanner_result.model_output`
   (`title`, `summary`, `intent`, `outcome`, `friction_points`, `keywords`) — done,
   no new scan needed.

2. **Find a summarizer scanner** if none exists yet:

   ```json
   posthog:vision-scanners-list
   {
     "scanner_type": "summarizer"
   }
   ```

   - Exactly one → use it.
   - More than one → show the user the scanners (name + prompt) and ask which to use.
   - None → no summarizer scanner exists. See
     **No summarizer scanner? Run a temporary one** below.

3. **Scan the session** with the chosen scanner. Warn this is async and takes
   several minutes (rasterize + LLM):

   ```json
   posthog:vision-scanners-scan-session
   {
     "id": "<scanner_id>",
     "session_id": "<session_id>"
   }
   ```

4. **Retrieve the result** by polling `vision-observations-list` (step 1) until
   the new observation reaches `succeeded`.

### No summarizer scanner? Run a temporary one

If the project has no summarizer scanner, you can still produce a one-off summary
with a throwaway scanner — but **ask the user's permission before creating anything**.

1. **Ask permission** to create a temporary summarizer scanner just to summarize
   this one session.

2. **Create it disabled** so it never sweeps on a schedule — a disabled scanner
   only runs when you trigger it on demand, so it won't touch other sessions or
   burn quota in the background:

   ```json
   posthog:vision-scanners-create
   {
     "name": "Temporary on-demand summary",
     "scanner_type": "summarizer",
     "scanner_config": {
       "prompt": "Summarize what the user was trying to do, whether they succeeded, and any friction they hit."
     },
     "query": { "kind": "RecordingsQuery" },
     "model": "gemini-3-flash-preview",
     "enabled": false
   }
   ```

3. **Scan this session on demand** with the new scanner, then poll for the result:

   ```json
   posthog:vision-scanners-scan-session
   {
     "id": "<new_scanner_id>",
     "session_id": "<session_id>"
   }
   ```

   Poll `vision-observations-list` until the observation reaches `succeeded` and
   read `scanner_result.model_output`.

4. **Ask whether to keep or delete the scanner.** Once you have the observation,
   ask the user if they want to keep the temporary scanner or delete it with
   `vision-scanners-delete`. Deleting is safe: the summary you just read is also
   emitted as an event that persists after the scanner is gone, so cleaning up the
   temporary scanner does not lose the result.

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
