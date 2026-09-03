//! Keeps a write pool off a demoted Postgres reader after a failover.
//!
//! A connection that survives a failover is healthy at the protocol level, so sqlx's ping
//! passes and writes keep failing with SQLSTATE 25006 until `max_lifetime` recycles it. sqlx
//! cannot drain a live pool and does not implement libpq's `target_session_attrs=read-write`,
//! so we run that check from `before_acquire` and discard any connection that fails it.

use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use sqlx::postgres::PgPoolOptions;

/// Writability probes, labeled `result`: `clean`, `read_only` (connection discarded), or
/// `unknown` (the GUC answered something other than `on`/`off`, treated as writable).
/// A nonzero `read_only` rate means this pool reached a reader; there is no background rate.
pub const DB_WRITER_PROBE_COUNTER: &str = "db_writer_probe_total";

/// Times the guard stopped discarding connections because replacements were read-only too,
/// which means the cluster is refusing writes and reconnecting cannot help.
pub const DB_WRITER_GUARD_CAPPED_COUNTER: &str = "db_writer_guard_rejection_capped_total";

/// Enough headroom to clear a pool's worth of poisoned connections several times over within
/// one window, while still bounding churn when no replacement is writable either.
const DEFAULT_MAX_REJECTIONS_PER_WINDOW: u32 = 32;

/// Long enough for a failover's DNS transition to finish inside one window, short enough that
/// the cap re-arms promptly once the cluster takes writes again.
const DEFAULT_REJECTION_WINDOW: Duration = Duration::from_secs(60);

#[derive(Debug, Clone)]
pub struct WriterGuardConfig {
    /// Most connections discarded per `rejection_window`. Past this the guard lets writes fail
    /// rather than churn connections against a cluster that accepts none.
    pub max_rejections_per_window: u32,
    pub rejection_window: Duration,

    /// Labels the guard's metrics. `Arc<str>` because it is cloned into a macro per probe.
    pub pool_name: Option<Arc<str>>,
}

impl Default for WriterGuardConfig {
    fn default() -> Self {
        Self {
            max_rejections_per_window: DEFAULT_MAX_REJECTIONS_PER_WINDOW,
            rejection_window: DEFAULT_REJECTION_WINDOW,
            pool_name: None,
        }
    }
}

/// Counts what probes find and bounds how many connections the guard will discard. Cheap to
/// clone; clones share one state.
#[derive(Clone)]
pub struct WriterGuard {
    config: Arc<WriterGuardConfig>,
    state: Arc<Mutex<State>>,
}

#[derive(Default)]
struct State {
    window_started: Option<Instant>,
    rejections_in_window: u32,
}

impl WriterGuard {
    pub fn new(config: WriterGuardConfig) -> Self {
        Self {
            config: Arc::new(config),
            state: Arc::new(Mutex::new(State::default())),
        }
    }

    fn record_clean(&self) {
        self.probe_counter("clean").increment(1);
    }

    fn record_unknown(&self) {
        self.probe_counter("unknown").increment(1);
    }

    /// Records a probe that found a reader. Returns whether to discard the connection, which is
    /// false once this window's rejection cap is spent.
    fn record_read_only(&self, now: Instant) -> bool {
        self.probe_counter("read_only").increment(1);
        let mut state = self.lock();

        let window_expired = state
            .window_started
            .is_none_or(|start| now.duration_since(start) >= self.config.rejection_window);
        if window_expired {
            state.window_started = Some(now);
            state.rejections_in_window = 0;
        }

        if state.rejections_in_window >= self.config.max_rejections_per_window {
            drop(state);
            self.counter(DB_WRITER_GUARD_CAPPED_COUNTER).increment(1);
            return false;
        }

        state.rejections_in_window += 1;
        true
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn counter(&self, name: &'static str) -> metrics::Counter {
        match &self.config.pool_name {
            Some(pool) => metrics::counter!(name, "pool" => pool.clone()),
            None => metrics::counter!(name),
        }
    }

    fn probe_counter(&self, result: &'static str) -> metrics::Counter {
        match &self.config.pool_name {
            Some(pool) => {
                metrics::counter!(DB_WRITER_PROBE_COUNTER, "pool" => pool.clone(), "result" => result)
            }
            None => metrics::counter!(DB_WRITER_PROBE_COUNTER, "result" => result),
        }
    }
}

/// Installs `guard` as a `before_acquire` hook so the pool stops handing out connections to a
/// demoted reader.
///
/// The probe replaces sqlx's ping rather than adding to it: `test_before_acquire` already spends
/// a round trip per acquire, and `SHOW transaction_read_only` answers the same liveness question
/// plus whether the server still takes writes. Because it costs no extra round trip, the guard
/// can probe every acquire, so a reader is caught on the next write.
/// `PgPoolOptions::before_acquire` documents this pattern.
///
/// `before_acquire` only sees connections from the idle queue, so a freshly opened one reaches
/// the caller unprobed and is caught on its next acquire. We deliberately do not also probe from
/// `after_connect`: an error there sends sqlx into a reconnect-backoff loop until
/// `acquire_timeout`, so a cluster-wide read-only state would surface as `PoolTimedOut` instead
/// of a 25006 the caller can classify.
pub fn install_writer_guard(options: PgPoolOptions, guard: &WriterGuard) -> PgPoolOptions {
    let guard = guard.clone();
    options
        .test_before_acquire(false)
        .before_acquire(move |conn, _meta| {
            let guard = guard.clone();
            Box::pin(async move {
                // libpq's `target_session_attrs=read-write` check. Reads `on` on an Aurora reader
                // and on a writer forced read-only, which are the same thing to this pool. An
                // error propagates, which drops the connection exactly as a failed ping would.
                let read_only: String = sqlx::query_scalar("SHOW transaction_read_only")
                    .fetch_one(&mut *conn)
                    .await?;

                if read_only.eq_ignore_ascii_case("on") {
                    // `Ok(false)` closes this connection; the replacement re-resolves the endpoint.
                    return Ok(!guard.record_read_only(Instant::now()));
                }

                // Postgres reports only `on` or `off`, so a third value means an assumption
                // broke. Keep the connection, because failing writes over a value we cannot
                // parse is worse than serving a stale reader, but count it so it is not silent.
                if !read_only.eq_ignore_ascii_case("off") {
                    guard.record_unknown();
                    return Ok(true);
                }

                guard.record_clean();
                Ok(true)
            })
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn guard() -> WriterGuard {
        WriterGuard::new(WriterGuardConfig {
            max_rejections_per_window: 2,
            rejection_window: Duration::from_secs(60),
            pool_name: None,
        })
    }

    /// A clean probe must not consume rejection budget: if it did, ordinary healthy traffic
    /// would exhaust the cap and the guard would stop discarding real readers.
    #[test]
    fn a_clean_probe_never_consumes_rejection_budget() {
        let g = guard(); // cap of 2 per 60s
        let t0 = Instant::now();

        for _ in 0..100 {
            g.record_clean();
        }
        {
            let state = g.lock();
            assert!(
                state.window_started.is_none(),
                "clean probes opened a window"
            );
            assert_eq!(state.rejections_in_window, 0);
        }

        assert!(g.record_read_only(t0));
        assert!(g.record_read_only(t0));
        assert!(!g.record_read_only(t0));
    }

    #[test]
    fn stops_discarding_connections_once_the_cap_is_spent() {
        let g = guard(); // cap of 2 per 60s
        let t0 = Instant::now();

        assert!(g.record_read_only(t0));
        assert!(g.record_read_only(t0));
        assert!(
            !g.record_read_only(t0),
            "replacements are readers too, so let writes fail instead of churning"
        );

        assert!(g.record_read_only(t0 + Duration::from_secs(60)));
    }
}
