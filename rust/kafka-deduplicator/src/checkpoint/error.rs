use std::fmt;

/// Error indicating an upload operation was cancelled (e.g., due to rebalance or shutdown).
/// Use anyhow's downcast_ref::<UploadCancelledError>() to detect this error type.
#[derive(Debug)]
pub struct UploadCancelledError {
    pub reason: String,
}

impl fmt::Display for UploadCancelledError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Upload cancelled: {}", self.reason)
    }
}

impl std::error::Error for UploadCancelledError {}

/// Error indicating a download operation was cancelled (e.g., due to rebalance or shutdown).
/// Use anyhow's downcast_ref::<DownloadCancelledError>() to detect this error type.
#[derive(Debug)]
pub struct DownloadCancelledError {
    pub reason: String,
}

impl fmt::Display for DownloadCancelledError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Download cancelled: {}", self.reason)
    }
}

impl std::error::Error for DownloadCancelledError {}

/// Error indicating a checkpoint import operation timed out.
/// This prevents exceeding Kafka's max poll interval during long imports.
/// Use anyhow's downcast_ref::<ImportTimeoutError>() to detect this error type.
#[derive(Debug)]
pub struct ImportTimeoutError {
    pub topic: String,
    pub partition: i32,
    pub timeout_secs: u64,
}

impl fmt::Display for ImportTimeoutError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Checkpoint import timed out after {}s for {}:{}",
            self.timeout_secs, self.topic, self.partition
        )
    }
}

impl std::error::Error for ImportTimeoutError {}
