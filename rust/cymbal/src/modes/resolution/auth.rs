use subtle::ConstantTimeEq;
use tonic::{Request, Status};

pub const INTERNAL_API_SECRET_HEADER: &str = "x-internal-api-secret";

#[derive(Clone)]
pub struct InternalApiSecretInterceptor {
    // Primary secret plus any still-trusted fallbacks (zero-downtime rotation), trimmed and non-empty.
    accepted_secrets: Vec<String>,
}

impl InternalApiSecretInterceptor {
    pub fn new(primary: impl Into<String>, fallbacks: impl IntoIterator<Item = String>) -> Self {
        let accepted_secrets = std::iter::once(primary.into())
            .chain(fallbacks)
            .map(|secret| secret.trim().to_string())
            .filter(|secret| !secret.is_empty())
            .collect();
        Self { accepted_secrets }
    }

    #[allow(clippy::result_large_err)]
    pub fn authenticate(&self, request: Request<()>) -> Result<Request<()>, Status> {
        if self.accepted_secrets.is_empty() {
            return Err(Status::unauthenticated(
                "internal API secret is not configured",
            ));
        }

        let Some(provided_secret) = request.metadata().get(INTERNAL_API_SECRET_HEADER) else {
            return Err(Status::unauthenticated("missing internal API secret"));
        };

        let provided_secret = provided_secret
            .to_str()
            .map_err(|_| Status::unauthenticated("invalid internal API secret"))?
            .trim();

        if provided_secret.is_empty() {
            return Err(Status::unauthenticated("missing internal API secret"));
        }

        let matches = self
            .accepted_secrets
            .iter()
            .any(|expected| provided_secret.as_bytes().ct_eq(expected.as_bytes()).into());

        if matches {
            Ok(request)
        } else {
            Err(Status::unauthenticated("invalid internal API secret"))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;
    use tonic::metadata::MetadataValue;
    use tonic::Code;

    fn request_with_secret(secret: &str) -> Request<()> {
        let mut request = Request::new(());
        request.metadata_mut().insert(
            INTERNAL_API_SECRET_HEADER,
            MetadataValue::from_str(secret).unwrap(),
        );
        request
    }

    #[test]
    fn allows_matching_secret() {
        let auth = InternalApiSecretInterceptor::new("test-secret", vec![]);
        assert!(auth
            .authenticate(request_with_secret("test-secret"))
            .is_ok());
    }

    #[test]
    fn accepts_primary_and_fallback_secrets() {
        let auth = InternalApiSecretInterceptor::new("new-secret", vec!["old-secret".to_string()]);
        assert!(auth.authenticate(request_with_secret("new-secret")).is_ok());
        assert!(auth.authenticate(request_with_secret("old-secret")).is_ok());
        let err = auth.authenticate(request_with_secret("bogus")).unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }

    #[test]
    fn trims_configured_and_provided_secret() {
        let auth =
            InternalApiSecretInterceptor::new(" test-secret\n", vec![" old-secret\n".to_string()]);
        assert!(auth
            .authenticate(request_with_secret("test-secret "))
            .is_ok());
        assert!(auth
            .authenticate(request_with_secret(" old-secret "))
            .is_ok());
    }

    #[test]
    fn rejects_missing_secret() {
        let auth = InternalApiSecretInterceptor::new("test-secret", vec![]);
        let err = auth.authenticate(Request::new(())).unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }

    #[test]
    fn rejects_mismatched_secret() {
        let auth = InternalApiSecretInterceptor::new("test-secret", vec![]);
        let err = auth
            .authenticate(request_with_secret("wrong-secret"))
            .unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }

    #[test]
    fn rejects_when_not_configured() {
        let auth = InternalApiSecretInterceptor::new("", vec![]);
        let err = auth
            .authenticate(request_with_secret("test-secret"))
            .unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }
}
