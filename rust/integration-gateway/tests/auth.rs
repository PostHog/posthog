//! Locks the JWT contract the gateway verifies against, matching what the Django mint helper
//! (`posthog/integration_gateway_jwt.py`) must produce: HS256, `aud = JWT_AUDIENCE`, `team_id`,
//! `caller`, `exp`. This mirrors the exact `Validation` config the axum extractor builds.

use std::time::{SystemTime, UNIX_EPOCH};

use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};

use integration_gateway::auth::JWT_AUDIENCE;

#[derive(Serialize, Deserialize)]
struct TestClaims {
    team_id: i64,
    caller: String,
    aud: String,
    exp: usize,
}

fn exp_in(secs: u64) -> usize {
    (SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + secs) as usize
}

fn mint(secret: &str, aud: &str) -> String {
    let claims = TestClaims {
        team_id: 42,
        caller: "cdp".to_string(),
        aud: aud.to_string(),
        exp: exp_in(300),
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(secret.as_bytes()),
    )
    .unwrap()
}

fn validation() -> Validation {
    let mut v = Validation::new(Algorithm::HS256);
    v.set_audience(&[JWT_AUDIENCE]);
    v
}

#[test]
fn verifies_scoped_token() {
    let token = mint("test-secret", JWT_AUDIENCE);
    let decoded = decode::<TestClaims>(
        &token,
        &DecodingKey::from_secret(b"test-secret"),
        &validation(),
    )
    .unwrap();
    assert_eq!(decoded.claims.team_id, 42);
    assert_eq!(decoded.claims.caller, "cdp");
}

#[test]
fn rejects_wrong_audience() {
    let token = mint("test-secret", "posthog:something_else");
    assert!(decode::<TestClaims>(
        &token,
        &DecodingKey::from_secret(b"test-secret"),
        &validation()
    )
    .is_err());
}

#[test]
fn rejects_wrong_secret() {
    let token = mint("test-secret", JWT_AUDIENCE);
    assert!(decode::<TestClaims>(
        &token,
        &DecodingKey::from_secret(b"other-secret"),
        &validation()
    )
    .is_err());
}
