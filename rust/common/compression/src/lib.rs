//! Common compression utilities for PostHog Rust services
//!
//! This crate provides gzip compression and decompression capabilities
//! that are shared across PostHog's Rust services, including feature-flags.
//!
//! Supports:
//! - gzip compression/decompression
//! - Base64 encoding/decoding

use base64::{engine::general_purpose, Engine as _};
use flate2::{read::GzDecoder, write::GzEncoder, Compression};
use std::io::{Read, Write};
use thiserror::Error;
use zstd::{Decoder, Encoder};

#[derive(Error, Debug)]
pub enum CompressionError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Base64 decoding error: {0}")]
    Base64(#[from] base64::DecodeError),
}

/// Gzip decompression
pub fn decompress_gzip(bytes: &[u8]) -> Result<Vec<u8>, CompressionError> {
    let mut decoder = GzDecoder::new(bytes);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed)?;
    Ok(decompressed)
}

/// Gzip compression
pub fn compress_gzip(data: &[u8]) -> Result<Vec<u8>, CompressionError> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
    encoder.write_all(data)?;
    let compressed = encoder.finish()?;
    Ok(compressed)
}

/// Zstd decompression (matching Django's ZstdCompressor)
pub fn decompress_zstd(bytes: &[u8]) -> Result<Vec<u8>, CompressionError> {
    let mut decoder = Decoder::new(bytes)?;
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed)?;
    Ok(decompressed)
}

/// Zstd compression (matching Django's ZstdCompressor)
pub fn compress_zstd(data: &[u8]) -> Result<Vec<u8>, CompressionError> {
    let mut encoder = Encoder::new(Vec::new(), 0)?; // Level 0 matches Django's zstd_preset = 0
    encoder.write_all(data)?;
    let compressed = encoder.finish()?;
    Ok(compressed)
}

/// Base64 encode
pub fn encode_base64(data: &[u8]) -> String {
    general_purpose::STANDARD.encode(data)
}

/// Base64 decode
pub fn decode_base64(data: &str) -> Result<Vec<u8>, CompressionError> {
    Ok(general_purpose::STANDARD.decode(data)?)
}

// Cyclotron compatibility layer

/// Compression format enum for cyclotron compatibility
pub enum CompressionFormat {
    Gzip,
}

/// High-level compression function with format selection (cyclotron compatibility)
pub fn compress_data(data: &[u8], format: CompressionFormat) -> Result<Vec<u8>, CompressionError> {
    match format {
        CompressionFormat::Gzip => compress_gzip(data),
    }
}

/// Decompression function for cyclotron compatibility
/// Tries gzip decompression first, then falls back to direct UTF-8 conversion
pub fn decompress_data(input: &[u8]) -> Result<String, CompressionError> {
    // Try gzip decompression first
    match decompress_gzip(input) {
        Ok(gzip_decompressed) => match String::from_utf8(gzip_decompressed) {
            Ok(decompressed_str) => Ok(decompressed_str),
            Err(e) => Err(CompressionError::Io(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("Decompressed data is not valid UTF-8: {e}"),
            ))),
        },
        Err(_) => {
            // If gzip fails, try direct UTF-8 conversion (uncompressed data)
            match String::from_utf8(input.to_vec()) {
                Ok(direct_string) => Ok(direct_string),
                Err(e) => Err(CompressionError::Io(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("Data is neither valid gzip nor valid UTF-8: {e}"),
                ))),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gzip_compression_decompression() {
        let original = r#"{"large": "json", "with": ["many", "fields"], "number": 42}"#;
        let compressed = compress_gzip(original.as_bytes()).unwrap();
        let decompressed = decompress_gzip(&compressed).unwrap();
        let decompressed_str = String::from_utf8(decompressed).unwrap();
        assert_eq!(decompressed_str, original);
    }

    #[test]
    fn test_base64_encode_decode() {
        let original = b"Hello, World!";
        let encoded = encode_base64(original);
        let decoded = decode_base64(&encoded).unwrap();
        assert_eq!(decoded, original);
    }

    #[test]
    fn test_gzip_with_empty_data() {
        let original = b"";
        let compressed = compress_gzip(original).unwrap();
        let decompressed = decompress_gzip(&compressed).unwrap();
        assert_eq!(decompressed, original);
    }

    #[test]
    fn test_invalid_gzip_data() {
        let corrupted_gzip = vec![0x1f, 0x8b, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00]; // Incomplete gzip header
        let result = decompress_gzip(&corrupted_gzip);
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_base64_data() {
        let invalid_base64 = "Invalid Base64!";
        let result = decode_base64(invalid_base64);
        assert!(result.is_err());
    }

    // Cyclotron compatibility tests
    #[test]
    fn test_compress_data_gzip() {
        let original = r#"{"test": "cyclotron_data"}"#;
        let compressed = compress_data(original.as_bytes(), CompressionFormat::Gzip).unwrap();
        let decompressed = decompress_gzip(&compressed).unwrap();
        let decompressed_str = String::from_utf8(decompressed).unwrap();
        assert_eq!(decompressed_str, original);
    }

    #[test]
    fn test_decompress_data_uncompressed_utf8() {
        let json_str = r#"{"test": "uncompressed"}"#;
        let result = decompress_data(json_str.as_bytes()).unwrap();
        assert_eq!(result, json_str);

        // Test non-JSON UTF-8 data too
        let text_str = "Plain text data";
        let result = decompress_data(text_str.as_bytes()).unwrap();
        assert_eq!(result, text_str);
    }

    #[test]
    fn test_decompress_data_gzip() {
        let original = r#"{"test": "compressed_cyclotron"}"#;
        let compressed = compress_gzip(original.as_bytes()).unwrap();
        let decompressed = decompress_data(&compressed).unwrap();
        assert_eq!(decompressed, original);
    }

    #[test]
    fn test_decompress_data_invalid_data() {
        // Data that is neither valid gzip nor valid UTF-8
        let invalid_data = vec![0xFF, 0xFE, 0xFD, 0xFC];
        let result = decompress_data(&invalid_data);
        assert!(result.is_err());
    }

    #[test]
    fn test_zstd_compression_decompression() {
        // Create a string of 1000 characters
        let long_string = "a".repeat(1000);
        let original = format!(
            r#"{{"large": "json", "with": ["many", "fields"], "number": 42, "big-string": "{long_string}"}}"#
        );
        let compressed = compress_zstd(original.as_bytes()).unwrap();
        let decompressed = decompress_zstd(&compressed).unwrap();
        let decompressed_str = String::from_utf8(decompressed).unwrap();
        assert_eq!(decompressed_str, original);
        assert!(compressed.len() < original.len());
    }

    #[test]
    fn test_zstd_with_empty_data() {
        let original = b"";
        let compressed = compress_zstd(original).unwrap();
        let decompressed = decompress_zstd(&compressed).unwrap();
        assert_eq!(decompressed, original);
    }

    #[test]
    fn test_invalid_zstd_data() {
        let corrupted_zstd = vec![0x28, 0xb5, 0x2f, 0xfd, 0x00]; // Incomplete zstd header
        let result = decompress_zstd(&corrupted_zstd);
        assert!(result.is_err());
    }
}
