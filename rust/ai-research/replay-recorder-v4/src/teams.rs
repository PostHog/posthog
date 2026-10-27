//! The teams that may be recorded: the replay teams of organizations that opt in to AI training.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;

use arc_swap::ArcSwap;
use sqlx::PgPool;
use tokio::time::Instant;

/// The query the v3 mirror's team service runs, narrowed to the columns v4 reads. The main lane drops a team without
/// a valid retention period, so the list leaves it out.
const TEAMS: &str = "
    SELECT t.id::bigint, t.api_token, COALESCE(o.is_ai_training_opted_in, false)
    FROM posthog_team t
    LEFT JOIN posthog_organization o ON o.id = t.organization_id
    WHERE t.session_recording_opt_in = true
      AND t.session_recording_retention_period IN ('30d', '90d', '1y', '5y')
";

/// After this many failed refreshes in a row the list is too old to show opt-outs, so the cache admits no team.
pub const MAX_FAILED_REFRESHES: u32 = 20;

/// A refresh that takes longer fails. Without it a hung query would never count as a failure.
pub const REFRESH_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Team {
    pub id: i64,
    pub ai_training_opted_in: bool,
}

struct Snapshot {
    teams: HashMap<String, Team>,
    loaded_at: Instant,
}

/// Teams by project token. Lookups read a snapshot, so the consume loop never waits on Postgres.
pub struct TeamCache {
    snapshot: ArcSwap<Snapshot>,
    failed_refreshes: AtomicU32,
    max_age: Duration,
}

impl Default for TeamCache {
    fn default() -> Self {
        Self::from_teams(HashMap::new(), Duration::MAX)
    }
}

impl TeamCache {
    pub fn new(max_age: Duration) -> Self {
        Self::from_teams(HashMap::new(), max_age)
    }

    pub fn from_teams(teams: HashMap<String, Team>, max_age: Duration) -> Self {
        Self {
            snapshot: ArcSwap::from_pointee(Snapshot {
                teams,
                loaded_at: Instant::now(),
            }),
            failed_refreshes: AtomicU32::new(0),
            max_age,
        }
    }

    /// The age at which a refreshing cache admits no team: as long as `MAX_FAILED_REFRESHES` intervals that time out.
    pub fn max_age_for(interval: Duration) -> Duration {
        (interval + REFRESH_TIMEOUT) * MAX_FAILED_REFRESHES
    }

    pub fn get(&self, token: &str) -> Option<Team> {
        if self.failed_refreshes.load(Ordering::Relaxed) >= MAX_FAILED_REFRESHES {
            return None;
        }
        let snapshot = self.snapshot.load();
        if snapshot.loaded_at.elapsed() > self.max_age {
            return None;
        }
        snapshot.teams.get(token).copied()
    }

    /// Counts a failed refresh. Returns true when the cache now admits no team.
    pub fn refresh_failed(&self) -> bool {
        let failures = self.failed_refreshes.fetch_add(1, Ordering::Relaxed) + 1;
        let closed = failures >= MAX_FAILED_REFRESHES;
        metrics::gauge!("ai_research_v4_recorder_teams_closed").set(if closed { 1.0 } else { 0.0 });
        closed
    }

    fn store(&self, teams: HashMap<String, Team>) {
        self.snapshot.store(Arc::new(Snapshot {
            teams,
            loaded_at: Instant::now(),
        }));
        self.failed_refreshes.store(0, Ordering::Relaxed);
        metrics::gauge!("ai_research_v4_recorder_teams_closed").set(0.0);
    }

    pub async fn refresh(&self, pool: &PgPool) -> Result<usize, sqlx::Error> {
        let rows: Vec<(i64, String, bool)> = sqlx::query_as(TEAMS).fetch_all(pool).await?;
        let teams: HashMap<String, Team> = rows
            .into_iter()
            .map(|(id, token, opted_in)| {
                (
                    token,
                    Team {
                        id,
                        ai_training_opted_in: opted_in,
                    },
                )
            })
            .collect();
        let count = teams.len();
        self.store(teams);
        metrics::gauge!("ai_research_v4_recorder_teams").set(count as f64);
        Ok(count)
    }

    /// Refreshes until shutdown. A failed or timed-out refresh keeps the previous list until `MAX_FAILED_REFRESHES` fail
    /// in a row, then the cache admits no team until a refresh succeeds. If this task ends early or panics, the process
    /// stops.
    pub async fn refresh_every(
        self: Arc<Self>,
        pool: PgPool,
        interval: Duration,
        handle: lifecycle::Handle,
    ) {
        let _guard = handle.process_scope();
        let shutdown = handle.shutdown_signal();
        tokio::pin!(shutdown);
        let mut ticker = tokio::time::interval(interval);
        ticker.tick().await;
        loop {
            tokio::select! {
                _ = &mut shutdown => return,
                _ = ticker.tick() => {}
            }
            let refreshed = match tokio::time::timeout(REFRESH_TIMEOUT, self.refresh(&pool)).await {
                Ok(result) => result.map_err(|error| error.to_string()),
                Err(_) => Err(format!("no answer in {REFRESH_TIMEOUT:?}")),
            };
            metrics::gauge!("ai_research_v4_recorder_team_snapshot_age_seconds")
                .set(self.snapshot.load().loaded_at.elapsed().as_secs_f64());
            if let Err(error) = refreshed {
                metrics::counter!("ai_research_v4_recorder_team_refresh_failures_total")
                    .increment(1);
                if self.refresh_failed() {
                    tracing::error!(%error, "team refreshes keep failing: admitting no team until one succeeds");
                } else {
                    tracing::warn!(%error, "team refresh failed");
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn admits_nothing_after_too_many_failed_refreshes_until_one_succeeds() {
        let team = Team {
            id: 7,
            ai_training_opted_in: true,
        };
        let teams = HashMap::from([("token".to_owned(), team)]);
        let cache = TeamCache::from_teams(teams.clone(), Duration::MAX);
        for _ in 1..MAX_FAILED_REFRESHES {
            assert!(!cache.refresh_failed());
        }
        assert_eq!(cache.get("token"), Some(team));
        assert!(cache.refresh_failed());
        assert_eq!(cache.get("token"), None);

        cache.store(teams);
        assert_eq!(cache.get("token"), Some(team));
    }

    #[test]
    fn admits_nothing_once_the_snapshot_is_too_old_until_a_refresh_succeeds() {
        let team = Team {
            id: 7,
            ai_training_opted_in: true,
        };
        let teams = HashMap::from([("token".to_owned(), team)]);
        let max_age = TeamCache::max_age_for(Duration::from_secs(300));
        let cache = TeamCache::from_teams(teams.clone(), max_age);
        assert_eq!(cache.get("token"), Some(team));

        cache.snapshot.store(Arc::new(Snapshot {
            teams: teams.clone(),
            loaded_at: Instant::now() - max_age - Duration::from_secs(1),
        }));
        assert_eq!(cache.get("token"), None);

        cache.store(teams);
        assert_eq!(cache.get("token"), Some(team));
    }
}
