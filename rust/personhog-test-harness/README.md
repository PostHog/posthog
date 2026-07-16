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

# Kill the coordinator: bring-up guarantees the first router holds the
# election, traffic targets the last; the kill revokes the election lease so
# failover is immediate and a later handoff runs under the new coordinator
target/debug/personhog-test-harness gate --leaders 3 --routers 2 --duration 20s \
  --router-kill-after 5s --shutdown-after 9s

# Compound: kill the target pod of an in-flight handoff (best-effort timing —
# fires on the first handoff observed after the shutdown/scale-up)
target/debug/personhog-test-harness gate --leaders 3 --duration 20s \
  --shutdown-after 5s --kill-handoff-target
```

### Known defects these scenarios reproduce

Four real leader-path bugs surfaced under specific gate configurations; one is fixed and gated, three remain open.
They are documented here so red or noisy runs read as signal, not harness flakiness.

**Cache eviction under writer lag loses acked writes — FIXED, now a CI regression gate.**
`--cache-capacity` sets the leader cache size in entries; below `--persons` it forces eviction of dirty entries whose writes the writer has not yet flushed.
Every operation used to reload the stale Postgres row on the next miss, later merges built on the stale base, and acked writes disappeared (this exact configuration once produced 4,886 violations).
The leader now marks every acked produce in a dirty index and recovers evicted marked persons from their changelog record instead of trusting PG; the scenario runs in CI (with a writer pause to guarantee the lag) and must stay green:

```bash
target/debug/personhog-test-harness gate --leaders 3 --partitions 8 --persons 50 \
  --cache-capacity 10 --duration 15s --writer-pause-after 3s --writer-pause-duration 8s
```

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

**A crashed coordinator blocks all handoffs for 10–20s — currently masked in the gate.**
The coordinator election is a lease-backed CAS (15s TTL, 5s keepalives, 5s campaign retry); a crash of the router holding it leaves the key in place until the lease expires, and no handoff can start until a survivor wins.
Leader crashes are usually unaffected (their own 30s registration lease gates discovery anyway), but a leader *drain* during the window stalls — which today, combined with the unordered-shutdown defect above, black-holes the draining pod's partitions for the whole gap (observed: 731 failed writes in ~10s at harness scale; one served strong read also returned NotFound for a person with acked writes, unreproduced and unexplained).
The gate's coordinator-kill scenario deliberately revokes the election lease to stay deterministic, so it does NOT exercise this window; the slow-failover variant is worth adding once the shutdown ordering is fixed and traffic survives the wait.
Fix direction: release the election on graceful exit reliably (the best-effort revoke can be dropped by the surrounding `select!` before it runs), and/or tune the election lease and retry intervals against the drain grace budget.

**A drain overlapping a pod death wedges convergence for the drained pod's full lifecycle timeout — the gate waits it out.**
The rebalance a drain triggers can race a concurrent pod death and create handoffs targeting the dead pod (self-healing: stale-handoff cleanup deletes them within a tick), but the re-drive rebalance still counts the *draining* pod as an assignment target — nothing marks it as leaving — and hands partitions back to it.
Its gRPC server is already dead (the unordered-shutdown defect above) and its coordination component gets only a 5s grace, so those handoffs stall in Draining with no DrainedAck; rebalancing is globally deferred while any handoff is in flight, so nothing can converge until the pod's 30s lifecycle timeout force-exits it, deregistration fires, and cleanup plus a fresh rebalance finally move everything to survivors (observed: ~36s end to end, with the affected partitions black-holed throughout).

```bash
# Nondeterministic: wedges only when the mid-drain rebalance picks the
# draining pod as a target. The signature is a large "settled in Ns" line
# and an elevated Failed count.
target/debug/personhog-test-harness gate --routers 2 --leaders 3 --duration 18s \
  --router-kill-after 4s --shutdown-after 8s --kill-handoff-target
```

Verification waits for convergence (bounded at 90s) before asserting strong reads, so the gate stays green through the wedge; red here means convergence itself failed.
Fix direction: the ordered-shutdown fix removes both halves (the server survives the drain, and coordination lives to write DrainedAck, collapsing "settled in" to near-zero — at which point the convergence deadline can tighten to re-gate on recovery time).
Independently worth fixing: draining pods should be excluded as rebalance targets, and one stuck handoff should not defer all rebalancing.

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
