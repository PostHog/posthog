# API

Every request goes through `src/api/client.ts`: it prefixes the host, adds the bearer token,
sets `X-PostHog-Client-Platform: mobile`, refreshes the token once on a 401, and throws
`ApiError` with the server's `code` and `detail` on any other failure.
`projectPath('signals/reports/')` builds `/api/projects/{projectId}/signals/reports/`.
Streams use `apiStream` (expo's fetch, so the body streams on native) and `src/api/sse.ts`.

Types are written by hand per module and name the Django serializer they mirror.
The app reads a small, stable slice of each endpoint, so generated types were not worth a
second toolchain. Regenerate the intent when a serializer changes: search the module for the
serializer name.

| Domain | Module | Endpoints | Notes |
| --- | --- | --- | --- |
| Account | `src/api/users.ts` | `GET /api/users/@me/`, `GET /api/organizations/{id}/` | [AUTH.md](AUTH.md) |
| OAuth | `src/auth/oauth.ts` | `/oauth/authorize`, `/oauth/token`, `/oauth/revoke` | PKCE public client |
| Inbox and reports | `src/api/reports.ts` | `signals/reports/for_you/`, `.../{id}/`, `.../signals/`, `.../artefacts/`, `read_state/`, `.../state/`, `.../reviewers/`, `available_reviewers/` | [DATA.md](DATA.md) |
| Today | `src/api/today.ts` | `today/reports/{id}/page/` | 403 or 404 means the project lacks Today; the report screen shows signals instead |
| Tasks | `src/api/tasks.ts` | `tasks/`, `tasks/{id}/`, `tasks/{id}/run/` (a chat's resume adds `resume_from_run_id` and `pending_user_message`), `.../runs/{runId}/`, `.../logs/`, `.../stream/`, `.../command/` (`user_message`, `set_config_option`, `permission_response`, `cancel`) | [HANDOFF.md](HANDOFF.md), [CHAT.md](CHAT.md) |
| Push | `src/api/pushTokens.ts` | `/api/users/@me/push_tokens/`, `.../unregister/` | [PUSH.md](PUSH.md) |

OAuth scopes the app requests: `openid profile email user:read user:write organization:read
project:read task:read task:write today:read conversation:write`.
