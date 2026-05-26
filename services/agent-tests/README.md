# `@posthog/agent-tests`

End-to-end test harness for the agent platform. Boots **agent-ingress + agent-runner in the same Node process** against the local stack and validates the full request → enqueue → dequeue → execute → log path through real wires:

| Wire             | Component                                                                |
| ---------------- | ------------------------------------------------------------------------ |
| Postgres (main)  | `posthog_team`, `agent_stack_*` (apps, revisions, identity space, users) |
| Postgres (queue) | `agent_sessions` (the runner's job table)                                |
| Kafka            | `log_entries` topic (real `KafkaLogProducer` from agent-core)            |
| ClickHouse       | `log_entries` table — assertions query it directly                       |

## Running

```bash
hogli start              # in a separate terminal
pnpm --filter @posthog/agent-tests test
```

The harness throws on startup if any of the four wires aren't reachable, so the error directs you at `hogli` rather than failing mid-test.

## Why a separate package

The harness imports both `agent-ingress` and `agent-runner`. Living in either of those services would create an awkward dep direction. As its own service it stays orthogonal — `pnpm --filter agent-ingress test` runs fast unit tests, `pnpm --filter @posthog/agent-tests test` is the slow honest end-to-end.

## Structure

```text
src/
├── harness/
│   ├── cluster.ts       # AgentCluster: boots ingress + runner; owns pools, bus, Kafka producer
│   ├── fixtures.ts      # team / app / identity-space builders + CleanupRegistry
│   ├── clients.ts       # supertest wrapper, queue reader, SSE collector, Slack signing
│   ├── clickhouse.ts    # HTTP client + poll-until helpers for log_entries assertions
│   └── executors.ts     # PrincipalEchoExecutor (surfaces principal into the response message)
└── cases/
    ├── auth.test.ts             # every caller-auth policy × happy/wrong/missing
    ├── slack-identity.test.ts   # trusted / B2C / stable-id / untrusted workspace
    ├── strict-match.test.ts     # /listen /send /cancel principal matching
    └── runtime.test.ts          # full flow + ClickHouse assertion: log_entries row exists for the session
```

## Test isolation

Every fixture builder registers a teardown on the cluster's `CleanupRegistry`. `afterAll` calls `cluster.cleanup.runAll()` then `cluster.stop()`. Fixtures use deterministic slug prefixes (`e2e-…`) so cleanup is precise; team 1's `secret_api_token` is restored to its prior value.
