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

/// The part of a token that is safe to log, wherever a key or digest sits in it. A digest is as good as the key to a reader of the logs.
pub fn loggable_token(token: &str) -> &str {
    let secret = [SECRET_KEY_PREFIX, SECRET_KEY_DIGEST_PREFIX]
        .into_iter()
        .filter_map(|marker| token.find(marker).map(|at| (at, marker)))
        .min();
    let Some((at, marker)) = secret else {
        return token;
    };
    let marker_end = at + marker.len();
    let end = if marker == SECRET_KEY_DIGEST_PREFIX {
        at + LOGGED_DIGEST_LENGTH
    } else {
        marker_end
    };
    token
        .get(..end)
        .unwrap_or(&token[..marker_end])
        .trim_start()
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
        assert_eq!(loggable_token("apikey: phs_unhashed_key"), "apikey: phs_");
        assert_eq!(
            loggable_token(&format!("Basic {digest}")),
            "Basic sha256$e39f0789"
        );
        assert_eq!(loggable_token("Basic sha256$e39f"), "Basic sha256$");
    }
}
