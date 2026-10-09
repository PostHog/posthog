# Hand-off and agent runs

How the report screen hands a report to the PostHog agent, follows the run, relays the agent's
questions, and shows the PR it opens. Code lives in `src/features/handoff/` and `src/api/tasks.ts`.

## Flow

```text
Hand off ──► kickOffReportTask ──► store.started ──► useTaskRun ──► store.live ──► mergeLiveRun ──► ActionBar
 (button or sheet)  GET report          (status card     bootstrap +     reducer       (report + live)    (footer state
                    POST tasks/          shows at once)   SSE stream                                       from actionBarStateFor)
                    POST tasks/{id}/run/
```

1. **Kickoff** (`kickoff.ts`). `GET signals/reports/{id}/` for a fresh title and summary, then the
   web's two calls:
   `POST tasks/` with `{title, description: <prompt>, origin_product: 'signal_report', signal_report, signal_report_task_relationship: 'implementation'}`
   (no `repository`), and, only when the response has no `latest_run`,
   `POST tasks/{task_id}/run/` with `{run_source: 'signal_report', signal_report_id, mode: 'interactive', pending_user_message: <prompt>, runtime_adapter: 'claude', model: 'claude-opus-5-5', reasoning_effort: 'high'}`.
   The run comes from `run`, else `latest_run`. Both calls retry a 503
   `warm_run_activation_unavailable` with `X-PostHog-Warm-Retry: <first retry_token>`, 250 ms
   doubling to 1 s, for up to 20 s.
2. **Started.** `useHandoffActions(id).handOff` stores `{taskId, runId}` in the hand-off store,
   tracks `mobile_report_handed_off`, and invalidates the report and inbox queries. While the
   calls are in flight `handOffPending` already shows the status card.
3. **Follow** (`useTaskRun.ts`). While the report screen is mounted and the app is in the
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

## Which run a report follows

The run this device started (kept in memory until the app restarts), else `report.task` from the
report adapter. The adapter picks the claim's task, else the newest implementation `task_run`
artefact.

## Stream handling

Frames follow `products/tasks/backend/presentation/views/api.py` (stream view) and the web's
`products/posthog_ai/frontend/logics/runStreamLogic.ts`. The SSE parser is `src/api/sse.ts`.

| SSE event | Handling |
| --- | --- |
| `keepalive` | Resets the 60 s idle timer. Nothing else. |
| `end` `{"type":"rotated"}` | Connection cap reached. Reconnect at once with `Last-Event-ID`. |
| `end` `{"type":"resync"}` | Drop the cursor, reconnect, take the full replay. |
| `stream-end` | Run finished. Drop the cursor, fetch the run once more, stop. |
| `error` | Server closes. Fetch the run; stop if terminal, else reconnect with backoff. |
| content (no `event:`) | Saved as the cursor (`id`), deduped by envelope `event_id`, reduced below. |

Reconnects back off 2 s doubling to 30 s, 10 attempts per drop and 30 per screen visit, and fetch
the run first so a finished run stops. A 503 at admission waits `Retry-After`. 401, 403 and 404 stop.
The first connection sends no `Last-Event-ID` (and not `start=latest`), so the server replays the
durable log (`log-<n>` ids) and a question asked before the app connected reaches the decision
card. Cursors stay in memory per run, so returning to the report resumes after the last event.

| Content frame | Effect on the live state |
| --- | --- |
| `task_run_state` | `status`, `stage`, `error_message`, `output.pr_url` / `pr_urls`. A terminal status clears the pending decision. |
| `session/update` `tool_call` | Latest tool title becomes the stage, shortened: "Read /repo/src/ChartLegend.tsx" reads "Reading ChartLegend.tsx". |
| `session/update` `tool_call_update` | Title updates of the latest call move the stage. A `completed` or `failed` update for the pending request's tool clears it (someone else answered). |
| `session/update` `agent_message_chunk` / `agent_message` | Keeps the trailing 280 characters of the agent's latest message. |
| `session/update` `current_mode_update`, `session/new` `_meta.permissionMode` | Permission mode for the tool policy. |
| `_posthog/progress` | `label` (else `detail`) overrides the tool title while the step runs; a finished step clears it. |
| `_posthog/turn_complete` | The agent waits for a message. Clears the pending request. |
| `_posthog/error` | Keeps `message` as the run error. |
| `permission_request` (live) and `_posthog/permission_request` (replay) | Runs the tool policy: allow it for the user, or surface it as a decision. Ignored when already handled, from an earlier run in the log, or when the run is terminal. |
| `_posthog/permission_resolved` (replay) | Clears the matching request and remembers its id so a replay cannot bring it back. |

The status card stage is the active step label, else the latest tool title, else the server's
`stage`, else "A PR will land here to review". There is no "step N of M": the API has no step count.

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

| Request | Card | Answer sent |
| --- | --- | --- |
| Question | `_meta.questions[0].question`; options `option_<idx>` with the label as title and the description as meta. Several questions show one at a time and go out together. | `permission_response` with `optionId` (the picked `option_<idx>` of the first question, else `option_0`), `answers` keyed by question text, and `customInput` for typed text. |
| Plan approval | "Approve the plan?" with "Approve the plan" (`auto`) and "Approve in full auto" (`bypassPermissions`), or the offered options when neither exists. | The picked mode. Typed text rejects with feedback (`customInput`). |
| Permission | "Allow {tool title}?" with the offered options. | The picked option. Typed text goes with the option that takes text, else a reject option, else the first. |
| Turn ended, no PR | "WAITING FOR YOUR REPLY" with the agent's last words and only a text field. | `user_message` (no `steer`). |

Success is `jsonrpc: '2.0'`, no `error`, and `result.resolved === true`. A 503 `sandbox_not_ready`
or `agent_session_not_ready` retries at 250, 500 and 1000 ms for up to 10 s. A 409
`permission_target_ended` or `run_ended` (or any 409 on `user_message`) means the run is over: the
card closes, a notice says the answer was not sent, and the run and report are fetched again. A
JSON-RPC error "No pending permission request" means someone else answered: the card closes.

The decided card shows the answer while it is delivered, with Undo, and after the agent confirms,
without Undo, until the run shows new activity. Undo aborts the request in flight and brings the
card back. It is best effort: a request the server already received still reaches the agent, and
answering again then gets "already moved on". Tracking: `mobile_decision_answered` with `kind`
(`question`, `plan`, `permission`, `reply`) and `picked_option`.

## Error copy

Hand-off and answer errors show as one orange line above the footer cards. The actions resolve
instead of rejecting, because every caller fires them without waiting.

| Case | Copy |
| --- | --- |
| 402 `self_driving_free_trial` | Server `detail`, else "During your free trial, Self-driving writes reports but doesn't open pull requests. Contact us to upgrade." |
| Other 402 (PR limit) | Server `detail`, else "Your organization reached its self-driving pull request limit. Ask an org admin to raise it from the Inbox usage widget." |
| 429 `signal_report_task_cap`, `throttled` | Server `error` or `detail`, else "Task limit reached for this report. Try again later." |
| Other 429 | Server copy, else "PostHog is busy. Try again in a few minutes." |
| 503 `warm_run_activation_unavailable` after 20 s | "PostHog couldn't start the agent in time. Try again." |
| 403 | Server copy, else "You don't have access to hand off reports in this project." |
| 404 | "This report is no longer available." |
| No run returned | "PostHog created the task but couldn't start it. Try again." |
| Network | "Couldn't reach PostHog. Check your connection and try again." |
| Anything else | "Couldn't hand off to PostHog. Try again." |

A failed run shows "PostHog couldn't finish" with the run's `error_message`, and a canceled one
"The run was canceled", above the hand-off button, which starts a new task.

## What is not possible

- **Undo after delivery.** The agent acts on an answer at once; there is no command to take it back.
- **Step counter.** The run has a free-text stage only, so there is no "Step N of M".
- **Background following.** Nothing streams while the report screen is closed or the app is in the
  background. A tool request that arrives then waits until a client connects; push notifications
  (`awaiting`) cover the wait.
- **Answers from other clients, live.** Resolutions appear only in the replayed log. Live, a
  request clears when its tool finishes, the turn ends, or the run ends.
- **Continuing an ended run.** A message to a run whose workflow ended needs a resume run
  (`POST tasks/{id}/run/` with `resume_from_run_id`); the app asks the user to hand off again instead.
