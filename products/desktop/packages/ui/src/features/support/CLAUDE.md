# Support (future-support)

The Support surface is the desktop home for **agent-assisted support engineering**: a ticket attention queue ("what do I work on") over the Conversations ticket product, with per-ticket checklists ("how do I work on it") arriving in later PRs. Plan: `docs/plans/future-support.md`.

Do not confuse this with:

- **Self-driving Inbox** (`features/inbox/`) — product signals and PR-shipping agents. Different product; reuse its patterns, not its stores.
- `[Support]`-prefixed PostHog dashboards — PostHog's internal support-team ops via Zendesk.
- `support-sidebar-max` — the Max docs-chat widget.

## Product model

The unit of work is an **attention decision**, not a ticket: resume an existing ticket (customer replied, agent handed back) vs pick something new. The queue is ranked by `rankQueue` in `@posthog/core/support/attention` — pure, deterministic for a fixed `now`, unit-tested per state. Every row renders an `AttentionChip` explaining its rank; an unexplained ranking gets ignored.

`agent-handed-back` is typed and ranked but never produced yet: it needs the `Task.ticket` linkage that ships with the server-side checklist PR (plan decision 5). The 30-minute re-prioritisation loop is still to come. Keep this file's Backend Contracts section current as those land.

Every attention state has its verb on the ticket detail: `TicketActions` (status/priority/snooze via PATCH) and `ReplyComposer` (human-typed reply or internal note via the reply action). Replies are never auto-sent and never AI-drafted (plan non-goals).

## Information architecture

| Surface | Route |
| --- | --- |
| Ticket queue | `/code/support` |
| Ticket detail (thread + meta) | `/code/support/$ticketId` |

`routes/code/support.tsx` is the flag gate (layout route): everything under `/code/support` renders only when `future-support` is enabled (default on in dev builds). The sidebar item (`sidebar/components/items/SupportItem.tsx`) gates on the same flag in `SidebarNavSection.tsx`.

## Ownership boundaries

- Components render; hooks (`hooks/`) wrap exactly one query via `useAuthenticatedQuery`.
- Pure display logic lives in `ticketPresentation.ts` — deterministic, `now` passed in, unit-tested. Add ranking logic to core (PR 2), not here.
- Ticket storage and business rules stay in `products/conversations` (posthog). Do not add frontend-only controls that imply a backend capability that doesn't exist.

## Domain rules worth knowing

- **Null priority means untriaged, not low.** Render "No priority" as its own (warning) state; never sort or style it as the bottom of the scale.
- **Assignment is one-of user/role** (DB check constraint). A role assignment is an unclaimed shared pool — rendered "(pool)", ranked differently later.
- **The resume signal**: `status ∈ {pending, on_hold}` AND `unread_team_count > 0` means the customer came back. This drives the PR 2 queue; the list already surfaces `unread_team_count`.
- Tickets carry customer PII. Never let ticket content reach PR descriptions, commit messages, or notification bodies.

## Backend Contracts

All under the Conversations product (`products/conversations/backend` in posthog):

- `GET /api/projects/{project_id}/conversations/tickets/` — paginated list; filters: `status`, `assignee`, `priority`, `sla`, `channel_source`, `search`, `order_by`.
- `GET /api/projects/{project_id}/conversations/tickets/{id}/` — single ticket.
- `GET /api/projects/{project_id}/conversations/tickets/{id}/messages/` — thread, oldest first, paginated. **Not in the generated OpenAPI client** — hand-typed as `TicketMessage` in `posthog-client.ts`; update both if the serializer changes.
- `GET /api/projects/{project_id}/conversations/tickets/unread_count/` — returns `{ count }`. The generated spec mis-annotates this as a full `Ticket`; the client method corrects it.
- `GET /api/environments/{project_id}/conversations/views/` — saved ticket views (note: `environments`, not `projects`).
- `PATCH /api/projects/{project_id}/conversations/tickets/{id}/` — triage writes; the surface only sends `status`, `priority` (nullable), `snoozed_until` (nullable). `assignee` is read-only on this serializer — assignment needs its own endpoint work.
- `POST /api/projects/{project_id}/conversations/tickets/{id}/reply/` — `{ message, is_private }`; `is_private=false` delivers to the customer over the ticket's channel, `true` stores a team-only note. Markdown, max 5000 chars, throttled server-side. **Not in the generated spec** — hand-typed in `posthog-client.ts`.

Generated types (`Ticket`, `TicketView`, `TicketAssignment`, …) come from `packages/api-client/src/generated.ts` and are re-exported through `posthog-client.ts`. The API serializer omits some model fields (`identity_verified`, `ai_triage`, `github_repo`) — don't assume model docs match the wire shape.

## Testing

- `ticketPresentation.test.ts` covers status/priority/assignee/SLA/requester rules (`it.each`), including the null-priority and role-vs-user cases.
- Rendering integration is covered by typecheck; queue/loop behaviors get their own tests in PR 2/3.
