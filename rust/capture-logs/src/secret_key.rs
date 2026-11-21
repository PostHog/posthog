//! The handlers write the token to spans, to a debug file and to Kafka. That is safe for a public
//! project token and not for a secret key, so a secret key becomes its digest before they run.

use axum::{
    body::Body,
    extract::Request,
    http::{header, HeaderValue},
    middleware::Next,
    response::{IntoResponse, Response},
};
use sha2::{Digest, Sha256};

use crate::authorizer::unauthorized;

pub const SECRET_KEY_PREFIX: &str = "phs_";
/// Must match `hash_key_value` in posthog/models/utils.py, which writes `secure_value`.
pub const SECRET_KEY_DIGEST_PREFIX: &str = "sha256$";

/// A generated key has up to 48 characters after the prefix, and a public token has 43 in total.
/// So a run this long marks a key even with no boundary before it, as in `Bearer%20phs_...`.
const SECRET_KEY_RUN: usize = 44;

/// Finds a secret key anywhere in `value`, so that no scheme, quote or encoding can pass one
/// through. A public token that holds `phs_` in the middle does not match.
pub fn find_secret_key(value: &str) -> Option<&str> {
    let is_key_char = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-';
    value
        .match_indices(SECRET_KEY_PREFIX)
        .find_map(|(start, _)| {
            let rest = &value[start..];
            let key = &rest[..rest.find(|c| !is_key_char(c)).unwrap_or(rest.len())];
            let at_boundary = !value[..start].ends_with(is_key_char);
            let long_run = key.len() - SECRET_KEY_PREFIX.len() >= SECRET_KEY_RUN;
            (at_boundary || long_run).then_some(key)
        })
}

/// `DROP_EVENTS_BY_TOKEN` entries have the form `token` or `token:distinct_id`. The authorizer
/// sees only the digest of a secret key, so an entry that holds the key must hold the digest.
pub fn hash_secret_keys_in_drop_list(drop_list: &str) -> String {
    drop_list
        .split(',')
        .map(|entry| match find_secret_key(entry) {
            Some(secret_key) => entry.replacen(secret_key, &hash_secret_key(secret_key), 1),
            None => entry.to_string(),
        })
        .collect::<Vec<_>>()
        .join(",")
}

pub fn is_secret_key_digest(token: &str) -> bool {
    token.starts_with(SECRET_KEY_DIGEST_PREFIX)
}

fn hash_secret_key(secret_key: &str) -> String {
    format!(
        "{SECRET_KEY_DIGEST_PREFIX}{}",
        hex::encode(Sha256::digest(secret_key.as_bytes()))
    )
}

#[cfg(test)]
pub(crate) const EXAMPLE_DIGEST: &str =
    "sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0";

pub async fn hash_secret_keys(mut req: Request<Body>, next: Next) -> Response {
    let mut digest = None;
    for value in req.headers().get_all(header::AUTHORIZATION) {
        let Ok(value) = value.to_str() else { continue };
        // The consumer trusts a digest as much as the key. A sender that learned a digest must not
        // be able to send it in place of the key, so only this layer may write one.
        if value.contains(SECRET_KEY_DIGEST_PREFIX) {
            return unauthorized("Invalid token").into_response();
        }
        if let Some(secret_key) = find_secret_key(value) {
            digest = Some(hash_secret_key(secret_key));
        }
    }

    if let Some(digest) = digest {
        let Ok(value) = HeaderValue::from_str(&format!("Bearer {digest}")) else {
            return unauthorized("Invalid token").into_response();
        };
        req.headers_mut().insert(header::AUTHORIZATION, value);
    }

    next.run(req).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{http::Request, http::StatusCode, routing::post, Router};
    use tower::ServiceExt;

    async fn echo_authorization(req: Request<Body>) -> String {
        req.headers()
            .get_all(header::AUTHORIZATION)
            .iter()
            .map(|v| v.to_str().unwrap())
            .collect::<Vec<_>>()
            .join("|")
    }

    async fn call(authorization: &[&str]) -> (StatusCode, String) {
        let mut builder = Request::builder().method("POST").uri("/x");
        for value in authorization {
            builder = builder.header(header::AUTHORIZATION, *value);
        }
        let response = Router::new()
            .route("/x", post(echo_authorization))
            .layer(axum::middleware::from_fn(hash_secret_keys))
            .oneshot(builder.body(Body::empty()).unwrap())
            .await
            .unwrap();
        let status = response.status();
        let body = axum::body::to_bytes(response.into_body(), 1024)
            .await
            .unwrap();
        (status, String::from_utf8(body.to_vec()).unwrap())
    }

    #[tokio::test]
    async fn a_handler_sees_the_digest_of_a_secret_key_and_never_the_key() {
        let expected = format!("Bearer {EXAMPLE_DIGEST}");
        let cases: &[&[&str]] = &[
            &["Bearer phs_example"],
            &["bearer phs_example"],
            &["phs_example"],
            &["  Bearer   phs_example  "],
            &["Bearer\tphs_example"],
            &["Basic phs_example"],
            &["Token phs_example"],
            &["Bearer,phs_example"],
            &["Bearer Bearer phs_example"],
            &["Bearer \"phs_example\""],
            &["Bearer phc_public", "Bearer phs_example"],
        ];
        for sent in cases {
            assert_eq!(
                call(sent).await,
                (StatusCode::OK, expected.clone()),
                "{sent:?}"
            );
        }
    }

    #[tokio::test]
    async fn a_generated_key_is_hashed_with_no_boundary_before_it() {
        let secret_key = format!("phs_{}", "a1B2".repeat(12));
        let expected = format!("Bearer {}", hash_secret_key(&secret_key));
        for prefix in ["Bearer%20", "Bearer%2520", "Bearer"] {
            let sent = format!("{prefix}{secret_key}");
            assert_eq!(
                call(&[sent.as_str()]).await,
                (StatusCode::OK, expected.clone()),
                "{prefix}"
            );
        }
    }

    #[test]
    fn a_drop_list_entry_with_a_secret_key_holds_its_digest() {
        assert_eq!(
            hash_secret_keys_in_drop_list("phc_public,phs_example,phs_example:user,abcphs_def"),
            format!("phc_public,{EXAMPLE_DIGEST},{EXAMPLE_DIGEST}:user,abcphs_def")
        );
    }

    #[tokio::test]
    async fn a_public_token_passes_unchanged() {
        for sent in ["Bearer phc_public", "Bearer abcphs_def"] {
            assert_eq!(call(&[sent]).await, (StatusCode::OK, sent.to_string()));
        }
    }

    #[tokio::test]
    async fn a_sender_cannot_send_a_digest() {
        let sent_digest = format!("Bearer {EXAMPLE_DIGEST}");
        let nested = format!("Bearer Bearer {EXAMPLE_DIGEST}");
        for sent in [sent_digest.as_str(), nested.as_str(), EXAMPLE_DIGEST] {
            assert_eq!(call(&[sent]).await.0, StatusCode::UNAUTHORIZED, "{sent:?}");
        }
    }
}
