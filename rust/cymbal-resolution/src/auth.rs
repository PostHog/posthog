use subtle::ConstantTimeEq;
use tonic::{Request, Status};

pub const INTERNAL_API_SECRET_HEADER: &str = "x-internal-api-secret";

#[derive(Clone)]
pub struct InternalApiSecretInterceptor {
    expected_secret: String,
}

impl InternalApiSecretInterceptor {
    pub fn new(expected_secret: impl Into<String>) -> Self {
        Self {
            expected_secret: expected_secret.into(),
        }
    }

    pub fn authenticate(&self, request: Request<()>) -> Result<Request<()>, Status> {
        let expected_secret = self.expected_secret.trim();
        if expected_secret.is_empty() {
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

        if provided_secret
            .as_bytes()
            .ct_eq(expected_secret.as_bytes())
            .into()
        {
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
        let auth = InternalApiSecretInterceptor::new("test-secret");
        assert!(auth
            .authenticate(request_with_secret("test-secret"))
            .is_ok());
    }

    #[test]
    fn trims_configured_and_provided_secret() {
        let auth = InternalApiSecretInterceptor::new(" test-secret\n");
        assert!(auth
            .authenticate(request_with_secret("test-secret "))
            .is_ok());
    }

    #[test]
    fn rejects_missing_secret() {
        let auth = InternalApiSecretInterceptor::new("test-secret");
        let err = auth.authenticate(Request::new(())).unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }

    #[test]
    fn rejects_mismatched_secret() {
        let auth = InternalApiSecretInterceptor::new("test-secret");
        let err = auth
            .authenticate(request_with_secret("wrong-secret"))
            .unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }

    #[test]
    fn rejects_when_not_configured() {
        let auth = InternalApiSecretInterceptor::new("");
        let err = auth
            .authenticate(request_with_secret("test-secret"))
            .unwrap_err();
        assert_eq!(err.code(), Code::Unauthenticated);
    }
}
