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
