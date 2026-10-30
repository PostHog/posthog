# Hand-off and agent runs

How the report screen hands a report to the PostHog agent, follows the run, relays the agent's
questions, and shows the PR it opens. Code lives in `src/features/handoff/` and `src/api/tasks.ts`.

## Flow

### Default agent

The report's hand-off button uses the last agent selected in the hand-off sheet: PostHog,
Claude Code or Codex. The selection is saved on this device across reports and app
restarts, with PostHog as the initial default. Selecting PostHog again restores that default.
Copy prompt does not change the preference. The preference is client-only; external handoffs
still open a prepared prompt without starting a PostHog run.

### External agents on mobile

The hand-off sheet offers two external destinations, independently of the PostHog run options:

PostHog, Claude Code and Codex each show their existing brand mark beside the option label.
The marks are decorative; screen readers announce the button's label and hint.

- **Claude Code** opens the [documented mobile composer](https://support.claude.com/en/articles/14898120-open-the-claude-mobile-app-with-a-link)
  at `claude://code/new` with an encoded `q` and, when the report's latest `repo_selection` artefact names
  a GitHub repository, `repo=owner/repo`. The user reviews and submits the prompt in Claude. Claude Code access
  is required, and Claude ignores a repository that is not connected to the user's GitHub account. The
  `/code?prompt=...&repositories=...` web route can open the mobile app without applying the prompt or repository.
- **Codex** opens `https://chatgpt.com/?prompt=<encoded text>`. ChatGPT's current
  [iOS universal-link configuration](https://chatgpt.com/.well-known/apple-app-site-association) explicitly
  admits this route. Prompt prefill was confirmed in device testing, and the web fallback was checked with
  harmless sample text: it fills the composer without sending.
  This replaces `codex://new?prompt=...&originUrl=...`, which opened ChatGPT but ignored the prompt and repository
  in device testing. Repository context stays in the prompt; this route does not select a Codex project or
  environment. Use `prompt`, not `q`, to target a draft. OS link preferences or an absent app may open the browser.

The prompt includes the report URL and ID, a repository hint when known, and instructions to retrieve evidence
through authenticated PostHog MCP tools. It does not make the report public or pass PostHog credentials.
The receiving agent needs its own PostHog connection. Copy prompt uses the same text as both direct links.
The agent claims the report when work starts, retains its `claim_id`, and attaches its PR URLs.
Opening or copying never claims the report, starts a PostHog run, or reports that an external agent
is working. Failed launches show an inline fallback. The web preview supports copying only.
Tracking: `mobile_external_handoff_opened` with `target` (`claude`, `codex`), `from` (`button`, `sheet`,
`inbox_menu`) and `has_repository`, never the prompt. A failed launch sends `mobile_handoff_failed` with
`agent` set to the target and `reason` (`launch_failed`, `unsupported_platform`). Copy prompt sends
`mobile_handoff_prompt_copied`.

Device acceptance checks (iOS and Android, with receiving apps installed and absent):

1. Open each direct option; check the destination, complete prompt, repository and explicit send step.
2. In ChatGPT, choose the project manually; the prompt includes repository context but does not select a project.
3. Return from each app and test a failed launch and Copy prompt; report state must stay unchanged.
4. Try a report with no repository; the prompt must ask the agent to confirm one.
5. Try a small screen and larger accessibility text; all destinations, PostHog options and Copy prompt must remain reachable.

### PostHog runs

```text
Hand off ──► kickOffReportTask ──► store.started ──► useTaskRun ──► store.live ──► mergeLiveRun ──► ActionBar
 (button or sheet)  GET report          (status card     bootstrap +     reducer       (report + live)    (footer state
                    POST tasks/          shows at once)   SSE stream                                       from actionBarStateFor)
                    POST tasks/{id}/run/
```

1. **Kickoff** (`kickoff.ts`). `GET signals/reports/{id}/` for a fresh title and summary, then the
   web's two calls:
   `POST tasks/` with `{title, description: <prompt>, origin_product: 'signal_report', signal_report, signal_report_task_relationship: 'implementation'}`
   (no `repository`: the server picks it from the report and rejects one the client sets), and, only
   when the response has no `latest_run`,
   `POST tasks/{task_id}/run/` with `{run_source: 'signal_report', signal_report_id, mode: 'interactive', pending_user_message: <prompt>, ...<run options>}`.
   The run options come from `buildHandoffRunRequest` (see [Run options](#run-options)).
   The run comes from `run`, else `latest_run`. Both calls retry a 503
   `warm_run_activation_unavailable` with `X-PostHog-Warm-Retry: <first retry_token>`, 250 ms
   doubling to 1 s, for up to 20 s.
   The created task ID stays in memory if its first run fails; after an app restart the report's current task claim recovers it. Retry fetches that same task, adopts any run the earlier request started, or starts its first run without creating another task. The Hand off button remains available while that task has no run, including after the report shows its claim. An ambiguous failure never deletes a potentially running task.
2. **Started.** `useHandoffActions(id).handOff` stores `{taskId, runId}` in the hand-off store,
   tracks `mobile_report_handed_off`, and invalidates the report and inbox queries. While the
   calls are in flight `handOffPending` already shows the status card.
3. **Follow** (`useTaskRun.ts`). While the report screen has focus and the app is in the
   foreground: `GET tasks/{task_id}/` (its `latest_run` wins over a run id from the report, which can
   be stale), falling back to `GET tasks/{task_id}/runs/{run_id}/`, then
   `GET tasks/{task_id}/runs/{run_id}/stream/`. A terminal run is not streamed.
4. **Overlay** (`useReportWithLiveRun.ts`, `liveReport.ts`). Lays the live state over B's
   `useReport(id)`: `task` (status, stage, pending decision, error), `work.pullRequest` (from
   `output.pr_url` when the report does not know that PR yet), and `prompt` (the external-agent
   prompt for "Copy prompt"). The footer stays driven by `actionBarStateFor`.
5. **Answer** (`hooks.ts`, `commands.ts`). The decision card answers through
   `POST tasks/{task_id}/runs/{run_id}/command/`.

Demo mode skips all of this: the demo store drives the same cards.

## Run options

The hand-off sheet has Model, Mode and Branch rows above the PostHog row. Each row opens a page in
the same sheet with a back control. The quick "Hand off" button uses the same options while they last
(see Reset below), so outside a sheet session it sends the defaults.
Code: `runOptions.ts` (ports of the web's `composerModels.ts` and `composerModes.ts`),
`runOptionsStore.ts`, `useRunOptions.ts`, `ModelPage.tsx`, `ModePage.tsx`, `BranchPage.tsx`.

| Request                               | When                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET tasks/models/` (`task:read`)     | Sheet open. `{models: [{runtime_adapter, model, display_name, supported_efforts, cost_multiplier}]}`. The app hides the catalogue's retired ids, except a retired stored default, which stays listed so it shows by name (the web's `pickerModels`). An empty list or an error shows "Couldn't load the model list" and the run uses the default model. |
| `GET tasks/@me/config/` (`task:read`) | Sheet open and at hand-off (cached 60 s). The app reads `resolved_ai_run_defaults.{runtime, runtime_adapter, model, reasoning_effort}`.                                                                                                                                                                                                                 |

The run body (`buildHandoffRunRequest`):

| Selection                                                                          | Fields sent                                                                                                                                                                                                                                                                               |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model untouched, usable stored default (`runtime: 'acp'` with a model and adapter) | `initial_permission_mode` only, mapped to the default's harness. The server resolves the user's, then the project's, default.                                                                                                                                                             |
| Model untouched, no usable stored default (`model` is null, or `runtime` is `pi`)  | `runtime_adapter: 'claude'`, `model: 'claude-opus-5-5'`, `reasoning_effort: 'high'`, and the mode mapped to Claude. A run that pins no runtime starts on ACP, and `resolve_ai_run_selection` discards a Pi default there; the web maps it to null too. Matches the web Inbox's Create PR. |
| Model untouched, `@me/config/` failed                                              | `initial_permission_mode` only, so a failed lookup never overrides a stored default.                                                                                                                                                                                                      |
| Model picked                                                                       | `runtime_adapter`, `model`, `reasoning_effort` (left out for a model with no efforts) and the mode mapped to that harness.                                                                                                                                                                |
| Branch typed                                                                       | `branch` (trimmed). Left out when empty: the server then uses the project's Inbox base branch for that repository (`autostart_base_branch_for_repository`), else the repository's GitHub default branch.                                                                                  |

- **Mode** defaults to Auto. Claude offers Default, Accept edits, Plan and Auto; Codex offers Plan,
  Read only and Auto. Full auto (`bypassPermissions`) and Full access (`full-access`) are hidden, as
  on the web. A mode from the other harness maps to its nearest equivalent, which can be looser:
  Default and Accept edits become Auto on Codex, Read only becomes Plan on Claude, and the hidden
  Full auto and Full access map onto each other.
- **Effort.** Picking a model keeps the current effort when the model supports it, else High, else
  the model's highest effort. With an untouched model, picking an effort pins the default model. An
  untouched picker marks the default's effort only when the stored default names one.
- **Repository** is not a choice: report tasks get their repository from the report's repository
  selection or the server's cascade, and the server answers 400 to a client-set one.
- **Reset.** Options are in memory for one sheet session, like the web's per-run picks. They go back
  to the defaults when the sheet closes (with or without a hand-off), after each hand-off, on a
  project switch and at sign-out. The Branch field writes to the store on every keystroke.
- **Scrolling.** The model list sits in a `Gesture.Native()` that the sheet's drag-to-close pan waits
  for, so a drag that starts on the list scrolls it. Drag the grabber or the header to close.
- **Tracking.** `mobile_handoff_option_changed` with `option` (`model`, `effort`, `mode`, `branch`),
  never the value. `mobile_report_handed_off` adds `model` (`default` when untouched),
  `reasoning_effort` (when pinned), `permission_mode` and `has_branch`.

The chat sheet (`src/features/chat/session/useSession.ts`, see [CHAT.md](CHAT.md)) reuses `runStream`, `permissionRequest`, `commands` and `toolPolicy` from this feature.

## Which run a report follows

The current task claim wins over the run this device started and over historical implementation
artefacts. A claim by a user, an external agent, or a system without a task clears historical task
execution from the report footer. When there is no claim, the adapter can use the newest
implementation `task_run` artefact. Discussion tasks do not become implementation ownership.
Within the current task, `GET tasks/{id}/` supplies its latest run; the bootstrap also updates
the task query so a resumed run can replace the report's older run immediately.

Tapping the action bar's agent status card opens that task's chat sheet, passing the task id and
the displayed run id when available. It sends `mobile_report_action_pressed` with `action: task_chat`,
`from` (`status_card`, `decided_card`, or `pr_card` for "View task activity") and `run_status`. The round
Chat button sends it with `action: chat`. A claim without a task id cannot open a task chat yet. The
round Chat button beside the Reassign / Resolve / Dismiss pill starts a new conversation with the report attached.
The streamed command beneath the status title stays on one line and truncates at the end.

## Stream handling

Frames follow `products/tasks/backend/presentation/views/api.py` (stream view) and the web's
`products/posthog_ai/frontend/logics/runStreamLogic.ts`. The SSE parser is `src/api/sse.ts`.

| SSE event                  | Handling                                                                                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `keepalive`                | Resets the 60 s idle timer and publishes any buffered report history.                                                                               |
| `end` `{"type":"rotated"}` | Connection cap reached. Reconnect at once with `Last-Event-ID`.                                                                                     |
| `end` `{"type":"resync"}`  | Drop the cursor, reconnect, take the full replay.                                                                                                   |
| `stream-end`               | Stream finished. Publish buffered history, drop the cursor, fetch the run once more, stop. The run snapshot determines whether the run is terminal. |
| `error`                    | Server closes. Fetch the run; stop if terminal, else reconnect with backoff.                                                                        |
| content (no `event:`)      | Saved as the cursor (`id`), deduped by envelope `event_id`, reduced below.                                                                          |

Reconnects back off 2 s doubling to 30 s, 10 attempts per drop and 30 per screen visit, and fetch
the run first so a finished run stops. A 503 at admission waits `Retry-After`. 401, 403 and 404 stop.
The first connection sends no `Last-Event-ID` (and not `start=latest`), so the server replays the
durable log (`log-<n>` ids) and a question asked before the app connected reaches the decision
card. Cursors stay in memory per run, so returning to the report resumes after the last event.

Opening or reconnecting a report folds the initial stream privately in `RunHydration`, keeping
the cached report and PRs visible. Durable `log-<n>` frames never paint individually. Once Redis
frames arrive, a 250 ms quiet interval coalesces their initial tail into one publication; keepalive
or explicit `stream-end` can also settle it. Subsequent live frames publish immediately. Rotation,
resync, errors and unmarked EOF do not publish incomplete catchup. Rotation keeps the private
state and cursor together; leaving the screen discards both unpublished copies. An authoritative
terminal snapshot can settle accumulated PR metadata while clearing pending input. Cursors commit
with their state and clear at session end, so reopening cannot skip unpublished history.

All catchup frames, including Redis history, use replay permission policy: they cannot send
automatic approval commands. The final unresolved request remains available to answer. Local
answers and handled request ids written during catchup survive publication. A resumed cursor
can apply work missed while disconnected without replaying its intermediate status changes.

The server has no explicit catchup-complete event or snapshot watermark. A quiet Redis tail is a
UI batching heuristic: Redis history delivered in arbitrarily slow chunks can still look live
after the quiet interval. An authoritative boundary requires backend work listed in
[GAPS.md](GAPS.md#agent-state-backend-backlog); the client does not use `start=latest` to skip
history because doing so could lose an outstanding question.

| Content frame                                                                | Effect on the live state                                                                                                                                             |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `task_run_state`                                                             | `status`, `stage`, `error_message`, `output.pr_url` / `pr_urls`. A terminal status clears the pending decision.                                                      |
| `session/update` `tool_call`                                                 | Latest tool title becomes the stage, shortened: "Read /repo/src/ChartLegend.tsx" reads "Reading ChartLegend.tsx".                                                    |
| `session/update` `tool_call_update`                                          | Title updates of the latest call move the stage. A `completed` or `failed` update for the pending request's tool clears it (someone else answered).                  |
| `session/update` `agent_message_chunk` / `agent_message`                     | Records activity for the current run. Message text belongs in task chat.                                                                                             |
| `session/update` `current_mode_update`, `session/new` `_meta.permissionMode` | Permission mode for the tool policy.                                                                                                                                 |
| `_posthog/progress`                                                          | `label` (else `detail`) overrides the tool title while the step runs; a finished step clears it.                                                                     |
| `_posthog/turn_complete`                                                     | The turn is idle. Clears pending requests and transient progress; it does not create an input request.                                                               |
| `_posthog/error`                                                             | Keeps `message` as the run error.                                                                                                                                    |
| `permission_request` (live) and `_posthog/permission_request` (replay)       | Runs the tool policy: allow it for the user, or surface it as a decision. Ignored when already handled, from an earlier run in the log, or when the run is terminal. |
| `_posthog/permission_resolved` (replay)                                      | Clears the matching request and remembers its id so a replay cannot bring it back.                                                                                   |

While execution is working, the status card stage is the active step label, else the latest tool
title, else the server's `stage`. Idle and terminal runs clear this transient text. There is no
"step N of M": the API has no step count. A claim identifies ownership, not execution; unknown
execution and missing check data stay unknown.

## Tool policy

`toolPolicy.ts` is a port of `products/posthog_ai/frontend/policy/toolPolicy.ts` and the routing in
`runStreamLogic.routePermissionRequest`. An interactive run relays approvals to the connected client
and waits; when the phone is the only client, a request it does not answer stalls the agent.

- Allowed for the user (with `allow_once`, else another `allow*` option): built-in tools (a
  canonical tool name such as `Bash`, `Edit`), and PostHog `exec` calls in the task's project.
- Asked: questions (`AskUserQuestion`), plan approvals (no tool name, `kind: 'switch_mode'`),
  other MCP servers (`mcp__*`), connected-project calls (`posthog-connection-call`,
  `posthog-connection-forward`), and anything with no tool name.
- In `bypassPermissions` mode everything is allowed except questions, plans and connected-project calls.
- A request from the replayed log is never answered for the user, since the run may have moved on.
- If allowing fails, the request shows as a decision instead.

## Decisions and answers

| Request       | Card                                                                                                                                                                 | Answer sent                                                                                                                                                                   |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Question      | `_meta.questions[0].question`; options `option_<idx>` with the label as title and the description as meta. Several questions show one at a time and go out together. | `permission_response` with `optionId` (the picked `option_<idx>` of the first question, else `option_0`), `answers` keyed by question text, and `customInput` for typed text. |
| Plan approval | "Approve the plan?" with "Approve the plan" (`auto`) and "Approve in full auto" (`bypassPermissions`), or the offered options when neither exists.                   | The picked mode. Typed text rejects with feedback (`customInput`).                                                                                                            |
| Permission    | "Allow {tool title}?" with the offered options.                                                                                                                      | The picked option. Typed text goes with the option that takes text, else a reject option, else the first.                                                                     |

Success is `jsonrpc: '2.0'`, no `error`, and `result.resolved === true`. A 503 `sandbox_not_ready`
or `agent_session_not_ready` retries at 250, 500 and 1000 ms for up to 10 s. A 409
`permission_target_ended` or `run_ended` (or any 409 on `user_message`) means the run is over: the
card closes, a notice says the answer was not sent, and the run and report are fetched again. A
JSON-RPC error "No pending permission request" means someone else answered: the card closes.

The decided card shows the answer while it is delivered, with Undo, and after the agent confirms,
without Undo, until the run shows new activity. Undo aborts the request in flight and brings the
card back. It is best effort: a request the server already received still reaches the agent, and
answering again then gets "already moved on". Tracking: `mobile_decision_answered` with `kind`
(`question`, `plan`, `permission`) and `picked_option`. "Read question" sends `mobile_report_sheet_opened`
with `sheet: decision` and the same `kind`, so shown and answered form a funnel. A close before an answer
sends `mobile_report_sheet_dismissed`. Undo sends `mobile_decision_undone`. Task chat uses the same card
and sends none of these sheet events.

## Error copy

Hand-off and answer errors show as one orange line above the footer cards. The actions resolve
instead of rejecting, because every caller fires them without waiting.

| Case                                             | Copy                                                                                                                                             |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 402 `self_driving_free_trial`                    | Server `detail`, else "During your free trial, Self-driving writes reports but doesn't open pull requests. Contact us to upgrade."               |
| Other 402 (PR limit)                             | Server `detail`, else "Your organization reached its self-driving pull request limit. Ask an org admin to raise it from the Inbox usage widget." |
| 429 `signal_report_task_cap`, `throttled`        | Server `error` or `detail`, else "Task limit reached for this report. Try again later."                                                          |
| Other 429                                        | Server copy, else "PostHog is busy. Try again in a few minutes."                                                                                 |
| 503 `warm_run_activation_unavailable` after 20 s | "PostHog couldn't start the agent in time. Try again."                                                                                           |
| 403                                              | Server copy, else "You don't have access to hand off reports in this project."                                                                   |
| 404                                              | "This report is no longer available."                                                                                                            |
| No run returned                                  | "PostHog created the task but couldn't start it. Try again."                                                                                     |
| Network                                          | "Couldn't reach PostHog. Check your connection and try again."                                                                                   |
| Anything else                                    | "Couldn't hand off to PostHog. Try again."                                                                                                       |

Tracking: `mobile_handoff_failed` with `agent: posthog` and `reason`, one value per row above
(`free_trial`, `pr_limit`, `task_limit`, `busy`, `start_timeout`, `forbidden`, `not_found`,
`run_not_started`, `network`, `unknown`, plus `not_signed_in`), never the message. `handoffFailureReason`
in `kickoff.ts` picks the reason and `handoffErrorMessage` maps it to the copy, so the two cannot drift.

Execution, attention and pull requests are independent footer state. A failed or canceled run
keeps its known PR available, alongside its run outcome and task-chat entry point. A completed
turn with no outstanding request is idle; continuation happens in task chat. A connection failure
shows reconnecting or unavailable, rather than claiming work is running or stopped.

## What is not possible

- **Undo after delivery.** The agent acts on an answer at once; there is no command to take it back.
- **Step counter.** The run has a free-text stage only, so there is no "Step N of M".
- **Background following.** Nothing streams while the report screen is closed or the app is in the
  background, or while another route covers the report. A tool request that arrives then waits until a client connects; push notifications
  (`awaiting`) cover the wait.
- **Answers from other clients, live.** Resolutions appear only in the replayed log. Live, a
  request clears when its tool finishes, the turn ends, or the run ends.
- **Continuing an ended run.** A message to a run whose workflow ended needs a resume run
  (`POST tasks/{id}/run/` with `resume_from_run_id`). Open the implementation task
  chat to start that resume run, see [CHAT.md](CHAT.md#follow-ups-and-resume).

## Pull request checks

`usePullRequestChecks(reportId, selectedPr.id)` reads
`GET signals/reports/{id}/pr_checks/?pull_request_id={selectedPr.id}`. The canonical PR id
selects only that report-linked PR; a discovered URL without an id cannot fetch checks.
The focused report checks every 30 seconds in live mode while the app is active, and fetches
again on foreground return. Changing the selected PR uses a separate query entry.

"View PR" sends `mobile_pull_request_opened` with `from` (`report`, `chat`, `inbox_menu`), `state` and
`pr_count`. Choosing between several PRs opens the `pull_request_picker` sheet (see the sheet events in
[DATA.md](DATA.md#actions)).

Checking, passing, failing, pending, no checks and unavailable are distinct states. Empty checks
mean no checks, while missing or malformed data and request errors mean unavailable. A successful
snapshot records when this client fetched it, including while cached data stays visible during
refresh. This is a local observation time; the endpoint provides no server observation timestamp
or head SHA, so it cannot prove that a cached green result describes the PR's newest commit.

## Freshness and backend follow-ups

The visible report polls its detail, artefacts and task snapshot every 15 seconds while the app is
active. It takes a fresh lightweight snapshot on foreground or route return. Today pages and
signals are not part of that interval. Known PRs stay visible during background refetches. Stream
PR/status/turn changes invalidate these lightweight queries, throttled to one refresh per two
seconds; message chunks do not cause network refetches. Task or run changes abort the old follower,
and canceled responses and permission deliveries cannot update its successor.

A dropped stream uses the bounded retry budget above, showing reconnecting during retries and
unavailable after exhaustion or a fatal admission response. Terminal snapshots clear connection
warnings. A nonterminal `stream-end` keeps an idle turn idle and otherwise makes execution unknown.
Polling the current task continues to discover later resumes after the stream has ended.

These frontend rules cannot prove that an external agent is active, that monitoring is scheduled,
that a replayed input is still outstanding, or that CI belongs to the latest PR head. The API needs
authoritative snapshots for those states. The concrete backend work is tracked in
[GAPS.md](GAPS.md#agent-state-backend-backlog). Automatic permission routing remains the existing
client policy; moving it to the server is separate backend work, not part of this frontend change.
