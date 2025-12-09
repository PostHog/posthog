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

/// AI-specific blob storage that handles concatenation and URL generation.
#[derive(Clone)]
pub struct AiBlobStorage {
    s3_client: S3Client,
    prefix: String,
}

impl AiBlobStorage {
    pub fn new(s3_client: S3Client, prefix: String) -> Self {
        Self { s3_client, prefix }
    }

    /// Upload multiple blobs as a single concatenated file.
    /// Returns metadata for generating S3 URLs with byte ranges.
    pub async fn upload_blobs(
        &self,
        team_id: u32,
        event_uuid: &str,
        blobs: Vec<(String, Bytes)>, // (property_name, data)
    ) -> Result<UploadedBlobs, S3Error> {
        if blobs.is_empty() {
            // No blobs to upload, return empty result
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
        let key = format!("{}{}/{}", self.prefix, team_id, event_uuid);
        self.s3_client
            .put_object(&key, concatenated.freeze(), "application/octet-stream")
            .await?;

        let base_url = format!("s3://{}/{}", self.s3_client.bucket(), key);

        Ok(UploadedBlobs { base_url, parts })
    }

    /// Check S3 connectivity.
    pub async fn check_health(&self) -> bool {
        self.s3_client.check_health().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_blob_part_range_url_generation() {
        let uploaded = UploadedBlobs {
            base_url: "s3://capture/llma/123/abc-def".to_string(),
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
            "s3://capture/llma/123/abc-def?range=0-99"
        );
        assert_eq!(
            properties.get("$ai_output").unwrap().as_str().unwrap(),
            "s3://capture/llma/123/abc-def?range=100-249"
        );
    }

    #[test]
    fn test_s3_url_format() {
        let bucket = "capture";
        let prefix = "llma/";
        let team_id = 123u32;
        let event_uuid = "550e8400-e29b-41d4-a716-446655440000";

        let key = format!("{}{}/{}", prefix, team_id, event_uuid);
        let url = format!("s3://{}/{}", bucket, key);

        assert_eq!(
            url,
            "s3://capture/llma/123/550e8400-e29b-41d4-a716-446655440000"
        );
    }
}
