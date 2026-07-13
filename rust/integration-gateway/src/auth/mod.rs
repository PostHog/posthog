pub mod claims;

use async_trait::async_trait;
use axum::extract::FromRequestParts;
use axum::http::{header::AUTHORIZATION, request::Parts, StatusCode};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};

use crate::app_context::AppState;
pub use claims::{AuthedCaller, Claims, JWT_AUDIENCE};

/// Axum extractor that verifies the scoped JWT and yields the authenticated caller.
///
/// Fails closed: no `Authorization: Bearer` header, no configured secret, wrong audience,
/// expired, or bad signature => 401. Tries every configured secret (primary then fallbacks),
/// mirroring `posthog/jwt.py::decode_jwt`'s rotation loop. Adapted for axum from the tonic
/// decode in `rust/capture-logs/src/auth.rs`.
#[async_trait]
impl FromRequestParts<AppState> for AuthedCaller {
    type Rejection = StatusCode;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        if state.jwt_secrets.is_empty() {
            return Err(StatusCode::UNAUTHORIZED);
        }

        let token = parts
            .headers
            .get(AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|h| h.strip_prefix("Bearer "))
            .map(str::trim)
            .ok_or(StatusCode::UNAUTHORIZED)?;

        let mut validation = Validation::new(Algorithm::HS256);
        validation.set_audience(&[JWT_AUDIENCE]);
        // `exp` is validated by default.

        for secret in state.jwt_secrets.iter() {
            if let Ok(data) = decode::<Claims>(
                token,
                &DecodingKey::from_secret(secret.as_bytes()),
                &validation,
            ) {
                return Ok(AuthedCaller {
                    team_id: data.claims.team_id,
                    caller: data.claims.caller,
                });
            }
        }

        Err(StatusCode::UNAUTHORIZED)
    }
}
