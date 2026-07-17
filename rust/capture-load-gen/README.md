# capture-load-gen

High-throughput load generator for the PostHog [capture](../capture) `/batch`
endpoint. Generates synthetic events shaped like real traffic (via
`common_types::RawEvent`) and drives capture at a target rate, sharding cleanly
across pods so a fleet can sum to a single cluster-wide target.

## Modes

Pick exactly one:

- **Rate** — fire at a target events/s for a fixed time:

  ```bash
  capture-load-gen --token phc_xxx --rate 50000 --duration 3m
  ```

- **Count** — send a fixed number of events then stop:

  ```bash
  capture-load-gen --token phc_xxx --count 1000000
  ```

Every request is a `/batch` POST carrying `--batch-size` events, so requests/s =
rate / batch-size. `--rate` and `--count` are expressed in **events**, not
requests.

## Common flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--endpoint` | `http://localhost:8000` (`$CAPTURE_ENDPOINT`) | Capture base URL; `/batch` is appended |
| `--token` | (`$CAPTURE_TOKEN`) | Project API token, sent as `api_key` |
| `--batch-size` | `100` | Events per `/batch` request |
| `--concurrency` | `32` | In-flight requests |
| `--no-gzip` | off | Disable gzip of the request body |
| `--distinct-ids` | `10000` | Synthetic-user cardinality |
| `--event-name` | `$pageview`, `$autocapture`, `custom_event` | Event names to pick from (repeatable) |
| `--prop-bytes` | `256` | Approx filler bytes per event |
| `--dry-run` | off | Print one sample batch as JSON and exit |

Output is a once-per-second throughput line plus a final summary with
HdrHistogram latency percentiles (p50/p95/p99).

## Sharding

One pod can't saturate capture at high rates, so the workload is split across
shards. Each shard does `1/N` of the rate (or count); the remainder goes to the
lowest indices so the fleet total is exact.

- `--shard-total N` — total shards (defaults to `$SHARD_TOTAL`, else 1)
- `--shard-index I` — this shard, 0-based (defaults to `$JOB_COMPLETION_INDEX`, else 0)

With `--rate 50000 --shard-total 10`, each shard fires at 5000 events/s; ten
shards sum to 50000.

## Deploying as a Kubernetes Indexed Job

A [Kubernetes Indexed Job](https://kubernetes.io/docs/tasks/job/indexed-parallel-processing-static/)
is the natural fit: finite work, off when idle, scales by `parallelism`.
Kubernetes injects `$JOB_COMPLETION_INDEX` per pod, and we wire `$SHARD_TOTAL`
to `completions`, so the binary self-partitions with no per-pod config.

```yaml
spec:
  completionMode: Indexed
  completions: 10        # shard total
  parallelism: 10        # all pods at once
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: capture-load-gen
          image: ghcr.io/posthog/posthog/capture-load-gen:<tag>
          # The shared rust image entrypoint is `sh -c "$BIN"` and does not
          # forward args, so override command to pass flags directly.
          command: ["/usr/local/bin/capture-load-gen"]
          args: ["--rate", "50000", "--duration", "3m"]
          env:
            - name: SHARD_TOTAL
              value: "10"
            - name: CAPTURE_ENDPOINT
              value: "http://capture:8000"
            - name: CAPTURE_TOKEN
              valueFrom: { secretKeyRef: { name: load-gen, key: token } }
```

Scaling to 100k events/s is just bumping `completions`/`parallelism` and
`SHARD_TOTAL` — the args stay the same.
