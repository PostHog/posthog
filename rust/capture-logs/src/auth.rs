use anyhow::Result;
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde_derive::{Deserialize, Serialize};
use std::fmt;
use thiserror::Error;
use tonic::{Request, Status};

/// JWT claims with team_id
#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub team_id: String,
    pub exp: Option<usize>, // Optional expiration time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iat: Option<usize>, // Optional issued at time
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iss: Option<String>, // Optional issuer
}

impl fmt::Display for Claims {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Claims {{ team_id: {} }}", self.team_id)
    }
}

#[derive(Debug, Error)]
pub enum AuthError {
    #[error("Missing Authorization header")]
    MissingHeader,

    #[error("Invalid Authorization header format")]
    InvalidHeaderFormat,

    #[error("JWT error: {0}")]
    JwtError(Box<jsonwebtoken::errors::Error>),
}

/// Extract and validate JWT token from the Authorization header
pub fn extract_team_id_from_jwt(
    request: &Request<impl std::fmt::Debug>,
    jwt_secret: &str,
) -> Result<String, AuthError> {
    // Extract the Authorization header
    let auth_header = request
        .metadata()
        .get("authorization")
        .ok_or(AuthError::MissingHeader)?;

    // Convert to a string and validate format
    let auth_str = auth_header
        .to_str()
        .map_err(|_| AuthError::InvalidHeaderFormat)?;

    // Check if it starts with "Bearer "
    if !auth_str.starts_with("Bearer ") {
        return Err(AuthError::InvalidHeaderFormat);
    }

    // Extract the token part
    let token = auth_str["Bearer ".len()..].trim();

    // Decode and validate the JWT
    let token_data = decode::<Claims>(
        token,
        &DecodingKey::from_secret(jwt_secret.as_bytes()),
        &Validation::new(Algorithm::HS256),
    )
    .map_err(|e| AuthError::JwtError(Box::new(e)))?;

    // Return the team_id from the claims
    Ok(token_data.claims.team_id)
}

/// Middleware-style function to extract team_id from request
pub fn authenticate_request(
    request: &Request<impl std::fmt::Debug>,
    jwt_secret: &str,
) -> Result<String, Box<Status>> {
    extract_team_id_from_jwt(request, jwt_secret).map_err(|err| {
        tracing::error!("Authentication error: {err}");
        Box::new(match err {
            AuthError::MissingHeader | AuthError::InvalidHeaderFormat => {
                Status::unauthenticated("Invalid or missing Authorization header")
            }
            AuthError::JwtError(_) => Status::unauthenticated(format!("Invalid JWT token: {err}")),
        })
    })
}
