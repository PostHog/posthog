//! Shared exception/stacktrace domain types used by both run modes. The
//! processing event model (`RawErrProps`, `OutputErrProps`, the pipeline
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
}
