# Chat

The chat sheet talks to PostHog AI on the task runtime, as the web app's side-panel chat does.
Every chat is a task with interactive runs in a sandbox.
A new chat creates the task on its first message; the Chats list reopens one by its task id.
The protocol below follows the web's `taskTrackerSceneLogic.ts`, `runInteractionLogic.ts` and `runStreamLogic.ts` in `products/posthog_ai/frontend`.

## Files

| File | Role |
| --- | --- |
| `src/features/chat/ChatSheet.tsx` | The sheet: header, thread or empty state, composer, the options reducer, draft restore |
| `src/features/chat/session/useSession.ts` | `useSession({ taskId?, runId? })`: create, follow, send, sync options, resume, stop, answer, reset, demo replies |
| `src/features/chat/session/sessionRun.ts` | Pure request bodies: the create shapes, run fields, the `set_config_option` plan, the tracked run config |
| `src/features/chat/session/sessionReducer.ts` | Folds run log lines and stream frames into the thread, as the web's `foldLogFromCheckpoint` does |
| `src/features/chat/session/sessionDisplay.ts` | Groups thoughts and tool calls into activity rows, error copy |
| `src/features/chat/session/SessionThread.tsx` | The thread, its rows, the PR card and the status line |
| `src/features/chat/session/SessionDecisionPanel.tsx` | The notice line and a pending question, plan approval or permission |
| `src/features/chat/chatRunOptions.ts` | `ChatRunOptions` (model and permission mode), its reducer, the chip label, seeding from a run |
| `src/features/chat/ChatOptionsSheet.tsx` | The Model and Mode pages in a sheet over the chat |
| `src/features/chat/contextPrompt.ts` | The leading context blocks, `bareQuestion`, `stripInjectedContext` |
| `src/features/chat/chatErrors.ts` | Maps HTTP and network failures to copy, including the PostHog Desktop gate |
| `src/features/chat/*.tsx` | `Composer`, `ContextChip`, `MentionPopover`, `ChatEmptyState`, `ChatMarkdown`, `ChatErrorBubble`, `ChatProgressLine`, `UserBubble` |
| `src/features/chats/` | The Chats screen: list, search, day groups and `useChatList()` (see [DESIGN.md](DESIGN.md)) |
| `src/demo/sessionThreads.ts` | Demo run logs keyed by the demo task ids in `src/demo/chats.ts`, and the demo replies |

The transport is `src/api/tasks.ts`, shared with the hand-off (see [HANDOFF.md](HANDOFF.md)).
Every request carries `X-PostHog-Client-Platform: mobile`, so `run/` never reuses a warm run a web composer booted.

## Composer drafts

Text and attached report IDs are saved separately for each task, each report discussion, and
the new-chat composer. Native drafts use encrypted device storage, scoped to the account,
host and project, with at most 50 drafts per project. Changes save after 400 ms of idle time
and flush when the composer closes or the app backgrounds. Opening a saved chat restores its
draft after storage loads.

A successful send clears the submitted text. A failed send keeps it, and a delayed completion
does not replace text typed for a later message. Sign-out or session expiry clears the account's
drafts. Demo drafts stay in the current composer; the web preview stores drafts in memory only. Photo
attachments are still unavailable; this does not enable the dimmed Attach control.

## Rich replies

PostHog object tags render as inline links to the selected host and project. Standalone
`display="block"` insight tags show the saved name and description; SQL tags show a three-line
preview with Show all. Insight summaries use `refresh=force_cache`, so opening a reply does not
run its insight queries. A reply renders at most ten cards, then uses inline links. Unknown
object kinds keep their labels, tags inside code stay literal, and unfinished tags stay hidden
while the reply streams. The object registry is generated from `posthog/object_tags/kinds.py`
into this app so standalone builds do not depend on the desktop app.

Closed Mermaid fences render offline in a native WebView. The bundled renderer uses strict
mode and a policy that blocks network requests; navigation is disabled. Wide diagrams scroll
horizontally. Incomplete, invalid, or remote-image diagrams stay as code. The web preview also
uses the code fallback. Adding this renderer requires a new native build with
`react-native-webview` before distributing an update that uses it.

Insight summaries need the `insight:read` OAuth scope. Existing sessions need a new sign-in,
and the server's mobile OAuth application must allow the scope; see [AUTH.md](AUTH.md).

## Starting a chat

The first send creates a task, then starts an interactive run on it.
Both calls go through `withWarmRetry`, which retries a 503 `warm_run_activation_unavailable` with the server's retry token.
The bubble shows at once and is taken back if the start fails.

Two create shapes (`chatStartRequests` in `sessionRun.ts`):

- **PostHog AI chat** (no report, or more than one report attached). `POST tasks/`:

  ```json
  { "title": "", "description": "<bare question>", "origin_product": "posthog_ai",
    "initial_permission_mode": "auto", "pending_user_message": "<context blocks>\n\n<question>" }
  ```

  The server generates the title from `description` in the create request, so the response already carries it.
  The app sends no `branch` and no `repository`, so the create never claims a warm run.
- **Inbox "Discuss"** (exactly one attached report). `POST tasks/`:

  ```json
  { "title": "<report title>", "description": "<prompt>", "origin_product": "signal_report",
    "signal_report": "<report id>", "signal_report_task_relationship": "discussion",
    "signal_report_discussion_question": "<question as typed, at most 4000 characters>",
    "pending_user_message": "<prompt>" }
  ```

  The server exempts a repo-less report discussion from the PostHog Desktop gate.
  `signal_report_discussion_question` is the trimmed question as typed, without the prompt's tag escaping, cut at 4000 code points.
  Every later fresh run of a task with a `signal_report` carries `run_source: "signal_report"` and `signal_report_id`, also when the Chats list opens it.
  It counts toward the report's discussion task limit (see [Errors](#errors)).

Then `POST tasks/{t}/run/`, unless the create answered with a `latest_run`:

```json
{ "mode": "interactive", "pending_user_message": "<context blocks>\n\n<question>", "initial_permission_mode": "auto" }
```

- `mode: "interactive"` is required: only interactive runs relay approvals and questions to the client.
- A picked model adds `runtime_adapter`, `model` and `reasoning_effort` (left out for a model without effort control), and maps the mode onto that harness.
  An untouched model sends only the mode, so the server applies the stored default.
- The app follows `run.id` from the response (`latest_run` on older servers).
- A refused run (any 4xx, or a 503) deletes the task it just created with `DELETE tasks/{t}/`, so no empty row stays in the Chats list.
  A 5xx other than 503 or a lost connection may still have started a run, so the task stays, and the next message first looks for that run (see [Follow-ups and resume](#follow-ups-and-resume)).
- Closing the sheet or tapping New chat does not abort the create or the run start, so the app always learns the task id and whether a run started.
  When the create finishes after the chat was dropped, the app deletes the new task and starts no run.

## Options

The composer has a Model chip and a Mode chip after `@`.
They open `ChatOptionsSheet` with the hand-off's `ModelPage` and `ModePage`.
`mobile_chat_option_changed` is captured with `option` (`model`, `effort` or `mode`) only.

- **Seeding.** When a chat opens, or the run's config becomes known, the sheet seeds the options from `session.runConfig`:
  the run's model and effort as a pinned model, and its permission mode.
  A run with no known harness or model seeds "Default"; an unknown mode seeds Auto.
  Seeding stops once the person picks anything in this sheet, and New chat starts seeding again.
  While seeding, the Mode chip follows the mode the stream reports (`current_mode_update`), also for a run the app started.
  After a pick, a new mode from the stream still replaces the picked mode, as the web drops its mode override: the agent can leave Plan on its own when a plan is approved.
- **Enabled** while the agent is idle, the history has loaded, no send is in flight and no decision waits, also on an open chat.
- **One harness per run.** A live run cannot switch between Claude Code and Codex.
  On an open chat the Model page lists only the models of the run's harness, and an untouched model keeps that harness.
  The hook still refuses a cross-harness pick with a notice.
- **The mode that is sent.** The Mode chip shows the mode mapped onto the harness the next message runs on (`chatPermissionMode`), and the sheet sends that mode.

### Live changes: `set_config_option`

A pick alone sends nothing.
On the next message to a live run, `useSession` first sends one command per changed value, in the web's order (model, effort, mode):

```json
{ "jsonrpc": "2.0", "method": "set_config_option", "params": { "configId": "model", "value": "claude-opus-5-5" } }
```

- "Changed" means different from what the run last had: what it started with, then each change the app applied (`TrackedRunConfig`).
  A mode the app set wins over the mode the stream reported before it, until the stream reports a mode again; then the stream's mode wins, as the web clears `sentMode` on `setCurrentMode`.
- The starting mode is the run's `state.initial_permission_mode` from the `run/` response, which can differ from the mode sent.
- Each change is recorded as it succeeds, so a later failure resends only what did not go out.
- 503 `sandbox_not_ready` retries for up to 10 seconds, honoring `Retry-After`.
- 409 means the run ended. The message then starts a resume run that carries the options.
- A 400 (such as a model outside the run's gateway pin), a 502, or a JSON-RPC `error` in the body stops the send before its `user_message`, shows the notice and restores the draft.

## Follow-ups and resume

- **Live run.** `POST tasks/{t}/runs/{r}/command/` with `user_message` and the context-wrapped text.
  Success is `result.queued`. The bubble moves to where the turn starts when the agent echoes it.
- **No run known.** After a first run that failed with a 5xx or a lost connection, or on a task opened without a run, `GET tasks/{t}/` comes first.
  A live `latest_run` gets the message and is followed; an ended one is resumed. Only a task with no run gets a fresh run.
- **Ended run, or a 409 on `user_message`.** `POST tasks/{t}/run/` with `mode: "interactive"`, `resume_from_run_id`, `pending_user_message`, and the run fields.
  An untouched model sends no triple, so the server keeps the previous run's selection; the mode maps onto the previous run's harness.
  No `branch`: a resumed run keeps its base branch.
- One send at a time. While the agent works, Stop replaces Send.
- `mobile_session_sent` is captured with `new_task`, `resumed_run`, `report_count`, `model`, `reasoning_effort` and `permission_mode`.

## Reading a run

- `GET tasks/{t}/` gives the title and the latest run. With a `runId` the sheet follows that run through `GET tasks/{t}/runs/{r}/`.
- **Ended run.** `GET tasks/{t}/runs/{r}/logs/` returns the whole resume chain as JSON lines, folded into the thread.
- **Live run.** `GET tasks/{t}/runs/{r}/stream/` without a cursor replays the stored log, then streams.
  Reconnects follow the hand-off rules (see [HANDOFF.md](HANDOFF.md)); a replay after a lost cursor rebuilds the thread.
- `mobile_session_resumed` is captured with the run status.

## Stop

Stop sends the `cancel` command (`{ "jsonrpc": "2.0", "method": "cancel" }`), which interrupts the turn and keeps the run alive.
The app sends it only after the stream showed the agent generating, because a cancel before that drops the run's first message; until then the notice says "The agent hasn't started yet."
A JSON-RPC `error` in the answer shows "Couldn't stop this run. Try again."
`mobile_session_stopped` is captured.

## Decisions

Permission requests go through the hand-off tool policy (`toolPolicy.ts`, see [HANDOFF.md](HANDOFF.md#tool-policy)):
the app allows built-in tools and PostHog `exec` calls on the person's behalf and asks about the rest.
A question, plan approval or permission shows in `SessionDecisionPanel` and replaces the composer while it waits.
The answer goes as a `permission_response` command and shows in the thread as the person's bubble.

## Errors

- A send, answer or stop that fails shows one notice line above the composer.
  A failed send also sets `unsentText`; the sheet puts it back into an empty input once.
- **PostHog Desktop gate.** `run/` and `user_message` answer 403 `code_access_required` for a user the gate refuses.
  The message is under `error`, and the app shows it as is, because it names the reason (Startup plan, prepaid credits).
  A 503 `desktop_access_unavailable` says "We couldn't verify PostHog Desktop access. Try again."
  A 429 `usage_limit_exceeded` or `billing_limit` shows the server copy.
  `cancel` and `set_config_option` are not gated. Only the Inbox "Discuss" shape is exempt.
- **Report discussion limit.** A one-report chat counts toward the report's discussion task limit.
  `POST tasks/` and `run/` answer 429 `signal_report_task_cap` with the copy under `error`; the app shows it, else "This report has reached its chat limit. Try again later."
- A 400 shows the server copy (`detail` or `error`, such as "Invalid resume_from_run_id" or a model the account cannot use), else a generic line.
- A 502 "Failed to queue" says the message did not reach the agent.
- The run's own failure (`error_message`, `_posthog/error`) shows inline in the thread.

## Context block

`chatPrompt(question, context)` ports the web's `wrapWithPosthogContext`.
The web thread strips only leading blocks, so the blocks lead and the question follows.

```text
<posthog_trusted_context>
- A user sent the message after this block about the PostHog Inbox report at {report url}. If it is a question, answer it; if it asks for action, carry the action out and summarize what you did.
- {REPORT_DISCUSSION_STATE_INSTRUCTIONS}
- {NO_CHECKOUT_INSTRUCTIONS}
</posthog_trusted_context>
<posthog_untrusted_context>
{the web's hardening header}
- signal_report {report id} ("Report: {title}")
{the web's reminder}
</posthog_untrusted_context>

{question}
```

- The trusted block goes only with attached reports. Its first line names the report by the web URL the app builds from the signed-in host, as the web's `discussReportInstructions` does.
  When the report cannot be acted on, the first line becomes "Answer this question about the PostHog Inbox report at {report url}. The question is the message after this block." and the state instructions drop out.
- The web has no framing for several reports. The app names them all ("these PostHog Inbox reports: {url}, {url}") and adds "The instructions below speak of one report. Apply them to each of these reports on its own."
- With no report attached, the first message of a new chat lists up to 20 inbox rows as `signal_report` lines in the untrusted block.
  Follow-ups and opened chats send no inbox list.
- The agent reads report details through the inbox MCP tools, so the prompt carries no summaries.
- `defang` escapes context tags and line breaks in every item field; `bareQuestion` escapes context tags in the question.
- `description` and the bubble get the bare question. `stripInjectedContext` removes leading blocks from echoes and logs.
- The blocks go with every message while a chip stays attached, because the chip says it is attached.

## Rendering

- Assistant text renders as markdown with `react-native-markdown-display`, styled from `src/ui/tokens.ts`.
  `html: false`; images are dropped. Relative links open on the signed-in host; only http(s) links open.
- The status line shows the current stage or tool, "Thinking…", or "Reconnecting…".
- The PR card shows when the run has a PR and the agent is idle.

## New chat

The compose button in the header shows once a chat has a task or a message.
It drops the open task (or the one the first send created), clears the text and attached reports, and resets the options to Default and Auto.
The header shows the task title, else "New chat".
The empty state with suggested prompts shows while there is no task and no message.

## Chats list

`useChatList()` (`src/features/chats/hooks.ts`) lists the person's sandbox sessions:
`GET tasks/?created_by={user id}&ordering=-last_activity_at&basic=true&limit=30`.

- `created_by` takes the numeric user id from `GET /api/users/@me/`. A session restored from before the app stored it has none:
  the hook calls `reloadAccount()` once and shows loading until it settles, then the list, the account error with Try again, or an empty list.
- `chatListFromSessions` (`src/model/adapters/chats.ts`) maps `origin_product` to the row's origin: `posthog_ai` is a chat, `signal_report` a report, anything else a session.
  The server already leaves out archived tasks.
- A row opens the sheet with `{ taskId }`; `mobile_chat_opened` is captured with `origin`.
- A 403 or 404 from tasks means the user has no sessions and shows the empty state.
- `chatGroups.ts` labels rows by local calendar day and filters titles on the device.
- Regaining focus (closing the sheet) invalidates the list, so a new chat appears with its title.
- Legacy LangGraph conversations are not listed. The web's new side panel does not list them either.

## Demo mode

No request goes out.
A new chat gets a demo task id, echoes the message and plays `DEMO_REPLY` through the session reducer: streamed chunks, the final message, then a turn end.
Demo sessions replay the run logs in `src/demo/sessionThreads.ts`:
"Fix the flaky checkout test" ended with a PR, "Add dark mode to settings" waits on a question,
and "Migrate billing webhooks" failed. A send plays `DEMO_REPLY`, an answer plays `DEMO_ANSWER_REPLY`, and Stop cuts the reply short.
The model list is the static catalogue, and the options change nothing about the reply.
