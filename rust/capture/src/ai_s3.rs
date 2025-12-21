use async_trait::async_trait;
use bytes::{BufMut, Bytes, BytesMut};
use rand::Rng;
use sha2::{Digest, Sha256};

use crate::s3_client::{S3Client, S3Error};

/// Hash a token for use in S3 keys.
/// This prevents path traversal attacks from malicious tokens containing "../" or "/".
/// Returns first 16 hex characters (64 bits) which is sufficient for this use case.
fn hash_token(token: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    format!("{:x}", hasher.finalize())[..16].to_string()
}

/// A blob to upload with its metadata.
pub struct BlobData {
    pub property_name: String,
    pub content_type: Option<String>,
    pub content_encoding: Option<String>,
    pub data: Bytes,
}

/// Result of uploading blobs, containing the base URL and part metadata for generating URLs.
pub struct UploadedBlobs {
    /// Base S3 URL without range parameter (e.g., "s3://bucket/prefix/team/uuid")
    pub base_url: String,
    /// Boundary string used in the multipart document
    pub boundary: String,
    /// Blob parts in order, with their byte ranges
    pub parts: Vec<BlobPartRange>,
}

/// A blob part with its byte range in the multipart file.
/// The range includes the boundary, headers, and body - a complete single-part multipart document.
pub struct BlobPartRange {
    pub property_name: String,
    pub range_start: usize,
    pub range_end: usize,
}

/// Trait for blob storage implementations.
/// Allows mocking in tests via dynamic dispatch.
#[async_trait]
pub trait BlobStorage: Send + Sync {
    /// Upload multiple blobs as a multipart/mixed document.
    /// Returns metadata for generating S3 URLs with byte ranges.
    /// Each range extracts a complete single-part multipart document.
    async fn upload_blobs(
        &self,
        token: &str,
        event_uuid: &str,
        blobs: Vec<BlobData>,
    ) -> Result<UploadedBlobs, S3Error>;
}

/// AI-specific blob storage that handles multipart/mixed format and URL generation.
pub struct AiBlobStorage {
    s3_client: S3Client,
    prefix: String,
}

impl AiBlobStorage {
    pub fn new(s3_client: S3Client, prefix: String) -> Self {
        Self { s3_client, prefix }
    }
}

/// Generate a unique boundary for multipart document.
/// Includes event UUID and random suffix to prevent collisions with content.
fn generate_boundary(event_uuid: &str) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(&rand::distributions::Alphanumeric)
        .take(8)
        .map(char::from)
        .collect();
    format!("----posthog-ai-{event_uuid}-{suffix}")
}

/// Write multipart part headers and body directly into the buffer.
/// Does NOT write boundaries - those are handled by build_multipart_document.
/// Returns the number of bytes written.
///
/// Format:
/// Content-Disposition: form-data; name="property_name"\r\n
/// Content-Type: content_type\r\n
/// [Content-Encoding: encoding\r\n]
/// \r\n
/// <body>\r\n
fn write_multipart_part(
    buffer: &mut BytesMut,
    property_name: &str,
    content_type: &str,
    content_encoding: Option<&str>,
    body: &[u8],
) -> usize {
    let start_len = buffer.len();

    // Content-Disposition header
    buffer.put_slice(b"Content-Disposition: form-data; name=\"");
    buffer.put_slice(property_name.as_bytes());
    buffer.put_slice(b"\"\r\n");

    // Content-Type header (always present)
    buffer.put_slice(b"Content-Type: ");
    buffer.put_slice(content_type.as_bytes());
    buffer.put_slice(b"\r\n");

    // Optional Content-Encoding header
    if let Some(encoding) = content_encoding {
        buffer.put_slice(b"Content-Encoding: ");
        buffer.put_slice(encoding.as_bytes());
        buffer.put_slice(b"\r\n");
    }

    // End of headers
    buffer.put_slice(b"\r\n");

    // Body
    buffer.put_slice(body);
    buffer.put_slice(b"\r\n");

    buffer.len() - start_len
}

/// Write an opening boundary to the buffer.
fn write_opening_boundary(buffer: &mut BytesMut, boundary: &str) {
    buffer.put_slice(b"--");
    buffer.put_slice(boundary.as_bytes());
    buffer.put_slice(b"\r\n");
}

/// Write the closing boundary to the buffer.
fn write_closing_boundary(buffer: &mut BytesMut, boundary: &str) {
    buffer.put_slice(b"--");
    buffer.put_slice(boundary.as_bytes());
    buffer.put_slice(b"--\r\n");
}

/// Result of building a complete multipart document.
struct BuiltDocument {
    /// The complete multipart document bytes
    data: Bytes,
    /// Boundary used in the document
    boundary: String,
    /// Byte ranges for each part (property_name, start, end inclusive)
    parts: Vec<BlobPartRange>,
}

/// Build a complete multipart document from multiple blobs.
///
/// The document format is:
/// --boundary\r\n<part1_headers_and_body>\r\n--boundary\r\n<part2_headers_and_body>\r\n--boundary--\r\n
///
/// Each part's byte range includes headers and body but excludes boundaries.
/// Clients can parse the extracted range as HTTP-style headers + body.
fn build_multipart_document(event_uuid: &str, blobs: Vec<BlobData>) -> BuiltDocument {
    let boundary = generate_boundary(event_uuid);

    // Pre-allocate capacity to avoid reallocations.
    // Per-blob overhead (~200 bytes): boundary, headers, CRLF sequences.
    // Plus ~100 bytes for closing boundary.
    let blob_data_size: usize = blobs.iter().map(|b| b.data.len()).sum();
    let estimated_capacity = blob_data_size + (blobs.len() * 200) + 100;
    let mut document = BytesMut::with_capacity(estimated_capacity);
    let mut parts = Vec::with_capacity(blobs.len());

    for blob in &blobs {
        // Write opening boundary
        write_opening_boundary(&mut document, &boundary);

        // Record start position (after boundary, at headers)
        let range_start = document.len();

        let content_type = blob
            .content_type
            .as_deref()
            .unwrap_or("application/octet-stream");

        // Write headers and body (no boundaries)
        write_multipart_part(
            &mut document,
            &blob.property_name,
            content_type,
            blob.content_encoding.as_deref(),
            &blob.data,
        );

        // Range ends before the trailing \r\n that precedes the next boundary
        // write_multipart_part ends with body + \r\n, we want to exclude that \r\n
        let range_end = document.len() - 3; // -1 for inclusive, -2 for \r\n

        parts.push(BlobPartRange {
            property_name: blob.property_name.clone(),
            range_start,
            range_end,
        });
    }

    // Write closing boundary at the end
    write_closing_boundary(&mut document, &boundary);

    BuiltDocument {
        data: document.freeze(),
        boundary,
        parts,
    }
}

#[async_trait]
impl BlobStorage for AiBlobStorage {
    /// Upload multiple blobs as a multipart/mixed document.
    /// Each blob becomes a standalone part that can be extracted via byte range.
    ///
    /// `token` is used as the partition key in the S3 path.
    /// TODO: Replace with team_id once secret key signing is implemented.
    async fn upload_blobs(
        &self,
        token: &str,
        event_uuid: &str,
        blobs: Vec<BlobData>,
    ) -> Result<UploadedBlobs, S3Error> {
        if blobs.is_empty() {
            return Ok(UploadedBlobs {
                base_url: String::new(),
                boundary: String::new(),
                parts: vec![],
            });
        }

        let doc = build_multipart_document(event_uuid, blobs);

        // Upload with multipart/mixed content type
        // Hash the token to prevent path traversal attacks from malicious input
        let token_hash = hash_token(token);
        let key = format!("{}{}/{}", self.prefix, token_hash, event_uuid);
        let content_type = format!("multipart/mixed; boundary={}", doc.boundary);
        self.s3_client
            .put_object(&key, doc.data, &content_type)
            .await?;

        let base_url = format!("s3://{}/{}", self.s3_client.bucket(), key);

        Ok(UploadedBlobs {
            base_url,
            boundary: doc.boundary,
            parts: doc.parts,
        })
    }
}

/// Mock blob storage for testing.
/// Returns predictable S3 URLs without actually uploading.
pub struct MockBlobStorage {
    bucket: String,
    prefix: String,
}

impl MockBlobStorage {
    pub fn new(bucket: String, prefix: String) -> Self {
        Self { bucket, prefix }
    }
}

#[async_trait]
impl BlobStorage for MockBlobStorage {
    async fn upload_blobs(
        &self,
        token: &str,
        event_uuid: &str,
        blobs: Vec<BlobData>,
    ) -> Result<UploadedBlobs, S3Error> {
        if blobs.is_empty() {
            return Ok(UploadedBlobs {
                base_url: String::new(),
                boundary: String::new(),
                parts: vec![],
            });
        }

        // Build document to get correct byte ranges (data is discarded for mock)
        let doc = build_multipart_document(event_uuid, blobs);

        let token_hash = hash_token(token);
        let key = format!("{}{}/{}", self.prefix, token_hash, event_uuid);
        let base_url = format!("s3://{}/{}", self.bucket, key);

        Ok(UploadedBlobs {
            base_url,
            boundary: doc.boundary,
            parts: doc.parts,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_multipart_part_format() {
        let mut buffer = BytesMut::new();
        let bytes_written = write_multipart_part(
            &mut buffer,
            "$ai_input",
            "application/json",
            None,
            b"{\"test\": true}",
        );

        let expected = concat!(
            "Content-Disposition: form-data; name=\"$ai_input\"\r\n",
            "Content-Type: application/json\r\n",
            "\r\n",
            "{\"test\": true}\r\n",
        );

        assert_eq!(String::from_utf8_lossy(&buffer), expected);
        assert_eq!(bytes_written, buffer.len());
    }

    #[test]
    fn test_multipart_part_with_encoding() {
        let mut buffer = BytesMut::new();
        let bytes_written = write_multipart_part(
            &mut buffer,
            "$ai_output",
            "text/plain",
            Some("gzip"),
            b"compressed data",
        );

        let expected = concat!(
            "Content-Disposition: form-data; name=\"$ai_output\"\r\n",
            "Content-Type: text/plain\r\n",
            "Content-Encoding: gzip\r\n",
            "\r\n",
            "compressed data\r\n",
        );

        assert_eq!(String::from_utf8_lossy(&buffer), expected);
        assert_eq!(bytes_written, buffer.len());
    }

    #[test]
    fn test_write_returns_correct_size() {
        let mut buffer = BytesMut::new();

        let bytes_written = write_multipart_part(
            &mut buffer,
            "$ai_input",
            "application/json",
            Some("gzip"),
            b"test body content",
        );

        assert_eq!(bytes_written, buffer.len());
    }

    #[test]
    fn test_s3_url_format() {
        let bucket = "capture";
        let prefix = "llma/";
        let token = "phc_test_token";
        let event_uuid = "550e8400-e29b-41d4-a716-446655440000";

        let token_hash = hash_token(token);
        let key = format!("{prefix}{token_hash}/{event_uuid}");
        let url = format!("s3://{bucket}/{key}");

        // Token is hashed (first 16 chars) to prevent path traversal attacks
        assert_eq!(token_hash, "0f25663a3e84ea94");
        assert_eq!(
            url,
            "s3://capture/llma/0f25663a3e84ea94/550e8400-e29b-41d4-a716-446655440000"
        );
    }

    #[test]
    fn test_hash_token_prevents_path_traversal() {
        // Malicious tokens with path traversal attempts should be safely hashed
        let malicious_tokens = [
            "../../../etc/passwd",
            "phc_test/../other_customer",
            "token/with/slashes",
            "token\0with\0nulls",
        ];

        for token in malicious_tokens {
            let hashed = hash_token(token);
            // Hash should be 16 hex characters (first 64 bits of SHA-256)
            assert_eq!(hashed.len(), 16);
            // Hash should only contain hex characters (safe for S3 keys)
            assert!(hashed.chars().all(|c| c.is_ascii_hexdigit()));
        }
    }

    #[test]
    fn test_boundary_generation() {
        let uuid = "550e8400-e29b-41d4-a716-446655440000";
        let boundary = generate_boundary(uuid);

        // Should start with prefix and contain event UUID
        assert!(boundary.starts_with("----posthog-ai-550e8400-e29b-41d4-a716-446655440000-"));
        // Should have 8-char random suffix
        let expected_prefix = "----posthog-ai-550e8400-e29b-41d4-a716-446655440000-";
        assert_eq!(boundary.len(), expected_prefix.len() + 8);

        // Each call should generate different boundary
        let boundary2 = generate_boundary(uuid);
        assert_ne!(boundary, boundary2);
    }

    /// Helper to parse all parts from bytes using multer
    async fn parse_all_parts(data: Bytes, boundary: &str) -> Vec<(String, String, Bytes)> {
        use multer::Multipart;

        let stream = futures::stream::once(async move { Ok::<_, std::io::Error>(data) });
        let mut multipart = Multipart::new(stream, boundary);

        let mut parts = Vec::new();
        while let Some(field) = multipart.next_field().await.unwrap() {
            let name = field.name().unwrap().to_string();
            let content_type = field.content_type().map(|m| m.to_string()).unwrap();
            let body = field.bytes().await.unwrap();
            parts.push((name, content_type, body));
        }

        parts
    }

    /// Helper to parse MIME part (headers + body) using httparse
    fn parse_mime_part(data: &[u8]) -> (std::collections::HashMap<String, String>, &[u8]) {
        // httparse requires a mutable array of Header structs
        let mut header_buf = [httparse::EMPTY_HEADER; 16];

        // Parse headers (httparse expects request/response format, so we parse as headers only)
        let status =
            httparse::parse_headers(data, &mut header_buf).expect("Failed to parse headers");

        let (header_len, parsed_headers) = match status {
            httparse::Status::Complete((len, headers)) => (len, headers),
            httparse::Status::Partial => panic!("Incomplete headers in MIME part"),
        };

        // Build headers map
        let mut headers = std::collections::HashMap::new();
        for header in parsed_headers {
            let name = header.name.to_lowercase();
            let value = std::str::from_utf8(header.value)
                .expect("Invalid UTF-8 in header value")
                .to_string();
            headers.insert(name, value);
        }

        // Body starts after headers
        let body = &data[header_len..];

        (headers, body)
    }

    #[tokio::test]
    async fn test_single_part_document() {
        let event_uuid = "test-event-uuid";
        let body_content = b"{\"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}";

        let doc = build_multipart_document(
            event_uuid,
            vec![BlobData {
                property_name: "$ai_input".to_string(),
                content_type: Some("application/json".to_string()),
                content_encoding: None,
                data: Bytes::from_static(body_content),
            }],
        );

        // Should have one part
        assert_eq!(doc.parts.len(), 1);
        assert_eq!(doc.parts[0].property_name, "$ai_input");

        // Full document should parse as valid multipart
        let parts = parse_all_parts(doc.data.clone(), &doc.boundary).await;
        assert_eq!(parts.len(), 1);
        assert_eq!(parts[0].0, "$ai_input");
        assert_eq!(parts[0].1, "application/json");
        assert_eq!(parts[0].2.as_ref(), body_content);

        // Extract by range - should get headers + body (no boundaries)
        let range = doc.parts[0].range_start..=doc.parts[0].range_end;
        let extracted = doc.data.slice(range);

        let (headers, body) = parse_mime_part(&extracted);
        assert_eq!(
            headers.get("content-disposition").unwrap(),
            "form-data; name=\"$ai_input\""
        );
        assert_eq!(headers.get("content-type").unwrap(), "application/json");
        assert_eq!(body, body_content);
    }

    #[tokio::test]
    async fn test_multiple_parts_document_extract_each_by_range() {
        let event_uuid = "test-event-uuid";

        let doc = build_multipart_document(
            event_uuid,
            vec![
                BlobData {
                    property_name: "$ai_input".to_string(),
                    content_type: Some("application/json".to_string()),
                    content_encoding: None,
                    data: Bytes::from_static(b"{\"q\": 1}"),
                },
                BlobData {
                    property_name: "$ai_output".to_string(),
                    content_type: Some("text/plain".to_string()),
                    content_encoding: None,
                    data: Bytes::from_static(b"response text"),
                },
                BlobData {
                    property_name: "$ai_metadata".to_string(),
                    content_type: Some("application/json".to_string()),
                    content_encoding: None,
                    data: Bytes::from_static(b"{\"tokens\": 100}"),
                },
            ],
        );

        // Should have three parts with non-overlapping ranges
        assert_eq!(doc.parts.len(), 3);
        assert_eq!(doc.parts[0].property_name, "$ai_input");
        assert_eq!(doc.parts[1].property_name, "$ai_output");
        assert_eq!(doc.parts[2].property_name, "$ai_metadata");

        // Ranges should not overlap
        assert!(doc.parts[0].range_end < doc.parts[1].range_start);
        assert!(doc.parts[1].range_end < doc.parts[2].range_start);

        // Full document should parse as valid multipart
        let parts = parse_all_parts(doc.data.clone(), &doc.boundary).await;
        assert_eq!(parts.len(), 3);
        assert_eq!(parts[0].2.as_ref(), b"{\"q\": 1}");
        assert_eq!(parts[1].2.as_ref(), b"response text");
        assert_eq!(parts[2].2.as_ref(), b"{\"tokens\": 100}");

        // Extract each part by range - should get headers + body (no boundaries)
        let extracted1 = doc
            .data
            .slice(doc.parts[0].range_start..=doc.parts[0].range_end);
        let (headers, body) = parse_mime_part(&extracted1);
        assert!(headers
            .get("content-disposition")
            .unwrap()
            .contains("$ai_input"));
        assert_eq!(headers.get("content-type").unwrap(), "application/json");
        assert_eq!(body, b"{\"q\": 1}");

        let extracted2 = doc
            .data
            .slice(doc.parts[1].range_start..=doc.parts[1].range_end);
        let (headers, body) = parse_mime_part(&extracted2);
        assert!(headers
            .get("content-disposition")
            .unwrap()
            .contains("$ai_output"));
        assert_eq!(headers.get("content-type").unwrap(), "text/plain");
        assert_eq!(body, b"response text");

        let extracted3 = doc
            .data
            .slice(doc.parts[2].range_start..=doc.parts[2].range_end);
        let (headers, body) = parse_mime_part(&extracted3);
        assert!(headers
            .get("content-disposition")
            .unwrap()
            .contains("$ai_metadata"));
        assert_eq!(headers.get("content-type").unwrap(), "application/json");
        assert_eq!(body, b"{\"tokens\": 100}");
    }

    #[tokio::test]
    async fn test_content_type_defaults_to_octet_stream() {
        let event_uuid = "test-event-uuid";

        let doc = build_multipart_document(
            event_uuid,
            vec![BlobData {
                property_name: "$ai_data".to_string(),
                content_type: None, // No content type specified
                content_encoding: None,
                data: Bytes::from_static(b"binary data"),
            }],
        );

        let extracted = doc
            .data
            .slice(doc.parts[0].range_start..=doc.parts[0].range_end);
        let (headers, _) = parse_mime_part(&extracted);
        assert_eq!(
            headers.get("content-type").unwrap(),
            "application/octet-stream"
        );
    }
}
