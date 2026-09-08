# AI browser recovery tests

This suite exercises chat submission, workflow startup, and approval delivery with Claude and Codex.
It uses the real application and sandbox agent with synthetic model responses. Chart coverage belongs in a later increment.
`run-surface.spec.ts` remains a separate, fast suite that mocks the tasks API and stream.

## Boundaries

```mermaid
flowchart LR
    Browser[Playwright / real chat UI] --> Django[Django ASGI / auth / tasks API]
    Django --> DB[(Postgres / Redis / object storage)]
    Django --> Registration[Registration barrier]
    Registration --> Temporal[Real Temporal]
    Django -->|real signals, including NOT_FOUND| Temporal
    Temporal --> Worker[Isolated tasks worker / startup barrier]
    Worker --> Agent[Checkout-built sandbox agent / Claude or Codex]
    Django --> Proxy[Approval command proxy]
    Proxy --> Agent
    Agent --> Models[Provider SSE replay server]
    Agent --> MCP[Real MCP server]
    MCP --> Django
    Agent -->|real event ingest| Django
    Django -->|real SSE| Browser
    Test[Test's TypeScript sequence] --> Controller[Test-only controller]
    Controller --> Registration
    Controller --> Worker
    Controller --> Proxy
    Controller --> Models
```

Authentication, run creation, persistence, Temporal, agent execution, MCP tool execution, and browser streaming stay real.
The launcher reuses the eval harness's Django server, Temporal worker, service startup, local skills, and sandbox lifecycle helpers.
It does not start the eval engine or require Braintrust credentials.

Only model responses and peripheral external services are simulated. Model discovery, Anthropic token counting, and Django
title generation have explicit handlers. Claude SDK session titles also use an independent, correlated handler.
Billing reads and membership updates use local endpoints. Analytics capture is disabled.
Feature flags select synchronous workflow dispatch and Django streaming, so the failure boundaries remain consistent.

The launcher installs wrappers in its own process. Workflow code contains no E2E branches.
After database setup, the launcher sets `TEST=False` and clears cached Redis clients so task streams use real Redis.
Django's unit-test commit shortcut is replaced with `transaction.on_commit`: a browser and worker need to observe committed rows.

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

| Control        | Boundary                                                                        | What remains live                                     |
| -------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `registration` | Immediately before the real `Client.start_workflow` call, after the run commits | Temporal and the unmodified signal call               |
| `worker`       | Before starting the attempt's tasks worker                                      | Temporal registration and signal acceptance           |
| `approval`     | Before forwarding the targeted `permission_response`                            | Agent session, approval card, and tool implementation |

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
```

Local mode prepares the eval databases, personhog, and an isolated Temporal server. Attach mode uses already provisioned databases and
Temporal; it still owns Django ASGI, the MCP process, and the isolated tasks worker. Configure database URLs, ClickHouse,
and personhog before entering attach mode. Pass environment overrides after the wrapper, for example
`.codex/with-flox env DATABASE_URL=postgres://posthog:posthog@localhost:5432/test_posthog hogli test:e2e:ai --attach`.
The launcher prepares frontend dependencies, including Quill's generated assets, before building a missing frontend bundle.
Run the frontend build after changing frontend code.

Each launch creates `artifacts/<launch-id>/`. Before cleanup it captures browser traces/screenshots, the consumed fixture
steps, fault timeline, run records, persisted stream, container and agent-server logs, service logs, and image provenance.
`metrics.json` records elapsed time and launcher/child peak RSS. On Linux it also samples `MemTotal - MemAvailable` every
100 ms, covering Docker services on the dedicated CI runner. `artifacts/ci/metrics.json` includes provisioning and builds;
the launch's metrics cover the launcher lifecycle. Runner memory includes the operating system and other processes, so
local measurements on a shared devbox are not isolated suite measurements.

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
The AI job reuses the backend's schema cache only when its migration, dependency, Postgres image, and routing fingerprint
matches. The existing schema restore helper seeds migration defaults; migrations still run afterwards. A miss or failed
restore falls back to the full migration history.

Regular Playwright discovery and spec selection exclude `*.ai.spec.ts`; the AI config selects them explicitly. The AI path filter
covers frontend, tasks, agent, MCP, harness, and build inputs. Older checkouts missing the tooling skip the new job's steps.
The existing required check includes AI failures and prerequisite failures. Normal triggers and the regular suite's
selection, reporting, and retry behavior remain in place. The AI job also defaults to one CI retry.

For runner validation, dispatch the workflow on the tested branch with `playwright_retries=0` and `ai_repeat_each=10`.
This runs all six runtime/case combinations ten times. Retain the workflow URL, commit, image provenance, runtime, and peak
memory with the review evidence. A local repetition run does not substitute for this runner validation.

### Runner validation: 2026-09-07

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
