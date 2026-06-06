use axum::body::Body;
use axum::extract::{MatchedPath, Query as AxumQuery, State};
use axum::http::{header, HeaderMap, Method};
use axum::response::IntoResponse;
use axum_client_ip::InsecureClientIp;

use super::constants::{CAPTURE_V1_PATH, CAPTURE_V1_PATH_TRAILING};
use super::query::Query;
use super::types::Batch;
use tracing::Level;

use crate::v1::constants::*;
use crate::v1::context::Context;
use crate::{ctx_log, log_stat_error, router, v1};

pub async fn handle_request(
    state: State<router::State>,
    headers: HeaderMap,
    query: AxumQuery<Query>,
    ip: InsecureClientIp,
    method: Method,
    path: MatchedPath,
    body: Body,
) -> Result<axum::response::Response, v1::Error> {
    let static_path: &'static str = match path.as_str() {
        CAPTURE_V1_PATH => CAPTURE_V1_PATH,
        CAPTURE_V1_PATH_TRAILING => CAPTURE_V1_PATH_TRAILING,
        other => {
            tracing::warn!(path = other, "unexpected matched path");
            CAPTURE_V1_PATH
        }
    };
    let mut context = Context::new(&headers, &ip, &query, method.clone(), static_path)
        .map_err(|err| log_and_return_header_error(err, &headers, &ip, &query, &method, &path))?;

    // TODO: purposely chatty, for now
    ctx_log!(Level::INFO, context, "handle_request called");

    let raw_bytes = v1::util::extract_body_with_timeout(
        body,
        state.capture_v1_max_compressed_body_bytes,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        context.path,
    )
    .await
    .map_err(|err| {
        log_stat_error!(err, &context);
        err
    })?;

    let payload = v1::util::decompress_payload(
        context.content_encoding.as_deref(),
        raw_bytes,
        state.capture_v1_max_decompressed_body_bytes,
        state.body_read_chunk_size_kb,
    )
    .await
    .map_err(|err| {
        log_stat_error!(err, &context);
        err
    })?;

    let batch: Batch = serde_json::from_slice(&payload).map_err(|e| {
        let err = v1::Error::RequestParsingError(e.to_string());
        log_stat_error!(err, &context);
        err
    })?;

    match super::process::process_batch(&state, &mut context, batch).await {
        Ok(resp) => Ok(resp.into_response()),
        Err(err) => {
            log_stat_error!(err, &context);
            Err(err)
        }
    }
}

/// Logs a header-validation error before a Context could be constructed.
/// Manually extracts raw header values for structured logging, then bumps
/// the error metric with no Context path (falls back to "unknown").
fn log_and_return_header_error(
    err: v1::Error,
    headers: &HeaderMap,
    ip: &InsecureClientIp,
    query: &AxumQuery<Query>,
    method: &Method,
    path: &MatchedPath,
) -> v1::Error {
    let token = raw_header_str(headers, header::AUTHORIZATION.as_str());
    let request_id = raw_header_str(headers, POSTHOG_REQUEST_ID);
    let sdk_info = raw_header_str(headers, POSTHOG_SDK_INFO);
    let attempt = raw_header_str(headers, POSTHOG_ATTEMPT);
    let client_ts = raw_header_str(headers, POSTHOG_REQUEST_TIMESTAMP);
    let user_agent = raw_header_str(headers, "user-agent");
    let content_type = raw_header_str(headers, "content-type");
    let content_encoding = raw_header_str(headers, "content-encoding");

    let msg = format!("{}: {err:#}", err.tag());
    match err.log_level() {
        Level::WARN => tracing::warn!(
            token = %token,
            request_id = %request_id,
            sdk_info = %sdk_info,
            attempt = %attempt,
            client_timestamp = %client_ts,
            user_agent = %user_agent,
            content_type = %content_type,
            content_encoding = %content_encoding,
            client_ip = %ip.0,
            method = %method,
            query = ?query.0,
            path = %path.as_str(),
            "{}", msg
        ),
        _ => tracing::error!(
            token = %token,
            request_id = %request_id,
            sdk_info = %sdk_info,
            attempt = %attempt,
            client_timestamp = %client_ts,
            user_agent = %user_agent,
            content_type = %content_type,
            content_encoding = %content_encoding,
            client_ip = %ip.0,
            method = %method,
            query = ?query.0,
            path = %path.as_str(),
            "{}", msg
        ),
    }
    err.stat_error(None::<&Context>);
    err
}

fn raw_header_str<'a>(headers: &'a HeaderMap, name: &str) -> &'a str {
    headers
        .get(name)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("absent")
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use axum::Router;
    use tower::ServiceExt;
    use uuid::Uuid;

    use crate::router;
    use crate::v1::analytics::constants::CAPTURE_V1_PATH;
    use crate::v1::constants::*;
    use crate::v1::test_utils::{batch_payload, compressed_payload, valid_event, TestStateBuilder};

    fn test_app(state: router::State) -> Router {
        Router::new()
            .route(CAPTURE_V1_PATH, axum::routing::post(super::handle_request))
            .layer(axum::middleware::from_fn(
                super::super::router::v1_common_headers,
            ))
            .with_state(state)
    }

    fn valid_request() -> axum::http::request::Builder {
        Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rust/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
    }

    async fn response_json(resp: axum::response::Response) -> serde_json::Value {
        let bytes = axum::body::to_bytes(resp.into_body(), 1024 * 1024)
            .await
            .unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[tokio::test]
    async fn happy_path_single_event() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let event = valid_event();
        let uuid = event.uuid.clone();
        let payload = batch_payload(&[event]);

        let resp = app
            .oneshot(valid_request().body(Body::from(payload)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = response_json(resp).await;
        let results = body["results"].as_object().unwrap();
        assert_eq!(results[&uuid]["result"], "ok");
    }

    #[tokio::test]
    async fn happy_path_batch() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let events = vec![valid_event(), valid_event(), valid_event()];
        let uuids: Vec<String> = events.iter().map(|e| e.uuid.clone()).collect();
        let payload = batch_payload(&events);

        let resp = app
            .oneshot(valid_request().body(Body::from(payload)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::OK);
        let body = response_json(resp).await;
        let results = body["results"].as_object().unwrap();
        for uuid in &uuids {
            assert_eq!(results[uuid]["result"], "ok");
        }
    }

    #[tokio::test]
    async fn missing_authorization() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let payload = batch_payload(&[valid_event()]);
        let req = Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rust/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
            .body(Body::from(payload))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn missing_required_headers() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let payload = batch_payload(&[valid_event()]);
        // Only Authorization and Content-Type — missing SDK-Info, Attempt, etc.
        let req = Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("X-Forwarded-For", "127.0.0.1")
            .header("User-Agent", "test-agent/1.0")
            .body(Body::from(payload))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn empty_body() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let resp = app
            .oneshot(valid_request().body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn malformed_json() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let garbage = b"not json at all {{{".to_vec();
        let resp = app
            .oneshot(valid_request().body(Body::from(garbage)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn empty_batch() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let payload = br#"{"created_at":"2026-03-19T14:30:00Z","batch":[]}"#.to_vec();
        let resp = app
            .oneshot(valid_request().body(Body::from(payload)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn gzip_compressed_payload() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let event = valid_event();
        let uuid = event.uuid.clone();
        let raw = batch_payload(&[event]);
        let compressed = compressed_payload(&raw, "gzip");

        let req = Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("Content-Encoding", "gzip")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rust/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
            .body(Body::from(compressed))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let body = response_json(resp).await;
        assert_eq!(body["results"][&uuid]["result"], "ok");
    }

    #[tokio::test]
    async fn zstd_compressed_payload() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let event = valid_event();
        let uuid = event.uuid.clone();
        let raw = batch_payload(&[event]);
        let compressed = compressed_payload(&raw, "zstd");

        let req = Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("Content-Encoding", "zstd")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rust/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
            .body(Body::from(compressed))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let body = response_json(resp).await;
        assert_eq!(body["results"][&uuid]["result"], "ok");
    }

    #[tokio::test]
    async fn unsupported_encoding() {
        let ts = TestStateBuilder::new().build();
        let app = test_app(ts.state);

        let payload = batch_payload(&[valid_event()]);
        let req = Request::builder()
            .method("POST")
            .uri(CAPTURE_V1_PATH)
            .header("Authorization", "Bearer phc_test_token")
            .header("Content-Type", "application/json")
            .header("Content-Encoding", "lz4")
            .header("X-Forwarded-For", "127.0.0.1")
            .header(POSTHOG_SDK_INFO, "posthog-rust/1.0.0")
            .header(POSTHOG_ATTEMPT, "1")
            .header(POSTHOG_REQUEST_ID, Uuid::new_v4().to_string())
            .header(POSTHOG_REQUEST_TIMESTAMP, "2026-03-19T14:30:00Z")
            .header("User-Agent", "test-agent/1.0")
            .body(Body::from(payload))
            .unwrap();

        let resp = app.oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);
    }

    #[tokio::test]
    async fn service_unavailable_no_sink() {
        let mut ts = TestStateBuilder::new().build();
        ts.state.v1_sink_router = None;
        let app = test_app(ts.state);

        let payload = batch_payload(&[valid_event()]);
        let resp = app
            .oneshot(valid_request().body(Body::from(payload)).unwrap())
            .await
            .unwrap();

        assert_eq!(resp.status(), StatusCode::SERVICE_UNAVAILABLE);
    }
}
