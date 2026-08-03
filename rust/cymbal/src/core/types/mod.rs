//! Shared exception/stacktrace domain types used by both run modes. The
//! processing event model (`RawExceptionProperties`, `ProcessedExceptionProperties`, the pipeline
//! `Batch`/`Operator` types) lives in `crate::modes::processing::types`.

use serde::{Deserialize, Serialize};

pub mod exception;
pub mod frames;
pub mod langs;
pub mod notification;
pub mod stacktrace;

pub use exception::*;
pub use stacktrace::*;

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Mechanism {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub handled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(rename = "type")]
    pub mechanism_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub synthetic: Option<bool>,
    /// Position of this exception in the `$exception_list` chain the SDK emitted,
    /// `0` being the outermost error. Only set for multi-exception chains.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exception_id: Option<u32>,
    /// `exception_id` of the exception this one is the cause of. Ids stay attached
    /// to their exception, so wire-order normalization does not invalidate them.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<u32>,
}
