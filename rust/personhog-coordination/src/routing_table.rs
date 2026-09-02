use std::collections::{HashMap, HashSet};
use std::str::from_utf8;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex, RwLock as StdRwLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use etcd_client::{EventType, WatchStream};
use tokio::sync::RwLock;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;

use crate::authority::AuthorityClock;
use crate::error::{Error, Result};
use crate::store::{self, PersonhogStore};
use crate::types::{HandoffPhase, HandoffState, RegisteredPod, RegisteredRouter, RouterFreezeAck};
use crate::util;

/// Trait for the router-side stash handler. Implementations are responsible
/// for holding writes to a partition while a handoff is in progress, then
/// draining the stash to the new owner once the handoff completes.
#[async_trait]
pub trait StashHandler: Send + Sync {
    /// Begin stashing writes for the partition. Must be idempotent — may be
    /// called more than once for the same partition across non-terminal
    /// phase transitions (`Freezing` → `Draining` → `Warming`) and on
    /// watch reconnects.
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()>;

    /// Drain stashed writes to the given target and resume normal routing.
    /// `cancel` requests a cooperative stop: implementations yield at a
    /// request boundary, putting anything they had taken back so the full
    /// remaining stash stays parked, in order, for a successor drain.
    /// Cancellation is a routing decision, never a request outcome — no
    /// client-visible failure may result from it.
    async fn drain_stash(
        &self,
        partition: u32,
        target: &str,
        cancel: CancellationToken,
    ) -> Result<()>;

    /// Whether the partition's stash lifecycle is still open — an entry
    /// exists, holding parked requests or an unflushed (possibly empty)
    /// stash window. This is the authority the reconcile pass consults
    /// before re-requesting a drain: a settled partition has no entry
    /// (the drain's final act evicts it), while a drain that yielded
    /// early leaves the entry and its backlog behind, so re-requesting
    /// is exactly the retry mechanism. Entry existence — not backlog
    /// depth — is the correct predicate, because a completed handoff
    /// with an empty stash window still needs one drain to settle and
    /// evict the entry; gating on parked requests would leave that
    /// window open forever.
    ///
    /// Defaults to `true`, which preserves the always-request behavior
    /// for implementations that don't track stash state.
    fn stash_pending(&self, _partition: u32) -> bool {
        true
    }
}

/// Runs drains off the handoff watch loop, one lane per partition.
///
/// A drain's duration is data-plane work — it scales with queue depth,
/// arrival rate, and the health of the target pod — so it is never awaited
/// on the watch loop, where it would gate freeze acks and routing updates
/// for every partition. Lanes serialize drains per partition: requesting a
/// drain toward a different target supersedes the one in flight (its token
/// is cancelled and it yields at a batch boundary, leaving the stash entry
/// live), and the new drain starts only after the old one has fully
/// stopped, so two drains can never interleave batches toward different
/// targets. A request toward the same target is absorbed by the running
/// drain, whose loop already covers later arrivals. Observing a
/// non-terminal handoff phase pauses the lane: the running drain is
/// cancelled with no successor, so the partition stops forwarding until
/// the next `Complete` names a target — the ownership state, not the
/// drain, decides where parked requests go. Lane entries are retained
/// after completion — the map is bounded by the partition count, and a
/// finished lane costs one no-op cancel and an immediate join on the
/// next request.
struct DrainLanes {
    /// Parent of every drain token, so cancelling it stops all drains on
    /// shutdown.
    cancel: CancellationToken,
    lanes: StdMutex<HashMap<u32, Lane>>,
}

struct Lane {
    token: CancellationToken,
    handle: JoinHandle<()>,
    target: String,
}

impl DrainLanes {
    fn new(cancel: CancellationToken) -> Self {
        Self {
            cancel,
            lanes: StdMutex::new(HashMap::new()),
        }
    }

    /// Start the drain for `partition` toward `target`, superseding any
    /// drain already in flight for the partition toward a different
    /// target.
    fn request(
        &self,
        handler: Arc<dyn StashHandler>,
        router_name: String,
        partition: u32,
        target: String,
    ) {
        let token = self.cancel.child_token();
        let task_token = token.clone();
        let mut lanes = self.lanes.lock().expect("drain lanes lock poisoned");
        // A drain already running toward the same target covers everything
        // this request would: its loop keeps taking runs until it observes
        // the queue fully settled, including arrivals after this point.
        // Restarting it would only churn — cancel, put back, re-take the
        // same backlog — for no coverage gain.
        if let Some(prev) = lanes.get(&partition) {
            if prev.target == target && !prev.token.is_cancelled() && !prev.handle.is_finished() {
                return;
            }
        }
        let prev = lanes.remove(&partition);
        let task_target = target.clone();
        let handle = tokio::spawn(async move {
            if let Some(prev) = prev {
                prev.token.cancel();
                drop(prev.handle.await);
            }
            if let Err(e) = handler
                .drain_stash(partition, &task_target, task_token)
                .await
            {
                tracing::error!(
                    router = %router_name,
                    partition,
                    target = %task_target,
                    error = %e,
                    "stash drain failed; remaining stash awaits a successor drain"
                );
            }
        });
        lanes.insert(
            partition,
            Lane {
                token,
                handle,
                target,
            },
        );
    }

    /// Pause the drain for `partition`, if one is running: cancel its
    /// token without starting a successor. The drain puts anything it
    /// had taken back and exits, leaving the stash parked. Called when a
    /// non-terminal handoff phase is observed — the partition is
    /// (re-)entering a stash window, and nothing may be forwarded until
    /// the next `Complete` names the target. Idempotent; a later
    /// `request` supersedes the paused lane.
    fn pause(&self, partition: u32) {
        let lanes = self.lanes.lock().expect("drain lanes lock poisoned");
        if let Some(lane) = lanes.get(&partition) {
            lane.token.cancel();
        }
    }

    /// Cancel every lane and await the drains' termination. Runs during
    /// teardown, after the watch loop (the only source of new requests)
    /// has stopped and before the router's lease is revoked: the lease
    /// must outlive the last forward. Joining is quick — cancellation
    /// stops each drain within one in-flight request — and joining the
    /// newest handle per partition transitively joins its predecessors,
    /// which each successor task awaits before starting.
    async fn shutdown(&self) {
        self.cancel.cancel();
        let handles: Vec<JoinHandle<()>> = {
            let mut lanes = self.lanes.lock().expect("drain lanes lock poisoned");
            lanes.drain().map(|(_, lane)| lane.handle).collect()
        };
        for handle in handles {
            drop(handle.await);
        }
    }
}

/// Configuration for the routing table.
#[derive(Debug, Clone)]
pub struct RoutingTableConfig {
    pub router_name: String,
    pub lease_ttl: i64,
    pub heartbeat_interval: Duration,
    /// Fail the run when the handoff watch loop makes no progress for
    /// this long. Registration is lease-backed and the lease keepalive is
    /// its own task, so a router whose watch loop has stalled stays
    /// registered — counted in every freeze quorum — while never acking:
    /// one such router wedges every handoff in the cluster. The watchdog
    /// closes that divergence by tying the registration's fate to loop
    /// progress: on a stall the run errors out, deregisters on the way
    /// down, and the process supervisor restarts a healthy participant.
    /// `None` disables the watchdog.
    pub participant_stall_threshold: Option<Duration>,
    /// How often the watch loop re-derives its state from a fresh etcd
    /// snapshot, independent of events. Watches are the latency path;
    /// this pass is the truth path — it repairs anything a dropped,
    /// stalled, or reconnected watch stream failed to deliver, exactly
    /// as the coordinator's reconcile tick and the pod's fresh-read
    /// convergence do for theirs. It runs as an arm of the watch loop
    /// itself, so the routing table keeps a single writer and the stall
    /// watchdog supervises it too.
    pub reconcile_interval: Duration,
    /// How many consecutive reconcile-pass failures to tolerate before
    /// failing the run. A failed pass leaves the router exactly as
    /// stale as the previous tick — the watch-driven steady state — so
    /// a single failure carries no safety content and brief etcd blips
    /// must not restart the fleet; sustained outage already self-fences
    /// through the lease keepalive. The budget bounds the partial mode
    /// where snapshot reads fail while the lease stays healthy, which
    /// would otherwise silently stall the healing the pass provides
    /// (freeze-ack re-assertion, yielded-drain re-requests, address
    /// refresh).
    pub reconcile_failure_budget: u32,
    /// How many consecutive coordination-attempt failures the run
    /// supervisor tolerates before giving up and letting the process
    /// restart. An attempt that ran healthily before failing resets the
    /// count, so the budget bounds crash loops, not lifetime failures.
    pub run_retry_budget: u32,
    /// Base backoff between coordination attempts; doubles per
    /// consecutive failure up to a fixed cap.
    pub run_retry_backoff: Duration,
    /// How many freeze acks may share one transaction. Not a tuning
    /// knob but a mirror of the server's `--max-txn-ops`: a batch above
    /// it is refused outright, while a smaller one only costs an extra
    /// round trip. Defaults to etcd's own default, so it needs setting
    /// only against a server configured otherwise.
    pub max_txn_ops: usize,
}

impl Default for RoutingTableConfig {
    fn default() -> Self {
        Self {
            router_name: "router-0".to_string(),
            // A crashed router stays in every freeze quorum until its
            // registration expires, stalling any handoff frozen in that
            // window — keep the TTL short (graceful exits deregister
            // immediately on the way out).
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            participant_stall_threshold: Some(Duration::from_secs(60)),
            reconcile_interval: Duration::from_secs(5),
            reconcile_failure_budget: 12,
            run_retry_budget: 10,
            run_retry_backoff: Duration::from_millis(500),
            max_txn_ops: 128,
        }
    }
}

/// Routing table that watches etcd handoffs to keep its
/// partition-to-owner map in sync.
///
/// Ongoing routing changes are driven entirely by handoff Complete events —
/// the atomic `complete_handoff` txn writes both `phase=Complete` and the
/// new `PartitionAssignment`, and we update the local table inside the
/// handoff watch so both sides stay consistent without racing against a
/// separate assignment watch.
///
/// Initial state is loaded once at startup via `load_initial` from
/// `list_assignments`. After that, only handoff completion events mutate
/// the table. Any out-of-band write to `assignments/{partition}` is
/// invisible to routers by design; see `PersonhogStore::complete_handoff`
/// for the wider invariant.
///
/// During non-terminal phases (`Freezing`, `Draining`, `Warming`) the
/// routing table calls `StashHandler::begin_stash` and writes a
/// `RouterFreezeAck` so the coordinator can collect freeze quorum. At
/// `Complete` the table flips to the new owner and `drain_stash` flushes
/// any buffered requests through the standard forwarding path.
/// How long any of the routing table's lease revokes may take before
/// its exit path stops waiting. The routing table's own bound, not the
/// coordinator's constant: they happen to agree today, but each answers
/// to its own component budget, and sharing one number across two
/// budgets is how a retune of either silently reshapes the other.
const REVOKE_TIMEOUT: Duration = Duration::from_secs(2);

pub struct RoutingTable {
    store: Arc<PersonhogStore>,
    config: RoutingTableConfig,
    table: Arc<RwLock<HashMap<u32, String>>>,
    /// `pod_name` → advertised `host:port`, learned from the same
    /// assignments and handoff events that drive `table`, so reachability
    /// can never lag ownership. Entries for departed pods linger until
    /// overwritten; lookups only ever go through current owners. A std
    /// lock (never held across await) so the leader backend's synchronous
    /// address resolver can read it.
    addresses: Arc<StdRwLock<HashMap<String, String>>>,
}

impl RoutingTable {
    pub fn new(store: Arc<PersonhogStore>, config: RoutingTableConfig) -> Self {
        let renewal_margin = AuthorityClock::renewal_margin(config.lease_ttl);
        assert!(
            config.heartbeat_interval < renewal_margin,
            "heartbeat_interval ({:?}) must be well under the keepalive renewal margin \
             (2/3 of lease_ttl = {renewal_margin:?}): the post-renewal sleep alone would \
             exhaust the margin and the router would deregister against healthy etcd",
            config.heartbeat_interval,
        );
        Self {
            store,
            config,
            table: Arc::new(RwLock::new(HashMap::new())),
            addresses: Arc::new(StdRwLock::new(HashMap::new())),
        }
    }

    /// Look up the current owner of a partition.
    pub async fn lookup(&self, partition: u32) -> Option<String> {
        self.table.read().await.get(&partition).cloned()
    }

    /// Return a snapshot of the full routing map.
    pub async fn snapshot(&self) -> HashMap<u32, String> {
        self.table.read().await.clone()
    }

    /// Return a shared handle to the routing table.
    ///
    /// Useful for tests that need to inspect the table after moving the
    /// `RoutingTable` into a spawned task.
    pub fn table_handle(&self) -> Arc<RwLock<HashMap<u32, String>>> {
        Arc::clone(&self.table)
    }

    /// Shared handle to the pod-name → advertised-address map, for the
    /// leader backend's dialing.
    pub fn addresses_handle(&self) -> Arc<StdRwLock<HashMap<String, String>>> {
        Arc::clone(&self.addresses)
    }

    /// Run the routing table, supervising the coordination loop across
    /// etcd failures. Each attempt registers with etcd, loads the
    /// initial state, and watches the handoffs keyspace; when an attempt
    /// fails (a broken watch stream, a failed etcd write, an exhausted
    /// reconcile budget), the failure is contained here instead of
    /// killing the process: the data plane keeps serving from the
    /// last-known routing table and the stash keeps its parked clients
    /// while the coordination layer rebuilds in place through the same
    /// bootstrap that recovers a restarted process.
    ///
    /// Serving while disconnected is safe because ownership cannot move
    /// while etcd is unreachable — the coordinator cannot advance
    /// handoffs — and once etcd recovers, any handoff created before we
    /// re-register excludes us from its freeze quorum, so the old owner
    /// fences before a new owner warms and our stale forwards bounce
    /// into the drain/retry machinery rather than landing.
    ///
    /// Retries back off exponentially and are budgeted by consecutive
    /// failures (an attempt that made real progress — a reconcile pass
    /// completed, a handoff event applied — resets the count); past the
    /// budget the last error is returned and the process-restart path
    /// takes over as the backstop.
    pub async fn run(
        &self,
        cancel: CancellationToken,
        handler: Arc<dyn StashHandler>,
    ) -> Result<()> {
        const BACKOFF_CAP: Duration = Duration::from_secs(15);

        let mut consecutive_failures: u32 = 0;
        // Set by the coordination loop whenever it does real work;
        // consumed by each failure note to decide crash-loop vs fresh
        // failure. Arc because the watch loop runs as a spawned task.
        let progress = Arc::new(AtomicBool::new(false));
        loop {
            let result = self
                .run_once(cancel.clone(), Arc::clone(&handler), &progress)
                .await;
            if cancel.is_cancelled() {
                return result;
            }
            let err = match result {
                Ok(()) => return Ok(()),
                Err(e) => e,
            };

            if !util::note_run_failure(
                &mut consecutive_failures,
                &progress,
                self.config.run_retry_budget,
                "router",
                &self.config.router_name,
                &err,
            ) {
                return Err(err);
            }

            let backoff = self
                .config
                .run_retry_backoff
                .saturating_mul(2u32.saturating_pow(consecutive_failures.saturating_sub(1)))
                .min(BACKOFF_CAP);
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(backoff) => {}
            }
        }
    }

    /// One coordination attempt: register, load initial state, watch.
    /// Runs its own teardown on every exit path — tasks joined, drains
    /// joined, lease revoked best-effort (an unreachable etcd lets it
    /// lapse by TTL, which quorums already treat as departure) — so the
    /// supervisor above can always start the next attempt from a clean
    /// slate. The cancellation exits before registration are the one
    /// shape apart: nothing exists to tear down yet, and the mid-
    /// registration exit revokes its own lease inline.
    ///
    /// The `handler` implements stashing and drain. It's invoked on handoff
    /// phase transitions: `begin_stash` at Freezing, `drain_stash` at Complete.
    async fn run_once(
        &self,
        cancel: CancellationToken,
        handler: Arc<dyn StashHandler>,
        progress: &Arc<AtomicBool>,
    ) -> Result<()> {
        // How long the registered-but-not-yet-watching bootstrap may
        // take. Registration makes this router count in freeze quorums,
        // so a bootstrap that hangs past this must tear down rather than
        // stall every handoff frozen in the meantime.
        const BOOTSTRAP_DEADLINE: Duration = Duration::from_secs(30);

        // Register this router so the coordinator can count it for ack
        // quorum. Both calls race cancellation; past the grant, any
        // abandonment revokes the known lease, since a registration
        // that landed anyway would stall every freeze in its TTL
        // window.
        let granted_at = Instant::now();
        let lease_id = tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            granted = self.store.grant_lease(self.config.lease_ttl) => granted?,
        };
        let registered = tokio::select! {
            _ = cancel.cancelled() => {
                drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
                return Ok(());
            }
            registered = self.register_router(lease_id) => registered,
        };
        if let Err(e) = registered {
            // A failed registration may also have half-landed; revoking
            // clears it rather than leaving the lease to its TTL.
            drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
            return Err(e);
        }

        // From here to the supervised select below, this router is
        // registered — counted in every freeze quorum — but not yet
        // acking. Every bootstrap failure must therefore deregister on
        // the way out: returning with the lease intact would leave a
        // never-acking quorum member, re-registered afresh by every
        // supervisor retry. The same reasoning bounds the bootstrap and
        // races it against shutdown; nothing here is supervised yet (the
        // keepalive and watchdog tasks spawn only after it succeeds).
        let bootstrap = async {
            let (snapshot_revision, pods_revision) = self.load_initial(&handler).await?;

            // The pod watch anchors strictly after the pod snapshot, exactly
            // like the handoff watch below: nothing older than the snapshot
            // is ever replayed, so a registration installed by the snapshot
            // can never be regressed by a replayed predecessor. (Anchoring
            // before the snapshot — the coordinator's pattern — is only safe
            // for CAS-guarded consumers; this map is last-writer-wins.)
            let pods_stream = self.store.watch_pods_from(pods_revision + 1).await?;

            // Anchor the handoff watch to the snapshot's revision: every event
            // at or before it was handled by `load_initial`, every later one
            // is replayed by the watch regardless of when it attaches. Without
            // the anchor, an event landing between the snapshot read and the
            // watch attaching is in neither and is never redelivered.
            let handoff_stream = self
                .store
                .watch_handoffs_from(snapshot_revision + 1)
                .await?;
            Ok::<_, Error>((pods_stream, handoff_stream))
        };
        let (pods_stream, handoff_stream) = tokio::select! {
            _ = cancel.cancelled() => {
                drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
                return Ok(());
            }
            r = tokio::time::timeout(BOOTSTRAP_DEADLINE, bootstrap) => match r {
                Ok(Ok(streams)) => streams,
                Ok(Err(e)) => {
                    drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
                    return Err(e);
                }
                Err(_) => {
                    drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
                    return Err(Error::invalid_state(format!(
                        "router bootstrap exceeded {BOOTSTRAP_DEADLINE:?} while registered"
                    )));
                }
            },
        };

        // Run heartbeat and handoff watch concurrently
        let mut tasks = tokio::task::JoinSet::new();

        // Loop progress is measured against a process-local monotonic
        // epoch, immune to wall-clock steps. The watch loop stamps it
        // from a ticker arm inside its own select, so the stamp only
        // advances while the loop is actually free to iterate; the
        // watchdog task fails the run when the stamp goes stale.
        let progress_epoch = Instant::now();
        let last_progress = Arc::new(AtomicU64::new(0));
        let stamp_interval = self
            .config
            .participant_stall_threshold
            .map(|t| (t / 4).clamp(Duration::from_millis(250), Duration::from_secs(5)))
            .unwrap_or(Duration::from_secs(5));

        {
            let store = Arc::clone(&self.store);
            let interval = self.config.heartbeat_interval;
            let lease_ttl = self.config.lease_ttl;
            let token = cancel.child_token();
            tasks.spawn(async move {
                util::run_lease_keepalive(
                    store, lease_id, interval, lease_ttl, granted_at, "router", None, token,
                )
                .await
            });
        }

        if let Some(threshold) = self.config.participant_stall_threshold {
            let last_progress = Arc::clone(&last_progress);
            let router_name = self.config.router_name.clone();
            let token = cancel.child_token();
            tasks.spawn(async move {
                let mut check = tokio::time::interval(stamp_interval);
                loop {
                    tokio::select! {
                        _ = token.cancelled() => return Ok(()),
                        _ = check.tick() => {
                            let stamped_ms = last_progress.load(Ordering::Relaxed);
                            let now_ms = progress_epoch.elapsed().as_millis() as u64;
                            let stale_ms = now_ms.saturating_sub(stamped_ms);
                            if stale_ms > threshold.as_millis() as u64 {
                                return Err(Error::invalid_state(format!(
                                    "handoff watch loop of router {router_name} made no \
                                     progress for {stale_ms}ms (threshold \
                                     {}ms); failing the run so the router deregisters \
                                     and restarts as a healthy participant",
                                    threshold.as_millis()
                                )));
                            }
                        }
                    }
                }
            });
        }

        {
            let addresses = Arc::clone(&self.addresses);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_pod_addresses_loop(addresses, token, pods_stream).await
            });
        }

        // Drain lanes get their own token, torn down below: drains must
        // wind down on any exit path — including an error teardown, where
        // the caller's token was never cancelled — rather than outliving
        // the run as orphans forwarding for a deregistered router. The
        // handle is held here, not just inside the watch loop, so the
        // teardown can join the lane tasks rather than merely signal them.
        let lanes = Arc::new(DrainLanes::new(cancel.child_token()));

        {
            let store = Arc::clone(&self.store);
            let table = Arc::clone(&self.table);
            let addresses = Arc::clone(&self.addresses);
            let handler = Arc::clone(&handler);
            let router_name = self.config.router_name.clone();
            let lanes = Arc::clone(&lanes);
            let last_progress = Arc::clone(&last_progress);
            let reconcile_interval = self.config.reconcile_interval;
            let reconcile_failure_budget = self.config.reconcile_failure_budget;
            let max_txn_ops = self.config.max_txn_ops;
            let token = cancel.child_token();
            let progress = Arc::clone(progress);
            tasks.spawn(async move {
                Self::watch_handoffs_loop(
                    store,
                    table,
                    addresses,
                    handler,
                    lanes,
                    router_name,
                    token,
                    handoff_stream,
                    last_progress,
                    progress_epoch,
                    stamp_interval,
                    reconcile_interval,
                    reconcile_failure_budget,
                    max_txn_ops,
                    progress,
                )
                .await
            });
        }

        let result = tokio::select! {
            _ = cancel.cancelled() => Ok(()),
            Some(result) = tasks.join_next() => {
                result.map_err(|e| Error::invalid_state(format!("task panicked: {e}")))?
            }
        };

        // Abort and await all remaining tasks first — the watch loop is
        // the only source of new drain requests, so once it is gone the
        // lane set is final and can be joined.
        tasks.shutdown().await;

        // Cancel and JOIN every drain before touching the lease: the
        // lease must outlive the last forward, so anything a drain
        // delivered happened while this router was still a legitimately
        // registered participant. Signalling without joining would let
        // drains keep forwarding past deregistration, stretching the
        // zombie-router window beyond the lease bound the protocol's
        // residual analysis relies on.
        lanes.shutdown().await;

        // Deregister so freeze quorums stop counting this router
        // immediately. Left to lease expiry, every handoff frozen in the
        // next TTL window stalls waiting for a freeze ack this router
        // will never write. Still best-effort — an unreachable etcd lets
        // the lease lapse by TTL — but loudly so: this line is the proof
        // a graceful shutdown reached its deregistration. Bounded,
        // because an etcd that hangs rather than erring would otherwise
        // spend this component's whole shutdown budget here and turn the
        // proof into a lifecycle-abandonment log.
        match tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await {
            Ok(Ok(())) => {
                metrics::counter!(
                    "personhog_coordination_router_deregistered_total",
                    "outcome" => "revoked"
                )
                .increment(1);
                tracing::info!(
                    router = %self.config.router_name,
                    "router deregistered, freeze quorums no longer count it"
                );
            }
            Ok(Err(e)) => {
                metrics::counter!(
                    "personhog_coordination_router_deregistered_total",
                    "outcome" => "revoke_failed"
                )
                .increment(1);
                tracing::warn!(
                    router = %self.config.router_name,
                    error = %e,
                    "router lease revoke failed; registration lapses by TTL and \
                     freezes created meanwhile stall on it"
                );
            }
            Err(_) => {
                metrics::counter!(
                    "personhog_coordination_router_deregistered_total",
                    "outcome" => "revoke_failed"
                )
                .increment(1);
                tracing::warn!(
                    router = %self.config.router_name,
                    "router lease revoke unanswered after {REVOKE_TIMEOUT:?}; the request may \
                     still land — if it does not, registration lapses by TTL and freezes \
                     created meanwhile stall on it"
                );
            }
        }

        result
    }

    async fn register_router(&self, lease_id: i64) -> Result<()> {
        let now = util::now_seconds();
        let router = RegisteredRouter {
            router_name: self.config.router_name.clone(),
            registered_at: now,
            last_heartbeat: now,
        };
        self.store.register_router(&router, lease_id).await
    }

    /// Returns the etcd revisions of the handoff and pod snapshots, so
    /// the caller can anchor each watch strictly after its own snapshot.
    async fn load_initial(&self, handler: &Arc<dyn StashHandler>) -> Result<(i64, i64)> {
        // Catch up on any in-progress handoffs BEFORE populating the
        // routing table. The table starts empty, so every lookup fails
        // closed until it is loaded; opening the stashes first guarantees
        // that by the time a mid-handoff partition becomes routable it is
        // already stashing. In the reverse order there is a window where a
        // write routes to the old owner with no stash open — potentially
        // after the old owner has already drained.
        //
        // A late-joining router that observes a non-terminal handoff needs
        // to begin stashing — and if we're still in Freezing, also write a
        // FreezeAck so the coordinator's quorum can progress. Handoffs
        // already at Complete arrive as a normal Put event through the
        // watch loop below.
        let (handoffs, snapshot_revision) = self.store.list_handoffs_with_revision().await?;
        let mut acks = Vec::new();
        for handoff in handoffs {
            if matches!(
                handoff.phase,
                HandoffPhase::Freezing | HandoffPhase::Draining | HandoffPhase::Warming
            ) {
                tracing::info!(
                    router = %self.config.router_name,
                    partition = handoff.partition,
                    old_owner = ?handoff.old_owner,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    "catching up on in-progress handoff: begin stash"
                );

                handler
                    .begin_stash(handoff.partition, &handoff.new_owner)
                    .await?;

                // Only ack while still in Freezing — once the
                // coordinator advanced, the quorum has been collected
                // and a late ack is redundant (quorum evaluation matches
                // on handoff_id, so it can never count elsewhere).
                if handoff.phase == HandoffPhase::Freezing {
                    acks.push(RouterFreezeAck {
                        router_name: self.config.router_name.clone(),
                        partition: handoff.partition,
                        acked_at: util::now_seconds(),
                        acked_at_ms: 0,
                        handoff_id: handoff.handoff_id.clone(),
                    });
                }
            }
        }
        // One batched write after every stash above is open: a restart
        // during a fleet-wide freeze otherwise pays one round trip per
        // frozen partition, serially, with the freeze quorum waiting.
        self.store
            .put_freeze_acks(&acks, self.config.max_txn_ops)
            .await?;

        let assignments = self.store.list_assignments().await?;
        // Live registrations overlay assignment-carried addresses: an
        // assignment's address is a snapshot from the handoff that
        // installed the owner, and the owner may have re-registered at a
        // new address since (same pod name, new IP) without any handoff.
        // Registrations are the authority on addresses; everything else
        // is a fallback for entries the registration feed hasn't covered.
        let (pods, pods_revision) = self.store.list_pods_with_revision().await?;
        let mut table = self.table.write().await;
        {
            let mut addresses = self.addresses.write().expect("addresses lock poisoned");
            for a in &assignments {
                if let Some(address) = &a.advertise_address {
                    addresses.insert(a.owner.clone(), address.clone());
                }
            }
            for pod in pods {
                if let Some(address) = pod.advertise_address {
                    addresses.insert(pod.pod_name, address);
                }
            }
        }
        for a in assignments {
            table.insert(a.partition, a.owner);
        }
        tracing::info!(count = table.len(), "loaded initial routing table");
        drop(table);

        Ok((snapshot_revision, pods_revision))
    }

    /// Keep the address map current with pod registrations. Ownership is
    /// untouched — routing still moves only on handoff events — but a pod
    /// that re-registers under the same name at a new address (a restart
    /// that kept its assignments) must refresh where the router dials, or
    /// every dial keeps hitting the dead address until the next handoff.
    /// Deletes are ignored: a lease expiry precedes either a re-register
    /// (which overwrites) or a handoff away (after which the entry is
    /// never consulted).
    async fn watch_pod_addresses_loop(
        addresses: Arc<StdRwLock<HashMap<String, String>>>,
        cancel: CancellationToken,
        mut stream: WatchStream,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "pod")?;
                    for event in resp.events() {
                        if event.event_type() != EventType::Put {
                            continue;
                        }
                        let pod: RegisteredPod = match parse_watch_value(event) {
                            Ok(p) => p,
                            Err(e) => {
                                tracing::error!(error = %e, "failed to parse pod event");
                                continue;
                            }
                        };
                        if let Some(address) = pod.advertise_address {
                            addresses
                                .write()
                                .expect("addresses lock poisoned")
                                .insert(pod.pod_name, address);
                        }
                    }
                }
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn watch_handoffs_loop(
        store: Arc<PersonhogStore>,
        table: Arc<RwLock<HashMap<u32, String>>>,
        addresses: Arc<StdRwLock<HashMap<String, String>>>,
        handler: Arc<dyn StashHandler>,
        lanes: Arc<DrainLanes>,
        router_name: String,
        cancel: CancellationToken,
        mut stream: WatchStream,
        last_progress: Arc<AtomicU64>,
        progress_epoch: Instant,
        stamp_interval: Duration,
        reconcile_interval: Duration,
        reconcile_failure_budget: u32,
        max_txn_ops: usize,
        progress: Arc<AtomicBool>,
    ) -> Result<()> {
        let mut consecutive_reconcile_failures: u32 = 0;
        // The stamp arm can only run while the loop is free to iterate —
        // an event handler stuck in an inline await freezes the stamp,
        // which is exactly what the watchdog listens for.
        let mut stamp_tick = tokio::time::interval(stamp_interval);
        // The truth path: periodically re-derive stash, table, and drain
        // state from a fresh snapshot, repairing whatever the event path
        // failed to deliver. An arm of this loop on purpose — the routing
        // table keeps a single writer, and a reconcile that hangs stops
        // the progress stamp and trips the watchdog.
        // First pass one full interval out: load_initial has just done
        // this exact convergence, and an immediate re-pass would only
        // duplicate handler calls.
        let mut reconcile_tick = tokio::time::interval_at(
            tokio::time::Instant::now() + reconcile_interval,
            reconcile_interval,
        );
        // Banked ticks after a slow event handler would fire back to
        // back, each failing fast during an outage and burning the
        // failure budget in milliseconds instead of one tick of real
        // staleness per count.
        reconcile_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = stamp_tick.tick() => {
                    last_progress.store(
                        progress_epoch.elapsed().as_millis() as u64,
                        Ordering::Relaxed,
                    );
                }
                _ = reconcile_tick.tick() => {
                    // A failed pass is tolerated: the router is exactly
                    // as stale as one tick ago (the watch-driven steady
                    // state), and the next successful pass compensates
                    // fully. Making single failures fatal would let a
                    // brief etcd blip restart every router in the fleet
                    // simultaneously; sustained outage is the lease
                    // keepalive's job. The consecutive budget bounds the
                    // partial-failure mode where reads fail while the
                    // lease stays healthy.
                    match Self::reconcile_pass(
                        &store,
                        &table,
                        &addresses,
                        &handler,
                        &lanes,
                        &router_name,
                        max_txn_ops,
                    )
                    .await
                    {
                        Ok(()) => {
                            progress.store(true, Ordering::SeqCst);
                            consecutive_reconcile_failures = 0;
                        }
                        Err(e) => {
                            consecutive_reconcile_failures += 1;
                            metrics::counter!(
                                "personhog_coordination_reconcile_failures_total",
                                "component" => "router"
                            )
                            .increment(1);
                            tracing::warn!(
                                router = %router_name,
                                error = %e,
                                consecutive = consecutive_reconcile_failures,
                                budget = reconcile_failure_budget,
                                "reconcile pass failed; continuing on last-known state"
                            );
                            if consecutive_reconcile_failures >= reconcile_failure_budget {
                                return Err(e);
                            }
                        }
                    }
                }
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "handoff")?;
                    let mut acks = Vec::new();
                    for event in resp.events() {
                        match event.event_type() {
                            EventType::Put => {
                                if Self::handle_handoff_put(
                                    event,
                                    &table,
                                    &addresses,
                                    &handler,
                                    &lanes,
                                    &router_name,
                                    &mut acks,
                                ).await?
                                {
                                    progress.store(true, Ordering::SeqCst);
                                }
                            }
                            EventType::Delete => {
                                // A handoff record is never deleted while
                                // non-terminal — cancellation replaces it
                                // with the record that resolves its stashes
                                // — so a deletion has exactly one protocol
                                // meaning: cleanup after Complete, which
                                // requires nothing from the router. If a
                                // stash is somehow still open here (an
                                // out-of-protocol raw deletion), it stays
                                // parked; the reconcile tick derives
                                // disposal from durable state and drains it
                                // to the assignment owner.
                                let Some(kv) = event.kv() else { continue };
                                let key = from_utf8(kv.key()).unwrap_or("");
                                let Some(partition) = store::extract_partition_from_key(key) else {
                                    continue
                                };
                                tracing::debug!(
                                    router = %router_name,
                                    partition,
                                    "handoff record deleted"
                                );
                            }
                        }
                    }
                    // One write per response, after every event's stash
                    // is open: a response carrying a plan's worth of
                    // freezes costs one round trip instead of one per
                    // partition.
                    store.put_freeze_acks(&acks, max_txn_ops).await?;
                }
            }
        }
    }

    /// One level-triggered convergence pass over a fresh snapshot: the
    /// router's equivalent of the coordinator's reconcile tick and the
    /// pod's fresh-read convergence. Every action here is idempotent
    /// against the event path — `begin_stash` no-ops on a live entry,
    /// freeze acks are id-correlated, table writes are last-writer-wins
    /// from the authority, and drain requests are absorbed by a running
    /// same-target lane.
    ///
    /// Ordering matters exactly as in `load_initial`: stashes converge
    /// before tables, so a mid-handoff partition is stashing before it is
    /// routable. The final rule — no handoff means no stash, so drain
    /// anything parked to the assignment owner — makes stash disposal a
    /// property derived from durable state rather than a decision taken
    /// on any single event, which is what heals a missed Complete, a
    /// silently dead watch stream, or an out-of-protocol raw deletion.
    async fn reconcile_pass(
        store: &PersonhogStore,
        table: &Arc<RwLock<HashMap<u32, String>>>,
        addresses: &Arc<StdRwLock<HashMap<String, String>>>,
        handler: &Arc<dyn StashHandler>,
        lanes: &Arc<DrainLanes>,
        router_name: &str,
        max_txn_ops: usize,
    ) -> Result<()> {
        // Registrations are the address authority; refresh them wholesale
        // so a pod that re-registered at a new address is dialable even
        // when the address watch missed the event.
        let pods = store.list_pods().await?;
        {
            let mut addresses = addresses.write().expect("addresses lock poisoned");
            for pod in pods {
                if let Some(address) = pod.advertise_address {
                    addresses.insert(pod.pod_name, address);
                }
            }
        }

        let handoffs = store.list_handoffs().await?;
        let mut constrained: HashSet<u32> = HashSet::new();
        let mut acks = Vec::new();
        for handoff in &handoffs {
            constrained.insert(handoff.partition);
            match handoff.phase {
                HandoffPhase::Freezing | HandoffPhase::Draining | HandoffPhase::Warming => {
                    lanes.pause(handoff.partition);
                    handler
                        .begin_stash(handoff.partition, &handoff.new_owner)
                        .await?;
                    if handoff.phase == HandoffPhase::Freezing {
                        acks.push(RouterFreezeAck {
                            router_name: router_name.to_string(),
                            partition: handoff.partition,
                            acked_at: util::now_seconds(),
                            acked_at_ms: 0,
                            handoff_id: handoff.handoff_id.clone(),
                        });
                    }
                }
                HandoffPhase::Complete => {
                    if let Some(address) = &handoff.new_owner_address {
                        addresses
                            .write()
                            .expect("addresses lock poisoned")
                            .entry(handoff.new_owner.clone())
                            .or_insert_with(|| address.clone());
                    }
                    table
                        .write()
                        .await
                        .insert(handoff.partition, handoff.new_owner.clone());
                    // Only request a drain while the stash lifecycle is
                    // open. A settled partition has no entry, and its
                    // finished lane never absorbs (a finished drain may
                    // have yielded with backlog), so an unconditional
                    // request here would respawn a no-op drain every
                    // tick for every quiet partition.
                    if handler.stash_pending(handoff.partition) {
                        lanes.request(
                            Arc::clone(handler),
                            router_name.to_string(),
                            handoff.partition,
                            handoff.new_owner.clone(),
                        );
                    }
                }
            }
        }

        // One batched write after every stash above is open; deferring
        // an ack only delays the quorum, never lies to it.
        store.put_freeze_acks(&acks, max_txn_ops).await?;

        let assignments = store.list_assignments().await?;
        for assignment in assignments {
            if constrained.contains(&assignment.partition) {
                continue;
            }
            if let Some(address) = &assignment.advertise_address {
                addresses
                    .write()
                    .expect("addresses lock poisoned")
                    .entry(assignment.owner.clone())
                    .or_insert_with(|| address.clone());
            }
            table
                .write()
                .await
                .insert(assignment.partition, assignment.owner.clone());
            // Same gate as the Complete arm: "no handoff means no stash"
            // only demands a drain when something is actually parked or
            // a window is still open.
            if handler.stash_pending(assignment.partition) {
                lanes.request(
                    Arc::clone(handler),
                    router_name.to_string(),
                    assignment.partition,
                    assignment.owner,
                );
            }
        }
        Ok(())
    }

    async fn handle_handoff_put(
        event: &etcd_client::Event,
        table: &Arc<RwLock<HashMap<u32, String>>>,
        addresses: &Arc<StdRwLock<HashMap<String, String>>>,
        handler: &Arc<dyn StashHandler>,
        lanes: &Arc<DrainLanes>,
        router_name: &str,
        acks: &mut Vec<RouterFreezeAck>,
    ) -> Result<bool> {
        let handoff: HandoffState = match parse_watch_value(event) {
            Ok(h) => h,
            Err(e) => {
                tracing::error!(error = %e, "failed to parse handoff event");
                // Nothing was applied: an unparseable record must not
                // count as run-budget progress, or a poison record would
                // reset the budget on every delivery.
                return Ok(false);
            }
        };
        util::record_phase_watch_delivery("router", handoff.phase, handoff.phase_entered_at_ms);

        match handoff.phase {
            HandoffPhase::Freezing | HandoffPhase::Draining | HandoffPhase::Warming => {
                tracing::info!(
                    router = %router_name,
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    "beginning stash"
                );
                // A drain still running from the previous ownership era
                // must stop before this partition re-enters the stash
                // window: pausing the lane makes the running drain put
                // its in-flight entries back, so they park behind
                // nothing and drain to whatever owner the next
                // `Complete` names.
                lanes.pause(handoff.partition);
                handler
                    .begin_stash(handoff.partition, &handoff.new_owner)
                    .await?;

                // Only ack in Freezing — routers can arrive late,
                // observe a later phase, and must not re-ack a quorum
                // that has already cleared. Collected, not written: the
                // watch loop flushes one batch per response, after every
                // event's stash is open.
                if handoff.phase == HandoffPhase::Freezing {
                    acks.push(RouterFreezeAck {
                        router_name: router_name.to_string(),
                        partition: handoff.partition,
                        acked_at: util::now_seconds(),
                        acked_at_ms: 0,
                        handoff_id: handoff.handoff_id.clone(),
                    });
                }
            }
            HandoffPhase::Complete => {
                // The address must land before the table flips: the drain
                // below dials the new owner immediately. Insert only if
                // absent — the handoff carries an address snapshotted at
                // handoff creation, and the pod may have re-registered at
                // a newer address since; the registration feed (a separate
                // stream with no cross-stream ordering) is the authority
                // and must never be overwritten by this fallback.
                match &handoff.new_owner_address {
                    Some(address) => {
                        addresses
                            .write()
                            .expect("addresses lock poisoned")
                            .entry(handoff.new_owner.clone())
                            .or_insert_with(|| address.clone());
                    }
                    None => {
                        // Only possible for handoffs written by a
                        // pre-advertise-address coordinator; dials to this
                        // owner fail closed until it re-registers.
                        tracing::warn!(
                            router = %router_name,
                            partition = handoff.partition,
                            new_owner = %handoff.new_owner,
                            "handoff carries no advertise address"
                        );
                    }
                }

                // Pre-update the routing table before draining so that any
                // new request arriving mid-drain routes to the new owner
                // rather than to the old owner (which has already
                // released). The reconcile pass converges the table
                // against the assignment keys each tick and re-sets the
                // same value idempotently.
                table
                    .write()
                    .await
                    .insert(handoff.partition, handoff.new_owner.clone());

                tracing::info!(
                    router = %router_name,
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    "updated routing table and draining stash to new owner"
                );
                lanes.request(
                    Arc::clone(handler),
                    router_name.to_string(),
                    handoff.partition,
                    handoff.new_owner.clone(),
                );
            }
        }
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::sync::mpsc;

    /// A drain that parks until its token is cancelled, reporting when it
    /// starts and stops — enough to pin the lane contract.
    struct ParkingDrainHandler {
        events: mpsc::UnboundedSender<String>,
    }

    #[async_trait]
    impl StashHandler for ParkingDrainHandler {
        async fn begin_stash(&self, _partition: u32, _new_owner: &str) -> Result<()> {
            Ok(())
        }

        async fn drain_stash(
            &self,
            _partition: u32,
            target: &str,
            cancel: CancellationToken,
        ) -> Result<()> {
            drop(self.events.send(format!("start:{target}")));
            cancel.cancelled().await;
            drop(self.events.send(format!("stop:{target}")));
            Ok(())
        }
    }

    fn parking_lanes() -> (
        DrainLanes,
        Arc<dyn StashHandler>,
        mpsc::UnboundedReceiver<String>,
    ) {
        let (tx, rx) = mpsc::unbounded_channel();
        let lanes = DrainLanes::new(CancellationToken::new());
        let handler: Arc<dyn StashHandler> = Arc::new(ParkingDrainHandler { events: tx });
        (lanes, handler, rx)
    }

    /// Two drains for one partition must never overlap: interleaved
    /// batches toward different targets would break per-key ordering at
    /// the leader. A new request cancels the old drain and starts only
    /// after it has fully stopped.
    #[tokio::test]
    async fn a_new_drain_supersedes_and_never_overlaps_the_old() {
        let (lanes, handler, mut rx) = parking_lanes();

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());
        assert_eq!(rx.recv().await.unwrap(), "start:a");

        lanes.request(handler, "r".into(), 0, "b".into());
        assert_eq!(rx.recv().await.unwrap(), "stop:a");
        assert_eq!(rx.recv().await.unwrap(), "start:b");
    }

    /// One partition's stalled drain must not delay another partition's —
    /// the lanes exist precisely so cross-partition work is independent.
    #[tokio::test]
    async fn drains_for_different_partitions_run_concurrently() {
        let (lanes, handler, mut rx) = parking_lanes();

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());
        assert_eq!(rx.recv().await.unwrap(), "start:a");

        lanes.request(handler, "r".into(), 1, "b".into());
        assert_eq!(rx.recv().await.unwrap(), "start:b");
    }

    /// A request toward the target already being drained must not restart
    /// the drain: the running loop covers all arrivals — including the
    /// routine post-`Complete` cleanup deletion that drains back to the
    /// same owner the table just flipped to — and restarting it would
    /// only churn the same backlog.
    #[tokio::test]
    async fn a_same_target_request_does_not_supersede_the_running_drain() {
        let (lanes, handler, mut rx) = parking_lanes();

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());
        assert_eq!(rx.recv().await.unwrap(), "start:a");

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());

        // The first drain was neither stopped nor restarted: the next
        // events are its supersession by a different target — with no
        // duplicate "a" drain in between.
        lanes.request(handler, "r".into(), 0, "b".into());
        assert_eq!(rx.recv().await.unwrap(), "stop:a");
        assert_eq!(rx.recv().await.unwrap(), "start:b");
    }

    /// Teardown must JOIN drains, not merely signal them: `shutdown`
    /// returns only after every lane task has observed cancellation and
    /// exited, so the caller can revoke the router's lease knowing no
    /// forward happens after it. Signalling without joining would leave
    /// detached drains forwarding for a deregistered router.
    #[tokio::test]
    async fn shutdown_joins_running_drains_before_returning() {
        let (lanes, handler, mut rx) = parking_lanes();

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());
        lanes.request(handler, "r".into(), 1, "b".into());
        let starts = [rx.recv().await.unwrap(), rx.recv().await.unwrap()];
        assert!(starts.contains(&"start:a".to_string()));
        assert!(starts.contains(&"start:b".to_string()));

        lanes.shutdown().await;

        // Both drains exited before shutdown returned — their stop
        // events must already be in the channel, no further waiting.
        let mut stops = [rx.try_recv().unwrap(), rx.try_recv().unwrap()];
        stops.sort();
        assert_eq!(stops, ["stop:a".to_string(), "stop:b".to_string()]);
    }

    /// Observing a non-terminal handoff phase pauses the lane: the
    /// running drain is cancelled with no successor, so nothing forwards
    /// while the partition re-enters its stash window. Only the next
    /// `Complete`'s request may start a fresh drain, toward whatever
    /// owner it names.
    #[tokio::test]
    async fn a_pause_stops_the_drain_without_starting_a_successor() {
        let (lanes, handler, mut rx) = parking_lanes();

        lanes.request(Arc::clone(&handler), "r".into(), 0, "a".into());
        assert_eq!(rx.recv().await.unwrap(), "start:a");

        lanes.pause(0);
        assert_eq!(rx.recv().await.unwrap(), "stop:a");
        assert!(
            rx.try_recv().is_err(),
            "pause must not start a successor drain"
        );

        // The next Complete re-requests; the paused lane is superseded.
        lanes.request(handler, "r".into(), 0, "b".into());
        assert_eq!(rx.recv().await.unwrap(), "start:b");
    }
}
