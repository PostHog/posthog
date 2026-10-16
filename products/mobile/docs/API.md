# API

Every request goes through `src/api/client.ts`: it prefixes the host, adds the bearer token,
sets `X-PostHog-Client-Platform: mobile`, refreshes the token once on a 401, and throws
`ApiError` with the server's `code` and `detail` on any other failure.
`projectPath('signals/reports/')` builds `/api/projects/{projectId}/signals/reports/`.
Streams use `apiStream` (expo's fetch, so the body streams on native) and `src/api/sse.ts`.

Most existing types are written by hand per module and name the Django serializer they mirror.
PR checks use `PullRequestChecksResponseApi` from the Signals generated schemas. New API
types should come from the generated schemas; update the Django serializer and run
`hogli build:openapi` when those contracts change. Mobile CI includes the Signals schema
file for typechecking, and its type-only import adds nothing to the native bundle.

| Domain | Module | Endpoints | Notes |
| --- | --- | --- | --- |
| Account | `src/api/users.ts` | `GET /api/users/@me/`, `GET /api/organizations/{id}/` | [AUTH.md](AUTH.md) |
| OAuth | `src/auth/oauth.ts` | `/oauth/authorize`, `/oauth/token`, `/oauth/revoke` | PKCE public client |
| Inbox and reports | `src/api/reports.ts` | `signals/reports/for_you/`, `.../{id}/`, `.../signals/`, `.../artefacts/`, `read_state/`, `.../state/`, `.../reviewers/`, `available_reviewers/` | [DATA.md](DATA.md) |
| Today | `src/api/today.ts` | `today/reports/{id}/page/` | 403 or 404 means the project lacks Today; the report screen shows signals instead |
| Tasks | `src/api/tasks.ts` | `tasks/`, `tasks/{id}/` (`PATCH { archived }` archives a chat), `tasks/{id}/run/` (a chat's resume adds `resume_from_run_id` and `pending_user_message`; `pending_user_artifact_ids` carries staged files), `.../runs/{runId}/`, `.../logs/`, `.../stream/`, `.../command/` (`user_message`, with `artifact_ids` for files; `set_config_option`, `permission_response`, `cancel`) | [HANDOFF.md](HANDOFF.md), [CHAT.md](CHAT.md) |
| Chat attachments | `src/api/tasks.ts`, `src/features/chat/attachments/uploadAttachments.ts` | `tasks/{id}/staged_artifacts/prepare_upload/`, `tasks/{id}/staged_artifacts/finalize_upload/`, `.../runs/{runId}/artifacts/prepare_upload/`, `.../runs/{runId}/artifacts/finalize_upload/`, all `task:write`; then a presigned S3 `POST` with no PostHog auth | [CHAT.md](CHAT.md#attachments) |
| Push | `src/api/pushTokens.ts` | `/api/users/@me/push_tokens/`, `.../unregister/` | [PUSH.md](PUSH.md) |
| Views pins | `src/api/shortcuts.ts` | `file_system_shortcut/`, `.../{id}/` | [VIEWS.md](VIEWS.md) |
| Views dashboards | `src/api/dashboards.ts` | `dashboards/`, `dashboards/{id}/?refresh=force_cache` | [VIEWS.md](VIEWS.md) |
| Views insights | `src/api/insights.ts` | `insights/`, `insights/{id}/`, `insights/viewed/` | [VIEWS.md](VIEWS.md) |
| Web analytics, people at a point | `src/api/webAnalytics.ts`, `src/api/actors.ts` | `query/` (`WebOverviewQuery`, `ActorsQuery`) | [VIEWS.md](VIEWS.md) |

`send()` also keeps the server clock offset from each response's `Date` header (`src/api/serverClock.ts`) and spends a token from the request's budget family (`src/api/budget.ts`); an empty bucket throws `BudgetExceededError` without sending.

`runQuery()` applies one deadline to the initial `POST query/` and every status poll. If the server does not answer in
time, the request is canceled and the caller gets a timeout error. Reviewer edits load artefact pages until the latest
reviewer assignment is found before sending the replacement list, so GitHub-only reviewers remain assigned.

OAuth scopes the app requests: `OAUTH_SCOPES` in `src/auth/oauth.ts`, listed in [AUTH.md](AUTH.md#scopes).
