//! Which teams the realtime cohort pipeline processes.
//!
//! A team processes when `REALTIME_COHORT_TEAM_ALLOWLIST` names it, or when its row in Django's
//! `cohort_realtime_team_access` table is at `processing` or `serving`. [`TeamAccessPoller`] reads
//! the whole table on a short poll and swaps the rows into [`TeamAccess`], so a grant or a revoke
//! reaches every reader within one poll, and the per-event check never waits on a lock.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use arc_swap::ArcSwapOption;
use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::gauge;
use rand::Rng;
use sqlx::PgPool;
use thiserror::Error;
use tracing::{debug, warn};

/// A transaction-mode PgBouncer does not keep the session `statement_timeout` that
/// `common-database` sets after connect. So each read sets its own timeout inside its transaction,
/// and the server cancels a blocked read instead of holding a pool connection.
const QUERY_TIMEOUT_SQL: &str = "SET LOCAL statement_timeout = '5s'";
const ACCESS_ROWS_SQL: &str = "SELECT team_id, level FROM cohort_realtime_team_access";

/// Bounds the whole poll on the client. The statement timeout stops only the server, so a socket
/// that dies after the pool hands it out would otherwise hang the poll and freeze every grant and
/// revoke. Longer than the statement timeout, so the server cancels a slow read first.
const POLL_TIMEOUT: Duration = Duration::from_secs(10);

const POLL_INTERVAL: Duration = Duration::from_secs(15);
const POLL_JITTER: Duration = Duration::from_secs(3);

/// Zero until the first poll succeeds, then set only when a poll succeeds. So a staleness alert
/// covers a reader that never loaded, and failed polls, including those that keep a regressed row.
/// The charts allowlist of metrics that alerts can read matches the `posthog_cohort_` prefix.
const LAST_SUCCESS: &str = "posthog_cohort_team_access_last_success_timestamp_seconds";

#[derive(Debug, Error)]
pub enum PollError {
    #[error("querying cohort_realtime_team_access failed: {0}")]
    Query(#[from] sqlx::Error),
    #[error("reading cohort_realtime_team_access timed out")]
    TimedOut(#[from] tokio::time::error::Elapsed),
    #[error("team {team_id} has the unknown level {level:?}")]
    UnknownLevel { team_id: i32, level: String },
    /// Such a read is wrong: an empty table, another database, or a replica that lags behind the
    /// previous read. See [`Level::may_become`]. These teams keep their previous rows, and the
    /// read's other rows still take effect, so a revoke reaches the reader even then.
    #[error("the read lacks the rows of teams {0:?}, or grants them again after `off`, so they keep their previous rows")]
    RegressedRows(Vec<i32>),
}

/// The levels of `RealtimeCohortLevel` in `products/cohorts/backend/models/team_access.py`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Level {
    Off,
    Processing,
    Serving,
}

impl Level {
    fn parse(level: &str) -> Option<Self> {
        match level {
            "off" => Some(Self::Off),
            "processing" => Some(Self::Processing),
            "serving" => Some(Self::Serving),
            _ => None,
        }
    }

    fn processes(self) -> bool {
        match self {
            Self::Off => false,
            Self::Processing | Self::Serving => true,
        }
    }

    /// Whether a later read may show this row at `next`. Django never deletes a row, and it refuses
    /// to grant an `off` row again, so only a wrong read shows either change.
    fn may_become(self, next: Option<Self>) -> bool {
        match (self, next) {
            (_, None) => false,
            (Self::Off, Some(Self::Off)) => true,
            (Self::Off, Some(Self::Processing | Self::Serving)) => false,
            (Self::Processing | Self::Serving, Some(_)) => true,
        }
    }
}

/// Every row of one read, `off` rows included, because the poller checks the next read against them.
#[derive(Debug)]
struct AccessRows(HashMap<i32, Level>);

impl AccessRows {
    fn parse(rows: Vec<(i32, String)>) -> Result<Self, PollError> {
        rows.into_iter()
            .map(|(team_id, level)| match Level::parse(&level) {
                Some(parsed) => Ok((team_id, parsed)),
                None => Err(PollError::UnknownLevel { team_id, level }),
            })
            .collect::<Result<_, _>>()
            .map(Self)
    }

    fn processes(&self, team_id: i32) -> bool {
        self.0.get(&team_id).is_some_and(|level| level.processes())
    }

    fn granted(&self) -> usize {
        self.0.values().filter(|level| level.processes()).count()
    }

    /// Puts back the `previous` row of each team whose row here is a change that
    /// [`Level::may_become`] rules out, and returns those teams.
    fn restore_regressed(&mut self, previous: &Self) -> Vec<i32> {
        let mut regressed = Vec::new();
        for (&team_id, &level) in &previous.0 {
            if !level.may_become(self.0.get(&team_id).copied()) {
                self.0.insert(team_id, level);
                regressed.push(team_id);
            }
        }
        regressed.sort_unstable();
        regressed
    }
}

/// Answers whether a team processes, from the rows the poller stored last.
#[derive(Debug)]
pub struct TeamAccess {
    env: TeamAllowlist,
    /// `None` until the first accepted read. Until then no team processes, not even one the env list
    /// names: a reader that ran on the env list alone would treat every granted team as revoked.
    rows: ArcSwapOption<AccessRows>,
}

impl TeamAccess {
    pub fn new(env: TeamAllowlist) -> (Arc<Self>, TeamAccessPoller) {
        gauge!(LAST_SUCCESS).set(0.0);
        let access = Arc::new(Self {
            env,
            rows: ArcSwapOption::empty(),
        });
        let poller = TeamAccessPoller {
            access: access.clone(),
        };
        (access, poller)
    }

    /// A loaded reader whose one read granted `granted` at `processing`.
    #[cfg(feature = "test-util")]
    pub fn with_granted(env: TeamAllowlist, granted: impl IntoIterator<Item = i32>) -> Arc<Self> {
        let rows = granted
            .into_iter()
            .map(|team_id| (team_id, Level::Processing))
            .collect();
        Arc::new(Self {
            env,
            rows: ArcSwapOption::from_pointee(AccessRows(rows)),
        })
    }

    pub fn processing(&self, team_id: i32) -> bool {
        self.rows
            .load()
            .as_ref()
            .is_some_and(|rows| self.env.includes(team_id) || rows.processes(team_id))
    }

    pub fn is_loaded(&self) -> bool {
        self.rows.load().is_some()
    }
}

/// The only writer of its [`TeamAccess`]. It checks each read against the rows it stored last,
/// which is sound only while one poller swaps the rows, so it is not `Clone`.
#[derive(Debug)]
pub struct TeamAccessPoller {
    access: Arc<TeamAccess>,
}

impl TeamAccessPoller {
    /// Reads the table and swaps the rows in. Returns how many rows grant processing.
    ///
    /// # Errors
    ///
    /// Fails when the query fails or times out, or when a row has a level this crate does not know.
    /// The previous rows then stay in place. Also fails when the read lacks a row that the reader
    /// holds, or grants one of its `off` rows again. Only those teams keep their previous rows.
    /// So a row deleted or granted again by hand keeps its old state, and fails every later poll,
    /// until the service restarts.
    pub async fn poll(&mut self, pool: &PgPool) -> Result<usize, PollError> {
        let read = async {
            let mut transaction = pool.begin().await?;
            sqlx::query(QUERY_TIMEOUT_SQL)
                .execute(&mut *transaction)
                .await?;
            let fetched = sqlx::query_as::<_, (i32, String)>(ACCESS_ROWS_SQL)
                .fetch_all(&mut *transaction)
                .await?;
            transaction.commit().await?;
            Ok::<_, sqlx::Error>(fetched)
        };
        let fetched = tokio::time::timeout(POLL_TIMEOUT, read).await??;
        self.accept(AccessRows::parse(fetched)?)
    }

    fn accept(&mut self, mut read: AccessRows) -> Result<usize, PollError> {
        let regressed = match self.access.rows.load().as_deref() {
            Some(previous) => read.restore_regressed(previous),
            None => Vec::new(),
        };
        let granted = read.granted();
        self.access.rows.store(Some(Arc::new(read)));
        if !regressed.is_empty() {
            return Err(PollError::RegressedRows(regressed));
        }
        gauge!(LAST_SUCCESS).set(now_unix_seconds());
        Ok(granted)
    }

    /// Polls every `POLL_INTERVAL ± POLL_JITTER` until shutdown. After a failed poll it waits for
    /// the next tick.
    ///
    /// Register `handle` without a liveness deadline: a database outage must not stop a service that
    /// can keep working on the rows it has.
    pub async fn run(mut self, pool: PgPool, handle: Handle) {
        let _guard = handle.process_scope();

        loop {
            tokio::select! {
                _ = handle.shutdown_recv() => break,
                _ = tokio::time::sleep(next_interval()) => match self.poll(&pool).await {
                    Ok(granted) => debug!(granted_teams = granted, "team access polled"),
                    Err(err) => warn!(error = %err, "team access poll failed"),
                },
            }
        }
    }
}

/// The jitter spreads the polls of many pods over time.
fn next_interval() -> Duration {
    let max_jitter_ms = 2 * POLL_JITTER.as_millis() as u64;
    let jitter = Duration::from_millis(rand::thread_rng().gen_range(0..=max_jitter_ms));
    POLL_INTERVAL - POLL_JITTER + jitter
}

/// Seconds since the Unix epoch, saturating at 0 on a clock set before it.
fn now_unix_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|since| since.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rows(rows: &[(i32, &str)]) -> AccessRows {
        AccessRows::parse(
            rows.iter()
                .map(|&(team_id, level)| (team_id, level.to_string()))
                .collect(),
        )
        .unwrap()
    }

    fn env_only(teams: &[i32]) -> TeamAllowlist {
        TeamAllowlist::Only(teams.iter().copied().collect())
    }

    #[test]
    fn no_team_processes_before_the_first_accepted_read() {
        let (access, _poller) = TeamAccess::new(TeamAllowlist::All);

        assert!(!access.is_loaded());
        assert!(!access.processing(2));
    }

    #[test]
    fn processing_is_the_env_list_united_with_the_granted_rows() {
        let (access, mut poller) = TeamAccess::new(env_only(&[2, 3]));
        poller
            .accept(rows(&[
                (3, "off"),
                (5, "processing"),
                (6, "serving"),
                (7, "off"),
            ]))
            .unwrap();

        for (team_id, expected) in [
            (2, true),
            (3, true),
            (5, true),
            (6, true),
            (7, false),
            (8, false),
        ] {
            assert_eq!(access.processing(team_id), expected, "team {team_id}");
        }
    }

    #[test]
    fn a_read_that_lost_a_row_or_regranted_an_off_row_keeps_those_rows_and_applies_the_others() {
        let (access, mut poller) = TeamAccess::new(env_only(&[]));
        assert_eq!(poller.accept(rows(&[])).unwrap(), 0);
        assert!(access.is_loaded());
        poller
            .accept(rows(&[(5, "off"), (6, "processing"), (7, "processing")]))
            .unwrap();

        let regressed = poller.accept(rows(&[(5, "processing"), (6, "off"), (8, "processing")]));
        assert!(matches!(regressed, Err(PollError::RegressedRows(teams)) if teams == [5, 7]));
        for (team_id, expected) in [(5, false), (6, false), (7, true), (8, true)] {
            assert_eq!(access.processing(team_id), expected, "team {team_id}");
        }
    }

    #[test]
    fn a_read_that_changes_granted_levels_or_turns_every_row_off_is_accepted() {
        let (access, mut poller) = TeamAccess::new(env_only(&[]));
        poller
            .accept(rows(&[(5, "processing"), (6, "serving")]))
            .unwrap();
        poller
            .accept(rows(&[(5, "serving"), (6, "processing")]))
            .unwrap();

        assert_eq!(poller.accept(rows(&[(5, "off"), (6, "off")])).unwrap(), 0);
        assert!(!access.processing(5));
        assert!(!access.processing(6));
    }

    #[test]
    fn an_unknown_level_fails_the_read() {
        let parsed =
            AccessRows::parse(vec![(5, "processing".to_string()), (6, "beta".to_string())]);

        assert!(matches!(
            parsed,
            Err(PollError::UnknownLevel { team_id: 6, level }) if level == "beta"
        ));
    }
}
