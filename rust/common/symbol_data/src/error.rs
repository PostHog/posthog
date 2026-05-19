use std::string::FromUtf8Error;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
pub enum Error {
    #[error("Wrong version: {0}, expected {1}")]
    WrongVersion(u32, u32),
    #[error("Data too short, expected {0}, got {1}")]
    DataTooShort(u64, u64),
    #[error("Data too long, expected {0}, got {1}")]
    DataTooLong(u64, u64),
    #[error("Invalid magic")]
    InvalidMagic,
    #[error("Invalid data type: {0} expected {1}")]
    InvalidDataType(u32, String),
    #[error("Invalid data type {0} for operation {1}")]
    InvalidDataTypeForOperation(u32, String),
    #[error("Invalid utf8, got error: {0}")]
    InvalidUtf8(String),
    #[error("Compression error: {0}")]
    CompressionError(String),
    #[error("Unknown compression type: {0}")]
    UnknownCompression(u8),
}

impl From<FromUtf8Error> for Error {
    fn from(e: FromUtf8Error) -> Self {
        Error::InvalidUtf8(e.to_string())
    }
}
