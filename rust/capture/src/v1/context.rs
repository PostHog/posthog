use std::net::IpAddr;

use axum::extract::Query as AxumQuery;
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::token::validate_token;
use crate::v1::analytics::header::*;
use crate::v1::analytics::query::Query;
use crate::v1::Error;

const REQUIRED_HEADERS: &[&str] = &[
    POSTHOG_API_TOKEN,
    POSTHOG_SDK_INFO,
    POSTHOG_ATTEMPT,
    POSTHOG_REQUEST_ID,
    POSTHOG_CLIENT_TIMESTAMP,
    "content-type",
    "user-agent",
];

#[derive(Debug)]
pub struct Context {
    pub api_token: String,
    pub authorization: Option<String>,
    pub user_agent: String,
    pub content_type: String,
    pub content_encoding: Option<String>,
    pub sdk_info: String,
    pub attempt: u32,
    pub request_id: Uuid,
    pub client_timestamp: DateTime<Utc>,
    pub client_ip: IpAddr,
    pub query: Query,
    pub method: Method,
    pub path: String,
    pub server_received_at: DateTime<Utc>,
    pub created_at: Option<String>,
    pub capture_internal: bool,
    pub historical_migration: bool,
}

/// Extracts a required header as &str, assuming presence was already checked.
fn header_str<'a>(headers: &'a HeaderMap, name: &str) -> Result<&'a str, Error> {
    headers
        .get(name)
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| {
            Error::InvalidHeaderValue(format!("{name} contains non-visible ASCII characters"))
        })
}

impl Context {
    pub fn clock_skew(&self) -> chrono::Duration {
        self.client_timestamp
            .signed_duration_since(self.server_received_at)
    }

    pub fn new(
        headers: &HeaderMap,
        ip: &InsecureClientIp,
        query: &AxumQuery<Query>,
        method: Method,
        path: &str,
    ) -> Result<Self, Error> {
        // Missing-headers gate: collect all absent required headers at once
        let missing: Vec<String> = REQUIRED_HEADERS
            .iter()
            .filter(|name| headers.get(**name).is_none())
            .map(|name| name.to_string())
            .collect();

        if !missing.is_empty() {
            return Err(Error::MissingRequiredHeaders(missing));
        }

        // All required headers are present — validate each one

        let token_raw = header_str(headers, POSTHOG_API_TOKEN)?;
        validate_token(token_raw).map_err(|reason| Error::InvalidApiToken(reason.to_string()))?;
        let api_token = token_raw.to_string();

        let authorization = match headers.get("authorization") {
            Some(val) => {
                let val_str = val.to_str().map_err(|_| {
                    Error::InvalidHeaderValue(
                        "Authorization contains non-visible ASCII characters".into(),
                    )
                })?;
                if let Some(token) = val_str.strip_prefix("Bearer ") {
                    Some(token.to_string())
                } else {
                    return Err(Error::InvalidHeaderValue(
                        "Authorization must use Bearer scheme".into(),
                    ));
                }
            }
            None => None,
        };

        let content_type_raw = header_str(headers, "content-type")?;
        let mime_type = content_type_raw
            .split(';')
            .next()
            .unwrap_or("")
            .trim()
            .to_ascii_lowercase();
        if mime_type != "application/json" {
            return Err(Error::UnsupportedContentType(content_type_raw.to_string()));
        }
        let content_type = content_type_raw.to_string();

        let content_encoding = match headers.get("content-encoding") {
            Some(val) => {
                let enc = val.to_str().map_err(|_| {
                    Error::InvalidHeaderValue(
                        "Content-Encoding contains non-visible ASCII characters".into(),
                    )
                })?;
                if !SUPPORTED_ENCODINGS.contains(&enc) {
                    return Err(Error::UnsupportedEncoding(enc.to_string()));
                }
                Some(enc.to_string())
            }
            None => None,
        };

        let request_id_raw = header_str(headers, POSTHOG_REQUEST_ID)?;
        let request_id = Uuid::parse_str(request_id_raw).map_err(|_| {
            Error::InvalidHeaderValue(format!(
                "{POSTHOG_REQUEST_ID} is not a valid UUID: {request_id_raw}"
            ))
        })?;

        let attempt_raw = header_str(headers, POSTHOG_ATTEMPT)?;
        let attempt: u32 = attempt_raw
            .parse::<u32>()
            .ok()
            .filter(|&n| n >= 1)
            .ok_or_else(|| {
                Error::InvalidHeaderValue(format!(
                    "{POSTHOG_ATTEMPT} must be a positive integer: {attempt_raw}"
                ))
            })?;

        let client_ts_raw = header_str(headers, POSTHOG_CLIENT_TIMESTAMP)?;
        let client_timestamp: DateTime<Utc> = DateTime::parse_from_rfc3339(client_ts_raw)
            .map(|dt| dt.with_timezone(&Utc))
            .map_err(|_| {
                Error::InvalidHeaderValue(format!(
                    "{POSTHOG_CLIENT_TIMESTAMP} is not valid RFC 3339: {client_ts_raw}"
                ))
            })?;

        let user_agent = header_str(headers, "user-agent")?.to_string();
        let sdk_info = header_str(headers, POSTHOG_SDK_INFO)?.to_string();

        Ok(Self {
            api_token,
            authorization,
            user_agent,
            content_type,
            content_encoding,
            sdk_info,
            attempt,
            request_id,
            client_timestamp,
            client_ip: ip.0,
            query: query.0.clone(),
            method,
            path: path.to_string(),
            server_received_at: Utc::now(),
            created_at: None,
            capture_internal: false,
            historical_migration: false,
        })
    }

    pub fn set_batch_metadata(&mut self, batch: &crate::v1::analytics::types::Batch) {
        self.created_at = Some(batch.created_at.clone());
        self.capture_internal = batch.capture_internal.unwrap_or(false);
        self.historical_migration = batch.historical_migration;
    }
}

#[cfg(test)]
mod tests {
    use std::net::{IpAddr, Ipv4Addr};

    use axum::extract::Query as AxumQuery;
    use axum::http::{HeaderMap, HeaderValue, Method};
    use axum_client_ip::InsecureClientIp;
    use uuid::Uuid;

    use super::*;

    fn test_context(headers: &HeaderMap) -> Result<Context, Error> {
        Context::new(
            headers,
            &InsecureClientIp(IpAddr::V4(Ipv4Addr::LOCALHOST)),
            &AxumQuery(Query::default()),
            Method::POST,
            crate::v1::analytics::router::CAPTURE_V1_PATH,
        )
    }

    fn valid_headers() -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert(
            POSTHOG_API_TOKEN,
            HeaderValue::from_static("phc_test_token_123"),
        );
        h.insert(
            POSTHOG_SDK_INFO,
            HeaderValue::from_static("posthog-rust/1.0.0"),
        );
        h.insert(POSTHOG_ATTEMPT, HeaderValue::from_static("1"));
        h.insert(
            POSTHOG_REQUEST_ID,
            HeaderValue::from_str(&Uuid::new_v4().to_string()).unwrap(),
        );
        h.insert(
            POSTHOG_CLIENT_TIMESTAMP,
            HeaderValue::from_static("2025-01-15T10:30:00Z"),
        );
        h.insert("content-type", HeaderValue::from_static("application/json"));
        h.insert("user-agent", HeaderValue::from_static("test-agent/1.0"));
        h
    }

    #[test]
    fn all_valid_headers_returns_ok() {
        let headers = valid_headers();
        let ctx = test_context(&headers);
        assert!(ctx.is_ok());
        let ctx = ctx.unwrap();
        assert_eq!(ctx.api_token, "phc_test_token_123");
        assert_eq!(ctx.attempt, 1);
        assert_eq!(ctx.content_type, "application/json");
        assert!(ctx.authorization.is_none());
        assert!(ctx.content_encoding.is_none());
        assert!(ctx.created_at.is_none());
        assert!(!ctx.capture_internal);
        assert!(!ctx.historical_migration);
    }

    #[test]
    fn missing_single_required_header() {
        let mut headers = valid_headers();
        headers.remove(POSTHOG_API_TOKEN);
        let err = test_context(&headers).unwrap_err();
        match err {
            Error::MissingRequiredHeaders(names) => {
                assert_eq!(names, vec![POSTHOG_API_TOKEN]);
            }
            other => panic!("expected MissingRequiredHeaders, got: {other:?}"),
        }
    }

    #[test]
    fn missing_multiple_required_headers() {
        let mut headers = valid_headers();
        headers.remove(POSTHOG_API_TOKEN);
        headers.remove("user-agent");
        let err = test_context(&headers).unwrap_err();
        match err {
            Error::MissingRequiredHeaders(names) => {
                assert!(names.contains(&POSTHOG_API_TOKEN.to_string()));
                assert!(names.contains(&"user-agent".to_string()));
                assert_eq!(names.len(), 2);
            }
            other => panic!("expected MissingRequiredHeaders, got: {other:?}"),
        }
    }

    #[test]
    fn invalid_token_returns_error() {
        let mut headers = valid_headers();
        headers.insert(
            POSTHOG_API_TOKEN,
            HeaderValue::from_static("phx_personal_key"),
        );
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidApiToken(_)));
    }

    #[test]
    fn bad_authorization_format() {
        let mut headers = valid_headers();
        headers.insert("authorization", HeaderValue::from_static("Basic abc123"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidHeaderValue(_)));
    }

    #[test]
    fn valid_bearer_authorization() {
        let mut headers = valid_headers();
        headers.insert("authorization", HeaderValue::from_static("Bearer my_token"));
        let ctx = test_context(&headers).unwrap();
        assert_eq!(ctx.authorization, Some("my_token".to_string()));
    }

    #[test]
    fn wrong_content_type() {
        let mut headers = valid_headers();
        headers.insert("content-type", HeaderValue::from_static("text/plain"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::UnsupportedContentType(_)));
    }

    #[test]
    fn content_type_with_charset() {
        let mut headers = valid_headers();
        headers.insert(
            "content-type",
            HeaderValue::from_static("application/json; charset=utf-8"),
        );
        let ctx = test_context(&headers).unwrap();
        assert_eq!(ctx.content_type, "application/json; charset=utf-8");
    }

    #[test]
    fn content_type_case_insensitive() {
        let mut headers = valid_headers();
        headers.insert("content-type", HeaderValue::from_static("Application/JSON"));
        let ctx = test_context(&headers).unwrap();
        assert_eq!(ctx.content_type, "Application/JSON");
    }

    #[test]
    fn bad_content_encoding() {
        let mut headers = valid_headers();
        headers.insert("content-encoding", HeaderValue::from_static("lz4"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::UnsupportedEncoding(_)));
    }

    #[test]
    fn valid_content_encoding() {
        let mut headers = valid_headers();
        headers.insert("content-encoding", HeaderValue::from_static("gzip"));
        let ctx = test_context(&headers).unwrap();
        assert_eq!(ctx.content_encoding, Some("gzip".to_string()));
    }

    #[test]
    fn invalid_uuid_request_id() {
        let mut headers = valid_headers();
        headers.insert(POSTHOG_REQUEST_ID, HeaderValue::from_static("not-a-uuid"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidHeaderValue(_)));
    }

    #[test]
    fn non_numeric_attempt() {
        let mut headers = valid_headers();
        headers.insert(POSTHOG_ATTEMPT, HeaderValue::from_static("abc"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidHeaderValue(_)));
    }

    #[test]
    fn zero_attempt_returns_error() {
        let mut headers = valid_headers();
        headers.insert(POSTHOG_ATTEMPT, HeaderValue::from_static("0"));
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidHeaderValue(_)));
    }

    #[test]
    fn invalid_rfc3339_timestamp() {
        let mut headers = valid_headers();
        headers.insert(
            POSTHOG_CLIENT_TIMESTAMP,
            HeaderValue::from_static("not-a-timestamp"),
        );
        let err = test_context(&headers).unwrap_err();
        assert!(matches!(err, Error::InvalidHeaderValue(_)));
    }
}
