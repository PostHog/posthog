use async_trait::async_trait;
use bytes::{BufMut, Bytes, BytesMut};
use serde_json::{Map, Value};

use crate::s3_client::{S3Client, S3Error};

/// Result of uploading blobs, containing the base URL and part metadata for generating URLs.
pub struct UploadedBlobs {
    /// Base S3 URL without range parameter (e.g., "s3://bucket/prefix/team/uuid")
    pub base_url: String,
    /// Blob parts in order, with their byte ranges
    pub parts: Vec<BlobPartRange>,
}

/// A blob part with its byte range in the concatenated file.
pub struct BlobPartRange {
    pub property_name: String,
    pub range_start: usize,
    pub range_end: usize,
}

impl UploadedBlobs {
    /// Insert S3 URLs into event properties.
    pub fn insert_urls_into_properties(&self, properties: &mut Map<String, Value>) {
        for part in &self.parts {
            let url = format!(
                "{}?range={}-{}",
                self.base_url, part.range_start, part.range_end
            );
            properties.insert(part.property_name.clone(), Value::String(url));
        }
    }
}

/// Trait for blob storage implementations.
/// Allows mocking in tests via dynamic dispatch.
#[async_trait]
pub trait BlobStorage: Send + Sync {
    /// Upload multiple blobs as a single concatenated file.
    /// Returns metadata for generating S3 URLs with byte ranges.
    async fn upload_blobs(
        &self,
        token: &str,
        event_uuid: &str,
        blobs: Vec<(String, Bytes)>,
    ) -> Result<UploadedBlobs, S3Error>;
}

/// AI-specific blob storage that handles concatenation and URL generation.
pub struct AiBlobStorage {
    s3_client: S3Client,
    prefix: String,
}

impl AiBlobStorage {
    pub fn new(s3_client: S3Client, prefix: String) -> Self {
        Self { s3_client, prefix }
    }
}

#[async_trait]
impl BlobStorage for AiBlobStorage {
    /// Upload multiple blobs as a single concatenated file.
    /// Returns metadata for generating S3 URLs with byte ranges.
    ///
    /// `token` is used as the partition key in the S3 path.
    /// TODO: Replace with team_id once secret key signing is implemented.
    async fn upload_blobs(
        &self,
        token: &str,
        event_uuid: &str,
        blobs: Vec<(String, Bytes)>,
    ) -> Result<UploadedBlobs, S3Error> {
        if blobs.is_empty() {
            return Ok(UploadedBlobs {
                base_url: String::new(),
                parts: vec![],
            });
        }

        // Concatenate all blobs and track byte ranges
        let mut concatenated = BytesMut::new();
        let mut parts = Vec::with_capacity(blobs.len());

        for (property_name, data) in blobs {
            let range_start = concatenated.len();
            concatenated.put(data);
            let range_end = concatenated.len() - 1; // Inclusive end

            parts.push(BlobPartRange {
                property_name,
                range_start,
                range_end,
            });
        }

        // Upload concatenated data
        let key = format!("{}{}/{}", self.prefix, token, event_uuid);
        self.s3_client
            .put_object(&key, concatenated.freeze(), "application/octet-stream")
            .await?;

        let base_url = format!("s3://{}/{}", self.s3_client.bucket(), key);

        Ok(UploadedBlobs { base_url, parts })
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
        blobs: Vec<(String, Bytes)>,
    ) -> Result<UploadedBlobs, S3Error> {
        if blobs.is_empty() {
            return Ok(UploadedBlobs {
                base_url: String::new(),
                parts: vec![],
            });
        }

        // Calculate byte ranges without actually uploading
        let mut offset = 0;
        let mut parts = Vec::with_capacity(blobs.len());

        for (property_name, data) in blobs {
            let range_start = offset;
            let range_end = offset + data.len() - 1;
            offset += data.len();

            parts.push(BlobPartRange {
                property_name,
                range_start,
                range_end,
            });
        }

        let key = format!("{}{}/{}", self.prefix, token, event_uuid);
        let base_url = format!("s3://{}/{}", self.bucket, key);

        Ok(UploadedBlobs { base_url, parts })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_blob_part_range_url_generation() {
        let uploaded = UploadedBlobs {
            base_url: "s3://capture/llma/phc_test_token/abc-def".to_string(),
            parts: vec![
                BlobPartRange {
                    property_name: "$ai_input".to_string(),
                    range_start: 0,
                    range_end: 99,
                },
                BlobPartRange {
                    property_name: "$ai_output".to_string(),
                    range_start: 100,
                    range_end: 249,
                },
            ],
        };

        let mut properties = Map::new();
        uploaded.insert_urls_into_properties(&mut properties);

        assert_eq!(
            properties.get("$ai_input").unwrap().as_str().unwrap(),
            "s3://capture/llma/phc_test_token/abc-def?range=0-99"
        );
        assert_eq!(
            properties.get("$ai_output").unwrap().as_str().unwrap(),
            "s3://capture/llma/phc_test_token/abc-def?range=100-249"
        );
    }

    #[test]
    fn test_s3_url_format() {
        let bucket = "capture";
        let prefix = "llma/";
        let token = "phc_test_token";
        let event_uuid = "550e8400-e29b-41d4-a716-446655440000";

        let key = format!("{prefix}{token}/{event_uuid}");
        let url = format!("s3://{bucket}/{key}");

        assert_eq!(
            url,
            "s3://capture/llma/phc_test_token/550e8400-e29b-41d4-a716-446655440000"
        );
    }
}
