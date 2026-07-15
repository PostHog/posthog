use std::sync::Arc;

use aws_sdk_s3::primitives::ByteStreamError;
use common_kafka::kafka_producer::KafkaProduceError;
use common_redis::CustomRedisError;
use common_types::ClickHouseEvent;
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
    pub error: Arc<UnhandledError>,
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
    #[error("Unhandled redis error: {0}")]
    RedisError(#[from] CustomRedisError),
    #[error("Unhandled error: {0}")]
    Other(String),
}

impl UnhandledError {
    /// A Postgres pool-acquire timeout means the pool was briefly saturated — in-flight request
    /// concurrency can outrun the small connection pool during a burst, and the acquire queued
    /// past `acquire_timeout`. This is a load-shedding signal, not a genuine failure: an HTTP
    /// handler should answer 429 so the caller backs off, rather than 500-ing and paging as an
    /// unhandled exception. (This is client backpressure, distinct from internal retry — pool
    /// exhaustion is systemic, so retrying in-process against the same pool only amplifies load;
    /// see `common_database::is_transient_error`, which deliberately excludes `PoolTimedOut`.)
    pub fn is_pool_timeout(&self) -> bool {
        matches!(self, UnhandledError::SqlxError(sqlx::Error::PoolTimedOut))
    }

    /// Collapse a shared `Arc<UnhandledError>` (as surfaced by a moka cache loader, where the
    /// concrete error can't be moved out) into an owned `UnhandledError`. `UnhandledError` isn't
    /// `Clone` — its inner sqlx/kafka errors aren't — so the general case degrades to
    /// `Other(String)`. But a pool-acquire timeout must survive the collapse: the /process
    /// handler keys its 429-vs-500 decision on [`Self::is_pool_timeout`], and the linking stage (a
    /// heavy Postgres user) is exactly where a burst exhausts the pool, so a flattened timeout
    /// would otherwise silently downgrade back to a 500.
    pub fn flatten_arc(error: &Arc<UnhandledError>) -> UnhandledError {
        if error.is_pool_timeout() {
            UnhandledError::SqlxError(sqlx::Error::PoolTimedOut)
        } else {
            UnhandledError::Other(error.to_string())
        }
    }
}

// These are errors that occur during frame resolution. This excludes e.g. network errors,
// which are handled by the store - this is the error type that's handed to the frame to see
// if it can still make something useful out of it.
// NOTE - these are serialized and deserialized, so that when we fail to get a symbol set from
// some provider (e.g. we fail to look up a sourcemap), we can return the correct error in the future
// without hitting their infra again (by storing it in PG).
#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum FrameError {
    #[error(transparent)]
    JavaScript(#[from] JsResolveErr),
    #[error(transparent)]
    Hermes(#[from] HermesError),
    #[error(transparent)]
    Proguard(#[from] ProguardError),
    #[error(transparent)]
    Apple(#[from] AppleError),
    #[error(transparent)]
    Native(#[from] NativeError),
    #[error("No symbol set for chunk id: {0}")]
    MissingChunkIdData(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
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

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
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

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum ProguardError {
    #[error("Data error: {0}")]
    DataError(#[from] SymbolDataError),
    #[error("Invalid mapping")]
    InvalidMapping,
    #[error("No proguard map uploaded for id: {0}")]
    MissingMap(String),
    #[error("No map ID sent with frame")]
    NoMapId,
    #[error("No original frames could be derived from this raw frame")]
    NoOriginalFrames,
    #[error("No module provided")]
    NoModuleProvided,
    #[error("No class matched")]
    MissingClass,
    #[error("Invalid class format")]
    InvalidClass,
}

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum AppleError {
    #[error("Data error: {0}")]
    DataError(#[from] SymbolDataError),
    #[error("No dSYM uploaded for debug_id: {0}")]
    MissingDsym(String),
    #[error("No debug_id found for frame")]
    NoDebugId,
    #[error("Invalid address format: {0}")]
    InvalidAddress(String),
    #[error("Symbol not found at address: {0:#x}")]
    SymbolNotFound(u64),
    #[error("Failed to parse dSYM: {0}")]
    ParseError(String),
    #[error("No matching debug image found for frame")]
    NoMatchingDebugImage,
}

// Errors produced by the shared native (DWARF/symcache) resolution machinery.
// Apple frames map these 1:1 onto AppleError so that stored failure reasons
// and metric labels for apple keep their existing shape.
#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum NativeError {
    #[error("Data error: {0}")]
    DataError(#[from] SymbolDataError),
    #[error("No debug symbols uploaded for debug_id: {0}")]
    MissingSymbolSet(String),
    #[error("No debug_id found for frame")]
    NoDebugId,
    #[error("Invalid address format: {0}")]
    InvalidAddress(String),
    #[error("Symbol not found at address: {0:#x}")]
    SymbolNotFound(u64),
    #[error("Failed to parse debug symbols: {0}")]
    ParseError(String),
    #[error("No matching debug image found for frame")]
    NoMatchingDebugImage,
}

impl From<NativeError> for AppleError {
    fn from(e: NativeError) -> Self {
        match e {
            NativeError::DataError(e) => AppleError::DataError(e),
            NativeError::MissingSymbolSet(id) => AppleError::MissingDsym(id),
            NativeError::NoDebugId => AppleError::NoDebugId,
            NativeError::InvalidAddress(s) => AppleError::InvalidAddress(s),
            NativeError::SymbolNotFound(addr) => AppleError::SymbolNotFound(addr),
            NativeError::ParseError(s) => AppleError::ParseError(s),
            NativeError::NoMatchingDebugImage => AppleError::NoMatchingDebugImage,
        }
    }
}

#[derive(Debug, Error, Clone, Serialize, PartialEq)]
pub enum EventError {
    #[error("Wrong event type: {0} for event {1}")]
    WrongEventType(String, Uuid),
    #[error("Invalid properties on event {0}, serde error: {1}")]
    InvalidProperties(Uuid, String),
    #[error("Empty exception list on event {0}")]
    EmptyExceptionList(Uuid),
    #[error("Suppressed issue: {0}")]
    Suppressed(Uuid),
    #[error("Suppressed by rule: {0}")]
    SuppressedByRule(Uuid),
    #[error("Rate limited (per-issue): {0}")]
    RateLimitedPerIssue(Uuid),
    #[error("Rate limited (project): team {0}")]
    RateLimitedProject(i32),
}

impl JsResolveErr {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::NoUrlOrChunkId | Self::NoSourceUrl => "no_reference",
            Self::NoSourcemap(_) | Self::NoSourcemapUploaded(_) => "no_symbol_set",
            Self::TokenNotFound(..) => "symbol_not_found",
            Self::Timeout(_)
            | Self::HttpStatus(..)
            | Self::NetworkError(_)
            | Self::RedirectError(_) => "network_error",
            Self::InvalidSourceMap(_)
            | Self::InvalidSourceUrl(_)
            | Self::InvalidSourceMapHeader(_)
            | Self::InvalidSourceMapUrl(_)
            | Self::InvalidDataUrl(..)
            | Self::JSDataError(_)
            | Self::InvalidSourceAndMap => "invalid_data",
        }
    }
}

impl HermesError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::NoChunkId => "no_reference",
            Self::NoSourcemapUploaded(_) => "no_symbol_set",
            Self::NoTokenForColumn(..) => "symbol_not_found",
            Self::DataError(_) | Self::InvalidMap(_) => "invalid_data",
        }
    }
}

impl ProguardError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::NoMapId | Self::NoModuleProvided => "no_reference",
            Self::MissingMap(_) => "no_symbol_set",
            Self::NoOriginalFrames | Self::MissingClass => "symbol_not_found",
            Self::DataError(_) | Self::InvalidMapping | Self::InvalidClass => "invalid_data",
        }
    }
}

impl AppleError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::NoDebugId | Self::NoMatchingDebugImage => "no_reference",
            Self::MissingDsym(_) => "no_symbol_set",
            Self::SymbolNotFound(_) => "symbol_not_found",
            Self::DataError(_) | Self::InvalidAddress(_) | Self::ParseError(_) => "invalid_data",
        }
    }
}

impl NativeError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::NoDebugId | Self::NoMatchingDebugImage => "no_reference",
            Self::MissingSymbolSet(_) => "no_symbol_set",
            Self::SymbolNotFound(_) => "symbol_not_found",
            Self::DataError(_) | Self::InvalidAddress(_) | Self::ParseError(_) => "invalid_data",
        }
    }
}

impl FrameError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::JavaScript(e) => e.metric_reason(),
            Self::Hermes(e) => e.metric_reason(),
            Self::Proguard(e) => e.metric_reason(),
            Self::Apple(e) => e.metric_reason(),
            Self::Native(e) => e.metric_reason(),
            Self::MissingChunkIdData(_) => "no_symbol_set",
        }
    }
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

impl From<ProguardError> for ResolveError {
    fn from(e: ProguardError) -> Self {
        FrameError::Proguard(e).into()
    }
}

impl From<AppleError> for ResolveError {
    fn from(e: AppleError) -> Self {
        FrameError::Apple(e).into()
    }
}

impl From<NativeError> for ResolveError {
    fn from(e: NativeError) -> Self {
        FrameError::Native(e).into()
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
        PipelineFailure {
            index,
            error: Arc::new(error),
        }
    }
}

impl From<(usize, Arc<UnhandledError>)> for PipelineFailure {
    fn from((index, error): (usize, Arc<UnhandledError>)) -> Self {
        PipelineFailure { index, error }
    }
}

impl From<UnhandledError> for PipelineFailure {
    fn from(error: UnhandledError) -> Self {
        PipelineFailure {
            index: 0,
            error: Arc::new(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pool_timeout_is_classified_as_backpressure() {
        // A pool-acquire timeout is the one sqlx failure the /process handler answers with 429
        // instead of 500; every other error stays a hard failure.
        assert!(UnhandledError::SqlxError(sqlx::Error::PoolTimedOut).is_pool_timeout());
        assert!(!UnhandledError::SqlxError(sqlx::Error::PoolClosed).is_pool_timeout());
        assert!(!UnhandledError::Other("boom".to_string()).is_pool_timeout());
    }

    #[test]
    fn flatten_arc_preserves_pool_timeout() {
        // The linking stage collapses moka's `Arc<UnhandledError>` back to an owned error; a pool
        // timeout must stay classifiable through that collapse, or it silently 500s again.
        let timeout = Arc::new(UnhandledError::SqlxError(sqlx::Error::PoolTimedOut));
        assert!(UnhandledError::flatten_arc(&timeout).is_pool_timeout());

        // Anything else degrades to `Other` (the concrete inner error can't be cloned out).
        let other = Arc::new(UnhandledError::SqlxError(sqlx::Error::PoolClosed));
        let flattened = UnhandledError::flatten_arc(&other);
        assert!(!flattened.is_pool_timeout());
        assert!(matches!(flattened, UnhandledError::Other(_)));
    }
}
