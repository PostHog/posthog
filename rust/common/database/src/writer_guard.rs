//! Keeps a write pool off a demoted Postgres reader after a failover.
//!
//! When Aurora fails over, most clients lose their sockets and reconnect against the new
//! writer. A connection that survives the failover is the dangerous case: the old writer is
//! now a reader, so the socket is healthy, `test_before_acquire`'s ping succeeds, and every
//! write on it is refused with SQLSTATE 25006 until `max_lifetime` finally recycles it.
//!
//! libpq solves this with `target_session_attrs=read-write`, which issues
//! `SHOW transaction_read_only` and rejects the session if it answers `on`. sqlx implements
//! neither that option nor any way to drain a live pool (`set_connect_options` documents that
//! existing connections are left as-is, and `close` is terminal), so we run the same check
//! ourselves from a `before_acquire` hook. Returning `Ok(false)` there makes sqlx close the
//! connection and open a replacement, which re-resolves the writer endpoint.
//!
//! Probing every acquire would add a round trip to every query, so the guard idles at a
//! heartbeat cadence and switches to probing every acquire once it has seen a reader. Each
//! probe only inspects the one connection being acquired, so the worst case for noticing a
//! partially poisoned pool is roughly `heartbeat` × connections — after which the armed mode
//! clears the remaining bad connections within a few acquires.

use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use sqlx::{postgres::PgPoolOptions, Error as SqlxError};

/// Writability probes, labeled `result`: `clean` (a writer) or `read_only` (a reader, so the
/// connection was discarded and reopened). A nonzero `read_only` rate is the signal that this
/// pool was pointed at a reader; it has no steady-state background rate.
pub const DB_WRITER_PROBE_COUNTER: &str = "db_writer_probe_total";

/// Times the guard stopped discarding connections because it hit its rejection cap. Nonzero
/// means replacements keep coming back read-only, so the cluster itself is not accepting
/// writes and churning connections would not help.
pub const DB_WRITER_GUARD_CAPPED_COUNTER: &str = "db_writer_guard_rejection_capped_total";

/// SQLSTATE 25006, `read_only_sql_transaction`: the server refused a write because the
/// session is read-only. On Aurora this is what a demoted writer returns.
///
/// Distinct from a connection error — the socket is fine, the server's role changed. Callers
/// that retry on transient errors should not expect a retry on the same connection to help.
pub fn is_read_only_error(error: &SqlxError) -> bool {
    let SqlxError::Database(db) = error else {
        return false;
    };
    db.code().as_deref() == Some("25006")
}

/// Coarse, bounded label for a failed query, for use as a metric dimension. SQLSTATE itself
/// has far too many values to label a counter with directly.
pub fn error_class(error: &SqlxError) -> &'static str {
    // Pool-level conditions come first: `is_timeout_error` counts `PoolTimedOut` as a
    // timeout, but a saturated pool and a slow statement are different problems with
    // different responses, so they must not share a label.
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
    /// How long the guard waits between probes while it has no reason to suspect a reader.
    pub heartbeat: Duration,

    /// Consecutive clean probes required to leave the every-acquire probing mode.
    pub clean_probes_to_disarm: u32,

    /// Most connections the guard will discard within `rejection_window`. Past this it stops
    /// discarding and lets queries fail: if replacements keep coming back read-only, the
    /// cluster is not accepting writes and reconnecting only adds load to a struggling
    /// database.
    pub max_rejections_per_window: u32,
    pub rejection_window: Duration,

    /// Labels the guard's metrics, so a service with several pools can tell them apart.
    /// `Arc<str>` because it is cloned into a metric macro on every probe.
    pub pool_name: Option<Arc<str>>,
}

impl Default for WriterGuardConfig {
    fn default() -> Self {
        Self {
            heartbeat: Duration::from_secs(5),
            clean_probes_to_disarm: 3,
            max_rejections_per_window: 32,
            rejection_window: Duration::from_secs(60),
            pool_name: None,
        }
    }
}

/// Decides whether an acquire should pay for a writability probe, and tracks what probes find.
///
/// Cheap to clone; every clone shares one state.
#[derive(Clone)]
pub struct WriterGuard {
    config: Arc<WriterGuardConfig>,
    state: Arc<Mutex<State>>,
}

struct State {
    /// Probe every acquire until `clean_probes_to_disarm` consecutive clean probes.
    armed: bool,
    consecutive_clean: u32,
    last_probe: Option<Instant>,
    window_started: Option<Instant>,
    rejections_in_window: u32,
}

impl WriterGuard {
    pub fn new(config: WriterGuardConfig) -> Self {
        Self {
            config: Arc::new(config),
            state: Arc::new(Mutex::new(State {
                armed: false,
                consecutive_clean: 0,
                last_probe: None,
                window_started: None,
                rejections_in_window: 0,
            })),
        }
    }

    /// True when this acquire should pay for a probe: either the guard is armed, or a
    /// heartbeat has elapsed since the last probe.
    fn should_probe(&self, now: Instant) -> bool {
        let state = self.lock();
        if state.armed {
            return true;
        }
        match state.last_probe {
            None => true,
            Some(last) => now.duration_since(last) >= self.config.heartbeat,
        }
    }

    /// Record a probe that found a writer. Disarms after enough consecutive clean probes.
    fn record_clean(&self, now: Instant) {
        self.probe_counter("clean").increment(1);
        let mut state = self.lock();
        state.last_probe = Some(now);
        state.consecutive_clean = state.consecutive_clean.saturating_add(1);
        if state.armed && state.consecutive_clean >= self.config.clean_probes_to_disarm {
            state.armed = false;
        }
    }

    /// Record a probe that found a reader. Returns whether to discard the connection, which
    /// is false once the rejection cap for the current window is spent.
    fn record_read_only(&self, now: Instant) -> bool {
        self.probe_counter("read_only").increment(1);
        let mut state = self.lock();
        state.last_probe = Some(now);
        state.armed = true;
        state.consecutive_clean = 0;

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

/// Installs `guard` as a `before_acquire` hook, so the pool stops handing out connections to
/// a demoted reader.
///
/// The hook only sees connections coming off the idle queue; a freshly opened connection goes
/// straight to the caller. That is why the guard stays armed until several clean probes in a
/// row, rather than trusting the first replacement it opens.
pub fn install_writer_guard(options: PgPoolOptions, guard: &WriterGuard) -> PgPoolOptions {
    let guard = guard.clone();
    options.before_acquire(move |conn, _meta| {
        let guard = guard.clone();
        Box::pin(async move {
            let now = Instant::now();
            if !guard.should_probe(now) {
                return Ok(true);
            }

            // The check libpq performs for `target_session_attrs=read-write`. Reads as `on`
            // on an Aurora reader, and also on a writer that has been forced read-only (a
            // storage-full instance, some maintenance operations) — the same situation from
            // this pool's point of view.
            let read_only: String = sqlx::query_scalar("SHOW transaction_read_only")
                .fetch_one(&mut *conn)
                .await?;

            if read_only.eq_ignore_ascii_case("on") {
                // `Ok(false)` closes this connection and opens a replacement, which
                // re-resolves the writer endpoint.
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
            clean_probes_to_disarm: 3,
            max_rejections_per_window: 2,
            rejection_window: Duration::from_secs(60),
            pool_name: None,
        })
    }

    #[test]
    fn probes_once_per_heartbeat_when_unarmed() {
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
        // Armed: the heartbeat no longer gates probing, so a connection acquired a
        // millisecond later is still checked.
        assert!(g.should_probe(t0 + Duration::from_millis(1)));
    }

    #[test]
    fn disarms_only_after_consecutive_clean_probes() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);

        g.record_clean(t0);
        assert!(g.should_probe(t0), "one clean probe is not enough");
        g.record_clean(t0);
        assert!(g.should_probe(t0));
        g.record_clean(t0);

        // Disarmed, so the heartbeat gates probing again.
        assert!(!g.should_probe(t0 + Duration::from_secs(1)));
    }

    #[test]
    fn a_reader_resets_progress_toward_disarming() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);
        g.record_clean(t0);
        g.record_clean(t0);

        // Two clean probes in, one short of disarming, and another reader appears.
        g.record_read_only(t0);
        g.record_clean(t0);
        g.record_clean(t0);
        assert!(
            g.should_probe(t0 + Duration::from_secs(1)),
            "the count restarted, so the guard is still armed"
        );
    }

    #[test]
    fn stops_discarding_connections_once_the_cap_is_spent() {
        let g = guard(); // cap of 2 per 60s window
        let t0 = Instant::now();

        assert!(g.record_read_only(t0));
        assert!(g.record_read_only(t0));
        assert!(
            !g.record_read_only(t0),
            "every replacement is a reader too, so stop churning and let writes fail"
        );

        // The window rolls over and the guard is willing to try again.
        assert!(g.record_read_only(t0 + Duration::from_secs(60)));
    }

    #[test]
    fn cap_does_not_stop_the_guard_probing() {
        let g = guard();
        let t0 = Instant::now();
        g.record_read_only(t0);
        g.record_read_only(t0);
        g.record_read_only(t0); // capped

        assert!(
            g.should_probe(t0),
            "still probing, so recovery is noticed as soon as a writer answers"
        );
    }

    #[test]
    fn error_class_separates_a_failover_from_ordinary_write_failures() {
        // The point of the label: a read-only refusal must not be lumped in with the
        // failures propdefs already sees routinely.
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
        assert!(!is_read_only_error(&SqlxError::RowNotFound));
        // Only the SQLSTATE counts. Matching the message text would let any error carrying
        // that phrase masquerade as a failover.
        assert!(!is_read_only_error(&SqlxError::Protocol(
            "cannot execute INSERT in a read-only transaction".to_string()
        )));
    }
}
