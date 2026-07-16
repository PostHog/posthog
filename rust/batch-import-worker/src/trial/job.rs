use std::sync::Arc;

use anyhow::{Context, Error};
use lifecycle::Handle;
use tokio::sync::Mutex;
use tracing::{info, warn};
use uuid::Uuid;

use crate::{
    context::AppContext,
    error::ensure_user_message,
    job::{
        cleanup_committed_part_if_done,
        config::SinkConfig,
        handle_fetch_error, load_or_init_state,
        model::{JobModel, JobState},
        select_and_fetch_next_chunk,
    },
    parse::{format::ParserFnFor, Parsed},
    source::DataSource,
    staging::s3_client::create_trial_output_store,
    trial::{parser::build_trial_parser, sink::TrialSink, TrialRecord},
};

/// A bounded trial run of an import: same source, format, and transforms as the
/// real thing, but each source record is paired with its would-be output (or the
/// reason it failed) and written to the trial output bucket instead of being
/// captured.
///
/// Unlike [`crate::job::Job`], processing is sequential — no pipelined
/// fetch/commit, no two-stage offset commit. Durability comes from ordering:
/// pages are written to object storage before the progress that counts them is
/// flushed, so a worker death re-fetches at most one chunk and overwrites the
/// same page indices. Re-transformed records can differ in generated values
/// (fresh UUIDs for events without one, identify-cache dedup state), which is
/// acceptable for a preview.
pub struct TrialJob {
    context: Arc<AppContext>,
    handle: Handle,
    job_id: Uuid,
    chunk_size: usize,
    state: Mutex<JobState>,
    model: Mutex<JobModel>,
    source: Box<dyn DataSource>,
    transform: Arc<ParserFnFor<TrialRecord>>,
    sink: TrialSink,
    record_limit: u64,
}

impl TrialJob {
    pub async fn new(
        mut model: JobModel,
        context: Arc<AppContext>,
        handle: Handle,
    ) -> Result<Self, Error> {
        let SinkConfig::TrialS3 { record_limit } = &model.import_config.sink else {
            anyhow::bail!(
                "TrialJob constructed for job {} without a trial_s3 sink",
                model.id
            );
        };
        let record_limit = (*record_limit).clamp(1, context.config.trial_max_record_limit);

        // Fail fast (pausing the job with a user-facing message) when this
        // worker has no trial bucket configured, before any source work starts.
        let store = create_trial_output_store(&context.config)
            .await
            .map_err(|e| {
                ensure_user_message(
                    e,
                    "Trial runs are temporarily unavailable. Please try again later.",
                )
            })?;
        let prefix = format!(
            "{}/team_{}/job_{}",
            context.config.trial_bucket_prefix.trim_matches('/'),
            model.team_id,
            model.id
        );
        let sink = TrialSink::new(store, prefix, context.config.trial_records_per_page);

        let is_restarting = model.state.is_some();
        let source = model
            .import_config
            .source
            .construct(&model.secrets, context.clone(), is_restarting, model.id)
            .await
            .with_context(|| "Failed to construct data source for trial job".to_string())?;
        source.prepare_for_job().await?;

        let transform = Arc::new(build_trial_parser(&model, context.clone()).await?);
        let state = load_or_init_state(source.as_ref(), &mut model).await?;

        let job_id = model.id;
        let chunk_size = context.config.trial_chunk_size;

        Ok(Self {
            context,
            handle,
            job_id,
            chunk_size,
            state: Mutex::new(state),
            model: Mutex::new(model),
            source,
            transform,
            sink,
            record_limit,
        })
    }

    pub async fn run(self) -> Result<(), Error> {
        loop {
            if self.handle.is_shutting_down() {
                // Keep remote staging on shutdown so the pod that re-claims the
                // trial attaches to staged parts instead of re-downloading.
                info!("Shutting down, releasing in-flight trial job resources");
                if let Err(e) = self.source.release_job_resources().await {
                    warn!("Failed to release trial job source resources: {:?}", e);
                }
                return Ok(());
            }

            let records_emitted = {
                let state = self.state.lock().await;
                state.trial.as_ref().map_or(0, |t| t.records_emitted)
            };
            if records_emitted >= self.record_limit {
                break;
            }

            let fetched = select_and_fetch_next_chunk(
                &self.state,
                &self.model,
                self.source.as_ref(),
                &self.transform,
                self.chunk_size,
                self.job_id,
            )
            .await;

            let outcome = match fetched {
                Ok(Some((key, parsed, reset_backoff))) => {
                    self.commit_chunk(&key, parsed, reset_backoff).await
                }
                Ok(None) => break, // Source exhausted before the record limit
                Err(e) => Err(e),
            };

            if let Err(e) = outcome {
                // Same classification as the import path: transient errors
                // (source rate limits, object-store weather) back off and the
                // trial resumes from its persisted progress; anything else
                // pauses with a user-facing message.
                handle_fetch_error(
                    &e,
                    &self.context,
                    &self.model,
                    &self.state,
                    self.source.as_ref(),
                )
                .await?;
                return Ok(());
            }
        }

        self.complete().await
    }

    /// Persist one fetched chunk: write its records as pages, fold them into the
    /// running summary, then flush the advanced offsets and trial progress.
    /// Ordering matters — pages first, progress second — so a crash in between
    /// re-fetches the chunk and overwrites the same pages.
    async fn commit_chunk(
        &self,
        key: &str,
        parsed: Parsed<Vec<TrialRecord>>,
        reset_backoff: bool,
    ) -> Result<(), Error> {
        let mut progress = {
            let state = self.state.lock().await;
            state.trial.clone().unwrap_or_default()
        };

        let mut records = parsed.data;
        progress.truncate_to_budget(&mut records, self.record_limit);

        if !records.is_empty() {
            let pages = self
                .sink
                .write_pages(progress.pages_written, progress.records_emitted, &records)
                .await?;
            progress.absorb(&records, pages);
        }

        let state_snapshot = {
            let mut state = self.state.lock().await;
            state.trial = Some(progress);
            state.clone()
        };

        {
            let mut model = self.model.lock().await;
            if reset_backoff && model.backoff_attempt > 0 {
                model.reset_backoff_in_db(&self.context.db).await?;
            }
            model.state = Some(state_snapshot);
            model.flush(&self.context.db, true).await?;
        }

        cleanup_committed_part_if_done(self.source.as_ref(), &self.model, key).await;
        Ok(())
    }

    /// Write the summary and mark the job completed. Idempotent: a resume after
    /// a failure here re-enters via the record-limit (or exhausted-source) check
    /// and rewrites the same summary from the persisted progress.
    async fn complete(self) -> Result<(), Error> {
        if let Err(e) = self.source.cleanup_after_job().await {
            warn!("Failed to cleanup after trial job: {:?}", e);
        }

        let progress = {
            let state = self.state.lock().await;
            state.trial.clone().unwrap_or_default()
        };
        self.sink.write_summary(&progress).await?;

        let mut model = self.model.lock().await;
        info!(
            job_id = %self.job_id,
            records = progress.records_emitted,
            "Trial job completed"
        );
        model.complete(&self.context.db).await
    }
}
