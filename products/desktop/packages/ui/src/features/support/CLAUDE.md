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

## Layout

**The queue** (`SupportListView`) is a full-width column table over a bordered container:

- `QUEUE_COLUMNS` in `ticketPresentation.ts` is the column inventory — id, label, default visibility, the width/alignment classes the header cell and the row cell *both* apply, and the sort field the header toggles. `TicketRow` renders a cell per visible column by id; adding a column is one entry plus one `switch` case.
- `customer` is the one column with no toggle (`ALWAYS_VISIBLE_COLUMN_ID`), because it carries the `AttentionChip`. Hiding it would hide the reason a row ranks where it does, which is the surface's whole point.
- Each row leads with a 4px **SLA stripe** (`slaTone` → `SLA_STRIPE_CLASS`) so urgency reads down the list without parsing text. Tickets with no SLA get a transparent stripe rather than no stripe, so rows stay aligned. `slaTone`'s at-risk band is `SLA_AT_RISK_WINDOW_MS` from core — the same threshold the ranking uses, so the colour and the tier can never disagree.
- Toolbar: `QueueFilterMenu` (status / priority / channel / SLA / assignee, each a single-select the tickets endpoint actually supports), `QueueDisplayMenu` (order + column visibility), and a debounced search box. Applied filters become removable chips (`QueueFilterChips`), each chip's remove button carrying the whole filter set it produces so removal stays pure.
- **Column sorting is an override, never the default.** `applyQueueSort(ranked, null)` is the attention ranking; a `QueueSort` re-sorts that already-ranked array, so rows tying on the sorted column keep their attention order. The override is session-only (`supportQueueStore` persists columns, not sort) and the queue shows a one-click way back to attention order while it's active.

**The detail** (`TicketDetailView`) is header + thread + right column:

- Header pins identity and urgency: back, `#number`, channel glyph, subject over requester/email, the SLA countdown chip ("in 3h" / "2h overdue"), and the same `AttentionChip` the queue row showed.
- `TicketSidebar` is a fixed-width right column with two tabs, because the two halves answer different questions. **Ticket**: an Account card and a Ticket card (`TicketActions` pickers, then read-only channel context). **Activity**: the ticket's timeline and the customer's other tickets.
- Cards share `SidebarCard` chrome plus `CardRow` / `CardPickerRow`; a card with nothing to show returns `null` rather than collapsing.

Editable ticket fields use `PillPicker` (quill `DropdownMenu` behind a colour-coded pill), so status and priority read as their value rather than as a form control. Assignee is a `CardRow`, not a picker — the serializer refuses assignment writes.

Two things the sidebar derives rather than fetches, because the api-client has no endpoint for them:

- **Activity** is built from the thread we already load (`ticketActivityEntries`): opened, last customer message, last team reply, last internal note. PostHog's `activity_log` would give the full field-edit history; wire it here when the client gains the method.
- **Ticket history** matches the customer by `requesterKey` over a `search` for their email, since the list endpoint has no identity filter. The open ticket is always merged in, so the card can't read as if it doesn't exist.

Base UI note: `DropdownMenuLabel` is `Menu.GroupLabel` and throws at render outside a `DropdownMenuGroup` — a `DropdownMenuRadioGroup` is not a substitute. Typecheck won't catch it.

## Information architecture

| Surface | Route |
| --- | --- |
| Ticket queue | `/code/support` |
| Ticket detail (thread + meta) | `/code/support/$ticketId` |

`routes/code/support.tsx` is the flag gate (layout route): everything under `/code/support` renders only when `future-support` is enabled (default on in dev builds).

**Support has two entry points, because the app has two shells.** `ChannelsSidebar` renders either the code sidebar (`SidebarNavSection`, with `items/SupportItem.tsx`) or — under the spaces layout (`useChannelsLayout`, i.e. `code-spaces-layout` + `project-bluebird`) — the icon rail `canvas/components/ChannelNav.tsx`. It's an either/or, not a superset: a destination wired into only one shell is *invisible* in the other, with no type error to catch it. Both flags default on in dev, so the rail is what you actually see locally. Add nav destinations to both, and note the rail is a hardcoded list — the Customize-sidebar dialog only governs `SidebarNavSection`.

## Ownership boundaries

- Components render; hooks (`hooks/`) wrap exactly one query via `useAuthenticatedQuery`.
- Pure display logic lives in `ticketPresentation.ts` — deterministic, `now` passed in, unit-tested. That includes the column inventory, the filter→chip and filter→query-param mappings, the column-sort comparators, and the Tailwind class maps for SLA/status/priority. Add ranking logic to core, not here.
- `supportQueueStore.ts` is view state only: visible column ids (persisted) and the sort override (not persisted — a stale column order would silently bury today's urgent work).
- Ticket storage and business rules stay in `products/conversations` (posthog). Do not add frontend-only controls that imply a backend capability that doesn't exist.

## Domain rules worth knowing

- **Null priority means untriaged, not low.** Render "No priority" as its own state — an outlined pill, not a fourth fill — and sort it between medium and low (`applyQueueSort` reuses the ranking's weights), never at the bottom of the scale.
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
- It also covers the layout logic worth breaking: the at-risk boundary against `SLA_AT_RISK_WINDOW_MS`, column resolution (customer always in, canonical order), the sort override (attention preserved when unset, untriaged above low, absent SLA/assignee last in *both* directions), chip removal clearing exactly one filter, and the history merge that keeps the open ticket present.
- Rendering integration is covered by typecheck plus the running app. Typecheck does not catch Base UI composition errors (see the `DropdownMenuGroup` note above) — open new menus once in the app.
