use sha2::{Digest, Sha256};

pub const SECRET_KEY_PREFIX: &str = "phs_";
pub const AUTH_TYPE_HEADER: &str = "auth-type";
pub const AUTH_TYPE_SECRET_KEY: &str = "secret_key";
pub const SECRET_KEY_SCOPE: &str = "logs:write";

pub fn is_secret_key(token: &str) -> bool {
    token.starts_with(SECRET_KEY_PREFIX)
}

/// Must match `hash_key_value` in posthog/models/utils.py, which writes `secure_value`.
pub fn hash_secret_key(secret_key: &str) -> String {
    format!(
        "sha256${}",
        hex::encode(Sha256::digest(secret_key.as_bytes()))
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_matches_the_value_django_stores() {
        assert_eq!(
            hash_secret_key("phs_example"),
            "sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0"
        );
    }
}
