use std::str::FromStr;
use std::time::Duration;

use thiserror::Error;
use tonic::metadata::MetadataValue;
use tonic::{Code, Request, Status};

pub const INTERNAL_API_SECRET_HEADER: &str = "x-internal-api-secret";

/// Errors observable by the remote resolver's retry logic. The `retryable`
/// half is what cymbal will retry against another endpoint; `terminal` is
/// surfaced as a handled error so the rest of `/process` can move on.
#[derive(Debug, Error)]
pub enum RemoteCallError {
    #[error("remote resolution rpc returned retryable status {0:?}")]
    Retryable(Status),
    #[error("remote resolution rpc returned terminal status {0:?}")]
    Terminal(Status),
    #[error("remote resolution rpc deadline exceeded after {0:?}")]
    Deadline(Duration),
}

impl RemoteCallError {
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            RemoteCallError::Retryable(_) | RemoteCallError::Deadline(_)
        )
    }

    /// Short tag suitable for metric labels. Keeps the cardinality bounded
    /// to the gRPC code set plus "deadline" so dashboards can distinguish
    /// transport classes without exploding labels.
    pub fn reason_tag(&self) -> &'static str {
        match self {
            RemoteCallError::Deadline(_) => "deadline",
            RemoteCallError::Retryable(status) | RemoteCallError::Terminal(status) => {
                code_tag(status.code())
            }
        }
    }
}

fn code_tag(code: Code) -> &'static str {
    match code {
        Code::Ok => "ok",
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::InvalidArgument => "invalid_argument",
        Code::DeadlineExceeded => "deadline_exceeded",
        Code::NotFound => "not_found",
        Code::AlreadyExists => "already_exists",
        Code::PermissionDenied => "permission_denied",
        Code::ResourceExhausted => "resource_exhausted",
        Code::FailedPrecondition => "failed_precondition",
        Code::Aborted => "aborted",
        Code::OutOfRange => "out_of_range",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data_loss",
        Code::Unauthenticated => "unauthenticated",
    }
}

pub(crate) fn with_internal_api_secret<T>(
    mut request: Request<T>,
    internal_api_secret: &str,
) -> Result<Request<T>, Box<Status>> {
    let secret = internal_api_secret.trim();
    if secret.is_empty() {
        return Err(Box::new(Status::unauthenticated(
            "internal API secret is not configured",
        )));
    }
    let value = MetadataValue::from_str(secret).map_err(|_| {
        Box::new(Status::unauthenticated(
            "invalid internal API secret metadata",
        ))
    })?;
    request
        .metadata_mut()
        .insert(INTERNAL_API_SECRET_HEADER, value);
    Ok(request)
}

pub(crate) fn classify_status(status: Status) -> RemoteCallError {
    match status.code() {
        // Transport/availability/timeouts → retry against another endpoint.
        Code::Unavailable
        | Code::ResourceExhausted
        | Code::DeadlineExceeded
        | Code::Aborted
        | Code::Cancelled
        | Code::Unknown
        | Code::Internal => RemoteCallError::Retryable(status),
        // Everything else (InvalidArgument, NotFound, PermissionDenied, …) is
        // terminal; retrying will keep failing the same way.
        _ => RemoteCallError::Terminal(status),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn with_internal_api_secret_adds_expected_metadata() {
        let request = with_internal_api_secret(Request::new(()), " test-secret\n").unwrap();
        assert_eq!(
            request
                .metadata()
                .get(INTERNAL_API_SECRET_HEADER)
                .unwrap()
                .to_str()
                .unwrap(),
            "test-secret"
        );
    }

    #[test]
    fn with_internal_api_secret_rejects_empty_secret() {
        let err = with_internal_api_secret(Request::new(()), " ").unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }
}
