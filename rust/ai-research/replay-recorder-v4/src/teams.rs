//! The teams that may be recorded: the replay teams of organizations that opt in to AI training.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;

use arc_swap::ArcSwap;
use sqlx::PgPool;

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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Team {
    pub id: i64,
    pub ai_training_opted_in: bool,
}

/// Teams by project token. Lookups read a snapshot, so the consume loop never waits on Postgres.
#[derive(Default)]
pub struct TeamCache {
    teams: ArcSwap<HashMap<String, Team>>,
    failed_refreshes: AtomicU32,
}

impl TeamCache {
    pub fn from_teams(teams: HashMap<String, Team>) -> Self {
        Self {
            teams: ArcSwap::from_pointee(teams),
            failed_refreshes: AtomicU32::new(0),
        }
    }

    pub fn get(&self, token: &str) -> Option<Team> {
        if self.failed_refreshes.load(Ordering::Relaxed) >= MAX_FAILED_REFRESHES {
            return None;
        }
        self.teams.load().get(token).copied()
    }

    /// Counts a failed refresh. Returns true when the cache now admits no team.
    pub fn refresh_failed(&self) -> bool {
        let failures = self.failed_refreshes.fetch_add(1, Ordering::Relaxed) + 1;
        let closed = failures >= MAX_FAILED_REFRESHES;
        metrics::gauge!("replay_recorder_v4_teams_closed").set(if closed { 1.0 } else { 0.0 });
        closed
    }

    fn store(&self, teams: HashMap<String, Team>) {
        self.teams.store(Arc::new(teams));
        self.failed_refreshes.store(0, Ordering::Relaxed);
        metrics::gauge!("replay_recorder_v4_teams_closed").set(0.0);
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
        metrics::gauge!("replay_recorder_v4_teams").set(count as f64);
        Ok(count)
    }

    /// Refreshes forever. A failed refresh keeps the previous list until `MAX_FAILED_REFRESHES` fail in a row, then
    /// the cache admits no team until a refresh succeeds.
    pub async fn refresh_every(self: Arc<Self>, pool: PgPool, interval: Duration) {
        let mut ticker = tokio::time::interval(interval);
        ticker.tick().await;
        loop {
            ticker.tick().await;
            if let Err(error) = self.refresh(&pool).await {
                metrics::counter!("replay_recorder_v4_team_refresh_failures_total").increment(1);
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
        let cache = TeamCache::from_teams(teams.clone());
        for _ in 1..MAX_FAILED_REFRESHES {
            assert!(!cache.refresh_failed());
        }
        assert_eq!(cache.get("token"), Some(team));
        assert!(cache.refresh_failed());
        assert_eq!(cache.get("token"), None);

        cache.store(teams);
        assert_eq!(cache.get("token"), Some(team));
    }
}
