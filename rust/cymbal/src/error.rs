use aws_sdk_s3::primitives::ByteStreamError;
use rdkafka::error::KafkaError;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("Serde error: {0}")]
    SerdeError(#[from] serde_json::Error),
    #[error("Config error: {0}")]
    ConfigError(#[from] envconfig::Error),
    #[error("Kafka error: {0}")]
    KafkaError(#[from] KafkaError),
    #[error("Sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error(transparent)]
    ResolutionError(#[from] ResolutionError),
    #[error(transparent)]
    S3Error(#[from] aws_sdk_s3::Error),
    #[error(transparent)]
    ByteStreamError(#[from] ByteStreamError), // AWS specific bytestream error. Idk
}

// These are errors that occur during frame resolution. This excludes e.g. network errors,
// which are handled by the store - this is the error type that's handed to the frame to see
// if it can still make something useful out of it.
// NOTE - these are serialized and deserialized, so that when we fail to get a symbol set from
// some provider (e.g. we fail to look up a sourcemap), we can return the correct error in the future
// without hitting their infra again (by storing it in PG).
#[derive(Debug, Error, Serialize, Deserialize)]
pub enum ResolutionError {
    #[error(transparent)]
    JavaScript(#[from] JsResolveErr),
}

#[derive(Debug, Error, Serialize, Deserialize)]
pub enum JsResolveErr {
    // The frame has no source url. This might indicate it needs no further processing, who knows
    #[error("No source url found")]
    NoSourceUrl,
    // We failed to parse a found source map
    #[error("Invalid source map: {0}")]
    InvalidSourceMap(String),
    // We found and parsed the source map, but couldn't find our frames token in it
    #[error("Token not found for frame: {0}:{1}:{2}")]
    TokenNotFound(String, u32, u32),
    // We couldn't parse the source url of the frame
    #[error("Invalid source url: {0}")]
    InvalidSourceUrl(String),
    // We couldn't find a sourcemap associated with the frames source url, after
    // fetching the source, in either the headers or body. This might indicate
    // the frame is not minified
    #[error("Could not find sourcemap for source url: {0}")]
    NoSourcemap(String),
    // We made a request to the source URL, and got a source
    // map header, but couldn't parse it to a utf8 string
    #[error("Could not parse source-map header from url {0}")]
    InvalidSourceMapHeader(String),
    // We found a source map url, in the headers or body
    // of the response from the source url, but couldn't
    // parse it to a URL to actually fetch the source map
    #[error("Invalid source url: {0}")]
    InvalidSourceMapUrl(String),
    // For timeout errors when fetching source or sourcemap
    #[error("Request timed out while fetching: {0}")]
    Timeout(String),
    // For when the server returns a non-200 status code
    #[error("HTTP error {0} while fetching: {1}")]
    HttpStatus(u16, String),
    // For DNS/connection/TLS errors
    #[error("Network error while fetching: {0}")]
    NetworkError(String),
    // For redirect loops or too many redirects
    #[error("Redirect error while fetching: {0}")]
    RedirectError(String),
}

impl From<JsResolveErr> for Error {
    fn from(e: JsResolveErr) -> Self {
        ResolutionError::JavaScript(e).into()
    }
}

impl From<sourcemap::Error> for JsResolveErr {
    fn from(e: sourcemap::Error) -> Self {
        JsResolveErr::InvalidSourceMap(e.to_string())
    }
}

impl From<reqwest::Error> for JsResolveErr {
    fn from(e: reqwest::Error) -> Self {
        if e.is_timeout() {
            return JsResolveErr::Timeout(e.to_string());
        }

        if e.is_status() {
            let status = e.status().unwrap();
            return JsResolveErr::HttpStatus(status.as_u16(), e.to_string());
        }

        if e.is_redirect() {
            return JsResolveErr::RedirectError(e.to_string());
        }

        // For connect errors, DNS errors, TLS errors, etc.
        if e.is_connect() || e.is_request() || e.is_builder() {
            return JsResolveErr::NetworkError(e.to_string());
        }

        // Fallback for any other errors
        JsResolveErr::NetworkError(e.to_string())
    }
}
