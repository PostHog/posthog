use std::sync::{atomic::Ordering, Arc};

use anyhow::{Context, Error};

use common_types::InternallyCapturedEvent;
use model::{JobModel, JobState, PartState};
use tokio::sync::Mutex;
use tracing::{debug, error, info, warn};

use crate::{
    context::AppContext,
    emit::Emitter,
    error::get_user_message,
    parse::{format::ParserFn, Parsed},
    source::DataSource,
    spawn_liveness_loop,
};

pub mod config;
pub mod model;

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
                    .with_context(|| format!("Failed to get size for part {}", key))?;
                debug!("Got size for part {}: {:?}", key, size);
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
                // If we fail to fetch and parse, we need to pause the job (assuming manual intervention is required) and
                // return an Ok(None) - this pod can continue to process other jobs, it just can't work on this one
                error!("Failed to fetch and parse chunk: {:?}", e);
                self.model
                    .lock()
                    .await
                    .pause(
                        self.context.clone(),
                        format!("Failed to fetch and parse chunk: {:?}", e),
                        Some(user_facing_error_message.to_string()),
                    )
                    .await?;
                return Ok(None);
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
                        next_part.key.clone(),
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
            .context(format!("Fetching part chunk {:?}", next_part))?;

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
            .context(format!("Processing part chunk {:?}", next_part))?;

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

        Ok(Some((next_part.key.clone(), parsed)))
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
        model.complete(&self.context.db).await
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
            return Err(Error::msg(format!("No part found with key {}", key)));
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
