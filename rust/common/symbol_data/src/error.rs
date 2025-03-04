use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, Serialize, Deserialize)]
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
}
