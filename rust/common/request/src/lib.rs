use axum::http::{HeaderMap, Method};
use bytes::Bytes;
use serde::{Deserialize, Serialize};
use std::net::IpAddr;
use uuid::Uuid;

#[derive(Clone, Deserialize, Default)]
pub struct FlagsQueryParams {
    /// Optional API version identifier
    #[serde(alias = "v")]
    pub version: Option<String>,

    /// Compression type for the incoming request
    pub compression: Option<Compression>,

    /// Library version (alias: "ver")
    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    /// Optional timestamp indicating when the request was sent
    #[serde(alias = "_")]
    pub sent_at: Option<i64>,

    /// Optional personal API key.
    pub personal_api_key: Option<String>,

    /// Optional secret API key.
    pub secret_api_key: Option<String>,

    /// Whether to send cohorts to the client. Only applies to the flags definition endpoint.
    pub send_cohorts: Option<bool>,
}

/// Represents information about the request.
pub struct RequestInfo {
    /// Request ID
    pub id: Uuid,

    /// Client IP
    pub ip: IpAddr,

    /// HTTP headers
    pub headers: HeaderMap,

    /// Query params (contains compression, library version, etc.)
    pub meta: FlagsQueryParams,

    /// Raw request body
    pub body: Bytes,

    /// HTTP method
    pub method: Method,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
    #[serde(rename = "base64")]
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Base64 => "base64",
            Compression::Unsupported => "unsupported",
        }
    }
}
