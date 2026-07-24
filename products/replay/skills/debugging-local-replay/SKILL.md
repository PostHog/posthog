---
name: debugging-local-replay
description: >
  Debugs why session recordings aren't appearing in the local dev environment.
  Use when a developer reports that local replay ingestion isn't working,
  recordings aren't showing up despite /s calls, or the replay pipeline
  seems broken after hogli start. Covers the full local pipeline:
  SDK capture, Caddy proxy, capture-replay (Rust), Kafka, ingestion-sessionreplay (Node),
  recording-api (Node), SeaweedFS, and common failure modes like orphaned processes,
  stuck phrocs workers, and trigger misconfiguration.
---

# Debugging local session replay

When a developer says "local replay isn't working" or "recordings aren't showing up",
work through these layers in order.
The local replay pipeline has several moving parts and failures are usually silent.

## Quick symptom guide

| Symptom                                                | Likely cause                                                                              |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| No `/s` calls in Network tab                           | SDK not recording — triggers, settings, or recorder script issue (Step 1)                 |
| `/s` calls return 200 but no recordings in list        | Ingestion pipeline broken — capture-replay, Kafka, or ingestion-sessionreplay (Steps 2-3) |
| Recordings listed but playback stuck on "Buffering..." | `recording-api` (port 6741) not running (Step 2)                                          |
| Recorder script MIME type or CORS error in console     | Frontend build stale — need `pnpm build` + `pnpm copy-scripts` (Step 1)                   |

## The local replay pipeline

```text
Browser SDK  →  /s endpoint (Caddy proxy :8000)
             →  capture-replay (Rust, :3306)
             →  Kafka (session_recording_snapshot_item_events topic)
             →  ingestion-sessionreplay (Node, :6740, PLUGIN_SERVER_MODE=recordings-blob-ingestion-v2)
             →  SeaweedFS (blob storage, :8333)
             →  recording-api (Node, :6741, PLUGIN_SERVER_MODE=recording-api)
             →  Frontend
```

A break at any point in this chain means no recordings in the UI.
The diagnostic approach is to find where the chain breaks.

## Step 1 — Is the SDK even trying to record?

Ask the developer to open browser DevTools Network tab and filter for `/s`.

**If no `/s` calls at all:**
The SDK isn't attempting to send recording data. Investigate client-side causes:

- **Triggers configured in project settings.** If URL triggers, event triggers, or linked flag triggers
  are set up, recording won't start until a trigger fires. This is the most common cause for
  developers who've been testing trigger features. Check Session replay settings in the local UI
  (Project settings > Session replay). Remove or adjust triggers to allow recording to start.
- **Recording disabled in project settings.** Session replay may be toggled off.
- **Sample rate set too low.** If `$replay_sample_rate` is < 1.0, sessions may be sampled out.
- **SDK not initialized with recording.** Check the local app's PostHog initialization —
  `session_recording` must not be explicitly disabled.
- **Wrong PostHog host.** The local app must point to `http://localhost:8000` (or wherever
  the local Caddy proxy is running).
- **Ad blocker.** Even in local dev, browser extensions can block the recorder script or `/s` endpoint.
- **Recorder script failed to load (MIME type / CORS error).** The browser console may show
  `MIME type ('text/html') is not executable` for `posthog-recorder.js` or a CORS error for
  `lazy-recorder.js`. This means Django is serving an HTML page (usually the login redirect)
  instead of the JS file — the static recorder scripts are stale or missing.
  See [recorder script build failure](./references/common-failures.md#recorder-script-build-failure).

**If `/s` calls are happening with 200 responses:**
The SDK is recording and capture is receiving data. The break is downstream — proceed to Step 2.

**If `/s` calls are returning errors (4xx/5xx):**
The capture service may be down or misconfigured. Check `capture-replay` in phrocs.

## Step 2 — Are the required processes running?

Check that these phrocs processes are running and healthy.
A "running" process that never produced output after `tsx watch src/index.ts` is effectively dead.

### Key processes and their ports

| Process                   | Port | What it does                                     |
| ------------------------- | ---- | ------------------------------------------------ |
| `capture-replay`          | 3306 | Rust service receiving `/s`, writes to Kafka     |
| `ingestion-sessionreplay` | 6740 | Node consumer processing recordings from Kafka   |
| `recording-api`           | 6741 | Node service serving replay data to the frontend |

Verify with:

```bash
lsof -nP -i :3306 -i :6740 -i :6741
```

**If ports are not listening:**
The processes haven't started or are stuck. See [common failures](./references/common-failures.md).

**If ports are listening:**
The pipeline processes are running. Proceed to Step 3.

### Docker dependencies

These Docker containers must be running and healthy:

| Container              | Purpose                          |
| ---------------------- | -------------------------------- |
| `posthog-kafka-1`      | Message bus for recording events |
| `posthog-db-1`         | Postgres for metadata            |
| `posthog-redis7-1`     | Redis for state                  |
| `posthog-clickhouse-1` | ClickHouse for session data      |
| `seaweedfs-main`       | Blob storage for recording data  |

Check with:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "kafka|db|redis7|clickhouse|seaweed"
```

All should show `(healthy)` except seaweedfs which doesn't have a health check.
If `seaweedfs-main` is missing, the `replay` Docker profile may not be active —
check the `docker-compose` phrocs process output for `--profile replay`.

## Step 3 — Is data flowing through Kafka?

If capture-replay is running and receiving `/s` calls, data should land on the
`session_recording_snapshot_item_events` Kafka topic. Check the Kafka UI at
`http://localhost:8080` (if the `debug_tools` intent is enabled) or use kcat:

```bash
kcat -b localhost:9092 -t session_recording_snapshot_item_events -C -c 5 -e
```

**If the topic is empty or doesn't exist:**
capture-replay isn't writing to Kafka. Check its phrocs logs for Kafka connection errors.

**If data is on the topic but recordings don't appear:**
ingestion-sessionreplay isn't consuming. Check if it's stuck, crashed, or if an
orphaned process is holding the consumer group (see common failures).

## Step 4 — Check SeaweedFS

Ingestion writes recording blobs to SeaweedFS. Verify it's accessible:

```bash
curl -s http://localhost:8333/ | head -5
```

The `SESSION_RECORDING_V2_S3_ENDPOINT` env var must be set correctly.
In `bin/start`, this defaults to `http://seaweedfs:8333` (the Docker hostname).
Host processes resolve this via Docker networking.

## Common failures reference

See [common failures](./references/common-failures.md) for detailed diagnosis of:

- Orphaned Node processes holding Kafka consumer groups
- Processes stuck at `bin/wait-for-docker`
- tsx watch silently swallowing crashes
- Port conflicts between Docker and host processes
- Cargo build lock contention on startup
