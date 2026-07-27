//! Fanout core and admission control (plan §2.5).
//!
//! [`TopicRegistry`] maps each subscribed [`Topic`] to a `watch` channel, the
//! conflating primitive that gives "only the latest version matters" for free:
//! a slow receiver sees the newest value and nothing stale, with no ring buffer
//! and no per-connection queue. [`ConnectionPermits`] is the per-kind admission
//! backstop, released by RAII when the SSE stream drops.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use thiserror::Error;
use tokio::sync::watch;

use crate::domain::{Observation, Topic, VersionState};

/// The subscribe/apply/GC triangle over per-topic `watch` channels.
///
/// Two invariants make it race-free and are enforced by construction — no
/// method hands out the raw [`watch::Sender`]:
///
/// 1. [`subscribe`](Self::subscribe) creates the receiver via the DashMap entry
///    API while the entry write guard is held. Cloning the sender out and
///    calling `.subscribe()` after dropping the guard would let [`gc`](Self::gc)
///    remove the entry in the gap; a later same-topic subscribe would then make
///    a fresh channel and the orphaned receiver would never wake again — a
///    silent permanent-staleness bug.
/// 2. [`apply`](Self::apply) sends through the read guard from the map lookup,
///    and `gc` removes under the shard write lock, so the two are mutually
///    exclusive with invariant-1 subscribes.
#[derive(Default)]
pub struct TopicRegistry {
    topics: DashMap<Topic, watch::Sender<VersionState>>,
}

impl TopicRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Subscribe to a topic, creating it on first subscribe. The receiver is
    /// created under the entry guard (invariant 1).
    pub fn subscribe(&self, topic: Topic) -> watch::Receiver<VersionState> {
        self.topics
            .entry(topic)
            .or_insert_with(|| watch::channel(VersionState::default()).0)
            .subscribe()
    }

    /// Apply a trigger observation, waking receivers only when the state
    /// actually changed. No-op when nobody is subscribed — the M4 sweep only
    /// sweeps subscribed topics, so an unsubscribed topic has nothing to wake
    /// (hints, though, can arrive for any team). The send goes through the held
    /// read guard (invariant 2). The outcome feeds the trigger truth-table
    /// metric (`flags_stream_observations_total{outcome}`, plan §2.10).
    pub fn apply(&self, topic: Topic, obs: Observation) -> ApplyOutcome {
        match self.topics.get(&topic) {
            Some(sender) => {
                if sender.send_if_modified(|state| state.apply(obs)) {
                    ApplyOutcome::Changed
                } else {
                    ApplyOutcome::Unchanged
                }
            }
            None => ApplyOutcome::NoSubscribers,
        }
    }

    /// Topics that currently have at least one receiver — the sweep's input, so
    /// trigger load scales with subscribed teams, not all teams.
    pub fn subscribed_topics(&self) -> Vec<Topic> {
        self.topics
            .iter()
            .filter(|entry| entry.receiver_count() > 0)
            .map(|entry| *entry.key())
            .collect()
    }

    /// Drop entries whose channel has no receivers. `retain` is the map-wide
    /// form of "remove-if receiver-less"; it evaluates the predicate under each
    /// shard's write lock, so it is mutually exclusive with invariant-1
    /// subscribes.
    pub fn gc(&self) {
        self.topics
            .retain(|_topic, sender| sender.receiver_count() > 0);
    }

    /// Total live topic entries (subscribed or not-yet-GC'd). For metrics and
    /// tests that assert GC physically removed an entry.
    pub fn topic_count(&self) -> usize {
        self.topics.len()
    }
}

/// What applying an observation did — the per-observation truth the trigger
/// layer records as a metric label.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ApplyOutcome {
    /// The topic had no channel (nobody ever subscribed, or GC'd).
    NoSubscribers,
    /// The observation matched the current state; receivers were not woken.
    Unchanged,
    /// The state transitioned; receivers were woken.
    Changed,
}

/// A connect-time admission denial (plan §2.5).
#[derive(Debug, Error, PartialEq, Eq)]
pub enum PermitDenied {
    /// The per-pod global cap (both kinds) is full — the backstop that protects
    /// the pod. Displaced clients fall back to polling (today's behavior).
    #[error("per-pod global connection cap reached")]
    GlobalCapReached,
    /// The per-token cap for `Definitions` is full — sized against the refetch
    /// limiter (plan §2.6).
    #[error("per-token connection cap reached")]
    TokenCapReached,
}

/// Per-kind connection admission (plan §2.5).
///
/// Both kinds share a global per-pod cap. Only `Definitions` (server SDKs) has a
/// per-token cap, and there is deliberately **no** per-token path for
/// `RemoteEval`: the project token is public, so a per-token cap there is not a
/// defense but a targeted-denial lever — an attacker reading the token from page
/// source could fill it and lock out every real browser. That asymmetry is
/// encoded in the API: [`acquire_remote_eval`](Self::acquire_remote_eval) takes
/// no token, so a token cap is not expressible for it. Admission control for
/// Mode 2 is the team allowlist plus the global cap (enforced in M4).
#[derive(Clone)]
pub struct ConnectionPermits {
    inner: Arc<PermitState>,
}

struct PermitState {
    global_current: AtomicUsize,
    global_max: usize,
    /// Active connections per token for `Definitions` only. Entries are removed
    /// on reaching zero so idle tokens never leak map entries.
    per_token: DashMap<String, usize>,
    per_token_max: usize,
}

impl ConnectionPermits {
    pub fn new(global_max: usize, definitions_per_token_max: usize) -> Self {
        Self {
            inner: Arc::new(PermitState {
                global_current: AtomicUsize::new(0),
                global_max,
                per_token: DashMap::new(),
                per_token_max: definitions_per_token_max,
            }),
        }
    }

    /// Admit a `Definitions` (server-SDK) connection under both the global cap
    /// and the per-token cap.
    pub fn acquire_definitions(&self, token: &str) -> Result<ConnectionPermit, PermitDenied> {
        self.inner.reserve_global()?;
        if !self.inner.reserve_token(token) {
            self.inner.release_global();
            return Err(PermitDenied::TokenCapReached);
        }
        Ok(ConnectionPermit {
            state: Arc::clone(&self.inner),
            token: Some(token.to_owned()),
        })
    }

    /// Admit a `RemoteEval` (browser) connection under the global cap only — by
    /// design there is no per-token cap at this tier.
    pub fn acquire_remote_eval(&self) -> Result<ConnectionPermit, PermitDenied> {
        self.inner.reserve_global()?;
        Ok(ConnectionPermit {
            state: Arc::clone(&self.inner),
            token: None,
        })
    }

    /// Current global connection count (both kinds). For metrics and tests.
    pub fn active_connections(&self) -> usize {
        self.inner.global_current.load(Ordering::SeqCst)
    }

    /// Number of tokens with at least one active `Definitions` connection. Used
    /// by tests to prove entries do not leak after release.
    pub fn tracked_tokens(&self) -> usize {
        self.inner.per_token.len()
    }
}

impl PermitState {
    /// Reserve one global slot via a CAS loop, so the counter never exceeds the
    /// cap even transiently — an observer can never read more than the cap.
    fn reserve_global(&self) -> Result<(), PermitDenied> {
        let mut current = self.global_current.load(Ordering::SeqCst);
        loop {
            if current >= self.global_max {
                return Err(PermitDenied::GlobalCapReached);
            }
            match self.global_current.compare_exchange_weak(
                current,
                current + 1,
                Ordering::SeqCst,
                Ordering::SeqCst,
            ) {
                Ok(_) => return Ok(()),
                Err(actual) => current = actual,
            }
        }
    }

    fn release_global(&self) {
        self.global_current.fetch_sub(1, Ordering::SeqCst);
    }

    /// Reserve one per-token slot under the shard write lock. Never leaves a
    /// phantom zero entry on rejection.
    fn reserve_token(&self, token: &str) -> bool {
        match self.per_token.entry(token.to_owned()) {
            Entry::Occupied(mut e) => {
                if *e.get() >= self.per_token_max {
                    false
                } else {
                    *e.get_mut() += 1;
                    true
                }
            }
            Entry::Vacant(e) => {
                if self.per_token_max == 0 {
                    false
                } else {
                    e.insert(1);
                    true
                }
            }
        }
    }

    fn release_token(&self, token: &str) {
        if let Entry::Occupied(mut e) = self.per_token.entry(token.to_owned()) {
            let count = e.get_mut();
            *count = count.saturating_sub(1);
            if *count == 0 {
                e.remove();
            }
        }
    }
}

/// RAII admission guard. Dropping it releases the global slot (and, for
/// `Definitions`, the per-token slot). This is the axum disconnect signal: axum
/// has no disconnect callback, so the response stream — and this guard moved
/// into it — is simply dropped when the client goes away (plan §2.5).
pub struct ConnectionPermit {
    state: Arc<PermitState>,
    token: Option<String>,
}

impl std::fmt::Debug for ConnectionPermit {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ConnectionPermit")
            .field("token", &self.token)
            .finish_non_exhaustive()
    }
}

impl Drop for ConnectionPermit {
    fn drop(&mut self) {
        self.state.release_global();
        if let Some(token) = &self.token {
            self.state.release_token(token);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{CacheKind, Etag};
    use std::str::FromStr;

    fn topic(team_id: i32, kind: CacheKind) -> Topic {
        Topic { team_id, kind }
    }

    fn etag(hex: &str) -> Etag {
        Etag::from_str(hex).expect("valid etag")
    }

    #[test]
    fn subscribe_then_apply_wakes_with_new_state() {
        let reg = TopicRegistry::new();
        let t = topic(1, CacheKind::Definitions);
        let rx = reg.subscribe(t);
        // A fresh subscriber has already "seen" the initial Unknown value.
        assert!(!rx.has_changed().expect("sender alive"));

        let outcome = reg.apply(t, Observation::Present(etag("0123456789abcdef")));

        assert_eq!(outcome, ApplyOutcome::Changed);
        assert!(rx.has_changed().expect("sender alive"));
        assert_eq!(*rx.borrow(), VersionState::Known(etag("0123456789abcdef")));
    }

    #[test]
    fn apply_on_identical_etag_does_not_wake() {
        let reg = TopicRegistry::new();
        let t = topic(1, CacheKind::Definitions);
        let mut rx = reg.subscribe(t);
        let e = etag("0123456789abcdef");

        assert_eq!(reg.apply(t, Observation::Present(e)), ApplyOutcome::Changed);
        assert!(rx.has_changed().expect("sender alive"));
        rx.mark_unchanged();

        assert_eq!(
            reg.apply(t, Observation::Present(e)),
            ApplyOutcome::Unchanged
        );
        assert!(!rx.has_changed().expect("sender alive"));
    }

    #[test]
    fn apply_on_unsubscribed_topic_is_noop() {
        let reg = TopicRegistry::new();
        let t = topic(42, CacheKind::RemoteEval);
        assert_eq!(
            reg.apply(t, Observation::Present(etag("0123456789abcdef"))),
            ApplyOutcome::NoSubscribers
        );
        assert_eq!(reg.topic_count(), 0, "apply must not create the topic");
    }

    // The invariant-1 regression: subscribe -> drop receiver -> gc ->
    // resubscribe -> apply. If subscribe cloned the sender out after dropping
    // the entry guard, gc could remove the entry in the gap and the resubscribe
    // would create a fresh channel the apply never reaches. The new receiver
    // must wake.
    #[test]
    fn resubscribe_after_gc_still_wakes() {
        let reg = TopicRegistry::new();
        let t = topic(1, CacheKind::Definitions);

        let rx1 = reg.subscribe(t);
        drop(rx1);
        reg.gc();
        assert_eq!(reg.topic_count(), 0, "gc removes the receiver-less topic");

        let rx2 = reg.subscribe(t);
        reg.apply(t, Observation::Present(etag("fedcba9876543210")));

        assert!(rx2.has_changed().expect("sender alive"));
        assert_eq!(*rx2.borrow(), VersionState::Known(etag("fedcba9876543210")));
    }

    #[test]
    fn gc_removes_only_receiverless_topics() {
        let reg = TopicRegistry::new();
        let t_a = topic(1, CacheKind::Definitions);
        let t_b = topic(2, CacheKind::Definitions);

        let rx_a = reg.subscribe(t_a);
        let _rx_b = reg.subscribe(t_b);
        assert_eq!(reg.topic_count(), 2);

        drop(rx_a);
        // subscribed_topics excludes the receiver-less topic even before gc.
        assert_eq!(reg.subscribed_topics(), vec![t_b]);

        reg.gc();
        assert_eq!(reg.topic_count(), 1, "only t_a is removed");
        assert_eq!(reg.subscribed_topics(), vec![t_b]);
    }

    #[test]
    fn global_cap_enforced_across_kinds() {
        let permits = ConnectionPermits::new(2, 100);
        let p1 = permits.acquire_definitions("t").expect("first");
        let p2 = permits.acquire_remote_eval().expect("second");
        assert_eq!(permits.active_connections(), 2);

        // Third connect of either kind is denied by the shared global cap.
        assert_eq!(
            permits.acquire_remote_eval().unwrap_err(),
            PermitDenied::GlobalCapReached
        );
        assert_eq!(
            permits.acquire_definitions("u").unwrap_err(),
            PermitDenied::GlobalCapReached
        );

        drop(p1);
        drop(p2);
        assert_eq!(permits.active_connections(), 0);
    }

    #[test]
    fn definitions_token_cap_enforced_per_token() {
        let permits = ConnectionPermits::new(1000, 2);
        let _a1 = permits.acquire_definitions("token-a").expect("a1");
        let _a2 = permits.acquire_definitions("token-a").expect("a2");
        assert_eq!(
            permits.acquire_definitions("token-a").unwrap_err(),
            PermitDenied::TokenCapReached
        );
        // A different token has its own budget.
        let _b1 = permits.acquire_definitions("token-b").expect("b1");
        assert_eq!(permits.active_connections(), 3);
    }

    #[test]
    fn remote_eval_unaffected_by_token_caps() {
        // Per-token max of 1, but RemoteEval has no token path at all.
        let permits = ConnectionPermits::new(1000, 1);
        let mut held = Vec::new();
        for _ in 0..50 {
            held.push(
                permits
                    .acquire_remote_eval()
                    .expect("remote eval always admits"),
            );
        }
        assert_eq!(permits.active_connections(), 50);
        assert_eq!(permits.tracked_tokens(), 0, "remote_eval tracks no tokens");
    }

    #[test]
    fn drop_releases_both_levels_and_reacquire_succeeds() {
        let permits = ConnectionPermits::new(1, 1);
        {
            let _p = permits.acquire_definitions("t").expect("acquire");
            assert_eq!(permits.active_connections(), 1);
            assert_eq!(permits.tracked_tokens(), 1);
        }
        assert_eq!(permits.active_connections(), 0);
        // Token entry removed on reaching zero — no leak.
        assert_eq!(permits.tracked_tokens(), 0);
        // Both levels freed, so a re-acquire under the caps of 1/1 succeeds.
        let _p = permits.acquire_definitions("t").expect("re-acquire");
        assert_eq!(permits.active_connections(), 1);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_acquire_never_exceeds_caps() {
        let permits = ConnectionPermits::new(10, 100);
        let mut handles = Vec::new();
        // 100 contenders that hold their permit (returned, not dropped) until
        // joined, so every Ok is simultaneously alive. Exactly the cap can be
        // live at once, proving no over-admission under contention.
        for _ in 0..100 {
            let permits = permits.clone();
            handles.push(tokio::spawn(async move { permits.acquire_remote_eval() }));
        }

        let mut live = Vec::new();
        for handle in handles {
            if let Ok(permit) = handle.await.expect("task joins") {
                live.push(permit);
            }
        }

        assert_eq!(live.len(), 10, "exactly the global cap admitted");
        assert_eq!(permits.active_connections(), 10);

        drop(live);
        assert_eq!(permits.active_connections(), 0);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_token_churn_leaves_no_leak() {
        let permits = ConnectionPermits::new(1000, 1000);
        let mut handles = Vec::new();
        for i in 0..200 {
            let permits = permits.clone();
            let token = format!("token-{}", i % 8);
            handles.push(tokio::spawn(async move {
                let permit = permits
                    .acquire_definitions(&token)
                    .expect("under generous caps");
                tokio::task::yield_now().await;
                drop(permit);
            }));
        }
        for handle in handles {
            handle.await.expect("task joins");
        }
        assert_eq!(permits.active_connections(), 0);
        assert_eq!(permits.tracked_tokens(), 0, "all token entries removed");
    }
}
