use std::error::Error;
use std::fmt::Display;

/// Validate that a token is the correct shape

#[derive(Clone, Debug, PartialEq)]
pub enum InvalidTokenReason {
    Empty,

    // ignoring for now, as serde and the type system save us but we need to error properly
    // IsNotString,
    TooLong,
    NotAscii,
    PersonalApiKey,
    NullByte,
}

impl InvalidTokenReason {
    pub fn reason(&self) -> &str {
        match *self {
            Self::Empty => "empty",
            Self::NotAscii => "not_ascii",
            // Self::IsNotString => "not_string",
            Self::TooLong => "too_long",
            Self::PersonalApiKey => "personal_api_key",
            Self::NullByte => "null_byte",
        }
    }
}

impl Display for InvalidTokenReason {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", self.reason())
    }
}

impl Error for InvalidTokenReason {
    fn description(&self) -> &str {
        self.reason()
    }
}

/// Check if a token is the right shape and normalize it. It may not actually be a valid token!
/// We don't validate these against team lookup at the edge yet.
///
/// Leading/trailing whitespace is stripped so that an accidental newline or space in a copied
/// API key (e.g. `phc_...\n`) is normalized rather than silently failing team lookup and
/// dropping the events. The trimmed token is returned and must be used by callers for lookup.
pub fn validate_token(token: &str) -> Result<&str, InvalidTokenReason> {
    let token = token.trim();

    if token.is_empty() {
        return Err(InvalidTokenReason::Empty);
    }

    if token.len() > 64 {
        return Err(InvalidTokenReason::TooLong);
    }

    if !token.is_ascii() {
        return Err(InvalidTokenReason::NotAscii);
    }

    if token.starts_with("phx_") {
        return Err(InvalidTokenReason::PersonalApiKey);
    }

    // We refuse tokens with null bytes
    if token.contains('\0') {
        return Err(InvalidTokenReason::NullByte);
    }

    Ok(token)
}

#[cfg(test)]
mod tests {
    use crate::token::{validate_token, InvalidTokenReason};

    #[test]
    fn blocks_empty_tokens() {
        let valid = validate_token("");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::Empty);
    }

    #[test]
    fn blocks_too_long_tokens() {
        let valid =
            validate_token("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::TooLong);
    }

    #[test]
    fn blocks_invalid_ascii() {
        let valid = validate_token("🦀");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::NotAscii);
    }

    #[test]
    fn blocks_personal_api_key() {
        let valid = validate_token("phx_hellothere");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::PersonalApiKey);
    }

    #[test]
    fn blocks_null_byte() {
        let valid = validate_token("hello\0there");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::NullByte);
    }

    #[test]
    fn trims_surrounding_whitespace() {
        // A stray newline in a copied API key must be normalized away, not cause a
        // team-lookup miss and silent event loss.
        assert_eq!(validate_token("phc_hellothere\n").unwrap(), "phc_hellothere");
        assert_eq!(validate_token("  phc_hellothere  ").unwrap(), "phc_hellothere");
        assert_eq!(validate_token("\tphc_hellothere\r\n").unwrap(), "phc_hellothere");
    }

    #[test]
    fn blocks_whitespace_only_token() {
        let valid = validate_token("   \n");

        assert!(valid.is_err());
        assert_eq!(valid.unwrap_err(), InvalidTokenReason::Empty);
    }
}
