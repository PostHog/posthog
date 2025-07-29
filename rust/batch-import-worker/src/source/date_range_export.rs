use super::DataSource;
use crate::error::ToUserError;
use crate::extractor::{ExtractedPartData, PartExtractor};
use anyhow::{Context, Error};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use reqwest::{Client, Error as ReqwestError};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};
use tempfile::TempDir;
use tokio::{
    fs::File,
    io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt},
    sync::Mutex,
};
use tracing::{debug, info, warn};

// Extract a user friendly error message
// from status code of request to the export source endpoint
fn extract_status_error(error: &ReqwestError) -> String {
    if let Some(status) = error.status() {
        match status.as_u16() {
            400 => "Export endpoint returned 400 -- your data export may be too large to support exporting straight from this source".to_string(),
            401 => "Authentication failed, check your credentials".to_string(),
            403 => "Access denied -- check your credentials".to_string(),
            408 => "Request timed out -- data export may be too large to support exporting straight from source".to_string(),
            429 => "Rate limit exceeded -- pause the job and try again later".to_string(),
            500 => "Remote server error".to_string(),
            _ => "Unknown error -- try the job again or use a different source".to_string(),
        }
    } else {
        "Unknown error -- try the job again or use a different source".to_string()
    }
}

fn extract_client_request_error(error: &ReqwestError) -> String {
    if error.is_timeout() {
        "Request timed out -- data export may be too large to support exporting from this source"
            .to_string()
    } else {
        "Unknown error -- try the job again or use a different source".to_string()
    }
}

#[derive(Clone)]
pub enum AuthConfig {
    None,
    ApiKey { header_name: String, key: String },
    BearerToken { token: String },
    BasicAuth { username: String, password: String },
    // Annoying special case for Mixpanel
    MixpanelAuth { secret_key: String },
}

pub struct DateRangeExportSourceBuilder {
    base_url: String,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    interval_duration: i64,
    extractor: Arc<dyn PartExtractor>,

    // Optional with defaults
    start_qp: String,
    end_qp: String,
    timeout: Duration,
    retries: usize,
    auth_config: AuthConfig,
    date_format: String,
    headers: HashMap<String, String>,
}

impl DateRangeExportSourceBuilder {
    pub fn new(
        base_url: String,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        interval_duration: i64,
        extractor: Arc<dyn PartExtractor>,
    ) -> Self {
        Self {
            base_url,
            start,
            end,
            interval_duration,
            extractor,
            start_qp: "start".to_string(),
            end_qp: "end".to_string(),
            timeout: Duration::from_secs(30),
            retries: 3,
            auth_config: AuthConfig::None,
            date_format: "%Y-%m-%dT%H:%M:%SZ".to_string(),
            headers: HashMap::new(),
        }
    }

    pub fn with_query_params(mut self, start_qp: String, end_qp: String) -> Self {
        self.start_qp = start_qp;
        self.end_qp = end_qp;
        self
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    pub fn with_retries(mut self, retries: usize) -> Self {
        self.retries = retries;
        self
    }

    pub fn with_auth(mut self, auth_config: AuthConfig) -> Self {
        self.auth_config = auth_config;
        self
    }

    pub fn with_date_format(mut self, date_format: String) -> Self {
        self.date_format = date_format;
        self
    }

    pub fn with_headers(mut self, headers: HashMap<String, String>) -> Self {
        self.headers = headers;
        self
    }
    pub fn build(self) -> Result<DateRangeExportSource, Error> {
        let mut intervals = Vec::new();
        let mut current = self.start;
        while current < self.end {
            let next = std::cmp::min(
                current + ChronoDuration::seconds(self.interval_duration),
                self.end,
            );
            intervals.push((current, next));
            current = next;
        }

        let client = reqwest::Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| Error::msg(e.to_string()))?;

        Ok(DateRangeExportSource {
            base_url: self.base_url,
            intervals,
            start_qp: self.start_qp,
            end_qp: self.end_qp,
            headers: self.headers,
            auth_config: self.auth_config,
            date_format: self.date_format,
            client,
            retries: self.retries,
            extractor: self.extractor,
            temp_dir: Arc::new(Mutex::new(None)),
            prepared_keys: Arc::new(Mutex::new(HashMap::new())),
        })
    }
}

pub struct DateRangeExportSource {
    pub base_url: String,
    pub intervals: Vec<(DateTime<Utc>, DateTime<Utc>)>,
    pub client: Client,
    pub retries: usize,
    pub extractor: Arc<dyn PartExtractor>,
    pub start_qp: String,
    pub end_qp: String,
    temp_dir: Arc<Mutex<Option<TempDir>>>,
    prepared_keys: Arc<Mutex<HashMap<String, ExtractedPartData>>>,
    auth_config: AuthConfig,
    date_format: String,
    headers: HashMap<String, String>,
}

/*
 * Support for importing data directly from another analytics service's batch export endpoint.
 * A date range is specified for the chunk of data to be exported and usually comes to the client
 * in a compressed format.
 *
 * Handling different compression formats is supported by supplying a PartExtractor trait that can be used to extract
 * data from a compressed file into a byte seekable interface that can be processed in chunks
 *
 * The tricky part about this source is that the export endpoints have some minimum time range that they can export over.
 * Because a customer may have more data in the minimum time range than we can processs and commit in one go, we need to cache the data
 * on the worker's file system so we don't have to download the entire part of data for an interval
 * for each chunk that we process from it.
 */
impl DateRangeExportSource {
    pub fn builder(
        base_url: String,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        interval_duration: i64,
        extractor: Arc<dyn PartExtractor>,
    ) -> DateRangeExportSourceBuilder {
        DateRangeExportSourceBuilder::new(base_url, start, end, interval_duration, extractor)
    }

    fn interval_key((start, end): (DateTime<Utc>, DateTime<Utc>)) -> String {
        format!("{}_{}", start.to_rfc3339(), end.to_rfc3339())
    }

    fn interval_from_key(&self, key: &str) -> Option<(DateTime<Utc>, DateTime<Utc>)> {
        let parts: Vec<&str> = key.split('_').collect();
        if parts.len() != 2 {
            return None;
        }
        let start = DateTime::parse_from_rfc3339(parts[0])
            .ok()?
            .with_timezone(&Utc);
        let end = DateTime::parse_from_rfc3339(parts[1])
            .ok()?
            .with_timezone(&Utc);
        Some((start, end))
    }

    async fn get_temp_dir_path(&self) -> Result<PathBuf, Error> {
        let temp_dir_guard = self.temp_dir.lock().await;
        Ok(temp_dir_guard
            .as_ref()
            .ok_or_else(|| Error::msg("Temp directory not initialized"))?
            .path()
            .to_path_buf())
    }

    async fn cleanup_temp_files(&self) -> Result<(), Error> {
        let temp_dir = self.get_temp_dir_path().await?;
        let mut entries = tokio::fs::read_dir(temp_dir)
            .await
            .with_context(|| "Failed to read temp directory while cleaning up files")?;
        while let Some(entry) = entries.next_entry().await.with_context(|| {
            "Failed to read next entry from temp directory, while cleaning up files"
        })? {
            let path = entry.path();
            if let Some(extension) = path.extension() {
                if extension == "raw" || extension == "data" {
                    if let Err(e) = tokio::fs::remove_file(&path).await {
                        warn!("Failed to remove temp file {}: {:?}", path.display(), e);
                    } else {
                        info!("Cleaned up temp file: {}", path.display());
                    }
                }
            }
        }
        Ok(())
    }

    // Keys for this source need their parts to to be "prepared" before we can consume from them
    // To support exporting directly from sources that do not provide a byte seekable interface, we need to create
    // that byte seekable interface ourselves

    // This method streams the data from the source into a temp file on disk via 8kb buffers,
    // then uses an extractor to convert the compressed/separated data into a single file that
    // can be read/seeked through via byte offsets
    async fn download_and_prepare_part_data(&self, key: &str) -> Result<ExtractedPartData, Error> {
        let (start, end) = self
            .interval_from_key(key)
            .ok_or_else(|| Error::msg("Invalid interval key"))?;

        // clean up any orphaned .raw and .data files for this job before starting download
        if let Err(e) = self.cleanup_temp_files().await {
            warn!("Failed to cleanup temp files: {:?}", e);
        }

        info!("Downloading and preparing key: {}", key);
        let mut request = self.client.get(&self.base_url).query(&[
            (&self.start_qp, start.format(&self.date_format).to_string()),
            (&self.end_qp, end.format(&self.date_format).to_string()),
        ]);

        request = match &self.auth_config {
            AuthConfig::None => request,
            AuthConfig::ApiKey { header_name, key } => request.header(header_name, key),
            AuthConfig::BearerToken { token } => request.bearer_auth(token),
            AuthConfig::BasicAuth { username, password } => {
                request.basic_auth(username, Some(password))
            }
            AuthConfig::MixpanelAuth { secret_key } => request.basic_auth(secret_key, None::<&str>),
        };

        let mut headers = reqwest::header::HeaderMap::new();
        for (key, value) in &self.headers {
            if let (Ok(header_name), Ok(header_value)) = (
                reqwest::header::HeaderName::from_bytes(key.as_bytes()),
                reqwest::header::HeaderValue::from_str(value),
            ) {
                headers.insert(header_name, header_value);
            }
        }
        request = request.headers(headers);

        let response = request.send().await.or_else(|req_error| {
            let friendly_msg = extract_client_request_error(&req_error);
            Err(req_error).user_error(friendly_msg)
        })?;

        // If there isn't data for this interval, create an empty file with size 0
        // We want to return something to the .process() thread so that we end up making a commit
        // for this key/part of the overall job
        if response.status() == 404 {
            info!("No data available for key: {} (404 response)", key);
            let temp_dir = self.get_temp_dir_path().await?;

            let empty_data_file_path = temp_dir.join(format!("{}.data", key.replace(':', "_")));
            let empty_file = File::create(&empty_data_file_path).await?;
            empty_file.sync_all().await?;

            return Ok(ExtractedPartData {
                data_file_path: empty_data_file_path,
                data_file_size: 0,
            });
        }

        let response = response.error_for_status().or_else(|status_error| {
            let friendly_msg = extract_status_error(&status_error);
            Err(status_error).user_error(friendly_msg)
        })?;

        let temp_dir = self.get_temp_dir_path().await?;

        let raw_file_path = temp_dir.join(format!("{}.raw", key.replace(':', "_")));
        let mut raw_file = File::create(&raw_file_path)
            .await
            .with_context(|| format!("Failed to create raw file : {}", raw_file_path.display()))?;

        let mut stream = response.bytes_stream();
        let mut total_bytes = 0;

        use futures_util::StreamExt;

        while let Some(result) = stream.next().await {
            let chunk: bytes::Bytes = result?;
            raw_file.write_all(&chunk).await.with_context(|| {
                format!(
                    "Failed to write chunk to raw file: {}",
                    raw_file_path.display()
                )
            })?;
            total_bytes += chunk.len();
        }

        raw_file.sync_all().await.with_context(|| {
            format!(
                "Failed to sync raw file to disk: {}",
                raw_file_path.display()
            )
        })?;
        info!(
            "Streamed {} bytes to file {} for key: {}",
            total_bytes,
            raw_file_path.display(),
            key
        );

        let extracted_part = self
            .extractor
            .extract_compressed_to_seekable_file(key, &raw_file_path, temp_dir.as_path())
            .await
            .with_context(|| {
                format!(
                    "Failed to extract compressed to seekable file for key: {}",
                    key
                )
            })?;

        if let Err(e) = tokio::fs::remove_file(&raw_file_path).await {
            warn!(
                "Failed to remove raw file {}: {}",
                raw_file_path.display(),
                e
            );
        }

        info!(
            "Extracted part key: {} with {} total bytes",
            key, extracted_part.data_file_size
        );

        Ok(extracted_part)
    }

    async fn get_chunk_from_prepared_key(
        &self,
        key: &str,
        offset: u64,
        size: u64,
    ) -> Result<Vec<u8>, Error> {
        let extracted_part = {
            let prepared_keys = self.prepared_keys.lock().await;
            prepared_keys
                .get(key)
                .ok_or_else(|| Error::msg(format!("Key not prepared: {}", key)))?
                .clone()
        };

        if extracted_part.data_file_size == 0 {
            return Ok(Vec::new());
        }

        let total_size = extracted_part.data_file_size as u64;
        if offset >= total_size {
            return Ok(Vec::new());
        }

        let end_offset = std::cmp::min(offset + size, total_size);
        let read_size = (end_offset - offset) as usize;

        let mut file = File::open(extracted_part.data_file_path)
            .await
            .with_context(|| format!("Failed to open extracted data file for key: {}", key))?;
        file.seek(std::io::SeekFrom::Start(offset))
            .await
            .with_context(|| {
                format!(
                    "Failed to seek to offset {} in extracted data file for key: {}",
                    offset, key
                )
            })?;
        let mut buffer = vec![0u8; read_size];
        file.read_exact(&mut buffer).await.with_context(|| {
            format!(
                "Failed to read exact {} bytes from extracted data file for key: {}",
                read_size, key
            )
        })?;

        if end_offset == total_size {
            if let Err(e) = self.cleanup_key(key).await {
                warn!("Failed to cleanup key {}: {:?}", key, e);
            }
        }

        Ok(buffer)
    }
}

#[async_trait]
impl DataSource for DateRangeExportSource {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        Ok(self
            .intervals
            .iter()
            .map(|&interval| Self::interval_key(interval))
            .collect())
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        let prepared_keys = self.prepared_keys.lock().await;
        if let Some(extracted_part) = prepared_keys.get(key) {
            let total_bytes = extracted_part.data_file_size as u64;
            Ok(Some(total_bytes))
        } else {
            Ok(None)
        }
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let mut retries = self.retries;
        loop {
            match self.get_chunk_from_prepared_key(key, offset, size).await {
                Ok(chunk) => return Ok(chunk),
                Err(e) => {
                    if retries == 0 {
                        return Err(e);
                    }
                    warn!(
                        "Error reading prepared chunk: {:?}, remaining retries: {}",
                        e, retries
                    );
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    retries -= 1;
                }
            }
        }
    }

    // The lifecycle of this temp dir matches the lifecycle of the job
    // It should be cleaned up when the job completes, fails, panics, etc.
    // This ensures that files are cleaned up on a per job basis, but does not clean up
    // .raw and .data files that are created for each key that we process per job
    // We need to make sure to properly manage the clean up of those files as well
    async fn prepare_for_job(&self) -> Result<(), Error> {
        let temp_dir =
            tempfile::tempdir().with_context(|| "Failed to create temp directory for job")?;
        info!("Created temp directory for job: {:?}", temp_dir.path());

        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            *temp_dir_guard = Some(temp_dir);
        }

        Ok(())
    }

    async fn cleanup_after_job(&self) -> Result<(), Error> {
        let keys_and_data = {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys
                .drain()
                .collect::<Vec<(String, ExtractedPartData)>>()
        };
        let mut cleanup_errors = Vec::new();

        for (key, extracted_part) in keys_and_data {
            if let Err(e) = tokio::fs::remove_file(&extracted_part.data_file_path).await {
                let err = e.to_string();
                cleanup_errors.push((key.clone(), e));
                warn!("Failed to remove temp file for key {}: {}", key, err);
            } else {
                info!("Cleaned up key: {}", key);
            }
        }
        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            if let Some(temp_dir) = temp_dir_guard.take() {
                drop(temp_dir);
                info!("Cleaned up temp directory");
            }
        }

        info!("Job cleanup complete");
        if !cleanup_errors.is_empty() {
            return Err(Error::msg(format!(
                "Failed to cleanup {} keys: {:?}",
                cleanup_errors.len(),
                cleanup_errors.iter().map(|(k, _)| k).collect::<Vec<_>>()
            )));
        }
        Ok(())
    }

    // We call this every time we process a chunk from a key/part
    // So this needs to be idempotent/a no-op when the key/part is already prepared
    async fn prepare_key(&self, key: &str) -> Result<(), Error> {
        {
            let prepared_keys = self.prepared_keys.lock().await;
            if prepared_keys.contains_key(key) {
                debug!("Key already prepared: {}", key);
                return Ok(());
            }
        }

        let extracted_part = self.download_and_prepare_part_data(key).await?;

        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.insert(key.to_string(), extracted_part);
        }

        Ok(())
    }

    // Should be called after we've read the last of a key/part into memory and attempt to commit it
    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        let extracted_part = {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.remove(key)
        };

        if let Some(extracted_part) = extracted_part {
            if let Err(e) = tokio::fs::remove_file(&extracted_part.data_file_path).await {
                warn!("Failed to remove temp file for key {}: {}", key, e);
            } else {
                info!("Cleaned up key: {}", key);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extractor::ExtractedPartData;
    use chrono::{TimeZone, Utc};
    use httpmock::MockServer;
    use std::path::Path;
    use tokio::fs;

    struct MockExtractor;

    #[async_trait]
    impl PartExtractor for MockExtractor {
        async fn extract_compressed_to_seekable_file(
            &self,
            _key: &str,
            raw_file_path: &Path,
            temp_dir: &Path,
        ) -> Result<ExtractedPartData, Error> {
            let data_file_path = temp_dir.join(format!(
                "{}.data",
                raw_file_path.file_stem().unwrap().to_string_lossy()
            ));
            fs::copy(raw_file_path, &data_file_path).await?;
            let metadata = fs::metadata(&data_file_path).await?;
            Ok(ExtractedPartData {
                data_file_path,
                data_file_size: metadata.len() as usize,
            })
        }
    }

    const TEST_DATA: &str = r#"{"event": "test1", "timestamp": "2023-01-01T00:00:00Z"}
{"event": "test2", "timestamp": "2023-01-01T01:00:00Z"}
{"event": "test3", "timestamp": "2023-01-01T02:00:00Z"}"#;

    fn create_test_source(base_url: String, interval_duration: i64) -> DateRangeExportSource {
        let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2023, 1, 1, 6, 0, 0).unwrap();

        DateRangeExportSource::builder(
            base_url,
            start,
            end,
            interval_duration,
            Arc::new(MockExtractor),
        )
        .with_auth(AuthConfig::None)
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(HashMap::new())
        .build()
        .unwrap()
    }

    #[tokio::test]
    async fn test_interval_generation() {
        let server = MockServer::start();
        let source = create_test_source(server.url("/export"), 3600); // 1 hour intervals

        let keys = source.keys().await.unwrap();
        assert_eq!(keys.len(), 6); // 6 hours with 1-hour intervals

        assert!(keys[0].starts_with("2023-01-01T00:00:00"));
        assert!(keys[0].contains("2023-01-01T01:00:00"));
    }

    #[tokio::test]
    async fn test_interval_key_parsing() {
        let server = MockServer::start();
        let source = create_test_source(server.url("/export"), 3600);

        let key = "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00";
        let interval = source.interval_from_key(key).unwrap();

        assert_eq!(
            interval.0,
            Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap()
        );
        assert_eq!(
            interval.1,
            Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap()
        );
    }

    #[tokio::test]
    async fn test_successful_data_download_and_prepare() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("start", "2023-01-01T00:00:00Z")
                .query_param("end", "2023-01-01T01:00:00Z");
            then.status(200)
                .header("content-type", "application/json")
                .body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let size = source.size(key).await.unwrap();
        assert!(size.is_some());
        assert_eq!(size.unwrap(), TEST_DATA.len() as u64);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_404_handling() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(404);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let size = source.size(key).await.unwrap();
        assert_eq!(size, Some(0)); // Should create empty file for 404

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_auth_configurations() {
        let server = MockServer::start();

        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .header("X-API-Key", "test-key");
            then.status(200).body(TEST_DATA);
        });

        let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap();

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
        )
        .with_auth(AuthConfig::ApiKey {
            header_name: "X-API-Key".to_string(),
            key: "test-key".to_string(),
        })
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(HashMap::new())
        .build()
        .unwrap();

        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        source.prepare_key(&keys[0]).await.unwrap();
        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_bearer_token_auth() {
        let server = MockServer::start();

        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .header("Authorization", "Bearer test-token");
            then.status(200).body(TEST_DATA);
        });

        let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap();

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
        )
        .with_auth(AuthConfig::BearerToken {
            token: "test-token".to_string(),
        })
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(HashMap::new())
        .build()
        .unwrap();

        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        source.prepare_key(&keys[0]).await.unwrap();
        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_get_chunk_functionality() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let chunk = source.get_chunk(key, 0, 10).await.unwrap();
        assert_eq!(chunk.len(), 10);
        assert_eq!(&chunk, &TEST_DATA.as_bytes()[0..10]);

        let chunk = source.get_chunk(key, 10, 20).await.unwrap();
        assert_eq!(chunk.len(), 20);
        assert_eq!(&chunk, &TEST_DATA.as_bytes()[10..30]);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_get_chunk_beyond_file_size() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let file_size = TEST_DATA.len() as u64;

        let chunk = source.get_chunk(key, file_size + 100, 10).await.unwrap();
        assert!(chunk.is_empty());

        let chunk = source.get_chunk(key, file_size - 5, 20).await.unwrap();
        assert_eq!(chunk.len(), 5);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_error_handling_401() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(401);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        let result = source.prepare_key(key).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Authentication failed"));

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_error_handling_500() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(500);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        let result = source.prepare_key(key).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Remote server error"));

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_custom_headers() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .header("X-Custom-Header", "custom-value");
            then.status(200).body(TEST_DATA);
        });

        let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap();

        let mut headers = HashMap::new();
        headers.insert("X-Custom-Header".to_string(), "custom-value".to_string());

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
        )
        .with_auth(AuthConfig::None)
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(headers)
        .build()
        .unwrap();

        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        source.prepare_key(&keys[0]).await.unwrap();
        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_key_cleanup() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        assert!(source.size(key).await.unwrap().is_some());

        source.cleanup_key(key).await.unwrap();

        assert!(source.size(key).await.unwrap().is_none());

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_prepare_key_idempotent() {
        let server = MockServer::start();
        let mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();
        source.prepare_key(key).await.unwrap();

        assert_eq!(mock.hits(), 1);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_reading_entire_file_cleans_up_key() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let source = create_test_source(server.url("/export"), 3600);
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let file_size = source.size(key).await.unwrap().unwrap();

        let _chunk = source.get_chunk(key, 0, file_size).await.unwrap();

        assert!(source.size(key).await.unwrap().is_none());

        source.cleanup_after_job().await.unwrap();
    }
}
