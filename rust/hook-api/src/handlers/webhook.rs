use std::collections::HashMap;
use std::time::Instant;

use axum::{extract::State, http::StatusCode, Json};
use hook_common::webhook::{WebhookJobMetadata, WebhookJobParameters};
use serde_derive::Deserialize;
use serde_json::Value;
use url::Url;

use hook_common::pgqueue::{NewJob, PgQueue};
use hook_common::webhook::HttpMethod;
use serde::Serialize;
use tracing::{debug, error};

#[derive(Serialize, Deserialize)]
pub struct WebhookPostResponse {
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// The body of a request made to create a webhook Job.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookPostRequestBody {
    parameters: WebhookJobParameters,
    metadata: WebhookJobMetadata,

    #[serde(default = "default_max_attempts")]
    max_attempts: u32,
}

fn default_max_attempts() -> u32 {
    3
}

pub async fn post_webhook(
    State(pg_queue): State<PgQueue>,
    Json(payload): Json<WebhookPostRequestBody>,
) -> Result<Json<WebhookPostResponse>, (StatusCode, Json<WebhookPostResponse>)> {
    debug!("received payload: {:?}", payload);

    let url_hostname = get_hostname(&payload.parameters.url)?;
    // We could cast to i32, but this ensures we are not wrapping.
    let max_attempts = i32::try_from(payload.max_attempts).map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(WebhookPostResponse {
                error: Some("invalid number of max attempts".to_owned()),
            }),
        )
    })?;
    let job = NewJob::new(
        max_attempts,
        payload.metadata,
        payload.parameters,
        url_hostname.as_str(),
    );

    let start_time = Instant::now();

    pg_queue.enqueue(job).await.map_err(internal_error)?;

    let elapsed_time = start_time.elapsed().as_secs_f64();
    metrics::histogram!("webhook_api_enqueue").record(elapsed_time);

    Ok(Json(WebhookPostResponse { error: None }))
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct HoghookFetchParameters {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub headers: Option<HashMap<String, String>>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub method: Option<HttpMethod>,
}

#[derive(Debug, Serialize, Deserialize)]
struct HoghookArgs(
    String,
    #[serde(default, skip_serializing_if = "Option::is_none")] Option<HoghookFetchParameters>,
);

#[derive(Debug, Serialize, Deserialize)]
struct HoghookAsyncFunctionRequest {
    name: String,
    args: HoghookArgs,
}

pub async fn post_hoghook(
    State(pg_queue): State<PgQueue>,
    Json(payload): Json<Value>,
) -> Result<Json<WebhookPostResponse>, (StatusCode, Json<WebhookPostResponse>)> {
    debug!("received payload: {:?}", payload);

    // We use these fields for metrics in the janitor, but we don't actually need to do anything
    // with them now.
    payload
        .get("teamId")
        .ok_or_else(|| bad_request("missing required field 'teamId'"))?
        .as_number()
        .ok_or_else(|| bad_request("'teamId' is not a number"))?;
    payload
        .get("hogFunctionId")
        .ok_or_else(|| bad_request("missing required field 'hogFunctionId'"))?
        .as_str()
        .ok_or_else(|| bad_request("'hogFunctionId' is not a string"))?;

    // We deserialize a copy of the `asyncFunctionRequest` field here because we want to leave
    // the original payload unmodified so that it can be passed through exactly as it came to us.
    let async_function_request = payload
        .get("asyncFunctionRequest")
        .ok_or_else(|| bad_request("missing required field 'asyncFunctionRequest'"))?
        .clone();
    let async_function_request: HoghookAsyncFunctionRequest =
        serde_json::from_value(async_function_request).map_err(|err| {
            let msg = format!("unable to deserialize 'asyncFunctionRequest': {}", err);
            bad_request(&msg)
        })?;

    if async_function_request.name != "fetch" {
        return Err(bad_request("asyncFunctionRequest.name must be 'fetch'"));
    }

    // Note that the URL is parsed (and thus validated as a valid URL) as part of
    // `get_hostname` below.
    let url = async_function_request.args.0.clone();
    let parameters = if let Some(fetch_options) = async_function_request.args.1 {
        WebhookJobParameters {
            body: fetch_options.body.unwrap_or("".to_owned()),
            headers: fetch_options.headers.unwrap_or_default(),
            method: fetch_options.method.unwrap_or(HttpMethod::POST),
            url,
        }
    } else {
        WebhookJobParameters {
            body: "".to_owned(),
            headers: HashMap::new(),
            method: HttpMethod::POST,
            url,
        }
    };

    let url_hostname = get_hostname(&parameters.url)?;
    let max_attempts = default_max_attempts() as i32;

    let job = NewJob::new(max_attempts, payload, parameters, url_hostname.as_str());

    let start_time = Instant::now();

    pg_queue.enqueue(job).await.map_err(internal_error)?;

    let elapsed_time = start_time.elapsed().as_secs_f64();
    metrics::histogram!("webhook_api_enqueue").record(elapsed_time);

    Ok(Json(WebhookPostResponse { error: None }))
}

fn bad_request(msg: &str) -> (StatusCode, Json<WebhookPostResponse>) {
    error!(msg);
    (
        StatusCode::BAD_REQUEST,
        Json(WebhookPostResponse {
            error: Some(msg.to_owned()),
        }),
    )
}

fn internal_error<E>(err: E) -> (StatusCode, Json<WebhookPostResponse>)
where
    E: std::error::Error,
{
    error!("internal error: {}", err);
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(WebhookPostResponse {
            error: Some(err.to_string()),
        }),
    )
}

fn get_hostname(url_str: &str) -> Result<String, (StatusCode, Json<WebhookPostResponse>)> {
    let url = Url::parse(url_str).map_err(|_| bad_request("could not parse url"))?;

    match url.host_str() {
        Some(hostname) => Ok(hostname.to_owned()),
        None => Err(bad_request("couldn't extract hostname from url")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use axum::{
        body::Body,
        http::{self, Request, StatusCode},
        Router,
    };
    use hook_common::pgqueue::PgQueue;
    use hook_common::webhook::{HttpMethod, WebhookJobParameters};
    use http_body_util::BodyExt;
    use sqlx::PgPool; // for `collect`
    use std::collections;
    use tower::ServiceExt; // for `call`, `oneshot`, and `ready`

    use crate::handlers::app::add_routes;

    const MAX_BODY_SIZE: usize = 1_000_000;

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_success(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let mut headers = collections::HashMap::new();
        headers.insert("Content-Type".to_owned(), "application/json".to_owned());
        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers,
                                method: HttpMethod::POST,
                                url: "http://example.com/".to_owned(),
                                body: r#"{"a": "b"}"#.to_owned(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"{}");
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_bad_url(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers: collections::HashMap::new(),
                                method: HttpMethod::POST,
                                url: "invalid".to_owned(),
                                body: r#"{"a": "b"}"#.to_owned(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_missing_fields(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body("{}".to_owned())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_not_json(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body("x".to_owned())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_body_too_large(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let bytes: Vec<u8> = vec![b'a'; MAX_BODY_SIZE + 1];
        let long_string = String::from_utf8_lossy(&bytes);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers: collections::HashMap::new(),
                                method: HttpMethod::POST,
                                url: "http://example.com".to_owned(),
                                body: long_string.to_string(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
    }

    #[derive(sqlx::FromRow, Debug)]
    struct TestJobRow {
        parameters: Value,
        metadata: Value,
        target: String,
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn hoghook_success(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db.clone()).await;
        let hog_mode = true;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let valid_payloads = vec![
            (
                r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com"]}, "teamId": 1, "hogFunctionId": "abc"}"#,
                r#"{"body": "", "headers": {}, "method": "POST", "url": "http://example.com"}"#,
            ),
            (
                r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com", {"method": "GET"}]}, "teamId": 1, "hogFunctionId": "abc"}"#,
                r#"{"body": "", "headers": {}, "method": "GET", "url": "http://example.com"}"#,
            ),
            (
                r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com", {"body": "hello, world"}]}, "teamId": 1, "hogFunctionId": "abc"}"#,
                r#"{"body": "hello, world", "headers": {}, "method": "POST", "url": "http://example.com"}"#,
            ),
            (
                r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com", {"headers": {"k": "v"}}]}, "teamId": 1, "hogFunctionId": "abc"}"#,
                r#"{"body": "", "headers": {"k": "v"}, "method": "POST", "url": "http://example.com"}"#,
            ),
            (
                r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com", {"method": "GET", "body": "hello, world", "headers": {"k": "v"}}]}, "otherField": true, "teamId": 1, "hogFunctionId": "abc"}"#,
                r#"{"body": "hello, world", "headers": {"k": "v"}, "method": "GET", "url": "http://example.com"}"#,
            ),
        ];

        for (payload, expected_parameters) in valid_payloads {
            let mut headers = collections::HashMap::new();
            headers.insert("Content-Type".to_owned(), "application/json".to_owned());
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method(http::Method::POST)
                        .uri("/hoghook")
                        .header(http::header::CONTENT_TYPE, "application/json")
                        .body(Body::from(payload.to_owned()))
                        .unwrap(),
                )
                .await
                .unwrap();

            assert_eq!(response.status(), StatusCode::OK);

            let body = response.into_body().collect().await.unwrap().to_bytes();
            assert_eq!(&body[..], b"{}");

            let mut conn = db.acquire().await.unwrap();

            let row = sqlx::query_as::<_, TestJobRow>(
                "SELECT parameters, metadata, target FROM job_queue;",
            )
            .fetch_one(&mut *conn)
            .await
            .unwrap();

            assert_eq!(
                row.parameters,
                serde_json::from_str::<Value>(expected_parameters).unwrap()
            );
            assert_eq!(
                row.metadata,
                serde_json::from_str::<Value>(payload).unwrap()
            );
            assert_eq!(row.target, "example.com");

            sqlx::query("DELETE FROM job_queue")
                .execute(&mut *conn)
                .await
                .unwrap();
        }
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn hoghook_bad_requests(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db.clone()).await;
        let hog_mode = true;

        let app = add_routes(Router::new(), pg_queue, hog_mode, MAX_BODY_SIZE);

        let invalid_payloads = vec![
            r#"{}"#,
            r#"{"asyncFunctionRequest":{"teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"not-fetch","args":[]}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch"}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":{}}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":[]}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["not-url"]}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com", {"method": "not-method"}]}, "teamId": 1, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com"]}, "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com"]}, "teamId": "string", "hogFunctionId": "abc"}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com"]}, "teamId": 1}"#,
            r#"{"asyncFunctionRequest":{"name":"fetch","args":["http://example.com"]}, "teamId": 1, "hogFunctionId": 1}"#,
        ];

        for payload in invalid_payloads {
            let mut headers = collections::HashMap::new();
            headers.insert("Content-Type".to_owned(), "application/json".to_owned());
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method(http::Method::POST)
                        .uri("/hoghook")
                        .header(http::header::CONTENT_TYPE, "application/json")
                        .body(Body::from(payload.to_owned()))
                        .unwrap(),
                )
                .await
                .unwrap();

            assert!(
                response.status() == StatusCode::BAD_REQUEST
                    || response.status() == StatusCode::UNPROCESSABLE_ENTITY
            );
        }
    }
}
