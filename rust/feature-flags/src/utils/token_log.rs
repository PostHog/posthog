use std::borrow::Cow;

/// Redacts a token for safe logging, showing only a prefix and suffix.
pub fn redact_token(token: &str) -> String {
    match (token.get(..4), token.get(token.len().saturating_sub(4)..)) {
        (Some(prefix), Some(suffix)) if token.len() > 8 => format!("{prefix}…{suffix}"),
        _ => "***".to_string(),
    }
}

/// Keeps `phc_` project tokens whole, because they are public and identify the project in logs.
/// Any other value in a token field can be a private key, so only its prefix and suffix are logged.
pub fn loggable_token(token: &str) -> Cow<'_, str> {
    if token.starts_with("phc_") {
        Cow::Borrowed(token)
    } else {
        Cow::Owned(redact_token(token))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_redact_token() {
        assert_eq!(redact_token("short"), "***");
        assert_eq!(redact_token("phc_abcdefghijklmnop"), "phc_…mnop");
        assert_eq!(redact_token("12345678"), "***");
        assert_eq!(redact_token("123456789"), "1234…6789");
    }

    #[test]
    fn test_loggable_token() {
        assert_eq!(
            loggable_token("phc_abcdefghijklmnop"),
            "phc_abcdefghijklmnop"
        );
        assert_eq!(loggable_token("phx_abcdefghijklmnop"), "phx_…mnop");
        assert_eq!(loggable_token("legacy-token-value"), "lega…alue");
        assert_eq!(loggable_token("short"), "***");
    }
}
