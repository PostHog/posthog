# Example runner configs

Ready-to-run configs for `posthog-tool-runner`. Each file is fully
populated — no placeholders to fill in — so you can build and run end
to end in two terminals.

## What's here

| File                               | Stands up                                                                | External deps                                                   |
| ---------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------- |
| [`echo.yaml`](echo.yaml)           | Two `command` tools backed by `/bin/echo` + `seq` — minimal sanity check | None                                                            |
| [`k8s-local.yaml`](k8s-local.yaml) | Four read-only Kubernetes tools via `kubectl`                            | `kubectl` on `$PATH` + a cluster your current context points at |

Both configs target `http://127.0.0.1:18080` (the `fake-posthog`
default) and read their bearer token from `/tmp/runner-token`.

## Quick start

From the runner's repo root:

```sh
# 1. Build both binaries
make build

# 2. Put a dev token where the configs expect it
echo "phtr_local_dev" > /tmp/runner-token

# 3. Start the fake ingress (logs every request)
./bin/fake-posthog serve

# 4. In another terminal, start the runner against an example config
./bin/posthog-tool-runner --config examples/echo.yaml

# 5. In a third terminal, invoke a tool
./bin/fake-posthog state
./bin/fake-posthog invoke --tool echo.greet --args '{"name":"ben"}'
./bin/fake-posthog invoke --tool echo.count --args '{"n":5}'
```

For the k8s example, swap step 4 for:

```sh
./bin/posthog-tool-runner --config examples/k8s-local.yaml
```

then in step 5:

```sh
./bin/fake-posthog invoke --tool k8s.namespaces_list --args '{}'
./bin/fake-posthog invoke --tool k8s.pods_list --args '{"namespace":"default"}'
```

## Writing your own

The two examples cover both styles the reference runner supports:

- **`source: command`** — shell-command tools. Args are JSON-Schema
  validated, then `${args.X}` placeholders are substituted into the
  command's argv. **No shell is invoked**, so values cannot escape
  their argv slot.
- **`source: mcp`** — proxies an in-cluster MCP server (e.g. official
  Grafana MCP, Kubernetes MCP). Not exercised in these examples
  because they assume nothing is running locally — drop in your
  upstream MCP URL when you have one.

Refer to [`docs/agent-platform/plans/self-hosted-tool-runners.md`](../../../docs/agent-platform/plans/self-hosted-tool-runners.md)
for the full design, including the wire protocol, the McpRef shape,
and the per-MCP approval-policy model.
