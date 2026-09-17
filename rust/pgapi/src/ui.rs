//! Embedded single-page UI, served at `/` behind the same identity middleware as
//! the API. It only ever calls `/api/v1/*`.

use axum::http::header;
use axum::response::{Html, IntoResponse, Response};

pub async fn index() -> Response {
    // The page changes with every deploy; never let a browser keep a stale copy.
    (
        [(header::CACHE_CONTROL, "no-cache")],
        Html(include_str!("ui/index.html")),
    )
        .into_response()
}
