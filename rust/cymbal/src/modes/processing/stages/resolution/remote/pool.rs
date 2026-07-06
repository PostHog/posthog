use std::collections::HashMap;
use std::fmt;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use rand::{seq::SliceRandom, Rng};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::sync::{Mutex, Notify};
use tonic::transport::{Channel, Endpoint};
use tracing::{info, warn};

use super::config::RemoteResolutionConfig;
use super::dns::DnsResolver;
use super::mux::ResolveMux;
use super::subscription::{spawn_subscription, LoadCell, LoadSnapshot, SubscriptionHandle};
use crate::metric_consts::{
    REMOTE_RESOLUTION_ENDPOINTS_BY_STATE, REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT,
    REMOTE_RESOLUTION_POOL_SIZE,
};

const RESOLVE_MUX_QUEUE_CAPACITY: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EndpointPoolEmptyReason {
    NoEndpoints,
    NoFreshLoadSnapshots,
    AllEndpointsDraining,
    AllEndpointsEjected,
}

impl EndpointPoolEmptyReason {
    pub fn as_metric_tag(self) -> &'static str {
        match self {
            Self::NoEndpoints => "no_endpoints",
            Self::NoFreshLoadSnapshots => "no_fresh_load_snapshots",
            Self::AllEndpointsDraining => "all_endpoints_draining",
            Self::AllEndpointsEjected => "all_endpoints_ejected",
        }
    }
}

impl fmt::Display for EndpointPoolEmptyReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::NoEndpoints => "no DNS endpoints",
            Self::NoFreshLoadSnapshots => "no fresh load snapshots",
            Self::AllEndpointsDraining => "all endpoints draining",
            Self::AllEndpointsEjected => "all endpoints ejected after overload",
        })
    }
}

/// Errors returned by [`EndpointPool::select`] and [`EndpointPool::refresh`].
#[derive(Debug, Error)]
pub enum EndpointPoolError {
    #[error("remote resolution pool is empty ({0})")]
    Empty(EndpointPoolEmptyReason),
    #[error("dns resolution failed for {host}:{port}: {source}")]
    Dns {
        host: String,
        port: u16,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid endpoint uri {addr}: {source}")]
    InvalidEndpoint {
        addr: SocketAddr,
        #[source]
        source: tonic::transport::Error,
    },
}

struct EndpointState {
    channel: Channel,
    mux: ResolveMux,
    in_flight: Arc<AtomicUsize>,
    /// Pre-formatted address used as the `endpoint` metric label. Built once
    /// when the endpoint is added so the routing path clones an `Arc` instead
    /// of allocating a fresh `String` per selection (see `rust/CLAUDE.md`).
    endpoint_label: Arc<str>,
    // Endpoints that DNS no longer reports are marked draining. The mux is
    // closed so in-flight waiters reroute, and the endpoint is evicted once
    // local handles have observed the break and dropped.
    draining: bool,
    /// Latest server-reported load snapshot. Updated by the subscription task
    /// when one is attached; reads on the routing path are cheap.
    load: LoadCell,
    /// Deadline until which this endpoint is temporarily excluded after an
    /// overload outcome. This is local to this cymbal process.
    overload_ejected_until: Option<Instant>,
    /// Current adaptive ejection duration. Repeated overloads double this up to
    /// config.overload_ejection_max; a quiet window resets it to the initial duration.
    overload_ejection_cooldown: Duration,
    /// Last time this endpoint reported overload in this cymbal process.
    overload_last_seen: Option<Instant>,
    /// Background task subscribing to this endpoint's freshness/draining stream. `None`
    /// when subscriptions are disabled (test pools constructed via
    /// [`EndpointPool::from_addrs_without_subscriptions`]).
    subscription: Option<SubscriptionHandle>,
}

#[derive(Default)]
struct PoolInner {
    endpoints: HashMap<SocketAddr, EndpointState>,
}

/// Pool of gRPC channels addressed by resolved `SocketAddr`. Refreshed
/// periodically from DNS. Routes via one of two strategies — rendezvous
/// hashing on a routing key ([`SelectionStrategy::ByKey`]) or a random pick
/// ([`SelectionStrategy::Random`]) — over endpoints with a fresh, non-
/// non-draining load snapshot; retires endpoints that DNS removed.
pub struct EndpointPool {
    config: RemoteResolutionConfig,
    resolver: Arc<dyn DnsResolver>,
    inner: Mutex<PoolInner>,
    /// Notified when a subscription reports a fresh non-draining snapshot, so
    /// readiness checks can wait for actual routability.
    ready: Arc<Notify>,
    /// When false, the pool does not spawn per-endpoint subscription tasks.
    /// Used by tests that drive endpoint state manually.
    enable_subscriptions: bool,
}

/// RAII handle to a selected endpoint. Holds the in-flight counter increment
/// for the duration of the borrow and releases it on drop. The `Channel` is
/// `Clone` and internally `Arc`-shared, so cloning it for a request is cheap.
pub struct EndpointPoolHandle {
    pub addr: SocketAddr,
    pub channel: Channel,
    pub mux: ResolveMux,
    counter: Arc<AtomicUsize>,
    endpoint_label: Arc<str>,
}

impl EndpointPoolHandle {
    fn new(
        addr: SocketAddr,
        channel: Channel,
        mux: ResolveMux,
        counter: Arc<AtomicUsize>,
        endpoint_label: Arc<str>,
    ) -> Self {
        counter.fetch_add(1, Ordering::AcqRel);
        Self {
            addr,
            channel,
            mux,
            counter,
            endpoint_label,
        }
    }
}

impl Drop for EndpointPoolHandle {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::AcqRel);
        metrics::gauge!(
            REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT,
            "endpoint" => self.endpoint_label.clone(),
        )
        .decrement(1.0);
    }
}

impl EndpointPool {
    pub async fn new(
        config: RemoteResolutionConfig,
        resolver: Arc<dyn DnsResolver>,
    ) -> Result<Arc<Self>, EndpointPoolError> {
        let pool = Arc::new(Self {
            config,
            resolver,
            inner: Mutex::new(PoolInner::default()),
            ready: Arc::new(Notify::new()),
            enable_subscriptions: true,
        });
        // Eagerly seed the pool so the first request doesn't pay a full DNS
        // cost. Refresh errors propagate so AppContext bootstrap can fail
        // loudly when the host is misconfigured.
        pool.refresh().await?;
        if pool.inner.lock().await.endpoints.is_empty() {
            return Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::NoEndpoints,
            ));
        }
        Ok(pool)
    }

    /// Build a pool from a pre-resolved list of addresses with subscriptions
    /// enabled. Used by integration tests that point at a real stub server.
    pub fn from_addrs(
        config: RemoteResolutionConfig,
        addrs: &[SocketAddr],
    ) -> Result<Arc<Self>, EndpointPoolError> {
        Self::from_addrs_inner(config, addrs, true)
    }

    /// Build a pool from a pre-resolved list of addresses without spawning
    /// subscription tasks. Used by unit tests that exercise routing logic
    /// against manually-injected load snapshots.
    pub fn from_addrs_without_subscriptions(
        config: RemoteResolutionConfig,
        addrs: &[SocketAddr],
    ) -> Result<Arc<Self>, EndpointPoolError> {
        Self::from_addrs_inner(config, addrs, false)
    }

    fn from_addrs_inner(
        config: RemoteResolutionConfig,
        addrs: &[SocketAddr],
        enable_subscriptions: bool,
    ) -> Result<Arc<Self>, EndpointPoolError> {
        let pool = Arc::new(Self {
            config: config.clone(),
            // Dummy resolver — `refresh` should not be called in this mode.
            resolver: Arc::new(super::dns::TokioDnsResolver),
            inner: Mutex::new(PoolInner::default()),
            ready: Arc::new(Notify::new()),
            enable_subscriptions,
        });
        let mut inner = pool.inner.try_lock().expect("freshly constructed pool");
        for addr in addrs {
            let mut state = build_endpoint_state(*addr, &config)?;
            if enable_subscriptions {
                state.subscription = Some(spawn_subscription(
                    *addr,
                    state.channel.clone(),
                    state.load.clone(),
                    config.subscribe_tick_hint,
                    config.subscribe_reconnect_backoff,
                    config.internal_api_secret.clone(),
                    pool.ready.clone(),
                ));
            }
            inner.endpoints.insert(*addr, state);
        }
        metrics::gauge!(REMOTE_RESOLUTION_POOL_SIZE).set(inner.endpoints.len() as f64);
        record_endpoint_states(
            &inner,
            Instant::now(),
            config.subscribe_tick_hint.saturating_mul(2),
        );
        drop(inner);
        Ok(pool)
    }

    /// Resolve the configured hostname and reconcile the channel map. New
    /// addresses get a fresh channel; addresses that disappeared from DNS are
    /// marked draining and evicted once their in-flight counter reaches zero.
    pub async fn refresh(&self) -> Result<(), EndpointPoolError> {
        let resolved = self
            .resolver
            .resolve(&self.config.host, self.config.port)
            .await
            .map_err(|source| EndpointPoolError::Dns {
                host: self.config.host.clone(),
                port: self.config.port,
                source,
            });

        let resolved = resolved?;

        let mut inner = self.inner.lock().await;
        let mut still_present = std::collections::HashSet::new();
        for addr in &resolved {
            still_present.insert(*addr);
            let needs_rebuild = inner
                .endpoints
                .get(addr)
                .is_some_and(|state| state.mux.is_closed());
            if inner.endpoints.contains_key(addr) && !needs_rebuild {
                let state = inner.endpoints.get_mut(addr).expect("endpoint exists");
                // Re-add: any prior draining flag is cleared.
                state.draining = false;
                continue;
            }
            if needs_rebuild {
                info!(endpoint = %addr, "rebuilding closed remote resolution endpoint mux");
                if let Some(state) = inner.endpoints.remove(addr) {
                    state.mux.close();
                    if let Some(handle) = state.subscription {
                        handle.cancel();
                    }
                }
            }
            match build_endpoint_state(*addr, &self.config) {
                Ok(mut state) => {
                    info!(endpoint = %addr, "added remote resolution endpoint");
                    if self.enable_subscriptions {
                        state.subscription = Some(spawn_subscription(
                            *addr,
                            state.channel.clone(),
                            state.load.clone(),
                            self.config.subscribe_tick_hint,
                            self.config.subscribe_reconnect_backoff,
                            self.config.internal_api_secret.clone(),
                            self.ready.clone(),
                        ));
                    }
                    inner.endpoints.insert(*addr, state);
                }
                Err(err) => {
                    warn!(endpoint = %addr, error = %err, "skipping endpoint with invalid uri");
                }
            }
        }

        // Mark previously-known endpoints not in DNS as draining; evict
        // immediately if they have no in-flight requests.
        let to_remove: Vec<SocketAddr> = inner
            .endpoints
            .iter_mut()
            .filter_map(|(addr, state)| {
                if !still_present.contains(addr) {
                    state.draining = true;
                    state.mux.close();
                    if state.in_flight.load(Ordering::Acquire) == 0 {
                        Some(*addr)
                    } else {
                        None
                    }
                } else {
                    None
                }
            })
            .collect();
        for addr in to_remove {
            info!(endpoint = %addr, "evicted drained remote resolution endpoint");
            if let Some(state) = inner.endpoints.remove(&addr) {
                state.mux.close();
                if let Some(handle) = state.subscription {
                    handle.cancel();
                }
            }
        }

        let healthy_count = inner
            .endpoints
            .values()
            .filter(|state| !state.draining)
            .count();
        metrics::gauge!(REMOTE_RESOLUTION_POOL_SIZE).set(healthy_count as f64);
        record_endpoint_states(
            &inner,
            Instant::now(),
            self.config.subscribe_tick_hint.saturating_mul(2),
        );

        Ok(())
    }

    /// Select an endpoint at random among those with a fresh, non-draining load snapshot. Missing, stale, and draining
    /// snapshots are excluded from routing.
    ///
    /// Production routes via [`Self::select_for_key`] for warm-cache locality;
    /// this entry point is retained for tests and as a fallback for callers
    /// that have no useful routing key. `exclude` lists endpoints already
    /// tried this round so retries avoid them.
    pub async fn select(
        &self,
        exclude: &[SocketAddr],
    ) -> Result<EndpointPoolHandle, EndpointPoolError> {
        self.select_inner(SelectionStrategy::Random, exclude).await
    }

    /// Temporarily remove an endpoint from routing after it returned a
    /// per-item overload outcome. The ejection is process-local, doubles on
    /// repeated overloads up to the configured max, and expires automatically
    /// on the selection path.
    pub async fn eject_overloaded(&self, addr: SocketAddr) {
        if self.config.overload_ejection_initial.is_zero() {
            return;
        }
        let now = Instant::now();
        let mut inner = self.inner.lock().await;
        if let Some(state) = inner.endpoints.get_mut(&addr) {
            let quiet = state
                .overload_last_seen
                .and_then(|last_seen| now.checked_duration_since(last_seen))
                .is_none_or(|elapsed| elapsed >= self.config.overload_ejection_decay);
            let cooldown = if quiet || state.overload_ejection_cooldown.is_zero() {
                self.config.overload_ejection_initial
            } else {
                state
                    .overload_ejection_cooldown
                    .saturating_mul(2)
                    .min(self.config.overload_ejection_max)
            };
            let until = now + cooldown;
            state.overload_last_seen = Some(now);
            state.overload_ejection_cooldown = cooldown;
            state.overload_ejected_until = Some(until);
            warn!(
                endpoint = %addr,
                ejection_ms = cooldown.as_millis() as u64,
                "temporarily ejected overloaded remote resolution endpoint"
            );
            record_endpoint_states(
                &inner,
                now,
                self.config.subscribe_tick_hint.saturating_mul(2),
            );
        }
    }

    /// Select an endpoint using rendezvous hashing for the supplied routing
    /// key. This keeps events that need the same symbol set sticky to one
    /// cymbal-resolution pod, improving warm-cache locality while still
    /// spreading distinct keys across the pool. Draining endpoints are
    /// excluded. `exclude` lists endpoints already tried this round; the
    /// highest-ranked endpoint not in that set is chosen, so retries
    /// deterministically avoid the endpoint that just failed.
    pub async fn select_for_key(
        &self,
        routing_key: &str,
        exclude: &[SocketAddr],
    ) -> Result<EndpointPoolHandle, EndpointPoolError> {
        if routing_key.is_empty() {
            return self.select(exclude).await;
        }
        self.select_inner(SelectionStrategy::ByKey { routing_key }, exclude)
            .await
    }

    async fn select_inner(
        &self,
        strategy: SelectionStrategy<'_>,
        exclude: &[SocketAddr],
    ) -> Result<EndpointPoolHandle, EndpointPoolError> {
        let mut inner = self.inner.lock().await;
        if inner.endpoints.is_empty() {
            return Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::NoEndpoints,
            ));
        }

        let now = Instant::now();
        // Snapshot is fresh for two tick periods after observation. Deriving
        // staleness from the tick avoids a separate config knob and keeps the
        // freshness window scaled to whatever cadence the subscription is
        // running at.
        let stale_after = self.config.subscribe_tick_hint.saturating_mul(2);

        // Snapshot-required routing: a pod is only routable when its server-
        // reported LoadEvent snapshot is non-None AND fresh AND not
        // draining. There is no caller-side fallback — guessing load
        // from the local in-flight counter is strictly worse than using the
        // server's own signal, and silently routing on guesses defeats the
        // purpose of the Subscribe stream. If all pods are excluded, the
        // caller sees pool_empty with a reason label and retries with backoff.
        // Bootstrap therefore waits for one Subscribe tick before routing
        // begins.
        let mut candidates: Vec<Candidate> = Vec::with_capacity(inner.endpoints.len());
        let mut active_endpoint_count = 0usize;
        let mut ejected_endpoint_count = 0usize;
        let mut saw_missing_or_stale_snapshot = false;
        for (addr, state) in inner.endpoints.iter_mut() {
            if state.draining {
                continue;
            }
            active_endpoint_count += 1;
            if state
                .overload_ejected_until
                .is_some_and(|ejected_until| ejected_until > now)
            {
                ejected_endpoint_count += 1;
                continue;
            }
            state.overload_ejected_until = None;
            let Some(snapshot) = state.load.lock().ok().and_then(|guard| guard.clone()) else {
                saw_missing_or_stale_snapshot = true;
                continue;
            };
            if !snapshot.is_fresh(now, stale_after) {
                saw_missing_or_stale_snapshot = true;
                continue;
            }
            if snapshot.draining {
                continue;
            }
            candidates.push(Candidate {
                addr: *addr,
                channel: state.channel.clone(),
                mux: state.mux.clone(),
                counter: state.in_flight.clone(),
                endpoint_label: state.endpoint_label.clone(),
            });
        }

        record_endpoint_states(&inner, now, stale_after);

        if candidates.is_empty() {
            return Err(EndpointPoolError::Empty(classify_empty_reason(
                active_endpoint_count,
                ejected_endpoint_count,
                saw_missing_or_stale_snapshot,
            )));
        }

        // Prefer endpoints not yet tried this round. If every candidate has
        // been tried (e.g. a single-endpoint pool, or all others excluded),
        // fall back to the full set — retrying a pod after backoff beats
        // failing the batch when it's the only option left.
        let untried_count = candidates
            .iter()
            .filter(|c| !exclude.contains(&c.addr))
            .count();
        if untried_count > 0 {
            candidates.retain(|c| !exclude.contains(&c.addr));
        }

        let chosen = match strategy {
            SelectionStrategy::Random => match candidates.choose(&mut rand::thread_rng()) {
                Some(candidate) => candidate.clone(),
                None => {
                    return Err(EndpointPoolError::Empty(classify_empty_reason(
                        active_endpoint_count,
                        ejected_endpoint_count,
                        saw_missing_or_stale_snapshot,
                    )));
                }
            },
            SelectionStrategy::ByKey { routing_key } => {
                // Score each candidate once (O(n)) rather than re-hashing inside
                // the comparator (O(n log n) hashes). Rank by score desc with a
                // deterministic addr-asc tie-break, then discard the scores.
                let mut scored: Vec<(u64, Candidate)> = candidates
                    .into_iter()
                    .map(|c| (rendezvous_score(routing_key, &c.endpoint_label), c))
                    .collect();
                scored.sort_by(|(a_score, a), (b_score, b)| {
                    b_score.cmp(a_score).then(a.addr.cmp(&b.addr))
                });
                let ranked: Vec<Candidate> = scored.into_iter().map(|(_, c)| c).collect();
                match choose_ranked_candidate(ranked, self.config.routing_jitter) {
                    Some(candidate) => candidate,
                    None => {
                        return Err(EndpointPoolError::Empty(classify_empty_reason(
                            active_endpoint_count,
                            ejected_endpoint_count,
                            saw_missing_or_stale_snapshot,
                        )));
                    }
                }
            }
        };

        // Per-endpoint in-flight gauge; emitted only for the chosen endpoint
        // (not every candidate). The label is the endpoint's pre-built
        // `Arc<str>`, so this clone is a refcount bump rather than an alloc.
        metrics::gauge!(
            REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT,
            "endpoint" => chosen.endpoint_label.clone(),
        )
        .increment(1.0);

        Ok(EndpointPoolHandle::new(
            chosen.addr,
            chosen.channel,
            chosen.mux,
            chosen.counter,
            chosen.endpoint_label,
        ))
    }

    /// Wait until at least one endpoint is actually routable: present in DNS,
    /// not draining, and carrying a fresh non-draining load snapshot.
    pub async fn wait_ready(&self, timeout: Duration) -> Result<(), EndpointPoolError> {
        let timeout_at = tokio::time::Instant::now() + timeout;
        let mut last_reason: EndpointPoolEmptyReason;

        loop {
            let notified = self.ready.notified();
            match self.routing_availability().await {
                Ok(()) => return Ok(()),
                Err(reason) => last_reason = reason,
            }
            tokio::select! {
                _ = notified => {}
                _ = tokio::time::sleep_until(timeout_at) => {
                    return Err(EndpointPoolError::Empty(last_reason));
                }
            }
        }
    }

    async fn routing_availability(&self) -> Result<(), EndpointPoolEmptyReason> {
        let inner = self.inner.lock().await;
        if inner.endpoints.is_empty() {
            return Err(EndpointPoolEmptyReason::NoEndpoints);
        }
        let mut active_endpoint_count = 0usize;
        let mut ejected_endpoint_count = 0usize;
        let mut saw_missing_or_stale_snapshot = false;
        let now = Instant::now();
        let stale_after = self.config.subscribe_tick_hint.saturating_mul(2);
        for state in inner.endpoints.values() {
            if state.draining {
                continue;
            }
            active_endpoint_count += 1;
            if state
                .overload_ejected_until
                .is_some_and(|ejected_until| ejected_until > now)
            {
                ejected_endpoint_count += 1;
                continue;
            }
            let Some(snapshot) = state.load.lock().ok().and_then(|guard| guard.clone()) else {
                saw_missing_or_stale_snapshot = true;
                continue;
            };
            if !snapshot.is_fresh(now, stale_after) {
                saw_missing_or_stale_snapshot = true;
                continue;
            }
            if !snapshot.draining {
                return Ok(());
            }
        }
        Err(classify_empty_reason(
            active_endpoint_count,
            ejected_endpoint_count,
            saw_missing_or_stale_snapshot,
        ))
    }

    /// Test/observability helper: snapshot the current endpoints.
    pub async fn endpoints(&self) -> Vec<SocketAddr> {
        let inner = self.inner.lock().await;
        let mut addrs: Vec<SocketAddr> = inner
            .endpoints
            .iter()
            .filter(|(_, state)| !state.draining)
            .map(|(addr, _)| *addr)
            .collect();
        addrs.sort();
        addrs
    }

    /// Test-only: inject a synthetic load snapshot for an endpoint so the
    /// routing logic can be exercised without standing up a real subscription.
    /// Returns `false` if the endpoint isn't tracked.
    #[doc(hidden)]
    pub async fn inject_load_snapshot_for_test(
        &self,
        addr: SocketAddr,
        snapshot: LoadSnapshot,
    ) -> bool {
        let inner = self.inner.lock().await;
        let Some(state) = inner.endpoints.get(&addr) else {
            return false;
        };
        if let Ok(mut slot) = state.load.lock() {
            let should_notify = !snapshot.draining;
            *slot = Some(snapshot);
            if should_notify {
                self.ready.notify_waiters();
            }
            return true;
        }
        false
    }

    #[cfg(test)]
    async fn expire_overload_ejection_for_test(&self, addr: SocketAddr) -> bool {
        let mut inner = self.inner.lock().await;
        let Some(state) = inner.endpoints.get_mut(&addr) else {
            return false;
        };
        state.overload_ejected_until = Some(Instant::now() - Duration::from_millis(1));
        true
    }

    #[cfg(test)]
    async fn overload_ejection_cooldown_for_test(&self, addr: SocketAddr) -> Option<Duration> {
        let inner = self.inner.lock().await;
        inner
            .endpoints
            .get(&addr)
            .map(|state| state.overload_ejection_cooldown)
    }
}

#[derive(Clone)]
struct Candidate {
    addr: SocketAddr,
    channel: Channel,
    mux: ResolveMux,
    counter: Arc<AtomicUsize>,
    endpoint_label: Arc<str>,
}

enum SelectionStrategy<'a> {
    Random,
    ByKey { routing_key: &'a str },
}

fn classify_empty_reason(
    active_endpoint_count: usize,
    ejected_endpoint_count: usize,
    saw_missing_or_stale_snapshot: bool,
) -> EndpointPoolEmptyReason {
    if active_endpoint_count == 0 {
        EndpointPoolEmptyReason::AllEndpointsDraining
    } else if ejected_endpoint_count == active_endpoint_count {
        EndpointPoolEmptyReason::AllEndpointsEjected
    } else if saw_missing_or_stale_snapshot {
        EndpointPoolEmptyReason::NoFreshLoadSnapshots
    } else {
        EndpointPoolEmptyReason::AllEndpointsDraining
    }
}

fn rendezvous_score(routing_key: &str, addr_label: &str) -> u64 {
    // SHA-256 (no per-process seed) keeps the key->endpoint mapping identical
    // across every client pod. `addr_label` is the endpoint's pre-formatted
    // address string, so the hashed input matches the historical
    // `SocketAddr::to_string()` bytes exactly — the mapping is stable across a
    // rolling deploy — while the caller avoids re-allocating it per selection.
    let mut hasher = Sha256::new();
    hasher.update(routing_key.as_bytes());
    hasher.update(b"\0");
    hasher.update(addr_label.as_bytes());
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[0..8].try_into().expect("sha256 digest has 8 bytes"))
}

#[derive(Clone, Copy)]
enum EndpointRoutingState {
    Routable,
    Ejected,
    Draining,
    Stale,
    MissingSnapshot,
}

impl EndpointRoutingState {
    const ALL: [Self; 5] = [
        Self::Routable,
        Self::Ejected,
        Self::Draining,
        Self::Stale,
        Self::MissingSnapshot,
    ];

    fn as_metric_tag(self) -> &'static str {
        match self {
            Self::Routable => "routable",
            Self::Ejected => "ejected",
            Self::Draining => "draining",
            Self::Stale => "stale",
            Self::MissingSnapshot => "missing_snapshot",
        }
    }

    fn index(self) -> usize {
        match self {
            Self::Routable => 0,
            Self::Ejected => 1,
            Self::Draining => 2,
            Self::Stale => 3,
            Self::MissingSnapshot => 4,
        }
    }
}

fn endpoint_routing_state(
    state: &EndpointState,
    now: Instant,
    stale_after: Duration,
) -> EndpointRoutingState {
    if state.draining {
        return EndpointRoutingState::Draining;
    }
    if state
        .overload_ejected_until
        .is_some_and(|ejected_until| ejected_until > now)
    {
        return EndpointRoutingState::Ejected;
    }
    let Some(snapshot) = state.load.lock().ok().and_then(|guard| guard.clone()) else {
        return EndpointRoutingState::MissingSnapshot;
    };
    if !snapshot.is_fresh(now, stale_after) {
        return EndpointRoutingState::Stale;
    }
    if snapshot.draining {
        return EndpointRoutingState::Draining;
    }
    EndpointRoutingState::Routable
}

fn record_endpoint_states(inner: &PoolInner, now: Instant, stale_after: Duration) {
    let mut counts = [0usize; EndpointRoutingState::ALL.len()];
    for state in inner.endpoints.values() {
        counts[endpoint_routing_state(state, now, stale_after).index()] += 1;
    }
    for state in EndpointRoutingState::ALL {
        metrics::gauge!(REMOTE_RESOLUTION_ENDPOINTS_BY_STATE, "state" => state.as_metric_tag())
            .set(counts[state.index()] as f64);
    }
}

fn choose_ranked_candidate(candidates: Vec<Candidate>, routing_jitter: f64) -> Option<Candidate> {
    let top_ranked = candidates.first()?.clone();
    if routing_jitter <= 0.0 || candidates.len() == 1 {
        return Some(top_ranked);
    }
    if routing_jitter >= 1.0 {
        return candidates.choose(&mut rand::thread_rng()).cloned();
    }

    let weights = (0..candidates.len())
        .map(|rank| routing_jitter.powi(rank as i32))
        .collect::<Vec<_>>();
    let total_weight = weights.iter().sum::<f64>();
    let mut draw = rand::thread_rng().gen_range(0.0..total_weight);

    for (candidate, weight) in candidates.into_iter().zip(weights) {
        if draw < weight {
            return Some(candidate);
        }
        draw -= weight;
    }

    Some(top_ranked)
}

#[cfg(test)]
fn ranked_selection_probability(rank: usize, candidate_count: usize, routing_jitter: f64) -> f64 {
    if candidate_count == 0 || rank >= candidate_count {
        return 0.0;
    }
    if routing_jitter <= 0.0 {
        return if rank == 0 { 1.0 } else { 0.0 };
    }
    if routing_jitter >= 1.0 {
        return 1.0 / candidate_count as f64;
    }

    let rank_weight = routing_jitter.powi(rank as i32);
    let total_weight = (0..candidate_count)
        .map(|candidate_rank| routing_jitter.powi(candidate_rank as i32))
        .sum::<f64>();
    rank_weight / total_weight
}

/// Start a background task that periodically calls [`EndpointPool::refresh`].
/// Returns the join handle so callers can shut it down when needed.
pub fn spawn_refresh_task(pool: Arc<EndpointPool>) -> tokio::task::JoinHandle<()> {
    let interval = pool.config.dns_refresh;
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            ticker.tick().await;
            if let Err(err) = pool.refresh().await {
                warn!(error = %err, "remote resolution dns refresh failed");
            }
        }
    })
}

fn build_endpoint_state(
    addr: SocketAddr,
    config: &RemoteResolutionConfig,
) -> Result<EndpointState, EndpointPoolError> {
    // tonic's `Endpoint` parses the URI and applies channel options. Using
    // `connect_lazy()` keeps cold endpoints out of the connect path until
    // they're actually selected, which matters for k8s rolling pods.
    let uri = format!("http://{addr}");
    let endpoint = Endpoint::from_shared(uri)
        .map_err(|source| EndpointPoolError::InvalidEndpoint { addr, source })?;
    let endpoint = endpoint
        .connect_timeout(config.connect_timeout)
        .tcp_keepalive(Some(Duration::from_secs(30)))
        .keep_alive_while_idle(true);
    let channel = endpoint.connect_lazy();
    let mux = ResolveMux::new(
        addr,
        channel.clone(),
        config.internal_api_secret.clone(),
        RESOLVE_MUX_QUEUE_CAPACITY,
    );
    Ok(EndpointState {
        channel,
        mux,
        in_flight: Arc::new(AtomicUsize::new(0)),
        endpoint_label: Arc::from(addr.to_string()),
        draining: false,
        load: Arc::new(StdMutex::new(None)),
        overload_ejected_until: None,
        overload_ejection_cooldown: Duration::ZERO,
        overload_last_seen: None,
        subscription: None,
    })
}

#[cfg(test)]
mod test {
    use std::io;

    use async_trait::async_trait;
    use tokio::sync::Mutex as TokioMutex;

    use super::*;

    fn mock_config() -> RemoteResolutionConfig {
        RemoteResolutionConfig {
            host: "cymbal-resolution.test".to_string(),
            port: 50061,
            internal_api_secret: "test-secret".to_string(),
            dns_refresh: Duration::from_secs(1),
            request_deadline: Duration::from_secs(5),
            connect_timeout: Duration::from_millis(500),
            max_retries: 2,
            retry_backoff: Duration::from_millis(1),
            retry_max_backoff: Duration::from_millis(2),
            sample_rate: 1.0,
            routing_jitter: 0.0,
            routing_acceptance_concurrency: 10,
            overload_ejection_initial: Duration::ZERO,
            overload_ejection_max: Duration::ZERO,
            overload_ejection_decay: Duration::from_secs(30),
            subscribe_tick_hint: Duration::from_millis(50),
            subscribe_reconnect_backoff: Duration::from_millis(50),
        }
    }

    struct FakeResolver(Arc<TokioMutex<Vec<Vec<SocketAddr>>>>);

    #[async_trait]
    impl DnsResolver for FakeResolver {
        async fn resolve(&self, _host: &str, _port: u16) -> io::Result<Vec<SocketAddr>> {
            let mut queued = self.0.lock().await;
            if queued.is_empty() {
                Err(io::Error::other("no more fixtures"))
            } else {
                Ok(queued.remove(0))
            }
        }
    }

    fn addr(s: &str) -> SocketAddr {
        s.parse().unwrap()
    }

    fn fresh_snapshot() -> LoadSnapshot {
        LoadSnapshot {
            draining: false,
            observed_at: Instant::now(),
            sequence: 1,
        }
    }

    #[tokio::test]
    async fn new_fails_when_dns_returns_no_endpoints() {
        let queue = Arc::new(TokioMutex::new(vec![Vec::new()]));
        let result = EndpointPool::new(mock_config(), Arc::new(FakeResolver(queue))).await;
        assert!(matches!(
            result,
            Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::NoEndpoints
            ))
        ));
    }

    #[tokio::test]
    async fn refresh_adds_new_endpoints_and_drains_removed_ones() {
        let queue = Arc::new(TokioMutex::new(vec![
            vec![addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
            vec![addr("10.0.0.2:50061"), addr("10.0.0.3:50061")],
        ]));
        let pool = EndpointPool::new(mock_config(), Arc::new(FakeResolver(queue.clone())))
            .await
            .unwrap();
        assert_eq!(
            pool.endpoints().await,
            vec![addr("10.0.0.1:50061"), addr("10.0.0.2:50061")]
        );

        pool.refresh().await.unwrap();
        assert_eq!(
            pool.endpoints().await,
            vec![addr("10.0.0.2:50061"), addr("10.0.0.3:50061")]
        );
    }

    /// Inject a fresh snapshot on every endpoint of `pool` so
    /// snapshot-required routing has all endpoints to choose from.
    async fn inject_uniform_fresh_snapshots(pool: &Arc<EndpointPool>, addrs: &[SocketAddr]) {
        for a in addrs {
            assert!(
                pool.inject_load_snapshot_for_test(*a, fresh_snapshot())
                    .await
            );
        }
    }

    #[tokio::test]
    async fn select_returns_empty_when_no_endpoint_has_a_fresh_snapshot() {
        // Snapshot-required routing: with no LoadEvent received yet, every
        // pod is excluded. select() surfaces Empty so the caller can retry
        // with backoff while subscriptions warm up.
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        assert!(matches!(
            pool.select(&[]).await,
            Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::NoFreshLoadSnapshots
            ))
        ));
    }

    #[tokio::test]
    async fn select_reports_all_draining_when_every_fresh_snapshot_is_draining() {
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        let mut draining = fresh_snapshot();
        draining.draining = true;
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), draining.clone())
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), draining)
                .await
        );

        assert!(matches!(
            pool.select(&[]).await,
            Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::AllEndpointsDraining
            ))
        ));
    }

    #[tokio::test]
    async fn wait_ready_requires_a_fresh_non_draining_snapshot() {
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061")],
        )
        .unwrap();
        assert!(matches!(
            pool.wait_ready(Duration::from_millis(1)).await,
            Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::NoFreshLoadSnapshots
            ))
        ));
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), fresh_snapshot())
                .await
        );
        pool.wait_ready(Duration::from_millis(1)).await.unwrap();
    }

    #[tokio::test]
    async fn select_excludes_endpoints_with_stale_snapshots() {
        // A pod whose snapshot is older than the freshness window is excluded
        // from routing — the pool does NOT fall back to caller-side
        // in-flight estimation. The remaining fresh pod is the only candidate.
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        let stale = LoadSnapshot {
            draining: false,
            observed_at: Instant::now() - Duration::from_secs(10),
            sequence: 1,
        };
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), stale)
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), fresh_snapshot())
                .await
        );

        // .1 is stale and excluded; .2 is the only candidate.
        for _ in 0..5 {
            let handle = pool.select(&[]).await.unwrap();
            assert_eq!(handle.addr, addr("10.0.0.2:50061"));
        }
    }

    #[tokio::test]
    async fn select_spreads_randomly_across_fresh_healthy_endpoints() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        // All endpoints are fresh and healthy, so random selection should
        // reach every one of them over enough draws.
        let mut picks = std::collections::HashSet::new();
        for _ in 0..200 {
            picks.insert(pool.select(&[]).await.unwrap().addr);
        }
        assert_eq!(picks.len(), addrs.len());
    }

    #[tokio::test]
    async fn select_for_key_is_sticky_for_the_same_key() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let first = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        for _ in 0..10 {
            let next = pool
                .select_for_key("team:1:symbol:bundle-a", &[])
                .await
                .unwrap()
                .addr;
            assert_eq!(next, first);
        }
    }

    #[tokio::test]
    async fn select_for_key_top_choice_is_independent_of_insertion_order() {
        // Rendezvous ranking must depend only on (routing_key, addr), not on
        // the order endpoints were added — otherwise different pods, which see
        // DNS in arbitrary order, would disagree on the sticky endpoint and
        // shred cache locality. Two orderings of the same set must agree.
        let forward = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let reverse = [
            addr("10.0.0.3:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.1:50061"),
        ];
        let key = "team:1:symbol:bundle-order";

        let pool_forward =
            EndpointPool::from_addrs_without_subscriptions(mock_config(), &forward).unwrap();
        inject_uniform_fresh_snapshots(&pool_forward, &forward).await;
        let pool_reverse =
            EndpointPool::from_addrs_without_subscriptions(mock_config(), &reverse).unwrap();
        inject_uniform_fresh_snapshots(&pool_reverse, &reverse).await;

        let chosen_forward = pool_forward.select_for_key(key, &[]).await.unwrap().addr;
        let chosen_reverse = pool_reverse.select_for_key(key, &[]).await.unwrap().addr;
        assert_eq!(chosen_forward, chosen_reverse);
    }

    #[test]
    fn rendezvous_score_is_deterministic_and_stable() {
        let key = "team:1:symbol:bundle-a";
        // Stable across calls (no per-process seed) and distinct per endpoint.
        assert_eq!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.1:50061")
        );
        assert_ne!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.2:50061")
        );
        // Port is part of the label, so two ports on one host differ.
        assert_ne!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.1:50062")
        );
        // The hashed input is the SocketAddr's Display form, so scoring the
        // label matches scoring `addr.to_string()` byte-for-byte. This pins the
        // key->endpoint mapping so it survives a rolling deploy.
        let socket = addr("10.0.0.1:50061");
        assert_eq!(
            rendezvous_score(key, &socket.to_string()),
            rendezvous_score(key, "10.0.0.1:50061")
        );
    }

    #[tokio::test]
    async fn select_for_key_uses_random_routing_when_jitter_is_full() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let mut config = mock_config();
        config.routing_jitter = 1.0;
        let pool = EndpointPool::from_addrs_without_subscriptions(config, &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let mut picks = std::collections::HashSet::new();
        for _ in 0..200 {
            picks.insert(
                pool.select_for_key("team:1:symbol:bundle-a", &[])
                    .await
                    .unwrap()
                    .addr,
            );
        }

        assert!(
            picks.len() > 1,
            "full routing jitter should not stay sticky to one endpoint"
        );
    }

    #[test]
    fn routing_jitter_probability_decays_by_rank() {
        assert_eq!(ranked_selection_probability(0, 4, 0.0), 1.0);
        assert_eq!(ranked_selection_probability(1, 4, 0.0), 0.0);

        for rank in 0..4 {
            assert!((ranked_selection_probability(rank, 4, 1.0) - 0.25).abs() < f64::EPSILON);
        }

        let total_weight = 1.0 + 0.5 + 0.25 + 0.125;
        assert!((ranked_selection_probability(0, 4, 0.5) - (1.0 / total_weight)).abs() < 1e-12);
        assert!((ranked_selection_probability(1, 4, 0.5) - (0.5 / total_weight)).abs() < 1e-12);
        assert!((ranked_selection_probability(2, 4, 0.5) - (0.25 / total_weight)).abs() < 1e-12);
        assert!((ranked_selection_probability(3, 4, 0.5) - (0.125 / total_weight)).abs() < 1e-12);
    }

    #[tokio::test]
    async fn select_for_key_spreads_distinct_keys_across_endpoints() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let mut picks = std::collections::HashSet::new();
        for idx in 0..64 {
            let handle = pool
                .select_for_key(&format!("team:1:symbol:bundle-{idx}"), &[])
                .await
                .unwrap();
            picks.insert(handle.addr);
        }

        assert!(
            picks.len() > 1,
            "distinct routing keys should not all route to one endpoint"
        );
    }

    #[tokio::test]
    async fn select_for_key_avoids_excluded_endpoints_on_retry() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let first = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        // Excluding the first pick forces the next-ranked endpoint.
        let retry = pool
            .select_for_key("team:1:symbol:bundle-a", &[first])
            .await
            .unwrap()
            .addr;
        assert_ne!(retry, first);

        // Excluding both forces the third; the result is stable (rendezvous
        // ranking, not rotation).
        let third = pool
            .select_for_key("team:1:symbol:bundle-a", &[first, retry])
            .await
            .unwrap()
            .addr;
        assert_ne!(third, first);
        assert_ne!(third, retry);
    }

    #[tokio::test]
    async fn overload_ejection_excludes_endpoint_across_requests_until_expiry() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let mut config = mock_config();
        config.overload_ejection_initial = Duration::from_millis(25);
        config.overload_ejection_max = Duration::from_millis(100);
        let pool = EndpointPool::from_addrs_without_subscriptions(config, &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let first = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        pool.eject_overloaded(first).await;

        let while_ejected = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        assert_ne!(while_ejected, first);

        assert_eq!(
            pool.overload_ejection_cooldown_for_test(first).await,
            Some(Duration::from_millis(25))
        );
        assert!(pool.expire_overload_ejection_for_test(first).await);
        let after_expiry = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        assert_eq!(after_expiry, first);

        pool.eject_overloaded(first).await;
        assert_eq!(
            pool.overload_ejection_cooldown_for_test(first).await,
            Some(Duration::from_millis(50))
        );
        let after_initial_duration = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        assert_ne!(after_initial_duration, first);

        assert!(pool.expire_overload_ejection_for_test(first).await);
        let after_doubled_duration = pool
            .select_for_key("team:1:symbol:bundle-a", &[])
            .await
            .unwrap()
            .addr;
        assert_eq!(after_doubled_duration, first);
    }

    #[tokio::test]
    async fn select_reports_all_ejected_when_every_endpoint_is_in_cooldown() {
        let addrs = [addr("10.0.0.1:50061"), addr("10.0.0.2:50061")];
        let mut config = mock_config();
        config.overload_ejection_initial = Duration::from_secs(1);
        config.overload_ejection_max = Duration::from_secs(1);
        let pool = EndpointPool::from_addrs_without_subscriptions(config, &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        for addr in addrs {
            pool.eject_overloaded(addr).await;
        }

        assert!(matches!(
            pool.select(&[]).await,
            Err(EndpointPoolError::Empty(
                EndpointPoolEmptyReason::AllEndpointsEjected
            ))
        ));
    }

    #[tokio::test]
    async fn select_for_key_excludes_draining_endpoints() {
        let addrs = [addr("10.0.0.1:50061"), addr("10.0.0.2:50061")];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();

        let mut draining = fresh_snapshot();
        draining.draining = true;
        assert!(pool.inject_load_snapshot_for_test(addrs[0], draining).await);
        assert!(
            pool.inject_load_snapshot_for_test(addrs[1], fresh_snapshot())
                .await
        );

        let handle = pool
            .select_for_key("team:1:symbol:force-away-from-draining", &[])
            .await
            .unwrap();
        assert_eq!(handle.addr, addrs[1]);
    }

    #[tokio::test]
    async fn select_excludes_endpoints_reporting_draining() {
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        let mut bad = fresh_snapshot();
        bad.draining = true;
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), bad)
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), fresh_snapshot())
                .await
        );

        // Draining endpoints are excluded even when they have fresh snapshots.
        let handle = pool.select(&[]).await.unwrap();
        assert_eq!(handle.addr, addr("10.0.0.2:50061"));
    }
}
