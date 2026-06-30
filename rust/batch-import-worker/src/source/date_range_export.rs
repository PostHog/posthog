use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};

use anyhow::{Context, Error};
use async_trait::async_trait;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use reqwest::header::HeaderMap;
use reqwest::{Client, Error as ReqwestError};
use tempfile::TempDir;
use tokio::{fs::File, io::AsyncWriteExt, sync::Mutex};
use tracing::{debug, info, warn};

use super::{read_prepared_chunk, remove_prepared_key, DataSource, PreparedPart};
use crate::error::{RateLimitedError, ToUserError};
use crate::extractor::PartExtractor;
use crate::staging::StagingGuard;

// Extract a user friendly error message
// from status code of request to the export source endpoint
fn extract_status_error(error: &ReqwestError) -> String {
    if let Some(status) = error.status() {
        match status.as_u16() {
            400 => "Export endpoint returned 400 -- check your date range, credentials, and API key permissions".to_string(),
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

// Parse Retry-After header per RFC7231: either delta-seconds or HTTP-date
pub(crate) fn parse_retry_after_header(headers: &HeaderMap) -> Option<Duration> {
    let value = headers.get(reqwest::header::RETRY_AFTER)?;
    let s = value.to_str().ok()?;

    if let Ok(seconds) = s.trim().parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }

    if let Ok(date) = httpdate::parse_http_date(s) {
        let now = std::time::SystemTime::now();
        if let Ok(diff) = date.duration_since(now) {
            // clamp to zero if in past
            return Some(diff);
        }
    }
    None
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
    staging_dir: PathBuf,

    // Optional with defaults
    start_qp: String,
    end_qp: String,
    timeout: Duration,
    retries: usize,
    retry_delay: Duration,
    auth_config: AuthConfig,
    date_format: String,
    headers: HashMap<String, String>,
    staging_max_bytes: u64,
}

impl DateRangeExportSourceBuilder {
    pub fn new(
        base_url: String,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        interval_duration: i64,
        extractor: Arc<dyn PartExtractor>,
        staging_dir: PathBuf,
    ) -> Self {
        Self {
            base_url,
            start,
            end,
            interval_duration,
            extractor,
            staging_dir,
            start_qp: "start".to_string(),
            end_qp: "end".to_string(),
            timeout: Duration::from_secs(30),
            retries: 3,
            retry_delay: Duration::from_secs(30),
            auth_config: AuthConfig::None,
            date_format: "%Y-%m-%dT%H:%M:%SZ".to_string(),
            headers: HashMap::new(),
            staging_max_bytes: 0,
        }
    }

    pub fn with_staging_max_bytes(mut self, staging_max_bytes: u64) -> Self {
        self.staging_max_bytes = staging_max_bytes;
        self
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

    pub fn with_retry_delay(mut self, retry_delay: Duration) -> Self {
        self.retry_delay = retry_delay;
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
            interval_duration: self.interval_duration,
            start_qp: self.start_qp,
            end_qp: self.end_qp,
            headers: self.headers,
            auth_config: self.auth_config,
            date_format: self.date_format,
            client,
            retries: self.retries,
            retry_delay: self.retry_delay,
            extractor: self.extractor,
            staging_dir: self.staging_dir,
            staging_max_bytes: self.staging_max_bytes,
            temp_dir: Arc::new(Mutex::new(None)),
            prepared_keys: Arc::new(Mutex::new(HashMap::new())),
        })
    }
}

pub struct DateRangeExportSource {
    pub base_url: String,
    pub intervals: Vec<(DateTime<Utc>, DateTime<Utc>)>,
    /// The duration of each interval in seconds. Used to adjust the end date
    /// query parameter for APIs with inclusive date ranges.
    pub interval_duration: i64,
    pub client: Client,
    pub retries: usize,
    pub retry_delay: Duration,
    pub extractor: Arc<dyn PartExtractor>,
    pub start_qp: String,
    pub end_qp: String,
    staging_dir: PathBuf,
    staging_max_bytes: u64,
    temp_dir: Arc<Mutex<Option<TempDir>>>,
    prepared_keys: Arc<Mutex<HashMap<String, PreparedPart>>>,
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
        staging_dir: PathBuf,
    ) -> DateRangeExportSourceBuilder {
        DateRangeExportSourceBuilder::new(
            base_url,
            start,
            end,
            interval_duration,
            extractor,
            staging_dir,
        )
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

    pub fn format_date_range_from_key(&self, key: &str) -> Option<String> {
        let (start, end) = self.interval_from_key(key)?;
        Some(format!(
            "{} to {}",
            start.format("%Y-%m-%d %H:%M UTC"),
            end.format("%Y-%m-%d %H:%M UTC")
        ))
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
                        debug!("Cleaned up temp file: {}", path.display());
                    }
                }
            }
        }
        Ok(())
    }

    // Keys for this source need their parts to to be "prepared" before we can consume from them
    // To support exporting directly from sources that do not provide a byte seekable interface, we need to create
    // that byte seekable interface ourselves

    // This method streams the compressed data from the source into a temp `.raw`
    // file on disk, then opens a streaming decoder over it. The compressed file is
    // kept and decompressed on demand as the job reads forward, so disk usage is
    // bounded by the compressed size rather than the (potentially much larger)
    // decompressed size.
    async fn download_and_prepare_part_data(&self, key: &str) -> Result<PreparedPart, Error> {
        let (start, end) = self
            .interval_from_key(key)
            .ok_or_else(|| Error::msg("Invalid interval key"))?;

        // clean up any orphaned .raw and .data files for this job before starting download
        if let Err(e) = self.cleanup_temp_files().await {
            warn!("Failed to cleanup temp files: {:?}", e);
        }

        info!("Downloading and preparing key: {}", key);

        // Let errors (including 429 wrapped as RateLimitedError) bubble up to job-level backoff
        self.download_and_prepare_part_data_inner(key, start, end)
            .await
    }

    async fn download_and_prepare_part_data_inner(
        &self,
        key: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<PreparedPart, Error> {
        // All date range export APIs (Mixpanel, Amplitude, etc.) use inclusive date ranges,
        // meaning both start and end dates/times are included in the results. Our intervals
        // are created as semi-open [start, end), so we subtract one interval unit from the
        // end date to avoid fetching overlapping data between adjacent intervals.
        //
        // For example, with hourly intervals:
        // - Internal interval: [14:00, 15:00)
        // - Without adjustment: start=14:00, end=15:00 → returns hours 14 AND 15 (overlap!)
        // - With adjustment: start=14:00, end=14:00 → returns only hour 14 (correct)
        //
        // When the interval is shorter than interval_duration (e.g. a partial last interval),
        // we clamp end_for_query to start so the query never has end < start.
        let end_for_query =
            std::cmp::max(end - ChronoDuration::seconds(self.interval_duration), start);

        let mut request = self.client.get(&self.base_url).query(&[
            (&self.start_qp, start.format(&self.date_format).to_string()),
            (
                &self.end_qp,
                end_for_query.format(&self.date_format).to_string(),
            ),
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
            info!(
                "No data available for key: {} (404 response), sleeping for 2 seconds",
                key
            );
            tokio::time::sleep(Duration::from_secs(2)).await;
            return Ok(PreparedPart::empty());
        }

        if response.status().as_u16() == 429 {
            let headers_clone = response.headers().clone();
            let http_err = response.error_for_status().unwrap_err();
            let retry_after = parse_retry_after_header(&headers_clone);
            let rl = RateLimitedError {
                retry_after,
                source: http_err,
            };
            let err = anyhow::Error::from(rl).context(crate::error::UserError::new(
                "Rate limit exceeded -- pause the job and try again later",
            ));
            return Err(err);
        }

        let response = response.error_for_status().or_else(|status_error| {
            let friendly_msg = extract_status_error(&status_error);
            Err(status_error).user_error(friendly_msg)
        })?;

        let temp_dir = self.get_temp_dir_path().await?;

        // Pause the job if staging is already over budget (e.g. leftover from a
        // prior part) before we add to it, and again as the `.raw` grows.
        let mut guard = StagingGuard::new(self.staging_dir.clone(), self.staging_max_bytes);
        guard.check().await?;

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
            guard.record(chunk.len() as u64).await?;
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

        // Keep the `.raw` file and decompress on demand as the job reads forward.
        let reader = self.extractor.open_reader(raw_file_path.clone());

        info!(
            "Prepared key {} ({total_bytes} compressed bytes, streaming decode)",
            key
        );

        Ok(PreparedPart::streaming(raw_file_path, reader))
    }

    async fn get_chunk_from_prepared_key(
        &self,
        key: &str,
        offset: u64,
        size: u64,
    ) -> Result<Vec<u8>, Error> {
        read_prepared_chunk(&self.prepared_keys, key, offset, size).await
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
        Ok(prepared_keys.get(key).and_then(|part| part.total_size))
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

    async fn prepare_for_job(&self) -> Result<(), Error> {
        // Temp dir lifetime is tied to the job via self.temp_dir
        let temp_dir = tempfile::Builder::new()
            .prefix("job-")
            .tempdir_in(&self.staging_dir)
            .with_context(|| {
                format!(
                    "Failed to create temp directory in staging dir: {}",
                    self.staging_dir.display()
                )
            })?;
        debug!("Created temp directory for job: {:?}", temp_dir.path());

        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            *temp_dir_guard = Some(temp_dir);
        }

        Ok(())
    }

    async fn cleanup_after_job(&self) -> Result<(), Error> {
        // Clear refs then explicitly close() the temp dir to surface removal errors
        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.clear();
        }
        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            if let Some(temp_dir) = temp_dir_guard.take() {
                let path = temp_dir.path().to_path_buf();
                if let Err(e) = temp_dir.close() {
                    warn!("Failed to remove temp directory {}: {e}", path.display());
                } else {
                    debug!("Cleaned up temp directory: {}", path.display());
                }
            }
        }
        debug!("Job cleanup complete");
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

        let prepared_part = self.download_and_prepare_part_data(key).await?;

        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.insert(key.to_string(), prepared_part);
        }

        Ok(())
    }

    // Should be called after we've read the last of a key/part into memory and attempt to commit it
    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        remove_prepared_key(&self.prepared_keys, key).await;
        Ok(())
    }

    fn get_date_range_for_key(&self, key: &str) -> Option<String> {
        self.format_date_range_from_key(key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extractor::StreamingReader;
    use chrono::{TimeZone, Utc};
    use httpmock::MockServer;
    use std::path::Path;
    use tempfile::TempDir;

    /// Test extractor that streams the downloaded body back verbatim (no
    /// decompression, no newline normalization), so assertions can compare
    /// against the exact plaintext body served by the mock server.
    struct MockExtractor;

    impl PartExtractor for MockExtractor {
        fn open_reader(&self, raw_file_path: PathBuf) -> StreamingReader {
            StreamingReader::open_verbatim(raw_file_path)
        }
    }

    /// Read a key to completion through the public source API in `chunk`-sized
    /// forward reads, returning the reconstructed bytes. Mirrors how the job's
    /// chunker consumes a key (monotonic offsets), and drives lazy size discovery.
    async fn read_key_to_end(source: &DateRangeExportSource, key: &str, chunk: u64) -> Vec<u8> {
        let mut out = Vec::new();
        let mut offset = 0u64;
        loop {
            let bytes = source.get_chunk(key, offset, chunk).await.unwrap();
            if bytes.is_empty() {
                break;
            }
            offset += bytes.len() as u64;
            out.extend_from_slice(&bytes);
        }
        out
    }

    /// Count `.raw` staging files anywhere under `dir`. Peak/residual `.raw` count
    /// is how we assert staging disk is freed (see the free-on-EOF tests below).
    fn count_raw_files(dir: &Path) -> usize {
        let mut count = 0;
        let mut stack = vec![dir.to_path_buf()];
        while let Some(d) = stack.pop() {
            let Ok(entries) = std::fs::read_dir(&d) else {
                continue;
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else if path.extension().and_then(|e| e.to_str()) == Some("raw") {
                    count += 1;
                }
            }
        }
        count
    }

    const TEST_DATA: &str = r#"{"event": "test1", "timestamp": "2023-01-01T00:00:00Z"}
{"event": "test2", "timestamp": "2023-01-01T01:00:00Z"}
{"event": "test3", "timestamp": "2023-01-01T02:00:00Z"}"#;

    fn create_test_source(
        base_url: String,
        interval_duration: i64,
        staging_dir: PathBuf,
    ) -> DateRangeExportSource {
        let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2023, 1, 1, 6, 0, 0).unwrap();

        DateRangeExportSource::builder(
            base_url,
            start,
            end,
            interval_duration,
            Arc::new(MockExtractor),
            staging_dir,
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
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf()); // 1 hour intervals

        let keys = source.keys().await.unwrap();
        assert_eq!(keys.len(), 6); // 6 hours with 1-hour intervals

        assert!(keys[0].starts_with("2023-01-01T00:00:00"));
        assert!(keys[0].contains("2023-01-01T01:00:00"));
    }

    #[tokio::test]
    async fn test_parse_retry_after_seconds() {
        // delta-seconds parse
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::RETRY_AFTER,
            reqwest::header::HeaderValue::from_static("120"),
        );
        let d = super::parse_retry_after_header(&headers).unwrap();
        assert_eq!(d.as_secs(), 120);
    }

    #[tokio::test]
    async fn test_parse_retry_after_http_date() {
        // HTTP-date parse
        let future = httpdate::fmt_http_date(
            std::time::SystemTime::now() + std::time::Duration::from_secs(90),
        );
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::RETRY_AFTER,
            reqwest::header::HeaderValue::from_str(&future).unwrap(),
        );
        let d = super::parse_retry_after_header(&headers).unwrap();
        assert!(d.as_secs() <= 90 && d.as_secs() > 0);
    }

    #[tokio::test]
    async fn test_interval_key_parsing() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

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
        // With the inclusive end date fix, the end query param is adjusted by subtracting
        // interval_duration (3600 seconds = 1 hour), so end becomes the same as start.
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("start", "2023-01-01T00:00:00Z")
                .query_param("end", "2023-01-01T00:00:00Z");
            then.status(200)
                .header("content-type", "application/json")
                .body(TEST_DATA);
        });

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        // Size is discovered lazily: unknown until the stream has been read to EOF.
        assert_eq!(source.size(key).await.unwrap(), None);

        let data = read_key_to_end(&source, key, 8).await;
        assert_eq!(data, TEST_DATA.as_bytes());

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_404_handling() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(404);
        });

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
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
        let _staging = TempDir::new().unwrap();

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
            _staging.path().to_path_buf(),
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
        let _staging = TempDir::new().unwrap();

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
            _staging.path().to_path_buf(),
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

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
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

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        let file_size = TEST_DATA.len() as u64;

        // Reads are forward-only. A window that straddles EOF returns just the
        // available tail; a subsequent read at EOF returns empty.
        let chunk = source.get_chunk(key, file_size - 5, 20).await.unwrap();
        assert_eq!(chunk.len(), 5);

        let chunk = source.get_chunk(key, file_size, 10).await.unwrap();
        assert!(chunk.is_empty());

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_error_handling_401() {
        use crate::error::get_user_message;

        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(401);
        });

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        let result = source.prepare_key(key).await;
        assert!(result.is_err());
        let err = result.unwrap_err();
        let user_msg = get_user_message(&err);
        assert_eq!(user_msg, "Authentication failed, check your credentials");

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_error_handling_500() {
        use crate::error::get_user_message;

        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(500);
        });

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        let result = source.prepare_key(key).await;
        assert!(result.is_err());
        let err = result.unwrap_err();
        let user_msg = get_user_message(&err);
        assert_eq!(user_msg, "Remote server error");

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
        let _staging = TempDir::new().unwrap();

        let mut headers = HashMap::new();
        headers.insert("X-Custom-Header".to_string(), "custom-value".to_string());

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            3600,
            Arc::new(MockExtractor),
            _staging.path().to_path_buf(),
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

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();

        // The key is prepared and readable.
        let chunk = source.get_chunk(key, 0, 8).await.unwrap();
        assert!(!chunk.is_empty());

        source.cleanup_key(key).await.unwrap();

        // After cleanup the key is torn down, so reading it errors.
        assert!(source.get_chunk(key, 0, 8).await.is_err());

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_prepare_key_idempotent() {
        let server = MockServer::start();
        let mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();
        source.prepare_key(key).await.unwrap();

        assert_eq!(mock.hits(), 1);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_reading_entire_file_frees_raw_and_keeps_size() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();
        assert_eq!(
            count_raw_files(staging.path()),
            1,
            "prepared key stages one .raw"
        );

        // Reading the key to completion reconstructs the body, and the source frees
        // the compressed `.raw` on the EOF read — no `cleanup_after_job` needed.
        let data = read_key_to_end(&source, key, 8).await;
        assert_eq!(data, TEST_DATA.as_bytes());
        assert_eq!(
            count_raw_files(staging.path()),
            0,
            "the .raw must be deleted once the key is fully read"
        );

        // The bookkeeping entry is retained so the now-known size is still reportable.
        assert_eq!(
            source.size(key).await.unwrap(),
            Some(TEST_DATA.len() as u64)
        );

        source.cleanup_after_job().await.unwrap();
    }

    /// Robustness proof for the hex-security finding / the A1 class of regression:
    /// staging cleanup happens on the EOF read itself, so a caller that consumes
    /// the final chunk and immediately treats the part as done (issuing no further
    /// read) still frees the `.raw`. A single read larger than the body reaches EOF
    /// in one shot; we assert the file is gone without any terminal `offset>=total`
    /// read, and that the retained entry keeps `prepare_key` from re-downloading it.
    #[tokio::test]
    async fn test_raw_freed_on_single_eof_read_without_terminal_read() {
        let server = MockServer::start();
        let mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(200).body(TEST_DATA);
        });

        let staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, staging.path().to_path_buf());
        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        source.prepare_key(key).await.unwrap();
        assert_eq!(mock.hits(), 1);
        assert_eq!(count_raw_files(staging.path()), 1);

        // One read past the end returns the whole body and reaches EOF.
        let bytes = source
            .get_chunk(key, 0, TEST_DATA.len() as u64 + 4096)
            .await
            .unwrap();
        assert_eq!(bytes, TEST_DATA.as_bytes());

        // Cleanup fired on that read alone — no second (terminal) get_chunk issued.
        assert_eq!(
            count_raw_files(staging.path()),
            0,
            "the .raw must be freed on the EOF read, without a terminal read"
        );
        assert_eq!(
            source.size(key).await.unwrap(),
            Some(TEST_DATA.len() as u64)
        );

        // The retained entry keeps prepare_key a no-op, so the freed file is not
        // re-downloaded (which would re-stage the .raw we just reclaimed).
        source.prepare_key(key).await.unwrap();
        assert_eq!(
            mock.hits(),
            1,
            "prepare_key must not re-download a freed key"
        );
        assert_eq!(count_raw_files(staging.path()), 0);

        source.cleanup_after_job().await.unwrap();
    }

    #[tokio::test]
    async fn test_format_date_range_from_key() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

        let key = "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00";
        let formatted = source.format_date_range_from_key(key).unwrap();

        assert_eq!(formatted, "2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC");
    }

    #[tokio::test]
    async fn test_format_date_range_from_key_different_dates() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

        let key = "2023-12-31T23:30:00+00:00_2024-01-01T00:30:00+00:00";
        let formatted = source.format_date_range_from_key(key).unwrap();

        assert_eq!(formatted, "2023-12-31 23:30 UTC to 2024-01-01 00:30 UTC");
    }

    #[tokio::test]
    async fn test_format_date_range_from_invalid_key() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

        let key = "invalid-key-format";
        let formatted = source.format_date_range_from_key(key);

        assert!(formatted.is_none());
    }

    #[tokio::test]
    async fn test_get_date_range_for_key_trait_method() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

        let key = "2023-06-15T12:00:00+00:00_2023-06-15T13:00:00+00:00";
        let date_range = source.get_date_range_for_key(key).unwrap();

        assert_eq!(date_range, "2023-06-15 12:00 UTC to 2023-06-15 13:00 UTC");
    }

    #[tokio::test]
    async fn test_format_date_range_edge_cases() {
        let server = MockServer::start();
        let _staging = TempDir::new().unwrap();
        let source = create_test_source(server.url("/export"), 3600, _staging.path().to_path_buf());

        let key_with_ms = "2023-01-01T00:00:00.123+00:00_2023-01-01T01:30:45.456+00:00";
        let formatted = source.format_date_range_from_key(key_with_ms).unwrap();
        assert_eq!(formatted, "2023-01-01 00:00 UTC to 2023-01-01 01:30 UTC");

        let invalid_key = "2023-01-01T00:00:00+00:00";
        assert!(source.format_date_range_from_key(invalid_key).is_none());

        let invalid_key2 = "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00_extra";
        assert!(source.format_date_range_from_key(invalid_key2).is_none());

        let invalid_date_key = "invalid-date_2023-01-01T01:00:00+00:00";
        assert!(source
            .format_date_range_from_key(invalid_date_key)
            .is_none());
    }

    #[tokio::test]
    async fn test_429_surfaces_immediately() {
        let server = MockServer::start();

        let mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(429); // Always return 429
        });

        let _staging = TempDir::new().unwrap();
        let source = DateRangeExportSource::builder(
            server.url("/export"),
            Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap(),
            Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap(),
            3600,
            Arc::new(MockExtractor),
            _staging.path().to_path_buf(),
        )
        .build()
        .unwrap();

        source.prepare_for_job().await.unwrap();
        let keys = source.keys().await.unwrap();
        let key = &keys[0];

        let result = source.prepare_key(key).await;
        assert!(result.is_err());
        let err = result.unwrap_err();
        // Our code wraps 429 as RateLimitedError (with reqwest::Error as source). Use helper.
        assert!(crate::error::is_rate_limited_error(&err));

        // No internal retry loop anymore
        assert_eq!(
            mock.hits(),
            1,
            "Single request, surfaced to job-level backoff"
        );

        source.cleanup_after_job().await.unwrap();
    }

    /// Test that verifies no duplicate events are fetched when using adjacent date intervals.
    ///
    /// All date range export APIs (Mixpanel, Amplitude, etc.) use inclusive date ranges:
    /// - from_date and to_date are both INCLUSIVE
    /// - from_date=2025-06-05&to_date=2025-06-06 returns events from June 5 AND June 6
    ///
    /// The implementation automatically adjusts the end date query parameter by subtracting
    /// one interval_duration, so that each interval fetches only its own data without overlap.
    ///
    /// The mock server handles all possible date combinations (both buggy and correct queries).
    /// The test passes only if NO duplicate $insert_id values appear across all fetched data.
    #[tokio::test]
    async fn test_adjacent_intervals_should_not_produce_duplicate_events() {
        // Test events for each day, with unique $insert_id values
        let june_5_events = r#"{"event":"Event A","properties":{"time":1749085200,"distinct_id":"user1","$insert_id":"id_june5_event1"}}
{"event":"Event B","properties":{"time":1749088800,"distinct_id":"user2","$insert_id":"id_june5_event2"}}"#;

        let june_6_events = r#"{"event":"Event C","properties":{"time":1749171600,"distinct_id":"user1","$insert_id":"id_june6_event1"}}
{"event":"Event D","properties":{"time":1749175200,"distinct_id":"user2","$insert_id":"id_june6_event2"}}"#;

        let june_7_events = r#"{"event":"Event E","properties":{"time":1749258000,"distinct_id":"user1","$insert_id":"id_june7_event1"}}
{"event":"Event F","properties":{"time":1749261600,"distinct_id":"user2","$insert_id":"id_june7_event2"}}"#;

        let server = MockServer::start();

        // Mock all possible date query combinations, simulating the API's INCLUSIVE behavior
        // Buggy queries (old implementation would send these without adjustment):
        let _mock_buggy_1 = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("from_date", "2025-06-05")
                .query_param("to_date", "2025-06-06");
            then.status(200)
                .body(format!("{}\n{}", june_5_events, june_6_events));
        });

        let _mock_buggy_2 = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("from_date", "2025-06-06")
                .query_param("to_date", "2025-06-07");
            then.status(200)
                .body(format!("{}\n{}", june_6_events, june_7_events));
        });

        // Correct queries (implementation automatically subtracts interval_duration from end):
        let _mock_fixed_1 = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("from_date", "2025-06-05")
                .query_param("to_date", "2025-06-05");
            then.status(200).body(june_5_events);
        });

        let _mock_fixed_2 = server.mock(|when, then| {
            when.method(httpmock::Method::GET)
                .path("/export")
                .query_param("from_date", "2025-06-06")
                .query_param("to_date", "2025-06-06");
            then.status(200).body(june_6_events);
        });

        // Create source with Mixpanel-style config: daily intervals, %Y-%m-%d format
        // The interval_duration (86400 seconds = 1 day) is automatically used to adjust
        // the end date query parameter for inclusive APIs.
        let start = Utc.with_ymd_and_hms(2025, 6, 5, 0, 0, 0).unwrap();
        let end = Utc.with_ymd_and_hms(2025, 6, 7, 0, 0, 0).unwrap();
        let _staging = TempDir::new().unwrap();

        let source = DateRangeExportSource::builder(
            server.url("/export"),
            start,
            end,
            86400, // 1 day intervals - also used to adjust end date for inclusive APIs
            Arc::new(MockExtractor),
            _staging.path().to_path_buf(),
        )
        .with_query_params("from_date".to_string(), "to_date".to_string())
        .with_date_format("%Y-%m-%d".to_string())
        .build()
        .unwrap();

        source.prepare_for_job().await.unwrap();

        let keys = source.keys().await.unwrap();
        assert_eq!(keys.len(), 2, "Should have 2 daily intervals");

        // Fetch data for both intervals
        source.prepare_key(&keys[0]).await.unwrap();
        let chunk0 = source.get_chunk(&keys[0], 0, 100000).await.unwrap();

        source.prepare_key(&keys[1]).await.unwrap();
        let chunk1 = source.get_chunk(&keys[1], 0, 100000).await.unwrap();

        // Combine all fetched data and extract $insert_id values
        let data0 = String::from_utf8(chunk0).unwrap();
        let data1 = String::from_utf8(chunk1).unwrap();
        let combined = format!("{}\n{}", data0, data1);

        // Extract all $insert_id values from the combined data
        let mut insert_ids: Vec<&str> = Vec::new();
        for line in combined.lines() {
            if line.trim().is_empty() {
                continue;
            }
            if let Some(start_idx) = line.find("\"$insert_id\":\"") {
                let rest = &line[start_idx + 14..];
                if let Some(end_idx) = rest.find('"') {
                    insert_ids.push(&rest[..end_idx]);
                }
            }
        }

        // Check for duplicates
        let mut seen = std::collections::HashSet::new();
        let mut duplicates = Vec::new();
        for id in &insert_ids {
            if !seen.insert(*id) {
                duplicates.push(*id);
            }
        }

        assert!(
            duplicates.is_empty(),
            "DUPLICATE EVENTS DETECTED! The following $insert_id values appeared multiple times: {:?}\n\
            This indicates that adjacent date intervals are fetching overlapping data.\n\
            Total events fetched: {}, Unique events: {}\n\
            Chunk 0 data:\n{}\n\
            Chunk 1 data:\n{}",
            duplicates,
            insert_ids.len(),
            seen.len(),
            data0,
            data1
        );

        source.cleanup_after_job().await.unwrap();
    }
}
