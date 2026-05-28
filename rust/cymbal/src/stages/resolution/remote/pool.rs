use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::sync::{Mutex, Notify};
use tonic::transport::{Channel, Endpoint};
use tracing::{info, warn};

use super::config::RemoteResolutionConfig;
use super::dns::DnsResolver;
use super::subscription::{spawn_subscription, LoadCell, LoadSnapshot, SubscriptionHandle};
use crate::metric_consts::{REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT, REMOTE_RESOLUTION_POOL_SIZE};

/// Errors returned by [`EndpointPool::select`] and [`EndpointPool::refresh`].
#[derive(Debug, Error)]
pub enum EndpointPoolError {
    #[error("remote resolution pool is empty (no healthy endpoints)")]
    Empty,
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
    in_flight: Arc<AtomicUsize>,
    // Endpoints that DNS no longer reports are marked draining. They keep
    // serving in-flight work but get no new requests. They are evicted on the
    // next refresh tick once in_flight drops to zero.
    draining: bool,
    /// Latest server-reported load snapshot. Updated by the subscription task
    /// when one is attached; reads on the routing path are cheap.
    load: LoadCell,
    /// Background task subscribing to this endpoint's load event bus. `None`
    /// when subscriptions are disabled (test pools constructed via
    /// [`EndpointPool::from_addrs_without_subscriptions`]).
    subscription: Option<SubscriptionHandle>,
}

#[derive(Default)]
struct PoolInner {
    endpoints: HashMap<SocketAddr, EndpointState>,
    /// Monotonic counter used to break ties round-robin.
    round_robin: usize,
}

/// Pool of gRPC channels addressed by resolved `SocketAddr`. Refreshed
/// periodically from DNS; selects endpoints by lowest fresh server-reported
/// load, with round-robin tie-breaking; retires endpoints that DNS removed.
pub struct EndpointPool {
    config: RemoteResolutionConfig,
    resolver: Arc<dyn DnsResolver>,
    inner: Mutex<PoolInner>,
    /// Notified when the pool first has at least one healthy endpoint, so
    /// readiness probes can wait for the pool to warm up.
    ready: Notify,
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
    counter: Arc<AtomicUsize>,
}

impl EndpointPoolHandle {
    fn new(addr: SocketAddr, channel: Channel, counter: Arc<AtomicUsize>) -> Self {
        counter.fetch_add(1, Ordering::AcqRel);
        Self {
            addr,
            channel,
            counter,
        }
    }
}

impl Drop for EndpointPoolHandle {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::AcqRel);
        metrics::gauge!(
            REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT,
            "endpoint" => self.addr.to_string(),
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
            ready: Notify::new(),
            enable_subscriptions: true,
        });
        // Eagerly seed the pool so the first request doesn't pay a full DNS
        // cost. Refresh errors propagate so AppContext bootstrap can fail
        // loudly when the host is misconfigured.
        pool.refresh().await?;
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
            ready: Notify::new(),
            enable_subscriptions,
        });
        let mut inner = pool.inner.try_lock().expect("freshly constructed pool");
        for addr in addrs {
            let mut state = build_endpoint_state(*addr, config.connect_timeout)?;
            if enable_subscriptions {
                state.subscription = Some(spawn_subscription(
                    *addr,
                    state.channel.clone(),
                    state.load.clone(),
                    config.subscribe_tick_hint,
                    config.subscribe_reconnect_backoff,
                    config.internal_api_secret.clone(),
                ));
            }
            inner.endpoints.insert(*addr, state);
        }
        metrics::gauge!(REMOTE_RESOLUTION_POOL_SIZE).set(inner.endpoints.len() as f64);
        drop(inner);
        pool.ready.notify_waiters();
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
            if let Some(state) = inner.endpoints.get_mut(addr) {
                // Re-add: any prior draining flag is cleared.
                state.draining = false;
                continue;
            }
            match build_endpoint_state(*addr, self.config.connect_timeout) {
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

        if healthy_count > 0 {
            self.ready.notify_waiters();
        }
        Ok(())
    }

    /// Select an endpoint, preferring lowest reported load ratio among endpoints
    /// with fresh snapshots. Missing, stale, degraded, and draining snapshots
    /// are excluded from routing. Ties are broken round-robin.
    ///
    /// Production routes via [`Self::select_for_key`] for warm-cache locality;
    /// this entry point is retained for tests and as a fallback for callers
    /// that have no useful routing key.
    pub async fn select(&self) -> Result<EndpointPoolHandle, EndpointPoolError> {
        self.select_inner(SelectionStrategy::LeastLoad).await
    }

    /// Select an endpoint using rendezvous hashing for the supplied routing
    /// key. This keeps events that need the same symbol set sticky to one
    /// cymbal-resolution pod, improving warm-cache locality while still
    /// spreading distinct keys across the pool. Draining/degraded endpoints are
    /// excluded just like load-aware selection. `attempt` rotates through the
    /// ranked endpoint list so retries can avoid the endpoint that just failed.
    pub async fn select_for_key(
        &self,
        routing_key: &str,
        attempt: u32,
    ) -> Result<EndpointPoolHandle, EndpointPoolError> {
        if routing_key.is_empty() {
            return self.select().await;
        }
        self.select_inner(SelectionStrategy::Keyed {
            routing_key,
            attempt,
        })
        .await
    }

    async fn select_inner(
        &self,
        strategy: SelectionStrategy<'_>,
    ) -> Result<EndpointPoolHandle, EndpointPoolError> {
        let mut inner = self.inner.lock().await;
        if inner.endpoints.is_empty() {
            return Err(EndpointPoolError::Empty);
        }

        let now = Instant::now();
        // Snapshot is fresh for two tick periods after observation. Deriving
        // staleness from the tick avoids a separate config knob and keeps the
        // freshness window scaled to whatever cadence the subscription is
        // running at.
        let stale_after = self.config.subscribe_tick_hint.saturating_mul(2);

        // Snapshot-required routing: a pod is only routable when its server-
        // reported LoadEvent snapshot is non-None AND fresh AND not
        // degraded/draining. There is no caller-side fallback — guessing load
        // from the local in-flight counter is strictly worse than using the
        // server's own signal, and silently routing on guesses defeats the
        // purpose of the load bus. If all pods are excluded, the caller sees
        // pool_empty and retries (which consumes the retry budget with
        // backoff). Bootstrap therefore takes one Subscribe tick before
        // routing begins.
        let mut candidates: Vec<Candidate> = Vec::with_capacity(inner.endpoints.len());
        for (addr, state) in inner.endpoints.iter() {
            if state.draining {
                continue;
            }
            let Some(snapshot) = state.load.lock().ok().and_then(|guard| guard.clone()) else {
                continue;
            };
            if !snapshot.is_fresh(now, stale_after) {
                continue;
            }
            if snapshot.degraded || snapshot.draining {
                continue;
            }
            candidates.push(Candidate {
                addr: *addr,
                load_ratio: snapshot.load_ratio(),
                in_flight: snapshot.in_flight,
                channel: state.channel.clone(),
                counter: state.in_flight.clone(),
            });
        }

        if candidates.is_empty() {
            return Err(EndpointPoolError::Empty);
        }

        let chosen = match strategy {
            SelectionStrategy::LeastLoad => {
                // Sort by (load_ratio, server-reported in_flight, addr) so
                // tie-breaking is deterministic before the round-robin
                // rotation, which keeps test observability clean.
                candidates.sort_by(|a, b| {
                    a.load_ratio
                        .partial_cmp(&b.load_ratio)
                        .unwrap_or(std::cmp::Ordering::Equal)
                        .then(a.in_flight.cmp(&b.in_flight))
                        .then(a.addr.cmp(&b.addr))
                });

                let min_ratio = candidates[0].load_ratio;
                let min_in_flight = candidates[0].in_flight;
                let tied_count = candidates
                    .iter()
                    .take_while(|c| {
                        (c.load_ratio - min_ratio).abs() < f64::EPSILON
                            && c.in_flight == min_in_flight
                    })
                    .count();
                let idx = if tied_count <= 1 {
                    0
                } else {
                    inner.round_robin = inner.round_robin.wrapping_add(1);
                    inner.round_robin % tied_count
                };
                candidates.into_iter().nth(idx).expect("tied candidate")
            }
            SelectionStrategy::Keyed {
                routing_key,
                attempt,
            } => {
                candidates.sort_by(|a, b| {
                    rendezvous_score(routing_key, b.addr)
                        .cmp(&rendezvous_score(routing_key, a.addr))
                        .then(
                            a.load_ratio
                                .partial_cmp(&b.load_ratio)
                                .unwrap_or(std::cmp::Ordering::Equal),
                        )
                        .then(a.in_flight.cmp(&b.in_flight))
                        .then(a.addr.cmp(&b.addr))
                });
                let idx = attempt as usize % candidates.len();
                candidates.into_iter().nth(idx).expect("keyed candidate")
            }
        };

        // Per-endpoint in-flight gauge; emitted only for the chosen endpoint
        // (not every candidate) to keep the per-selection allocation bounded.
        metrics::gauge!(
            REMOTE_RESOLUTION_ENDPOINT_IN_FLIGHT,
            "endpoint" => chosen.addr.to_string(),
        )
        .increment(1.0);

        Ok(EndpointPoolHandle::new(
            chosen.addr,
            chosen.channel,
            chosen.counter,
        ))
    }

    /// Wait until the pool has at least one healthy endpoint, or the deadline
    /// elapses. Returns `Ok(())` when the pool is ready, `Err(Empty)` if the
    /// timeout fires first.
    pub async fn wait_ready(&self, timeout: Duration) -> Result<(), EndpointPoolError> {
        let notified = self.ready.notified();
        tokio::pin!(notified);
        if self
            .inner
            .lock()
            .await
            .endpoints
            .values()
            .any(|s| !s.draining)
        {
            return Ok(());
        }
        match tokio::time::timeout(timeout, notified).await {
            Ok(()) => Ok(()),
            Err(_) => Err(EndpointPoolError::Empty),
        }
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

    /// Smallest `suggested_max_batch_items` across all endpoints that
    /// currently have a fresh, non-degraded, non-draining snapshot AND
    /// advertise a non-zero suggestion. Returns `None` when no candidate
    /// has a usable suggestion — caller falls back to its own config.
    ///
    /// Conservative by design: when one pod is asking callers to shrink
    /// batches, every caller respects it. Per-team routing means different
    /// teams *could* target pods with different suggestions; the small loss
    /// of efficiency for taking the global minimum is worth the simpler
    /// model.
    pub async fn min_suggested_max_items(&self) -> Option<u32> {
        let inner = self.inner.lock().await;
        let now = Instant::now();
        let stale_after = self.config.subscribe_tick_hint.saturating_mul(2);
        let mut min: Option<u32> = None;
        for state in inner.endpoints.values() {
            if state.draining {
                continue;
            }
            let Some(snap) = state.load.lock().ok().and_then(|guard| guard.clone()) else {
                continue;
            };
            if !snap.is_fresh(now, stale_after) || snap.degraded || snap.draining {
                continue;
            }
            if snap.suggested_max_batch_items == 0 {
                continue;
            }
            min = Some(match min {
                Some(prev) => prev.min(snap.suggested_max_batch_items),
                None => snap.suggested_max_batch_items,
            });
        }
        min
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
            *slot = Some(snapshot);
            return true;
        }
        false
    }
}

struct Candidate {
    addr: SocketAddr,
    load_ratio: f64,
    /// Server-reported in-flight count from the latest fresh `LoadEvent`.
    /// Tie-breaker after `load_ratio`; deterministic and reflects what the
    /// server actually sees, not what the caller guesses.
    in_flight: u32,
    channel: Channel,
    counter: Arc<AtomicUsize>,
}

enum SelectionStrategy<'a> {
    LeastLoad,
    Keyed { routing_key: &'a str, attempt: u32 },
}

fn rendezvous_score(routing_key: &str, addr: SocketAddr) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(routing_key.as_bytes());
    hasher.update(b"\0");
    hasher.update(addr.to_string().as_bytes());
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[0..8].try_into().expect("sha256 digest has 8 bytes"))
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
    connect_timeout: Duration,
) -> Result<EndpointState, EndpointPoolError> {
    // tonic's `Endpoint` parses the URI and applies channel options. Using
    // `connect_lazy()` keeps cold endpoints out of the connect path until
    // they're actually selected, which matters for k8s rolling pods.
    let uri = format!("http://{addr}");
    let endpoint = Endpoint::from_shared(uri)
        .map_err(|source| EndpointPoolError::InvalidEndpoint { addr, source })?;
    let endpoint = endpoint
        .connect_timeout(connect_timeout)
        .tcp_keepalive(Some(Duration::from_secs(30)))
        .keep_alive_while_idle(true);
    let channel = endpoint.connect_lazy();
    let _ = addr;
    Ok(EndpointState {
        channel,
        in_flight: Arc::new(AtomicUsize::new(0)),
        draining: false,
        load: Arc::new(StdMutex::new(None)),
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
            max_batch_items: 64,
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

    fn fresh_snapshot(in_flight: u32, max_in_flight: u32) -> LoadSnapshot {
        LoadSnapshot {
            in_flight,
            max_in_flight,
            degraded: false,
            draining: false,
            observed_at: Instant::now(),
            sequence: 1,
            suggested_max_batch_items: 0,
        }
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

    /// Inject a fresh, zero-load snapshot on every endpoint of `pool` so
    /// snapshot-required routing has all endpoints to choose from. Used by
    /// tests that exercise selection semantics independent of load values.
    async fn inject_uniform_fresh_snapshots(pool: &Arc<EndpointPool>, addrs: &[SocketAddr]) {
        for a in addrs {
            assert!(
                pool.inject_load_snapshot_for_test(*a, fresh_snapshot(0, 64))
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
        assert!(matches!(pool.select().await, Err(EndpointPoolError::Empty)));
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
            in_flight: 0,
            max_in_flight: 64,
            degraded: false,
            draining: false,
            observed_at: Instant::now() - Duration::from_secs(10),
            sequence: 1,
            suggested_max_batch_items: 0,
        };
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), stale)
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), fresh_snapshot(0, 64))
                .await
        );

        // .1 is stale and excluded; .2 is the only candidate.
        for _ in 0..5 {
            let handle = pool.select().await.unwrap();
            assert_eq!(handle.addr, addr("10.0.0.2:50061"));
        }
    }

    #[tokio::test]
    async fn select_distributes_with_round_robin_on_ties() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        // All endpoints report identical zero load, so round-robin breaks
        // the tie deterministically across consecutive selections.
        let h1 = pool.select().await.unwrap();
        let h2 = pool.select().await.unwrap();
        let h3 = pool.select().await.unwrap();
        let mut picks = [h1.addr, h2.addr, h3.addr];
        picks.sort();
        assert_eq!(picks, addrs);
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
            .select_for_key("team:1:symbol:bundle-a", 0)
            .await
            .unwrap()
            .addr;
        for _ in 0..10 {
            let next = pool
                .select_for_key("team:1:symbol:bundle-a", 0)
                .await
                .unwrap()
                .addr;
            assert_eq!(next, first);
        }
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
                .select_for_key(&format!("team:1:symbol:bundle-{idx}"), 0)
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
    async fn select_for_key_rotates_ranked_endpoints_on_retry_attempts() {
        let addrs = [
            addr("10.0.0.1:50061"),
            addr("10.0.0.2:50061"),
            addr("10.0.0.3:50061"),
        ];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        inject_uniform_fresh_snapshots(&pool, &addrs).await;

        let first = pool
            .select_for_key("team:1:symbol:bundle-a", 0)
            .await
            .unwrap()
            .addr;
        let retry = pool
            .select_for_key("team:1:symbol:bundle-a", 1)
            .await
            .unwrap()
            .addr;

        assert_ne!(retry, first);
    }

    #[tokio::test]
    async fn select_for_key_excludes_degraded_endpoints() {
        let addrs = [addr("10.0.0.1:50061"), addr("10.0.0.2:50061")];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();

        let mut degraded = fresh_snapshot(0, 64);
        degraded.degraded = true;
        assert!(pool.inject_load_snapshot_for_test(addrs[0], degraded).await);
        assert!(
            pool.inject_load_snapshot_for_test(addrs[1], fresh_snapshot(0, 64))
                .await
        );

        let handle = pool
            .select_for_key("team:1:symbol:force-away-from-degraded", 0)
            .await
            .unwrap();
        assert_eq!(handle.addr, addrs[1]);
    }

    #[tokio::test]
    async fn least_load_breaks_ties_on_server_reported_in_flight() {
        // With identical load_ratio, the tie-breaker is the server-reported
        // in_flight count — NOT the caller-side counter. Verified by injecting
        // snapshots where both report load_ratio=0.5 but different in_flight.
        let addrs = [addr("10.0.0.1:50061"), addr("10.0.0.2:50061")];
        let pool = EndpointPool::from_addrs_without_subscriptions(mock_config(), &addrs).unwrap();
        // Both snapshots: load_ratio = 50/100 == 0.5; .1 reports 50 in-flight,
        // .2 reports 50 in-flight too (so the next tie-breaker — addr — wins).
        // Then bump .2 down to 49/100 and observe .2 wins on lower in_flight.
        assert!(
            pool.inject_load_snapshot_for_test(addrs[0], fresh_snapshot(50, 100))
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addrs[1], fresh_snapshot(49, 100))
                .await
        );
        // load_ratio: .1 = 0.50, .2 = 0.49 — .2 wins by load_ratio alone.
        let handle = pool.select().await.unwrap();
        assert_eq!(handle.addr, addrs[1]);
    }

    #[tokio::test]
    async fn select_prefers_endpoint_with_lower_reported_load_ratio() {
        // With fresh load snapshots, routing is driven by load ratio, not by
        // local in-flight. Inject snapshots that contradict the local count so
        // we can be sure the server signal wins.
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        // .1 reports heavily loaded; .2 reports lightly loaded.
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), fresh_snapshot(60, 64))
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), fresh_snapshot(2, 64))
                .await
        );

        let handle = pool.select().await.unwrap();
        assert_eq!(handle.addr, addr("10.0.0.2:50061"));
    }

    #[tokio::test]
    async fn select_excludes_endpoints_reporting_degraded_or_draining() {
        let pool = EndpointPool::from_addrs_without_subscriptions(
            mock_config(),
            &[addr("10.0.0.1:50061"), addr("10.0.0.2:50061")],
        )
        .unwrap();
        let mut bad = fresh_snapshot(0, 64);
        bad.degraded = true;
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.1:50061"), bad)
                .await
        );
        assert!(
            pool.inject_load_snapshot_for_test(addr("10.0.0.2:50061"), fresh_snapshot(40, 64))
                .await
        );

        // Even though .1 reports the lower ratio, it is excluded because its
        // snapshot is flagged degraded.
        let handle = pool.select().await.unwrap();
        assert_eq!(handle.addr, addr("10.0.0.2:50061"));
    }
}
