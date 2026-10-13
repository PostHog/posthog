# Chat

The chat sheet talks to PostHog AI about one or more inbox reports, or about the inbox as a whole.

## Files

| File | Role |
| --- | --- |
| `src/api/conversations.ts` | Transport: request, SSE event parsing, typed message union, `fetchConversation`, `listConversations`, `chatKeys` |
| `src/features/chat/conversation.ts` | Pure reducer that folds stream events into the thread |
| `src/features/chat/contextPrompt.ts` | The prompt template, a port of the web's Today Ask prompt |
| `src/features/chat/chatErrors.ts` | Maps HTTP and network failures to thread copy |
| `src/features/chat/hooks.ts` | `useConversation({ initialConversationId? })`: send, stream, reconnect, stop, retry, reset, resume a stored chat, demo replies |
| `src/demo/chatThreads.ts` | Stored demo conversations, keyed by the ids in `src/demo/chats.ts` |
| `src/features/chats/` | The Chats screen: list, search, day groups and the `useChatList()` hook (see [DESIGN.md](DESIGN.md)) |
| `src/features/chat/webLinks.ts` | Web app URLs for reports, the conversation, insights and reply links |
| `src/features/chat/*.tsx` | `ChatSheet`, `Composer`, `ContextChip`, `MentionPopover`, `Thread`, `ChatMarkdown`, `ChatErrorBubble`, `ChatLinkCard`, `ChatProgressLine`, `ChatEmptyState` |

## Endpoint

`POST /api/projects/:project_id/conversations/` (`ee/api/conversation.py`, `ConversationViewSet.create`).

- Scope `conversation:write`. The sign-in scope list in `src/auth/oauth.ts` includes it.
- This is the LangGraph runtime. The sandbox runtime opens through `/conversations/:id/open/`,
  which declares no OAuth scopes, so an app token gets 403 there.
- Body: `{ conversation, trace_id, content }`.
  - `conversation` is a UUID the app generates once per sheet session. The server creates the row on the first message.
  - `trace_id` is a new UUID per request. The server echoes it on the human message.
  - `content` is the prompt (the typed question plus a context block), or `null` to reattach to a running turn.
  - The app sends no `ui_context`: `MaxUIContext` has no report key and rejects unknown keys.

## Framing

`text/event-stream` with `event:` and `data:` lines (parsed by `src/api/sse.ts`).
`: keepalive` comments arrive every 15 seconds and are ignored.
There is no terminal event: the turn ends when the server closes the body.

| Event | Data | Thread effect |
| --- | --- | --- |
| `conversation` | Conversation metadata | Sets the header title once the server generates one |
| `message` | One message, by `type` (below) | See the next table |
| `update` | `{ id, tool_call_id, content }` | Progress line on the assistant message `id`; creates a placeholder when the update arrives first. Object `content` (subagent updates) is ignored |
| `status` | `{ type: 'generation_error' }` | Ends the turn with an error entry and Try again |
| `approval` | Pending dangerous-operation card | A link entry: "PostHog AI needs your approval to continue. Approve or reject it in PostHog." |
| `notebook`, `sandbox`, other | | Ignored |

| `message.type` | Thread effect |
| --- | --- |
| `human` | Replaces the bubble with the same `trace_id` (falls back to the same text) and keeps the typed text; the echo carries the full prompt |
| `ai`, id `temp-N` | Streaming full-text snapshot: replaced in place by id, within the current turn, status `loading` |
| `ai`, UUID id | Final message: replaces the same id, else the oldest loading snapshot of the turn, else appends. Status `completed` |
| `ai` with empty text | A tool-call step. Not drawn; its progress shows in the status line |
| `ai/failure` | Error entry with the server copy (or "Something went wrong. Try again.") and Try again |
| `ai/artifact` | Link entry, "Chart: {name}" or "Notebook: {title}", with Open in PostHog (the insight for `source: insight`, else the conversation in the web app) |
| `tool` | Ignored. `ui_payload` only drives web tools the app does not have |
| `ai/reasoning`, `ai/viz`, `ai/planning`, others | Ignored |

When the body closes, loading entries complete and progress lines clear.
A turn that produced no reply at all ends with "No reply came back. Try again."

## Turn control

- **One turn at a time.** Send is disabled while a reply streams; the send button becomes Stop.
- **Stop** aborts the fetch. App tokens cannot call `PATCH .../cancel/`, so the run finishes on the server.
- **409 on send** means a stopped turn is still running. The app takes the new bubble back,
  reattaches with `content: null` to show the end of that turn, then sends the message again.
- **Reconnect.** When the connection drops after the stream opened, the app reattaches with
  `content: null` and a new `trace_id`, waiting one more second per attempt, up to 15 attempts.
  The server replays the turn from its start, so the first replayed event cuts the thread back to
  the user's message and the replay rebuilds it.
  A 400 on reattach means the turn ended while the app was away: the app loads
  `GET conversations/:id/` and rebuilds the thread from it.
  A drop before the stream opens is not retried on its own, because the server may never have
  seen the message; the error entry offers Try again.
- **Try again** removes the error entry and resends the last prompt with a new `trace_id`.
  After a mid-stream failure the stored conversation then holds the message twice, as on the web.
- **New chat** (the compose button in the header) aborts any stream and starts a new conversation id.
- `mobile_chat_sent` is captured on each send with `report_count`.

## Context template

`chatPrompt(question, context)` ports `todayAskPrompt` from
`frontend/src/scenes/project-homepage/today/todayAskPrompt.ts` and copies
`REPORT_DISCUSSION_STATE_INSTRUCTIONS` and `NO_CHECKOUT_INSTRUCTIONS` verbatim from
`products/signals/frontend/inbox/inboxTaskKickoffLogic.ts`.

```text
{question}

<posthog_context>
#### Context from the Inbox report I am reading      (reports, plural, for several)

- Report: [{title}]({web url})                        (or "{title} (id `{id}`)" without a URL)
- Priority: {priority}                                (when set)
- Status: {status}                                    (when known)
- Pull request: {url}                                 (when set)
- Summary:
  {summary, first 1500 characters, indented}         (when known)

  ...one group per attached report...

The report link ends with the report id. Use that id with the inbox MCP tools.

If my message is a question, answer it. If it asks for action, carry the action out and summarize what you did.

{REPORT_DISCUSSION_STATE_INSTRUCTIONS}
    or, when any attached report cannot be acted on:
Answer my message as a question about this report.   (these reports, for several)

{NO_CHECKOUT_INSTRUCTIONS}
</posthog_context>
```

- `canAct` comes from `ReportView.canAct` (the web's `isActionCapableReport`). A report that has not loaded counts as not actionable.
- Server `suggested_prompts` replace the default chips only for one attached report the agent may act on, as on the web.
- Each attached report's chip loads the report with `useReport`, so the prompt has its summary and status.
- With no report attached, the prompt lists up to 20 inbox rows under `#### Context from my PostHog inbox`
  (`N. [title](url) (source; state: open; an agent is waiting for my answer)`), so "What needs me today?" has something to answer from.
- Escaping: `[` and `]` in titles are backslash-escaped. `<posthog_context`, `<posthog_trusted_context` and
  `<posthog_untrusted_context` (and their closing tags) in titles, summaries and the question become `<\posthog_…`.
- The bubble shows only the typed text. `stripInjectedContext` removes the block from server echoes and stored conversations.
- The context goes with every message while the chip stays attached, because the chip says it is attached.

## Rendering

- Assistant text renders as markdown with `react-native-markdown-display`, styled from `src/ui/tokens.ts`:
  inline code in the mono font on `sunken`, fenced code in a bordered block, links in ink and underlined.
- `html: false`, so raw HTML in a reply shows as text. Images are dropped.
- Relative links such as `/project/2/insights/abc` open on the signed-in host. Only http(s) links open.
- The status line under the thread shows the latest tool progress, "Thinking…", or "Reconnecting…".

## Limits

- **No server cancel.** Stop only stops reading.
- **404 until titled.** `GET conversations/:id/` returns 404 until the server generates a title, so a
  reconnect that finds the turn already over in the first seconds of a new conversation cannot load the reply
  and shows "The connection dropped before the reply finished. Try again."
- **AI consent is not checked.** PostHog enforces `organization.is_ai_data_processing_approved` only in the web client.
  The auth store does not expose the flag, so the app shows no consent notice. See GAPS.md.
- **No report tools.** The LangGraph agent has no inbox MCP tools, so the prompt inlines each summary.
  The ported instructions still name those tools. See GAPS.md.
- **Approvals, forms and charts** open in the web app.
- **Sandbox sessions open in the web app.** The Chats list shows them, but the sheet only resumes LangGraph conversations.

## Resuming a chat

The Chats screen opens the sheet with `conversationId`.
The hook loads `GET conversations/:id/` (or the demo thread), dispatches `hydrated`, and captures `mobile_chat_resumed`.
While it loads, the sheet shows "Loading chat" and send is disabled.
A failed load shows "Couldn't load this chat" with Try again; a 404 says the chat no longer exists.
A stored conversation whose status is `in_progress` reattaches with `content: null` after loading, so the running turn plays to its end.
New messages keep the stored id, so they append to that conversation on the server.
New chat (the compose button) drops the stored id and starts a fresh conversation, as before.

## Chats list

`useChatList()` (`src/features/chats/hooks.ts`) merges two sources, like the web app's Chats pane:

- `GET conversations/?limit=30`: the caller's own titled LangGraph conversations, newest first.
- `GET tasks/?created_by={user id}&ordering=-last_activity_at&basic=true&limit=30`: the caller's sandbox sessions.
  `created_by` takes the numeric user id, which `GET /api/users/@me/` returns as `id`; a session restored from before the app stored it skips this source until the account reloads.

`chatListFromSources` (`src/model/adapters/chats.ts`) drops archived sessions, drops a conversation whose `task.id` is a listed session, sorts by last activity and keeps 30 rows.
`chatGroups.ts` labels rows by local calendar day (Today, Yesterday, a weekday, "Oct 3", "Oct 3, 2025", Earlier) and filters titles on the device.
When one source fails and the other loads, the list shows what loaded and a "Some chats didn't load." line; a 403 or 404 from tasks means the user has no sessions and shows no line.
Regaining focus (closing the sheet) invalidates the list, so a chat that got its title while the sheet was open appears.

## Demo mode

The demo plays a scripted reply through the same reducer: a tool step with a progress line,
streamed snapshots, then the final message. Stop and New chat work the same way.
