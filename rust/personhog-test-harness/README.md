# personhog-test-harness

Load, consistency, and e2e correctness harness for the personhog leader path.
Revived from the original personhog-cannon draft (#55581) and extended with stack orchestration, Postgres seeding, and an acked-write journal so it can gate CI, not just generate load.

The core invariant it checks: **every write acked by the leader path is visible afterwards** — in strong reads immediately, and in Postgres (with exactly the acked version) once the writer drains.
Every acked update is journaled under a unique property key, so the final state must contain all of them regardless of how concurrent writers interleaved.
Version monotonicity is asserted throughout: an ack observing a lower version than an earlier ack for the same person, or a strong read observing a version below the highest ack, is a violation.

## Requirements

The docker-compose dev dependencies must be running: Postgres (`posthog_persons`), Kafka, and etcd (`COMPOSE_PROFILES=etcd`).
For `gate` without `--external-router-url`, build the service binaries first:

```bash
cargo build -p personhog-replica -p personhog-router -p personhog-leader -p personhog-writer -p personhog-test-harness
```

## `gate` — the e2e correctness gate

Brings up an isolated stack (replica, writer, N leaders, leader-mode router hosting the coordinator), seeds persons, drives update traffic, verifies strong reads and Postgres, cleans up, and tears down.
Exits non-zero on any violation.

```bash
target/debug/personhog-test-harness gate --duration 10s --persons 100 --concurrency 10

# More leaders/partitions
target/debug/personhog-test-harness gate --leaders 3 --partitions 8 --duration 30s

# Against an already-running stack instead of spawning one. The dev stack's
# writer targets personhog_person_tmp, so tell the verifier to read it there.
target/debug/personhog-test-harness gate --external-router-url http://127.0.0.1:50054 \
  --pg-target-table personhog_person_tmp
```

The spawned stack is isolated from the dev stack: its own port range (51xxx), its own etcd prefix (`/personhog-test-harness/`), and a per-run changelog topic (`personhog_test_harness_<run_id>`, deleted on teardown).
Persons are seeded directly in Postgres for a reserved harness team id (SQL is the interim seeding mechanism until the create RPC's future is settled; `src/seed.rs` is the swap seam).
Service logs land in `<bin-dir>/harness-logs/<run_id>/`.

Multiple local leaders work because each registers with a `host:port` pod name, which the router's address resolver dials as-is (bare pod names still resolve via DNS on the fleet-wide leader port).

### Chaos disruptions

Disruptions fire mid-traffic, scheduled relative to the start of the traffic phase (spawned stack only).
The invariant is unchanged: failed writes were never acked, but everything acked through the disruption must still be visible afterwards.

```bash
# Crash the busiest leader 5s in (SIGKILL + etcd lease revoke for instant detection)
target/debug/personhog-test-harness gate --leaders 3 --duration 15s --kill-after 5s

# Let the coordinator discover the crash via lease TTL expiry instead.
# --leader-lease-ttl shortens the lease (prod default 30s) so the dead
# window fits in a short run; expect failures on the victim's partitions
# for the full TTL — the coordinator is blind until the lease expires.
target/debug/personhog-test-harness gate --leaders 3 --duration 20s \
  --leader-lease-ttl 5 --kill-after 4s --kill-fast false

# Graceful shutdown: SIGTERM, drain, partitions hand off while traffic flows
target/debug/personhog-test-harness gate --leaders 3 --duration 15s --shutdown-after 5s

# Scale out mid-traffic, then crash the busiest leader
target/debug/personhog-test-harness gate --leaders 2 --duration 20s --scale-up-after 5s --kill-after 12s

# Zombie: SIGSTOP + lease revoke so ownership moves, then SIGCONT the old
# owner — it wakes believing it still owns its partitions
target/debug/personhog-test-harness gate --leaders 3 --duration 20s --zombie-after 4s --zombie-duration 8s

# Crash-restart the busiest leader under the same pod name (StatefulSet
# restart): it must re-register and converge on the partitions etcd says it owns
target/debug/personhog-test-harness gate --leaders 3 --duration 15s --restart-after 5s

# Writer crash-restart (at-least-once redelivery under the version guard)
# and writer pause/resume (controlled lag injection)
target/debug/personhog-test-harness gate --duration 15s --writer-crash-after 5s
target/debug/personhog-test-harness gate --duration 15s --writer-pause-after 3s --writer-pause-duration 8s

# Kill the coordinator: traffic targets the last router, chaos kills the
# first (the election winner); a later handoff runs under the new coordinator
target/debug/personhog-test-harness gate --leaders 3 --routers 2 --duration 20s \
  --router-kill-after 5s --shutdown-after 9s

# Compound: kill the target pod of an in-flight handoff (best-effort timing —
# fires on the first handoff observed after the shutdown/scale-up)
target/debug/personhog-test-harness gate --leaders 3 --duration 20s \
  --shutdown-after 5s --kill-handoff-target
```

### Known defects these scenarios reproduce

Two real leader-path bugs surface under specific gate configurations.
They are documented here so red or noisy runs read as signal, not harness flakiness.

**Cache eviction under writer lag loses acked writes — the gate goes RED.**
`--cache-capacity` sets the leader cache size in entries; below `--persons` it forces eviction of dirty entries whose writes the writer has not yet flushed.
The next operation reloads the stale Postgres row, later merges build on the stale base, and acked writes disappear — exactly what the journal catches:

```bash
# Expect thousands of violations until the eviction hazard is fixed
target/debug/personhog-test-harness gate --persons 50 --cache-capacity 10 --duration 10s
```

Fix direction: pin dirty entries until the writer's committed offset passes their produce offset (see the TODO in `personhog-leader/src/cache/persons.rs`).

**Graceful shutdown black-holes the leader's partitions — elevated Failed count, gate stays green.**
The leader's lifecycle manager signals every component at SIGTERM simultaneously, so the gRPC server and Kafka producer finish shutting down (~160ms) long before the coordination drain hands partitions off (~2s: Draining status → 1s coordinator rebalance debounce → freeze → stash → fence → release).
For most of that window the pod is still the registered owner with a dead server: writes get UNAVAILABLE, the router retries against the same owner (the stash only engages once it observes Freezing), and callers fail.

```bash
# Expect ~1% failed writes. All are unacked, so the invariant holds and the
# gate passes — the signature is the Failed column, not violations.
target/debug/personhog-test-harness gate --leaders 3 --duration 15s --shutdown-after 5s
```

Fix direction: ordered shutdown — drain the coordination component before stopping the gRPC server and producer (the lifecycle crate currently has no phase/ordering primitive).
Once fixed, this run's Failed count should drop to ~0, matching the zombie scenario's.

## `seed` / `cleanup` — manage traffic targets

```bash
# Create targets; prints a copy-pasteable --person-ids list
target/debug/personhog-test-harness seed --team-id 900001 --count 100

# Remove everything the harness wrote for a team
target/debug/personhog-test-harness cleanup --team-id 900001
```

## `blast` — throughput with read-back verification

Concurrent property updates against random targets, then a strong read-back verifying every acked write.
Defaults to the dev stack's leader-mode router (`http://127.0.0.1:50054`).

```bash
target/debug/personhog-test-harness blast \
  --team-id 900001 --person-ids 42,43,44 \
  --concurrency 50 --duration 30s
```

## `consistency` — write-then-read validation

Each worker writes a unique property and immediately reads it back with STRONG consistency.

```bash
target/debug/personhog-test-harness consistency \
  --team-id 900001 --person-ids 42,43 \
  --concurrency 5 --iterations 100
```

## Output

```text
=== personhog-test-harness gate results ===
  Duration: 6.06s | Team: 900001 | Persons: 20

  Operation     Total  Success  Failed      p50      p95      p99       RPS
  writes          970      970       0   23.3ms   45.4ms   56.4ms     160.1
  reads            20       20       0    753us    1.2ms    1.3ms       3.3

  Consistency violations: 0
```

Violations are printed per person/key with expected vs actual; `__version` rows mean Postgres settled at a different version than the last ack, `__row` rows mean the person never reached Postgres at all.

Set `RUST_LOG=personhog_test_harness=debug` for per-request logging.
