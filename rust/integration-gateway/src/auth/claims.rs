use serde::Deserialize;

/// Audience the gateway accepts. Django mints tokens with this exact `aud`
/// (see the mint helper `posthog/integration_gateway_jwt.py`).
pub const JWT_AUDIENCE: &str = "posthog:integration_gateway";

/// Claims carried by a caller's scoped JWT.
#[derive(Debug, Deserialize)]
pub struct Claims {
    /// The single team this token is scoped to. The service returns only rows for this team.
    pub team_id: i64,
    /// Which service minted this token (e.g. "cdp"). Self-asserted; used for auditing.
    pub caller: String,
    /// Validated by `jsonwebtoken` against `JWT_AUDIENCE`.
    #[allow(dead_code)]
    pub aud: String,
    /// Validated (expiry) by `jsonwebtoken`.
    #[allow(dead_code)]
    pub exp: usize,
}

/// The authenticated caller, produced by the `FromRequestParts` extractor.
pub struct AuthedCaller {
    pub team_id: i64,
    pub caller: String,
}
