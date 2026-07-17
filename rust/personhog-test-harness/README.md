# personhog-test-harness

Load, consistency, and e2e correctness harness for the personhog leader path.
Revived from the original personhog-cannon draft (#55581) and extended with stack orchestration, Postgres seeding, and an acked-write journal so it can gate CI, not just generate load.

The core invariant it checks: **every write acked by the leader path is visible afterwards** — in strong reads once coordination has converged (post-chaos handoffs re-driven; an already-settled run waits zero time, and failing to converge within 90s fails the gate), and in Postgres (at or above the highest acked version) once the writer drains.
Every acked update is journaled under a unique property key, so the final state must contain all of them regardless of how concurrent writers interleaved.
Version assignment is asserted throughout: the leader assigns each version of a person to at most one acked write, so a duplicated acked version (two writes served from the same base state), or a strong read observing a version below the highest ack, is a violation.
Read-your-write recency is asserted live: `--probers` (default 2) workers run write-then-strong-read cycles alongside the blast traffic, so a staleness window during a chaos event trips a probe even if it heals before the end-of-run verification.

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

The spawned stack is isolated from the dev stack: its own port range (24xxx, kept below the ephemeral range so outbound connections cannot steal a listen port), its own etcd prefix (`/personhog-test-harness/`), and a per-run changelog topic (`personhog_test_harness_<run_id>`, deleted on teardown).
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

# Kill the coordinator: the kill resolves the live election holder from etcd
# (the traffic router never campaigns, so it can never be the target),
# revokes the election lease so failover is immediate, and a later handoff
# runs under the new coordinator
target/debug/personhog-test-harness gate --leaders 3 --routers 3 --duration 20s \
  --router-kill-after 5s --shutdown-after 9s

# Compound: kill the target pod of an in-flight handoff (best-effort timing —
# fires on the first handoff observed after the shutdown/scale-up)
target/debug/personhog-test-harness gate --leaders 3 --duration 20s \
  --shutdown-after 5s --kill-handoff-target
```

### Known defects these scenarios reproduce

Four real leader-path bugs surfaced under specific gate configurations; two are fixed and gated, one is mostly fixed, one remains open.
They are documented here so red or noisy runs read as signal, not harness flakiness.

**Cache eviction under writer lag loses acked writes — FIXED, now a CI regression gate.**
`--cache-capacity` sets the leader cache size in entries; below `--persons` it forces eviction of dirty entries whose writes the writer has not yet flushed.
Every operation used to reload the stale Postgres row on the next miss, later merges built on the stale base, and acked writes disappeared (this exact configuration once produced 4,886 violations).
The leader now marks every acked produce in a dirty index and recovers evicted marked persons from their changelog record instead of trusting PG; the scenario runs in CI (with a writer pause to guarantee the lag) and must stay green:

```bash
target/debug/personhog-test-harness gate --leaders 3 --partitions 8 --persons 50 \
  --cache-capacity 10 --duration 15s --writer-pause-after 3s --writer-pause-duration 8s
```

**Graceful shutdown black-holes the leader's partitions — FIXED via lifecycle shutdown phases.**
The leader's lifecycle manager used to signal every component at SIGTERM simultaneously, so the gRPC server and Kafka producer finished shutting down (~160ms) long before the coordination drain handed partitions off, leaving the pod a registered owner with a dead server for the whole drain (~1% failed writes per drain).
The lifecycle crate now supports ordered shutdown phases (`ComponentOptions::with_shutdown_phase`): coordination drains in phase 0 while the server keeps serving and the producer keeps delivering, and both stop in phase 1 once the partitions are handed off.

```bash
# Expect zero failed writes through the drain.
target/debug/personhog-test-harness gate --leaders 3 --duration 15s --shutdown-after 5s
```

**A crashed or restarted coordinator blocked all handoffs for 10–30s — FIXED.**
Two leases gated failover and both could dangle. The election lease's revoke-on-exit could be dropped by an unbiased `select!` racing cancellation, so even graceful restarts stranded the election until its TTL; and a router never deregistered on exit, so freeze quorums kept counting it until its registration lease expired, stalling any handoff frozen in that window.
Graceful exits now run both revokes deterministically (measured handover: ~250ms), a failed election keepalive makes the leader abdicate instead of coordinating as a zombie beside its successor, and crash failover is bounded by tightened TTLs (election 5s + 1s campaign retry, registration 10s with 3s heartbeats).
Both paths are gated in CI and the slow-failover window is finally exercised:

```bash
# Graceful handover: SIGTERM the coordinator, then drain a leader under
# the successor. Settles in ~0s with zero failed writes.
target/debug/personhog-test-harness gate --routers 3 --leaders 3 --duration 15s \
  --router-shutdown-after 4s --shutdown-after 8s

# True crash: no lease revoked, the survivor is blind until the TTLs
# expire; a drain issued inside the window completes once they do. The
# phased leader shutdown keeps the drained pod serving throughout.
target/debug/personhog-test-harness gate --routers 3 --leaders 3 --duration 18s \
  --router-kill-after 4s --router-kill-fast false --shutdown-after 8s
```

The one served strong read that returned NotFound during the original coordinator-less drain (pre-fix, compounded by unordered shutdown) has not reproduced across the newly covered slow-failover runs with probers active.

**A drain overlapping a pod death wedged convergence for the drained pod's full lifecycle timeout — MOSTLY FIXED by the shutdown phases above.**
The rebalance a drain triggers can race a concurrent pod death and create handoffs targeting the dead pod (self-healing: stale-handoff cleanup deletes them within a tick), and the re-drive rebalance still counts the *draining* pod as an assignment target — nothing marks it as leaving — handing partitions back to it.
Before ordered shutdown, that wedged everything: the draining pod's coordination component was cancelled after a 5s grace, so those handoffs stalled with no DrainedAck until the pod's lifecycle timeout force-exited it (observed: ~36s end to end, partitions black-holed throughout).
With phased shutdown, coordination survives the whole drain and acks promptly — the composite below now settles in ~0s with only the killed pod's own crash window as failures.

```bash
target/debug/personhog-test-harness gate --routers 3 --leaders 3 --duration 18s \
  --router-kill-after 4s --shutdown-after 8s --kill-handoff-target
```

Verification still waits for convergence (bounded at 90s) before asserting strong reads; red here means convergence itself failed.
Remaining scope: draining pods should be excluded as rebalance targets (now mere churn rather than a black hole — a mid-drain rebalance can hand partitions to a pod that immediately re-drains them), and one stuck handoff should not defer all rebalancing.

**Follow-up: coalesce changelog recovery fetches if the pool ever queues.**
Recoveries check out one pooled consumer per person, so N concurrent misses on genuinely-behind persons cost N sequential Kafka point-reads once the pool saturates.
The changelog is offset-ordered, so a batch executor could assign one consumer at the lowest pending offset per partition and satisfy every waiter it passes in a single sweep (group-commit shape; bound the sweep span so sparse marks don't degenerate into scanning the gap between them).
Build this only when `personhog_leader_recovery_pool_wait_ms` shows sustained queuing.
Considered and rejected instead: a PG-first version check on marked misses (serve PG when its row version reaches the mark's).
Routing it off the prune loop's committed-offset snapshot is circular — every mark below the snapshot was already pruned by the same tick that produced it — and an unconditional PG-first probe taxes exactly the writer-lag bursts it can't help, while the 1s prune interval already shrinks its target window (applied-but-unpruned marks) to about a second.

**Follow-up: partition ownership should be invisible to clients.**
A leader refuses requests it cannot safely serve — a write against a fenced partition, or a read that races a release (both refuse *before* any state changes, so a redirect cannot double-apply) — and today those refusals propagate to the client as `FAILED_PRECONDITION`.
The router should absorb them instead: detect the not-owned refusal in the raw-proxy response (a typed header from the leader, not status-code matching), and re-stash the request if a handoff is in flight for the partition, else re-resolve the owner and retry once.
Most of the gate's residual failed writes during handoff scenarios are these refusals; with the redirect in place those counts become hard zero-failure invariants.

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
