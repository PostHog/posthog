//! Error helpers.
//!
//! Node steps signal retriability with an `isRetriable` property on the thrown error.
//! Here a step returns an `anyhow::Error` that wraps a `PipelineError`, and
//! `is_retriable` reads it from the error chain.

use std::fmt;
use std::sync::Arc;

#[derive(Debug, thiserror::Error)]
#[error("{message}")]
pub struct PipelineError {
    pub message: String,
    /// `Some(true)` retries, `Some(false)` goes to the DLQ, `None` retries and then crashes.
    pub retriable: Option<bool>,
}

impl PipelineError {
    pub fn retriable(message: impl Into<String>) -> anyhow::Error {
        anyhow::Error::new(Self {
            message: message.into(),
            retriable: Some(true),
        })
    }

    pub fn non_retriable(message: impl Into<String>) -> anyhow::Error {
        anyhow::Error::new(Self {
            message: message.into(),
            retriable: Some(false),
        })
    }
}

/// The Node `error.isRetriable` lookup.
pub fn is_retriable(error: &anyhow::Error) -> Option<bool> {
    for cause in error.chain() {
        if let Some(pipeline_error) = cause.downcast_ref::<PipelineError>() {
            return pipeline_error.retriable;
        }
        if let Some(shared) = cause.downcast_ref::<SharedError>() {
            return is_retriable(&shared.0);
        }
    }
    None
}

/// An error that more than one caller must see. A poisoned pipeline rejects every later
/// `next()` with the same error, and `anyhow::Error` cannot be cloned.
#[derive(Clone)]
pub struct SharedError(pub Arc<anyhow::Error>);

impl fmt::Debug for SharedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(&*self.0, f)
    }
}

impl fmt::Display for SharedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&*self.0, f)
    }
}

impl std::error::Error for SharedError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        self.0.source()
    }
}

pub fn shared_error(error: Arc<anyhow::Error>) -> anyhow::Error {
    anyhow::Error::new(SharedError(error))
}

/// Converts a task join failure (a panic or a cancel) into an error.
pub fn join_error(error: tokio::task::JoinError) -> anyhow::Error {
    anyhow::anyhow!("pipeline task failed: {error}")
}
