# Common local replay failures

## Orphaned Node processes

**Symptoms:** New phrocs processes start but recordings don't flow.
Ports 6740/6741 may not be listening, or they are listening but Kafka messages aren't consumed.

**Cause:** A previous phrocs session left behind a Node.js process (ppid=1, running for days).
This orphan holds the Kafka consumer group assignment for `session_recording_snapshot_item_events`,
preventing new consumers from getting partitions.

**Diagnosis:**

```bash
# Look for node processes with ppid=1 (orphans) connected to Kafka
ps -eo pid,ppid,etime,command | grep "node.*tsx\|node.*index" | grep -v grep
# Old processes (etime showing days) with ppid=1 are orphans

# Confirm it's connected to Kafka
lsof -nP -p <PID> | grep ":9092"
```

**Fix:**

```bash
kill <orphaned_pid>
```

Then restart the `ingestion-sessionreplay` process in phrocs.
The new process will join the consumer group and get partitions assigned.

## Processes stuck at bin/wait-for-docker

**Symptoms:** Phrocs shows processes started but they never produce application output.
The process tree shows bash shells with no children.

**Cause:** `bin/wait-for-docker` polls Docker health checks for core services (db, redis7, kafka, clickhouse).
If Docker containers are slow to start or the Docker daemon is unresponsive,
processes block for up to 300s (the timeout).

**Diagnosis:**

```bash
# Check if the core Docker services are healthy
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "db|redis7|kafka|clickhouse"

# Check if processes have children (if not, they're stuck in wait-for-docker)
pgrep -f "ingestion-sessionreplay" | xargs -I{} pgrep -P {}
```

**Fix:**
If Docker services are healthy but processes are stuck, they may have started before
Docker was ready and are now zombied. Restart phrocs:

```bash
hogli stop && hogli start
```

## tsx watch silently swallowing crashes

**Symptoms:** Phrocs shows `tsx watch src/index.ts` running, but nothing happens after.
No "All systems go" message, no port listening, no error output.

**Cause:** `tsx watch` catches fatal errors and restarts silently.
The Node process crashes immediately on startup but tsx keeps restarting it
in a tight loop without surfacing the error.

**Diagnosis:**
Run the service without `watch` to see the actual error:

```bash
cd nodejs
PLUGIN_SERVER_MODE=recordings-blob-ingestion-v2 HTTP_SERVER_PORT=6740 \
  KAFKA_HOSTS=localhost:9092 \
  DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog \
  NODE_ENV=dev npx tsx src/index.ts
```

Common underlying errors:

- `ERR_REQUIRE_CYCLE_MODULE` — Node.js ESM/CJS cycle issue (check Node version compatibility)
- Missing environment variables
- Connection refused to Kafka/Postgres/Redis (Docker not ready)

**Fix:** Address the underlying error, then restart the process in phrocs.

## Port conflicts between Docker and host

**Symptoms:** Host processes can't bind to ports 6740/6741.
`lsof` shows OrbStack (Docker) already listening on those ports.

**Cause:** Both Docker containers (via `docker-compose.dev.yml` port mappings)
and host phrocs processes try to use the same ports.
The Docker `ingestion-sessionreplay` and `recording-api` services are behind
the `ingestion` profile — they should NOT be running when using phrocs.

**Diagnosis:**

```bash
lsof -nP -i :6740 -i :6741
# If OrbStack/Docker is listed, Docker containers are claiming the ports
```

**Fix:**
Stop the Docker containers that are conflicting:

```bash
docker compose -f docker-compose.dev.yml stop ingestion-sessionreplay recording-api
```

Or tear down Docker entirely and let phrocs restart it with the correct profiles:

```bash
hogli stop
docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml down
hogli start
```

## Cargo build lock contention on startup

**Symptoms:** Multiple Node processes show `Blocking waiting for file lock on package cache`
or `Blocking waiting for file lock on build directory` in their phrocs output.
Startup is very slow (5+ minutes) but eventually resolves.

**Cause:** The `bin/posthog-node` script runs `pnpm build:cyclotron:dev` which triggers
`cargo build`. When multiple Node processes start simultaneously (ingestion, ingestion-sessionreplay,
recording-api, nodejs), they all contend on Cargo's file lock.

**Fix:** This is expected on first start or after a Rust code change.
Wait for the first process to finish building — subsequent ones will be fast (cached).
If it persists, pre-build cyclotron before starting phrocs:

```bash
cd rust/cyclotron-node && cargo build
```

## Recorder script build failure

**Symptoms:** Browser console shows one or both of:

- `Refused to execute script from '.../posthog-recorder.js' because its MIME type ('text/html') is not executable`
- `Access to script at '.../lazy-recorder.js' ... blocked by CORS policy`

No `/s` calls appear in the Network tab because the recorder never loads.

**Cause:** The static recorder script files (`posthog-recorder.js`, `lazy-recorder.js`)
are missing or stale in the frontend build output. When the browser requests them,
Django doesn't find the static file and falls through to serving an HTML response
(typically the login page redirect), which the browser rejects as non-executable.

This happens after:

- A fresh checkout or branch switch
- A failed or incomplete frontend build
- Upgrading posthog-js without rebuilding

**Fix:**

```bash
pnpm --filter=@posthog/frontend build
pnpm copy-scripts
```

Then hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+R) to clear cached script references.

If on a hedgebox or remote dev environment, the same commands apply —
the recorder scripts need to be built and copied into the static files directory.

## Kafka consumer group stuck

**Symptoms:** Data is on the Kafka topic (visible in Kafka UI or kcat)
but ingestion-sessionreplay doesn't process it. No errors in logs.

**Cause:** The consumer group may be in a bad state after an unclean shutdown.
The group coordinator might be waiting for the session timeout to expire
before reassigning partitions.

**Diagnosis:**
Check the Kafka UI at `http://localhost:8080` → Consumer Groups →
look for the session recording consumer group. If it shows members
with old client IDs, the group is stale.

**Fix:**
Restart the `ingestion-sessionreplay` process in phrocs.
If that doesn't help, reset the consumer group:

```bash
# Find the consumer group name in Kafka UI, then:
docker exec posthog-kafka-1 /opt/bitnami/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --group <group_name> --reset-offsets --to-latest --execute --all-topics
```
