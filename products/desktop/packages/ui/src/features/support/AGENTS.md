# Support

The support surface: a queue of Conversations tickets beside the open ticket, with a right rail that switches between ticket context and an agent thread. Behind the `desktop-support` flag, internal-first.

Do not confuse this with:

- **Inbox** (`features/inbox/`) — product signals and PR-shipping agents. A different product; reuse its patterns, not its stores.
- **Conversations in the PostHog web app** — the general-purpose ticket UI. It stays the system of record's own surface; this is an engineer-facing one.
- `support-sidebar-max` in the web app — the docs chat widget.

## What this surface owns, and what it does not

Ticket storage, delivery, SLA computation and assignment rules stay in `products/conversations` in posthog/posthog. This surface reads and writes that API and adds no state of its own beyond view state. Do not add a control that implies a capability the backend does not have.

The agent thread is an ordinary Desktop task, created through `TaskService` like any other. That is deliberate: model and effort selection, run streaming, presence, usage limits and the pull-request machinery all come for free, and anything added to tasks applies here without a change. The ticket points at its task through a tag (`ai-task:<id>`), encoded in one place — `@posthog/core/support/ticketTaskLink` — so the swap to a real field is a change to that file.

## Backend contracts worth knowing before you touch this

All under `products/conversations/backend` in posthog/posthog.

- `GET .../conversations/tickets/{id}/` — **not idempotent.** For a caller with editor access the backend clears the ticket's `unread_team_count` and invalidates the team's unread cache, so reading a ticket marks it read for everyone. Fetch it when a person opens a ticket; never on a timer, a prefetch or a list refresh. This is why `supportKeys` keeps lists and details in separate key namespaces: a list invalidation must not reach the open ticket's entry by prefix. Writes seed the cache from their own response instead of invalidating it.
- `GET .../tickets/{id}/messages/` — the thread, oldest first, `limit`/`offset` only, keyed on the ticket **UUID** and not its number. Reading it has no side effects, so this is the poll that carries liveness while a ticket is open.
- `POST .../tickets/{id}/reply/` — `{message, is_private}`. Returns **201** when it posted, **200** when it replayed an identical reply from the same author inside 120s, **409** while a concurrent identical send is still in flight. Throttled at 10/minute per user, far tighter than the rest of the API.
- `PATCH .../tickets/{idOrNumber}/` — status, priority, `snoozed_until`, tags, and `assignee` as `{type, id}` (integer id for a user, UUID for a role) or null. Assignment rides this endpoint even though the serializer marks it read-only. **Omit `status`** to let the backend apply its own snooze transitions; `predictTicketUpdate` in core mirrors them so an optimistic write matches the response.
- `GET .../tickets/unread_count/` — `{count}`, cached 30s server-side. Safe to poll.
- List params are flat and inconsistently shaped: statuses, priorities and assignees are comma-separated, tags are a JSON array, and the channel param is `channel_source` (`channel` is the saved-view spelling and is ignored). `view` takes a saved view's **short_id**, and explicit params override that view per field.

## Sending a reply

A reply reaches a customer, so the thread never shows an optimistic row: the server's own message is inserted on success. When a send fails in a way that leaves the outcome unknown — dropped connection, timeout, a concurrent identical send, a server error — the thread is re-read and searched for the message before the person is told anything, because resending a reply that did land sends it twice. A rejection that definitely wrote nothing, throttling included, surfaces as an error with the draft intact. The rules live in `@posthog/core/support/replyOutcome`; keep the recovery window in step with the server's.

## Layout

The queue lives in the `/support` layout route so it stays mounted while tickets change under it. The ticket occupies the middle; `TicketSidebar` is a fixed right column with two tabs, both kept mounted so switching never tears down a live agent session. The agent tab takes the front when a ticket already has a thread, because that is usually why someone returns to such a ticket.

## Ownership boundaries

- Components render. Hooks in `hooks/` wrap exactly one query or mutation.
- Domain rules — attention ranking, SLA state, snooze prediction, the task link, reply-failure classification — live in `@posthog/core/support/` as pure functions with `now` passed in, and are unit-tested there. Presentation-only mappings (labels, badge variants, class maps, relative times) live in `ticketPresentation.ts`.
- `supportQueueStore.ts` is view state only, and splits on display versus scope: the sort order and the open tab persist, because neither changes which tickets are fetched. The scope, search and applied view do not, because a queue that silently narrows itself after a relaunch, with the reason off screen, hides work.

## Domain rules worth knowing

- **Null priority means untriaged, not low.** Render it as its own state and never as a fourth step on the scale.
- **A role assignment is an unclaimed pool**, not a person; it reads "(pool)".
- **The resume signal** is `status ∈ {pending, on_hold}` with `unread_team_count > 0`: the customer came back and the ticket is actionable again. It outranks the SLA states in `ticketAttention`.
- Tickets carry customer data. Never let ticket content reach analytics properties, commit messages or notification bodies.
