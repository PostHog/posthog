pub const SECRET_KEY_PREFIX: &str = "phs_";
/// capture-logs replaces a secret key with this digest, which has the form of `secure_value`.
pub const SECRET_KEY_DIGEST_PREFIX: &str = "sha256$";
pub const AUTH_TYPE_HEADER: &str = "auth-type";
pub const AUTH_TYPE_SECRET_KEY: &str = "secret_key";
pub const SECRET_KEY_SCOPE: &str = "logs:write";

pub fn is_secret_key_digest(token: &str) -> bool {
    token.starts_with(SECRET_KEY_DIGEST_PREFIX)
}

/// A key that no capture service hashed. It is never looked up or logged.
pub fn is_secret_key(token: &str) -> bool {
    token.trim_start().starts_with(SECRET_KEY_PREFIX)
}
