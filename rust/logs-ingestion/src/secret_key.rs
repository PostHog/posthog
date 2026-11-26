pub const SECRET_KEY_PREFIX: &str = "phs_";
/// capture-logs replaces a secret key with this digest, which has the form of `secure_value`.
pub const SECRET_KEY_DIGEST_PREFIX: &str = "sha256$";
pub const AUTH_TYPE_HEADER: &str = "auth-type";
pub const AUTH_TYPE_SECRET_KEY: &str = "secret_key";
pub const SECRET_KEY_SCOPE: &str = "logs:write";
const LOGGED_DIGEST_LENGTH: usize = SECRET_KEY_DIGEST_PREFIX.len() + 8;

pub fn is_secret_key_digest(token: &str) -> bool {
    token.starts_with(SECRET_KEY_DIGEST_PREFIX)
}

pub fn is_unhashed_secret_key(token: &str) -> bool {
    token.trim_start().starts_with(SECRET_KEY_PREFIX)
}

/// The part of a token that is safe to log. A digest is as good as the key to a reader of the logs.
pub fn loggable_token(token: &str) -> &str {
    if is_unhashed_secret_key(token) {
        SECRET_KEY_PREFIX
    } else if is_secret_key_digest(token) {
        token
            .get(..LOGGED_DIGEST_LENGTH)
            .unwrap_or(SECRET_KEY_DIGEST_PREFIX)
    } else {
        token
    }
}

#[cfg(test)]
mod tests {
    use super::loggable_token;

    #[test]
    fn logs_only_the_safe_part_of_a_token() {
        let digest = "sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0";
        assert_eq!(loggable_token(digest), "sha256$e39f0789");
        assert_eq!(loggable_token("sha256$e39f"), "sha256$");
        assert_eq!(loggable_token(" phs_unhashed_key"), "phs_");
        assert_eq!(loggable_token("phc_example"), "phc_example");
    }
}
