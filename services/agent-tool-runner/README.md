# posthog-tool-runner

A customer-deployed process that exposes in-network tools (Grafana,
Kubernetes, internal MCP servers, shell commands) to PostHog-hosted
agents via an outbound-only HTTPS protocol — no inbound ports, no
public DNS, no holes in the customer's network.

See [`docs/agent-platform/plans/self-hosted-tool-runners.md`](../../docs/agent-platform/plans/self-hosted-tool-runners.md)
for the design and wire protocol.

## What lives here

| Path                     | Purpose                                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| [`main.go`](main.go)     | Entrypoint: loads config, spawns one project-runner loop per `projects[]` entry, handles SIGINT/SIGTERM for graceful drain. |
| [`config/`](config/)     | YAML config types + loader + validator. Mirrors the example in the spec doc verbatim.                                       |
| [`protocol/`](protocol/) | JSON wire-protocol structs shared with PostHog ingress. **The contract.**                                                   |
| [`client/`](client/)     | HTTP client to the PostHog ingress (`heartbeat`, `poll`, `result`, `extend_lease`).                                         |
| [`runner/`](runner/)     | Per-project loop: register, heartbeat, long-poll, dispatch, report. Owns the `Source` interface.                            |
| [`sources/`](sources/)   | Built-in `Source` impls — `mcp` (proxy an in-cluster MCP server) and `command` (shell exec). **Currently stubbed.**         |

## Build

```sh
make build           # produces ./bin/posthog-tool-runner + ./bin/fake-posthog
make build-runner    # production binary only
make build-fake      # dev-only fake PostHog ingress only
make build-image     # builds the customer-pull-able container image
make test            # go test ./...
make lint            # go vet ./... + gofmt check
```

## Local development

Until the real PostHog ingress endpoints are built, use the bundled
`fake-posthog` binary as a stand-in. It implements the wire protocol
plus a small admin CLI for invoking tools manually.

Ready-to-run example configs live in [`examples/`](examples/) — the
smallest is [`examples/echo.yaml`](examples/echo.yaml) and a real-world
one is [`examples/k8s-local.yaml`](examples/k8s-local.yaml) for talking
to your local Kubernetes context.

```sh
# 1. Start the fake ingress (logs every request)
./bin/fake-posthog serve         # binds :18080 by default

# 2. In another terminal, start the runner against an example config
echo "phtr_local_dev" > /tmp/runner-token
./bin/posthog-tool-runner --config examples/echo.yaml

# 3. Check that the runner registered + which tools are live
./bin/fake-posthog state

# 4. Invoke a tool through the polling protocol; prints the runner's result
./bin/fake-posthog invoke --tool echo.greet --args '{"name":"ben"}'
```

> **Default ports:** fake-posthog listens on `:18080`, the runner's
> health endpoint on `:18081`. Both can be overridden via `--addr` and
> `--health-addr` respectively. Defaults avoid a clash with OrbStack /
> Docker Desktop, which claim `:8080` on macOS.

The runner is **resilient to ingress unavailability** — it retries the
initial registration with exponential backoff indefinitely, and exposes
its current state via `GET /healthz`. States: `connecting` (no
successful registration yet), `live` (registered + heartbeating),
`degraded` (registered but recent heartbeats failing). The endpoint
returns 503 unless every configured project is `live`.

## Project status

This is the **first commit of the runner-side** of the self-hosted-tool-runners
feature. The wire protocol, project-loop orchestration, and shell of both
built-in `Source` impls are in place. **Tool execution itself is stubbed**
so the loop can be exercised against the eventual PostHog ingress endpoints
before sinking time into MCP/exec wiring that might want to change shape
once we see the protocol in motion.

Stubbed work (separate follow-up commits):

- `sources/mcp.go` — open an MCP client to the configured endpoint, cache
  `listTools()`, forward `Call()` via `client.callTool`.
- `sources/command.go` — JSON Schema arg validation, safe arg-substitution
  templating, `exec.CommandContext` (no shell), stdout capture.
- `runner/runner.go` — `extend_lease` plumbing for long-running tools.

## Custom runners

Customers who need anything the reference runner doesn't cover (heavy
native code, embedded SDKs, in-memory state, custom auth flows) can
write their own runner against the same wire protocol — see
[`protocol/`](protocol/) for the canonical Go types and the spec doc
for the HTTP shapes. The PostHog side has no preference for the
reference runner over a custom one; they're indistinguishable on the
wire.
