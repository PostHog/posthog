use std::time::Instant;

use super::{CheckpointPlan, CheckpointUploader, UploadCancelledError};
use crate::metrics_const::{CHECKPOINT_UPLOADS_COUNTER, CHECKPOINT_UPLOAD_DURATION_HISTOGRAM};

use anyhow::Result;
use metrics;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

#[derive(Debug)]
pub struct CheckpointExporter {
    uploader: Box<dyn CheckpointUploader>,
}

impl CheckpointExporter {
    pub fn new(uploader: Box<dyn CheckpointUploader>) -> Self {
        Self { uploader }
    }

    /// Export checkpoint using a plan with incremental deduplication - legacy non-cancellable
    pub async fn export_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<()> {
        self.export_checkpoint_with_plan_cancellable(plan, None, None)
            .await
    }

    /// Export checkpoint with cancellation support.
    /// If cancel_token is provided and cancelled during upload, returns an error early.
    /// Cancellation is NOT treated as an error for metrics/logging purposes.
    ///
    /// The optional `cancel_cause` is used for metrics when the upload is cancelled.
    /// Use "rebalance" when cancelled due to a Kafka rebalance (to free S3 bandwidth for imports).
    /// Use "shutdown" when cancelled due to service shutdown.
    pub async fn export_checkpoint_with_plan_cancellable(
        &self,
        plan: &CheckpointPlan,
        cancel_token: Option<&CancellationToken>,
        cancel_cause: Option<&str>,
    ) -> Result<()> {
        if !self.is_available().await {
            metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "unavailable").increment(1);
            warn!(
                remote_metadata_path = plan.info.get_metadata_key(),
                "Export failed: uploader not available"
            );
            return Err(anyhow::anyhow!("Uploader not available"));
        }

        let upload_start = Instant::now();

        match self
            .uploader
            .upload_checkpoint_with_plan_cancellable(plan, cancel_token)
            .await
        {
            Ok(uploaded_files) => {
                let upload_duration = upload_start.elapsed();
                let total_files = plan.info.metadata.files.len();
                let new_files = plan.files_to_upload.len();
                let reused_files = total_files - new_files;

                metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, "result" => "success")
                    .record(upload_duration.as_secs_f64());
                metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "success").increment(1);

                info!(
                    remote_path = plan.info.get_metadata_key(),
                    uploaded_file_count = uploaded_files.len(),
                    total_files = total_files,
                    new_files = new_files,
                    reused_files = reused_files,
                    elapsed_seconds = upload_duration.as_secs_f64(),
                    "Export successful: checkpoint uploaded with deduplication",
                );

                Ok(())
            }

            Err(e) => {
                let upload_duration = upload_start.elapsed();
                // Cancellation is NOT an error - metrics only (s3_uploader already logged the detail)
                if e.downcast_ref::<UploadCancelledError>().is_some() {
                    // Map cause to static strings for metrics (metrics library requires 'static)
                    let cause: &'static str = match cancel_cause {
                        Some("rebalance") => "rebalance",
                        Some("shutdown") => "shutdown",
                        _ => "unknown",
                    };
                    metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, "result" => "cancelled", "cause" => cause)
                        .record(upload_duration.as_secs_f64());
                    metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "cancelled", "cause" => cause)
                        .increment(1);
                } else {
                    metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, "result" => "error")
                        .record(upload_duration.as_secs_f64());
                    metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "error").increment(1);
                    error!(
                        remote_path = plan.info.get_metadata_key(),
                        elapsed_seconds = upload_duration.as_secs_f64(),
                        "Export failed: uploading checkpoint: {}",
                        e
                    );
                }
                Err(e)
            }
        }
    }

    pub async fn is_available(&self) -> bool {
        self.uploader.is_available().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use chrono::{TimeZone, Utc};

    use crate::checkpoint::{CheckpointInfo, CheckpointMetadata, UploadCancelledError};

    /// Mock uploader for testing cancellation detection
    #[derive(Debug)]
    struct MockUploader {
        should_return_cancelled: bool,
        should_return_error: bool,
    }

    impl MockUploader {
        fn new_success() -> Self {
            Self {
                should_return_cancelled: false,
                should_return_error: false,
            }
        }

        fn new_cancelled() -> Self {
            Self {
                should_return_cancelled: true,
                should_return_error: false,
            }
        }

        fn new_error() -> Self {
            Self {
                should_return_cancelled: false,
                should_return_error: true,
            }
        }
    }

    #[async_trait]
    impl CheckpointUploader for MockUploader {
        async fn upload_checkpoint_with_plan_cancellable(
            &self,
            _plan: &CheckpointPlan,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<Vec<String>> {
            if self.should_return_cancelled {
                Err(UploadCancelledError {
                    reason: "test".to_string(),
                }
                .into())
            } else if self.should_return_error {
                Err(anyhow::anyhow!("S3 error: connection failed"))
            } else {
                Ok(vec!["test/key".to_string()])
            }
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    fn create_test_plan() -> CheckpointPlan {
        let timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();
        let metadata =
            CheckpointMetadata::new("test-topic".to_string(), 0, timestamp, 12345, 100, 50);
        let info = CheckpointInfo::new(metadata, "checkpoints".to_string(), None);
        CheckpointPlan {
            info,
            files_to_upload: vec![],
        }
    }

    #[tokio::test]
    async fn test_export_success() {
        let uploader = Box::new(MockUploader::new_success());
        let exporter = CheckpointExporter::new(uploader);
        let plan = create_test_plan();

        let result = exporter
            .export_checkpoint_with_plan_cancellable(&plan, None, None)
            .await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_export_cancelled_returns_error_with_cancelled_message() {
        let uploader = Box::new(MockUploader::new_cancelled());
        let exporter = CheckpointExporter::new(uploader);
        let plan = create_test_plan();

        let result = exporter
            .export_checkpoint_with_plan_cancellable(&plan, None, Some("rebalance"))
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<UploadCancelledError>().is_some(),
            "Error should be UploadCancelledError: {}",
            err
        );
    }

    #[tokio::test]
    async fn test_export_error_returns_error_without_cancelled_type() {
        let uploader = Box::new(MockUploader::new_error());
        let exporter = CheckpointExporter::new(uploader);
        let plan = create_test_plan();

        let result = exporter
            .export_checkpoint_with_plan_cancellable(&plan, None, None)
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<UploadCancelledError>().is_none(),
            "Error should NOT be UploadCancelledError: {}",
            err
        );
    }
}
