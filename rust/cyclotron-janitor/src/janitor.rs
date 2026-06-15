use cyclotron_core::{QueueError, SHARD_ID_KEY};
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
    pub canceled: u64,
    pub poisoned: u64,
    pub stalled: u64,
}

pub struct Janitor {
    pub inner: cyclotron_core::Janitor,
    pub settings: JanitorSettings,
    pub metrics_labels: Vec<(String, String)>,
}

impl Janitor {
    pub async fn new(config: JanitorConfig) -> Result<Self, QueueError> {
        let settings = config.settings;
        let inner = cyclotron_core::Janitor::new(config.pool).await?;

        let metrics_labels = vec![
            ("janitor_id".to_string(), settings.id.clone()),
            (SHARD_ID_KEY.to_string(), settings.shard_id.clone()),
        ];

        Ok(Self {
            inner,
            settings,
            metrics_labels,
        })
    }

    pub async fn run_once(&self) -> Result<CleanupResult, QueueError> {
        info!("Running janitor loop");
        let _loop_start = common_metrics::timing_guard(RUN_TIME, &self.metrics_labels);
        common_metrics::inc(RUN_STARTS, &self.metrics_labels, 1);

        let aggregated_deletes = {
            let _time = common_metrics::timing_guard(CLEANUP_TIME, &self.metrics_labels);
            self.inner.delete_completed_and_failed_jobs().await?
        };

        let mut completed_count = 0u64;
        let mut failed_count = 0u64;
        let mut canceled_count = 0u64;
        for delete in &aggregated_deletes {
            if delete.state == "completed" {
                completed_count += delete.count as u64;
            } else if delete.state == "failed" {
                failed_count += delete.count as u64;
            } else if delete.state == "canceled" {
                canceled_count += delete.count as u64;
            }
        }
        common_metrics::inc(COMPLETED_COUNT, &self.metrics_labels, completed_count);
        common_metrics::inc(FAILED_COUNT, &self.metrics_labels, failed_count);
        common_metrics::inc(CANCELED_COUNT, &self.metrics_labels, canceled_count);

        let poisoned = {
            let _time = common_metrics::timing_guard(POISONED_TIME, &self.metrics_labels);
            self.inner
                .delete_poison_pills(self.settings.stall_timeout, self.settings.max_touches)
                .await?
        };
        common_metrics::inc(POISONED_COUNT, &self.metrics_labels, poisoned);

        if poisoned > 0 {
            warn!("Deleted {} poison pills", poisoned);
        }

        let stalled = {
            let _time = common_metrics::timing_guard(STALLED_TIME, &self.metrics_labels);
            self.inner
                .reset_stalled_jobs(self.settings.stall_timeout)
                .await?
        };
        common_metrics::inc(STALLED_COUNT, &self.metrics_labels, stalled);

        if stalled > 0 {
            warn!("Reset {} stalled jobs", stalled);
        }

        let available = {
            let _time = common_metrics::timing_guard(AVAILABLE_DEPTH_TIME, &self.metrics_labels);
            self.inner.waiting_jobs().await?
        };

        let mut available_labels = self.metrics_labels.clone();
        for (count, queue_name) in available {
            available_labels.push(("queue_name".to_string(), queue_name));
            common_metrics::gauge(AVAILABLE_DEPTH, &available_labels, count as f64);
            available_labels.pop();
        }

        let dlq_depth = {
            let _time = common_metrics::timing_guard(DLQ_DEPTH_TIME, &self.metrics_labels);
            self.inner.count_dlq_depth().await?
        };
        common_metrics::gauge(DLQ_DEPTH, &self.metrics_labels, dlq_depth as f64);

        common_metrics::inc(RUN_ENDS, &self.metrics_labels, 1);
        info!("Janitor loop complete");
        Ok(CleanupResult {
            completed: completed_count,
            failed: failed_count,
            canceled: canceled_count,
            poisoned,
            stalled,
        })
    }
}
