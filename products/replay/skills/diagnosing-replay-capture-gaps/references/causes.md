# Capture gap causes

Each cause lists its symptom, the evidence that proves it, and the fix.
They are grouped by the three verdicts in the skill, and ordered by how often they reach support.
Recipes are in [reading-the-export.md](./reading-the-export.md).

## Expected by config

### Recording conditions leave sessions or pages out

**Symptom:** "only some users", "only landing pages", "nothing on mobile since the upgrade", "the subdomain stopped recording".

**Evidence:**

- `$remote_config_received`: `sampleRate` below 1, `urlTriggers`, `eventTriggers`, `linkedFlag`, `triggerGroups`, `triggerMatchType`.
- `$recording_started.reason` tells which condition started this recording. `sampled` with triggers configured means the trigger never fired and this session only got in through sampling.
- `triggerGroupSamplingDecisionMade` shows each group's sample rate and decision.
- Events: `$sdk_debug_replay_url_trigger_status`, `$sdk_debug_replay_event_trigger_status`, `$sdk_debug_replay_linked_flag_trigger_status` stay `trigger_pending` on sessions that do not record.

**Common mistakes:**

- A URL trigger regex that cannot match. Check it against the `$current_url` values of real events, including the scheme, subdomain, and slashes.
- An event trigger that only fires on web. Recording conditions are project-wide and shared by web and mobile, so mobile never records. Add an event that fires on mobile (for example `$screen` or `Application Opened`); event triggers combine with OR.
- A sample rate set in the collapsed **legacy recording conditions** section of replay settings. The UI hides that section when trigger groups are in use, but the rate still applies. Which pages are missing then looks meaningful but is random per session.
- The customer's own rollout flag or sampling stacked on top of PostHog sampling.
- Mobile SDK upgrades: older Android SDKs ignored remote sampling and triggers and recorded everything. After an upgrade, the same project settings record fewer sessions.
- A local `sessionReplayConfig.sampleRate` in a mobile SDK overrides the project rate.

**Fix:** settings path: Settings > Session replay > Recording conditions. Explain the trade-off between triggers and sampling.
On web, the SDK buffers about a minute before a trigger fires, so the recording starts shortly before the trigger. Mobile SDKs have no pre-trigger buffer: recording starts at the trigger.
Docs: https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record

### Minimum duration drops short sessions

**Symptom:** short visits never have a recording, or "only long sessions are recorded".

**Evidence:** `minimumDurationMilliseconds` in `$remote_config_received`. Sessions shorter than it are not kept.

**Fix:** lower it in recording conditions if short sessions matter.

### URL blocklist pauses recording

**Symptom:** a page is missing from the middle of a recording.

**Evidence:** `recording paused` with `reason: url blocker`, then `recording resumed`. `urlBlocklist` in the config holds the pattern.

**Fix:** none if intended. Otherwise narrow the pattern.

### Idle time and hidden tabs

**Symptom:** "large gaps", "the recording skips minutes", "the replay is shorter than the visit".

**Evidence:** `sessionIdle` before the gap and `sessionNoLongerIdle` after it, or `window hidden` and `window visible`. The gaps recipe lines up with these.

**Fix:** none. This is expected. The player skips inactivity by default.

### The session rotated into another recording

**Symptom:** a visit is split in two, or the end of what the user did is not in this recording.

**Evidence:** `$session_id_change` and `$session_ending` / `$session_starting`. `changeReason.activityTimeout` (30 minutes idle) and `sessionPastMaximumLength` (24 hours) are normal. `noSessionId` means the app called `posthog.reset()`, often at logout or login.

**Fix:** follow `nextSessionId` to the other recording. If `reset()` runs at login, recordings split there by design. Old posthog-js versions had rotation bugs that split or dropped recordings, so recommend the current version.

## Data lost on the way

### The start of a window is missing ("the first N can't be played")

**Symptom:** the banner "The first Xm Xs of this recording can't be played. The first screen snapshot arrived late."

**Evidence:** in the windows recipe, `first_full_s` is well after `first_s` for a window. Events and network data exist for that stretch, but no full snapshot, so the player cannot draw it.

**Causes:**

- The first upload batch was lost: the tab closed, the network dropped (`browser offline`), or a blocker or proxy dropped it.
- On full-page-reload sites, the SDK buffers snapshots until its remote config arrives. If the user leaves first, the buffer is discarded by design, and that page is missing. Slow loading of posthog-js itself (a large bundle behind blocking scripts) makes this worse.
- In long-lived tabs, a session rotation without a fresh full snapshot. Recent posthog-js versions fix this.

**Fix:** upgrade posthog-js. Load PostHog early and do not put it behind blocking scripts. Check nothing interferes with requests to the API host.
Docs: https://posthog.com/docs/session-replay/troubleshooting#recording-shows-blank-opening-or-late-snapshot-warning

### Recording stops at cookie consent or after an interaction

**Symptom:** the recording ends when the user accepts cookies, or right after they start using the page. Events may stop too.

**Evidence:** the recording's last data is at the consent moment. `$posthog_config` shows `opt_out_capturing_by_default: true` or `cookieless_mode`, and `api_host` is a relative path or the customer's own domain (a reverse proxy).
After consent the SDK starts sending to `/s/` and `/e/`, and the proxy breaks those requests.

**Causes and fixes:**

- A Next.js rewrite that redirects `/ingest/s/` to `/ingest/s` with a 308. Set `skipTrailingSlashRedirect: true` in `next.config.js`.
- A proxy that drops the query string or rejects bodies around 1 MB on `/s/`. Events still work because their requests are small.
- Use the managed reverse proxy to avoid both.

Docs: https://posthog.com/docs/advanced/proxy

### Recordings stopped for everyone on a date, events still arrive

**Symptom:** "no recordings for two weeks", with normal event volume.

**Evidence:** not visible in the recording. Check, in this order:

1. The session replay **billing limit**. When it is reached, new recordings are dropped until the period resets. The capture endpoint still returns 200, so the browser shows no error.
2. Replay turned off in project settings. `disable_session_recording: false` in code does not turn replay on; it only stops the client from blocking it.
3. The settings were changed recently. Changes take a few minutes to reach ingestion.

**Fix:** raise the limit in Organization settings > Billing above what the period already used. It clears in about 15 minutes. Dropped recordings cannot be recovered.
A product analytics limit has the opposite effect: recordings arrive, but events do not, so recordings have no person and searches by user find nothing.

## Never recorded

### A second app or page with replay off

**Symptom:** only the landing or marketing pages are recorded, never the app or checkout.

**Evidence:** events show pages with no Meta `href` in any recording. Those events have a different `$lib_version` or come from another `posthog.init`.
If the recording covers the hand-off page, `$posthog_config` of the first app is fine, and there is no data after the navigation.

**Fix:** find the second `posthog.init` and remove `disable_session_recording: true`, or install PostHog there. Use the same project token in both.

### The recorder script never loaded

**Symptom:** events arrive but the session has no recording, or only some users or browsers have recordings.

**Evidence:** usually no recording exists. When one does, this is not the cause.
In events: `$recording_status = lazy_loading` that never advances, or `$sdk_debug_recording_script_not_loaded = true`.
If network capture is on, the recorder script request (`posthog-recorder.js` or `recorder.js`) fails in some recordings.

**Causes:** an ad blocker (some match the file name, so a proxy does not help), a reverse proxy that does not serve `/static/`, or a CSP rule.

**Fix:** make the proxy serve the static path, or bundle the recorder with npm installs (`import 'posthog-js/dist/posthog-recorder'`). Name a proxy subdomain neutrally, without `posthog`, `analytics`, or `tracking`.
Hand off to the `diagnosing-missing-recordings` skill for per-session checks.

### posthog-js runs inside an iframe with `recordCrossOriginIframes`

**Symptom:** recording reports as started, but nothing arrives.

**Evidence:** `$session_options.payload.sessionRecordingOptions.recordCrossOriginIframes` is `true`, and the app runs inside an iframe. With that option, the child frame sends its recording to the parent window and not to PostHog. Events show `$sdk_debug_replay_internal_buffer_length = 0` and `$sdk_debug_replay_flushed_size = 0`.

**Fix:** if the app is embedded in pages the customer does not own, remove the option. If they own the parent page, install PostHog there with the same option.

### Two PostHog instances record the same page

**Symptom:** recordings fail to load, or contain jumps between two states of the page.

**Evidence:** two `$posthog_config` events with different configs in the same window, or interleaved full snapshots and Meta events with no navigation between them.

**Fix:** there is one recorder per page. Let one instance own replay and set `disable_session_recording: true` on the other.

## When nothing matches

Say what the recording shows and what it rules out.
Ask for the private replay link, the session ID (`posthog.get_session_id()`), the SDK version, and whether a proxy or ad blocker is in use.
Recommend the current SDK version first, because many capture fixes ship there.
