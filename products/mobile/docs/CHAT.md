# Chat

The chat screen talks to PostHog AI on the task runtime, as the web app's side-panel chat does.
Every chat is a task with interactive runs in a sandbox.
A new chat creates the task on its first message; the Chats list reopens one by its task id.
New and existing chats open as full-screen stack pages. Back returns to the previous screen or the
configured default page for a direct link. The title-free header uses the shared blur and fading edge;
New chat and the ellipsis share the Inbox's pill control. The composer clears the keyboard and safe area.

The ellipsis menu offers **Copy link to chat** and **Archive chat**. Copy uses the current project's
web URL. Archive returns to the previous page after success and keeps the chat open for retry on failure.
The menu is disabled for an unsaved new chat. Model, Mode, and attachment options still open as overlays.
The protocol below follows the web's `taskTrackerSceneLogic.ts`, `runInteractionLogic.ts` and `runStreamLogic.ts` in `products/posthog_ai/frontend`.

## Files

| File                                                 | Role                                                                                                                                                                                                                                    |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/features/chat/ChatScreen.tsx`                   | The sheet: header, thread or empty state, composer, the options reducer, draft restore                                                                                                                                                  |
| `src/features/chat/chatSheetEvents.ts`               | The sheet's `entry` from the route params, and the opened and closed events                                                                                                                                                             |
| `src/features/chat/ChatAccessGate.tsx`               | The organization AI approval and the personal consent before the composer (see [AI consent](#ai-consent))                                                                                                                               |
| `src/features/chat/session/useSession.ts`            | `useSession({ taskId?, runId? })`: create, follow, send, sync options, resume, stop, answer, reset, demo replies                                                                                                                        |
| `src/features/chat/session/sessionRun.ts`            | Pure request bodies: the create shapes, run fields, the `set_config_option` plan, the tracked run config                                                                                                                                |
| `src/features/chat/session/sessionReducer.ts`        | Folds run log lines and stream frames into the thread, as the web's `foldLogFromCheckpoint` does                                                                                                                                        |
| `src/features/chat/session/sessionDisplay.ts`        | Groups thoughts and tool calls into activity rows, error copy                                                                                                                                                                           |
| `src/features/chat/session/sessionTurn.ts`           | `SessionTurnTracker`: one `mobile_session_finished` per turn the person started                                                                                                                                                         |
| `src/features/chat/session/SessionThread.tsx`        | The thread, its rows, the PR card and the status line                                                                                                                                                                                   |
| `src/features/chat/session/SessionDecisionPanel.tsx` | The notice line and a pending question, plan approval or permission                                                                                                                                                                     |
| `src/features/chat/messageQueue.ts`                  | The queue reducer, the hold, and the queue, drain and Send now rules                                                                                                                                                                    |
| `src/features/chat/QueuedMessages.tsx`               | The queue banner above the composer: count, rows, remove and Send now                                                                                                                                                                   |
| `src/features/chat/chatRunOptions.ts`                | `ChatRunOptions` (model and permission mode), its reducer, the chip label, seeding from a run                                                                                                                                           |
| `src/features/chat/ChatOptionsSheet.tsx`             | The Model and Mode pages in a sheet over the chat                                                                                                                                                                                       |
| `src/features/chat/contextPrompt.ts`                 | The leading context blocks, `bareQuestion`, `stripInjectedContext`                                                                                                                                                                      |
| `src/features/chat/objectContext.ts`                 | The issue and recording item types, `objectContextFromParams`, their trusted lines (see [Object context](#object-context))                                                                                                              |
| `src/features/chat/attachments/`                     | Files in the composer: the limits and content types (`attachmentRules.ts`), the pickers, the three-step upload (`uploadAttachments.ts`), `useComposerAttachments`, the Attach sheet and the file chip (see [Attachments](#attachments)) |
| `src/features/chat/chatErrors.ts`                    | Maps HTTP and network failures to copy, including the PostHog Desktop gate                                                                                                                                                              |
| `src/features/chat/*.tsx`                            | `Composer`, `ContextChip`, `MentionPopover`, `ChatEmptyState`, `ChatMarkdown`, `ChatErrorBubble`, `ChatProgressLine`, `UserBubble`                                                                                                      |
| `src/features/chats/`                                | The Chats screen: list, search, day groups and `useChatList()` (see [DESIGN.md](DESIGN.md))                                                                                                                                             |
| `src/demo/sessionThreads.ts`                         | Demo run logs keyed by the demo task ids in `src/demo/chats.ts`, and the demo replies                                                                                                                                                   |

The transport is `src/api/tasks.ts`, shared with the hand-off (see [HANDOFF.md](HANDOFF.md)).
Every request carries `X-PostHog-Client-Platform: mobile`, so `run/` never reuses a warm run a web composer booted.

## AI consent

The same approval rules cover Chat, Create PR/task handoff, and replay summarization. The chat composer and decision panel remain hidden until approval is known.

- **Organization approval.** The selected project's organization must have `is_ai_data_processing_approved: true`. The app reads the requesting user's `membership_level` from `OrganizationSerializer` in `/api/users/@me/` and `/api/organizations/{id}/`: 8 is an administrator and 15 is an owner. Only those confirmed roles see Open settings; other members and unknown roles see instructions to ask an admin or owner. The settings link opens the organization's existing web approval control; mobile never changes that setting itself.
- **Personal consent.** The shared sheet explains that messages, reports, attached files and photos, selected recordings, and project data used by the agent can go to PostHog AI and third-party model providers. It links to the privacy policy. Continue records the disclosure on this device for this host and user; Not now sends nothing. The broader disclosure invalidates consent saved by older versions of the chat-only sheet. Sign-out and session expiry clear consent.
- **Fresh checks.** Every submitted message (including queue delivery), handoff, decision answer, and replay summary first reads the organization's current approval. The chat also rechecks on foreground before showing role-specific controls. Unknown approval, a failed read, and removed project access stop the action. Changing host, user, project or session, or leaving the originating screen while the sheet is open, cancels its pending action.
- Demo mode skips approval and sends no live requests.

These client checks supplement existing server scopes, resource RBAC and product checks. They do not grant an organization role or replace server authorization. Revocation after a check must still be enforced by the backend; mobile cannot stop an agent that is already running on the server.

## Composer drafts

The message input wraps long text onto multiple lines and grows up to 120 points tall.
Longer drafts scroll vertically within the input. The keyboard's Send action sends the message
and keeps the keyboard open for a follow-up.

Text and attached report IDs are saved separately for each task, each report discussion, and
the new-chat composer. Native drafts use encrypted device storage, scoped to the account,
host and project, with at most 50 drafts per project. Changes save after 400 ms of idle time
and flush when the composer closes or the app backgrounds. Opening a saved chat restores its
draft after storage loads.
`mobile_chat_draft_restored` is captured with `text_length` and `report_count` when the restored draft has text.

A successful send clears the submitted text. A failed send keeps it, and a delayed completion
does not replace text typed for a later message. Sign-out or session expiry clears the account's
drafts. Demo drafts stay in the current composer; the web preview stores drafts in memory only.
Picked files are not part of a draft. They stay in memory and go when the sheet closes (see [Attachments](#attachments)).

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
`mobile_chat_diagram_failed` is captured once per diagram with `reason` (`timeout`, `render_error`, `load_error`, `process_gone` or `open_window`).

A tap on an object link, an insight card, a SQL card or a markdown link opens it in the browser.
`mobile_chat_link_opened` is captured after the system opens it, with `source` (`object_chip`, `insight_card`, `query_card` or `markdown`),
`object_kind` (the registry kind, null for a markdown link) and `app_link` (a markdown link that was an app path).

Insight summaries need the `insight:read` OAuth scope. Existing sessions need a new sign-in,
and the server's mobile OAuth application must allow the scope; see [AUTH.md](AUTH.md).

## Starting a chat

The first send creates a task, then starts an interactive run on it.
Both calls go through `withWarmRetry`, which retries a 503 `warm_run_activation_unavailable` with the server's retry token.
The bubble shows at once and is taken back if the start fails.

Two create shapes (`chatStartRequests` in `sessionRun.ts`):

- **PostHog AI chat** (no report, or more than one report attached). `POST tasks/`:

  ```json
  {
    "title": "",
    "description": "<bare question>",
    "origin_product": "posthog_ai",
    "initial_permission_mode": "auto",
    "pending_user_message": "<context blocks>\n\n<question>"
  }
  ```

  The server generates the title from `description` in the create request, so the response already carries it.
  The app sends no `branch` and no `repository`, so the create never claims a warm run.

- **Inbox "Discuss"** (exactly one attached report). `POST tasks/`:

  ```json
  {
    "title": "<report title>",
    "description": "<prompt>",
    "origin_product": "signal_report",
    "signal_report": "<report id>",
    "signal_report_task_relationship": "discussion",
    "signal_report_discussion_question": "<question as typed, at most 4000 characters>",
    "pending_user_message": "<prompt>"
  }
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
`mobile_chat_options_opened` is captured with `page` (`model` or `mode`) when a chip opens the sheet.
`mobile_chat_option_changed` is captured with `option` (`model`, `effort` or `mode`) only.

The resolved default model is selected when no model is pinned: its row has a tinted background,
bold model and Default labels, and a checkmark. A known default reasoning effort uses the same
filled pill as an explicit choice. Picking another model or resetting to default moves these
selection indicators to the active options.

- **Seeding.** When an existing chat opens, the sheet seeds the options from `session.runConfig`:
  the run's model and effort as a pinned model, and its permission mode.
  A new chat keeps "Default" after sending, even when the run resolves a model and effort.
  Its model changes only when the person picks a model or effort.
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
- **Queue.** A message sent while the agent works, while a send or an answer is in flight, while a decision waits, or behind earlier queued messages goes into a queue above the composer instead (`messageQueue.ts`, `QueuedMessages.tsx`), as on the web.
  The banner shows "N queued" and one row per message, each with a remove control.
  The queue lives in memory only.
  While the agent works and the input has text, Send shows beside Stop, which turns into an outline button.
- **Automatic drain.** When the turn ends and nothing else is in flight or waiting, the queued rows go out as one message, joined by blank lines.
  A run that has ended takes the queue too: the send resumes it, as for any follow-up.
- **Send now.** Sends the queue into the live turn at once with `params.steer: true` on `user_message`, when the session reports `canSteer`; otherwise it goes as an ordinary follow-up.
  It is disabled with "Answer the agent first" while a decision waits, and with "Wait for the agent to start" while the turn runs but the stream has not shown the agent generating yet.
  The reason shows under the banner, because a phone has no tooltip.
- **Hold.** Stop holds the queue, so it does not go out when the stopped turn ends; the banner then says "N queued, not sent yet".
  A new message lifts that hold.
  A failed delivery puts its rows back in front of anything queued since and holds them; only Send now sends them again, because the failed send may have reached the agent.
- Closing the sheet, an Android back, or New chat puts the queued messages back in front of the composer text, so the draft keeps them.
- **Files.** A queued message takes the composer's files with it, as on the web, and the row shows "1 file" or "N files".
  The drained message, or Send now, carries the files of every row in queue order. The 10-file cap applies per composer message, not to the join.
  A failed delivery puts the rows back with their files. Removing a row drops its files.
  Closing the sheet or New chat drops the queued files, as closing drops unsent composer files. The queued text folds into the chat's own draft, so its files must not follow into another chat.
  Attach stays enabled while messages queue. Files of a direct send still in flight stay with that send and never join the queue.
- `mobile_session_queued` is captured with `queue_length` when a message joins the queue, `mobile_session_queue_removed` with `queue_length` after a row is removed,
  and `mobile_session_queue_sent_now` with `queued_count` and `steer` (the session could steer at the tap).
- `mobile_session_sent` is captured with `new_task`, `resumed_run`, `report_count`, `attachment_count`, `model`, `reasoning_effort`, `permission_mode`,
  `delivery` (`steer` when the agent accepted a steered message, `queue` for a drained queue, else `direct`) and `queued_count`.
  Model and mode changes still go out as `set_config_option` before a steered message, as on the web.
- `mobile_session_send_failed` is captured with `code` and `new_task` when a send shows a notice.
  `code` is `upload_failed`, `config_rejected`, `command_failed`, `run_not_started`, `warm_run_unavailable`, or the `ChatError` kind from `chatErrors.ts`.
- `mobile_session_finished` is captured once per turn the person started, with `status`, `duration_s` (from the accepted send) and `had_decision`.
  A steered message joins the turn it steers, so it adds no event of its own.
  `status` is `completed` (the turn ended), `failed` (the run failed, or the turn ended with a new run error), `cancelled` (the run was cancelled without Stop),
  `stopped` (the turn or run ended after Stop) or `abandoned` (the sheet closed or New chat dropped the chat first).

## Attachments

The Attach button opens a sheet with Photo library and Choose a file.
Photo library uses `expo-image-picker` (images only, never the camera); Choose a file uses `expo-document-picker` (any type).
Both allow several files. The keyboard drops before the sheet opens and comes back after the pick.
The limits and content types are the web's (`products/posthog_ai/frontend/utils/attachments.ts`):

- Any file type. At most 30 MiB per file, 10 MiB for a `.pdf`. An empty file is refused.
- At most 10 files per message. At 10 the Attach button is dimmed, and its accessibility hint says "Up to 10 files fit in one message"; no visible text says it.
  Files picked past the cap are left off, and one line says how many.
- The content type comes from the extension, never from the picker. An unknown extension is `application/octet-stream`; a file is an image when its type starts with `image/`.
  iOS gives a converted photo the name of its original (`IMG_0001.HEIC` for a JPEG), so the extension of the file the picker wrote wins.
- A refused file shows in the notice line above the composer, such as "notes.txt is empty." or "slides.pdf is over the 10 MB limit for PDFs."

Picked files show as chips after the report chips: an image with a small thumbnail, any other file with a document icon, each with a remove ×.
They live in memory only, never in the draft store.
Text stays required: a send with files and no text does not go, as on the web.

Files upload when the message sends, in three steps per batch, as the web's `artifactUpload.ts` does:

1. `POST .../prepare_upload/` with `{ "artifacts": [{ "name", "type": "user_attachment", "source": "posthog_ai", "size", "content_type" }] }`.
   The answer keeps the request's order, and each entry has an `id`, a `storage_path` and a `presigned_post`.
2. A `multipart/form-data` `POST` to each `presigned_post.url`, all files at once.
   Every `presigned_post.fields` entry goes first, then the file as `file`. It is a plain `fetch`, so the PostHog token never goes to S3.
3. `POST .../finalize_upload/` with each `id`, `name`, `type`, `source`, `storage_path` and the extension's `content_type`.

One failed file fails the send, so a message never arrives with fewer files than the person attached.
The order of a send:

- **New chat.** `POST tasks/` (no `branch`, so it never claims a warm run and never answers with a run), then the staged upload against the new task (`tasks/{t}/staged_artifacts/...`),
  then `POST tasks/{t}/run/` with `pending_user_artifact_ids`. A failed upload deletes the new task, as a refused run does.
  If a create ever answers with a run while the send has files, the send fails the same way, because that run would never get the files.
- **Live run.** The changed options, then the run-scoped upload against the current run (`tasks/{t}/runs/{r}/artifacts/...`),
  then `user_message` with `params.artifact_ids`.
- **Ended run, or a 409.** Run-scoped ids belong to that run only, so the files upload again, staged against the task, and the resume `run/` carries `pending_user_artifact_ids`.
- **Demo.** Nothing uploads. The chips and the bubble show the files, and the canned reply plays.

While a send uploads, its chips show a spinner instead of ×, and Attach is dimmed. A successful send clears its chips.
A message that goes into the queue takes the composer's files with it (see [Follow-ups and resume](#follow-ups-and-resume)).
A failed send keeps them, puts the text back, and the notice says "Your files didn't upload. Try again."
Every failure while the files upload (prepare, the S3 post, finalize) shows this copy and counts as `upload_failed`, also when the server sent its own copy.
The first failed S3 post stops the other posts of the batch.
Closing the sheet or New chat aborts an upload in flight.

The bubble shows a picked image as a thumbnail from the file on the device and any other file as a chip with its name.
The echo names each file by a `resource_link` (or `image`) block whose URI ends in `.posthog/attachments/<runId>/<artifactId>/<name>`.
The reducer reads the ids from that path, keeps one entry per artifact, and fills the first entry of the same name that has no id yet, so the optimistic bubble keeps its thumbnail.
It also keeps each artifact's device file, so a resume, which draws the thread again from the log, keeps the thumbnails of files sent from this sheet.
A message with files and no text, which another client can send, has no bubble of its own: its files join the previous bubble, as on the web.
A file from history has no local copy and shows by name only (see [GAPS.md](GAPS.md#chat)).

- `mobile_chat_attach_menu_opened` when the sheet opens.
- `mobile_chat_file_attached` with `source` (`photos` or `files`), `attached_count` (files in the composer after the pick) and `image_count` (images in the pick).
- `mobile_chat_file_rejected` with `reason` (`empty`, `too_large`, `unreadable` or `too_many`), once per refused file and once per pick that went past the cap.
- `mobile_chat_file_removed` with `attached_count` when a chip's × removes a file.
- `mobile_chat_file_upload_failed` with `status` (the HTTP status of prepare, finalize or the S3 post, when there was one) and `new_task`.
- No event carries a file name or its content.

## Reading a run

- `GET tasks/{t}/` gives the title and the latest run. With a `runId` the sheet follows that run through `GET tasks/{t}/runs/{r}/`.
- **Ended run.** `GET tasks/{t}/runs/{r}/logs/` returns the whole resume chain as JSON lines, folded into the thread.
- **Live run.** `GET tasks/{t}/runs/{r}/stream/` without a cursor replays the stored log, then streams.
  The app buffers catch-up frames and shows the history together, then streams new replies.
  Catch-up ends on a keepalive, stream completion, or 250 ms of silence after a Redis frame; silence during durable-log replay never ends it.
  Opening a thread scrolls straight to the latest message without animation.
  Reconnects follow the hand-off rules (see [HANDOFF.md](HANDOFF.md)). A reconnect keeps the cursor and buffered history
  through a transport rotation, and buffers each new connection's backlog before showing it. A replay after a lost
  cursor rebuilds the thread with a fresh event deduplication set, so previously displayed or buffered frames remain in the full replay.
- `mobile_session_resumed` is captured with the run status.
- `mobile_session_load_failed` is captured with `code` (the `ChatError` kind) each time the thread shows "Couldn't load this session".
  `mobile_session_load_retried` is captured when the person taps Try again there.

## Stop

Stop sends the `cancel` command (`{ "jsonrpc": "2.0", "method": "cancel" }`), which interrupts the turn and keeps the run alive.
The app sends it only after the stream showed the agent generating, because a cancel before that drops the run's first message; until then the notice says "The agent hasn't started yet."
A JSON-RPC `error` in the answer shows "Couldn't stop this run. Try again."
`mobile_session_stopped` is captured when the cancel goes out. The turn's `mobile_session_finished` then has `status: stopped`.

## Decisions

Permission requests go through the hand-off tool policy (`toolPolicy.ts`, see [HANDOFF.md](HANDOFF.md#tool-policy)):
the app allows built-in tools and PostHog `exec` calls on the person's behalf and asks about the rest.
A question, plan approval or permission shows in `SessionDecisionPanel` and replaces the composer while it waits.
The answer goes as a `permission_response` command and shows in the thread as the person's bubble.
`mobile_decision_shown` is captured once per request with `kind` (`question`, `plan` or `permission`), `surface: chat` and `replayed` (the request was in the stored log).
`mobile_decision_answered` follows with `task_id`, `kind`, `picked_option` and `surface: chat`.

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

### Object context

The issue and session screens open the sheet with `entry` (`issue` or `replay`), `objectType`, `objectId` and `objectLabel`.
`objectContextFromParams` in `objectContext.ts` keeps only the two types the web uses, `error_tracking_issue` and `session_recording`.
The message carries one untrusted item line, `- {type} {id} ("{label}")`, and one static trusted line that names the investigating skill and the fetch tool (`query-error-tracking-issue`, `session-recording-get`).
The object shows as a removable chip with the issue or recording icon. While it is attached, @-mentions are off and report chips stay hidden, because a message frames one kind of context.
New chat drops it.

## Rendering

- Assistant text renders as markdown with `react-native-markdown-display`, styled from `src/ui/tokens.ts`.
  `html: false`; images are dropped. Relative links open on the signed-in host; only http(s) links open.
- The status line shows the current stage or tool, "Thinking…", or "Reconnecting…".
- Thoughts and tool calls fold into activity rows. Every row starts closed, also while it runs. `mobile_chat_activity_expanded` is captured with `running` and `tool_count` when the person opens one.
- Known PRs remain available while execution is active, idle or terminal. Their state is separate
  from execution; a discovered URL starts unknown until the report supplies authoritative state.
- Report task status opens that implementation task, including idle and completed runs that can
  resume. The Chat button beside the report action pill starts a separate report discussion. A completed turn
  alone does not create an attention request; the task composer provides continuation.

## New chat

The compose button stays available in the header.
It drops the open task (or the one the first send created), clears the text and attached reports, and resets the options to Default and Auto.
The header has no chat title.
The empty state with suggested prompts shows while there is no task and no message.
`mobile_chat_suggestion_picked` is captured with `source` (`report` for the report's own prompts, else `default`), `index` and `report_count`; never the prompt.

`@` or the @ button opens the report list. `mobile_chat_mention_opened` is captured with `trigger` (`typed` or `button`),
`mobile_chat_report_attached` with `attached_count`, and `mobile_chat_report_removed` (a chip's ×) with `attached_count` and `initial` (the report the sheet opened with).

## Page lifecycle

The navigator keeps one chat screen. Opening another chat reuses that screen and loads fresh
conversation state. A notification for the chat already on screen leaves its session, draft and
scroll position intact, including a chat started from the composer. A notification for a different
chat replaces the open chat, so one Back returns to the screen underneath. Starting New chat
does not prevent a later notification from reopening the previous conversation.

Changing the selected account, host or project closes an open chat and aborts its scoped work. Callbacks captured in the old scope cannot send to the newly selected project.
A send waiting for encrypted draft storage is cancelled by New chat or closing the sheet, and its text remains recoverable in the original draft.

The page opens from the bottom bar's compose button, a report's Chat button, a report's task status, an inbox row's menu and the Chats tab.
The route takes an optional `entry` param; `chatSheetSource` falls back on `report` with a `reportId`, `task` with only a `taskId`, else `compose`.

- `mobile_chat_sheet_opened` is captured once per open with `entry` (`chats_list`, `chats_search`, `chats_empty`, `compose`, `report`, `report_task`, `inbox_menu` or `task`),
  `origin` (the Chats row's origin, else null), `has_context` (a report is attached) and `resumed` (an existing task opened).
- `mobile_chat_sheet_closed` is captured on unmount, also after an Android back, with `entry`, `messages_sent`, `new_chats` (New chat taps), `had_run` and `dwell_s`.

## Chats list

`useChatList()` (`src/features/chats/hooks.ts`) lists the person's sandbox sessions:
`GET tasks/?created_by={user id}&ordering=-last_activity_at&basic=true&limit=30`.

- `created_by` takes the numeric user id from `GET /api/users/@me/`. A session restored from before the app stored it has none:
  the hook calls `reloadAccount()` once and shows loading until it settles, then the list, the account error with Try again, or an empty list.
- `chatListFromSessions` (`src/model/adapters/chats.ts`) maps `origin_product` to the row's origin: `posthog_ai` is a chat, `signal_report` a report, anything else a session.
  The server already leaves out archived tasks.
- A row opens the sheet with `{ taskId, entry, origin }`: `entry` is `chats_search` while the search field has text, else `chats_list`.
  `mobile_chat_sheet_opened` carries both; the list sends no event of its own for a row.
- `mobile_chats_searched` is captured with `query_length` and `result_count` once per query, after typing pauses.
- `mobile_chats_refreshed` is captured with `trigger` (`pull` or `retry`).
- `mobile_chats_load_failed` is captured with `code` (the `ChatError` kind) each time the list shows "Couldn't load your chats".
- A 403 or 404 from tasks means the user has no sessions and shows the empty state.
- `chatGroups.ts` labels rows by local calendar day and filters titles on the device.
- A long press (or the screen reader's "Show actions") opens the row menu (`ChatRowMenu`) with Archive.
  `useArchiveChat()` hides the row at once and sends `PATCH tasks/{id}/` with `{ "archived": true }`; the server stamps `archived_at`
  and leaves the task out of every later list. The toast offers Undo, which puts the row back and sends `{ "archived": false }` after any pending archive request finishes.
  Repeated archive submissions share the pending request. A failed archive puts the row back and shows "Couldn't archive this chat. Try again."
  A failed Undo hides the row again and shows "Couldn't restore this chat. Try again."
  There is no archived list in the app: the web app and PostHog Desktop show archived tasks.
- `mobile_chat_row_menu_opened`, `mobile_chat_archived` and `mobile_chat_archive_undone` carry the row's `origin` and `status`;
  `mobile_chat_archive_failed` carries `action` (`archive` or `restore`) and `code` (the `ChatError` kind).
- Regaining focus (closing the sheet) invalidates the list, so a new chat appears with its title.
- Legacy LangGraph conversations are not listed. The web's new side panel does not list them either.

## Demo mode

No request goes out, and attached files do not upload.
A new chat gets a demo task id, echoes the message and plays `DEMO_REPLY` through the session reducer: streamed chunks, the final message, then a turn end.
Demo sessions replay the run logs in `src/demo/sessionThreads.ts`:
"Fix the flaky checkout test" ended with a PR, "Add dark mode to settings" waits on a question,
and "Migrate billing webhooks" failed. A send plays `DEMO_REPLY`, an answer plays `DEMO_ANSWER_REPLY`, and Stop cuts the reply short.
The model list is the static catalogue, and the options change nothing about the reply.
Archiving a demo chat hides it in the demo store until the demo refreshes or resets.
