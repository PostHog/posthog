use std::sync::Arc;

use anyhow::{Context, Error};
use uuid::Uuid;

use crate::metrics as metric_emit;
use common_types::InternallyCapturedEvent;
use lifecycle::Handle;
use model::{JobModel, JobState, PartState};
use tokio::sync::Mutex;
use tracing::{debug, error, info, warn};

use crate::{
    context::AppContext,
    emit::Emitter,
    error::{
        extract_retry_after_from_error, get_user_message, is_rate_limited_error, is_timeout_error,
        is_transient_network_error, is_transient_object_store_error, is_transient_server_error,
        UserError,
    },
    extractor::detect_compression_magic,
    job::{backoff::format_backoff_messages, config::SinkConfig},
    parse::{format::ParserFn, Parsed},
    source::DataSource,
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
        let (status_msg, display_msg) =
            format_backoff_messages(current_date_range, delay, "Rate limited (429)");
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else if is_timeout_error(err) {
        let delay = policy.next_delay(current_attempt);
        let (status_msg, display_msg) =
            format_backoff_messages(current_date_range, delay, "Request timed out");
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else if is_transient_network_error(err) {
        let delay = policy.next_delay(current_attempt);
        let (status_msg, display_msg) =
            format_backoff_messages(current_date_range, delay, "Transient network error");
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else if is_transient_server_error(err) {
        let delay = policy.next_delay(current_attempt);
        let (status_msg, display_msg) =
            format_backoff_messages(current_date_range, delay, "Upstream server error (5xx)");
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else if is_transient_object_store_error(err) {
        // Temp-bucket staging I/O that outlived the S3 client's internal retries
        // (throttling, 5xx, timeouts, transport). Backoff and retry rather than
        // pausing a customer job over infrastructure weather.
        let delay = policy.next_delay(current_attempt);
        let (status_msg, display_msg) =
            format_backoff_messages(current_date_range, delay, "Temporary storage error");
        ErrorHandlingDecision::Backoff {
            delay,
            status_msg,
            display_msg,
        }
    } else {
        // Use the full error chain for developer-facing message
        let error_msg = match current_date_range {
            Some(dr) => format!("{err:#} (Date range: {dr})"),
            None => format!("{err:#}"),
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

/// Mirror a part's discovered total size into the model state, which is what
/// gets persisted to the DB on the next part commit.
async fn mirror_part_total(model: &Mutex<JobModel>, key: &str, total: u64) {
    let mut model = model.lock().await;
    if let Some(model_state) = &mut model.state {
        if let Some(model_part) = model_state.parts.iter_mut().find(|p| p.key == key) {
            model_part.total_size = Some(total);
        }
    }
}

/// DB-free core of [`Job::get_next_chunk`]: pick the next unfinished part, lazily
/// discover its (decompressed) size, fetch+parse one chunk, and advance the
/// in-memory part offset. A newly discovered `total_size` is mirrored into the
/// model in memory only — no DB write happens here, which keeps the fetch/select
/// loop testable without a database. Per-part staging cleanup is not driven from
/// here: the source frees each `.raw` on its own EOF read (see
/// [`crate::source::read_prepared_chunk`]).
///
/// Returns the fetched `(key, parsed, reset_backoff)`. `reset_backoff` is `false`
/// only on the empty-key short-circuit (so the caller skips the success backoff
/// reset, matching the original control flow) and `true` otherwise. `None` means
/// every part is done.
pub async fn select_and_fetch_next_chunk(
    state: &Mutex<JobState>,
    model: &Mutex<JobModel>,
    source: &dyn DataSource,
    transform: &Arc<ParserFn>,
    chunk_size: usize,
    job_id: Uuid,
) -> Result<Option<(String, Parsed<Vec<InternallyCapturedEvent>>, bool)>, Error> {
    let mut state = state.lock().await;

    let Some(next_part) = state.parts.iter_mut().find(|p| !p.is_done()) else {
        info!(job_id = %job_id, "Found no next part, returning");
        return Ok(None); // We're done fetching
    };

    let key = next_part.key.clone();
    source.prepare_key(&key).await?;

    if next_part.total_size.is_none() {
        if let Some(actual_size) = source.size(&key).await? {
            next_part.total_size = Some(actual_size);
            info!(job_id = %job_id, "Updated total size for key {}: {}", key, actual_size);
            mirror_part_total(model, &key, actual_size).await;

            // Streaming sources only learn their size on the read that observes
            // end-of-stream, which is usually also the read that consumed the last
            // bytes - so by the time the size is known here, the offset may already
            // be at (or past) the end. Re-check completion now: fetching again would
            // return an empty chunk, and advancing on one would push the offset past
            // the total, making the part permanently un-finishable.
            if next_part.is_done() {
                info!(
                    job_id = %job_id,
                    "Part {} (size {}) was fully consumed when its size was discovered, moving on",
                    key, actual_size
                );
                return Ok(Some((
                    key,
                    Parsed {
                        consumed: 0,
                        data: vec![],
                    },
                    false,
                )));
            }
        }
    }

    info!(job_id = %job_id, "Fetching part chunk {:?}", next_part);

    let next_chunk = source
        .get_chunk(&next_part.key, next_part.current_offset, chunk_size as u64)
        .await
        .context(format!("Fetching part chunk {next_part:?}"))?;

    // `>=` because sources clamp reads to the end of the part, so the final chunk
    // ends exactly at total_size - a strict `>` can never be true and would leave
    // the unconsumed-bytes check below unreachable.
    let is_last_chunk = match next_part.total_size {
        Some(total_size) => next_part.current_offset + next_chunk.len() as u64 >= total_size,
        None => false,
    };

    let chunk_bytes = next_chunk.len();

    // An empty chunk before the part looks finished means the source hit
    // end-of-stream at or before this offset. For streaming sources the size is
    // only discoverable on the read that observes EOF - which for an empty part
    // (a day with no events: an empty 200 body, a gzip of nothing, a zip with no
    // data members) or a resume at a not-yet-persisted EOF is this very read. So
    // re-consult the size now: if the source's own view confirms everything was
    // consumed, the part is complete. Anything else (a ranged source serving
    // empty bodies mid-part, a stream that shrank below the recorded total) can
    // never make progress, so fail rather than loop.
    if chunk_bytes == 0 && !is_last_chunk {
        let refreshed_size = source.size(&key).await?;
        let confirmed_complete = refreshed_size.is_some_and(|actual| {
            let total_consistent = next_part.total_size.is_none_or(|t| t == actual);
            total_consistent && next_part.current_offset >= actual
        });

        if !confirmed_complete {
            return Err(Error::msg(format!(
                "Source returned no data for part {} at offset {} before the end of the part",
                next_part.key, next_part.current_offset
            )));
        }

        let actual_size = refreshed_size.expect("confirmed_complete implies the size is known");
        if next_part.current_offset > actual_size {
            // A resumed offset past the stream's end: the export shrank between
            // downloads. Everything the source can serve was already consumed,
            // so completing is the only non-stranding option - but it deserves
            // a loud trace, since the tail of the previous download's data may
            // not exist in this download at all.
            warn!(
                job_id = %job_id,
                "Part {} resumed at offset {} past the stream end {}; marking complete",
                key, next_part.current_offset, actual_size
            );
        }
        next_part.total_size = Some(actual_size);
        mirror_part_total(model, &key, actual_size).await;
        info!(
            job_id = %job_id,
            "Part {} (size {}) has no data left to read at offset {}, marking complete",
            key, actual_size, next_part.current_offset
        );
        return Ok(Some((
            key,
            Parsed {
                consumed: 0,
                data: vec![],
            },
            false,
        )));
    }

    // A part that still *begins* with a known compression magic can never be
    // parsed as newline-delimited JSON: the file is compressed a second time, or
    // the source/extractor's compression setting does not match the file. Only the
    // start of a part is decisive - mid-file chunks can coincidentally begin with
    // these bytes - so this is gated on offset 0. Fail fast with an actionable,
    // non-transient error (a UserError pauses the job) instead of letting the
    // parser emit a confusing "invalid utf-8" failure or crawl one byte at a time.
    if next_part.current_offset == 0 {
        if let Some(fmt) = detect_compression_magic(&next_chunk) {
            let internal = Error::msg(format!(
                "part {} begins with {fmt} magic bytes at offset 0 ({chunk_bytes} bytes read)",
                next_part.key
            ));
            return Err(internal.context(UserError::new(format!(
                "Part {} begins with {fmt}-compressed data where newline-delimited JSON was \
                 expected - the file may be compressed twice, or the import's compression \
                 setting doesn't match the file.",
                next_part.key
            ))));
        }
    }

    info!(job_id = %job_id, "Fetched part chunk {:?}", next_part);
    let m_tf = transform.clone();
    let key_for_error = key.clone();
    // This is computationally expensive, so we run it in a blocking task
    let parsed = tokio::task::spawn_blocking(move || (m_tf)(next_chunk))
        .await?
        .map_err(|e| {
            let inner_msg = get_user_message(&e);
            e.context(UserError::new(format!(
                "Parsing data in file '{key_for_error}' failed: {inner_msg}"
            )))
        })
        .context(format!("Processing part chunk {next_part:?}"))?;

    info!(
        job_id = %job_id,
        "Parsed part chunk {:?}, consumed {} bytes",
        next_part, parsed.consumed
    );

    // Consuming more bytes than were read is always a parser bug: advancing the
    // offset past real data would silently skip it, or overshoot the end of the
    // part and make it permanently un-finishable.
    if parsed.consumed > chunk_bytes {
        return Err(Error::msg(format!(
            "Parser consumed {} bytes but only {} were read from part {} at offset {}",
            parsed.consumed, chunk_bytes, next_part.key, next_part.current_offset
        )));
    }

    // If this is the last chunk and we didn't consume all of it, we have leftover unparseable data.
    if parsed.consumed < chunk_bytes && is_last_chunk {
        return Err(Error::msg(format!(
            "Failed to parse data from part {} at offset {} - {} bytes left unconsumed",
            next_part.key,
            next_part.current_offset,
            chunk_bytes - parsed.consumed
        )));
    }

    // A single record larger than the read window fills a whole non-final chunk with no
    // line terminator, so the parser can't advance past it. Without this the loop would
    // crawl one byte per iteration (and, on the temp-bucket backend, issue a ranged GET
    // of up to chunk_size per byte). Fail fast with an actionable, non-transient error
    // that pauses the job.
    if !is_last_chunk && chunk_bytes == chunk_size && parsed.consumed <= 1 && parsed.data.is_empty()
    {
        // Public message stays free of internal tuning values (chunk_size); the root
        // error carries them for status_message and logs.
        return Err(Error::msg(format!(
            "single record exceeds chunk_size={chunk_size} in part {} at offset {}",
            next_part.key, next_part.current_offset
        ))
        .context(UserError::new(format!(
            "A single record in part {} is too large to process. Split the oversized \
             record into smaller records and re-run this date range or file.",
            next_part.key
        ))));
    }

    // If we consumed no bytes and have no parsed data but there was data to consume, something went wrong.
    // Note: don't error if we have no parsed data but have consumed bytes - invalid events may have been all filtered out
    if parsed.consumed == 0 && parsed.data.is_empty() && chunk_bytes > 0 {
        return Err(Error::msg(format!(
            "Failed to parse any data from part {} at offset {}",
            next_part.key, next_part.current_offset
        )));
    }

    // Update the in-memory part state (the read will be committed to the DB once the write is done)
    next_part.current_offset += parsed.consumed as u64;

    Ok(Some((key, parsed, true)))
}

/// Free a committed part's staging once it is fully consumed, best-effort.
///
/// Called from `do_commit` after `complete_commit` persists the advanced offsets. Checks
/// the *persisted* model view (not the in-memory fetch state, which runs one iteration
/// ahead) so staging is only freed for parts whose completion is durable. Failures are
/// logged and counted, never propagated: a missed delete leaks only transient storage,
/// reclaimed by `cleanup_after_job` and (for the temp bucket) the bucket TTL.
pub(crate) async fn cleanup_committed_part_if_done(
    source: &dyn DataSource,
    model: &Mutex<JobModel>,
    key: &str,
) {
    let part_done = {
        let model = model.lock().await;
        model
            .state
            .as_ref()
            .and_then(|state| state.parts.iter().find(|p| p.key == key))
            .is_some_and(|part| part.is_done())
    };
    if !part_done {
        return;
    }
    match source.cleanup_key(key).await {
        Ok(()) => crate::metrics::part_cleanup("ok"),
        Err(e) => {
            warn!("Failed to clean up staging for committed part {key}: {e:#}");
            crate::metrics::part_cleanup("error");
        }
    }
}

pub struct Job {
    pub context: Arc<AppContext>,
    handle: Handle,

    // Once created the job id doesn't change, store it on the Job struct for easy access, to avoid contention/locking on the model
    pub job_id: Uuid,

    // How many bytes to fetch from the source per iteration. Varies by sink
    // type: the capture sink uses a smaller value to stay within the capture
    // service's HTTP body size limit.
    pub chunk_size: usize,

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
    pub async fn new(
        mut model: JobModel,
        context: Arc<AppContext>,
        handle: Handle,
    ) -> Result<Self, Error> {
        let is_restarting = model.state.is_some();

        let source = model
            .import_config
            .source
            .construct(&model.secrets, context.clone(), is_restarting, model.id)
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
            info!(job_id = %model.id, "Found job with no parts, initializing parts list");
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
            info!(job_id = %model.id, "Initialized parts list: {:?}", state.parts);
        }

        let job_id = model.id;
        let chunk_size = match &model.import_config.sink {
            SinkConfig::Capture(_) => context.config.capture_chunk_size,
            _ => context.config.chunk_size,
        };

        Ok(Self {
            context,
            handle,
            job_id,
            chunk_size,
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
            // but this pod should restart, in case it's sink is in some bad state.
            // The failure is sink-side and the offset was rolled back, so keep the
            // staged remote data: the resume re-reads the byte-identical chunk
            // instead of re-downloading from an origin that may have changed.
            error!("Failed to commit chunk: {:?}", e);
            if let Err(cleanup_err) = self.source.release_job_resources().await {
                warn!("Failed to cleanup after commit failure: {:?}", cleanup_err);
            }
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
                // Cleanup is deferred until after classification below: transient
                // interruptions keep remote staging for the resume to attach to,
                // while source-side pauses sweep it for a clean re-download.
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
                    &user_facing_error_message,
                ) {
                    ErrorHandlingDecision::Backoff {
                        delay,
                        status_msg,
                        display_msg,
                    } => {
                        // Transient (or transient-persisted, below): keep staged
                        // remote parts so the resume attaches without re-hitting an
                        // origin that is likely still rate-limited or flaky.
                        if let Err(cleanup_err) = self.source.release_job_resources().await {
                            warn!("Failed to release job resources: {:?}", cleanup_err);
                        }
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
                                        "Transient error persisted. Job paused after maximum retries."
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
                            "transient error, scheduling retry: {:#}",
                            e
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
                        // Source-side pause: a human intervenes and may fix the
                        // source data in place, so the resume must re-download a
                        // clean copy, never attach to a stale staged one. Staged
                        // sources quarantine (rather than delete) the staged bytes,
                        // since they are the exact stream the failing offset points
                        // into — the evidence for debugging the parse failure.
                        if let Err(cleanup_err) = self.source.cleanup_after_data_error().await {
                            warn!("Failed to cleanup after data error: {:?}", cleanup_err);
                        }
                        let mut model = self.model.lock().await;
                        error!(
                            job_id = %model.id,
                            user_msg = %error_msg,
                            "Pausing job due to error: {:#}",
                            e
                        );
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
        let Some((key, parsed, reset_backoff)) = select_and_fetch_next_chunk(
            &self.state,
            &self.model,
            self.source.as_ref(),
            &self.transform,
            self.chunk_size,
            self.job_id,
        )
        .await?
        else {
            return Ok(None); // We're done fetching
        };

        // The only DB write in this path, kept out of the core above so the
        // fetch/select/cleanup loop stays testable without a database. Skipped on
        // the empty-key short-circuit, matching the original control flow.
        if reset_backoff {
            let mut model = self.model.lock().await;
            reset_backoff_after_success(self.context.clone(), &mut model).await?;
        }

        Ok(Some((key, parsed)))
    }

    async fn do_commit(&self) -> Result<(), Error> {
        self.shutdown_guard()?;
        let mut checkpoint_lock = self.checkpoint.lock().await;

        let Some(checkpoint) = checkpoint_lock.take() else {
            info!(job_id = %self.job_id, "No checkpointed data to commit, returning");
            return Ok(());
        };

        let (key, parsed) = (checkpoint.key, checkpoint.data);

        info!(job_id = %self.job_id, "Committing part {} consumed {} bytes", key, parsed.consumed);
        info!(job_id = %self.job_id, "Committing {} events", parsed.data.len());

        let mut sink = self.sink.lock().await;
        self.shutdown_guard()?;
        let txn = sink.begin_write().await?;
        info!(job_id = %self.job_id, "Writing {} events", parsed.data.len());
        self.shutdown_guard()?;
        txn.emit(&parsed.data).await?;
        // Two-stage commit: advance the offset and pause the job in PG *before* committing to
        // the sink. If we crash between the two, the job is left paused at the advanced offset
        // and requires manual intervention rather than silently skipping a chunk — the operator
        // confirms whether the sink commit landed via the last event written or the logs.
        self.shutdown_guard()?;
        info!(job_id = %self.job_id, "Beginning PG part commit");
        self.begin_part_commit(&key, parsed.consumed).await?;
        info!(job_id = %self.job_id, "Beginning emitter part commit");

        // A *returned* error (as opposed to a crash) means the sink definitively rejected the
        // chunk, so the speculative offset advance above is wrong: roll it back and record the
        // real error, so a resume re-processes the chunk instead of skipping it.
        let to_sleep = match txn.commit_write().await {
            Ok(to_sleep) => to_sleep,
            Err(e) => {
                self.rollback_part_commit(&key, parsed.consumed, &e).await?;
                return Err(e);
            }
        };
        info!(job_id = %self.job_id, "Finishing PG part commit");
        self.complete_commit().await?;
        info!(job_id = %self.job_id, "Committed part {} consumed {} bytes", key, parsed.consumed);

        // The committed part may now be fully consumed: free its staging eagerly and only
        // after its offsets are durable. Safe against concurrent reads: the in-memory state
        // marked this part done no later than the iteration before this commit (offsets
        // advance at fetch time, and the completion short-circuits - size-discovery and
        // empty-chunk - mark a part done in the same iteration that produces their
        // synthetic zero-consumed checkpoint), so the read loop can never re-select it.
        // Those synthetic checkpoints can make the hook fire a second time for a part
        // whose data commit already cleaned up; cleanup_key is idempotent, so the double
        // call is a tolerated no-op rather than a correctness issue. A rollback or a crash
        // between the two commit stages returns/aborts before reaching this point,
        // preserving the staged data for the byte-identical re-read on resume.
        cleanup_committed_part_if_done(self.source.as_ref(), &self.model, &key).await;

        info!(job_id = %self.job_id, "Sleeping for {:?}", to_sleep);
        tokio::select! {
            _ = tokio::time::sleep(to_sleep) => {},
            _ = self.handle.shutdown_recv() => {},
        }

        Ok(())
    }

    async fn successfully_complete(self) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        let result = model.complete(&self.context.db).await;
        if result.is_ok() {
            info!(job_id = %self.job_id, "Batch import job complete");
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

        let Some(new_offset) = model_state.advance_part_offset(key, consumed as u64) else {
            return Err(Error::msg(format!("No part found with key {key}")));
        };

        let status_message = format!(
            "Starting commit of part {key} to offset {new_offset}, consumed {consumed} additional bytes"
        );

        model
            .pause(
                self.context.clone(),
                status_message,
                Some("Job paused while committing events".to_string()),
            )
            .await
    }

    // Reverts the speculative offset advance from begin_part_commit after a definitive sink
    // rejection, leaving the job paused with the real error and the original offset, so a resume
    // re-processes the chunk rather than skipping it.
    async fn rollback_part_commit(
        &self,
        key: &str,
        consumed: usize,
        err: &Error,
    ) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        let Some(model_state) = &mut model.state else {
            return Err(Error::msg("No model state found"));
        };

        let Some(new_offset) = model_state.revert_part_offset(key, consumed as u64) else {
            return Err(Error::msg(format!("No part found with key {key}")));
        };

        let status_message =
            format!("Commit of part {key} failed, rolled back to offset {new_offset}: {err:#}");

        model
            .pause(
                self.context.clone(),
                status_message,
                Some("Job paused after a failed commit. Resolve the error and resume.".to_string()),
            )
            .await
    }

    // Unpauses the job
    async fn complete_commit(&self) -> Result<(), Error> {
        let mut model = self.model.lock().await;
        model.unpause(self.context.clone()).await
    }

    fn shutdown_guard(&self) -> Result<(), Error> {
        if self.handle.is_shutting_down() {
            warn!("Shutdown signaled during job processing, bailing");
            Err(Error::msg("Shutdown signaled during job processing"))
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
                assert!(error_msg.contains("500 Internal Server Error"));
                assert_eq!(display_msg, "Remote server error");
            }
            _ => panic!("expected pause"),
        }
    }

    /// Build the real object_store error a temp-bucket read/stage produces for the
    /// given S3 response status (client-level retries disabled for speed).
    async fn object_store_error_with_status(status: u16) -> Error {
        use object_store::ObjectStoreExt;
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.any_request();
            then.status(status);
        });
        let store = object_store::aws::AmazonS3Builder::new()
            .with_bucket_name("b")
            .with_endpoint(server.base_url())
            .with_region("us-east-1")
            .with_allow_http(true)
            .with_virtual_hosted_style_request(false)
            .with_access_key_id("k")
            .with_secret_access_key("s")
            .with_retry(object_store::RetryConfig {
                max_retries: 0,
                retry_timeout: std::time::Duration::from_secs(5),
                ..Default::default()
            })
            .build()
            .unwrap();
        let err = store
            .get(&object_store::path::Path::from("k.data"))
            .await
            .unwrap_err();
        Error::from(err).context("Failed to read staged object for key: k")
    }

    fn policy_for_test() -> crate::job::backoff::BackoffPolicy {
        crate::job::backoff::BackoffPolicy::new(
            std::time::Duration::from_secs(60),
            2.0,
            std::time::Duration::from_secs(3600),
        )
    }

    #[tokio::test]
    async fn test_decide_on_error_backoff_for_transient_storage_error() {
        // A temp-bucket 503 that outlived the S3 client's internal retries must
        // reach job backoff, not pause a customer job over infrastructure weather.
        let err = object_store_error_with_status(503).await;
        let decision = decide_on_error(&err, None, policy_for_test(), 0, "unused");
        match decision {
            ErrorHandlingDecision::Backoff { status_msg, .. } => {
                assert!(
                    status_msg.contains("Temporary storage error"),
                    "unexpected status: {status_msg}"
                );
            }
            other => panic!("expected backoff for storage 503, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn test_decide_on_error_pause_for_permanent_storage_error() {
        // 403 (IAM misconfig) must pause visibly: with unlimited backoff attempts,
        // classifying it transient would retry it invisibly forever.
        let err = object_store_error_with_status(403).await;
        let decision = decide_on_error(&err, None, policy_for_test(), 0, "Storage error");
        assert!(
            matches!(decision, ErrorHandlingDecision::Pause { .. }),
            "expected pause for storage 403, got {decision:?}"
        );
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

    #[tokio::test]
    async fn test_decide_on_error_backoff_for_timeout() {
        // Create a TCP listener that accepts but never responds, triggering a client timeout
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();

        let client = Client::builder()
            .timeout(std::time::Duration::from_millis(50))
            .build()
            .unwrap();

        let err = client
            .get(format!("http://{addr}/export"))
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);

        let decision = decide_on_error(
            &err,
            Some("2026-01-01 10:00 UTC to 2026-01-01 11:00 UTC"),
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "Request timed out",
        );

        match decision {
            ErrorHandlingDecision::Backoff {
                delay,
                status_msg,
                display_msg,
            } => {
                assert_eq!(delay.as_secs(), 60);
                assert!(
                    status_msg.contains("Request timed out"),
                    "status_msg should mention timeout: {status_msg}"
                );
                assert!(
                    display_msg.contains("Date range"),
                    "display_msg should include date range: {display_msg}"
                );
                assert!(
                    display_msg.contains("Request timed out"),
                    "display_msg should mention timeout: {display_msg}"
                );
            }
            _ => panic!("expected backoff for timeout error"),
        }
    }

    #[tokio::test]
    async fn test_decide_on_error_backoff_for_transient_network_error() {
        // Bind then drop to close the port — connecting will be refused.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        drop(listener);

        let client = Client::new();
        let err = client
            .get(format!("http://{addr}/export"))
            .send()
            .await
            .unwrap_err();
        let err = anyhow::Error::from(err);

        let decision = decide_on_error(
            &err,
            Some("2026-01-01 10:00 UTC to 2026-01-01 11:00 UTC"),
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "Transient network error",
        );

        match decision {
            ErrorHandlingDecision::Backoff {
                delay,
                status_msg,
                display_msg,
            } => {
                assert_eq!(delay.as_secs(), 60);
                assert!(
                    status_msg.contains("Transient network error"),
                    "status_msg should mention transient network error: {status_msg}"
                );
                assert!(
                    display_msg.contains("Date range"),
                    "display_msg should include date range: {display_msg}"
                );
                assert!(
                    display_msg.contains("Transient network error"),
                    "display_msg should mention transient network error: {display_msg}"
                );
            }
            _ => panic!("expected backoff for transient network error"),
        }
    }

    #[tokio::test]
    async fn test_decide_on_error_backoff_for_502() {
        let server = httpmock::MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/e");
            then.status(502);
        });
        let client = Client::new();
        let resp = client.get(server.url("/e")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);

        let decision = decide_on_error(
            &err,
            Some("2026-01-01 10:00 UTC to 2026-01-01 11:00 UTC"),
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "Upstream server error (5xx)",
        );

        match decision {
            ErrorHandlingDecision::Backoff {
                delay,
                status_msg,
                display_msg,
            } => {
                assert_eq!(delay.as_secs(), 60);
                assert!(
                    status_msg.contains("Upstream server error"),
                    "status_msg should mention upstream server error: {status_msg}"
                );
                assert!(
                    display_msg.contains("Date range"),
                    "display_msg should include date range: {display_msg}"
                );
            }
            _ => panic!("expected backoff for 502"),
        }
    }

    #[test]
    fn test_should_pause_due_to_max_attempts() {
        assert!(!should_pause_due_to_max_attempts(0, 0)); // unlimited
        assert!(!should_pause_due_to_max_attempts(2, 3));
        assert!(should_pause_due_to_max_attempts(3, 3));
        assert!(should_pause_due_to_max_attempts(4, 3));
    }

    #[test]
    fn test_decide_on_error_separates_developer_and_user_messages() {
        let root_error =
            std::io::Error::new(std::io::ErrorKind::InvalidData, "invalid byte sequence");
        let error = anyhow::Error::from(root_error)
            .context("Failed to parse JSON")
            .context("Processing chunk");

        let decision = decide_on_error(
            &error,
            Some("2023-01-01 to 2023-01-02"),
            crate::job::backoff::BackoffPolicy::new(
                std::time::Duration::from_secs(60),
                2.0,
                std::time::Duration::from_secs(3600),
            ),
            0,
            "User-friendly error message",
        );

        match decision {
            ErrorHandlingDecision::Pause {
                error_msg,
                display_msg,
            } => {
                assert!(
                    error_msg.contains("Processing chunk"),
                    "Developer message should contain outer context: {error_msg}"
                );
                assert!(
                    error_msg.contains("Failed to parse JSON"),
                    "Developer message should contain inner context: {error_msg}"
                );
                assert!(
                    error_msg.contains("invalid byte sequence"),
                    "Developer message should contain root cause: {error_msg}"
                );

                assert_eq!(
                    display_msg,
                    "User-friendly error message (Date range: 2023-01-01 to 2023-01-02)"
                );
            }
            _ => panic!("Expected Pause decision"),
        }
    }

    mod shutdown_guard_tests {
        use tokio_util::sync::CancellationToken;

        fn make_handle(token: CancellationToken) -> lifecycle::Handle {
            let mut manager = lifecycle::Manager::builder("test")
                .with_trap_signals(false)
                .with_prestop_check(false)
                .with_shutdown_token(token)
                .build();
            manager.register("test-component", lifecycle::ComponentOptions::new())
        }

        /// shutdown_guard delegates to handle.is_shutting_down(); verify the
        /// underlying predicate returns false before cancellation.
        #[test]
        fn handle_not_shutting_down_before_cancel() {
            let token = CancellationToken::new();
            let handle = make_handle(token);
            assert!(!handle.is_shutting_down());
        }

        /// After the token is cancelled, is_shutting_down() returns true --
        /// which is what shutdown_guard uses to bail out of commit phases.
        #[test]
        fn handle_shutting_down_after_cancel() {
            let token = CancellationToken::new();
            let handle = make_handle(token.clone());
            token.cancel();
            assert!(handle.is_shutting_down());
        }
    }

    /// Drives the real DB-free read loop (`select_and_fetch_next_chunk`) against
    /// the real `DateRangeExportSource` + `PlainGzipExtractor` over `httpmock`, to
    /// lock the end-to-end staging-cleanup invariant: across a whole run the loop
    /// alone (without `cleanup_after_job`) leaves no `.raw` behind and never keeps
    /// more than one part's `.raw` on disk at a time. The source frees each `.raw`
    /// on its own EOF read (see [`crate::source::read_prepared_chunk`]); the
    /// decisive read-level proof of that lives in `date_range_export`'s tests.
    mod staging_cleanup_invariant_tests {
        use super::*;
        use crate::extractor::ExtractorType;
        use crate::source::date_range_export::{AuthConfig, DateRangeExportSource};
        use chrono::{TimeZone, Utc};
        use flate2::write::GzEncoder;
        use flate2::Compression;
        use std::io::Write;
        use std::path::{Path, PathBuf};
        use tempfile::TempDir;

        pub(super) fn gzip_bytes(data: &[u8]) -> Vec<u8> {
            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(data).unwrap();
            encoder.finish().unwrap()
        }

        /// Build a source spanning `hours` one-hour intervals (one key per hour),
        /// all served the same body by the mock, decoded with `extractor`.
        /// `remote` selects temp-bucket staging; `None` is the local streaming path.
        pub(super) fn build_source_with(
            base_url: String,
            staging: &Path,
            hours: u32,
            extractor: ExtractorType,
            remote: Option<crate::source::RemoteStaging>,
        ) -> DateRangeExportSource {
            let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
            let end = Utc.with_ymd_and_hms(2023, 1, 1, hours, 0, 0).unwrap();
            DateRangeExportSource::builder(
                base_url,
                start,
                end,
                3600,
                extractor.create_extractor(),
                staging.to_path_buf(),
            )
            .with_auth(AuthConfig::None)
            .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
            .with_headers(HashMap::new())
            .with_remote_staging(remote)
            .build()
            .unwrap()
        }

        pub(super) fn build_source_with_extractor(
            base_url: String,
            staging: &Path,
            hours: u32,
            extractor: ExtractorType,
        ) -> DateRangeExportSource {
            build_source_with(base_url, staging, hours, extractor, None)
        }

        fn build_source(base_url: String, staging: &Path, hours: u32) -> DateRangeExportSource {
            build_source_with(base_url, staging, hours, ExtractorType::PlainGzip, None)
        }

        /// A transform that consumes the whole chunk and emits no events. The
        /// cleanup invariant is about offsets reaching `total` and each `.raw`
        /// being freed on its EOF read — parsing semantics are irrelevant here, so
        /// this keeps the loop advancing deterministically by exactly the bytes read.
        fn consume_all_transform() -> Arc<ParserFn> {
            Arc::new(Box::new(|bytes: Vec<u8>| {
                Ok(Parsed {
                    consumed: bytes.len(),
                    data: Vec::new(),
                })
            }))
        }

        /// A transform that runs the real newline parser to compute `consumed`
        /// (validating each complete line as JSON) but emits no events. This
        /// reproduces the parser's real boundary behavior — a chunk with no line
        /// terminator yields `consumed == 1` — which is what the oversized-record
        /// guard keys on, without standing up the full captured-event pipeline.
        pub(super) fn newline_consumed_transform() -> Arc<ParserFn> {
            Arc::new(Box::new(|bytes: Vec<u8>| {
                let parser = crate::parse::format::newline_delim(true, |line: &str| {
                    serde_json::from_str::<serde_json::Value>(line)
                        .map(|_| ())
                        .map_err(anyhow::Error::from)
                });
                let parsed = parser(bytes)?;
                Ok(Parsed {
                    consumed: parsed.consumed,
                    data: Vec::new(),
                })
            }))
        }

        fn count_raw_files(dir: &Path) -> usize {
            let mut count = 0;
            let mut stack = vec![dir.to_path_buf()];
            while let Some(d) = stack.pop() {
                let Ok(entries) = std::fs::read_dir(&d) else {
                    continue;
                };
                for entry in entries.flatten() {
                    let path: PathBuf = entry.path();
                    if path.is_dir() {
                        stack.push(path);
                    } else if path.extension().and_then(|e| e.to_str()) == Some("raw") {
                        count += 1;
                    }
                }
            }
            count
        }

        /// Drive `select_and_fetch_next_chunk` until it reports all parts done,
        /// up to `max_iterations`. Returns whether it completed within budget.
        pub(super) async fn drive_loop_to_completion(
            state: &Mutex<JobState>,
            model: &Mutex<JobModel>,
            source: &dyn DataSource,
            transform: &Arc<ParserFn>,
            chunk_size: usize,
            max_iterations: usize,
        ) -> Result<bool, Error> {
            for _ in 0..max_iterations {
                let next = select_and_fetch_next_chunk(
                    state,
                    model,
                    source,
                    transform,
                    chunk_size,
                    Uuid::now_v7(),
                )
                .await?;
                if next.is_none() {
                    return Ok(true);
                }
            }
            Ok(false)
        }

        pub(super) fn dummy_model(state: JobState) -> JobModel {
            JobModel {
                id: Uuid::now_v7(),
                team_id: 1,
                created_at: Utc::now(),
                updated_at: Utc::now(),
                lease_id: None,
                leased_until: None,
                status: model::JobStatus::Running,
                status_message: None,
                display_status_message: None,
                state: Some(state),
                import_config: config::JobConfig {
                    source: config::SourceConfig::Folder(config::FolderSourceConfig {
                        path: "/tmp".to_string(),
                    }),
                    data_format: crate::parse::format::FormatConfig::JsonLines {
                        skip_blanks: true,
                        content: crate::parse::content::ContentType::Captured,
                    },
                    sink: config::SinkConfig::NoOp,
                    import_events: true,
                    generate_identify_events: false,
                    generate_group_identify_events: false,
                },
                secrets: config::JobSecrets {
                    secrets: HashMap::new(),
                },
                backoff_attempt: 0,
                backoff_until: None,
                was_leased: false,
            }
        }

        pub(super) fn job_state(keys: &[String]) -> JobState {
            JobState {
                parts: keys
                    .iter()
                    .map(|key| PartState {
                        key: key.clone(),
                        current_offset: 0,
                        total_size: None,
                    })
                    .collect(),
            }
        }

        #[tokio::test]
        async fn test_single_part_raw_cleaned_up_by_read_loop_without_job_cleanup() {
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..2000 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let source = build_source(server.url("/export"), staging.path(), 1);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 1);

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = consume_all_transform();

            // Small chunk so the loop takes several passes before EOF.
            let mut peak_raw = 0;
            loop {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    1024,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                peak_raw = peak_raw.max(count_raw_files(staging.path()));
                if next.is_none() {
                    break;
                }
            }

            // The loop alone (no cleanup_after_job) must have deleted the .raw:
            // the source frees it on the EOF read.
            assert_eq!(
                count_raw_files(staging.path()),
                0,
                "the read loop must delete the part's .raw once it is fully read, without cleanup_after_job"
            );
            assert_eq!(
                peak_raw, 1,
                "exactly one .raw should exist while the part is in flight"
            );
        }

        #[tokio::test]
        async fn test_part_fully_consumed_at_eof_read_completes_without_offset_overshoot() {
            // Streaming sources only learn a part's total size on the read that
            // observes EOF. When that same read fully consumes the remaining bytes,
            // the offset lands exactly at the total while the job still has
            // total_size = None. The next loop iteration must then recognize the
            // part as done — not fetch an empty chunk, "consume" a phantom byte,
            // and push the offset past the total (which makes is_done() unreachable
            // and the job crawl one byte per iteration forever).
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let total_size = body.len() as u64;
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let source = build_source(server.url("/export"), staging.path(), 1);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 1);

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            // Real newline parser so `consumed` behaves exactly as in production.
            let transform = newline_consumed_transform();

            // Generous iteration budget: a healthy run needs ~(total/chunk + 2)
            // iterations. Far more than that means the loop is stuck.
            let chunk_size = 1024usize;
            let max_iterations = (total_size as usize / chunk_size) + 10;
            let mut completed = false;
            for _ in 0..max_iterations {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    chunk_size,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();

                let offset = state.lock().await.parts[0].current_offset;
                assert!(
                    offset <= total_size,
                    "part offset {offset} overshot total size {total_size}: the job would crawl forever"
                );

                if next.is_none() {
                    completed = true;
                    break;
                }
            }

            assert!(
                completed,
                "job did not finish the part within {max_iterations} iterations (offset {} / total {total_size})",
                state.lock().await.parts[0].current_offset
            );
        }

        #[tokio::test]
        async fn test_part_with_trailing_blank_lines_completes() {
            // Data whose final bytes are blank lines must still complete: the blanks
            // are only seen on the EOF read, after which the streaming source has
            // freed the part and can never serve those bytes again.
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            body.push('\n');
            let total_size = body.len() as u64;
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let source = build_source(server.url("/export"), staging.path(), 1);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            let chunk_size = 1024usize;
            let max_iterations = (total_size as usize / chunk_size) + 10;
            let mut completed = false;
            for _ in 0..max_iterations {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    chunk_size,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                if next.is_none() {
                    completed = true;
                    break;
                }
            }

            assert!(completed, "trailing blank lines must not stall the part");
            assert_eq!(state.lock().await.parts[0].current_offset, total_size);
        }

        #[tokio::test]
        async fn test_poisoned_part_with_overshot_offset_self_heals() {
            // A job written by a worker version with the overshoot bug has a part
            // whose stored offset exceeds its total size. On resume that part must
            // be treated as done (its real bytes were all consumed before the
            // phantom crawl began) so the job can move on to the remaining parts.
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let source = build_source(server.url("/export"), staging.path(), 2);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 2);

            // Part 1 poisoned as in production: offset way past its recorded total.
            let poisoned = JobState {
                parts: vec![
                    PartState {
                        key: keys[0].clone(),
                        current_offset: 25_328_072,
                        total_size: Some(24_441_157),
                    },
                    PartState {
                        key: keys[1].clone(),
                        current_offset: 0,
                        total_size: None,
                    },
                ],
            };
            let state = Mutex::new(poisoned.clone());
            let model = Mutex::new(dummy_model(poisoned));
            let transform = newline_consumed_transform();

            let mut completed = false;
            for _ in 0..20 {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    1024,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                if next.is_none() {
                    completed = true;
                    break;
                }
            }

            assert!(
                completed,
                "job with an overshot part must skip it and finish the rest"
            );
            let state = state.lock().await;
            assert_eq!(
                state.parts[0].current_offset, 25_328_072,
                "poisoned part must be skipped untouched, not re-read"
            );
            assert_eq!(
                state.parts[1].total_size,
                Some(state.parts[1].current_offset)
            );
        }

        #[tokio::test]
        async fn test_record_larger_than_chunk_size_fails_fast() {
            // A single JSON record with no interior newline, larger than the read window.
            // Without the guard the loop would crawl one byte per iteration forever.
            let server = MockServer::start();
            let huge_record = format!("{{\"event\":\"{}\"}}", "x".repeat(5000));
            assert!(!huge_record.contains('\n'));
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(huge_record.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let source = build_source(server.url("/export"), staging.path(), 1);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            // Read window (1024) is far smaller than the 5000-byte record.
            let result = select_and_fetch_next_chunk(
                &state,
                &model,
                &source,
                &transform,
                1024,
                Uuid::now_v7(),
            )
            .await;

            let err = result.expect_err("oversized record must fail fast, not crawl");
            // Actionable, user-facing message so the job pauses (not a transient retry),
            // free of internal tuning values; the internal chain keeps chunk_size.
            let user_msg = crate::error::get_user_message(&err);
            assert!(
                user_msg.contains("too large to process"),
                "unexpected message: {user_msg}"
            );
            assert!(
                !user_msg.contains("chunk_size") && !user_msg.contains("1024"),
                "public message must not leak internal tuning values: {user_msg}"
            );
            assert!(
                format!("{err:#}").contains("chunk_size=1024"),
                "internal chain must carry the limit detail: {err:#}"
            );
            assert!(!crate::error::is_rate_limited_error(&err));
            assert!(!crate::error::is_timeout_error(&err));
            assert!(!crate::error::is_transient_network_error(&err));
            assert!(!crate::error::is_transient_server_error(&err));
            assert!(!crate::error::is_transient_object_store_error(&err));
        }

        #[tokio::test]
        async fn test_multi_part_peak_staging_bounded_to_one_part() {
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..2000 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            // Two one-hour intervals -> two keys processed back to back.
            let source = build_source(server.url("/export"), staging.path(), 2);
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 2);

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = consume_all_transform();

            // Two invariants across the whole run:
            //  - peak coexisting .raw files stays at 1 (each part's .raw is freed
            //    on its EOF read, before the next part is read), and
            //  - after the loop, zero .raw remain — cleaned by the loop alone,
            //    including the last part (which has no later prepare-time sweep).
            let mut peak_raw = 0;
            loop {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    1024,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                peak_raw = peak_raw.max(count_raw_files(staging.path()));
                if next.is_none() {
                    break;
                }
            }

            assert_eq!(
                peak_raw, 1,
                "peak staging must be bounded to a single part's .raw; coexisting raws means a completed part was not cleaned up"
            );
            assert_eq!(
                count_raw_files(staging.path()),
                0,
                "all parts' .raw files must be cleaned up by the read loop alone"
            );
        }

        /// The real read loop over a remote-staged (temp-bucket) source: parts stage on
        /// first touch, sizes are known immediately (no lazy-size pass), every part
        /// completes with the parser consuming real newline-delimited records, and no
        /// `.raw` survives staging (deleted right after a successful ingest).
        #[tokio::test]
        async fn test_remote_staged_source_completes_all_parts_through_read_loop() {
            use crate::source::RemoteStaging;
            use crate::staging::TempBucketBackend;
            use object_store::memory::InMemory;

            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..500 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let remote = RemoteStaging {
                backend: Arc::new(TempBucketBackend::new(
                    Arc::new(InMemory::new()),
                    "staging/",
                    "job-LOOP",
                )),
                extractor_type: ExtractorType::PlainGzip,
                max_plaintext_bytes: 0,
            };
            let source = build_source_with(
                server.url("/export"),
                staging.path(),
                2,
                ExtractorType::PlainGzip,
                Some(remote),
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 2);

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            // Real newline parser: proves record reassembly across chunk boundaries
            // works over ranged backend reads, not just a consume-everything stub.
            let transform = newline_consumed_transform();

            loop {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    &source,
                    &transform,
                    1024,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                // A successful stage never leaves a .raw behind.
                assert_eq!(count_raw_files(staging.path()), 0);
                if next.is_none() {
                    break;
                }
            }

            let final_state = state.lock().await;
            for part in &final_state.parts {
                assert!(part.is_done(), "part {} must complete", part.key);
                assert_eq!(part.total_size, Some(body.len() as u64));
            }
        }

        /// Wraps a source to observe (and optionally fail) `cleanup_key` calls, so the
        /// post-commit hook's exactly-once / best-effort behavior is observable.
        struct SpySource<S> {
            inner: S,
            cleanup_calls: std::sync::atomic::AtomicUsize,
            fail_cleanup: bool,
        }

        impl<S> SpySource<S> {
            fn new(inner: S, fail_cleanup: bool) -> Self {
                Self {
                    inner,
                    cleanup_calls: std::sync::atomic::AtomicUsize::new(0),
                    fail_cleanup,
                }
            }

            fn cleanups(&self) -> usize {
                self.cleanup_calls.load(std::sync::atomic::Ordering::SeqCst)
            }
        }

        #[async_trait::async_trait]
        impl<S: DataSource> DataSource for SpySource<S> {
            async fn keys(&self) -> Result<Vec<String>, Error> {
                self.inner.keys().await
            }
            async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
                self.inner.size(key).await
            }
            async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
                self.inner.get_chunk(key, offset, size).await
            }
            async fn prepare_key(&self, key: &str) -> Result<(), Error> {
                self.inner.prepare_key(key).await
            }
            async fn prepare_for_job(&self) -> Result<(), Error> {
                self.inner.prepare_for_job().await
            }
            async fn cleanup_after_job(&self) -> Result<(), Error> {
                self.inner.cleanup_after_job().await
            }
            async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
                self.cleanup_calls
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                if self.fail_cleanup {
                    return Err(Error::msg("simulated cleanup failure"));
                }
                self.inner.cleanup_key(key).await
            }
        }

        fn remote_staging_for(
            store: Arc<object_store::memory::InMemory>,
        ) -> crate::source::RemoteStaging {
            crate::source::RemoteStaging {
                backend: Arc::new(crate::staging::TempBucketBackend::new(
                    store, "staging/", "job-HOOK",
                )),
                extractor_type: ExtractorType::PlainGzip,
                max_plaintext_bytes: 0,
            }
        }

        /// Drive the real fetch loop over a remote source, mirroring do_commit's
        /// post-complete sequence per checkpoint: persist the offset advance to the model,
        /// then invoke the hook. Returns the spy so callers can assert cleanup counts.
        async fn run_loop_with_hook(
            source: &SpySource<DateRangeExportSource>,
            keys: &[String],
        ) -> (Mutex<JobModel>, usize) {
            let state = Mutex::new(job_state(keys));
            let model = Mutex::new(dummy_model(job_state(keys)));
            let transform = newline_consumed_transform();
            let mut commits = 0usize;
            loop {
                let next = select_and_fetch_next_chunk(
                    &state,
                    &model,
                    source,
                    &transform,
                    1024,
                    Uuid::now_v7(),
                )
                .await
                .unwrap();
                let Some((key, parsed, _)) = next else { break };
                {
                    let mut model = model.lock().await;
                    model
                        .state
                        .as_mut()
                        .unwrap()
                        .advance_part_offset(&key, parsed.consumed as u64)
                        .unwrap();
                }
                cleanup_committed_part_if_done(source, &model, &key).await;
                commits += 1;
            }
            (model, commits)
        }

        #[tokio::test]
        async fn test_post_commit_hook_frees_each_remote_part_exactly_once() {
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..500 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let store = Arc::new(object_store::memory::InMemory::new());
            let remote = remote_staging_for(Arc::clone(&store));
            let backend = Arc::clone(&remote.backend);
            let source = SpySource::new(
                build_source_with(
                    server.url("/export"),
                    staging.path(),
                    2,
                    ExtractorType::PlainGzip,
                    Some(remote),
                ),
                false,
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let (_model, commits) = run_loop_with_hook(&source, &keys).await;

            // Multiple commits per part (small chunk size), but exactly one cleanup per
            // part: the hook fires only on the commit that makes the part done.
            assert!(commits > keys.len(), "expected multiple commits per part");
            assert_eq!(source.cleanups(), keys.len());
            for key in &keys {
                assert_eq!(
                    backend.size(key).await.unwrap(),
                    None,
                    "staged object for a committed part must be deleted"
                );
            }
        }

        #[tokio::test]
        async fn test_post_commit_hook_preserves_staging_until_part_is_done() {
            // Encodes the rollback / crash-between-commit-stages guarantee: the hook only
            // fires for a durably-done part, so a part mid-flight (or with its offset
            // reverted) keeps its staged object for the byte-identical re-read.
            let server = MockServer::start();
            let body = b"{\"event\":\"a\"}\n{\"event\":\"b\"}\n";
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body));
            });

            let staging = TempDir::new().unwrap();
            let store = Arc::new(object_store::memory::InMemory::new());
            let remote = remote_staging_for(Arc::clone(&store));
            let backend = Arc::clone(&remote.backend);
            let source = SpySource::new(
                build_source_with(
                    server.url("/export"),
                    staging.path(),
                    1,
                    ExtractorType::PlainGzip,
                    Some(remote),
                ),
                false,
            );
            source.prepare_for_job().await.unwrap();
            let key = source.keys().await.unwrap().remove(0);
            source.prepare_key(&key).await.unwrap();

            let model = Mutex::new(dummy_model(job_state(std::slice::from_ref(&key))));
            {
                let mut model = model.lock().await;
                let state = model.state.as_mut().unwrap();
                state.parts[0].total_size = Some(body.len() as u64);
                // Partially consumed (e.g. after a rollback reverted a later advance).
                state.parts[0].current_offset = 14;
            }

            cleanup_committed_part_if_done(&source, &model, &key).await;
            assert_eq!(
                source.cleanups(),
                0,
                "hook must not fire for a part mid-flight"
            );
            assert_eq!(
                backend.size(&key).await.unwrap(),
                Some(body.len() as u64),
                "staged object must survive for the re-read"
            );
        }

        #[tokio::test]
        async fn test_post_commit_hook_cleanup_failure_is_best_effort() {
            let server = MockServer::start();
            let body = b"{\"event\":\"a\"}\n";
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body));
            });

            let staging = TempDir::new().unwrap();
            let store = Arc::new(object_store::memory::InMemory::new());
            let remote = remote_staging_for(Arc::clone(&store));
            let source = SpySource::new(
                build_source_with(
                    server.url("/export"),
                    staging.path(),
                    1,
                    ExtractorType::PlainGzip,
                    Some(remote),
                ),
                true, // cleanup_key always fails
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            // The loop must run to completion despite every cleanup failing.
            let (_model, _commits) = run_loop_with_hook(&source, &keys).await;
            assert_eq!(source.cleanups(), 1, "hook attempted the cleanup");
        }

        #[tokio::test]
        async fn test_post_commit_hook_empty_part_cleanup_is_no_op() {
            let server = MockServer::start();
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(404);
            });

            let staging = TempDir::new().unwrap();
            let store = Arc::new(object_store::memory::InMemory::new());
            let remote = remote_staging_for(Arc::clone(&store));
            let backend = Arc::clone(&remote.backend);
            let source = SpySource::new(
                build_source_with(
                    server.url("/export"),
                    staging.path(),
                    1,
                    ExtractorType::PlainGzip,
                    Some(remote),
                ),
                false,
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let (model, _commits) = run_loop_with_hook(&source, &keys).await;

            // The empty part commits to done (0 == 0), the hook fires, and the delete of
            // the (empty) staged object succeeds; a second invocation is a no-op.
            assert_eq!(source.cleanups(), 1);
            assert_eq!(backend.size(&keys[0]).await.unwrap(), None);
            cleanup_committed_part_if_done(&source, &model, &keys[0]).await;
            assert_eq!(source.cleanups(), 2, "double cleanup is tolerated");
        }
    }

    /// A part whose first bytes are a known compression magic is still compressed
    /// (double-compression, or a source/extractor whose compression setting does
    /// not match the file). The loop must fail fast at part offset 0 with an
    /// actionable, non-transient error - never crawl or emit a confusing utf-8
    /// parse failure. The guard sits in the shared loop, so one streaming source
    /// (post-decompression double-gzip) and one plain verbatim source (a gzip file
    /// on a non-decompressing source) together prove it covers every source shape.
    mod compression_magic_guard_tests {
        use super::staging_cleanup_invariant_tests::{
            build_source_with_extractor, dummy_model, gzip_bytes, job_state,
            newline_consumed_transform,
        };
        use super::*;
        use crate::extractor::ExtractorType;
        use crate::source::folder::FolderSource;
        use tempfile::TempDir;

        fn assert_non_transient(err: &Error) {
            assert!(!crate::error::is_rate_limited_error(err));
            assert!(!crate::error::is_timeout_error(err));
            assert!(!crate::error::is_transient_network_error(err));
            assert!(!crate::error::is_transient_server_error(err));
        }

        #[tokio::test]
        async fn test_double_gzipped_part_detected_at_offset_zero() {
            // gzip(gzip(jsonl)): the extractor strips the outer gzip, so the
            // plaintext stream *starts* with the inner gzip magic. The guard must
            // catch it at offset 0 and pause with the double-compression message.
            let server = MockServer::start();
            let mut inner = String::new();
            for i in 0..50 {
                inner.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let double = gzip_bytes(&gzip_bytes(inner.as_bytes()));
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(double);
            });

            let staging = TempDir::new().unwrap();
            let source = build_source_with_extractor(
                server.url("/export"),
                staging.path(),
                1,
                ExtractorType::PlainGzip,
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            let err = select_and_fetch_next_chunk(
                &state,
                &model,
                &source,
                &transform,
                1024,
                Uuid::now_v7(),
            )
            .await
            .expect_err("double-gzipped data must be rejected at offset 0");

            let user_msg = crate::error::get_user_message(&err);
            assert!(
                user_msg.contains("compressed twice") && user_msg.contains("gzip"),
                "unexpected user message: {user_msg}"
            );
            assert!(
                format!("{err:#}").contains("offset 0"),
                "internal chain should record the offset, got: {err:#}"
            );
            assert_non_transient(&err);
            // The guard fires before advancing, so nothing is consumed.
            assert_eq!(state.lock().await.parts[0].current_offset, 0);
        }

        #[tokio::test]
        async fn test_plain_source_serving_gzip_file_detected_at_offset_zero() {
            // The reverse misconfiguration: a gzipped file handed to a plain
            // (verbatim, non-decompressing) source. The raw gzip magic is the first
            // thing the loop reads, so the same offset-0 guard must catch it.
            let staging = TempDir::new().unwrap();
            let gz = gzip_bytes(b"{\"event\":\"x\"}\n");
            std::fs::write(staging.path().join("data.jsonl"), &gz).unwrap();

            let source = FolderSource::new(staging.path().to_str().unwrap().to_string())
                .await
                .unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            let err = select_and_fetch_next_chunk(
                &state,
                &model,
                &source,
                &transform,
                1024,
                Uuid::now_v7(),
            )
            .await
            .expect_err("a gzip file on a plain source must be rejected at offset 0");

            let user_msg = crate::error::get_user_message(&err);
            assert!(
                user_msg.contains("compressed") && user_msg.contains("gzip"),
                "unexpected user message: {user_msg}"
            );
            assert_non_transient(&err);
        }

        #[tokio::test]
        async fn test_non_magic_binary_still_yields_parse_error() {
            // Bucket 3: non-magic invalid-utf8 content is corrupt data, not
            // compression. The guard must NOT fire; the pre-existing utf-8 parse
            // error must surface unchanged, proving the guard does not over-claim.
            let staging = TempDir::new().unwrap();
            // 0xff is not a compression-magic first byte; the trailing newline forms
            // a complete line that fails utf-8 validation - the pre-existing path.
            std::fs::write(staging.path().join("data.jsonl"), [0xff, 0x28, 0xff, b'\n']).unwrap();

            let source = FolderSource::new(staging.path().to_str().unwrap().to_string())
                .await
                .unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            let err = select_and_fetch_next_chunk(
                &state,
                &model,
                &source,
                &transform,
                1024,
                Uuid::now_v7(),
            )
            .await
            .expect_err("invalid-utf8 binary must still fail");

            let full = format!("{err:#}");
            assert!(
                full.contains("utf8") || full.contains("Failed to parse"),
                "expected the pre-existing parse error, got: {full}"
            );
            assert!(
                !crate::error::get_user_message(&err).contains("compressed twice"),
                "non-magic data must not be mislabeled as double-compression: {full}"
            );
            assert_non_transient(&err);
        }
    }

    /// Streaming sources discover a part's decompressed size only on the read
    /// that observes end-of-stream. When that stream turns out to be empty (or
    /// already fully consumed at the resume offset), the first read returns an
    /// empty chunk before the job has ever seen a size - which must complete the
    /// part, not pause the job as "source returned no data". These tests pin
    /// every empty-stream shape plus the error path for genuinely broken sources.
    mod empty_part_completion_tests {
        use super::staging_cleanup_invariant_tests::{
            build_source_with_extractor, drive_loop_to_completion, dummy_model, gzip_bytes,
            job_state, newline_consumed_transform,
        };
        use super::*;
        use crate::extractor::ExtractorType;
        use std::io::Write;
        use tempfile::TempDir;
        use zip::{write::SimpleFileOptions, ZipWriter};

        /// A zip archive with no `.json.gz` members - the Amplitude-shaped
        /// equivalent of an empty export (decompresses to zero bytes).
        pub(super) fn zip_without_json_members() -> Vec<u8> {
            let mut zip = ZipWriter::new(std::io::Cursor::new(Vec::new()));
            zip.start_file("readme.txt", SimpleFileOptions::default())
                .unwrap();
            zip.write_all(b"no data for this day").unwrap();
            zip.finish().unwrap().into_inner()
        }

        /// Empty exports come in several shapes, all decompressing to zero
        /// bytes: a raw empty 200 body (Mixpanel day with no events), a valid
        /// gzip of empty content, and a zip with no data members. Each must
        /// complete the part exactly like the pre-streaming code did.
        #[tokio::test]
        async fn test_empty_export_completes_part() {
            let cases: [(&str, Vec<u8>, ExtractorType); 3] = [
                ("empty 200 body", Vec::new(), ExtractorType::PlainGzip),
                (
                    "gzip of empty content",
                    gzip_bytes(b""),
                    ExtractorType::PlainGzip,
                ),
                (
                    "zip with no json members",
                    zip_without_json_members(),
                    ExtractorType::ZipGzipJson,
                ),
            ];

            for (name, body, extractor) in cases {
                let server = MockServer::start();
                let _mock = server.mock(|when, then| {
                    when.method(Method::GET).path("/export");
                    then.status(200).body(body);
                });

                let staging = TempDir::new().unwrap();
                let source = build_source_with_extractor(
                    server.url("/export"),
                    staging.path(),
                    1,
                    extractor,
                );
                source.prepare_for_job().await.unwrap();
                let keys = source.keys().await.unwrap();

                let state = Mutex::new(job_state(&keys));
                let model = Mutex::new(dummy_model(job_state(&keys)));
                let transform = newline_consumed_transform();

                let completed =
                    drive_loop_to_completion(&state, &model, &source, &transform, 1024, 10)
                        .await
                        .unwrap_or_else(|e| panic!("case '{name}' errored: {e:#}"));

                assert!(completed, "case '{name}' did not complete the empty part");
                let state = state.lock().await;
                assert_eq!(state.parts[0].current_offset, 0, "case '{name}'");
                assert_eq!(
                    state.parts[0].total_size,
                    Some(0),
                    "case '{name}' must record the discovered size so the DB state is terminal"
                );
                // The mirrored model state is what gets persisted on commit.
                let model = model.lock().await;
                assert_eq!(
                    model.state.as_ref().unwrap().parts[0].total_size,
                    Some(0),
                    "case '{name}' must mirror the size into the model"
                );
            }
        }

        /// A job can crash after committing the offset of a part's final chunk
        /// but before the next iteration discovered (and persisted) the size.
        /// On resume the re-downloaded stream EOFs exactly at the stored offset:
        /// the first read is empty with total_size still None, and the part must
        /// complete. If the re-downloaded data is instead *smaller* than the
        /// stored offset (non-byte-stable export), everything available was
        /// already consumed, so the part must also complete rather than strand
        /// the job on an unresolvable error.
        #[tokio::test]
        async fn test_resume_at_or_past_eof_with_unknown_total_completes() {
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let total_size = body.len() as u64;

            for (name, resume_offset) in [
                ("resume exactly at EOF", total_size),
                ("resume past a shrunk export", total_size + 1000),
            ] {
                let server = MockServer::start();
                let _mock = server.mock(|when, then| {
                    when.method(Method::GET).path("/export");
                    then.status(200).body(gzip_bytes(body.as_bytes()));
                });

                let staging = TempDir::new().unwrap();
                let source = build_source_with_extractor(
                    server.url("/export"),
                    staging.path(),
                    1,
                    ExtractorType::PlainGzip,
                );
                source.prepare_for_job().await.unwrap();
                let keys = source.keys().await.unwrap();

                let resumed = JobState {
                    parts: vec![PartState {
                        key: keys[0].clone(),
                        current_offset: resume_offset,
                        total_size: None,
                    }],
                };
                let state = Mutex::new(resumed.clone());
                let model = Mutex::new(dummy_model(resumed));
                let transform = newline_consumed_transform();

                let completed =
                    drive_loop_to_completion(&state, &model, &source, &transform, 1024, 10)
                        .await
                        .unwrap_or_else(|e| panic!("case '{name}' errored: {e:#}"));

                assert!(completed, "case '{name}' did not complete");
                let state = state.lock().await;
                assert_eq!(
                    state.parts[0].total_size,
                    Some(total_size),
                    "case '{name}' must record the size discovered on resume"
                );
                assert_eq!(
                    state.parts[0].current_offset, resume_offset,
                    "case '{name}' must not rewind or advance the stored offset"
                );
            }
        }

        /// A source that reports a fixed size but serves empty chunks - the
        /// "genuinely broken source" shape (e.g. a ranged HTTP server returning
        /// empty 200s mid-part, or a stream that shrank to a size that no longer
        /// matches the part's recorded total). These must still pause the job
        /// loudly, proving the empty-part completion path did not neuter the
        /// no-progress guard.
        struct EmptyChunkSource {
            reported_size: Option<u64>,
        }

        #[async_trait]
        impl DataSource for EmptyChunkSource {
            async fn keys(&self) -> Result<Vec<String>, Error> {
                Ok(vec!["part".to_string()])
            }

            async fn size(&self, _key: &str) -> Result<Option<u64>, Error> {
                Ok(self.reported_size)
            }

            async fn get_chunk(
                &self,
                _key: &str,
                _offset: u64,
                _size: u64,
            ) -> Result<Vec<u8>, Error> {
                Ok(Vec::new())
            }
        }

        #[tokio::test]
        async fn test_empty_chunk_before_end_of_part_still_errors() {
            // (case, part state total, part offset, source-reported size)
            let cases: [(&str, Option<u64>, u64, Option<u64>); 3] = [
                // Ranged source serving empty bodies mid-part.
                ("empty chunk below known size", Some(1000), 400, Some(1000)),
                // Stream ended early relative to what the source itself reports.
                ("source size past offset", None, 400, Some(1000)),
                // Stored total disagrees with what the source now reports.
                (
                    "shrunk source with recorded total",
                    Some(1000),
                    400,
                    Some(400),
                ),
            ];

            for (name, part_total, offset, reported_size) in cases {
                let source = EmptyChunkSource { reported_size };
                let part_state = JobState {
                    parts: vec![PartState {
                        key: "part".to_string(),
                        current_offset: offset,
                        total_size: part_total,
                    }],
                };
                let state = Mutex::new(part_state.clone());
                let model = Mutex::new(dummy_model(part_state));
                let transform = newline_consumed_transform();

                let result =
                    drive_loop_to_completion(&state, &model, &source, &transform, 1024, 5).await;

                let err = result.unwrap_err();
                assert!(
                    format!("{err:#}").contains("returned no data"),
                    "case '{name}' expected the no-data error, got: {err:#}"
                );
            }
        }
    }

    /// Remote (temp-bucket) staging must satisfy the same read-loop contracts the
    /// local streaming path is pinned to above and in `empty_part_completion_tests`:
    /// empty exports complete, trailing blank lines complete, and parts already done
    /// (including offsets overshot by a past worker bug) are skipped without ever
    /// touching the origin or the backend. All drive the real
    /// `select_and_fetch_next_chunk` loop over a temp-bucket-staged source.
    mod remote_read_loop_parity_tests {
        use super::empty_part_completion_tests::zip_without_json_members;
        use super::staging_cleanup_invariant_tests::{
            build_source_with, drive_loop_to_completion, dummy_model, gzip_bytes, job_state,
            newline_consumed_transform,
        };
        use super::*;
        use crate::extractor::ExtractorType;
        use crate::source::RemoteStaging;
        use crate::staging::{StagingBackend, TempBucketBackend};
        use object_store::memory::InMemory;
        use tempfile::TempDir;

        fn remote_staging(store: Arc<InMemory>) -> (RemoteStaging, Arc<TempBucketBackend>) {
            let backend = Arc::new(TempBucketBackend::new(store, "staging/", "job-PARITY"));
            let backend_dyn: Arc<dyn StagingBackend> = backend.clone();
            (
                RemoteStaging {
                    backend: backend_dyn,
                    extractor_type: ExtractorType::PlainGzip,
                    max_plaintext_bytes: 0,
                },
                backend,
            )
        }

        /// Remote counterpart of `test_empty_export_completes_part`: every empty
        /// export shape stages an empty object and completes the part.
        #[tokio::test]
        async fn test_remote_empty_export_completes_part() {
            let cases: [(&str, Vec<u8>, ExtractorType); 3] = [
                ("empty 200 body", Vec::new(), ExtractorType::PlainGzip),
                (
                    "gzip of empty content",
                    gzip_bytes(b""),
                    ExtractorType::PlainGzip,
                ),
                (
                    "zip with no json members",
                    zip_without_json_members(),
                    ExtractorType::ZipGzipJson,
                ),
            ];

            for (name, body, extractor) in cases {
                let server = MockServer::start();
                let _mock = server.mock(|when, then| {
                    when.method(Method::GET).path("/export");
                    then.status(200).body(body);
                });

                let staging = TempDir::new().unwrap();
                let (mut remote, backend) = remote_staging(Arc::new(InMemory::new()));
                remote.extractor_type = extractor.clone();
                let source = build_source_with(
                    server.url("/export"),
                    staging.path(),
                    1,
                    extractor,
                    Some(remote),
                );
                source.prepare_for_job().await.unwrap();
                let keys = source.keys().await.unwrap();

                let state = Mutex::new(job_state(&keys));
                let model = Mutex::new(dummy_model(job_state(&keys)));
                let transform = newline_consumed_transform();

                let completed =
                    drive_loop_to_completion(&state, &model, &source, &transform, 1024, 10)
                        .await
                        .unwrap_or_else(|e| panic!("case '{name}' errored: {e:#}"));

                assert!(completed, "case '{name}' did not complete the empty part");
                let state = state.lock().await;
                assert_eq!(state.parts[0].current_offset, 0, "case '{name}'");
                assert_eq!(state.parts[0].total_size, Some(0), "case '{name}'");
                // The empty object is durably staged: a resume attaches to it
                // instead of re-downloading from the origin.
                assert_eq!(
                    backend.size(&keys[0]).await.unwrap(),
                    Some(0),
                    "case '{name}' must stage an empty object"
                );
            }
        }

        /// Remote counterpart of `test_part_with_trailing_blank_lines_completes`:
        /// blank trailing content in the staged bytes is consumed over ranged
        /// backend reads exactly as over the local stream.
        #[tokio::test]
        async fn test_remote_part_with_trailing_blank_lines_completes() {
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            body.push('\n');
            let total_size = body.len() as u64;
            let _mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let (remote, _backend) = remote_staging(Arc::new(InMemory::new()));
            let source = build_source_with(
                server.url("/export"),
                staging.path(),
                1,
                ExtractorType::PlainGzip,
                Some(remote),
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();

            let state = Mutex::new(job_state(&keys));
            let model = Mutex::new(dummy_model(job_state(&keys)));
            let transform = newline_consumed_transform();

            let completed = drive_loop_to_completion(
                &state,
                &model,
                &source,
                &transform,
                1024,
                (total_size as usize / 1024) + 10,
            )
            .await
            .unwrap();

            assert!(completed, "trailing blank lines must not stall the part");
            assert_eq!(state.lock().await.parts[0].current_offset, total_size);
        }

        /// Remote counterpart of `test_poisoned_part_with_overshot_offset_self_heals`:
        /// a part whose stored offset overshot its total (a past worker bug) is
        /// skipped as done without being staged or re-downloaded - `is_done` is
        /// checked before any prepare work, so the poisoned part costs nothing.
        #[tokio::test]
        async fn test_remote_poisoned_part_skipped_without_staging() {
            let server = MockServer::start();
            let mut body = String::new();
            for i in 0..200 {
                body.push_str(&format!("{{\"event\":\"e{i}\"}}\n"));
            }
            let mock = server.mock(|when, then| {
                when.method(Method::GET).path("/export");
                then.status(200).body(gzip_bytes(body.as_bytes()));
            });

            let staging = TempDir::new().unwrap();
            let (remote, backend) = remote_staging(Arc::new(InMemory::new()));
            let source = build_source_with(
                server.url("/export"),
                staging.path(),
                2,
                ExtractorType::PlainGzip,
                Some(remote),
            );
            source.prepare_for_job().await.unwrap();
            let keys = source.keys().await.unwrap();
            assert_eq!(keys.len(), 2);

            let poisoned = JobState {
                parts: vec![
                    PartState {
                        key: keys[0].clone(),
                        current_offset: 25_328_072,
                        total_size: Some(24_441_157),
                    },
                    PartState {
                        key: keys[1].clone(),
                        current_offset: 0,
                        total_size: None,
                    },
                ],
            };
            let state = Mutex::new(poisoned.clone());
            let model = Mutex::new(dummy_model(poisoned));
            let transform = newline_consumed_transform();

            let completed = drive_loop_to_completion(&state, &model, &source, &transform, 1024, 20)
                .await
                .unwrap();

            assert!(completed, "job with an overshot part must finish the rest");
            let state = state.lock().await;
            assert_eq!(
                state.parts[0].current_offset, 25_328_072,
                "poisoned part must be skipped untouched"
            );
            assert_eq!(state.parts[1].total_size, Some(body.len() as u64));
            assert_eq!(
                backend.size(&keys[0]).await.unwrap(),
                None,
                "poisoned part must never be staged"
            );
            assert_eq!(
                mock.hits(),
                1,
                "only the healthy part may hit the origin (one download)"
            );
        }
    }
}
