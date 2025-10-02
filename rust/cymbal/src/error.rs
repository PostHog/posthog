use aws_sdk_s3::primitives::ByteStreamError;
use common_geoip::GeoIpError;
use common_kafka::kafka_producer::KafkaProduceError;
use common_redis::CustomRedisError;
use common_types::{CapturedEvent, ClickHouseEvent};
use posthog_symbol_data::SymbolDataError;
use rdkafka::error::KafkaError;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum ResolveError {
    #[error(transparent)]
    UnhandledError(#[from] UnhandledError),
    #[error(transparent)]
    ResolutionError(#[from] FrameError),
}

// An unhandled failure at some stage of the event pipeline, as
// well as the index of the item in the input buffer that caused
// the failure, so we can print the offset of problematic message
#[derive(Debug)]
pub struct PipelineFailure {
    pub index: usize,
    pub error: UnhandledError,
}

// The result of running the pipeline against a single message. Generally,
// an error here indicates some expected/handled invalidity of the input,
// like a missing token, or invalid timestamp. The pipeline converts a
// vector of input items into a vector of these
pub type PipelineResult = Result<ClickHouseEvent, EventError>;

#[derive(Debug, Error)]
pub enum UnhandledError {
    #[error("Config error: {0}")]
    ConfigError(#[from] envconfig::Error),
    #[error("Kafka error: {0}")]
    KafkaError(#[from] KafkaError),
    #[error("Produce error: {0}")]
    KafkaProduceError(#[from] KafkaProduceError),
    #[error("Sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("S3 error: {0}")]
    S3Error(#[from] Box<aws_sdk_s3::Error>),
    #[error(transparent)]
    ByteStreamError(#[from] ByteStreamError), // AWS specific bytestream error. Idk
    #[error("Unhandled serde error: {0}")]
    SerdeError(#[from] serde_json::Error),
    #[error("Unhandled geoip error: {0}")]
    GeoIpError(#[from] GeoIpError),
    #[error("Unhandled redis error: {0}")]
    RedisError(#[from] CustomRedisError),
    #[error("Unhandled error: {0}")]
    Other(String),
}

// These are errors that occur during frame resolution. This excludes e.g. network errors,
// which are handled by the store - this is the error type that's handed to the frame to see
// if it can still make something useful out of it.
// NOTE - these are serialized and deserialized, so that when we fail to get a symbol set from
// some provider (e.g. we fail to look up a sourcemap), we can return the correct error in the future
// without hitting their infra again (by storing it in PG).
#[derive(Debug, Error, Serialize, Deserialize)]
pub enum FrameError {
    #[error(transparent)]
    JavaScript(#[from] JsResolveErr),
    #[error(transparent)]
    Hermes(#[from] HermesError),
    #[error("No symbol set for chunk id: {0}")]
    MissingChunkIdData(String),
}

#[derive(Debug, Error, Serialize, Deserialize)]
pub enum JsResolveErr {
    #[error("This frame had no source url or chunk id")]
    NoUrlOrChunkId,
    // The frame has no source url. This might indicate it needs no further processing, who knows
    #[error("No source url found")]
    NoSourceUrl, // Deprecated, use NoUrlOrChunkId instead
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
    #[error("JSDataError: {0}")]
    JSDataError(#[from] SymbolDataError),
    #[error("Invalid Source and Map")]
    InvalidSourceAndMap,
    #[error("Invalid data url found at {0}. {1}")]
    InvalidDataUrl(String, String),
    #[error("No sourcemap uploaded for chunk id: {0}")]
    NoSourcemapUploaded(String),
}

#[derive(Debug, Error, Serialize, Deserialize)]
pub enum HermesError {
    #[error("Data error: {0}")]
    DataError(#[from] SymbolDataError),
    #[error("Invalid map: {0}")]
    InvalidMap(String),
    #[error("No sourcemap uploaded for chunk id: {0}")]
    NoSourcemapUploaded(String),
    #[error("No chunk id sent with frame")]
    NoChunkId,
    #[error("No token for column {0} on chunk {1}")]
    NoTokenForColumn(u32, String),
}

#[derive(Debug, Error, Clone)]
pub enum EventError {
    #[error("Wrong event type: {0} for event {1}")]
    WrongEventType(String, Uuid),
    #[error("No properties: {0}")]
    NoProperties(Uuid),
    #[error("Invalid properties: {0}, serde error: {1}")]
    InvalidProperties(Uuid, String),
    #[error("Empty exception list: {0}")]
    EmptyExceptionList(Uuid),
    #[error("Invalid event timestamp: {0}, {1}")]
    InvalidTimestamp(String, String),
    #[error("No team for token: {0}")]
    NoTeamForToken(String),
    #[error("Suppressed issue: {0}")]
    Suppressed(Uuid),
    #[error("Could not deserialize event data: {1}")]
    FailedToDeserialize(Box<CapturedEvent>, String),
    #[error("Filtered by team id")]
    FilteredByTeamId,
}

impl From<JsResolveErr> for ResolveError {
    fn from(e: JsResolveErr) -> Self {
        FrameError::JavaScript(e).into()
    }
}

impl From<HermesError> for ResolveError {
    fn from(e: HermesError) -> Self {
        FrameError::Hermes(e).into()
    }
}

impl From<FrameError> for UnhandledError {
    fn from(e: FrameError) -> Self {
        // TODO - this should be unreachable, but I need to reconsider the error enum structure to make it possible to assert that
        // at the type level. Leaving for a later refactor for now.
        UnhandledError::Other(format!("Unhandled resolution error: {e}"))
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

impl From<aws_sdk_s3::Error> for UnhandledError {
    fn from(e: aws_sdk_s3::Error) -> Self {
        UnhandledError::S3Error(Box::new(e))
    }
}

impl From<(usize, UnhandledError)> for PipelineFailure {
    fn from((index, error): (usize, UnhandledError)) -> Self {
        PipelineFailure { index, error }
    }
}
