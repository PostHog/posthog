use subtle::ConstantTimeEq;
use tonic::{Request, Status};

/// This seam has its own secret, not `INTERNAL_API_SECRET`, so a leak reaches this service only.
pub const PATH_RESOLUTION_SECRET_HEADER: &str = "x-cymbal-path-resolution-secret";

#[derive(Clone)]
pub struct SharedSecretInterceptor {
    // The current secret first, then older secrets that stay valid during a rotation.
    accepted_secrets: Vec<String>,
}

impl SharedSecretInterceptor {
    /// `secrets` is a comma-separated list. An empty list rejects every request.
    pub fn from_list(secrets: &str) -> Self {
        let accepted_secrets = secrets
            .split(',')
            .map(|secret| secret.trim().to_string())
            .filter(|secret| !secret.is_empty())
            .collect();
        Self { accepted_secrets }
    }

    #[allow(clippy::result_large_err)]
    pub fn authenticate(&self, request: Request<()>) -> Result<Request<()>, Status> {
        let provided = request
            .metadata()
            .get(PATH_RESOLUTION_SECRET_HEADER)
            .and_then(|value| value.to_str().ok())
            .map(str::trim)
            .unwrap_or_default();
        let matches = !provided.is_empty()
            && self
                .accepted_secrets
                .iter()
                .any(|expected| bool::from(provided.as_bytes().ct_eq(expected.as_bytes())));
        if matches {
            Ok(request)
        } else {
            Err(Status::unauthenticated("invalid path resolution secret"))
        }
    }
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use tonic::metadata::MetadataValue;

    use super::*;

    fn request_with(secret: Option<&str>) -> Request<()> {
        let mut request = Request::new(());
        if let Some(secret) = secret {
            request.metadata_mut().insert(
                PATH_RESOLUTION_SECRET_HEADER,
                MetadataValue::from_str(secret).unwrap(),
            );
        }
        request
    }

    #[test]
    fn accepts_current_and_previous_secrets_only() {
        let auth = SharedSecretInterceptor::from_list("new-secret, old-secret");

        assert!(auth.authenticate(request_with(Some("new-secret"))).is_ok());
        assert!(auth.authenticate(request_with(Some("old-secret"))).is_ok());
        assert!(auth.authenticate(request_with(Some("other"))).is_err());
        assert!(auth.authenticate(request_with(None)).is_err());
    }

    #[test]
    fn rejects_everything_when_no_secret_is_configured() {
        let auth = SharedSecretInterceptor::from_list(" , ");

        assert!(auth.authenticate(request_with(Some(""))).is_err());
        assert!(auth.authenticate(request_with(Some("anything"))).is_err());
    }
}
