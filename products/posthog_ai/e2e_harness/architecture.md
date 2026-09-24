# AI browser recovery tests

This suite exercises chat submission, workflow startup, and approval delivery with Claude and Codex.
It uses the real application and sandbox agent with synthetic model responses, including saved-insight table rendering.
`run-surface.spec.ts` remains a separate, fast suite that mocks the tasks API and stream.
The `flows-*.spec.ts` cases use held command responses and controlled SSE frames to check composer and approval interactions.
They run in regular Playwright; `--surface` runs them against the launcher's isolated server without starting agents.
The controller rejects any real agent creation during a surface case. These cases establish UI behavior, not Temporal delivery.

`startup.ai.spec.ts` adds cold creation and completed-conversation resume for both runtimes.
The browser suppresses speculative warming: the controller owns the exact warm target, or starts cold without one.
Task creation, initial submission, and follow-up delivery remain real.
Resume completes the original workflow through its normal signal, then warms a successor behind the registration barrier.
The attempt owns and cleans up every workflow and run in that conversation.

`journeys.ai.spec.ts` covers accepted-consent deep links and real cancellation during startup and an active tool turn.
The active-turn case releases an insight-creation response after cancellation and verifies that no insight was created.
`delivery.ai.spec.ts` queues two directions while the real agent has accepted an approval but its HTTP confirmation is held.
Queue and Steer must deliver those directions once, in order, while preserving a separate draft and one persisted insight update.
`insight.ai.spec.ts` creates an insight through MCP, renders constant SQL rows, reloads, and opens the saved insight.
These cases run with both runtimes. `sidebar.ai.spec.ts` uses Claude to cover the shared SQL editor integration: apply a
suggestion to its submitting editor, navigate before another tool completes, and keep the destination editor unchanged on replay.

The warm-resume case also holds a real history read while a provider response reaches the live stream. It releases history
only after the same response is persisted, forcing overlap without fabricating frames. `liveTransport.ts` passes through
real fetch bytes, records SSE IDs, and disconnects a reader. Reconnection must carry the last observed ID, and the successor
must start without the previous run's cursor. The follow-up model request must contain the earlier assistant response.

## Boundaries

```mermaid
flowchart LR
    Browser[Playwright / real chat UI] --> Django[Django ASGI / auth / tasks API]
    Django --> DB[(Postgres / Redis / object storage)]
    Django --> Outbox[(Durable workflow outbox)]
    Outbox --> Dispatcher[Real workflow dispatcher]
    Dispatcher --> Registration[Registration barrier]
    Registration --> Temporal[Real Temporal]
    Django -->|real signals, including NOT_FOUND| Temporal
    Temporal --> Worker[Isolated tasks worker / startup barrier]
    Worker --> Agent[Checkout-built sandbox agent / Claude or Codex]
    Django --> Proxy[Approval command proxy]
    Proxy --> Agent
    Agent --> Models[Provider SSE replay server]
    Agent --> MCP[Real MCP server]
    MCP --> Django
    Agent -->|signed event ingest| AgentProxy[Source-built agent-proxy]
    AgentProxy -->|real SSE| Browser
    AgentProxy -->|authenticated callbacks| Django
    Test[Test's TypeScript sequence] --> Controller[Test-only controller]
    Controller --> Registration
    Controller --> Worker
    Controller --> Proxy
    Controller --> Models
```

Authentication, run creation, persistence, Temporal, agent execution, MCP tool execution, and browser streaming stay real.
The launcher reuses the eval harness's Django server, Temporal worker, service startup, local skills, and sandbox lifecycle helpers.
It does not start the eval engine or require Braintrust credentials.

Python orchestration stays in `products/posthog_ai/e2e_harness/`.
Browser cases and replay fixtures stay in `frontend/e2e/`; artifacts stay under the harness.

Only model responses and peripheral external services are simulated. Model discovery, Anthropic token counting, and Django
title generation have explicit handlers. Claude SDK session titles also use an independent, correlated handler.
Billing reads and membership updates use local endpoints. Analytics capture is disabled.
Feature flags select durable asynchronous workflow dispatch and agent-proxy streaming.

The launcher installs wrappers in its own process and the dispatcher child. Workflow code contains no E2E branches.
After database setup, the launcher sets `TEST=False` and clears cached Redis clients so task streams use real Redis.
Django's unit-test commit shortcut is replaced with `transaction.on_commit`: a browser and worker need to observe committed rows.

### Flag profile

`flags.json` is the committed source of truth for browser, backend, and MCP overrides. Each entry declares its boolean
value and consumers. The profile enables tasks, sequenced ingest, proxy streaming, keep-stream-open, all three durable
dispatch flags, and PostHog connections. The MCP profile also enables markdown notebooks. Other task switches have explicit
false entries. CI never fetches live flag definitions or evaluates real users' targeting rules.
The launcher also supplies the browser profile through `PERSISTED_FEATURE_FLAGS`, so it remains active when capture is disabled.
Controlled surface runs omit proxy streaming because their task streams use the mocked Django endpoint.

Backend single-flag and bulk evaluations share the same values. An undeclared Tasks or PostHog AI flag records a test
failure even if the application catches an evaluation error. Unrelated flags remain false. Add an explicit manifest entry
when introducing a flag on the exercised path; do not enable every flag. `effective-flags.json` and
`flag-evaluations.ndjson` record the profile and observed backend decisions without user targeting properties.

## Response storage and replay

Each line in `fixtures/{claude,codex}/*.ndjson` is one provider event. The files contain synthetic text or an insight-update
tool request. Tests declare their response sequence as ordinary `ResponseStep[]` values in TypeScript:

```typescript
await ai.configure([
  ai.text(firstMessage, 'First response received.', 1),
  ai.text(followupMessage, 'Follow-up response received.', 2),
])
```

For each event, replay emits an SSE frame with `event: <provider event type>` and `data: <JSON event>`, followed by a blank
line. NDJSON is only the storage format. The agent SDK consumes provider-compatible SSE.

Substitution recursively replaces explicit `{{message_id}}`, `{{tool_call_id}}`, `{{resource_id}}`, `{{text}}`, `{{model}}`,
`{{tool_name}}`, `{{tool_namespace}}`, and `{{arguments}}` placeholders. Unknown or missing substitutions fail configuration. Arguments remain a
JSON string inside the provider's argument-delta event; the test constructs them with `JSON.stringify`.

Approval sequences first discover the real MCP tool. Claude reuses the tool-request fixture for `ToolSearch`; Codex uses
`tool-search.ndjson` for its native `tool_search_call`. The next step requires that discovery result. Codex returns the
definition in `tool_search_output.tools`, with `exec` inside the `mcp__posthog` namespace. Replay validates this definition
before emitting the insight update. No tool implementation or catalog response is substituted.

There is one locked cursor per attempt. Before advancing, the controller checks:

- Project and run identity from legacy gateway headers or `X-PostHog-Properties`.
- Provider, exact model, and streaming mode.
- The expected human message and ordered conversation history.
- Explicit `history_contains` fragments, including assistant responses required by resumed conversations.
- The real tool result's call ID and expected content before sending a post-tool response.
- The requested tool is present in the agent's offered tools.

A mismatch does not advance the cursor. Unexpected endpoints, extra completions, replay errors, and unconsumed steps fail
teardown. Title generation uses a separate handler and must happen exactly once for the synthetic task.

Both `SANDBOX_LLM_GATEWAY_URL` and `SANDBOX_AI_GATEWAY_URL` point at replay. The launcher explicitly clears the new gateway's
product routing and mint key to select the legacy route, while keeping the new URL local if routing changes. Django's
gateway URLs and Anthropic title URL also point locally. Live model credentials are removed and replaced with synthetic keys.
An internal Docker network prevents the sandbox reaching public providers; the launcher rejects public outbound sockets.
Because internal networks disable Docker's published ports, a loopback TCP forwarder connects Django to the agent's private
container address. It forwards bytes without changing authentication or command responses and is removed with its attempt.
There is no live-provider fallback.

## Fault lifecycle

Every attempt owns a synthetic organization, two users, two projects, an OAuth connection, insight, task, and run.
The insight belongs to the connected project: connected-project calls require approval under the real tool policy.
Its temporary OAuth grant uses the real connection forwarding API and expires after one hour.
The controller authenticates control
requests with a temporary bearer token. Approval proxy requests retain real signed agent credentials and must belong to the
attempt's project and run.

Each control exposes `arm`, `waitUntilReached`, `release`, and `reset`. Its timeline records arming, matching requests,
release, and observations such as Temporal NOT_FOUND or the insight save. Reset releases a barrier but retains the audit of
an arm that never fired. Teardown fails if any required fault was missed.

| Control                 | Boundary                                                                         | What remains live                                        |
| ----------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `registration`          | In the dispatcher child, immediately before real `Client.start_workflow`         | Outbox claiming, leases, Temporal, and signals           |
| `worker`                | Before starting the attempt's tasks worker                                       | Temporal registration and signal acceptance              |
| `approval`              | Before forwarding the targeted `permission_response`                             | Agent session, approval card, and tool implementation    |
| `approval_confirmation` | After the real agent accepts permission, before its HTTP response reaches Django | Actual tool execution and provider requests              |
| `model`                 | After opening the provider SSE response, before its content/tool argument frames | SDK cancellation, Temporal commands, and application SSE |

Arm `model` with a zero-based response-step index, for example `await ai.fault('model').arm('2')`.
The replay cursor advances before pausing; a steering request can consume the next declared step while the old response is held.
Cancelled responses may encounter a closed socket after release. Extra model requests and unconsumed steps still fail teardown.
Every new case needs its own ten-repeat CI validation; the historical runner results below do not cover these additions.

`approval` latches the first matching permission request ID and rejects retries of that request until released. A different
request does not inherit the fault. This tests recovery from a known rejection before execution. It does not reproduce or
make claims about the uncertain history of a previous approval.

### Worked example: workflow registration

Arm registration and seed a warm run matching the synthetic user's model defaults and the composer's Auto mode.
The wrapper records the run ID and reaches the registration barrier.
Open the new-chat composer and submit the first message through the task creation endpoint.
The signal goes to real Temporal, which returns NOT_FOUND because registration is still held.
Wait for `wait/not_found`, then release registration.
The frontend retries `503 warm_run_activation_unavailable` with the signed token that pins the original run and message.
Assert the answer, send a follow-up, reload, and assert each message and answer appears once.
Assert there is still exactly one task and one run, matching the seeded identities.
Before the follow-up, abort only the browser's proxy transport and wait for its real reconnect with `Last-Event-ID`.
The original application cancellation signal remains active, so the normal stream recovery loop handles the disconnect.
The follow-up and reload assertions reject missing or duplicate messages. Every case rejects Django SSE fallback and checks
that the dispatcher accepted its outbox row, the agent received ingest/keep-open settings, and agent-proxy ingested events.

### Worked example: approval rejection

Declare tool discovery, `posthog-connection-call` wrapping `insight-update` for the seeded connected project, and text that
requires the corresponding successful tool result. Calls in the chat's own project automatically approve, so they cannot
exercise this boundary.
Send the message and wait for the real permission card. Arm approval, then click its affirmative choice once
(currently “Yes” for Claude and “Accept” for Codex). The proxy returns the agent's exact upstream
response: HTTP 400 with `{"error":"No active session for this run"}`. Assert Django translates this to HTTP 503 with
`code: "agent_session_not_ready"`. At the barrier, the composer must be editable while the approval waits for delivery.
The insight must still have its original name and zero saves.

Release the fault. The same pending approval retries and reaches the real agent. The real MCP tool renames the seeded
insight. Replay only supplies the final answer after seeing that tool result. Assert the visible completion, the persisted
new name, exactly one insight save, and exactly one successful forwarded approval. An HTTP 200 alone cannot pass this case.

## Lifecycle and evidence

Run from the repository root:

```bash
.codex/with-flox hogli test:e2e:ai --grep 'claude.*workflow waits' --retries 0
.codex/with-flox hogli test:e2e:ai --attach --repeat-each 10 --retries 0
.codex/with-flox hogli test:e2e:ai --surface --grep 'Startup and approvals' --retries 0
```

Every launch creates and drops its own application database, including attach mode. This is necessary because the real
dispatcher claims outbox rows across all teams; a unique Temporal queue cannot isolate a shared application database.
Local mode prepares eval auxiliary stores, personhog, and an isolated Temporal server. Attach mode reuses provisioned
Postgres infrastructure, auxiliary stores, and Temporal; it owns Django ASGI, MCP, agent-proxy, the dispatcher, and the tasks worker.
Configure database URLs, ClickHouse,
and personhog before entering attach mode. Pass environment overrides after the wrapper, for example
`.codex/with-flox env DATABASE_URL=postgres://posthog:posthog@localhost:5432/test_posthog hogli test:e2e:ai --attach`.
The launcher prepares frontend dependencies, including Quill's generated assets, before building a missing frontend bundle.
Run the frontend build after changing frontend code.
The configured Postgres role must be able to create and drop databases. `DATABASE_URL` supplies connection credentials;
attach mode does not dispatch work from that URL's original database. Synthetic projects use randomized IDs to avoid
reusing the same tenant keys in shared auxiliary stores after a fresh application database is created.

Agent-proxy and MCP compile once per launch and run without development watchers on allocated ports. The proxy receives
the launch's RSA public key, local Redis URL, exact browser origin, and authenticated Django callback configuration.
All three `TASKS_AGENT_PROXY_*_URL` settings point to that proxy, using the Docker-reachable hostname for sandbox ingest.
The dispatcher receives the same database, Temporal queue, and backend profile through its test bootstrap. Control requests
authenticate with the launch token and validate the active attempt, task, and run before releasing registration.

Readiness waits are bounded to 60 seconds and service exits fail the browser runner promptly. Owned process groups receive
SIGTERM, a ten-second grace period, then SIGKILL. The proxy's drain grace is reduced for suite teardown. Logs remain in the
artifact directory after database cleanup. SIGTERM to the launcher enters the same cleanup path as an interrupted browser run.

Each launch creates `artifacts/<launch-id>/`. Before cleanup it captures browser traces/screenshots, the consumed fixture
steps, fault timeline, run records, persisted stream, container and agent-server logs, service logs, and image provenance.
`metrics.json` records elapsed time and launcher/child peak RSS. On Linux it also samples `MemTotal - MemAvailable` every
100 ms, covering Docker services on the dedicated CI runner. `artifacts/ci/metrics.json` includes provisioning and builds;
the launch's metrics cover the launcher lifecycle. Runner memory includes the operating system and other processes, so
local measurements on a shared devbox are not isolated suite measurements.
The metrics also contain stage durations for provisioning commands, database preparation, image and service builds,
service readiness, and browser execution. Proxy ingest evidence is captured after the sandbox closes its upload stream.

Teardown releases outstanding barriers, terminates only the owned workflow, ends the owned run's stream, stops its worker,
removes its sandbox containers, and deletes its synthetic database resources, run storage, and Redis stream keys.
Launch-scoped cache prefixes are cleared after the services stop. Shared services survive attach-mode teardown.
The CI provisioner separately captures compose logs and removes its own compose project.

Before building the image, the launcher renders skills using an owned synthetic project for HogQL examples and deletes
that project after rendering. This also supports a freshly restored database with no projects.

The agent image uses the existing `DockerSandbox._build_local_image` path. It installs from the desktop workspace's frozen
lockfile and builds the agent and workspace dependencies from source. The built workspace stays in the local image so a
second package installation cannot resolve different dependencies. Generated `dist` and `node_modules` are excluded from
the source copy. A source/dependency fingerprint and base image ID identify the cache; the launcher verifies the image label
and records the immutable image ID and lockfile digest before creating a sandbox. Signing credentials are generated per
launch and are never baked into the image.

## CI integration

The existing `ci-e2e-playwright.yml` contains the isolated AI job. One browser worker runs one sandbox at a time.
Failed environment preparation prints the full activation logs, preserving dependency errors that the terminal summary truncates.
The AI job reuses the backend's schema cache only when its migration, dependency, Postgres image, and routing fingerprint
matches. The existing schema restore helper seeds migration defaults; migrations still run afterwards. A miss or failed
restore falls back to the full migration history.
The provisioner leaves that empty, migrated database as a template. `AI_E2E_SCHEMA_TEMPLATE=posthog_ai_e2e` is a CI-only
handoff to the launcher, which rejects a template containing tasks and clones it into its launch-owned database. This
avoids repeating schema restore and migrations for the browser phase. Standalone launches restore and migrate their own database.

Regular Playwright discovery, spec selection, and the new-spec flake verifier exclude `*.ai.spec.ts`. The shared
`playwright/playwright.config.ts` defines an `ai` project that matches them, and only when `AI_E2E_OUTPUT` is set, because a
plain `playwright test` runs every project it finds and this one needs the launcher's stack. The launcher runs
`--project=ai` with one worker, so the suite keeps the shared quarantine reporter, the JUnit output with retries, and the
Trunk ownership map. The AI path filter covers the PostHog AI and tasks products, the MCP and agent-proxy services, the
sandbox image inputs, the shared Playwright tree, and the environment manifests; a change elsewhere in the app is left to
the regular suite. Older checkouts missing the tooling skip the new job's steps.
The AI job reports its own check and does not feed the required Playwright gate. It runs alongside regular Playwright,
with one AI browser worker and one active sandbox, and defaults to one CI retry. It does not create a provider matrix or
duplicate stack setup. The normal AI job timeout is 30 minutes, including provisioning and artifact steps.

The product's `backend:test` command also collects the replay unit tests under `e2e_harness/`.
Those checks validate fixture matching and fault controls without booting a browser or sandbox agent.

For runner validation, dispatch the workflow on the tested branch with `ai_repeat_each=10`. This selects a 90-minute job
and forces zero AI retries; an explicit nonzero retry override is rejected. `ai_repeat_each=1` selects the normal job.
This runs every real-service runtime/case combination ten times. Retain the workflow URL, commit, image provenance, runtime, and peak
memory with the review evidence. A local repetition run does not substitute for this runner validation.

### Runner validation: 2026-09-07

This historical result used synchronous dispatch and Django streaming. It does not validate the proxy/dispatcher profile.
That profile still requires its own CI repetition run and cold/warm normal-job timing evidence.

[CI run 34134228895](https://github.com/PostHog/posthog/actions/runs/34134228895/job/101781375259) passed all 60 executions
at commit `491dac51e71767e71912410b0f7e281893268e84`, with zero retries, one browser worker, and one active sandbox.
The runner was `depot-ubuntu-24.04-8` on Linux x86-64.

| Case                  | Claude passes | Claude duration | Codex passes | Codex duration |
| --------------------- | ------------- | --------------- | ------------ | -------------- |
| Workflow registration | 10/10         | 16.4–27.5 s     | 10/10        | 16.5–18.5 s    |
| Queued worker         | 10/10         | 16.8–18.1 s     | 10/10        | 16.1–19.8 s    |
| Approval rejection    | 10/10         | 12.3–14.8 s     | 10/10        | 12.2–14.1 s    |

Browser execution took 16.8 minutes. Provisioning, builds, and the suite took 1,484.6 seconds (24.7 minutes), excluding Flox
environment preparation. Peak runner memory was 14.01 GiB across that interval and 8.41 GiB during the launcher lifecycle,
sampled every 100 ms. These measurements include the operating system and Docker services.

The artifact audit verified all 60 fault timelines, consumed response sequences, and title requests. Every registration
attempt observed real Temporal NOT_FOUND before release. Every worker attempt accepted a signal before worker release.
All 20 approvals recorded one insight save and one successful forwarded command, with no replay or controller errors.

The `ai-playwright-results` artifact contains the traces, service logs, timelines, metrics, and image provenance. Its image
ID is `sha256:1321279cd7c3336e9e57372ff9eac70b5f26ec284bfd9d202e0ab6de6b2459a8`, with source fingerprint
`cad1caba2fcb4e286eadce155f2aa5d7e8bba69cf30177a0679f331c5bfa3410` and frozen lockfile fingerprint
`2b77ed7bbdd14a4f43d814786400020705ba3b2eff6720db93d742b8c450cb2e`.

## Runner notes

Run from the repository root through `.codex/with-flox hogli test:e2e:ai`. `--attach` reuses infrastructure while still
creating a fresh application database. The Postgres role must have database creation privileges. The runner drops only
its own application database; it does not dispatch another developer's queued tasks. Configure auxiliary stores and
Temporal before attaching. The launcher starts its own Django, MCP, agent-proxy, dispatcher, and tasks worker.

The committed [flag manifest](../frontend/e2e/flags.json) selects the proxy and durable dispatcher path. Browser, backend,
and MCP consumers derive their values from that file. Add an explicit entry when introducing a flag on the exercised
path. CI does not contact production feature-flag evaluation or import production targeting data.

Manual `ai_repeat_each=10` selects the 90-minute stability run and requires zero retries. Artifacts include browser traces,
proxy and dispatcher logs, effective flags, observed backend flag decisions, image provenance, per-stage timings, and peak
memory. Ten zero-retry repetitions on the actual CI runner establish stability; cold and warm normal runs establish
whether the suite fits its timeout. Historical Django-stream results do not establish stability or runtime for the proxy
profile.

The production `run_task_workflow_dispatcher` command accepts `--metrics-port` and `--health-directory`. Defaults remain
port `8001` and `/tmp`, producing `dispatcher-ready` and `dispatcher-heartbeat`. The E2E bootstrap uses an allocated
metrics port and its artifact directory so it does not collide with another dispatcher. Readiness files are removed on
shutdown.

## Readiness behavior

The browser handles two explicit startup rejections:

- Task creation and resume return `503 warm_run_activation_unavailable` with a signed retry token when Temporal confirms
  nondelivery. The browser retries the identical payload for up to 20 seconds, including the first request, and reuses
  the first token to pin the original run, workflow, and message.
- Approval delivery returns `503 agent_session_not_ready` for the exact upstream HTTP 400 no-active-session rejection.
  The browser retries for up to ten seconds and requires confirmed approval resolution.

Submission exhaustion preserves the draft, attachments, and unsent context for manual retry.
Approval submission immediately reveals the composer; failed delivery restores the approval with its answers, feedback,
and selections. An ended approval target returns `409 permission_target_ended` and clears the stale card.
Cancellation or replacement of the owning run or approval stops retries.

Transport errors, unrelated 503 responses, and JSON-RPC errors inside HTTP 200 do not qualify for automatic readiness
retries. An ambiguous transport failure could follow successful execution; replaying it could execute a tool twice.

## Regression coverage

The startup and approvals layer adds these five regression flows:

1. Cold creation and an idle follow-up keep the same task/run, model, and permission mode. Attached event context reaches the first submission once.
2. A completed conversation resumes on its intended warm successor after a real Temporal registration rejection, retaining each message once.
3. Exhausted startup retries return the draft for an explicit retry with the same payload.
4. Permission, question, and plan submissions immediately reveal an editable composer while delivery remains pending.
5. Failed approval delivery restores multi-select answers or feedback. Retrying sends the same response and preserves a separate composer draft.

`startup.ai.spec.ts` runs the first two through real services with Claude and Codex.
`flows-startup-approvals.spec.ts` checks the remaining visible interactions with controlled task API and stream responses.
The controlled suite runs with regular Playwright, or with `.codex/with-flox hogli test:e2e:ai --surface` for an isolated local server.
The task composer attaches entity context; it does not expose file uploads.
These new cases require their own ten-repeat CI validation before being described as stable.

The warm-resume case checks that the successor processes the new user message without an unsolicited continuation of the old conversation.
Replay rejects any undeclared model turn even when the eventual follow-up and history assertions pass.

The queue and steering layer adds the next five flows in `flows-queue-steering.spec.ts`:

6. A queued follow-up waits for both approval confirmation and turn completion, in either order.
7. Steer and Escape deliver the saved queue once while preserving a separate unsent draft.
8. Steering requested during approval delivery waits for confirmation and clears its deferred action after failure.
9. Failed queue delivery preserves message order and supports explicit retry, editing, removal, and fresh delivery.
10. Escape with an empty saved queue cancels the active turn and preserves an unsent draft.

An additional case within queue submission freezes the draft debounce and submits immediately.
It checks that queued text clears from the composer after submission.
The other queue cases advance that debounce with the browser clock so they independently exercise their delivery transitions.
These are browser interaction checks with held task commands, not real agent-delivery checks.

The cancellation and history layer adds the last five flows in `flows-cancellation-history.spec.ts`:

11. Startup Stop waits for the current agent and prompt. Navigating away clears the pending cancellation intent.
12. Pending cancellation blocks duplicate Escape, steering, and approvals; a failed cancellation allows an explicit retry.
13. Context pickers and queue editors retain Escape. Main chat handles Escape while reading; the sidebar requires composer focus.
14. Sidebar attachment preserves the startup draft and focus at normal and narrow viewport widths.
15. Reload, stream reconnect, and resolution from another client leave only the current run's unresolved approval actionable.

These cases use controlled task commands and stream events. They also guard against late task creation redirecting after
navigation and main-transcript clicks leaving focus outside the Escape boundary.

## Critical journeys through real services

The next layer adds coverage across boundaries that the controlled browser cases cannot establish:

| Journey               | Browser coverage                                                                                                            |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Deep links            | `/ai?ask=…` submits once with consent already accepted; a follow-up and reload retain the conversation.                     |
| Cancellation          | Startup Stop reaches the owning agent; active-turn Stop prevents a pending insight creation; both accept a follow-up.       |
| Queue and steering    | Two saved directions wait for real approval confirmation, arrive once in order, and preserve the separate draft.            |
| History and reconnect | A real live response overlaps persisted history; reconnect uses its SSE cursor; a warm successor retains assistant history. |
| Insight results       | MCP creates one saved insight, its SQL rows render in chat, and reload and the saved-insight link retain the result.        |
| Sidebar apply-back    | A SQL suggestion reaches the submitting editor; late completion and history replay leave another editor unchanged.          |

The first five run with Claude and Codex. The sidebar case uses Claude for the shared editor integration.
Provider replies use synthetic fixtures; tool execution, query results, persistence, and application streaming remain real.
The provider response barrier opens SSE before pausing so cancellation reaches an established SDK request.
Startup Stop also holds cancellation delivery until this barrier, so both runtimes cancel an active request instead of racing its creation.
The approval-confirmation barrier holds the real successful response after execution starts; it never fabricates acceptance.
These additions require ten repetitions on the actual CI runner before being described as stable.

The original recovery browser suite runs three cases for each of Claude and Codex:

- Submit from the new-chat composer while a seeded warm workflow waits for registration, recover on the original run, send a follow-up, and reload without duplicate messages.
- Submit while the worker is held, then release it and verify one persisted message and response on the original run.
- Submit one approval through an explicit startup rejection, keep the composer available, and verify exactly one real insight update.

The table below is the broader regression checklist. Controlled browser cases do not establish delivery across real services.
Existing Kea, component, and backend tests cover many individual transitions; they do not establish end-to-end behavior.

| Area                       | Flow and expected result                                                                                                                                          |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cold start                 | Create a chat without a warm run, complete a turn, and send an idle follow-up. Preserve model, permission mode, attachments, and selected context.                |
| Warm resume                | Resume a completed conversation while the successor workflow starts. Preserve history and attachments; deliver once to the intended successor.                    |
| Optimistic approvals       | Answer a question, submit permission feedback, or approve a plan. Queue a follow-up while delivery waits. Restore the same inputs on failure.                     |
| Approval and turn ordering | Hold a follow-up in **Up next** until both approval resolution and turn completion. Exercise either event arriving first.                                         |
| Steering                   | Use **Steer** or Escape to submit the saved queue during an active turn. Preserve the separate draft and verify the agent consumes the queued text once.          |
| Deferred steering          | Request steering while approval delivery waits. Submit only after confirmation; clear the deferred action on failure or replacement.                              |
| Failed queue delivery      | Restore older queued text ahead of newer text and preserve context. Require explicit retry; editing or removing the failed queue allows fresh delivery.           |
| Stopping                   | With no saved queue, Escape or Stop cancels the active turn. Show the Stop spinner and block sends, steering, and approvals until completion.                     |
| Startup stopping           | Request cancellation before attachment or agent readiness. Wait for the current agent and prompt, then cancel once. Leaving the chat cancels the pending intent.  |
| Focus ownership            | Main chat handles Escape while composing or reading. The sidebar handles it only in its composer or approval controls. Menus, dialogs, and editors retain Escape. |
| Sidebar attachment         | Type during startup and retain the draft and focus when the attached run replaces the startup view. Check normal and narrow scenes.                               |
| History and reconnects     | Reload a pending approval, reconnect, or resolve it from another client. Only the owning run's unresolved approval remains actionable.                            |

Keep deadline, token-validation, error-classification, duplicate-click, and stale-completion matrices in the existing backend and Kea tests with controlled clocks.
Use the real-service browser cases to prove delivery, visible recovery, and persisted effects across service boundaries.
Run runtime-sensitive journeys with both Claude and Codex; test focus and layout variations with the cheaper component or browser surface harness.

## Troubleshooting

- **No fixture consumed:** inspect the browser trace, then service/agent logs. Check auth, startup, and model request correlation.
- **Missing NOT_FOUND:** inspect the registration timeline. Do not replace the barrier with a timer or a mocked signal response.
- **Approval remains pending:** inspect the proxy timeline and provider tool result. A transport failure or JSON-RPC error
  inside HTTP 200 is not a safe readiness rejection and must not be retried automatically.
- **Unexpected model request:** add an explicit discovery/token/title handler only if it is a distinct protocol operation.
  Do not consume a chat response to hide it or allow live fallback.
- **Image mismatch:** rebuild through the launcher; never substitute an agent release image or another checkout's dependencies.
- **Missing services in attach mode:** verify the configured Postgres, ClickHouse, Temporal, personhog, Redis, and object-storage
  readiness. Object storage must complete credential bootstrap before the agent persists its stream.

Deadline permutations, exhausted retries, cancellation, preserved drafts/answers, stale approval ownership, JSON-RPC errors,
and ambiguous transport errors belong in the focused backend and Kea suites. They use fake clocks rather than more browsers.
