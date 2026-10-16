//! Sentinel error types for the durability layer.
//!
//! Plain `std::error::Error` structs so callers can thread them through `anyhow::Error` and recover
//! them with `downcast_ref::<T>()` to distinguish a cancellation (metrics only, not a real failure)
//! from a genuine error.

use std::fmt;

/// An upload was cancelled (e.g. rebalance or shutdown). Detect via `downcast_ref::<Self>()`.
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

/// A download was cancelled (e.g. rebalance or shutdown). Detect via `downcast_ref::<Self>()`.
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

/// Checkpoint planning was cancelled before upload started. Detect via `downcast_ref::<Self>()`.
#[derive(Debug)]
pub struct PlanningCancelledError {
    pub reason: String,
}

impl fmt::Display for PlanningCancelledError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Checkpoint planning cancelled: {}", self.reason)
    }
}

impl std::error::Error for PlanningCancelledError {}
