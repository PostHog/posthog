use std::fmt;
use std::str::FromStr;

use envconfig::Envconfig;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::coordinator::REVOKE_TIMEOUT as COORDINATOR_REVOKE_TIMEOUT;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReplicaDiscoveryMode {
    /// DNS mode: static channels to ClusterIP URL.
    Dns,
    /// K8s mode: EndpointSlice watcher with client-side p2c balancing.
    K8s,
}

impl fmt::Display for ReplicaDiscoveryMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ReplicaDiscoveryMode::Dns => write!(f, "dns"),
            ReplicaDiscoveryMode::K8s => write!(f, "k8s"),
        }
    }
}

impl FromStr for ReplicaDiscoveryMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "dns" => Ok(ReplicaDiscoveryMode::Dns),
            "k8s" => Ok(ReplicaDiscoveryMode::K8s),
            other => Err(format!(
                "unknown replica discovery mode '{other}', expected 'dns' or 'k8s'"
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RouterMode {
    /// Replica-only mode: all requests go to personhog-replica.
    Replica,
    /// Leader mode: person writes and strong reads go to leader pods
    /// via etcd-coordinated partition routing. Everything else goes to replica.
    Leader,
}

impl fmt::Display for RouterMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RouterMode::Replica => write!(f, "replica"),
            RouterMode::Leader => write!(f, "leader"),
        }
    }
}

impl FromStr for RouterMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "replica" => Ok(RouterMode::Replica),
            "leader" => Ok(RouterMode::Leader),
            other => Err(format!(
                "unknown router mode '{other}', expected 'replica' or 'leader'"
            )),
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50052")]
    pub grpc_address: SocketAddr,

    /// Router mode: "replica" (default) or "leader"
    #[envconfig(default = "replica")]
    pub router_mode: RouterMode,

    /// URL of the personhog-replica backend (DNS mode only)
    #[envconfig(default = "http://127.0.0.1:50051")]
    pub replica_url: String,

    /// Number of gRPC channels to open to the replica service (DNS mode only).
    /// Multiple channels distribute requests across K8s service endpoints.
    #[envconfig(default = "4")]
    pub replica_channels: usize,

    /// Discovery mode for replica endpoints: "dns" (default)
    /// or "k8s" (EndpointSlice watcher with client-side balancing)
    #[envconfig(default = "dns")]
    pub replica_discovery_mode: ReplicaDiscoveryMode,

    /// Kubernetes service name to watch for replica endpoints (k8s mode only)
    #[envconfig(default = "personhog-replica")]
    pub replica_service_name: String,

    /// Kubernetes namespace for replica endpoint discovery (k8s mode only).
    /// If empty, reads from the service account mount.
    #[envconfig(default = "")]
    pub replica_service_namespace: String,

    /// gRPC port on replica pods (k8s mode only)
    #[envconfig(default = "50051")]
    pub replica_port: u16,

    /// Timeout for backend requests in milliseconds
    #[envconfig(default = "5000")]
    pub backend_timeout_ms: u64,

    /// Connect timeout for backend connections in milliseconds (k8s mode only)
    #[envconfig(default = "2000")]
    pub backend_connect_timeout_ms: u64,

    #[envconfig(default = "9101")]
    pub metrics_port: u16,

    /// Maximum number of retry attempts for transient backend errors (0 = no retries)
    #[envconfig(default = "3")]
    pub max_retries: u32,

    /// Initial backoff delay in milliseconds before the first retry
    #[envconfig(default = "25")]
    pub initial_backoff_ms: u64,

    /// Maximum backoff delay in milliseconds (caps exponential growth)
    #[envconfig(default = "500")]
    pub max_backoff_ms: u64,

    /// Interval between HTTP/2 keepalive pings sent by the gRPC server (0 = disabled)
    #[envconfig(default = "30")]
    pub grpc_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack before considering the connection dead
    #[envconfig(default = "10")]
    pub grpc_keepalive_timeout_secs: u64,

    /// Interval between HTTP/2 keepalive pings sent to the replica backend (0 = disabled)
    #[envconfig(default = "30")]
    pub backend_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack from the replica backend
    #[envconfig(default = "10")]
    pub backend_keepalive_timeout_secs: u64,

    /// Maximum request body size the proxy will collect before forwarding,
    /// in bytes. Oversized requests are rejected with RESOURCE_EXHAUSTED.
    /// Responses stream through unbounded (see `response_size_warn_bytes`).
    #[envconfig(default = "134217728")]
    pub grpc_max_recv_message_size: usize,

    /// Log a warning when a gRPC response exceeds this size in bytes.
    /// Set to 0 to disable. Default: 10 MiB.
    #[envconfig(default = "10485760")]
    pub response_size_warn_bytes: usize,

    // ── etcd coordination (leader mode only) ─────────────────────
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    /// Router name for etcd registration (typically set from K8s downward API)
    #[envconfig(default = "router-0")]
    pub pod_name: String,

    /// Registration lease TTL. A crashed router stays in every freeze
    /// quorum until this expires, stalling any handoff frozen in that
    /// window — keep it short. Graceful exits deregister immediately.
    #[envconfig(default = "10")]
    pub lease_ttl: i64,

    #[envconfig(default = "3")]
    pub heartbeat_interval_secs: u64,

    /// Fail the coordination run when the handoff watch loop makes no
    /// progress for this long, so the router deregisters and restarts as
    /// a healthy participant instead of wedging freeze quorums while its
    /// lease stays alive. `0` disables the watchdog.
    #[envconfig(default = "60")]
    pub router_participant_stall_secs: u64,

    /// How often the routing table re-derives stash, table, and drain
    /// state from a fresh etcd snapshot, independent of watch events.
    #[envconfig(default = "5")]
    pub router_reconcile_secs: u64,

    /// How many consecutive reconcile-pass failures the routing table
    /// tolerates before failing the run. A failed pass only means the
    /// router stays as stale as the previous tick — the watch-driven
    /// steady state — so brief etcd blips must not be fatal; sustained
    /// outage is already handled by lease self-fencing. The budget
    /// bounds the partial-failure mode where snapshot reads fail while
    /// the lease stays healthy, which would otherwise silently degrade
    /// the liveness the reconcile provides.
    #[envconfig(default = "12")]
    pub router_reconcile_failure_budget: u32,

    /// How many consecutive coordination-attempt failures the routing
    /// table's run supervisor tolerates (rebuilding coordination in
    /// place while the data plane keeps serving) before giving up and
    /// letting the process restart. A healthy attempt resets the count.
    #[envconfig(default = "10")]
    pub router_run_retry_budget: u32,

    /// Base backoff in milliseconds between coordination attempts;
    /// doubles per consecutive failure up to a fixed cap.
    #[envconfig(default = "500")]
    pub router_run_retry_backoff_ms: u64,

    /// How long a handoff may sit in Warming before the coordinator
    /// cancels it by replacement. Warming replays the partition's
    /// changelog, so its budget is far above the general handoff
    /// deadline; `0` disables it.
    #[envconfig(default = "1800")]
    pub coordinator_warming_deadline_secs: u64,

    /// Maximum number of stashed write requests held per partition while
    /// a handoff is in progress. Excess requests return UNAVAILABLE and
    /// rely on caller-side retries.
    #[envconfig(default = "5000")]
    pub stash_max_messages_per_partition: usize,

    /// Maximum total payload bytes held in the stash per partition. Bounds
    /// memory pressure independent of message count, which matters when
    /// payload sizes vary widely (typical for person properties). Default
    /// is 50 MiB.
    #[envconfig(default = "52428800")]
    pub stash_max_bytes_per_partition: usize,

    /// Per-request deadline for stashed writes, in milliseconds. When
    /// drain dequeues a request whose `enqueued_at` is older than this,
    /// it returns `UNAVAILABLE` to the original caller without
    /// forwarding to the leader. This bounds individual request
    /// latency under sustained drain load and gives clients a
    /// definitive retryable error instead of an ambiguous gRPC timeout.
    /// Should be smaller than typical client gRPC timeouts (often
    /// 30+ seconds). Default 10 seconds.
    #[envconfig(default = "10000")]
    pub stash_max_wait_ms: u64,

    /// Maximum number of stashed requests to forward concurrently
    /// during a drain, grouped by `(team_id, person_id)`. Within each
    /// key the requests are forwarded sequentially to preserve per-key
    /// ordering at the leader; across keys the drain fans out to
    /// shrink wall-clock drain duration. Set to 1 to force fully
    /// sequential drain.
    #[envconfig(default = "32")]
    pub stash_drain_concurrency: usize,

    // ── coordinator (leader election among router-leader pods) ───
    /// Whether this leader-mode router campaigns for the coordinator
    /// election. Disabled, the router still registers in the routing
    /// table, serves traffic, and acks freezes — it just never
    /// coordinates. Production leaves this on everywhere; the test
    /// harness disables it on its traffic router so chaos targeting
    /// "the coordinator" can never land on the traffic path.
    #[envconfig(default = "true")]
    pub coordinator_enabled: bool,

    /// Lease TTL for the coordinator leader election. A crashed leader
    /// blocks every handoff until this expires and a survivor takes
    /// over. Survivors watch the leader key, so a succession follows the
    /// key's deletion rather than a retry tick, and this TTL is what
    /// bounds an ordinary outage. It also caps the wait a survivor paced
    /// by repeated bad endings can add on top, so the worst case is
    /// roughly twice this rather than unbounded in the pace. Graceful
    /// exits revoke the lease and fail over immediately.
    #[envconfig(default = "5")]
    pub coordinator_lease_ttl: i64,

    /// Keepalive interval for the coordinator lease. Several attempts
    /// must fit inside the TTL; a keepalive that reports the lease gone
    /// makes the leader abdicate.
    #[envconfig(default = "1")]
    pub coordinator_keepalive_secs: u64,

    /// How long a standby candidate waits on its leader-key watch before
    /// re-reading the key, and the base of the growing retry a candidate
    /// backs off on when it cannot read the election at all. Bounds how
    /// long a watch that stalls without erroring can hide an opening.
    #[envconfig(default = "5")]
    pub coordinator_standby_poll_secs: u64,

    /// Base wait before campaigning again after a leadership term ended
    /// badly. Doubles per consecutive bad ending, capped at the
    /// coordinator lease TTL so a paced candidate is never slower to take
    /// an open election than to wait out a crashed leader's lease.
    #[envconfig(default = "500")]
    pub coordinator_run_retry_backoff_ms: u64,

    /// How long without a bad ending before that pace starts over.
    /// Without it a bad spell leaves every candidate at the cap long
    /// after etcd recovered.
    #[envconfig(default = "300")]
    pub coordinator_backoff_decay_secs: u64,

    /// Debounce interval (ms) for batching pod events before rebalancing
    #[envconfig(default = "1000")]
    pub coordinator_rebalance_debounce_ms: u64,

    /// How often the coordinator re-evaluates in-flight handoffs
    /// regardless of watch events — the liveness backstop for state
    /// changes that fire no event (e.g. router departures) and for
    /// events missed before a watch attaches.
    #[envconfig(default = "5")]
    pub coordinator_reconcile_secs: u64,

    /// How long a handoff may run before the coordinator cancels it so a
    /// later plan can retry. The backstop for a handoff that can never
    /// satisfy its quorum: nothing else removes one whose new owner is
    /// alive, and an in-flight handoff pins its partition, so without
    /// this it waits for a human. Sized well above healthy handoffs,
    /// which complete in seconds. Zero disables the backstop entirely —
    /// a wedged handoff then really does wait for a human.
    #[envconfig(default = "120")]
    pub coordinator_handoff_deadline_secs: u64,

    // ── K8s awareness (leader mode only) ────────────────────────
    /// Enable K8s-aware departure classification for smarter rebalancing.
    /// When disabled, falls back to lease-based behavior.
    #[envconfig(default = "false")]
    pub k8s_awareness_enabled: bool,

    /// Kubernetes namespace to watch. If empty, auto-reads from the
    /// service account mount at /var/run/secrets/kubernetes.io/serviceaccount/namespace.
    #[envconfig(default = "")]
    pub k8s_namespace: String,

    /// How many freeze acks the routing table may put in one etcd
    /// transaction. Mirrors the server's `--max-txn-ops`: a batch above
    /// it is refused outright, a smaller one only costs a round trip.
    /// Defaults to etcd's own default.
    #[envconfig(default = "128")]
    pub etcd_max_txn_ops: usize,

    // ── Shutdown budgets ─────────────────────────────────────────
    // The lifecycle manager's per-phase windows. Configurable because
    // the timings validated against them — the keepalive interval, the
    // lease TTL — are, and a fixed ceiling under adjustable terms is a
    // configuration an operator cannot resolve. Their relations are
    // checked by `validate_shutdown_budgets` at startup.
    /// The gRPC server's phase-0 budget: it drains first while the
    /// coordination components keep serving its in-flight requests.
    #[envconfig(default = "15")]
    pub grpc_graceful_shutdown_secs: u64,

    /// The phase-1 coordination components' shared budget (routing
    /// table, coordinator, discovery, in parallel).
    #[envconfig(default = "5")]
    pub phase1_graceful_shutdown_secs: u64,

    /// How long the lifecycle manager lets the coordinator component
    /// exit gracefully, within phase 1.
    #[envconfig(default = "5")]
    pub coordinator_graceful_shutdown_secs: u64,

    /// Both phases plus slack. Must stay under the chart's termination
    /// grace period so shutdown concludes process-side.
    #[envconfig(default = "25")]
    pub global_shutdown_timeout_secs: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The envconfig defaults with no environment behind them, so an
    /// ambient `COORDINATOR_*` or `LEASE_TTL` in a developer's shell
    /// cannot change what these tests assert.
    fn default_config() -> Config {
        Config::init_from_hashmap(&std::collections::HashMap::new()).expect("defaults")
    }

    fn leased(lease_ttl: i64, heartbeat_interval_secs: u64) -> Config {
        let mut config = default_config();
        config.lease_ttl = lease_ttl;
        config.heartbeat_interval_secs = heartbeat_interval_secs;
        config
    }

    /// `leased`, in leader mode — where the coordinator can exist and
    /// its knobs are therefore live.
    fn leader_leased(lease_ttl: i64, heartbeat_interval_secs: u64) -> Config {
        let mut config = leased(lease_ttl, heartbeat_interval_secs);
        config.router_mode = RouterMode::Leader;
        config
    }

    /// The keepalive uses the heartbeat as the timeout for each renewal
    /// round, so a zero one times out instantly and the router fences
    /// itself against healthy etcd for as long as it runs — taking every
    /// handoff that needs its freeze ack with it.
    #[test]
    fn a_zero_heartbeat_is_refused() {
        assert!(leader_leased(10, 0).validate_lease_timescales().is_err());
        // A replica router registers no lease, so the same pair is dead
        // config there and must not refuse startup.
        assert!(leased(10, 0).validate_lease_timescales().is_ok());
    }

    /// A heartbeat past the renewal margin exhausts the lease by sleeping,
    /// with the same result.
    #[test]
    fn a_heartbeat_the_lease_cannot_fit_is_refused() {
        assert!(leader_leased(10, 30).validate_lease_timescales().is_err());
    }

    #[test]
    fn a_heartbeat_well_inside_the_margin_is_accepted() {
        assert!(leader_leased(10, 2).validate_lease_timescales().is_ok());
    }

    /// The coordinator election lease runs the same keepalive on its own
    /// pair of knobs; a misconfigured pair reproduces the same
    /// self-fencing loop, stalling every handoff behind the coordinator.
    #[test]
    fn a_coordinator_keepalive_the_lease_cannot_fit_is_refused() {
        let mut config = leader_leased(10, 2);
        config.coordinator_lease_ttl = 10;
        config.coordinator_keepalive_secs = 30;
        assert!(config.validate_lease_timescales().is_err());
        config.coordinator_keepalive_secs = 0;
        assert!(config.validate_lease_timescales().is_err());
        config.coordinator_keepalive_secs = 2;
        assert!(config.validate_lease_timescales().is_ok());

        // A coordinator that cannot exist never reads these knobs, so
        // they must not be able to refuse startup — whether it is
        // disabled by flag or by the router running in replica mode.
        config.coordinator_keepalive_secs = 0;
        config.coordinator_enabled = false;
        assert!(config.validate_lease_timescales().is_ok());
        config.coordinator_enabled = true;
        config.router_mode = RouterMode::Replica;
        assert!(config.validate_lease_timescales().is_ok());
    }

    /// The router now sets every coordinator knob explicitly, so its
    /// envconfig defaults — not `CoordinatorConfig::default()` — are what
    /// production runs on. The reasoning for each number still lives on
    /// the protocol's `Default` impl, which nothing else would notice
    /// drifting from these. Every shared knob is pinned; a partial list
    /// would leave the drift it exists to catch silent for the rest.
    #[test]
    fn the_router_defaults_match_the_protocols_own() {
        let config = default_config();
        let protocol = personhog_coordination::coordinator::CoordinatorConfig::default();

        assert_eq!(config.coordinator_lease_ttl, protocol.leader_lease_ttl);
        assert_eq!(
            config.coordinator_keepalive_interval(),
            protocol.keepalive_interval
        );
        assert_eq!(
            config.coordinator_standby_poll_interval(),
            protocol.standby_poll_interval
        );
        assert_eq!(
            config.coordinator_run_retry_backoff(),
            protocol.run_retry_backoff
        );
        assert_eq!(
            config.coordinator_backoff_decay_window(),
            protocol.backoff_decay_window
        );
        assert_eq!(
            config.coordinator_rebalance_debounce_interval(),
            protocol.rebalance_debounce_interval
        );
        assert_eq!(
            config.coordinator_reconcile_interval(),
            protocol.reconcile_interval
        );
        assert_eq!(
            config.coordinator_handoff_deadline(),
            protocol.handoff_deadline
        );
        assert_eq!(
            config.coordinator_warming_deadline(),
            protocol.warming_deadline
        );
    }

    /// A zero reconcile interval panics the interval it drives, and the
    /// panic retries through the whole run budget and then the process —
    /// forever. Leader-mode only: a replica router never reads these.
    #[test]
    fn a_zero_router_pace_is_refused_in_leader_mode() {
        let mut config = leased(10, 2);
        config.router_mode = RouterMode::Leader;
        config.router_reconcile_secs = 0;
        assert!(config.validate_lease_timescales().is_err());

        config.router_reconcile_secs = 5;
        config.router_run_retry_backoff_ms = 0;
        assert!(config.validate_lease_timescales().is_err());

        config.router_run_retry_backoff_ms = 500;
        assert!(config.validate_lease_timescales().is_ok());

        // Dead config on a replica router must not refuse startup.
        config.router_reconcile_secs = 0;
        config.router_mode = RouterMode::Replica;
        assert!(config.validate_lease_timescales().is_ok());
    }

    /// Each of the coordinator's three paced knobs is either a wait or
    /// the window a wait decays over, so a zero turns the loop it paces
    /// into one that runs as fast as etcd will answer — a standby reading
    /// the leader key and creating a watch back to back, or a candidate
    /// campaigning with a lease grant, a transaction and a revoke every
    /// turn. None of them has a floor at the point of use.
    #[test]
    fn a_zero_coordinator_pace_is_refused() {
        for zero in [
            |c: &mut Config| c.coordinator_standby_poll_secs = 0,
            |c: &mut Config| c.coordinator_run_retry_backoff_ms = 0,
            |c: &mut Config| c.coordinator_backoff_decay_secs = 0,
        ] {
            let mut config = leader_leased(10, 2);
            zero(&mut config);
            assert!(
                config.validate_lease_timescales().is_err(),
                "a zero pace must refuse startup"
            );
        }
    }

    /// The phase budgets have to fit the window supervising them. This
    /// held at compile time while they were constants; as configuration
    /// it is a startup refusal, and the defaults must still satisfy it.
    #[test]
    fn shutdown_phases_that_overrun_the_global_window_are_refused() {
        let config = default_config();
        assert!(
            config.validate_shutdown_budgets().is_ok(),
            "the defaults must satisfy their own relations"
        );

        let mut overrun = default_config();
        overrun.global_shutdown_timeout_secs =
            overrun.grpc_graceful_shutdown_secs + overrun.phase1_graceful_shutdown_secs;
        assert!(
            overrun.validate_shutdown_budgets().is_err(),
            "phases summing to the whole global window leave the manager no slack"
        );

        let mut oversized_coordinator = default_config();
        oversized_coordinator.coordinator_graceful_shutdown_secs =
            oversized_coordinator.phase1_graceful_shutdown_secs + 1;
        assert!(
            oversized_coordinator.validate_shutdown_budgets().is_err(),
            "the coordinator cannot outlast the phase it runs in"
        );
    }

    /// The coordinator's graceful exit joins its keepalive and then
    /// revokes the election lease, and the lifecycle manager abandons the
    /// component when its budget runs out. The keepalive join is not
    /// raced against cancellation, so a keepalive interval close to the
    /// renewal margin can spend the budget before the revoke is even
    /// reached — leaving the successor to wait out the lease TTL that the
    /// revoke exists to spare it.
    #[test]
    fn a_coordinator_teardown_that_cannot_fit_its_shutdown_budget_is_refused() {
        let mut config = leader_leased(10, 2);
        config.coordinator_lease_ttl = 5;
        // Inside the renewal margin (3.33s), so the keepalive pair is
        // valid — but a 3s join plus the 2s revoke reaches the whole 5s
        // budget, which is the case a check on the revoke alone misses.
        config.coordinator_keepalive_secs = 3;
        assert!(config.validate_lease_timescales().is_err());

        config.coordinator_keepalive_secs = 1;
        assert!(
            config.validate_lease_timescales().is_ok(),
            "a teardown that fits must be accepted"
        );
    }

    // ── ReplicaDiscoveryMode ──────────────────────────────────────────────────

    #[test]
    fn replica_discovery_mode_from_str_valid_variants() {
        let cases = [
            ("dns", ReplicaDiscoveryMode::Dns),
            ("k8s", ReplicaDiscoveryMode::K8s),
            // case-insensitive
            ("DNS", ReplicaDiscoveryMode::Dns),
            ("K8S", ReplicaDiscoveryMode::K8s),
            ("Dns", ReplicaDiscoveryMode::Dns),
        ];
        for (input, expected) in cases {
            let result: Result<ReplicaDiscoveryMode, _> = input.parse();
            assert_eq!(
                result.unwrap(),
                expected,
                "'{input}' should parse to {expected:?}",
            );
        }
    }

    #[test]
    fn replica_discovery_mode_from_str_invalid_returns_error() {
        let invalid_inputs = ["endpoint", "", "replica", "kubernetes", "k8s1"];
        for input in invalid_inputs {
            let result: Result<ReplicaDiscoveryMode, _> = input.parse();
            assert!(result.is_err(), "'{input}' should be an error");
            let msg = result.unwrap_err();
            assert!(
                msg.contains(input) || msg.contains("expected"),
                "error message should mention the bad input or expected values, got: {msg}",
            );
        }
    }

    #[test]
    fn replica_discovery_mode_display() {
        assert_eq!(ReplicaDiscoveryMode::Dns.to_string(), "dns");
        assert_eq!(ReplicaDiscoveryMode::K8s.to_string(), "k8s");
    }

    #[test]
    fn replica_discovery_mode_roundtrips() {
        for mode in [ReplicaDiscoveryMode::Dns, ReplicaDiscoveryMode::K8s] {
            let s = mode.to_string();
            let parsed: ReplicaDiscoveryMode = s.parse().unwrap();
            assert_eq!(
                parsed, mode,
                "Display → FromStr roundtrip failed for {mode:?}"
            );
        }
    }

    // ── RouterMode ───────────────────────────────────────────────────────────

    #[test]
    fn router_mode_from_str_valid_variants() {
        let cases = [
            ("replica", RouterMode::Replica),
            ("leader", RouterMode::Leader),
            ("REPLICA", RouterMode::Replica),
            ("LEADER", RouterMode::Leader),
        ];
        for (input, expected) in cases {
            let result: Result<RouterMode, _> = input.parse();
            assert_eq!(
                result.unwrap(),
                expected,
                "'{input}' should parse to {expected:?}"
            );
        }
    }

    #[test]
    fn router_mode_from_str_invalid_returns_error() {
        let invalid_inputs = ["dns", "", "follow", "primary"];
        for input in invalid_inputs {
            let result: Result<RouterMode, _> = input.parse();
            assert!(result.is_err(), "'{input}' should be an error");
        }
    }

    #[test]
    fn router_mode_display() {
        assert_eq!(RouterMode::Replica.to_string(), "replica");
        assert_eq!(RouterMode::Leader.to_string(), "leader");
    }

    #[test]
    fn router_mode_roundtrips() {
        for mode in [RouterMode::Replica, RouterMode::Leader] {
            let s = mode.to_string();
            let parsed: RouterMode = s.parse().unwrap();
            assert_eq!(
                parsed, mode,
                "Display → FromStr roundtrip failed for {mode:?}"
            );
        }
    }
}

impl Config {
    pub fn backend_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_timeout_ms)
    }

    pub fn backend_connect_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_connect_timeout_ms)
    }

    pub fn grpc_keepalive_interval(&self) -> Option<Duration> {
        if self.grpc_keepalive_interval_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_keepalive_interval_secs))
        }
    }

    pub fn grpc_keepalive_timeout(&self) -> Option<Duration> {
        if self.grpc_keepalive_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_keepalive_timeout_secs))
        }
    }

    pub fn backend_keepalive_interval(&self) -> Option<Duration> {
        if self.backend_keepalive_interval_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.backend_keepalive_interval_secs))
        }
    }

    pub fn backend_keepalive_timeout(&self) -> Option<Duration> {
        if self.backend_keepalive_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.backend_keepalive_timeout_secs))
        }
    }

    pub fn retry_config(&self) -> RetryConfig {
        RetryConfig {
            max_retries: self.max_retries,
            initial_backoff_ms: self.initial_backoff_ms,
            max_backoff_ms: self.max_backoff_ms,
        }
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    pub fn heartbeat_interval(&self) -> Duration {
        Duration::from_secs(self.heartbeat_interval_secs)
    }

    /// Refuse a heartbeat the lease cannot survive: a zero interval
    /// times out every renewal instantly and a slow one sleeps through
    /// the margin, so either exhausts the lease against healthy etcd
    /// and the participant keeps leaving mid-handoff. The coordinator
    /// election lease runs the same keepalive with its own knobs, so it
    /// gets the same refusal.
    pub fn validate_lease_timescales(&self) -> Result<(), String> {
        // Everything here is the routing table's, and the routing table
        // only exists in leader mode — a replica router registers no
        // lease and reads none of these, and refusing startup over dead
        // config would turn it into an outage.
        if self.router_mode == RouterMode::Leader {
            Self::validate_keepalive_pair(
                "HEARTBEAT_INTERVAL_SECS",
                self.heartbeat_interval(),
                "LEASE_TTL",
                self.lease_ttl,
            )?;
            // The reconcile interval's zero panics
            // `tokio::time::interval_at`, which ends the run, which
            // retries the panic through the whole budget and then
            // restarts the process — forever.
            for (name, value) in [
                ("ROUTER_RECONCILE_SECS", self.router_reconcile_interval()),
                (
                    "ROUTER_RUN_RETRY_BACKOFF_MS",
                    Duration::from_millis(self.router_run_retry_backoff_ms),
                ),
                (
                    "STASH_MAX_WAIT_MS",
                    Duration::from_millis(self.stash_max_wait_ms),
                ),
            ] {
                if value.is_zero() {
                    return Err(format!(
                        "{name} must be greater than zero: a zero either panics the \
                         interval it drives, turns its retries into a hot loop, or \
                         expires every stashed request the moment it arrives"
                    ));
                }
            }
        }
        // Only where a coordinator can actually run — which takes both
        // the flag and leader mode, since replica routers never register
        // one: refusing startup over knobs a coordinator that cannot
        // exist never reads would turn dead config into an outage.
        if !self.coordinator_enabled || self.router_mode != RouterMode::Leader {
            return Ok(());
        }
        Self::validate_keepalive_pair(
            "COORDINATOR_KEEPALIVE_SECS",
            self.coordinator_keepalive_interval(),
            "COORDINATOR_LEASE_TTL",
            self.coordinator_lease_ttl,
        )?;
        for (name, value) in [
            (
                "COORDINATOR_STANDBY_POLL_SECS",
                self.coordinator_standby_poll_interval(),
            ),
            (
                "COORDINATOR_RUN_RETRY_BACKOFF_MS",
                self.coordinator_run_retry_backoff(),
            ),
            (
                "COORDINATOR_BACKOFF_DECAY_SECS",
                self.coordinator_backoff_decay_window(),
            ),
            // Not a pace, but the same refusal for a worse failure: a
            // zero period panics `tokio::time::interval`, and the panic
            // ends the term, which retries the panic — a coordinator
            // that never coordinates and never stops campaigning.
            (
                "COORDINATOR_RECONCILE_SECS",
                self.coordinator_reconcile_interval(),
            ),
        ] {
            if value.is_zero() {
                return Err(format!(
                    "{name} must be greater than zero: every one of these paces a loop or \
                     is the window a pace decays over, and a zero either hot-loops against \
                     etcd or panics the interval it drives"
                ));
            }
        }
        // The teardown's only unraced await is the keepalive join —
        // bounded by one renewal round, which the pair check above
        // keeps under the margin — followed by the bounded revoke.
        // Checked here because both halves of the relation are known.
        let keepalive_bound = self.coordinator_keepalive_interval();
        let teardown = keepalive_bound + COORDINATOR_REVOKE_TIMEOUT;
        let budget = self.coordinator_graceful_shutdown();
        if teardown >= budget {
            return Err(format!(
                "the coordinator's teardown ({teardown:?} = a {keepalive_bound:?} keepalive \
                 join plus a {COORDINATOR_REVOKE_TIMEOUT:?} lease revoke) must finish inside \
                 its {budget:?} graceful shutdown budget; lower COORDINATOR_KEEPALIVE_SECS \
                 or raise COORDINATOR_GRACEFUL_SHUTDOWN_SECS"
            ));
        }
        Ok(())
    }

    /// The lifecycle manager's phases must fit the window that
    /// supervises them, or its own deadline fires before theirs.
    ///
    /// Checked at startup rather than compile time because the budgets
    /// are configuration: a fixed ceiling under adjustable phase
    /// timings is a configuration an operator cannot resolve.
    pub fn validate_shutdown_budgets(&self) -> Result<(), String> {
        let phases = self.grpc_graceful_shutdown() + self.phase1_graceful_shutdown();
        let global = self.global_shutdown_timeout();
        if phases >= global {
            return Err(format!(
                "the shutdown phases ({phases:?} = a {:?} gRPC drain plus a {:?} coordination \
                 phase) must finish inside the {global:?} global window with room to spare; \
                 raise GLOBAL_SHUTDOWN_TIMEOUT_SECS or lower the phases",
                self.grpc_graceful_shutdown(),
                self.phase1_graceful_shutdown(),
            ));
        }
        let coordinator = self.coordinator_graceful_shutdown();
        let phase1 = self.phase1_graceful_shutdown();
        if coordinator > phase1 {
            return Err(format!(
                "the coordinator's {coordinator:?} budget must fit the {phase1:?} phase it \
                 runs in; lower COORDINATOR_GRACEFUL_SHUTDOWN_SECS or raise \
                 PHASE1_GRACEFUL_SHUTDOWN_SECS"
            ));
        }
        Ok(())
    }

    pub fn grpc_graceful_shutdown(&self) -> Duration {
        Duration::from_secs(self.grpc_graceful_shutdown_secs)
    }

    pub fn phase1_graceful_shutdown(&self) -> Duration {
        Duration::from_secs(self.phase1_graceful_shutdown_secs)
    }

    pub fn coordinator_graceful_shutdown(&self) -> Duration {
        Duration::from_secs(self.coordinator_graceful_shutdown_secs)
    }

    pub fn global_shutdown_timeout(&self) -> Duration {
        Duration::from_secs(self.global_shutdown_timeout_secs)
    }

    fn validate_keepalive_pair(
        interval_name: &str,
        interval: Duration,
        ttl_name: &str,
        ttl: i64,
    ) -> Result<(), String> {
        let margin = AuthorityClock::renewal_margin(ttl);
        if interval.is_zero() {
            return Err(format!(
                "{interval_name} must be greater than zero: the keepalive uses it as the \
                 timeout for each renewal round, so a zero interval fences the holder \
                 against healthy etcd in a loop it cannot leave"
            ));
        }
        if interval >= margin {
            return Err(format!(
                "{interval_name} ({interval:?}) must be well under the keepalive renewal \
                 margin ({margin:?} = 2/3 of {ttl_name} {ttl}s): the sleep between renewals \
                 would exhaust the margin on its own, and the holder would fence itself \
                 against healthy etcd"
            ));
        }
        Ok(())
    }

    pub fn coordinator_keepalive_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_keepalive_secs)
    }

    pub fn coordinator_standby_poll_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_standby_poll_secs)
    }

    pub fn coordinator_run_retry_backoff(&self) -> Duration {
        Duration::from_millis(self.coordinator_run_retry_backoff_ms)
    }

    pub fn coordinator_backoff_decay_window(&self) -> Duration {
        Duration::from_secs(self.coordinator_backoff_decay_secs)
    }

    pub fn coordinator_rebalance_debounce_interval(&self) -> Duration {
        Duration::from_millis(self.coordinator_rebalance_debounce_ms)
    }

    pub fn coordinator_reconcile_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_reconcile_secs)
    }

    pub fn coordinator_handoff_deadline(&self) -> Duration {
        Duration::from_secs(self.coordinator_handoff_deadline_secs)
    }

    pub fn router_reconcile_interval(&self) -> Duration {
        Duration::from_secs(self.router_reconcile_secs)
    }

    pub fn coordinator_warming_deadline(&self) -> Duration {
        Duration::from_secs(self.coordinator_warming_deadline_secs)
    }

    pub fn participant_stall_threshold(&self) -> Option<Duration> {
        (self.router_participant_stall_secs > 0)
            .then(|| Duration::from_secs(self.router_participant_stall_secs))
    }

    pub fn stash_max_wait(&self) -> Duration {
        Duration::from_millis(self.stash_max_wait_ms)
    }

    /// Resolve the replica service namespace from config or the service account mount.
    pub fn resolve_replica_namespace(&self) -> Result<String, String> {
        if !self.replica_service_namespace.is_empty() {
            return Ok(self.replica_service_namespace.clone());
        }
        std::fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
            .map(|s| s.trim().to_string())
            .map_err(|e| {
                format!(
                    "replica_service_namespace not set and failed to read from service account: {e}"
                )
            })
    }

    /// Resolve the K8s namespace from config or the service account mount.
    pub fn resolve_k8s_namespace(&self) -> Result<String, String> {
        if !self.k8s_namespace.is_empty() {
            return Ok(self.k8s_namespace.clone());
        }
        std::fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
            .map(|s| s.trim().to_string())
            .map_err(|e| {
                format!("k8s_namespace not set and failed to read from service account: {e}")
            })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub initial_backoff_ms: u64,
    pub max_backoff_ms: u64,
}
