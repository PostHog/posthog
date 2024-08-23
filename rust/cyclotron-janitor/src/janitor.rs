use cyclotron_core::{
    delete_completed_jobs, delete_failed_jobs, delete_poison_pills, reset_stalled_jobs, QueueError,
    SHARD_ID_KEY,
};
use sqlx::PgPool;
use tracing::{info, warn};

use crate::{
    config::{JanitorConfig, JanitorSettings},
    metrics_constants::*,
};

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
    metrics_labels: Vec<(String, String)>,
}

impl Janitor {
    pub async fn new(config: JanitorConfig) -> Result<Self, QueueError> {
        let settings = config.settings;
        let pool = config.pool.connect().await?;

        let metrics_labels = vec![
            ("janitor_id".to_string(), settings.id.clone()),
            (SHARD_ID_KEY.to_string(), settings.shard_id.clone()),
        ];

        Ok(Self {
            pool,
            settings,
            metrics_labels,
        })
    }

    #[doc(hidden)]
    pub async fn from_pool(pool: PgPool, settings: JanitorSettings) -> Self {
        let metrics_labels = vec![
            ("janitor_id".to_string(), settings.id.clone()),
            (SHARD_ID_KEY.to_string(), settings.shard_id.clone()),
        ];

        Self {
            pool,
            settings,
            metrics_labels,
        }
    }

    pub async fn run_once(&self) -> Result<CleanupResult, QueueError> {
        info!("Running janitor loop");
        let _loop_start = common_metrics::timing_guard(RUN_TIME, &self.metrics_labels);
        common_metrics::inc(RUN_STARTS, &self.metrics_labels, 1);

        let completed = {
            let _time = common_metrics::timing_guard(COMPLETED_TIME, &self.metrics_labels);
            delete_completed_jobs(&self.pool).await?
        };
        common_metrics::inc(COMPLETED_COUNT, &self.metrics_labels, completed);

        let failed = {
            let _time = common_metrics::timing_guard(FAILED_TIME, &self.metrics_labels);
            delete_failed_jobs(&self.pool).await?
        };
        common_metrics::inc(FAILED_COUNT, &self.metrics_labels, failed);

        let poisoned = {
            let _time = common_metrics::timing_guard(POISONED_TIME, &self.metrics_labels);
            delete_poison_pills(
                &self.pool,
                self.settings.stall_timeout,
                self.settings.max_touches,
            )
            .await?
        };
        common_metrics::inc(POISONED_COUNT, &self.metrics_labels, poisoned);

        if poisoned > 0 {
            warn!("Deleted {} poison pills", poisoned);
        }

        let stalled = {
            let _time = common_metrics::timing_guard(STALLED_TIME, &self.metrics_labels);
            reset_stalled_jobs(&self.pool, self.settings.stall_timeout).await?
        };
        common_metrics::inc(STALLED_COUNT, &self.metrics_labels, stalled);

        if stalled > 0 {
            warn!("Reset {} stalled jobs", stalled);
        }

        let available = {
            let _time = common_metrics::timing_guard(QUEUE_DEPTH, &self.metrics_labels);
            cyclotron_core::count_total_waiting_jobs(&self.pool).await?
        };
        common_metrics::gauge(QUEUE_DEPTH, &self.metrics_labels, available as f64);

        common_metrics::inc(RUN_ENDS, &self.metrics_labels, 1);
        info!("Janitor loop complete");
        Ok(CleanupResult {
            completed,
            failed,
            poisoned,
            stalled,
        })
    }
}
