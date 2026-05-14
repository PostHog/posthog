# @posthog/agent-janitor

Operational process for the PostHog agent platform.

Two responsibilities, one process:

1. **Janitor loop** — periodic sweep of the queue: reset stalled jobs, fail poison pills, clean up terminal rows, publish per-queue depth gauges. Owns the same `SessionQueueJanitor` from `@posthog/agent-core` that agent-runner used to host.
2. **Internal HTTP surface** — `/internal/sessions/*` endpoints that the PostHog app (Django) calls to render the sessions UI and to cancel sessions.

The runtime owns session state. Django **never** writes to `agent_sessions`; the queue row is the single source of truth and Django reads it through this service.

## Routes

| Method | Path                            | Purpose                                                                                                   |
| ------ | ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| GET    | `/internal/sessions/:id`        | Fetch a single session by queue id                                                                        |
| GET    | `/internal/sessions`            | List sessions filtered by `application_id`, `revision_id`, `status`, `team_id`, `created_before`, `limit` |
| POST   | `/internal/sessions/:id/cancel` | Cancel an `available` or `running` session                                                                |
| GET    | `/health`                       | Always returns `{ok: true}` while listening                                                               |
| GET    | `/metrics`                      | Prometheus scrape endpoint                                                                                |

All `/internal/*` routes are gated by the `x-internal-key` header (`AGENT_INTERNAL_API_SHARED_KEY`).

## Hard rules

- **No imports from `nodejs/`.** Cherry-pick by copy.
- **No Anthropic / Modal / Claude Agent SDK imports.** Same blast-radius rule as ingress.
- Reads + cancels only — never enqueues. Enqueueing is ingress (`/run`) and is intentionally separated.
