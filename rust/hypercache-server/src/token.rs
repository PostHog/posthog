use std::fmt;

/// A validated project API token.
///
/// Can only be constructed via [`Token::parse`], which enforces:
/// - Non-empty, max 200 characters
/// - Only ASCII alphanumeric, underscore, and hyphen
///
/// This character class (`[a-zA-Z0-9_-]`) is safe to interpolate into
/// single-quoted JS strings — it provably cannot break out of the quote.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token(String);

/// Error returned when a raw string fails token validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TokenError {
    Empty,
    TooLong,
    InvalidCharacters,
}

impl fmt::Display for TokenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TokenError::Empty => write!(f, "Token not provided"),
            TokenError::TooLong => write!(f, "Token too long"),
            TokenError::InvalidCharacters => write!(f, "Invalid token format"),
        }
    }
}

impl Token {
    /// Parse and validate a raw token string.
    ///
    /// Matches Django's `BaseRemoteConfigAPIView.check_token`.
    pub fn parse(raw: &str) -> Result<Self, TokenError> {
        if raw.is_empty() {
            return Err(TokenError::Empty);
        }
        if raw.len() > 200 {
            return Err(TokenError::TooLong);
        }
        if !raw
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err(TokenError::InvalidCharacters);
        }
        Ok(Token(raw.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_tokens() {
        assert!(Token::parse("phc_abc123").is_ok());
        assert!(Token::parse("phc_leDMtGUQ1TDiPxotanVngOdEsShwcpDsLFLROFcGK9W").is_ok());
        assert!(Token::parse("some-old-token_with-dashes").is_ok());
        assert!(Token::parse("a").is_ok());
    }

    #[test]
    fn test_empty_token() {
        assert_eq!(Token::parse(""), Err(TokenError::Empty));
    }

    #[test]
    fn test_overlong_token() {
        assert_eq!(Token::parse(&"a".repeat(201)), Err(TokenError::TooLong));
        assert!(Token::parse(&"a".repeat(200)).is_ok());
    }

    #[test]
    fn test_invalid_characters() {
        for input in [
            "token with spaces",
            "token/with/slashes",
            "token.with.dots",
            "token<script>",
            "token'inject",
            "token\"quote",
            "token\nline",
            "token\0null",
        ] {
            assert_eq!(
                Token::parse(input),
                Err(TokenError::InvalidCharacters),
                "Expected InvalidCharacters for {input:?}"
            );
        }
    }

    #[test]
    fn test_as_str_roundtrip() {
        let token = Token::parse("phc_test123").unwrap();
        assert_eq!(token.as_str(), "phc_test123");
    }
}
