use chrono::Utc;
use cyclotron_core::{
    delete_completed_jobs, delete_failed_jobs, delete_poison_pills, reset_stalled_jobs, QueueError,
};
use sqlx::PgPool;
use tracing::{info, warn};

use crate::config::{JanitorConfig, JanitorSettings};

// The janitor reports it's own metrics, this is mostly for testing purposes
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CleanupResult {
    pub completed: u64,
    pub failed: u64,
    pub poisoned: u64,
    pub stalled: u64,
}

pub struct Janitor {
    pool: PgPool,
    settings: JanitorSettings,
    metrics_labels: Vec<(&'static str, String)>,
}

impl Janitor {
    pub async fn new(config: JanitorConfig) -> Result<Self, QueueError> {
        let settings = config.settings;
        let pool = config.pool.connect().await?;

        let metrics_labels = vec![("janitor_id", settings.id.clone())];

        Ok(Self {
            pool,
            settings,
            metrics_labels,
        })
    }

    pub fn from_pool(pool: PgPool, settings: JanitorSettings) -> Self {
        let metrics_labels = vec![("janitor_id", settings.id.clone())];
        Self {
            pool,
            settings,
            metrics_labels,
        }
    }

    // TODO - right now, the metrics produced here are pretty rough - just per shard, without
    // any per-queue or per-worker-type breakdown. It'd be nice to add that, eventually.
    pub async fn run_once(&self) -> Result<CleanupResult, QueueError> {
        info!("Running janitor loop");
        let start = Utc::now();
        metrics::counter!("cyclotron_janitor_run_starts", &self.metrics_labels).increment(1);

        let before = Utc::now();
        let completed = delete_completed_jobs(&self.pool).await?;
        let taken = Utc::now() - before;
        metrics::histogram!(
            "cyclotron_janitor_completed_jobs_cleanup_duration_ms",
            &self.metrics_labels
        )
        .record(taken.num_milliseconds() as f64);
        metrics::counter!(
            "cyclotron_janitor_completed_jobs_deleted",
            &self.metrics_labels
        )
        .increment(completed);

        let before = Utc::now();
        let failed = delete_failed_jobs(&self.pool).await?;
        let taken = Utc::now() - before;
        metrics::histogram!(
            "cyclotron_janitor_failed_jobs_cleanup_duration_ms",
            &self.metrics_labels
        )
        .record(taken.num_milliseconds() as f64);
        metrics::counter!(
            "cyclotron_janitor_failed_jobs_deleted",
            &self.metrics_labels
        )
        .increment(failed);

        // Note - if we reset stalled jobs before deleting poison pills, we'll never delete poision
        // pills, since resetting a stalled job clears the locked state.
        let before = Utc::now();
        let poisoned = delete_poison_pills(
            &self.pool,
            self.settings.stall_timeout,
            self.settings.max_touches,
        )
        .await?;
        let taken: chrono::Duration = Utc::now() - before;
        metrics::histogram!(
            "cyclotron_janitor_poison_pills_cleanup_duration_ms",
            &self.metrics_labels
        )
        .record(taken.num_milliseconds() as f64);
        metrics::counter!(
            "cyclotron_janitor_poison_pills_deleted",
            &self.metrics_labels
        )
        .increment(poisoned);
        if poisoned > 0 {
            warn!("Deleted {} poison pills", poisoned);
        }

        let before = Utc::now();
        let stalled = reset_stalled_jobs(&self.pool, self.settings.stall_timeout).await?;
        let taken = Utc::now() - before;
        metrics::histogram!(
            "cyclotron_janitor_stalled_jobs_reset_duration_ms",
            &self.metrics_labels
        )
        .record(taken.num_milliseconds() as f64);
        metrics::counter!("cyclotron_janitor_stalled_jobs_reset", &self.metrics_labels)
            .increment(stalled);
        if stalled > 0 {
            warn!("Reset {} stalled jobs", stalled);
        }

        metrics::counter!("cyclotron_janitor_run_ends", &self.metrics_labels).increment(1);
        let elapsed = Utc::now() - start;
        metrics::histogram!("cyclotron_janitor_run_duration_ms", &self.metrics_labels)
            .record(elapsed.num_milliseconds() as f64);
        info!("Janitor loop complete");
        Ok(CleanupResult {
            completed,
            failed,
            poisoned,
            stalled,
        })
    }
}
