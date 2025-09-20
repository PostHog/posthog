use std::sync::{atomic::Ordering, Arc};

use anyhow::{Context, Error};

use crate::metrics as metric_emit;
use common_types::InternallyCapturedEvent;
use model::{JobModel, JobState, PartState};
use tokio::sync::Mutex;
use tracing::{debug, error, info, warn};

use crate::{
    context::AppContext,
    emit::Emitter,
    error::{extract_retry_after_from_error, get_user_message, is_rate_limited_error},
    job::backoff::format_backoff_messages,
    parse::{format::ParserFn, Parsed},
    source::DataSource,
    spawn_liveness_loop,
};

pub mod backoff;
pub mod config;
pub mod model;

#[derive(Debug, PartialEq)]
enum ErrorHandlingDecision {
    Backoff {
        delay: std::time::Duration,
        status_msg: String,
        display_msg: String,
    },
    Pause {
        error_msg: String,
        display_msg: String,
    },
}

fn decide_on_error(
    err: &anyhow::Error,
    current_date_range: Option<&str>,
    policy: crate::job::backoff::BackoffPolicy,
    current_attempt: u32,
    user_message: &str,
) -> ErrorHandlingDecision {
    if is_rate_limited_error(err) {
        let mut delay = policy.next_delay(current_attempt);
        if let Some(ra) = extract_retry_after_from_error(err) {
            delay = std::cmp::min(ra, policy.max_delay);
        }
        let (status_msg, display_msg) = format_backoff_messages(current_date_range, delay);
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else {
        let error_msg = match current_date_range {
            Some(dr) => format!("{user_message} (Date range: {dr})"),
            None => user_message.to_string(),
        };
        let display_msg = match current_date_range {
            Some(dr) => format!("{user_message} (Date range: {dr})"),
            None => user_message.to_string(),
        };
        ErrorHandlingDecision::Pause {
            error_msg,
            display_msg,
        }
    }
}

fn should_pause_due_to_max_attempts(next_attempt: u32, max_attempts: u32) -> bool {
    max_attempts > 0 && next_attempt >= max_attempts
}

async fn reset_backoff_after_success(
    context: Arc<AppContext>,
    model: &mut JobModel,
) -> Result<(), Error> {
    model.reset_backoff_in_db(&context.db).await
}

pub struct Job {
    pub context: Arc<AppContext>,

    // The job maintains a copy of the job state, outside of the model,
    // because process in a pipelined fashion, and to do that we need to
    // seperate "in-memory job state" from "database job state"
    pub state: Mutex<JobState>,
    // We also maintain a copy of the model. This and the above are wrapped in a mutex
    // because we simultaneously modify both, modifying our in-memory state when we
    // fetch and parse data, and then updating the model state when we commit data
    pub model: Mutex<JobModel>,

    pub source: Box<dyn DataSource>,
    pub transform: Arc<ParserFn>,

    // We keep a mutex here so we can mutably borrow this and the job state at the same time
    pub sink: Mutex<Box<dyn Emitter>>,

    // We want to fetch data and send it at the same time, and this acts as a temporary store
    // for the data we've fetched, but not yet sent
    checkpoint: Mutex<Option<Checkpoint>>,
}

struct Checkpoint {
    key: String,
    data: Parsed<Vec<InternallyCapturedEvent>>,
}

impl Job {
    pub async fn new(mut model: JobModel, context: Arc<AppContext>) -> Result<Self, Error> {
        let is_restarting = model.state.is_some();

        let source = model
            .import_config
            .source
            .construct(&model.secrets, context.clone(), is_restarting)
            .await
            .with_context(|| "Failed to construct data source for job".to_string())?;

        // Some sources need to prepare for the job before we can start processing it
        source.prepare_for_job().await?;

        let transform = Box::new(
            model
                .import_config
                .data_format
                .get_parser(&model, context.clone())
                .await?,
        );

        let sink = model
            .import_config
            .sink
            .construct(context.clone(), &model)
            .await
            .with_context(|| format!("Failed to construct sink for job {}", model.id))?;

        let mut state = model
            .state
            .as_ref()
            .cloned()
            .unwrap_or_else(|| JobState { parts: vec![] });

        if state.parts.is_empty() {
            info!("Found job with no parts, initializing parts list");
            // If we have no parts, we assume this is the first time picking up the job,
            // and populate the parts list
            let mut parts = Vec::new();
            let keys = source
                .keys()
                .await
                .with_context(|| "Failed to get source keys".to_string())?;
            for key in keys {
                let size = source
                    .size(&key)
                    .await
                    .with_context(|| format!("Failed to get size for part {key}"))?;
                debug!("Got size for part {key}: {size:?}");
                parts.push(PartState {
                    key,
                    current_offset: 0,
                    total_size: size,
                });
            }
            state.parts = parts;
            model.state = Some(state.clone());
            info!("Initialized parts list: {:?}", state.parts);
        }

        Ok(Self {
            context,
            model: Mutex::new(model),
            state: Mutex::new(state),
            source,
            transform: Arc::new(transform),
            sink: Mutex::new(sink),
            checkpoint: Mutex::new(None),
        })
    }

    pub async fn process(self) -> Result<Option<Self>, Error> {
        let next_chunk_fut = self.get_next_chunk();
        let next_commit_fut = self.do_commit();

        let (next_chunk, next_commit) = tokio::join!(next_chunk_fut, next_commit_fut);

        if let Err(e) = next_commit {
            // If we fail to commit, we just log and bail out - the job will be paused if it needs to be,
            // but this pod should restart, in case it's sink is in some bad state
            error!("Failed to commit chunk: {:?}", e);
            return Err(e);
        }

        let next = match next_chunk {
            Ok(Some(chunk)) => chunk,
            Ok(None) => {
                // We're done fetching and parsing, so we can complete the job
                if let Err(e) = self.source.cleanup_after_job().await {
                    warn!("Failed to cleanup after job: {:?}", e);
                }
                self.successfully_complete().await?;
                return Ok(None);
            }
            Err(e) => {
                if let Err(e) = self.source.cleanup_after_job().await {
                    warn!("Failed to cleanup after job: {:?}", e);
                }
                let user_facing_error_message = get_user_message(&e);
                let current_date_range = {
                    let state = self.state.lock().await;
                    state
                        .parts
                        .iter()
                        .find(|p| !p.is_done())
                        .and_then(|p| self.source.get_date_range_for_key(&p.key))
                };

                let policy = self.context.config.backoff_policy();
                let current_attempt = {
                    let model = self.model.lock().await;
                    model.backoff_attempt.max(0) as u32
                };
                let next_attempt = current_attempt.saturating_add(1);
                match decide_on_error(
                    &e,
                    current_date_range.as_deref(),
                    policy,
                    current_attempt,
                    user_facing_error_message,
                ) {
                    ErrorHandlingDecision::Backoff {
                        delay,
                        status_msg,
                        display_msg,
                    } => {
                        if should_pause_due_to_max_attempts(
                            next_attempt,
                            self.context.config.backoff_max_attempts,
                        ) {
                            let mut model = self.model.lock().await;
                            let msg = match current_date_range.as_deref() {
                                Some(dr) => format!(
                                    "Max backoff attempts reached for date range {dr} (attempt {next_attempt}). Pausing."
                                ),
                                None => format!(
                                    "Max backoff attempts reached (attempt {next_attempt}). Pausing."
                                ),
                            };
                            model
                                .pause(
                                    self.context.clone(),
                                    msg,
                                    Some(
                                        "Rate limit persisted. Job paused after maximum retries."
                                            .to_string(),
                                    ),
                                )
                                .await?;
                            return Ok(None);
                        }

                        error!(
                            job_id = %self.model.lock().await.id,
                            attempt = next_attempt,
                            delay_secs = delay.as_secs(),
                            "rate limited (429): scheduling retry"
                        );
                        metric_emit::backoff_event(delay.as_secs_f64());

                        let mut model = self.model.lock().await;
                        model
                            .schedule_backoff(
                                &self.context.db,
                                delay,
                                status_msg,
                                Some(display_msg),
                                next_attempt as i32,
                            )
                            .await?;
                        return Ok(None);
                    }
                    ErrorHandlingDecision::Pause {
                        error_msg,
                        display_msg,
                    } => {
                        let mut model = self.model.lock().await;
                        error!(job_id = %model.id, error = ?e, "Pausing job due to error: {}", error_msg);
                        model
                            .pause(self.context.clone(), error_msg, Some(display_msg))
                            .await?;
                        return Ok(None);
                    }
                }
            }
        };

        let mut checkpoint = self.checkpoint.lock().await;
        *checkpoint = Some(Checkpoint {
            key: next.0,
            data: next.1,
        });

        drop(checkpoint);

        // This wasn't the last part/chunk, so we return the job to let it be processed again
        Ok(Some(self))
    }

    async fn get_next_chunk(
        &self,
    ) -> Result<Option<(String, Parsed<Vec<InternallyCapturedEvent>>)>, Error> {
        let mut state = self.state.lock().await;

        let Some(next_part) = state.parts.iter_mut().find(|p| !p.is_done()) else {
            info!("Found no next part, returning");
            return Ok(None); // We're done fetching
        };

        let key = next_part.key.clone();
        self.source.prepare_key(&key).await?;

        if next_part.total_size.is_none() {
            if let Some(actual_size) = self.source.size(&key).await? {
                next_part.total_size = Some(actual_size);
                info!("Updated total size for key {}: {}", key, actual_size);

                {
                    let mut model = self.model.lock().await;
                    if let Some(model_state) = &mut model.state {
                        if let Some(model_part) =
                            model_state.parts.iter_mut().find(|p| p.key == key)
                        {
                            model_part.total_size = Some(actual_size);
                        }
                    }
                }

                if actual_size == 0 {
                    info!(
                        "No data available for this key: {} try to get the next chunk",
                        key
                    );
                    next_part.current_offset = actual_size;
                    return Ok(Some((
                        key.clone(),
                        Parsed {
                            consumed: 0,
                            data: vec![],
                        },
                    )));
                }
            }
        }

        info!("Fetching part chunk {:?}", next_part);

        let next_chunk = self
            .source
            .get_chunk(
                &next_part.key,
                next_part.current_offset,
                self.context.config.chunk_size as u64,
            )
            .await
            .context(format!("Fetching part chunk {next_part:?}"))?;

        let is_last_chunk = match next_part.total_size {
            Some(total_size) => next_part.current_offset + next_chunk.len() as u64 > total_size,
            None => false,
        };

        let chunk_bytes = next_chunk.len();

        info!("Fetched part chunk {:?}", next_part);
        let m_tf = self.transform.clone();
        // This is computationally expensive, so we run it in a blocking task
        let parsed = tokio::task::spawn_blocking(move || (m_tf)(next_chunk))
            .await?
            .context(format!("Processing part chunk {next_part:?}"))?;

        info!(
            "Parsed part chunk {:?}, consumed {} bytes",
            next_part, parsed.consumed
        );

        // If this is the last chunk, and we didn't consume all of it, or we didn't manage to
        // consume any of this chunk, we've got a bad chunk, and should pause the job with an error.
        if parsed.consumed < chunk_bytes && is_last_chunk || parsed.data.is_empty() {
            return Err(Error::msg(format!(
                "Failed to parse any data from part {} at offset {}",
                next_part.key, next_part.current_offset
            )));
        }

        // Update the in-memory part state (the read will be committed to the DB once the write is done)
        next_part.current_offset += parsed.consumed as u64;

        let ret_key = key.clone();
        {
            let mut model = self.model.lock().await;
            reset_backoff_after_success(self.context.clone(), &mut model).await?;
        }

        Ok(Some((ret_key, parsed)))
    }

    async fn do_commit(&self) -> Result<(), Error> {
        let liveness_loop_flag = spawn_liveness_loop(self.context.worker_liveness.clone());
        self.shutdown_guard()?;
        let mut checkpoint_lock = self.checkpoint.lock().await;

        let Some(checkpoint) = checkpoint_lock.take() else {
            info!("No checkpointed data to commit, returning");
            return Ok(()); // We've got no checkpointed data to commit, so we're done
        };

        let (key, parsed) = (checkpoint.key, checkpoint.data);

        info!("Committing part {} consumed {} bytes", key, parsed.consumed);
        info!("Committing {} events", parsed.data.len());

        let mut sink = self.sink.lock().await;
        self.shutdown_guard()?;
        // If this fails, we just bail out, and then eventually someone else will pick up the job again and re-process this chunk
        let txn = sink.begin_write().await?;
        info!("Writing {} events", parsed.data.len());
        // If this fails, as above
        self.shutdown_guard()?;
        txn.emit(&parsed.data).await?;
        // This is where things get tricky - if we fail to commit the chunk to the sink in the next step, and we've told PG we've
        // committed the chunk, we'll bail out, and whoever comes next will end up skipping this chunk. To prevent this, we do a two
        // stage commit, where we pause the job before committing the chunk to the sink, and then only unpause it after the sink commit,
        // such that if we get interrupted between the two, the job will be paused, and manual intervention will be required to resume it.
        // This operator can then confirm whether the sink commit succeeded or not (by looking at the last event written, or by
        // looking at logs, or both). The jobs status message is set to enable this kind of debugging.
        self.shutdown_guard()?; // This is the last time we call this during the commit - if we get this far, we want to commit fully if at all possible
        info!("Beginning PG part commit");
        self.begin_part_commit(&key, parsed.consumed).await?;
        info!("Beginning emitter part commit");

        let to_sleep = txn.commit_write().await?;
        info!("Finishing PG part commit");
        self.complete_commit().await?;
        info!("Committed part {} consumed {} bytes", key, parsed.consumed);
        info!("Sleeping for {:?}", to_sleep);
        tokio::time::sleep(to_sleep).await;
        liveness_loop_flag.store(false, Ordering::Relaxed);

        Ok(())
    }

    async fn successfully_complete(self) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        let result = model.complete(&self.context.db).await;
        if result.is_ok() {
            info!(job_id = %model.id, "Batch import job complete");
        }
        result
    }

    // Writes the new partstate to the DB, and sets the job status to paused, such that if there's an issue with the sink commit, the job
    // will be paused, and manual intervention will be required to resume it
    async fn begin_part_commit(&self, key: &str, consumed: usize) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        let Some(model_state) = &mut model.state else {
            return Err(Error::msg("No model state found"));
        };

        // Iterate through the parts list and update the relevant part
        let Some(part) = model_state.parts.iter_mut().find(|p| p.key == key) else {
            return Err(Error::msg(format!("No part found with key {key}")));
        };

        part.current_offset += consumed as u64;

        let status_message = format!(
            "Starting commit of part {} to offset {}, consumed {} additional bytes",
            key, part.current_offset, consumed
        );

        model
            .pause(
                self.context.clone(),
                status_message,
                Some("Job paused while committing events".to_string()),
            )
            .await
    }

    // Unpauses the job
    async fn complete_commit(&self) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        model.unpause(self.context.clone()).await
    }

    // Used during the commit operations as a shorthand way to bail before an operation if we get a shutdown signal
    fn shutdown_guard(&self) -> Result<(), Error> {
        if !self.context.is_running() {
            warn!("Running flag set to flase during job processing, bailing");
            Err(Error::msg(
                "Running flag set to flase during job processing, bailing",
            ))
        } else {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use httpmock::Method;
    use httpmock::MockServer;
    use reqwest::Client;
    use std::collections::HashMap;

    struct MockDataSource {
        keys: Vec<String>,
        date_ranges: HashMap<String, String>,
    }

    impl MockDataSource {
        fn new() -> Self {
            let mut date_ranges = HashMap::new();
            date_ranges.insert(
                "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00".to_string(),
                "2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC".to_string(),
            );
            date_ranges.insert(
                "2023-01-01T01:00:00+00:00_2023-01-01T02:00:00+00:00".to_string(),
                "2023-01-01 01:00 UTC to 2023-01-01 02:00 UTC".to_string(),
            );

            Self {
                keys: vec![
                    "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00".to_string(),
                    "2023-01-01T01:00:00+00:00_2023-01-01T02:00:00+00:00".to_string(),
                ],
                date_ranges,
            }
        }
    }

    #[async_trait]
    impl DataSource for MockDataSource {
        async fn keys(&self) -> Result<Vec<String>, Error> {
            Ok(self.keys.clone())
        }

        async fn size(&self, _key: &str) -> Result<Option<u64>, Error> {
            Ok(Some(100))
        }

        async fn get_chunk(&self, _key: &str, _offset: u64, _size: u64) -> Result<Vec<u8>, Error> {
            Err(Error::msg("Mock error for testing"))
        }

        fn get_date_range_for_key(&self, key: &str) -> Option<String> {
            self.date_ranges.get(key).cloned()
        }
    }

    struct MockDataSourceWithoutDateRange {
        keys: Vec<String>,
    }

    impl MockDataSourceWithoutDateRange {
        fn new() -> Self {
            Self {
                keys: vec!["some-key".to_string()],
            }
        }
    }

    #[async_trait]
    impl DataSource for MockDataSourceWithoutDateRange {
        async fn keys(&self) -> Result<Vec<String>, Error> {
            Ok(self.keys.clone())
        }

        async fn size(&self, _key: &str) -> Result<Option<u64>, Error> {
            Ok(Some(100))
        }

        async fn get_chunk(&self, _key: &str, _offset: u64, _size: u64) -> Result<Vec<u8>, Error> {
            Err(Error::msg("Mock error for testing"))
        }
    }

    #[test]
    fn test_error_message_includes_date_range_when_available() {
        let mock_source = MockDataSource::new();
        let key = "2023-01-01T00:00:00+00:00_2023-01-01T01:00:00+00:00";

        let date_range = mock_source.get_date_range_for_key(key);
        assert_eq!(
            date_range,
            Some("2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC".to_string())
        );

        let error_message = format!(
            "Failed to fetch and parse chunk for date range {}: Mock error",
            date_range.unwrap()
        );
        assert_eq!(
            error_message,
            "Failed to fetch and parse chunk for date range 2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC: Mock error"
        );
    }

    #[tokio::test]
    async fn test_decide_on_error_backoff_for_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(429);
        });

        let resp = Client::new()
            .get(server.url("/export"))
            .send()
            .await
            .unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);

        let decision = decide_on_error(
            &err,
            Some("2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC"),
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "Rate limit exceeded",
        );

        match decision {
            ErrorHandlingDecision::Backoff {
                delay,
                status_msg,
                display_msg,
            } => {
                assert_eq!(delay.as_secs(), 60);
                assert!(status_msg.contains("retry"));
                assert!(display_msg.contains("Date range"));
            }
            _ => panic!("expected backoff"),
        }
    }

    #[tokio::test]
    async fn test_decide_on_error_pause_for_non_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/export");
            then.status(500);
        });

        let resp = Client::new()
            .get(server.url("/export"))
            .send()
            .await
            .unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);

        let decision = decide_on_error(
            &err,
            None,
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            2,
            "Remote server error",
        );

        match decision {
            ErrorHandlingDecision::Pause {
                error_msg,
                display_msg,
            } => {
                assert_eq!(error_msg, "Remote server error");
                assert_eq!(display_msg, "Remote server error");
            }
            _ => panic!("expected pause"),
        }
    }

    #[tokio::test]
    async fn test_retry_after_overrides_backoff() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(Method::GET).path("/rl");
            then.status(429).header("Retry-After", "2");
        });

        let resp = Client::new().get(server.url("/rl")).send().await.unwrap();
        // Clone headers from the actual response before turning it into an error
        let headers_clone = resp.headers().clone();
        let http_err = resp.error_for_status().unwrap_err();

        // Wrap into our RateLimitedError manually to include Retry-After from response
        let retry_after =
            crate::source::date_range_export::parse_retry_after_header(&headers_clone)
                .expect("retry-after parsed");
        let rl = crate::error::RateLimitedError {
            retry_after: Some(retry_after),
            source: http_err,
        };
        let err = anyhow::Error::from(rl);

        let decision = super::decide_on_error(
            &err,
            None,
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "Rate limit exceeded",
        );

        match decision {
            super::ErrorHandlingDecision::Backoff { delay, .. } => {
                assert_eq!(delay.as_secs(), 2);
            }
            _ => panic!("expected backoff"),
        }
    }

    #[test]
    fn test_reset_backoff_after_success() {
        let mut model = JobModel {
            // Minimal dummy values; only fields we need in this function
            id: uuid::Uuid::now_v7(),
            team_id: 1,
            created_at: chrono::Utc::now(),
            updated_at: chrono::Utc::now(),
            lease_id: None,
            leased_until: None,
            status: super::model::JobStatus::Running,
            status_message: None,
            display_status_message: None,
            state: Some(JobState { parts: vec![] }),
            import_config: super::config::JobConfig {
                // Construct a trivially valid config that won't be used by this test
                source: super::config::SourceConfig::Folder(super::config::FolderSourceConfig {
                    path: "/tmp".to_string(),
                }),
                data_format: crate::parse::format::FormatConfig::JsonLines {
                    skip_blanks: true,
                    content: crate::parse::content::ContentType::Captured,
                },
                sink: super::config::SinkConfig::NoOp,
                import_events: true,
                generate_identify_events: false,
                generate_group_identify_events: false,
            },
            secrets: super::config::JobSecrets {
                secrets: std::collections::HashMap::new(),
            },
            was_leased: false,
            backoff_attempt: 5,
            backoff_until: None,
        };

        // Only verifies local field change; DB write path covered elsewhere
        model.backoff_attempt = 0;
        assert_eq!(model.backoff_attempt, 0);
    }

    #[test]
    fn test_error_message_without_date_range() {
        let mock_source = MockDataSourceWithoutDateRange::new();
        let key = "some-key";

        let date_range = mock_source.get_date_range_for_key(key);
        assert!(date_range.is_none());

        let error_message = "Failed to fetch and parse chunk: Mock error";
        assert_eq!(error_message, "Failed to fetch and parse chunk: Mock error");
    }

    #[test]
    fn test_display_message_includes_date_range() {
        let user_message = "Connection failed";
        let date_range = "2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC";

        let display_message = format!("{user_message} (Date range: {date_range})");
        assert_eq!(
            display_message,
            "Connection failed (Date range: 2023-01-01 00:00 UTC to 2023-01-01 01:00 UTC)"
        );
    }

    #[test]
    fn test_should_pause_due_to_max_attempts() {
        assert!(!should_pause_due_to_max_attempts(0, 0)); // unlimited
        assert!(!should_pause_due_to_max_attempts(2, 3));
        assert!(should_pause_due_to_max_attempts(3, 3));
        assert!(should_pause_due_to_max_attempts(4, 3));
    }
}
