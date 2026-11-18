//! Embedded single-page UI, served at `/` behind the same identity middleware as
//! the API. It only ever calls `/api/v1/*`.

use axum::http::{header, HeaderValue};
use axum::response::{Html, IntoResponse, Response};

const INDEX: &str = include_str!("ui/index.html");

/// Identifies the build this process runs, so every replica of one build agrees on it (a
/// per-process value would make a browser that alternates between pods reload forever) and a
/// backend-only change still gets a new value. `build.rs` derives it from the crate sources.
pub static BUILD_TOKEN: HeaderValue = HeaderValue::from_static(concat!(
    env!("CARGO_PKG_VERSION"),
    "-",
    env!("PGAPI_BUILD_HASH")
));

pub async fn index() -> Response {
    // The page changes with every deploy; never let a browser keep a stale copy.
    ([(header::CACHE_CONTROL, "no-cache")], Html(INDEX)).into_response()
}
