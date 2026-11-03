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

#[derive(Debug, Clone, thiserror::Error)]
#[error("{message}")]
pub struct KafkaProduceError {
    pub code: i32,
    pub name: String,
    pub message: String,
}

pub const ERR_INVALID_MSG: i32 = 2;
pub const ERR_INVALID_MSG_SIZE: i32 = 4;
pub const ERR_MSG_SIZE_TOO_LARGE: i32 = 10;
pub const ERR_RECORD_LIST_TOO_LARGE: i32 = 18;
pub const ERR_INVALID_RECORD: i32 = 87;
pub const ERR_BAD_MSG: i32 = -199;
pub const ERR_INVALID_ARG: i32 = -186;
pub const ERR_INVALID_TYPE: i32 = -154;

pub const PER_MESSAGE_KAFKA_ERROR_CODES: [i32; 8] = [
    ERR_INVALID_MSG,
    ERR_INVALID_MSG_SIZE,
    ERR_MSG_SIZE_TOO_LARGE,
    ERR_RECORD_LIST_TOO_LARGE,
    ERR_INVALID_RECORD,
    ERR_BAD_MSG,
    ERR_INVALID_ARG,
    ERR_INVALID_TYPE,
];

/// `rethrowKafkaOutageAsDependency`: a Kafka outage on the logs produce replays the batch.
pub fn kafka_outage_as_dependency(error: anyhow::Error) -> anyhow::Error {
    match error.downcast_ref::<KafkaProduceError>() {
        Some(e) if !PER_MESSAGE_KAFKA_ERROR_CODES.contains(&e.code) => {
            anyhow::Error::new(DependencyUnavailableError {
                message: e.message.clone(),
                dependency_name: "Kafka".to_string(),
            })
        }
        _ => error,
    }
}

pub fn is_dependency_unavailable(error: &anyhow::Error) -> bool {
    error.downcast_ref::<DependencyUnavailableError>().is_some()
}

/// `error instanceof Error ? error.name : 'UnknownError'`.
pub fn error_name(error: &anyhow::Error) -> String {
    if let Some(e) = error.downcast_ref::<NamedError>() {
        return e.name.clone();
    }
    if let Some(e) = error.downcast_ref::<KafkaProduceError>() {
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
