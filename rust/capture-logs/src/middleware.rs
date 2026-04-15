//! Request-shaping middleware for the logs capture service.
//!
//! posthog-js signals body compression by appending `?compression=gzip-js`
//! (or `?compression=gzip`) to the request URL rather than by setting a
//! `Content-Encoding` header. This module translates that query-string hint
//! into a real `Content-Encoding: gzip` header so the downstream
//! `tower_http::decompression::RequestDecompressionLayer` can decode the
//! body transparently, without any handler-level changes.

use axum::{
    body::Body,
    extract::Request,
    http::{header, HeaderValue},
    middleware::Next,
    response::Response,
};

const COMPRESSION_QUERY_KEY: &str = "compression";

/// Axum middleware: if the URI query contains `compression=gzip-js` or
/// `compression=gzip` and the request does not already carry a
/// `Content-Encoding` header, inject `Content-Encoding: gzip` so the
/// downstream decompression layer runs.
///
/// Any other value (e.g. `base64`, `lz64`) is left alone — those are not
/// supported by `capture-logs` today and must surface as a normal
/// decoding failure in the handler rather than being silently mistranslated.
pub async fn translate_compression_query_param(mut req: Request<Body>, next: Next) -> Response {
    if req.headers().contains_key(header::CONTENT_ENCODING) {
        return next.run(req).await;
    }

    let Some(query) = req.uri().query() else {
        return next.run(req).await;
    };

    let is_gzip = query
        .split('&')
        .filter_map(|pair| pair.split_once('='))
        .any(|(k, v)| k == COMPRESSION_QUERY_KEY && (v == "gzip-js" || v == "gzip"));

    if is_gzip {
        req.headers_mut()
            .insert(header::CONTENT_ENCODING, HeaderValue::from_static("gzip"));
    }

    next.run(req).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
        routing::post,
        Router,
    };
    use tower::ServiceExt;

    async fn echo_encoding(req: Request<Body>) -> String {
        req.headers()
            .get(header::CONTENT_ENCODING)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("none")
            .to_string()
    }

    fn router() -> Router {
        Router::new()
            .route("/x", post(echo_encoding))
            .layer(axum::middleware::from_fn(translate_compression_query_param))
    }

    async fn call(uri: &str, headers: &[(&str, &str)]) -> (StatusCode, String) {
        let mut builder = Request::builder().method("POST").uri(uri);
        for (k, v) in headers {
            builder = builder.header(*k, *v);
        }
        let req = builder.body(Body::empty()).unwrap();
        let resp = router().oneshot(req).await.unwrap();
        let status = resp.status();
        let bytes = axum::body::to_bytes(resp.into_body(), 1024).await.unwrap();
        (status, String::from_utf8(bytes.to_vec()).unwrap())
    }

    #[tokio::test]
    async fn translates_compression_query_param() {
        #[allow(clippy::type_complexity)]
        let cases: &[(&str, &str, &[(&str, &str)], &str)] = &[
            (
                "injects gzip for gzip-js",
                "/x?compression=gzip-js",
                &[],
                "gzip",
            ),
            (
                "injects gzip for plain gzip",
                "/x?compression=gzip",
                &[],
                "gzip",
            ),
            ("leaves request alone when no query", "/x", &[], "none"),
            (
                "leaves request alone for unrelated params",
                "/x?token=abc&ver=1.2.3",
                &[],
                "none",
            ),
            (
                "does not touch unsupported values",
                "/x?compression=base64",
                &[],
                "none",
            ),
            (
                "preserves existing content-encoding header",
                "/x?compression=gzip-js",
                &[("content-encoding", "deflate")],
                "deflate",
            ),
            (
                "finds compression among many params",
                "/x?token=abc&ip=0&_=123&compression=gzip-js&ver=1.2.3",
                &[],
                "gzip",
            ),
        ];

        for (name, uri, headers, expected) in cases {
            let (status, body) = call(uri, headers).await;
            assert_eq!(status, StatusCode::OK, "{name}");
            assert_eq!(&body, expected, "{name}");
        }
    }
}
