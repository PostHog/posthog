//! Payload serialization — the format × envelope seam between routing and the
//! produce mechanism.
//!
//! A destination's payload encoding is a contract with the *consumers* of that
//! destination, not a property of the transport that carries it: the S3
//! fallback stores the same bytes Kafka would have carried precisely because
//! the format follows the destination, not the sink. This module names that
//! seam so the encoding can evolve (e.g. a protobuf cutover) without touching
//! sinks or call sites.
//!
//! Two composable axes:
//!
//! - [`Format`]: event → payload bytes, plus the `content-type` header value
//!   that identifies it on the wire.
//! - [`Envelope`]: bytes → bytes (compression), plus the `content-encoding`
//!   header value that signals it. The lz4 envelope is session replay's
//!   existing block format: a 4-byte little-endian uncompressed-size prefix,
//!   so consumers can allocate without inspecting magic bytes.
//!
//! A [`Serializer`] is one of each. Content headers are how old and new
//! encodings coexist on one destination during a rollout: consumers switch on
//! the header, producers cut over per destination, and rollback is config.
//!
//! Explicitly *not* here: partition keys, routing headers, topics. Those are
//! routing decisions; this module only turns an event into bytes.

use tracing::log::error;

use crate::api::CaptureError;
use crate::config::EnvelopeCompression;
use common_types::CapturedEvent;

/// Payload format: how an event becomes bytes.
///
/// `Json` is the wire contract every current destination's consumers expect.
/// It deliberately reports no `content-type`: today's consumers do not receive
/// one, and stamping it is a wire change to make deliberately, alongside the
/// first non-JSON format.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Json,
}

impl Format {
    pub fn serialize(&self, event: &CapturedEvent) -> Result<Vec<u8>, CaptureError> {
        match self {
            Format::Json => serde_json::to_vec(event).map_err(|e| {
                error!("failed to serialize event: {e:#}");
                CaptureError::NonRetryableSinkError
            }),
        }
    }

    /// The `content-type` header value identifying this format on the wire.
    /// `None` means "stamp nothing" (the implicit-JSON status quo).
    pub fn content_type(&self) -> Option<&'static str> {
        match self {
            Format::Json => None,
        }
    }
}

/// Payload envelope: compression applied over any [`Format`]'s bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Envelope {
    None,
    /// lz4 block format with a 4-byte LE uncompressed-size prefix; signalled
    /// on the wire via `content-encoding: lz4`.
    Lz4,
}

impl Envelope {
    pub fn encode(&self, bytes: Vec<u8>) -> Result<Vec<u8>, CaptureError> {
        match self {
            Envelope::None => Ok(bytes),
            Envelope::Lz4 => {
                let compressed = lz4::block::compress(&bytes, None, false).map_err(|e| {
                    error!("failed to LZ4-compress payload: {e:#}");
                    CaptureError::NonRetryableSinkError
                })?;
                let uncompressed_len = bytes.len() as u32;
                let mut payload = Vec::with_capacity(4 + compressed.len());
                payload.extend_from_slice(&uncompressed_len.to_le_bytes());
                payload.extend_from_slice(&compressed);
                Ok(payload)
            }
        }
    }

    /// The `content-encoding` header value signalling this envelope on the
    /// wire. `None` means "stamp nothing".
    pub fn content_encoding(&self) -> Option<&'static str> {
        match self {
            Envelope::None => None,
            Envelope::Lz4 => Some("lz4"),
        }
    }
}

impl From<EnvelopeCompression> for Envelope {
    fn from(compression: EnvelopeCompression) -> Self {
        match compression {
            EnvelopeCompression::None => Envelope::None,
            EnvelopeCompression::Lz4 => Envelope::Lz4,
        }
    }
}

/// One destination's payload encoding: a format wrapped in an envelope.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Serializer {
    format: Format,
    envelope: Envelope,
}

impl Serializer {
    pub fn new(format: Format, envelope: Envelope) -> Self {
        Self { format, envelope }
    }

    /// Plain JSON, no envelope — every non-replay destination today.
    pub fn json() -> Self {
        Self::new(Format::Json, Envelope::None)
    }

    pub fn serialize(&self, event: &CapturedEvent) -> Result<Vec<u8>, CaptureError> {
        self.envelope.encode(self.format.serialize(event)?)
    }

    pub fn content_type(&self) -> Option<&'static str> {
        self.format.content_type()
    }

    pub fn content_encoding(&self) -> Option<&'static str> {
        self.envelope.content_encoding()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn payload_bytes() -> Vec<u8> {
        br#"{"event":"$pageview","distinct_id":"user1"}"#.to_vec()
    }

    #[test]
    fn none_envelope_is_passthrough() {
        let bytes = payload_bytes();
        assert_eq!(Envelope::None.encode(bytes.clone()).unwrap(), bytes);
        assert_eq!(Envelope::None.content_encoding(), None);
    }

    #[test]
    fn lz4_envelope_prefixes_uncompressed_size_and_round_trips() {
        let bytes = payload_bytes();
        let encoded = Envelope::Lz4.encode(bytes.clone()).unwrap();

        let prefix: [u8; 4] = encoded[..4].try_into().unwrap();
        assert_eq!(u32::from_le_bytes(prefix) as usize, bytes.len());

        let decompressed = lz4::block::decompress(&encoded[4..], Some(bytes.len() as i32)).unwrap();
        assert_eq!(decompressed, bytes);
        assert_eq!(Envelope::Lz4.content_encoding(), Some("lz4"));
    }

    #[test]
    fn json_format_stamps_no_content_type() {
        assert_eq!(Format::Json.content_type(), None);
        assert_eq!(Serializer::json().content_type(), None);
        assert_eq!(Serializer::json().content_encoding(), None);
    }

    #[test]
    fn envelope_follows_compression_config() {
        assert_eq!(Envelope::from(EnvelopeCompression::None), Envelope::None);
        assert_eq!(Envelope::from(EnvelopeCompression::Lz4), Envelope::Lz4);
    }
}
