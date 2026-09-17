//! Embedded single-page UI, served at `/` behind the same identity middleware as
//! the API. It only ever calls `/api/v1/*`.

use axum::http::{header, HeaderValue};
use axum::response::{Html, IntoResponse, Response};
use once_cell::sync::Lazy;
use std::hash::{DefaultHasher, Hash, Hasher};

const INDEX: &str = include_str!("ui/index.html");

/// Identifies the page this binary serves. It is derived from the page itself rather than
/// from the process, so every replica of one build agrees on it (a per-process value would
/// make a browser that alternates between pods reload forever). DefaultHasher is not stable
/// across Rust versions, which is fine: every replica runs the same binary.
pub static BUILD_TOKEN: Lazy<HeaderValue> = Lazy::new(|| {
    let mut h = DefaultHasher::new();
    env!("CARGO_PKG_VERSION").hash(&mut h);
    INDEX.hash(&mut h);
    HeaderValue::from_str(&format!(
        "{}-{:016x}",
        env!("CARGO_PKG_VERSION"),
        h.finish()
    ))
    .expect("version and hex are ASCII")
});

pub async fn index() -> Response {
    // The page changes with every deploy; never let a browser keep a stale copy.
    ([(header::CACHE_CONTROL, "no-cache")], Html(INDEX)).into_response()
}
