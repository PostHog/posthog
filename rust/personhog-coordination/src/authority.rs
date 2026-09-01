//! Serving authority, published for the data plane to consult.
//!
//! A pod's right to serve a partition rests on its etcd lease. The
//! keepalive already detects loss and self-fences, but that detection is
//! itself a running task: a process that is stopped, starved, or wedged
//! stops renewing *and* stops noticing, and keeps answering requests out
//! of a cache the new owner is already mutating. A fence nobody is alive
//! to apply is not a fence.
//!
//! So the keepalive publishes rather than only reacts. It stamps this
//! clock on every confirmed renewal; the request path compares the stamp
//! against now and refuses once the lease could have expired at etcd. A
//! stalled keepalive then fences implicitly — the stamp simply stops
//! advancing — and the guarantee no longer depends on the liveness of
//! the component whose failure it exists to survive.
//!
//! The margin is the same two thirds of the TTL the keepalive uses to
//! declare loss, and stamps are anchored at the instant the renewal was
//! *sent* — before etcd could have restarted its countdown — so the
//! stamp always ages faster than the lease. Together those place the
//! refusal strictly before the moment the coordinator could treat the
//! lease as expired and hand the partition to someone else. Requests
//! are therefore refused while ownership is still merely *doubtful*,
//! ahead of it becoming wrong.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant};

/// A lease-backed claim to serve, readable from the request path.
///
/// Cheap by construction: publishing is one relaxed atomic store on the
/// keepalive's path, and checking is one load plus a comparison, so the
/// hot path pays no lock and no syscall.
#[derive(Debug)]
pub struct AuthorityClock {
    /// Fixed origin for the millisecond stamps below; `Instant` is not
    /// representable in an atomic, and absolute time would drag wall
    /// clock skew into a purely local measurement.
    origin: Instant,
    /// Milliseconds since `origin` at the last confirmed renewal.
    confirmed_ms: AtomicU64,
    /// How long a stamp stays good — the keepalive's renewal margin,
    /// in milliseconds. Supplied by the session rather than at
    /// construction: the lease TTL is coordination's business, and the
    /// data plane holding this handle should not have to know it, let
    /// alone agree with it. Zero until the first session claims it,
    /// which reads as no authority.
    margin_ms: AtomicU64,
    /// Set when authority is known to be gone, which is stronger than a
    /// stale stamp and never recovers within this session.
    surrendered: AtomicBool,
}

impl AuthorityClock {
    /// A clock holding no authority yet.
    ///
    /// Constructed once per process and shared: the data plane can hold
    /// it from startup and read it without coordinating with whichever
    /// session happens to be current. Before the first lease is granted
    /// it reads as invalid, which is the right answer for a pod that has
    /// not registered.
    pub fn unclaimed() -> Self {
        Self {
            origin: Instant::now(),
            confirmed_ms: AtomicU64::new(0),
            margin_ms: AtomicU64::new(0),
            surrendered: AtomicBool::new(true),
        }
    }

    /// Claim authority for a newly granted lease.
    ///
    /// A session boundary is deliberately a reset rather than a fresh
    /// object: the data plane holds one handle for the life of the
    /// process, so a new claim has to be expressible through the handle
    /// it already has.
    /// `granted_at` is when the lease's countdown started at the server,
    /// which is earlier than this call by however long the grant and
    /// registration took. Anchoring on it rather than on now keeps a slow
    /// registration from silently extending the first window — the same
    /// reasoning the keepalive applies to its own first deadline.
    ///
    /// The stores are ordered so every torn view fails closed: until the
    /// final `surrendered` flip a reader refuses outright, and the
    /// Release/Acquire pair on that flag makes the margin and stamp
    /// written above visible to any reader that observes it cleared —
    /// so no interleaving can pair the new claim with the old session's
    /// numbers.
    pub fn begin_session(&self, margin: Duration, granted_at: Instant) {
        self.margin_ms
            .store(margin.as_millis() as u64, Ordering::Relaxed);
        self.confirm_at(granted_at);
        self.surrendered.store(false, Ordering::Release);
    }

    /// The keepalive's renewal margin for a lease TTL: two thirds,
    /// leaving the final third for the fence to land before the
    /// coordinator can act on the expiry.
    ///
    /// The single definition of that fraction. The keepalive's own
    /// deadline, the pod's heartbeat assertion, and this clock all read
    /// it from here, because a data plane that stopped serving at a
    /// different point than the keepalive declares loss would mean one
    /// of the two is wrong.
    pub fn renewal_margin(lease_ttl: i64) -> Duration {
        Duration::from_secs(lease_ttl.max(0) as u64).mul_f64(2.0 / 3.0)
    }

    /// Record a confirmed renewal. Called by the keepalive, and only by
    /// the keepalive: a renewal is the one event that proves the lease
    /// was alive at a known instant.
    ///
    /// `at` is when the renewal was *sent*, not when the response
    /// arrived. etcd restarts the lease countdown when it processes the
    /// request, which is after the send and before the receipt — so the
    /// send instant is the latest moment guaranteed not to overstate how
    /// much lease is left. Stamping receipt would let a slow round keep
    /// the claim valid past the lease's actual expiry.
    pub fn confirm(&self, at: Instant) {
        self.confirm_at(at);
    }

    /// Record a renewal confirmed at a known instant.
    fn confirm_at(&self, at: Instant) {
        self.confirmed_ms.store(
            at.saturating_duration_since(self.origin).as_millis() as u64,
            Ordering::Relaxed,
        );
    }

    /// Give up authority permanently for this session. Lease loss is
    /// authoritative in a way a stale stamp is not, so it latches.
    pub fn surrender(&self) {
        self.surrendered.store(true, Ordering::Relaxed);
    }

    /// Whether this pod may still act as the partition owner.
    ///
    /// The Acquire pairs with `begin_session`'s Release: a reader that
    /// sees the surrender cleared also sees that session's margin and
    /// stamp. The remaining Relaxed loads are safe because every stale
    /// view they can produce — an old stamp, a zero margin — reads as
    /// invalid.
    pub fn is_valid(&self) -> bool {
        if self.surrendered.load(Ordering::Acquire) {
            return false;
        }
        self.since_confirmed() < self.margin()
    }

    /// How long since the last confirmed renewal — the number the
    /// request path is really asking about, exposed for metrics and for
    /// error messages that have to explain a refusal.
    pub fn since_confirmed(&self) -> Duration {
        let confirmed = Duration::from_millis(self.confirmed_ms.load(Ordering::Relaxed));
        self.origin.elapsed().saturating_sub(confirmed)
    }

    pub fn margin(&self) -> Duration {
        Duration::from_millis(self.margin_ms.load(Ordering::Relaxed))
    }

    /// Whether authority was given up outright, as opposed to merely
    /// aging out. The two are different operational events — one is a
    /// drain or a lease loss the operator expects, the other is a
    /// keepalive that stopped running — and reporting them under one
    /// name makes the second invisible among the first.
    pub fn is_surrendered(&self) -> bool {
        self.surrendered.load(Ordering::Relaxed)
    }

    /// A clock whose last confirmed renewal is `age` old.
    ///
    /// The stamp is stored relative to a fixed origin, so a test cannot
    /// age it by writing to it — it would have to go below the origin,
    /// and `confirm_at` saturates there. Ageing the origin is the only
    /// way to express "renewals stopped this long ago" without sleeping
    /// through the margin, and a sleep long enough to be reliable on a
    /// loaded runner is long enough to slow every run.
    #[cfg(any(test, feature = "test-support"))]
    pub fn stale_for(margin: Duration, age: Duration) -> Self {
        let now = Instant::now();
        Self {
            origin: now.checked_sub(age).unwrap_or(now),
            confirmed_ms: AtomicU64::new(0),
            margin_ms: AtomicU64::new(margin.as_millis() as u64),
            surrendered: AtomicBool::new(false),
        }
    }

    /// Whether any session has claimed this clock yet. Before the first
    /// grant there is no margin to compare against, so age is not a
    /// meaningful reading.
    pub fn is_claimed(&self) -> bool {
        self.margin_ms.load(Ordering::Relaxed) > 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn granted(margin: Duration) -> AuthorityClock {
        let clock = AuthorityClock::unclaimed();
        clock.begin_session(margin, Instant::now());
        clock
    }

    /// A pod that has not registered holds nothing, and must not serve
    /// on the strength of a clock that merely has not aged out yet.
    #[test]
    fn an_unclaimed_clock_is_invalid() {
        assert!(!AuthorityClock::unclaimed().is_valid());
    }

    #[test]
    fn a_fresh_grant_is_valid() {
        assert!(granted(Duration::from_secs(20)).is_valid());
    }

    /// A pod that loses its lease and registers again is serving under a
    /// new claim; the handle the data plane holds has to carry that.
    #[test]
    fn a_new_session_restores_surrendered_authority() {
        let clock = granted(Duration::from_secs(20));
        clock.surrender();
        assert!(!clock.is_valid());
        clock.begin_session(Duration::from_secs(20), Instant::now());
        assert!(clock.is_valid());
    }

    /// The stamp honors the instant the caller anchors it at — the
    /// renewal's send — rather than when the confirmation call happens.
    /// Stamping at the call would credit the round-trip delay to the
    /// lease and keep the claim valid past the lease's actual expiry.
    #[test]
    fn a_confirmation_is_anchored_at_its_send_not_its_receipt() {
        let margin = Duration::from_secs(8);
        let clock = AuthorityClock::stale_for(margin, Duration::from_secs(20));
        // A renewal whose response only just arrived, but which was sent
        // ten seconds ago — longer than the margin. Anchoring at the
        // call instead of the send would revalidate the claim here.
        let sent = Instant::now()
            .checked_sub(Duration::from_secs(10))
            .expect("test instants are boot-relative");
        clock.confirm(sent);
        assert!(
            !clock.is_valid(),
            "a renewal sent 10s ago must not back an 8s margin, however \
             recently its response arrived"
        );
        clock.confirm(Instant::now());
        assert!(clock.is_valid(), "a fresh send backs the margin");
    }

    /// The point of the clock: authority lapses on its own once renewals
    /// stop, with nothing running to notice they have.
    ///
    /// Anchored in the past rather than slept through — `begin_session`
    /// takes the instant the lease's countdown started precisely so a
    /// caller can say "this session is already old", and a sleep would
    /// make the test a race against a loaded runner for no added
    /// coverage.
    #[test]
    fn authority_lapses_without_renewal() {
        let margin = Duration::from_secs(20);
        let clock = AuthorityClock::stale_for(margin, margin + Duration::from_secs(1));
        assert!(!clock.is_valid());
    }

    #[test]
    fn a_confirmed_renewal_extends_authority() {
        let margin = Duration::from_secs(20);
        let clock = AuthorityClock::stale_for(margin, margin + Duration::from_secs(1));
        assert!(!clock.is_valid(), "stale before the renewal");

        clock.confirm(Instant::now());
        assert!(clock.is_valid(), "the renewal should have moved the stamp");
    }

    /// Lease loss is final for the session: a renewal cannot arrive
    /// afterwards, and treating one as valid would resurrect a claim the
    /// coordinator has already reassigned.
    #[test]
    fn surrendered_authority_never_returns() {
        let clock = granted(Duration::from_secs(20));
        clock.surrender();
        clock.confirm(Instant::now());
        assert!(!clock.is_valid());
    }
}
