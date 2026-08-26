# Support

Conversations tickets in Desktop: a queue beside the open ticket, with a right rail that switches between ticket context and an agent thread. Behind the `desktop-support` flag, internal-first.

Not to be confused with `features/inbox/` (product signals and PR-shipping agents), or with the Conversations UI in the PostHog web app, which stays the general-purpose surface.

## What this owns

Nothing about tickets. Storage, delivery, SLA computation and assignment rules live in `products/conversations` in posthog/posthog; this reads and writes that API and keeps only view state. Don't add a control that implies a capability the backend lacks.

The agent thread is an ordinary Desktop task created through `TaskService`, rendered with `EmbeddedSessionView`. Model and effort selection, streaming, presence, usage limits and the pull-request machinery therefore apply here without anything support-specific. The ticket points at its task through an `ai-task:<id>` tag because Conversations has no field for it; `@posthog/core/support/ticketTaskLink` is the only place that knows, so a real field replaces it there.

## Backend contracts that shape this code

- `GET .../tickets/{id}/` clears the ticket's `unread_team_count` for the whole team and invalidates the team's unread cache. So the detail query never polls or refetches in the background, writes seed the cache from their own response, and `supportKeys` keeps lists and details in separate namespaces — a list invalidation must not reach the open ticket by prefix.
- `GET .../tickets/{id}/messages/` has no side effects, so the thread poll is what carries liveness while a ticket is open.
- `POST .../tickets/{id}/reply/` replays an identical reply from the same author for 120s instead of posting twice, and is throttled at 10/minute. Resending after a failure is therefore safe, which is why there is no client-side reconciliation.
- `PATCH .../tickets/{id}/` takes `assignee` as `{type, id}` despite the serializer marking it read-only. Omit `status` and the backend applies its own snooze transitions; the response is authoritative.
- Assignment reads and writes are not the same shape. A write needs an integer user id; a read returns the user id on `assignee.id` and gives `assignee.user` only an `email` — no id and no name. Compare identity through `assignee.id`, and never expect a field on `assignee.user` that the generated `Record<string, string>` will happily let you write.
- List params are flat and unevenly shaped: statuses and assignees comma-separated, tags a JSON array, channel as `channel_source`, and `view` as a saved view's short_id.

## Rules worth keeping

- Null priority means untriaged, not low.
- A role assignment is an unclaimed pool, not a person.
- Tickets carry customer data: keep it out of analytics properties, commit messages and notification bodies.
