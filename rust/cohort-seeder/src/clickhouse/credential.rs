use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use tracing::warn;

use crate::config::Config;

const TOKEN_EXPIRY_LEEWAY_SECS: f64 = 10.0;

#[derive(Default)]
pub struct ClickHouseCredential {
    static_password: String,
    token_file: Option<PathBuf>,
}

impl ClickHouseCredential {
    pub fn new(static_password: String, token_file: &str) -> Self {
        Self {
            static_password,
            token_file: (!token_file.is_empty()).then(|| PathBuf::from(token_file)),
        }
    }

    pub fn from_config(config: &Config) -> Self {
        Self::new(
            config.clickhouse_password.clone(),
            &config.clickhouse_password_file,
        )
    }

    pub fn current(&self) -> String {
        self.current_at(SystemTime::now())
    }

    fn current_at(&self, now: SystemTime) -> String {
        let Some(token_file) = &self.token_file else {
            return self.static_password.clone();
        };
        let token = match fs::read_to_string(token_file) {
            Ok(contents) => contents.trim().to_owned(),
            Err(error) => {
                warn!(%error, "ClickHouse token file is not readable, using the static password");
                return self.static_password.clone();
            }
        };
        if token.is_empty() {
            warn!("ClickHouse token file is empty, using the static password");
            return self.static_password.clone();
        }
        // The kubelet stops refreshing the token of a terminating pod, so a slow shutdown can leave
        // an expired token that ClickHouse rejects.
        if !self.static_password.is_empty() && token_expired(&token, now) {
            warn!("ClickHouse token has expired, using the static password");
            return self.static_password.clone();
        }
        token
    }
}

/// Whether a JWT's `exp` claim has passed. The signature is not verified, because the ch-podauth
/// bridge validates the token. A token whose `exp` cannot be read counts as not expired.
fn token_expired(token: &str, now: SystemTime) -> bool {
    let Some(exp) = token_expiry(token) else {
        return false;
    };
    let now = now
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |elapsed| elapsed.as_secs_f64());
    now >= exp - TOKEN_EXPIRY_LEEWAY_SECS
}

fn token_expiry(token: &str) -> Option<f64> {
    let mut parts = token.split('.');
    let (Some(_header), Some(payload), Some(_signature), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return None;
    };
    let claims = URL_SAFE_NO_PAD.decode(payload.trim_end_matches('=')).ok()?;
    let claims: serde_json::Value = serde_json::from_slice(&claims).ok()?;
    claims.get("exp")?.as_f64()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration;

    use envconfig::Envconfig;

    use super::*;

    const NOW_SECS: u64 = 1_000_000;

    fn now() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(NOW_SECS)
    }

    fn jwt(payload: &str) -> String {
        format!(
            "{}.{}.signature",
            URL_SAFE_NO_PAD.encode(r#"{"alg":"RS256"}"#),
            URL_SAFE_NO_PAD.encode(payload)
        )
    }

    fn jwt_expiring_at(exp: u64) -> String {
        jwt(&format!(r#"{{"exp":{exp}}}"#))
    }

    #[test]
    fn the_token_file_supersedes_the_static_password_only_while_it_is_usable() {
        let scratch = tempfile::tempdir().unwrap();
        let live = jwt_expiring_at(NOW_SECS + 3600);
        let expired = jwt_expiring_at(NOW_SECS - 60);
        let within_leeway = jwt_expiring_at(NOW_SECS + 5);
        let padded_expired = {
            let (header_and_payload, _signature) = expired.rsplit_once('.').unwrap();
            format!("{header_and_payload}==.signature")
        };
        let no_exp = jwt(r#"{"sub":"system:serviceaccount:posthog:cohort-seeder"}"#);

        let cases: [(&str, Option<String>, &str, String); 9] = [
            (
                "live token",
                Some(format!("{live}\n")),
                "static",
                live.clone(),
            ),
            ("missing file", None, "static", "static".into()),
            ("empty file", Some(" \n".into()), "static", "static".into()),
            (
                "expired token",
                Some(expired.clone()),
                "static",
                "static".into(),
            ),
            (
                "expired token, no static",
                Some(expired.clone()),
                "",
                expired.clone(),
            ),
            (
                "inside the leeway",
                Some(within_leeway),
                "static",
                "static".into(),
            ),
            (
                "padded payload",
                Some(padded_expired),
                "static",
                "static".into(),
            ),
            ("no exp claim", Some(no_exp.clone()), "static", no_exp),
            (
                "opaque token",
                Some("not-a-jwt".into()),
                "static",
                "not-a-jwt".into(),
            ),
        ];
        for (case, contents, static_password, expected) in cases {
            let token_file = scratch.path().join(case.replace(' ', "_"));
            if let Some(contents) = contents {
                std::fs::write(&token_file, contents).unwrap();
            }
            let credential =
                ClickHouseCredential::new(static_password.into(), token_file.to_str().unwrap());
            assert_eq!(credential.current_at(now()), expected, "{case}");
        }
    }

    #[test]
    fn the_token_file_comes_from_clickhouse_password_file() {
        let scratch = tempfile::tempdir().unwrap();
        let token_file = scratch.path().join("token");
        std::fs::write(&token_file, "the-token").unwrap();
        let mut env = HashMap::from([("CLICKHOUSE_PASSWORD".to_string(), "static".to_string())]);
        let static_only = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(
            ClickHouseCredential::from_config(&static_only).current(),
            "static"
        );

        env.insert(
            "CLICKHOUSE_PASSWORD_FILE".to_string(),
            token_file.to_string_lossy().into_owned(),
        );
        let with_token = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(
            ClickHouseCredential::from_config(&with_token).current(),
            "the-token"
        );
    }
}
