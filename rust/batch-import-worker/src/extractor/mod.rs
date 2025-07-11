use anyhow::{Context, Error};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::{path::Path, path::PathBuf, sync::Arc};
use tokio::{fs::File, io::AsyncWriteExt};
use tracing::debug;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtractorType {
    ZipGzipJson,
    PlainGzip,
}

impl Default for ExtractorType {
    fn default() -> Self {
        Self::PlainGzip
    }
}

impl ExtractorType {
    pub fn create_extractor(&self) -> Arc<dyn PartExtractor> {
        match self {
            ExtractorType::ZipGzipJson => Arc::new(ZipGzipJsonExtractor),
            ExtractorType::PlainGzip => Arc::new(PlainGzipExtractor),
        }
    }
}

#[derive(Clone)]
pub struct ExtractedPartData {
    pub data_file_path: PathBuf,
    pub data_file_size: usize,
}

// The data source trait requires parts that can be seekable via byte offsets
// To support data sources that don't have seekable parts by default (export endpoints that return compresed files),
// we need this extractor that can handle converting whatever content the data source returned into a seekable file
#[async_trait]
pub trait PartExtractor: Send + Sync {
    async fn extract_compressed_to_seekable_file(
        &self,
        key: &str,
        file_path: &std::path::Path,
        temp_dir: &std::path::Path,
    ) -> Result<ExtractedPartData, Error>;
}

pub struct ZipGzipJsonExtractor;

#[async_trait]
impl PartExtractor for ZipGzipJsonExtractor {
    // This extracts a seekable file from a zip file that contains a bunch of json.gz files
    async fn extract_compressed_to_seekable_file(
        &self,
        key: &str,
        file_path: &Path,
        temp_dir: &Path,
    ) -> Result<ExtractedPartData, Error> {
        let data_file_path = temp_dir.join(format!("{}.data", key.replace(':', "_")));
        let mut output_file = File::create(&data_file_path)
            .await
            .with_context(|| format!("Failed to create data file for key: {}", key))?;
        let mut total_size = 0usize;

        let file_entries = tokio::task::spawn_blocking({
            let file_path = file_path.to_path_buf();
            move || -> Result<Vec<String>, Error> {
                use std::fs::File as StdFile;
                use zip::ZipArchive;

                let file = StdFile::open(file_path).with_context(|| "Failed to open zip file")?;
                let mut archive = ZipArchive::new(file)
                    .with_context(|| "Failed to read and create zip archive")?;

                let mut file_names: Vec<String> = (0..archive.len())
                    .filter_map(|i| {
                        archive.by_index(i).ok().and_then(|file| {
                            let name = file.name().to_string();
                            if name.ends_with(".json.gz") {
                                Some(name)
                            } else {
                                None
                            }
                        })
                    })
                    .collect();

                file_names.sort_by(|a, b| natord::compare(a, b));
                Ok(file_names)
            }
        })
        .await
        .with_context(|| {
            format!(
                "Failed to extract file entries from zip archive for key: {}",
                key
            )
        })??;

        for file_name in file_entries {
            let start_offset = total_size;

            let (tx, mut rx) = tokio::sync::mpsc::channel::<Result<Vec<u8>, Error>>(16);

            let decompress_handle = tokio::task::spawn_blocking({
                let file_path = file_path.to_path_buf();
                let file_name = file_name.clone();

                move || -> Result<bool, Error> {
                    use flate2::read::GzDecoder;
                    use std::fs::File as StdFile;
                    use std::io::Read;
                    use zip::ZipArchive;

                    let file = StdFile::open(file_path)
                        .with_context(|| "Failed to open zip file for decompression")?;
                    let mut archive = ZipArchive::new(file)
                        .with_context(|| "Failed to read zip archive for decompression")?;
                    let zip_file = archive
                        .by_name(&file_name)
                        .with_context(|| "Failed to find file in zip archive")?;
                    let mut decoder = GzDecoder::new(zip_file);

                    let mut buffer = [0u8; 8192];
                    let mut last_byte = None;

                    loop {
                        let bytes_read = decoder
                            .read(&mut buffer)
                            .with_context(|| "Failed to decompress gzip data from file")?;
                        if bytes_read == 0 {
                            break;
                        }
                        if bytes_read > 0 {
                            last_byte = Some(buffer[bytes_read - 1]);
                        }

                        if tx.blocking_send(Ok(buffer[..bytes_read].to_vec())).is_err() {
                            break;
                        }
                    }
                    Ok(last_byte != Some(b'\n'))
                }
            });
            let mut file_size = 0usize;
            while let Some(chunk_result) = rx.recv().await {
                let chunk = chunk_result?;
                output_file
                    .write_all(&chunk)
                    .await
                    .with_context(|| "Failed to write decompressed data to file")?;
                file_size += chunk.len();
            }

            let needs_newline = decompress_handle
                .await
                .with_context(|| "Failed to decompress file from zip archive")??;
            if needs_newline && file_size > 0 {
                output_file
                    .write_all(b"\n")
                    .await
                    .with_context(|| "Failed to write newline to file")?;
                file_size += 1;
            }

            total_size += file_size;
            debug!(
                "Processed file: {} from byte {} to {}",
                file_name, start_offset, total_size
            );
        }

        output_file
            .sync_all()
            .await
            .with_context(|| format!("Failed to sync output file to disk for key: {}", key))?;
        Ok(ExtractedPartData {
            data_file_path,
            data_file_size: total_size,
        })
    }
}

pub struct PlainGzipExtractor;

#[async_trait]
impl PartExtractor for PlainGzipExtractor {
    async fn extract_compressed_to_seekable_file(
        &self,
        key: &str,
        file_path: &Path,
        temp_dir: &Path,
    ) -> Result<ExtractedPartData, Error> {
        let data_file_path = temp_dir.join(format!("{}.data", key.replace(':', "_")));
        let mut output_file = File::create(&data_file_path)
            .await
            .with_context(|| format!("Failed to create data file for key: {}", key))?;

        let (tx, mut rx) = tokio::sync::mpsc::channel::<Result<Vec<u8>, Error>>(16);

        let decompress_handle = tokio::task::spawn_blocking({
            let file_path = file_path.to_path_buf();

            move || -> Result<bool, Error> {
                use flate2::read::GzDecoder;
                use std::fs::File as StdFile;
                use std::io::Read;

                let input_file = StdFile::open(file_path)
                    .context("Failed to open gzip file for decompression")?;
                let mut decoder = GzDecoder::new(input_file);
                let mut buffer = [0u8; 8192];
                let mut last_byte = None;

                loop {
                    let bytes_read = decoder.read(&mut buffer)?;
                    if bytes_read == 0 {
                        break;
                    }

                    if bytes_read > 0 {
                        last_byte = Some(buffer[bytes_read - 1]);
                    }

                    if tx.blocking_send(Ok(buffer[..bytes_read].to_vec())).is_err() {
                        break;
                    }
                }

                Ok(last_byte != Some(b'\n'))
            }
        });

        let mut total_size = 0usize;
        while let Some(chunk_result) = rx.recv().await {
            let chunk = chunk_result?;
            output_file
                .write_all(&chunk)
                .await
                .with_context(|| "Failed to write decompressed data to file")?;
            total_size += chunk.len();
        }

        let needs_newline = decompress_handle
            .await
            .context("Gzip decompression task panicked")??;
        let final_size = if needs_newline && total_size > 0 {
            output_file
                .write_all(b"\n")
                .await
                .with_context(|| "Failed to write newline to file")?;
            total_size + 1
        } else {
            total_size
        };

        output_file
            .sync_all()
            .await
            .with_context(|| format!("Failed to sync output file to disk for key: {}", key))?;

        Ok(ExtractedPartData {
            data_file_path,
            data_file_size: final_size,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::Result;
    use flate2::{write::GzEncoder, Compression};
    use std::{fs::File as StdFile, io::Write};
    use tempfile::TempDir;
    use tokio::fs;
    use zip::{write::SimpleFileOptions, ZipWriter};

    async fn create_test_gzip_file(content: &str, path: &std::path::Path) -> Result<()> {
        let file = StdFile::create(path)?;
        let mut encoder = GzEncoder::new(file, Compression::default());
        encoder.write_all(content.as_bytes())?;
        encoder.finish()?;
        Ok(())
    }

    async fn create_test_zip_with_gzip_json(
        json_files: Vec<(&str, &str)>,
        zip_path: &std::path::Path,
    ) -> Result<()> {
        let file = StdFile::create(zip_path)?;
        let mut zip = ZipWriter::new(file);

        for (filename, content) in json_files {
            let options = SimpleFileOptions::default();
            zip.start_file(filename, options)?;

            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(content.as_bytes())?;
            let compressed = encoder.finish()?;

            zip.write_all(&compressed)?;
        }
        zip.finish()?;
        Ok(())
    }

    #[tokio::test]
    async fn test_extractory_type_default() {
        let default_type = ExtractorType::default();
        assert!(matches!(default_type, ExtractorType::PlainGzip));
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_simple() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let gzip_file = temp_path.join("test.gz");
        let test_content = "line1\nline2\nline3\n";
        create_test_gzip_file(test_content, &gzip_file).await?;

        let extractor = PlainGzipExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("test_key", &gzip_file, temp_path)
            .await?;

        assert_eq!(result.data_file_size, test_content.len());
        assert!(result.data_file_path.exists());

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert_eq!(extracted_content, test_content);
        Ok(())
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_adds_newline_when_missing() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let gzip_file = temp_path.join("test.gz");
        let test_content = "line1\nline2\nline3"; // No trailing newline
        create_test_gzip_file(test_content, &gzip_file).await?;

        let extractor = PlainGzipExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("test_key", &gzip_file, temp_path)
            .await?;

        assert_eq!(result.data_file_size, test_content.len() + 1); // +1 for added newline

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert_eq!(extracted_content, format!("{}\n", test_content));

        Ok(())
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_empty_file() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let gzip_file = temp_path.join("empty.gz");
        create_test_gzip_file("", &gzip_file).await?;

        let extractor = PlainGzipExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("empty_key", &gzip_file, temp_path)
            .await?;

        assert_eq!(result.data_file_size, 0);
        assert!(result.data_file_path.exists());

        Ok(())
    }
    #[tokio::test]
    async fn test_zip_gzip_json_extractor_single_file() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let zip_file = temp_path.join("test.zip");
        let json_content = r#"{"event": "test", "timestamp": 123}
    {"event": "test2", "timestamp": 456}"#;

        create_test_zip_with_gzip_json(vec![("data.json.gz", json_content)], &zip_file).await?;

        let extractor = ZipGzipJsonExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("zip_test", &zip_file, temp_path)
            .await?;

        assert!(result.data_file_path.exists());
        assert!(result.data_file_size > 0);

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert!(extracted_content.contains("test"));
        assert!(extracted_content.contains("test2"));

        Ok(())
    }
    #[tokio::test]
    async fn test_zip_gzip_json_extractor_multiple_files() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let zip_file = temp_path.join("multi.zip");
        let json_files = vec![
            ("001.json.gz", r#"{"id": 1}"#),
            ("002.json.gz", r#"{"id": 2}"#),
            ("003.json.gz", r#"{"id": 3}"#),
        ];

        create_test_zip_with_gzip_json(json_files, &zip_file).await?;

        let extractor = ZipGzipJsonExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("multi_test", &zip_file, temp_path)
            .await?;

        assert!(result.data_file_path.exists());
        assert!(result.data_file_size > 0);

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert!(extracted_content.contains(r#"{"id": 1}"#));
        assert!(extracted_content.contains(r#"{"id": 2}"#));
        assert!(extracted_content.contains(r#"{"id": 3}"#));

        Ok(())
    }

    #[tokio::test]
    async fn test_zip_gzip_json_extractor_ignores_non_json_gz_files() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let zip_file = temp_path.join("mixed.zip");

        let file = StdFile::create(&zip_file)?;
        let mut zip = ZipWriter::new(file);

        zip.start_file("data.json.gz", SimpleFileOptions::default())?;
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"valid json")?;
        let compressed = encoder.finish()?;
        zip.write_all(&compressed)?;

        zip.start_file("readme.txt", SimpleFileOptions::default())?;
        zip.write_all(b"ignore me")?;

        zip.start_file("data.json", SimpleFileOptions::default())?;
        zip.write_all(b"also ignore")?;

        zip.finish()?;

        let extractor = ZipGzipJsonExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("mixed_test", &zip_file, temp_path)
            .await?;

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert!(extracted_content.contains("valid json"));
        assert!(!extracted_content.contains("ignore me"));
        assert!(!extracted_content.contains("also ignore"));

        Ok(())
    }
    #[tokio::test]
    async fn test_key_sanitization() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let gzip_file = temp_path.join("test.gz");
        create_test_gzip_file("test", &gzip_file).await?;

        let extractor = PlainGzipExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("test:key:with:colons", &gzip_file, temp_path)
            .await?;

        let expected_filename = "test_key_with_colons.data";
        assert!(result.data_file_path.file_name().unwrap().to_str().unwrap() == expected_filename);

        Ok(())
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_nonexistent_file() {
        let temp_dir = TempDir::new().unwrap();
        let temp_path = temp_dir.path();

        let nonexistent_file = temp_path.join("nonexistent.gz");
        let extractor = PlainGzipExtractor;

        let result = extractor
            .extract_compressed_to_seekable_file("test", &nonexistent_file, temp_path)
            .await;

        assert!(result.is_err());
    }
    #[tokio::test]
    async fn test_zip_gzip_extractor_invalid_zip() {
        let temp_dir = TempDir::new().unwrap();
        let temp_path = temp_dir.path();

        let invalid_zip = temp_path.join("invalid.zip");
        fs::write(&invalid_zip, b"not a zip file").await.unwrap();

        let extractor = ZipGzipJsonExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("test", &invalid_zip, temp_path)
            .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_zip_gzip_extractor_empty_zip() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        // Create empty zip
        let zip_file = temp_path.join("empty.zip");
        let file = StdFile::create(&zip_file)?;
        let zip = ZipWriter::new(file);
        zip.finish()?;

        let extractor = ZipGzipJsonExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("empty_zip", &zip_file, temp_path)
            .await?;

        assert_eq!(result.data_file_size, 0);
        assert!(result.data_file_path.exists());

        Ok(())
    }
    #[tokio::test]
    async fn test_large_file_handling() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let large_content = "line\n".repeat(10000);
        let gzip_file = temp_path.join("large.gz");
        create_test_gzip_file(&large_content, &gzip_file).await?;

        let extractor = PlainGzipExtractor;
        let result = extractor
            .extract_compressed_to_seekable_file("large_test", &gzip_file, temp_path)
            .await?;

        assert_eq!(result.data_file_size, large_content.len());

        let extracted_content = fs::read_to_string(&result.data_file_path).await?;
        assert_eq!(extracted_content, large_content);

        Ok(())
    }

    #[tokio::test]
    async fn test_trait_usage() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let temp_path = temp_dir.path();

        let gzip_file = temp_path.join("trait_test.gz");
        create_test_gzip_file("trait test content\n", &gzip_file).await?;

        let extractor: Arc<dyn PartExtractor> = Arc::new(PlainGzipExtractor);
        let result = extractor
            .extract_compressed_to_seekable_file("trait_test", &gzip_file, temp_path)
            .await?;

        assert!(result.data_file_path.exists());
        assert_eq!(result.data_file_size, "trait test content\n".len());

        Ok(())
    }
}
