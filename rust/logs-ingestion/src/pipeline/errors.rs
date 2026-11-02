//! JavaScript error identity for the DLQ headers and the batch result, and the
//! `retryOnDependencyUnavailableError` policy.

use std::future::Future;
use std::time::Duration;

use crate::avro::AvroError;
use crate::property_filter::coerce::JsTypeError;

#[derive(Debug, Clone, thiserror::Error)]
#[error("{message}")]
pub struct NamedError {
    pub name: String,
    pub message: String,
}

impl NamedError {
    pub fn new(name: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            message: message.into(),
        }
    }
}

/// `DependencyUnavailableError`: an infrastructure outage, which fails the batch instead of
/// quarantining the message.
#[derive(Debug, Clone, thiserror::Error)]
#[error("{message}")]
pub struct DependencyUnavailableError {
    pub message: String,
    pub dependency_name: String,
}

pub fn is_dependency_unavailable(error: &anyhow::Error) -> bool {
    error.downcast_ref::<DependencyUnavailableError>().is_some()
}

/// `error instanceof Error ? error.name : 'UnknownError'`.
pub fn error_name(error: &anyhow::Error) -> String {
    if let Some(e) = error.downcast_ref::<NamedError>() {
        return e.name.clone();
    }
    if error.downcast_ref::<DependencyUnavailableError>().is_some() {
        return "DependencyUnavailableError".to_string();
    }
    if error.downcast_ref::<JsTypeError>().is_some() {
        return "TypeError".to_string();
    }
    if error.downcast_ref::<AvroError>().is_some() {
        return "Error".to_string();
    }
    "Error".to_string()
}

pub fn error_message(error: &anyhow::Error) -> String {
    if let Some(e) = error.downcast_ref::<JsTypeError>() {
        return e.0.to_string();
    }
    error.to_string()
}

#[derive(Debug, Clone, Copy)]
pub struct DependencyRetry {
    pub retry_count: u32,
    pub initial_retry_delay_ms: u64,
}

impl Default for DependencyRetry {
    fn default() -> Self {
        Self {
            retry_count: 5,
            initial_retry_delay_ms: 1000,
        }
    }
}

pub async fn retry_on_dependency_unavailable<T, F, Fut>(
    policy: DependencyRetry,
    mut f: F,
) -> anyhow::Result<T>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = anyhow::Result<T>>,
{
    let mut attempt = 0;
    let mut delay = policy.initial_retry_delay_ms;
    loop {
        match f().await {
            Ok(value) => return Ok(value),
            Err(error) if is_dependency_unavailable(&error) && attempt + 1 < policy.retry_count => {
                tokio::time::sleep(Duration::from_millis(delay)).await;
                delay *= 2;
                attempt += 1;
            }
            Err(error) => return Err(error),
        }
    }
}
