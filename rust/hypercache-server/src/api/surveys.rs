use crate::{
    config_cache::{get_cached_data, CacheNamespace},
    router::State as AppState,
    token::{Token, TokenError},
};
use axum::{
    extract::{Query, State},
    http::{Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde::{Deserialize, Serialize};
use tracing::info;

/// Query parameters for the surveys endpoint.
/// Accepts `token` or `api_key` to identify the project (Django accepts both).
#[derive(Debug, Deserialize, Serialize)]
pub struct SurveysQueryParams {
    pub token: Option<String>,
    pub api_key: Option<String>,
}

/// Form body fields for POST requests (same field names as query params).
#[derive(Debug, Deserialize)]
struct SurveysFormBody {
    token: Option<String>,
    api_key: Option<String>,
}

fn empty_surveys_response() -> Response {
    Json(serde_json::json!({
        "surveys": [],
        "survey_config": null
    }))
    .into_response()
}

/// Surveys endpoint handler
///
/// Serves pre-cached survey definitions from HyperCache. This is a public endpoint
/// that only requires a project API token (no secret key or personal API key).
///
/// Mirrors Django's `POST /api/surveys` behavior:
/// - Token from query param `token` or `api_key` (checked first)
/// - For POST requests, falls back to form-encoded body (`token` or `api_key`)
/// - No authentication beyond token validation
/// - Returns cached `{"surveys": [...], "survey_config": {...}}`
pub async fn surveys_endpoint(
    State(state): State<AppState>,
    Query(params): Query<SurveysQueryParams>,
    method: Method,
    body: axum::body::Bytes,
) -> Response {
    info!(
        method = %method,
        token = ?params.token,
        "Processing surveys request"
    );

    match method {
        Method::HEAD => {
            return (
                StatusCode::OK,
                [("content-type", "application/json")],
                axum::body::Body::empty(),
            )
                .into_response();
        }
        Method::OPTIONS => {
            return (
                StatusCode::NO_CONTENT,
                [("allow", "GET, POST, OPTIONS, HEAD")],
            )
                .into_response();
        }
        _ => {} // GET and POST proceed below
    }

    let token = match extract_token(&params, &method, &body) {
        Ok(t) => t,
        Err(r) => return r,
    };

    let value = match get_cached_data(
        &state.surveys_hypercache_reader,
        state.surveys_negative_cache.as_ref(),
        CacheNamespace::Surveys,
        token.as_str(),
    )
    .await
    {
        Some(v) => v,
        None => return empty_surveys_response(),
    };

    Json(value).into_response()
}

/// Extract and validate the project token from query params or POST form body.
///
/// Priority: query `token` > query `api_key` > form body `token` > form body `api_key`.
#[allow(clippy::result_large_err)]
fn extract_token(
    params: &SurveysQueryParams,
    method: &Method,
    body: &[u8],
) -> Result<Token, Response> {
    // Try query params first
    let raw = params
        .token
        .as_deref()
        .or(params.api_key.as_deref())
        .filter(|s| !s.is_empty());

    // Fall back to form body for POST requests
    let raw = match raw {
        Some(t) => t,
        None if *method == Method::POST => {
            // Borrow ends here — we can't return &str from the parsed body since
            // serde_urlencoded produces owned Strings. Parse inline instead.
            let form: SurveysFormBody =
                serde_urlencoded::from_bytes(body).unwrap_or(SurveysFormBody {
                    token: None,
                    api_key: None,
                });
            let owned = form.token.or(form.api_key).filter(|s| !s.is_empty());
            return match owned {
                Some(t) => Token::parse(&t).map_err(token_error_response),
                None => Err((StatusCode::UNAUTHORIZED, "Token not provided").into_response()),
            };
        }
        None => {
            return Err((StatusCode::UNAUTHORIZED, "Token not provided").into_response());
        }
    };

    Token::parse(raw).map_err(token_error_response)
}

fn token_error_response(e: TokenError) -> Response {
    let status = match e {
        TokenError::Empty => StatusCode::UNAUTHORIZED,
        TokenError::TooLong | TokenError::InvalidCharacters => StatusCode::BAD_REQUEST,
    };
    (status, e.to_string()).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_utils::helpers::*;
    use axum::http::StatusCode;
    use common_redis::MockRedisClient;
    use serde_json::json;

    #[test]
    fn test_query_params_deserialize() {
        let params: SurveysQueryParams = serde_json::from_str(r#"{"token": "phc_test"}"#).unwrap();
        assert_eq!(params.token.as_deref(), Some("phc_test"));
    }

    #[tokio::test]
    async fn test_invalid_token_format_returns_400() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _body) = get(&router, "/api/surveys?token=token.with.dots").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_overlong_token_returns_400() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let long_token = "a".repeat(201);
        let (status, _body) = get(&router, &format!("/api/surveys?token={long_token}")).await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_missing_token_returns_401() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _body) = get(&router, "/api/surveys").await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn test_cache_miss_returns_empty_surveys() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = get(&router, "/api/surveys?token=phc_unknown").await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["surveys"], json!([]));
        assert_eq!(parsed["survey_config"], json!(null));
    }

    #[tokio::test]
    async fn test_cache_hit_returns_survey_data() {
        let token = "phc_test_surveys";
        let key = cache_key("surveys", "surveys.json", token);

        let survey_data = json!({
            "surveys": [{"id": "s1", "name": "NPS", "type": "popover"}],
            "survey_config": {"appearance": {"theme": "light"}}
        });

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&survey_data)));

        let surveys = mock_reader("surveys", "surveys.json", mock);
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = get(&router, &format!("/api/surveys?token={token}")).await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed, survey_data);
    }

    #[tokio::test]
    async fn test_api_key_query_param_works() {
        let token = "phc_apikey_test";
        let key = cache_key("surveys", "surveys.json", token);

        let survey_data = json!({"surveys": [{"id": "s1"}], "survey_config": null});

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&survey_data)));

        let surveys = mock_reader("surveys", "surveys.json", mock);
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = get(&router, &format!("/api/surveys?api_key={token}")).await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed, survey_data);
    }

    #[tokio::test]
    async fn test_post_form_body_token() {
        let token = "phc_form_test";
        let key = cache_key("surveys", "surveys.json", token);

        let survey_data = json!({"surveys": [{"id": "s2"}], "survey_config": null});

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&survey_data)));

        let surveys = mock_reader("surveys", "surveys.json", mock);
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = post_form(&router, "/api/surveys", &format!("token={token}")).await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed, survey_data);
    }

    #[tokio::test]
    async fn test_post_form_body_api_key() {
        let token = "phc_form_apikey";
        let key = cache_key("surveys", "surveys.json", token);

        let survey_data = json!({"surveys": [{"id": "s3"}], "survey_config": null});

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&survey_data)));

        let surveys = mock_reader("surveys", "surveys.json", mock);
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = post_form(&router, "/api/surveys", &format!("api_key={token}")).await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed, survey_data);
    }

    #[tokio::test]
    async fn test_query_param_takes_precedence_over_form_body() {
        let query_token = "phc_query_wins";
        let form_token = "phc_form_loses";

        let key = cache_key("surveys", "surveys.json", query_token);
        let survey_data = json!({"surveys": [{"id": "query"}], "survey_config": null});

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&survey_data)));

        let surveys = mock_reader("surveys", "surveys.json", mock);
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, body) = post_form(
            &router,
            &format!("/api/surveys?token={query_token}"),
            &format!("token={form_token}"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed, survey_data);
    }

    #[tokio::test]
    async fn test_post_no_token_returns_401() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _) = post_form(&router, "/api/surveys", "other_field=value").await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn test_negative_cache_short_circuits_surveys_miss() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let (router, surveys_nc, _config_nc) = test_router_with_negative_cache(surveys, config);

        let token = "phc_neg_cache_test";

        // First request: cache miss → populates negative cache, returns empty surveys
        let (status, body) = get(&router, &format!("/api/surveys?token={token}")).await;
        assert_eq!(status, StatusCode::OK);
        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["surveys"], json!([]));
        assert!(
            surveys_nc.contains(token),
            "miss should populate surveys negative cache"
        );

        // Second request: negative cache hit → returns empty without hitting Redis
        let (status2, body2) = get(&router, &format!("/api/surveys?token={token}")).await;
        assert_eq!(status2, StatusCode::OK);
        let parsed2: serde_json::Value = serde_json::from_str(&body2).unwrap();
        assert_eq!(parsed2["surveys"], json!([]));
    }
}
