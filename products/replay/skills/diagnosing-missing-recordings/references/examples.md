# Diagnostic examples

Real-world examples showing how diagnostic signals map to verdicts.
Use these to calibrate your interpretation of query results.

## Example 1: recording disabled

A session on a local dev instance (`localhost:8010`) where replay was turned off at the project level.

**Query result:**

| has_recording | recording_status | start_reason | script_not_loaded | url_trigger | event_trigger | flag_trigger | sample_rate | buffer_length | flushed_size | sdk_library | sdk_version |
| ------------- | ---------------- | ------------ | ----------------- | ----------- | ------------- | ------------ | ----------- | ------------- | ------------ | ----------- | ----------- |
| null          | disabled         | null         | null              | null        | null          | null         | null        | null          | null         | web         | 1.369.2     |

**Verdict:** DISABLED

**Explanation:**
`$recording_status = 'disabled'` on every event in the session.
The SDK decided not to record at initialization time.
All trigger and sampling signals are null because the SDK never reached
the point of evaluating them — recording was off before any of that logic runs.

**What to check:**

- Project settings > Session replay — is recording enabled?
- SDK init config — is `disable_session_recording: true` set?
- Has the user called `posthog.opt_out_capturing()`?

## Example 2: URL trigger never fired

A test session where a URL trigger was configured but the user never visited
a matching URL during the session.

**Query result:**

| has_recording | recording_status | start_reason | script_not_loaded | url_trigger     | event_trigger | flag_trigger | sample_rate | buffer_length | flushed_size | sdk_library | sdk_version |
| ------------- | ---------------- | ------------ | ----------------- | --------------- | ------------- | ------------ | ----------- | ------------- | ------------ | ----------- | ----------- |
| null          | buffering        | null         | null              | trigger_pending | null          | null         | null        | null          | null         | null        | null        |

**Verdict:** TRIGGER_PENDING

**Explanation:**
`$recording_status = 'buffering'` means the SDK initialized and was ready to record,
but `$sdk_debug_replay_url_trigger_status = 'trigger_pending'` shows it was waiting
for a URL trigger to match. The trigger never fired before the session ended,
so the buffer was discarded and no recording was stored.

**What to check:**

- Project settings > Session replay > URL triggers — what patterns are configured?
- Did the user visit any page matching those patterns?
- Is the URL pattern a regex that might not match the actual URLs?

## Example 3: snapshots produced but never flushed

A session where the SDK is recording and the internal buffer keeps growing,
but nothing ever gets flushed to PostHog.
This pattern can't be seen from a single event —
you need to look at the trend of buffer/flush signals across the session's events.

**Query to detect:**

```sql
SELECT
    timestamp,
    properties.$sdk_debug_replay_internal_buffer_length AS buffer_length,
    properties.$sdk_debug_replay_flushed_size AS flushed_size
FROM events
WHERE $session_id = '<session_id>'
ORDER BY timestamp ASC
```

**Pattern to look for:**

| timestamp | buffer_length | flushed_size |
| --------- | ------------- | ------------ |
| t0        | 3             | 0            |
| t1        | 17            | 0            |
| t2        | 42            | 0            |
| t3        | 98            | 0            |

**Verdict:** AD_BLOCKED (or misconfigured reverse proxy)

**Explanation:**
The buffer keeps climbing but `flushed_size` stays at zero.
That means the SDK is producing snapshots correctly but the `POST /s/` requests
never complete — so the recording data never reaches PostHog's backend.
Most commonly this is an ad blocker silently blocking the ingestion endpoint.
On self-hosted or reverse-proxied setups it can also indicate the proxy
isn't forwarding `/s/` to the capture service.

**What to check:**

- User's browser: does the Network tab show failed/blocked `POST /s/` requests?
- Reverse proxy config: is `/s/` routed to PostHog capture?
- Custom domain: is the recorder script using the same domain as capture?

This is a different signal from `$sdk_debug_recording_script_not_loaded` —
that one fires when the rrweb script itself is blocked from loading.
The flushing-never-happens pattern means rrweb loaded fine but the upload is blocked.
