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

use sqlx::{postgres::PgPoolOptions, Error as SqlxError};

/// Writability probes, labeled `result`: `clean` or `read_only` (connection discarded).
/// A nonzero `read_only` rate means this pool reached a reader; there is no background rate.
pub const DB_WRITER_PROBE_COUNTER: &str = "db_writer_probe_total";

/// Times the guard stopped discarding connections because replacements were read-only too,
/// which means the cluster is refusing writes and reconnecting cannot help.
pub const DB_WRITER_GUARD_CAPPED_COUNTER: &str = "db_writer_guard_rejection_capped_total";

/// SQLSTATE 25006: the server refused a write because the session is read-only. On Aurora this
/// is what a demoted writer returns, so retrying the same connection cannot help.
pub fn is_read_only_error(error: &SqlxError) -> bool {
    let SqlxError::Database(db) = error else {
        return false;
    };
    db.code().as_deref() == Some("25006")
}

/// Coarse, bounded label for a failed query. Raw SQLSTATE has too many values to label a
/// counter with.
pub fn error_class(error: &SqlxError) -> &'static str {
    // Pool-level cases first: `is_timeout_error` counts `PoolTimedOut`, but a saturated pool
    // and a slow statement need different responses.
    match error {
        SqlxError::PoolTimedOut => return "pool_timeout",
        SqlxError::PoolClosed => return "pool_closed",
        _ => {}
    }
    if is_read_only_error(error) {
        return "read_only";
    }
    if crate::is_timeout_error(error) {
        return "timeout";
    }
    if crate::is_foreign_key_constraint_error(error) {
        return "fk_violation";
    }
    match error {
        SqlxError::Database(db) => match db.code().as_deref() {
            Some("40P01") => "deadlock",
            Some("40001") => "serialization",
            Some("53300") => "too_many_connections",
            Some("57P01" | "57P02" | "57P03") => "server_shutdown",
            _ => "database",
        },
        SqlxError::Io(_) => "io",
        SqlxError::Tls(_) => "tls",
        _ => "other",
    }
}

#[derive(Debug, Clone)]
pub struct WriterGuardConfig {
    /// Gap between probes while no reader has been seen recently.
    pub heartbeat: Duration,

    /// How long after seeing a reader the guard probes every acquire. Must outlast the acquires
    /// needed to cover the pool: a probe only inspects the connection being acquired, so a
    /// fixed probe count can miss one and leave it serving writes.
    pub settle: Duration,

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
            heartbeat: Duration::from_secs(5),
            settle: Duration::from_secs(30),
            max_rejections_per_window: 32,
            rejection_window: Duration::from_secs(60),
            pool_name: None,
        }
    }
}

/// Decides whether an acquire pays for a probe, and tracks what probes find. Cheap to clone;
/// clones share one state.
#[derive(Clone)]
pub struct WriterGuard {
    config: Arc<WriterGuardConfig>,
    state: Arc<Mutex<State>>,
}

#[derive(Default)]
struct State {
    last_read_only: Option<Instant>,
    last_probe: Option<Instant>,
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

    /// True when this acquire should probe: a reader was seen within `settle`, or a heartbeat
    /// has elapsed.
    fn should_probe(&self, now: Instant) -> bool {
        let state = self.lock();
        if state
            .last_read_only
            .is_some_and(|t| now.duration_since(t) < self.config.settle)
        {
            return true;
        }
        match state.last_probe {
            None => true,
            Some(last) => now.duration_since(last) >= self.config.heartbeat,
        }
    }

    fn record_clean(&self, now: Instant) {
        self.probe_counter("clean").increment(1);
        self.lock().last_probe = Some(now);
    }

    /// Records a probe that found a reader. Returns whether to discard the connection, which is
    /// false once this window's rejection cap is spent.
    fn record_read_only(&self, now: Instant) -> bool {
        self.probe_counter("read_only").increment(1);
        let mut state = self.lock();
        state.last_probe = Some(now);
        state.last_read_only = Some(now);

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
/// The hook only sees connections from the idle queue; a freshly opened one reaches the caller
/// unprobed, which is why `settle` governs how long probing stays aggressive.
pub fn install_writer_guard(options: PgPoolOptions, guard: &WriterGuard) -> PgPoolOptions {
    let guard = guard.clone();
    options.before_acquire(move |conn, _meta| {
        let guard = guard.clone();
        Box::pin(async move {
            let now = Instant::now();
            if !guard.should_probe(now) {
                return Ok(true);
            }

            // libpq's `target_session_attrs=read-write` check. Reads `on` on an Aurora reader
            // and on a writer forced read-only, which are the same thing to this pool.
            let read_only: String = sqlx::query_scalar("SHOW transaction_read_only")
                .fetch_one(&mut *conn)
                .await?;

            if read_only.eq_ignore_ascii_case("on") {
                // `Ok(false)` closes this connection; the replacement re-resolves the endpoint.
                return Ok(!guard.record_read_only(now));
            }

            guard.record_clean(now);
            Ok(true)
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn guard() -> WriterGuard {
        WriterGuard::new(WriterGuardConfig {
            heartbeat: Duration::from_secs(10),
            settle: Duration::from_secs(30),
            max_rejections_per_window: 2,
            rejection_window: Duration::from_secs(60),
            pool_name: None,
        })
    }

    #[test]
    fn probes_once_per_heartbeat_while_no_reader_is_known() {
        let g = guard();
        let t0 = Instant::now();

        assert!(g.should_probe(t0), "first acquire has no prior probe");
        g.record_clean(t0);

        assert!(!g.should_probe(t0 + Duration::from_secs(9)));
        assert!(g.should_probe(t0 + Duration::from_secs(10)));
    }

    #[test]
    fn probes_every_acquire_once_a_reader_is_seen() {
        let g = guard();
        let t0 = Instant::now();

        assert!(g.record_read_only(t0), "first reader is discarded");
        assert!(g.should_probe(t0 + Duration::from_millis(1)));
    }

    /// A probe only inspects the connection being acquired, so a run of clean probes is no
    /// proof the whole pool was checked. Clean probes must not end probing early and leave an
    /// unprobed reader serving writes.
    #[test]
    fn clean_probes_never_end_probing_before_the_settle_window() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);

        for i in 0..50 {
            g.record_clean(t0 + Duration::from_millis(i));
        }

        assert!(g.should_probe(t0 + Duration::from_secs(29)));
    }

    #[test]
    fn stops_probing_every_acquire_once_the_settle_window_passes() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);

        let settled = t0 + Duration::from_secs(30);
        g.record_clean(settled);
        assert!(!g.should_probe(settled + Duration::from_secs(1)));
        assert!(g.should_probe(settled + Duration::from_secs(10)));
    }

    #[test]
    fn a_reader_extends_the_settle_window() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);
        g.record_read_only(t0 + Duration::from_secs(25));

        assert!(g.should_probe(t0 + Duration::from_secs(40)));
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

    #[test]
    fn cap_does_not_stop_the_guard_probing() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);
        g.record_read_only(t0);
        g.record_read_only(t0); // capped

        assert!(g.should_probe(t0));
    }

    #[test]
    fn error_class_separates_a_failover_from_ordinary_write_failures() {
        assert_eq!(error_class(&SqlxError::PoolTimedOut), "pool_timeout");
        assert_eq!(error_class(&SqlxError::PoolClosed), "pool_closed");
        assert_eq!(
            error_class(&SqlxError::Io(std::io::Error::other("x"))),
            "io"
        );
        assert_eq!(error_class(&SqlxError::RowNotFound), "other");
    }

    #[test]
    fn is_read_only_error_ignores_non_database_errors() {
        assert!(!is_read_only_error(&SqlxError::PoolTimedOut));
        // Only the SQLSTATE counts; matching message text would let any error impersonate a
        // failover.
        assert!(!is_read_only_error(&SqlxError::Protocol(
            "cannot execute INSERT in a read-only transaction".to_string()
        )));
    }
}
