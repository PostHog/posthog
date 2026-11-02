//! A hand-written Avro object container codec that matches avsc, which the Node consumer uses.
//!
//! The output must decode to what Node writes, and decode errors become the DLQ
//! `error_message`, so the codec reproduces avsc's header export, map semantics and error
//! strings. A general Avro library controls none of those.

mod decode;
mod encode;
mod schema;
mod value;

use thiserror::Error;

pub use decode::decode_container;
pub use encode::encode_container;
pub use schema::{EnumSchema, Field, FixedSchema, RecordSchema, Schema};
pub use value::{AvroMap, AvroValue};

pub(crate) const MAGIC: [u8; 4] = *b"Obj\x01";

/// A decoded container. `schema_json` is the header text exactly as the writer wrote it.
#[derive(Debug, Clone)]
pub struct Container {
    pub schema_json: String,
    pub schema: Schema,
    pub codec: String,
    pub records: Vec<AvroValue>,
}

/// The `Display` text is what the consumer writes to the DLQ `error_message` header, so each
/// one matches the Node message.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum AvroError {
    /// `decodeLogRecords` found no header: under 4 bytes, or a header that runs past the end.
    #[error("No metadata found")]
    NoMetadata,
    #[error("invalid magic bytes")]
    InvalidMagic,
    /// Only zstandard is registered, which hides avsc's built-in null and deflate codecs.
    #[error("unknown codec: {0}")]
    UnknownCodec(String),
    #[error("invalid sync marker")]
    InvalidSyncMarker,
    #[error("{0} codec decompression error")]
    Decompression(String),
    #[error("{0}")]
    Decode(String),
    #[error("{0}")]
    Encode(String),
    /// A writer schema that does not parse. avsc's text here comes from `JSON.parse` or
    /// `Type.forSchema`, and this port does not reproduce it.
    #[error("{0}")]
    Schema(String),
}
