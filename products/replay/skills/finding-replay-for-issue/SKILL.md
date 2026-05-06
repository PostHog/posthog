---
name: finding-replay-for-issue
description: >
  Finds the most informative session recording linked to an error tracking issue.
  Use when a user has an error tracking issue ID and wants to watch a replay showing
  what the user was doing when the error occurred. Ranks linked sessions by recency,
  activity score, and journey completeness, then summarizes the pre-error context.
  Replaces blind session picking from potentially hundreds of linked recordings.
---

# Finding the best replay for an error tracking issue

When a user says "show me a replay for this error" or "find a recording for issue X",
the goal isn't just any linked session — it's the one that best shows what led to the error.
Popular issues can have hundreds of linked sessions, and most are crash-only fragments
or duplicate occurrences. This skill picks the most useful one.

## Available tools

| Tool                                     | Purpose                                               |
| ---------------------------------------- | ----------------------------------------------------- |
| `posthog:error-tracking-issues-retrieve` | Get issue details (fingerprint, status, volume)       |
| `posthog:execute-sql`                    | Query exception events to find linked sessions        |
| `posthog:query-session-recordings-list`  | Fetch recording metadata for candidate sessions       |
| `posthog:session-recording-get`          | Get full details for the selected recording           |
| `posthog:session-recording-summarize`    | AI summary of the selected recording (optional, slow) |

## Workflow

### Step 1 — Get the issue details

Fetch the error tracking issue to understand what you're looking for:

```json
posthog:error-tracking-issues-retrieve
{
  "id": "<issue_id>"
}
```

Note the issue's `fingerprint`, `name`, and `description` — you'll need the fingerprint
to find linked sessions.

### Step 2 — Find sessions with this error

Query exception events to get session IDs where this error occurred.
Order by recency and include basic context:

```sql
posthog:execute-sql
SELECT
    $session_id AS session_id,
    count() AS occurrences,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen,
    any(properties.$current_url) AS url
FROM events
WHERE event = '$exception'
    AND properties.$exception_fingerprint = '<fingerprint>'
    AND $session_id IS NOT NULL
    AND timestamp > now() - INTERVAL 30 DAY
GROUP BY session_id
ORDER BY last_seen DESC
LIMIT 20
```

This gives you up to 20 candidate sessions. More candidates means better selection.

### Step 3 — Rank the candidates

Fetch recording metadata for the candidate sessions to rank them:

```json
posthog:query-session-recordings-list
{
  "session_ids": ["<id1>", "<id2>", "<id3>", ...],
  "date_from": "-30d"
}
```

Pick the best recording by filtering out bad candidates, then ranking what's left:

**Filter out:**

- Sessions under 10 seconds (crash-only fragments, no pre-error context)
- Sessions over 1 hour (too much data to load, error is a needle in a haystack)

**Rank by:**

1. **Sweet-spot duration** — 2-15 minutes is ideal. Long enough to show the user's
   journey before the error, short enough to be practical to watch or summarize.
2. **Active time ratio** — compare `active_seconds` to `recording_duration`. A 20-minute
   recording with 10 seconds of activity is mostly idle tabs — the user walked away.
   Prefer sessions where `active_seconds / recording_duration` is above 0.3 (30%).
3. **Activity score** — higher `activity_score` means the user was actively interacting,
   not idle. More interesting to watch.
4. **Recency** — more recent sessions reflect current app behavior.

### Step 4 — Present the finding

Fetch full details for the selected recording:

```json
posthog:session-recording-get
{
  "id": "<best_recording_id>"
}
```

Present to the user:

- **The recording** with a link to watch it
- **Why this one** — briefly explain the selection ("longest session with the error,
  user was browsing 3 pages before hitting it")
- **Pre-error context** — what pages the user visited and key actions before the exception,
  derived from the events query in step 2 (the `url` and `first_seen` columns)
- **Error frequency** — how many times the error occurred in this session

### Optional: AI summary

If the user wants a narrative summary without watching:

```json
posthog:session-recording-summarize
{
  "session_ids": ["<best_recording_id>"],
  "focus_area": "<error description or type>"
}
```

Warn that this takes ~5 minutes for first-time summaries.

## Tips

- If all candidate sessions are very short (<10 seconds), the error likely crashes
  the page immediately. Note this — it's useful context even without a long replay.
- When the issue has very few linked sessions (<3), skip the ranking and just present
  what's available with a note about the small sample.
- If `$session_id` is null on many exception events, session replay may not be enabled
  for the affected users. Mention this as a possible gap.
- The `focus_area` parameter on `session-recording-summarize` is powerful here —
  pass the exception type or message so the summary focuses on the error context
  rather than the entire session.
