//! Embedded single-page UI, served at `/` behind the same identity middleware as
//! the API. It only ever calls `/api/v1/*`.

use axum::http::{header, HeaderValue};
use axum::response::{Html, IntoResponse, Response};
use once_cell::sync::Lazy;
use std::hash::{DefaultHasher, Hash, Hasher};

const INDEX: &str = include_str!("ui/index.html");

/// Identifies the build this process runs. It is a hash of the executable, so every replica
/// of one build agrees on it (a per-process value would make a browser that alternates between
/// pods reload forever) and a backend-only change still gets a new value. No build id reaches
/// the image build, so the binary is the only per-build identity available. DefaultHasher is
/// not stable across Rust versions, which is fine: every replica runs the same binary. If the
/// executable cannot be read, the embedded page stands in for it.
pub static BUILD_TOKEN: Lazy<HeaderValue> = Lazy::new(|| {
    let mut h = DefaultHasher::new();
    env!("CARGO_PKG_VERSION").hash(&mut h);
    match std::env::current_exe().and_then(std::fs::read) {
        Ok(bytes) => bytes.hash(&mut h),
        Err(e) => {
            tracing::warn!(error = %e, "cannot read the executable; build token falls back to the page hash");
            INDEX.hash(&mut h)
        }
    }
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
