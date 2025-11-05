use std::error::Error;
use std::fmt;
use std::time;

use common_dns::NoPublicIPv4Error;
use hook_common::{pgqueue, webhook::WebhookJobError};
use http::StatusCode;
use thiserror::Error;

/// Enumeration of error classes handled by `WebhookWorker`.
#[derive(Error, Debug)]
pub enum WebhookError {
    #[error(transparent)]
    Parse(#[from] WebhookParseError),
    #[error(transparent)]
    Request(#[from] WebhookRequestError),
}

/// Enumeration of parsing errors that can occur as `WebhookWorker` sets up a webhook.
#[derive(Error, Debug)]
pub enum WebhookParseError {
    #[error("{0} is not a valid HttpMethod")]
    ParseHttpMethodError(String),
    #[error("error parsing webhook headers")]
    ParseHeadersError(http::Error),
    #[error("error parsing webhook url")]
    ParseUrlError(url::ParseError),
}

/// Enumeration of request errors that can occur as `WebhookWorker` sends a request.
#[derive(Error, Debug)]
pub enum WebhookRequestError {
    RetryableRequestError {
        error: reqwest::Error,
        status: Option<StatusCode>,
        response: Option<String>,
        retry_after: Option<time::Duration>,
    },
    NonRetryableRetryableRequestError {
        error: reqwest::Error,
        status: Option<StatusCode>,
        response: Option<String>,
    },
}

/// Enumeration of errors that can occur while handling a `reqwest::Response`.
/// Currently, not consumed anywhere. Grouped here to support a common error type for
/// `utils::first_n_bytes_of_response`.
#[derive(Error, Debug)]
pub enum WebhookResponseError {
    #[error("failed to parse a response as UTF8")]
    ParseUTF8StringError(#[from] std::str::Utf8Error),
    #[error("error while iterating over response body chunks")]
    StreamIterationError(#[from] reqwest::Error),
    #[error("attempted to slice a chunk of length {0} with an out of bounds index of {1}")]
    ChunkOutOfBoundsError(usize, usize),
}

/// Implement display of `WebhookRequestError` by appending to the underlying `reqwest::Error`
/// any response message if available.
impl fmt::Display for WebhookRequestError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            WebhookRequestError::RetryableRequestError {
                error,
                status: _,
                response,
                ..
            }
            | WebhookRequestError::NonRetryableRetryableRequestError {
                error,
                status: _,
                response,
            } => {
                let response_message = match response {
                    Some(m) => m.to_string(),
                    None => "No response from the server".to_string(),
                };
                if is_error_source::<NoPublicIPv4Error>(error) {
                    writeln!(f, "{error}: {NoPublicIPv4Error}")?;
                } else {
                    writeln!(f, "{error}")?;
                }
                write!(f, "{response_message}")?;

                Ok(())
            }
        }
    }
}

/// Implementation of `WebhookRequestError` designed to further describe the error.
/// In particular, we pass some calls to underyling `reqwest::Error` to provide more details.
impl WebhookRequestError {
    pub fn is_timeout(&self) -> bool {
        match self {
            WebhookRequestError::RetryableRequestError { error, .. }
            | WebhookRequestError::NonRetryableRetryableRequestError { error, .. } => {
                error.is_timeout()
            }
        }
    }

    pub fn is_status(&self) -> bool {
        match self {
            WebhookRequestError::RetryableRequestError { error, .. }
            | WebhookRequestError::NonRetryableRetryableRequestError { error, .. } => {
                error.is_status()
            }
        }
    }

    pub fn status(&self) -> Option<http::StatusCode> {
        match self {
            WebhookRequestError::RetryableRequestError { error, .. }
            | WebhookRequestError::NonRetryableRetryableRequestError { error, .. } => {
                error.status()
            }
        }
    }
}

impl From<&WebhookRequestError> for WebhookJobError {
    fn from(error: &WebhookRequestError) -> Self {
        if error.is_timeout() {
            WebhookJobError::new_timeout(&error.to_string())
        } else if error.is_status() {
            WebhookJobError::new_http_status(
                error.status().expect("status code is defined").into(),
                &error.to_string(),
            )
        } else {
            // Catch all other errors as `app_metrics::ErrorType::Connection` errors.
            // Not all of `reqwest::Error` may strictly be connection errors, so our supported error types may need an extension
            // depending on how strict error reporting has to be.
            WebhookJobError::new_connection(&error.to_string())
        }
    }
}

/// Enumeration of errors related to initialization and consumption of webhook jobs.
#[derive(Error, Debug)]
pub enum WorkerError {
    #[error("a database error occurred when executing a job")]
    DatabaseError(#[from] pgqueue::DatabaseError),
    #[error("a parsing error occurred in the underlying queue")]
    QueueParseError(#[from] pgqueue::ParseError),
    #[error("timed out while waiting for jobs to be available")]
    TimeoutError,
}

/// Check the error and it's sources (recursively) to return true if an error of the given type is found.
/// TODO: use Error::sources() when stable
pub fn is_error_source<T: Error + 'static>(err: &(dyn std::error::Error + 'static)) -> bool {
    if err.is::<NoPublicIPv4Error>() {
        return true;
    }
    match err.source() {
        None => false,
        Some(source) => is_error_source::<T>(source),
    }
}
