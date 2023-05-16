use std::error::Error;
use std::fmt::Display;

/// Validate that a token is the correct shape

#[derive(Debug, PartialEq)]
pub enum InvalidTokenReason {
    IsEmpty,

    // ignoring for now, as serde and the type system save us but we need to error properly
    IsNotString,

    IsTooLong,
    IsNotAscii,
    IsPersonalApiKey
}

impl InvalidTokenReason {
    pub fn reason(&self) -> &str {
        match *self {
            Self::IsEmpty => "empty",
            Self::IsNotAscii => "not_ascii",
            Self::IsNotString => "not_string",
            Self::IsTooLong => "too_long",
            Self::IsPersonalApiKey => "personal_api_key",
        }
    }
}

impl Display for InvalidTokenReason{
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", self.reason())
    }
}

impl Error for InvalidTokenReason {
    fn description(&self) -> &str {
        self.reason()
    }
}

/// Check if a token is the right shape. It may not actually be a valid token! We don't validate
/// these at the edge yet.
pub fn validate_token(token: &str) -> Result<(), InvalidTokenReason> {
    if token.is_empty() {
        return Err(InvalidTokenReason::IsEmpty);
    }
    
    if token.len() > 64 {
        return Err(InvalidTokenReason::IsTooLong);
    }

    if !token.is_ascii() {
        return Err(InvalidTokenReason::IsNotAscii);
    }

    if token.starts_with("phx_") {
        return Err(InvalidTokenReason::IsPersonalApiKey);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::token::{validate_token, InvalidTokenReason};

    #[test]
    fn blocks_empty_tokens() {
        let valid = validate_token("");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::IsEmpty);
    }

    #[test]
    fn blocks_too_long_tokens() {
        let valid = validate_token("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::IsTooLong);
    }

    #[test]
    fn blocks_invalid_ascii() {
        let valid = validate_token("🦀");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::IsNotAscii);
    }

    #[test]
    fn blocks_personal_api_key() {
        let valid = validate_token("phx_hellothere");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::IsPersonalApiKey);
    }
}
