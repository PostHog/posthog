//! Decompress a raw replay Kafka message value and tell web replays from mobile ones.

/// Why a payload could not be read; maps onto the TS pipeline's dlq/drop reasons.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailKind {
    /// The Kafka message value could not be decompressed (dlq `invalid_compressed_data`).
    InvalidCompressedData,
}

impl FailKind {
    pub fn reason(self) -> &'static str {
        match self {
            FailKind::InvalidCompressedData => "invalid_compressed_data",
        }
    }
}

#[derive(Debug)]
pub struct Failure {
    pub kind: FailKind,
    pub detail: String,
}

impl Failure {
    fn new(kind: FailKind, detail: impl Into<String>) -> Self {
        Self {
            kind,
            detail: detail.into(),
        }
    }
}

type SResult<T> = Result<T, Failure>;

/// Capture writes `web` when a client sends no source, so a missing source never comes from capture.
pub fn is_web_replay(snapshot_source: Option<&str>) -> bool {
    snapshot_source == Some("web")
}

const GZIP_MAGIC: &[u8; 4] = &[0x1f, 0x8b, 0x08, 0x00];

/// Decompress a raw Kafka message value the way capture wraps it (mirrors the TS
/// `decompressMessageValue`): lz4 block with a 4-byte LE uncompressed-size prefix when the
/// `content-encoding` header says lz4, gzip when the magic bytes say so, else pass through.
/// Codec failures classify as `invalid_compressed_data`, matching the TS path.
pub fn decompress_payload(raw: Vec<u8>, content_encoding: Option<&str>) -> SResult<Vec<u8>> {
    let bad = |e: anyhow::Error| Failure::new(FailKind::InvalidCompressedData, format!("{e:#}"));
    if content_encoding == Some("lz4") {
        return crate::compression::unlz4_block(&raw).map_err(bad);
    }
    if raw.starts_with(GZIP_MAGIC) {
        return crate::compression::gunzip(&raw)
            .map_err(|e| bad(e.context("gzip decompress failed")));
    }
    Ok(raw)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decompress_payload_matches_the_capture_producer_format() {
        let body = br#"{"distinct_id":"d","data":"{}"}"#.to_vec();

        // lz4: capture writes `block::compress` output behind a 4-byte LE uncompressed-size prefix,
        // signalled by the content-encoding header.
        let compressed = lz4::block::compress(&body, None, false).unwrap();
        let mut framed = (body.len() as u32).to_le_bytes().to_vec();
        framed.extend_from_slice(&compressed);
        assert_eq!(decompress_payload(framed, Some("lz4")).unwrap(), body);

        // gzip: detected by magic bytes, no header needed.
        {
            use std::io::Write;
            let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            enc.write_all(&body).unwrap();
            let zipped = enc.finish().unwrap();
            assert_eq!(decompress_payload(zipped, None).unwrap(), body);
        }

        // Uncompressed passes through untouched.
        assert_eq!(decompress_payload(body.clone(), None).unwrap(), body);

        // Corrupt lz4 fails closed with the TS parse step's classification.
        let err = decompress_payload(vec![9, 0, 0, 0, 0xff, 0xff], Some("lz4")).unwrap_err();
        assert_eq!(err.kind.reason(), "invalid_compressed_data");
    }
}
