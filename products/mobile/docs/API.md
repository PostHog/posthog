# API

Every request goes through `src/api/client.ts`: it prefixes the host, adds the bearer token,
sets `X-PostHog-Client-Platform: mobile`, refreshes the token once on a 401, and represents HTTP failures
as `ApiError` with the server's `code` and `detail`.
`projectPath('signals/reports/')` builds `/api/projects/{projectId}/signals/reports/` for the session's project.
`scopedPath(scope, 'signals/reports/')` builds the same path for the project the caller names. The report, task and Today helpers take that scope as their first argument, and `runQuery` takes it as an option.
Streams use `apiStream` (expo's fetch, so the body streams on native) and `src/api/sse.ts`.

Ordinary API requests have a 30-second deadline across token refresh and body reads. Caller cancellation stays distinct
from a deadline, and neither a timeout nor a lost connection automatically retries a write. A write can reach the server
before its response is lost, so a timeout does not mean it failed on the server. Long-lived task streams use their own
idle watchdog and reconnect policy. Transport failures have a dedicated error type; unrelated programming errors are
not reported as connectivity failures.

The classic conversation transport uses a 30-second connection deadline and a 60-second inactivity deadline.
Each received chunk, including a heartbeat, resets the inactivity deadline.
An interrupted accepted reply offers reconnection; the app does not resend it automatically.
History reconciliation retains streamed generation failures.
Pending approvals and clarification forms pause reconnection until the person responds.
The classic chat hook exposes form questions from both streamed replies and history, with submit and dismiss methods.
Form responses send no new chat message; they resume the conversation with the selected answers or a dismissal.
Notebook artifacts retain their Markdown and chart blocks, with links to saved notebooks and a web fallback for other content.
Reply links without a project prefix use the conversation's project; explicit project links and external links keep their destination.
Canceling a classic reply requires `conversation:write` for OAuth and personal API tokens.

Most existing types are written by hand per module and name the Django serializer they mirror.
PR checks use `PullRequestChecksResponseApi` from the Signals generated schemas. New API
types should come from the generated schemas; update the Django serializer and run
`hogli build:openapi` when those contracts change. Mobile CI includes the Signals schema
file for typechecking, and its type-only import adds nothing to the native bundle.

Inbox pages validate the fields used to render report rows before they enter the query cache. A malformed page fails
the request while previously loaded pages remain visible. The load-more retry requests the failed page again.

| Domain                           | Module                                                                   | Endpoints                                                                                                                                                                                                                                                                                                                                                                         | Notes                                                                             |
| -------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Account                          | `src/api/users.ts`                                                       | `GET /api/users/@me/`, `GET /api/organizations/{id}/`                                                                                                                                                                                                                                                                                                                             | Account and organization membership                                               |
| OAuth                            | `src/auth/oauth.ts`                                                      | `/oauth/authorize`, `/oauth/token`, `/oauth/revoke`                                                                                                                                                                                                                                                                                                                               | PKCE public client                                                                |
| Inbox and reports                | `src/api/reports.ts`                                                     | `signals/reports/?view=for_you&sort=priority`, `.../{id}/`, `.../signals/`, `.../artefacts/`, `read_state/`, `.../state/`, `.../reviewers/`, `available_reviewers/`                                                                                                                                                                                                               | [DATA.md](DATA.md)                                                                |
| Today                            | `src/api/today.ts`                                                       | `today/reports/{id}/page/`                                                                                                                                                                                                                                                                                                                                                        | 403 or 404 means the project lacks Today; the report screen shows signals instead |
| Tasks                            | `src/api/tasks.ts`                                                       | `tasks/`, `tasks/{id}/` (`PATCH { archived }` archives a chat), `tasks/{id}/run/` (a chat's resume adds `resume_from_run_id` and `pending_user_message`; `pending_user_artifact_ids` carries staged files), `.../runs/{runId}/`, `.../logs/`, `.../stream/`, `.../command/` (`user_message`, with `artifact_ids` for files; `set_config_option`, `permission_response`, `cancel`) | [HANDOFF.md](HANDOFF.md), [CHAT.md](CHAT.md)                                      |
| Classic AI                       | `src/api/conversations.ts`                                               | `GET conversations/`, `GET conversations/{id}/`, `POST conversations/` (SSE), `PATCH conversations/{id}/cancel/`                                                                                                                                                                                                                                                                  | [CHAT.md](CHAT.md)                                                                |
| Chat attachments                 | `src/api/tasks.ts`, `src/features/chat/attachments/uploadAttachments.ts` | `tasks/{id}/staged_artifacts/prepare_upload/`, `tasks/{id}/staged_artifacts/finalize_upload/`, `.../runs/{runId}/artifacts/prepare_upload/`, `.../runs/{runId}/artifacts/finalize_upload/`, all `task:write`; then a presigned S3 `POST` with no PostHog auth                                                                                                                     | [CHAT.md](CHAT.md#attachments)                                                    |
| Push                             | `src/api/pushTokens.ts`                                                  | `/api/users/@me/push_tokens/`, `.../unregister/`                                                                                                                                                                                                                                                                                                                                  | [PUSH.md](PUSH.md)                                                                |
| Views pins                       | `src/api/shortcuts.ts`                                                   | `file_system_shortcut/`, `.../{id}/`                                                                                                                                                                                                                                                                                                                                              | [VIEWS.md](VIEWS.md)                                                              |
| Views dashboards                 | `src/api/dashboards.ts`                                                  | `dashboards/`, `dashboards/{id}/?refresh=force_cache`                                                                                                                                                                                                                                                                                                                             | [VIEWS.md](VIEWS.md)                                                              |
| Views insights                   | `src/api/insights.ts`                                                    | `insights/`, `insights/{id}/`, `insights/viewed/`                                                                                                                                                                                                                                                                                                                                 | [VIEWS.md](VIEWS.md)                                                              |
| Web analytics, people at a point | `src/api/webAnalytics.ts`, `src/api/actors.ts`                           | `query/` (`WebOverviewQuery`, `ActorsQuery`)                                                                                                                                                                                                                                                                                                                                      | [VIEWS.md](VIEWS.md)                                                              |
| Session replay                   | `src/api/recordings.ts`, `src/api/replayVision.ts`                       | `session_recordings/`, `query/` (`HogQLQuery`), `vision/observations/`, `vision/scanners/watch_feed/`, `vision/scanners/inline_scan/`                                                                                                                                                                                                                                             | [Session replay](#session-replay)                                                 |
| Live project                     | `src/api/live.ts`                                                        | `GET /api/projects/{id}/`, once per project and session                                                                                                                                                                                                                                                                                                                           | `live_events_token` and `path_cleaning_filters`; [LIVE.md](LIVE.md#requests)      |
| Live users online                | `src/api/live.ts`                                                        | `GET https://live.us.posthog.com/stats` or `live.eu.posthog.com`, `Authorization: Bearer <live_events_token>`                                                                                                                                                                                                                                                                     | Plain `fetch` with no PostHog API budget; [LIVE.md](LIVE.md#requests)             |

`send()` also keeps the server clock offset from each response's `Date` header (`src/api/serverClock.ts`) and spends a token from the request's budget family (`src/api/budget.ts`); an empty bucket throws `BudgetExceededError` without sending.

`runQuery()` applies one deadline to the initial `POST query/` and every status poll. If the server does not answer in
time, the request is canceled and the caller gets a timeout error. Reviewer edits load artefact pages until the latest
reviewer assignment is found before sending the replacement list, so GitHub-only reviewers remain assigned.

OAuth scopes the app requests: `OAUTH_SCOPES` in `src/auth/oauth.ts`.

### Error tracking and replay scopes

The app asks for six more scopes for the Errors and Sessions screens. Views, the inbox and chats never need them.

| Scope                    | Why                                                                                                                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `error_tracking:read`    | The issues list, one issue, its events and spikes (`error_tracking/query/...`, `error_tracking/issues/{id}/`).                                                                                                     |
| `error_tracking:write`   | Resolve, suppress, reopen and assign an issue. It also covers the read.                                                                                                                                            |
| `session_recording:read` | The sessions list and one recording's metadata and events (`session_recordings/`).                                                                                                                                 |
| `replay_scanner:read`    | The AI summary and chapters of a recording (`vision/observations/`).                                                                                                                                               |
| `replay_scanner:write`   | Asking for a summary from the phone (`vision/scanners/inline_scan/`).                                                                                                                                              |
| `export:write`           | Rendering a recording as a video and reading the file (`exports/`). It also covers the read. It is not in `REPLAY_SCOPES`: a token without it still opens sessions, and only video playback shows its own message. |

`session_recording:write` is never requested: the phone does not change or delete recordings.
`ERRORS_SCOPES` and `REPLAY_SCOPES` in `src/api/scopeErrors.ts` hold the same lists, and `useFeatureAccess('errors' | 'replay')` reads them.
A server that drops a scope (the OAuth application's ceiling) gets the feature's "isn't available yet" state, not a broken screen.

## Error tracking

`src/api/errorTracking.ts` imports the generated issue-list request and response types. Other reads name the serializers in
`products/error_tracking/backend/presentation/views/` (`query_serializers.py`, `issues.py`, `spike_events.py`).
Mobile CI checks out the Signals and Error Tracking generated schemas. The compact `error_tracking/query/` endpoints are the ones the
MCP tools and agents use: they wrap `ErrorTrackingQuery`, `EventsQuery` and `ErrorTrackingBreakdownsQuery` and answer
typed, small payloads, so the phone does not post raw HogQL queries to `query/`.

| Call                | Endpoint                                                                                                  | Scope                  | Payload the app sends or reads                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Issues list         | `POST error_tracking/query/issues/`                                                                       | `error_tracking:read`  | `{ dateRange: { date_from: '-24h' \| '-7d' }, status: 'active', orderBy: 'users', orderDirection: 'DESC', limit: 15, offset: 0, volumeResolution: 0, assignee?: { type: 'user', id } }`; rows carry `id`, `name`, `description` (300 characters at most), `status`, `first_seen`, `last_seen`, `library`, `assignee { id, type }`, `aggregations { users, occurrences, sessions }`. Load more follows `nextOffset` while `hasMore` is true |
| Spikes              | `GET error_tracking/spike_events/?issue_ids=a,b&date_from=<ISO>&limit=100`                                | `error_tracking:read`  | `results[].issue.id`, `detected_at`; the web's issue list uses the same read for its spike marks                                                                                                                                                                                                                                                                                                                                           |
| One issue           | `GET error_tracking/issues/{id}/`                                                                         | `error_tracking:read`  | `id`, `status`, `name`, `description`, `first_seen`, `assignee`                                                                                                                                                                                                                                                                                                                                                                            |
| Impact and chart    | `POST error_tracking/query/issue/`                                                                        | `error_tracking:read`  | `{ issueId, dateRange, includeSparkline: true, volumeResolution: 24 \| 28 }`; reads `impact`, `sparkline`, `trend.direction`, `trend.change_percent`, `last_seen`, `library`, `latest_release`, `first_release`                                                                                                                                                                                                                            |
| Where it breaks     | The same endpoint with `includeBreakdown: true`                                                           | `error_tracking:read`  | `breakdown.occurrences` and `breakdown.top_values` (`path`, `url`, `screen`, `browser`, `os`, `app_version`). Its own request, because the server fails the whole response when the breakdown fails                                                                                                                                                                                                                                        |
| Frames and sessions | `POST error_tracking/query/issue_events/`                                                                 | `error_tracking:read`  | `{ issueId, dateRange, limit: 10, include: ['exception', 'stacktrace', 'environment', 'correlation'], onlyAppFrames: true }`; reads `$exception_list[].stacktrace.frames` (already symbolicated at ingestion: `resolved_name`, `source`, `line`), `$session_id`, `$browser`, `$os`, `timestamp`                                                                                                                                            |
| Linked report       | `GET signals/reports/?source_product=error_tracking&source_id={id}&limit=1&include_source_metadata=false` | `task:read`            | Error tracking signals carry the issue id as `source_id`                                                                                                                                                                                                                                                                                                                                                                                   |
| Status              | `PATCH error_tracking/issues/{id}/` `{ status: 'active' \| 'resolved' \| 'suppressed' }`                  | `error_tracking:write` | Answers the issue resource                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Assign              | `PATCH error_tracking/issues/{id}/assign/` `{ assignee: { type: 'user', id } \| null }`                   | `error_tracking:write` | `id` is the numeric user id from `@me`                                                                                                                                                                                                                                                                                                                                                                                                     |

None of these paths is in a `src/api/budget.ts` family, and none returns a `next_allowed_client_refresh` hint, so the
screens rely on TanStack staleness (60 seconds) and pull to refresh.
Pull to refresh discards later pages and reloads the first page. Spike reads are scoped to each loaded page, so
loading another page does not repeat the spike lookup for previous pages. New and Spiking filter the loaded rows;
an empty partial result offers Load more instead of claiming there are no matching issues in the project.
The Spiking filter waits for pending spike lookups and offers a retry when they fail. List sparklines are omitted;
the issue detail still requests its chart.
A 403 that names a missing scope goes to `reportScopeError(error, 'errors')`, and the screen shows `ViewsReauthState`.
`error_tracking/stack_frames/batch_get/` is not called: the frames in `$exception_list` already carry resolved names, and
the phone shows no code context.

## Session replay

`src/api/recordings.ts`, `src/api/replayVision.ts` and `src/api/replayVideo.ts`. Types are written by hand and name the
serializers they mirror: `SessionRecordingSerializer` in `posthog/session_recordings/session_recording_api.py`,
`ReplayObservationSerializer`, `InlineScanResponseSerializer` and `WatchFeedResponseSerializer` in
`products/replay_vision/backend/api/`, and `ExportedAssetSerializer` in `products/exports/backend/api/exports.py`. The
summary's `model_output` follows `SummarizerOutput` in `products/replay_vision/backend/temporal/scanners/summarizer.py`.

| Call                 | Endpoint                                                                                     | Scope                                            | Payload the app sends or reads                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| -------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sessions list        | `GET session_recordings/?limit=10&date_from=-7d`                                             | `session_recording:read`                         | Newest first (the server's default `start_time` order). Reads `id`, `distinct_id`, `recording_duration`, `start_time`, `end_time`, `click_count`, `console_error_count`, `start_url`, `person { name, distinct_ids, properties }`, `ongoing`, `activity_score`. Load more sends `next_cursor` as `after` while `has_next` is true                                                                                                                                                                                                                                                                                            |
| Worth watching       | `GET vision/scanners/watch_feed/?limit=5&date_from=-7d`                                      | `replay_scanner:read`, `session_recording:read`  | `results[].observation` and `results[].reason`. Starts after recordings load and never blocks their display. Enriches existing rows in place; other recommendations appear below the recordings without reordering them                                                                                                                                                                                                                                                                                                                                                                                                      |
| One recording        | `GET session_recordings/{id}/`                                                               | `session_recording:read`                         | The same fields. A 404 means the recording expired or never existed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Events timeline      | Two `POST query/` with a `HogQLQuery`, on the `replay` budget in `src/api/budget.ts`         | `query:read`                                     | One for `$pageview`, `$screen` and `$autocapture` clicks (`LIMIT 300`), one for `$rageclick` and `$exception` (`LIMIT 100`), each where `properties.$session_id = {session_id}`, between the recording's start and end padded by a minute, `ORDER BY timestamp`. The session id and the window are `values`, never query text. Reads the timestamp, the event, `$current_url`, `$pathname`, `$screen_name`, `elements_chain_texts`, `$exception_issue_id`, `$exception_types`, `$exception_values`, `$browser`, `$os`, `$geoip_city_name`                                                                                    |
| Summary and chapters | `GET vision/observations/?session_id={id}`                                                   | `replay_scanner:read`, `session_recording:read`  | Every scanner's observations of the session, newest first. The app uses the newest `succeeded` summarizer: `model_output.title`, `summary`, `chapters[] { kind, start_ms, end_ms, title }`, `key_moment_ms`, `notability`, `notability_reason`, plus `media[] { kind, position }` and `completed_at`. A `pending` or `running` summarizer means a summary is on its way                                                                                                                                                                                                                                                      |
| Frame                | `GET vision/observations/{id}/thumbnail/?chapter={n}`                                        | `replay_scanner:read`, `session_recording:read`  | A 302 to a signed object-storage URL. The app sends `redirect: 'manual'` and reads `Location`, so the bearer token never reaches the storage host; the image loads from the signed URL. Without `chapter` it is the observation's thumbnail                                                                                                                                                                                                                                                                                                                                                                                  |
| Summarize            | `POST vision/scanners/inline_scan/` `{ built_in: 'summarize_recording', session_ids: [id] }` | `replay_scanner:write`, `session_recording:read` | The web's Summarize button sends the same body, so both share one result. Answers 202 with `results[].scan_outcome`: `started`, `already_running`, `already_scanned`, `skipped_limit`, `skipped_quota`, `skipped_scanner_limit` or `failed`. A 400 means the organization has not approved AI data processing                                                                                                                                                                                                                                                                                                                |
| Video exports        | `GET exports/?session_recording_id={id}&export_format=video/mp4`                             | `export:read`                                    | The current user's exports of the session, newest first; the app reads the first page. It also checks `export_context.session_recording_id`, because a server that ignores the filters lists every export. It only reuses exports starting at zero whose requested duration covers the full recording. Missing range metadata is not reusable. It plays the newest finished one that has not expired (`has_content`, no `exception`, `expires_after` unset or later), else waits for the newest one that started rendering less than 75 minutes ago                                                                          |
| Render a video       | `POST exports/`                                                                              | `export:write`, `session_recording:read`         | `{ export_format: 'video/mp4', export_context: { session_recording_id, timestamp: 0, width: 1400, height: 600, filename: 'replay-{id}', duration, skip_inactivity: true } }`, the web player's whole-recording body, with `duration` in whole seconds. Only when no export is reusable, and never for a recording longer than 3 hours. Each one counts against the team's monthly video export cap: a 400 `{ export_limit_exceeded: [reason] }` shows the reason                                                                                                                                                             |
| Render status        | `GET exports/{id}/`                                                                          | `export:read`                                    | Every 4 seconds until `has_content` is true or `exception` is set. The server sets `exception` on a render older than its 75-minute workflow timeout. A finished render adds `video_duration_s` and `inactivity_periods[] { ts_from_s, ts_to_s, active, recording_ts_from_s, recording_ts_to_s }` to `export_context`; `src/features/replay/video/videoTime.ts` maps a session moment to a video second with them                                                                                                                                                                                                            |
| Video file           | `GET exports/{id}/content/`                                                                  | `export:read`                                    | A 302 to a signed object-storage URL that works for an hour. Sent with `redirect: 'manual'`, like the frame, so the bearer token never reaches the storage host, and the player loads the signed URL. The player renews it one minute before expiry and checks again when the app returns to the foreground, preserving the playhead, playback speed, and paused state. Transient renewal failures retry in the background while buffered playback continues. An actual playback failure offers a retry at the same playhead. Local dev serves the bytes from the API, so the player gets the API URL with the bearer header |

Session pagination deduplicates recording IDs. Pull to refresh reloads the first page and the optional feed.
A failed next page preserves the loaded rows and offers Try again.

After `started` or `already_running` the screen reloads the observations every 5 seconds while it is focused and the
app is in front, for at most 2 minutes. The app never sends `PATCH session_recordings/{id}/` (`viewed`), because that
needs `session_recording:write`, so opening a session on the phone does not mark it watched on the web.
A 403 that names a missing scope goes to `reportScopeError(error, 'replay')`, and the screen shows `ViewsReauthState`.
The timeline's queries spend the `replay` budget family (`runQuery({ budgetFamily: 'replay' })`, the same buckets as
`query`), not the Views `query` family, so Views refreshes and a session screen never block each other.

## Experiments

### Experiments list and reads

`src/api/experiments.ts` holds every experiments call behind `ExperimentsSource`.
`liveExperimentsSource` sends the calls, and `demoExperimentsSource` (`src/demo/experiments.ts`) answers them like the server.
The types come from `products/experiments/frontend/generated/api.schemas.ts`.
The app types by hand only two shapes that the generator leaves `unknown`: a metric `result` and the `ExperimentExposureQuery` response.
The server code is `EnterpriseExperimentsViewSet` in `products/experiments/backend/presentation/views.py`.

Reads need `experiment:read`.
`metrics_recalculation/` and every action need `experiment:write`.
The exposure query needs `query:read`, which the app already has.

`useFeatureAccess('experiments')` reads `EXPERIMENTS_SCOPES` in `src/api/scopeErrors.ts`.
If the OAuth application's ceiling does not include these scopes, the server drops them and the list shows "isn't available yet".
The app does not request `feature_flag:write`, `integration:read`, `activity_log:read` or `project:write`.

| Call           | Request                                                                | Notes                                                                                                                                                                                                                                                     |
| -------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Segments       | `GET experiments/?status=<status>&order=<order>&limit=20&offset=n`     | Running: `running`, `paused` and `exposure_frozen` by `-start_date`. `status=` takes one value, so the app sends three requests and merges them. More pages exist while one has `next`. Done: `stopped` by `-end_date`. Drafts: `draft` by `-created_at`. |
| Search         | The segment request with `search=<text>`                               | Only when the loaded pages do not hold the full segment. Otherwise the app filters the loaded rows.                                                                                                                                                       |
| One experiment | `GET experiments/{id}/`                                                |                                                                                                                                                                                                                                                           |
| Stored results | `GET experiments/{id}/metrics_recalculation/latest/`                   | A 404 means no results yet.                                                                                                                                                                                                                               |
| One run        | `GET experiments/{id}/metrics_recalculation/{run}/`                    | `completed_metrics` of `total_metrics` gives the progress.                                                                                                                                                                                                |
| Recalculate    | `POST experiments/{id}/metrics_recalculation/` `{ trigger: 'manual' }` | 201 starts a run. 200 returns the active run. A 429 within five minutes of the last run carries `Retry-After`.                                                                                                                                            |
| Running target | `GET experiments/{id}/running_time_target/`                            |                                                                                                                                                                                                                                                           |
| Health         | `GET experiments/{id}/health/`                                         |                                                                                                                                                                                                                                                           |
| Exposures      | `POST query/` with `ExperimentExposureQuery`                           | The same body as the web's `experimentLogic`.                                                                                                                                                                                                             |

A list row reads the experiment and its stored results only while the row is on screen, two reads at a time.
The experiment screen uses the same cache entries.
Row results stay while you scroll, until the project changes.
The list never starts a recalculation.
When server search fails, the list shows the error, and Retry and pull to refresh send the search again.

Every `experiments/` call, writes included, uses the `experiments` budget family in `src/api/budget.ts`.
It allows 120 calls a minute and 1,200 an hour, 25% of the published limit.
The exposure query uses the `query` family.

`differenceType` gives the units of a change: `relative` is a fraction of the control value, and `absolute` is in metric units.
It comes from `stats_config.<method>.difference_type`.
An interval with a null or non-finite bound gives no result.

### Experiment actions

The finish, launch, pause, resume, archive and edit conclusion sheets send these calls through `ExperimentsSource`.
The request bodies follow the web's `experimentLogic` and `products/experiments/backend/presentation/serializers.py`.
Every action needs `experiment:write`.
A cleanup PR (`open_cleanup_pr: true`) also needs `task:write`.

| Call            | Request                                                                                                                                    | Notes                                                                            |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Launch          | `POST experiments/{id}/launch/`                                                                                                            | 400 when the experiment is not a draft, or the flag has fewer than two variants. |
| Ship            | `POST experiments/{id}/ship_variant/` `{ variant_key, release_to_everyone, conclusion, conclusion_comment, open_cleanup_pr, repository? }` |                                                                                  |
| End             | `POST experiments/{id}/end/` `{ conclusion, conclusion_comment, open_cleanup_pr, repository? }`                                            | The flag does not change.                                                        |
| Cleanup target  | `GET experiments/{id}/flag_cleanup_target/`                                                                                                | Needs only `experiment:read`. The finish sheet reads it when it opens.           |
| Pause, resume   | `POST experiments/{id}/pause/`, `POST experiments/{id}/resume/`                                                                            |                                                                                  |
| Archive         | `POST experiments/{id}/archive/` `{}`                                                                                                      | 400 until the experiment ends.                                                   |
| Edit conclusion | `PATCH experiments/{id}/` `{ conclusion, conclusion_comment }`                                                                             | The app sends no `version`, so the server skips its concurrent-edit check.       |

Launch, ship, pause and resume change the flag through the approval gate.
When an approval policy applies, the server answers 409 with `code: 'approval_required'` or `'change_request_pending'`, and nothing changes.
Without `repository`, the server skips the cleanup PR for an `ambiguous` target, so the app sends `repository` only in that case.
The app never sends `set_repository_as_team_default` (needs `project:write` and project admin) or `disable_feature_flag` on archive (needs `feature_flag:write`).
A 403 for a missing `experiment:*` scope goes to `reportScopeError(error, 'experiments')`.
A missing `task:write` shows as an error in the sheet.

### Experiment screen

`src/features/experiments/ExperimentScreen.tsx` uses the reads above through `hooks.ts` and `detailHooks.ts`.
It needs no scope that the list does not need.

| Moment                        | Calls                                                                                                                    | Cadence                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| Open                          | The experiment and its stored results. A live experiment also reads the target, health and, after launch, the exposures. | Cached for 1 min. The target and health stay cached for 5 min.           |
| Pull, live experiment         | `POST metrics_recalculation/`, then `GET metrics_recalculation/{run}/`                                                   | Every 5 s while the screen is focused and the app is active, up to 2 min |
| Pull, 429                     | Read the stored results again, and count down `Retry-After`                                                              | Once                                                                     |
| Pull, other experiments       | Read again only: complete, draft and `exceeds_recalculation_age_limit`                                                   | Once                                                                     |
| Run that someone else started | Poll the `active_run` of the stored results                                                                              | As for a pull on a live experiment                                       |
| Launched less than 2 h ago    | Stored results and the exposure query. No recalculation.                                                                 | Every 60 s while focused                                                 |

The exposure query sends `as_of: query_to` from the stored results, like the web's `loadExposures`.
Then the exposure counts and the metric counts end at the same time.
Before the first stored results, and while watching, the query reads up to now.

The numbers follow the web's `MetricsView/shared/utils.ts`:

- The change is the midpoint of the interval.
- The server returns the chance that the variant is above control. For a `decrease` goal, the app shows `1 − chance_to_win`.
- A Bayesian result is significant when the chance passes `stats_config.bayesian.ci_level` in either direction (`is_decisive`).
  The About sheet explains significance by the chance, not by the interval.
- A Frequentist result is significant when the interval at `1 − frequentist.alpha` does not include 0.
- The sample ratio warning shows when `sample_ratio_mismatch.p_value` is below 0.001, the threshold in the web's `exposureHealth.ts`.
  It does not show when the `srm` health check is `not_applicable`.
- `sample_ratio_mismatch.expected` holds counts. The screen shows them as shares.

Chat opens `/chat` with `objectType: 'experiment'` and the experiment id, as the web's `SummarizeExperimentButton.tsx` does.
