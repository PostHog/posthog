# personhog-test-harness

Load, consistency, and e2e correctness harness for the personhog leader path.
Revived from the original personhog-cannon draft (#55581) and extended with stack orchestration, Postgres seeding, and an acked-write journal so it can gate CI, not just generate load.

The core invariant it checks: **every write acked by the leader path is visible afterwards** — on the person it was written to, or on the survivor once a merge folded that person away — in strong reads once coordination has converged (post-chaos handoffs re-driven; an already-settled run waits zero time, and failing to converge within 30s fails the gate), and in Postgres (at or above the highest acked version) once the writer drains.
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
Persons are seeded directly in Postgres for a reserved harness team id by default; `--create-via-identity` (below) creates them through the identity service instead.
Service logs land in `<bin-dir>/harness-logs/<run_id>/`.

### Creating persons via the identity service

`--create-via-identity` swaps SQL seeding for the personhog-identity get-or-create path: the spawned stack also runs `personhog-identity`, persons are created through `GetOrCreatePersonsByDistinctIds` (stub insert on the Postgres primary, then initial `$set` properties through the router to the owning leader), and the update traffic then targets the created persons.
Each create ack is journaled like any other write, so the gate holds create visibility — the initial properties and the acked version — to the same invariant as update visibility, in strong reads and in Postgres.

```bash
# Create through identity, then update through the router
target/debug/personhog-test-harness gate --create-via-identity \
  --duration 10s --persons 100 --concurrency 10

# The create path composes with chaos like any other run
target/debug/personhog-test-harness gate --create-via-identity \
  --leaders 3 --partitions 8 --duration 15s --kill-after 5s --scale-up-after 8s

# Against an already-running stack, point at its identity service too
# (the dev stack runs it at 50055)
target/debug/personhog-test-harness gate --create-via-identity \
  --external-router-url http://127.0.0.1:50054 \
  --external-identity-url http://127.0.0.1:50055 \
  --pg-target-table personhog_person_tmp
```

Multiple local leaders work because each registers with a `host:port` pod name, which the router's address resolver dials as-is (bare pod names still resolve via DNS on the fleet-wide leader port).

### Merging persons under load

`--merge-concurrency N` adds a merge lane: N workers repeatedly pick live persons and merge one or more sources into a target through `MergePersons` on the identity service, while the blast writers and probers keep writing to all of them.
Every source is a distinct live person, so each source that settles as `merged` ran the durable saga end to end (fence, seal, fold, flip, release) with writes racing the source's fence and the target's fold.
A source distinct id is reserved for one in-flight call and never reused once merged; targets are shared, so concurrent calls can contend for a person and settle as `skipped_conflict`.
`--merge-sources K` puts K sources on each call (default 1, the shape ingestion sends); the leader folds sealed sources in request order, and the journal holds the survivor to that order.
The lane implies `--create-via-identity` (merges need distinct ids) and merges identified sources by default (`--merge-identified-sources false` for `$identify` semantics, under which a survivor can never be a source again).

The invariant extends to the fold rather than stopping at it:

- The sources' acked writes are asserted on the survivor under the leader's fold rule (the survivor wins every key it has, the sources fill the rest in request order), and the folded version is claimed like any other ack.
- The merge event's own writes are asserted in the acked survivor document and afterwards: its `$set` key must be present, its `$set_once` must fill a fresh key, lose to the same event's `$set` on a shared key, and leave the seed property every person holds untouched.
- The journal is a tree: a merged source keeps its own keys and hangs off the survivor its ack named, and a live person's expected document is folded from that tree. So a source write whose ack lands after the merge was journaled still counts, even for a key an earlier fold already carried, and a survivor that merges on carries everything with it.
- A merged source must be gone: a strong read right after the ack and at end of run must answer not-found, its Postgres row must be a tombstone whose death version sits above every version the leader acked for it, and no acked version may exceed the sealed version the saga recorded on its `lifecycle_op_person` row — an ack above the seal means a write got through the fence.
- Two merges into one survivor are ordered by the folded version, not by ack arrival: the earlier fold fills a key and the later fold finds it present, which is what the journal expects.
- A merge the crash window abandons mid-saga is re-driven by the identity sweeper (the spawned identity runs it on a 3s cadence), and the delete leg waits for those ops to settle before it asserts.
- A call that loses every response (retried under the same op id) is settled after traffic from the saga's own `lifecycle_op` record: a completed merge is journaled late (safe, because folds are ordered by version), an aborted or never-started one leaves the source live, and one that never settles is a violation. Writes refused for a fenced or destroyed person are counted as lifecycle rejections, not failures.
- The delete leg expects merged sources to answer `not_found` on the first attempt.

Pathological merges — a person carrying thousands of distinct ids, every one of which the flip must repoint — get their own lane: `--merge-wide-persons N` creates N extra persons with `--merge-wide-distinct-ids K` extra mappings each (identity caps a create entry at 5000), and `--merge-wide-role source|target|both` decides which side they take.
Workers prefer a wide pair while one is available, and calls involving a wide person report as a separate `merges_wide` row so their cost does not hide in the ordinary median.
Merged sources are additionally checked for leftover mappings (`__merged_source_dids_left`): every distinct id of a destroyed person must point at the survivor.

```bash
# 5 wide sources with 2000 distinct ids each, merged into ordinary targets
target/debug/personhog-test-harness gate --merge-concurrency 2 --merge-rate 2 \
  --merge-wide-persons 5 --merge-wide-distinct-ids 2000 --merge-wide-role source \
  --persons 100 --duration 15s
```

Each merged source retires one person, so size `--persons` for sources × rate × duration; the report says when the lane ran the pool dry.
The `merges` row in the report is the baseline: one call is one saga, so its latency is the end-to-end merge cost and its RPS the merge throughput.

```bash
# Paced: 5 merges/s alongside the blast traffic
target/debug/personhog-test-harness gate --merge-concurrency 4 --merge-rate 5 \
  --persons 200 --concurrency 10 --duration 15s

# Throughput ceiling: unpaced workers, pool sized for a 10s burn
target/debug/personhog-test-harness gate --merge-concurrency 8 --persons 400 --duration 10s

# Merges through a leader kill and a scale-up: fences, folds, and death
# documents must survive the handoffs
target/debug/personhog-test-harness gate --leaders 3 --partitions 8 \
  --merge-concurrency 4 --merge-rate 5 --persons 200 --duration 15s \
  --kill-after 5s --scale-up-after 8s
```

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

# Lifecycle fence window: fence 5 persons (delete-op) at 3s, release
# (aborted) at 12s. While fenced, any write acked above the sealed version
# is a violation — writes to fenced persons must be rejected, not lost.
target/debug/personhog-test-harness gate --duration 15s \
  --fence-after 3s --fence-release-after 12s

# The fence durability property: the fence is part of the person document,
# so it must survive a leader crash-restart (recovered via warming /
# changelog recovery) — a fence that fails open after the restart acks a
# write above the seal and fails the gate
target/debug/personhog-test-harness gate --leaders 3 --duration 18s \
  --fence-after 3s --restart-after 6s --fence-release-after 14s
```

### Known defects these scenarios reproduce

Four real leader-path bugs surfaced under specific gate configurations; two are fixed and gated, one is mostly fixed, one remains open.
They are documented here so red or noisy runs read as signal, not harness flakiness.

**Cache eviction under writer lag loses acked writes — FIXED, now a CI regression gate.**
`--cache-capacity` sets the leader cache budget in bytes (entries are weighed by serialized size); set it below the seeded pool's footprint to force eviction of dirty entries whose writes the writer has not yet flushed.
Every operation used to reload the stale Postgres row on the next miss, later merges built on the stale base, and acked writes disappeared (this exact configuration once produced 4,886 violations).
The leader now marks every acked produce in a dirty index and recovers evicted marked persons from their changelog record instead of trusting PG; the scenario runs in CI (with a writer pause to guarantee the lag) and must stay green:

```bash
target/debug/personhog-test-harness gate --leaders 3 --partitions 8 --persons 50 \
  --cache-capacity 4096 --duration 15s --writer-pause-after 3s --writer-pause-duration 8s
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

Verification still waits for convergence (bounded at 30s — 2x the slow-crash TTL chain, the slowest legitimate recovery) before asserting strong reads; red here means convergence itself failed.
The two follow-ups once listed here are resolved: draining pods were never actually rebalance targets (`active_pod_names` has filtered to `Ready` pods since the original PoC — the earlier claim misread the wedge, whose real mechanism was the shutdown ordering fixed above), and a stuck handoff now defers only its own partition (the coordinator pins in-flight partitions and rebalances the rest — see `plan_partial_rebalance`).

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
  merges           80       80       0   80.6ms  197.0ms  697.3ms       5.0

  Lifecycle rejections (counted in Total, not Failed): 17 writes refused for a fenced or destroyed person
  Merge outcomes per source: merged=79 skipped_conflict=1

  Consistency violations: 0
```

Violations are printed per person/key with expected vs actual; `__version` rows mean Postgres settled at a different version than the last ack, `__row` rows mean the person never reached Postgres at all.
Merge runs add `__merged_source_alive` (a destroyed person still reads), `__merged_source_tombstone` / `__merged_source_death_version` (the source row is not a tombstone, or its death version does not sit above every acked write), `__merged_source_ack_above_seal` (the leader acked a source write above the sealed version the saga recorded — the fence failed open), `__merged_source_seal_record` (the saga left no deleted source row for a merged person), `__merged_twice` (one person destroyed by two merges), and `__merge_unsettled` (a merge that lost every response never reached a terminal step).

Set `RUST_LOG=personhog_test_harness=debug` for per-request logging.
