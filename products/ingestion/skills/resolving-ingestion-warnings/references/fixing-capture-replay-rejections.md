# Fixing capture replay rejections

Covers `missing_session_id`, `invalid_session_id`, and `missing_snapshot_data`.

These come from capture's session replay endpoint, `/s`, not from the replay consumer.
They carry `source = 'capture'` and a `path` detail of `/s` or `/s/`, which is how you tell them apart from the other `replay`-category warnings, whose batches had already been accepted and which carry `source = 'plugin-server'`.

Three things about this endpoint shape every diagnosis:

- **It rejects at the edge.** The request got a `400` and nothing reached the pipeline, so the batch is not in `session_replay_events`, not in the recording list, and has no trace anywhere else. The warning is the only record.
- **A batch is all-or-nothing.** Every `$snapshot` in one request is folded into a single `$snapshot_items` message, so one bad event rejects the whole request. `count` and `eventCount` are the number of events lost, which is why a single malformed event can show a `count` in the dozens.
- **Metadata comes from the first event only.** `$session_id`, `distinct_id`, and the rest are read off `events[0]`. A batch mixing two sessions is filed under the first one's id without warning, so a batch that looks fine can still be misattributed.

Check `lib` and `libVersion` first on every one of these. A rejection concentrated on one SDK version is an upgrade, not a payload problem. Replay has no SDK-info header, so `lib` may be derived from the user agent and read `web` when the payload carried no `$lib`.

## `missing_session_id`

The first `$snapshot` in the batch had no `$session_id` property at all.

posthog-js and the mobile SDKs always set this, so seeing it means something other than a stock SDK is building the payload. In practice:

- **Hand-rolled replay ingestion.** A script or server relay assembling `$snapshot` events itself, and omitting the property. `$session_id` is required; there is no default.
- **Session management driven outside the SDK.** An integration that generates its own session ids and forgot to attach one to the replay payload, while analytics events still carry theirs.
- **A rewriting proxy.** Something between the SDK and PostHog strips or renames properties. Compare a captured request body against what the browser actually sent.

## `invalid_session_id`

`$session_id` was present but unusable. The `reason` detail names which rule broke:

- **`not_a_string`** — the value arrived as a number, boolean, object, or `null`. Usually a session id held as an integer and serialized without quoting. Send it as a JSON string.
- **`too_long`** — over the 70-byte limit. `sessionIdLength` is the actual length. A UUID is 36 characters and fits comfortably, so this generally means a composite id (a session id concatenated with a user id, a tenant prefix, or a timestamp). Shorten it, or hash it to a UUID.
- **`invalid_charset`** — the id contains something outside `[A-Za-z0-9-]`. Underscores, colons, slashes, dots, and spaces all land here, as does any non-ASCII character. Composite ids joined with `_` or `:` are the common case.

The offending value itself is deliberately not in the details. It is unvalidated client input, and it would land in a customer-visible column, so `reason` and `sessionIdLength` carry the actionable part instead. To see the value, look at the SDK's own session id on the client.

If you are generating session ids yourself, the safe format is a UUID. PostHog's own SDKs emit one.

## `missing_snapshot_data`

An event in the batch had no usable `$snapshot_data`. The `reason` detail separates the two cases:

- **`absent`** — the property is missing entirely. Either an SDK too old to send it, or a payload assembled by hand. Note this can be a _later_ event in the batch: the first event can be perfectly valid and the request still rejects, which is why `count` covers events that looked fine.
- **`wrong_json_type`** — the property is present but is neither an array of rrweb events nor a single event object. A string lands here, which is the signature of double-encoded JSON: the snapshot data was serialized to a string and then embedded, so it arrives as `"[{...}]"` rather than `[{...}]`. Also seen with `null` and with numbers.

Double encoding is the most common cause worth ruling out first, and it points at whatever sits between the SDK and capture: a relay that re-serializes bodies, a proxy that treats the payload as an opaque string, or custom code doing an extra `JSON.stringify`.

Note the neighbouring case that does **not** produce this warning: `$snapshot_data: []`, an empty array, is accepted by capture and rejected later by the replay consumer as `message_contained_no_valid_rrweb_events`. If a team reports missing recordings and you see that type instead, the problem is downstream of this endpoint.
