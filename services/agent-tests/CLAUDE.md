# agent-tests — e2e harness for the v2 agent platform

The single source of truth for whether the platform works. Real
everywhere except the model layer; one in-process cluster per test
case.

Read [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md)
for the wider dev flow. This file is the test-side contract.

## The harness

[src/harness/cluster.ts](src/harness/cluster.ts) is the only thing
tests should construct. It boots:

- **Real Postgres** at `agent_runtime_queue_test` (override with
  `AGENT_TEST_DB_URL`). Schema is **dropped + reapplied per test** —
  no leaked state between cases.
- **Real filesystem** for the bundle store, in a per-test tmp dir.
- **Real Express ingress + Worker loop + InProcessSandboxPool**.
- **Real PiAiClient** pointed at pi-ai's `faux` provider — `c.setScript([...])`
  arms the next N responses.

What the harness does NOT mock: the queue, the bundle store, the
sandbox, the tool dispatcher, the lifecycle bus, the log sink, the
identity store. Mocking any of these in a test is a smell — fix the
real implementation, or extend the harness.

## The "vital feature → case" rule

If a user can perceive a feature, it has a case in
[src/cases/](src/cases/). New trigger? Add `<trigger>-trigger.test.ts`.
New lifecycle state? Extend `lifecycle-edges.test.ts` or add a
sibling. New tool category? `native-tool.test.ts` covers the dispatcher;
add a case for the new family.

Don't reach for per-service unit tests for feature coverage — they
don't catch integration drift between ingress, runner, janitor. They're
fine for pure logic (spec parsing, sweep math) but a feature isn't
"covered" until it has a case here.

## Real-inference suite

[src/cases/real-inference.test.ts](src/cases/real-inference.test.ts)
runs the same harness against a real provider. It **runs by default**
and fails fast if no key is in env or repo-root `.env`. This is
deliberate — losing real-inference coverage is how silent pi-ai
integration drift sneaks in.

Provider order: `POSTHOG_LLM_GATEWAY_KEY`+`URL` → `ANTHROPIC_API_KEY`
→ `OPENAI_API_KEY`. Override the model with `REAL_INFERENCE_MODEL_ID`.
Skip with `AGENT_SKIP_REAL_INFERENCE=1` (CI without creds, faux-only
iteration).

## Running

```bash
pnpm --filter @posthog/agent-tests test                      # full suite
pnpm --filter @posthog/agent-tests test cases/chat-trigger   # one file
pnpm --filter @posthog/agent-tests test -- -t 'multi-turn'   # by name
```

Vitest is configured with `fileParallelism: false` (cluster.ts uses a
shared pool; running files in parallel would race on schema drops).
Don't change this without rebuilding the pool model.

## Writing a new case

Minimal shape — start from [chat-trigger.test.ts](src/cases/chat-trigger.test.ts):

```ts
import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('my feature: real e2e', () => {
  let c: Cluster
  beforeEach(async () => {
    c = await buildCluster()
  })
  afterEach(async () => {
    await c.teardown()
  })
  afterAll(async () => {
    await closeSharedPool()
  })

  it('does the vital thing', async () => {
    c.setScript([fauxText('canned response')])
    await c.deployAgent({ slug: 'x' })
    // ...fire trigger, drain, assert state.
  })
})
```

Helpers in [src/harness/faux.ts](src/harness/faux.ts): `fauxText`,
`fauxCallTool`, `fauxEndSession`. If you need a new one, add it
there — don't inline ad-hoc faux turns in cases.

## What goes where

| Concern                                          | File pattern                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Trigger surface (`/run`, `/webhook`, Slack, MCP) | `<trigger>-trigger.test.ts`                                                                |
| Lifecycle state machine                          | `lifecycle-edges.test.ts`, `worker-resume.test.ts`                                         |
| Tool dispatch + sandboxing                       | `native-tool.test.ts`, `custom-tool-sandbox.test.ts`, `dynamic-skills.test.ts`             |
| Auth + identity                                  | `auth.test.ts`, `strict-principal.test.ts`, `slack-identity.test.ts`, `cross-team.test.ts` |
| Janitor + sweep                                  | `janitor.test.ts`                                                                          |
| Logs + SSE                                       | `log-entries.test.ts`, `listen-sse.test.ts`                                                |
| Routing + control flow                           | `routing-edges.test.ts`, `control-flow.test.ts`, `queued-followups.test.ts`                |
| Real model                                       | `real-inference.test.ts` (don't add a second — extend this)                                |

If your new case doesn't fit any of these, you may be solving the
wrong problem — or you've found a new category, in which case add it
to this table.
