//! Serialization seam: format × envelope.
//!
//! [`Format`] turns an event into payload bytes; [`Envelope`] wraps payload
//! bytes at the byte level. A [`Serializer`] composes one of each, and the
//! sink calls it instead of inlining the JSON conversion and the lz4 branch —
//! so a format cutover (e.g. protobuf) or a new envelope becomes a config
//! change behind this seam, with content headers carrying coexistence on a
//! topic.
//!
//! The sink resolves the composition by `data_type`, before routing: a replay
//! event redirected to the DLQ or a custom topic keeps the lz4 envelope, with
//! its `content-encoding` header travelling along. Resolution per routed
//! destination belongs to the outputs layer, not this seam.
//!
//! Partition keys, routing headers, and topics are deliberately not here:
//! this layer produces bytes and content headers only.

use serde::Serialize;
use thiserror::Error;

/// What can go wrong producing payload bytes. The caller owns the mapping
/// into its own error vocabulary and the logging, with the context (topic,
/// team, event) this layer does not have.
#[derive(Debug, Error)]
pub enum SerializationError {
    #[error("failed to serialize event: {0}")]
    Format(#[from] serde_json::Error),
    #[error("failed to apply envelope: {0}")]
    Envelope(#[from] std::io::Error),
}

/// Payload format: event → bytes. JSON is the only implementation and stamps
/// no `content-type` — absence is the wire contract today's consumers read.
/// A future format must return `Some` so old and new encodings can coexist
/// on one topic.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Json,
}

impl Format {
    pub fn serialize<T: Serialize>(&self, event: &T) -> Result<Vec<u8>, SerializationError> {
        match self {
            Format::Json => Ok(serde_json::to_vec(event)?),
        }
    }

    pub fn content_type(&self) -> Option<&'static str> {
        match self {
            Format::Json => None,
        }
    }
}

/// Byte-level envelope applied after the format. `Lz4` is the session replay
/// block envelope: lz4 block compression with a 4-byte LE uncompressed-size
/// prefix, so consumers can decompress without inspecting magic bytes. The
/// `content-encoding` header signals that unwrapping is required, which lets
/// enveloped and plain messages coexist on a topic during rollout and
/// rollback.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Envelope {
    None,
    Lz4,
}

impl Envelope {
    pub fn wrap(&self, payload: Vec<u8>) -> Result<Vec<u8>, SerializationError> {
        match self {
            Envelope::None => Ok(payload),
            Envelope::Lz4 => {
                let compressed = lz4::block::compress(&payload, None, false)?;
                let uncompressed_len = payload.len() as u32;
                let mut wrapped = Vec::with_capacity(4 + compressed.len());
                wrapped.extend_from_slice(&uncompressed_len.to_le_bytes());
                wrapped.extend_from_slice(&compressed);
                Ok(wrapped)
            }
        }
    }

    pub fn content_encoding(&self) -> Option<&'static str> {
        match self {
            Envelope::None => None,
            Envelope::Lz4 => Some("lz4"),
        }
    }
}

/// One format wrapped in one envelope — a destination's encoding contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Serializer {
    pub format: Format,
    pub envelope: Envelope,
}

impl Serializer {
    pub const JSON: Self = Self {
        format: Format::Json,
        envelope: Envelope::None,
    };
    pub const JSON_LZ4: Self = Self {
        format: Format::Json,
        envelope: Envelope::Lz4,
    };

    pub fn serialize<T: Serialize>(&self, event: &T) -> Result<Vec<u8>, SerializationError> {
        self.envelope.wrap(self.format.serialize(event)?)
    }

    /// The `content-encoding` a produced record must carry, `None` when the
    /// payload needs no unwrapping.
    pub fn content_encoding(&self) -> Option<&'static str> {
        self.envelope.content_encoding()
    }

    /// The `content-type` a produced record must carry, `None` for the
    /// default JSON contract.
    pub fn content_type(&self) -> Option<&'static str> {
        self.format.content_type()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    /// The lz4 envelope's byte layout is a consumer contract: 4-byte LE
    /// uncompressed length, then the lz4 block. A change to either half
    /// breaks decompression downstream.
    #[test]
    fn lz4_envelope_round_trips_with_le_size_prefix() {
        let payload = serde_json::to_vec(&json!({"event": "$snapshot", "data": "x".repeat(256)}))
            .expect("test payload must serialize");

        let wrapped = Envelope::Lz4.wrap(payload.clone()).unwrap();

        let prefix = u32::from_le_bytes(wrapped[..4].try_into().unwrap());
        assert_eq!(prefix as usize, payload.len());
        let unwrapped = lz4::block::decompress(&wrapped[4..], Some(prefix as i32)).unwrap();
        assert_eq!(unwrapped, payload);
    }

    #[test]
    fn none_envelope_passes_bytes_through() {
        let payload = b"{\"event\":\"test\"}".to_vec();
        assert_eq!(Envelope::None.wrap(payload.clone()).unwrap(), payload);
    }

    /// Content headers per composition: JSON stamps no content-type, and
    /// only the lz4 envelope stamps a content-encoding.
    #[rstest]
    #[case::json_plain(Serializer::JSON, None, None)]
    #[case::json_lz4(Serializer::JSON_LZ4, None, Some("lz4"))]
    fn content_headers_follow_the_composition(
        #[case] serializer: Serializer,
        #[case] content_type: Option<&str>,
        #[case] content_encoding: Option<&str>,
    ) {
        assert_eq!(serializer.content_type(), content_type);
        assert_eq!(serializer.content_encoding(), content_encoding);
    }

    /// The composed serializer produces exactly format-then-envelope bytes.
    /// The lz4 half decodes the output independently rather than calling
    /// `wrap` again, so a composition bug cannot cancel itself out.
    #[test]
    fn serializer_composes_format_then_envelope() {
        let event = json!({"event": "test", "distinct_id": "user-1"});
        let plain = Serializer::JSON.serialize(&event).unwrap();
        assert_eq!(plain, serde_json::to_vec(&event).unwrap());

        let wrapped = Serializer::JSON_LZ4.serialize(&event).unwrap();
        let prefix = u32::from_le_bytes(wrapped[..4].try_into().unwrap());
        assert_eq!(prefix as usize, plain.len());
        let unwrapped = lz4::block::decompress(&wrapped[4..], Some(prefix as i32)).unwrap();
        assert_eq!(unwrapped, plain);
    }
}
