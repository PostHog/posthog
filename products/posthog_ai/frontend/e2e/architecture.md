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

Python orchestration lives in `products/posthog_ai/eval_harness/test/e2e/` alongside the existing harness tests.
Browser cases, replay fixtures, and artifacts stay in `frontend/e2e/`, with thin Python entrypoints preserving the CLI commands.

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

Regular Playwright discovery and spec selection exclude `*.ai.spec.ts`; the AI config selects them explicitly. The AI path filter
covers frontend, tasks, agent, MCP, harness, and build inputs. Older checkouts missing the tooling skip the new job's steps.
The existing required check includes AI failures and prerequisite failures. Normal triggers and the regular suite's
selection, reporting, and retry behavior remain in place. The AI job also defaults to one CI retry.
The job runs alongside regular Playwright, with one AI browser worker and one active sandbox. It does not create a provider
matrix or duplicate stack setup. The normal AI job timeout is 30 minutes, including provisioning and artifact steps.

The product's `backend:test` command also collects the replay unit tests under `eval_harness/test/e2e/`.
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
