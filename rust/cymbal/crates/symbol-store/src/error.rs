use aws_sdk_s3::primitives::ByteStreamError;
use posthog_symbol_data::SymbolDataError;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SymbolStoreError {
    #[error("S3 error: {0}")]
    S3Error(#[from] Box<aws_sdk_s3::Error>),
    #[error(transparent)]
    ByteStreamError(#[from] ByteStreamError),
}

impl From<aws_sdk_s3::Error> for SymbolStoreError {
    fn from(error: aws_sdk_s3::Error) -> Self {
        Self::S3Error(Box::new(error))
    }
}

#[derive(Debug, Error)]
pub enum ResolveError {
    #[error(transparent)]
    UnhandledError(#[from] UnhandledError),
    #[error(transparent)]
    ResolutionError(#[from] FrameError),
}

#[derive(Debug, Error)]
pub enum UnhandledError {
    #[error("Sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("S3 error: {0}")]
    S3Error(#[from] Box<aws_sdk_s3::Error>),
    #[error(transparent)]
    ByteStreamError(#[from] ByteStreamError),
    #[error("Unhandled serde error: {0}")]
    SerdeError(#[from] serde_json::Error),
    #[error("Unhandled error: {0}")]
    Other(String),
}

impl From<SymbolStoreError> for UnhandledError {
    fn from(error: SymbolStoreError) -> Self {
        match error {
            SymbolStoreError::S3Error(error) => Self::S3Error(error),
            SymbolStoreError::ByteStreamError(error) => Self::ByteStreamError(error),
        }
    }
}

impl From<SymbolStoreError> for ResolveError {
    fn from(error: SymbolStoreError) -> Self {
        Self::UnhandledError(error.into())
    }
}

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
    #[error("No symbol set for chunk id: {0}")]
    MissingChunkIdData(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum JsResolveErr {
    #[error("This frame had no source url or chunk id")]
    NoUrlOrChunkId,
    #[error("No source url found")]
    NoSourceUrl,
    #[error("Invalid source map: {0}")]
    InvalidSourceMap(String),
    #[error("Token not found for frame: {0}:{1}:{2}")]
    TokenNotFound(String, u32, u32),
    #[error("Invalid source url: {0}")]
    InvalidSourceUrl(String),
    #[error("Could not find sourcemap for source url: {0}")]
    NoSourcemap(String),
    #[error("Could not parse source-map header from url {0}")]
    InvalidSourceMapHeader(String),
    #[error("Invalid source url: {0}")]
    InvalidSourceMapUrl(String),
    #[error("Request timed out while fetching: {0}")]
    Timeout(String),
    #[error("HTTP error {0} while fetching: {1}")]
    HttpStatus(u16, String),
    #[error("Network error while fetching: {0}")]
    NetworkError(String),
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

impl FrameError {
    pub fn metric_reason(&self) -> &'static str {
        match self {
            Self::JavaScript(error) => error.metric_reason(),
            Self::Hermes(error) => error.metric_reason(),
            Self::Proguard(error) => error.metric_reason(),
            Self::Apple(error) => error.metric_reason(),
            Self::MissingChunkIdData(_) => "no_symbol_set",
        }
    }
}

impl From<JsResolveErr> for ResolveError {
    fn from(error: JsResolveErr) -> Self {
        FrameError::JavaScript(error).into()
    }
}

impl From<HermesError> for ResolveError {
    fn from(error: HermesError) -> Self {
        FrameError::Hermes(error).into()
    }
}

impl From<ProguardError> for ResolveError {
    fn from(error: ProguardError) -> Self {
        FrameError::Proguard(error).into()
    }
}

impl From<AppleError> for ResolveError {
    fn from(error: AppleError) -> Self {
        FrameError::Apple(error).into()
    }
}

impl From<FrameError> for UnhandledError {
    fn from(error: FrameError) -> Self {
        Self::Other(format!("Unhandled resolution error: {error}"))
    }
}

impl From<reqwest::Error> for JsResolveErr {
    fn from(error: reqwest::Error) -> Self {
        if error.is_timeout() {
            return Self::Timeout(error.to_string());
        }

        if error.is_status() {
            let status = error.status().expect("status errors include status");
            return Self::HttpStatus(status.as_u16(), error.to_string());
        }

        if error.is_redirect() {
            return Self::RedirectError(error.to_string());
        }

        if error.is_connect() || error.is_request() || error.is_builder() {
            return Self::NetworkError(error.to_string());
        }

        Self::NetworkError(error.to_string())
    }
}
