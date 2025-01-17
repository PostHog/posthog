use std::sync::Arc;

use anyhow::Error;

use model::{JobModel, JobState, PartState};
use tracing::{debug, info, warn};

use crate::{context::AppContext, emit::Emitter, parse::format::ParserFn, source::DataSource};

pub mod config;
pub mod model;

pub struct Job {
    pub context: Arc<AppContext>,
    pub model: JobModel,
    pub state: JobState,

    pub source: Box<dyn DataSource>,
    pub transform: ParserFn,
    pub sink: Box<dyn Emitter>,
}

impl Job {
    pub async fn new(model: JobModel, context: Arc<AppContext>) -> Result<Self, Error> {
        let source = model
            .import_config
            .source
            .construct(&model.secrets, context.clone())
            .await?;

        let transform = Box::new(
            model
                .import_config
                .data_format
                .get_parser(&model, context.clone())
                .await?,
        );

        let sink = model.import_config.sink.construct(context.clone()).await?;

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
            let keys = source.keys().await?;
            for key in keys {
                let size = source.size(&key).await?;
                debug!("Got size for part {}: {}", key, size);
                parts.push(PartState {
                    key,
                    current_offset: 0,
                    total_size: size,
                });
            }
            state.parts = parts;
            info!("Initialized parts list: {:?}", state.parts);
        }

        Ok(Self {
            context: context.clone(),
            model,
            state,
            source,
            transform,
            sink,
        })
    }

    pub async fn process_next_chunk(mut self) -> Result<Option<Self>, Error> {
        let Some(next_part) = self.get_next_unfinished_part() else {
            self.successfully_complete().await?;
            return Ok(None);
        };

        let next_chunk = match self
            .source
            .get_chunk(
                &next_part.key,
                next_part.current_offset,
                self.context.config.chunk_size,
            )
            .await
        {
            Ok(c) => c,
            Err(e) => {
                // Failure to fetch - pause, and let some manual intervention resume the job
                warn!("Failed to fetch part {}: {}, pausing job", next_part.key, e);
                self.model.pause(self.context, e.to_string()).await?;
                return Ok(None);
            }
        };

        let is_last_chunk = next_part.current_offset + next_chunk.len() > next_part.total_size;

        let chunk_bytes = next_chunk.len();

        // TODO - spawn blocking? Probably not, we only let a worker run one job at a time anyway
        let parsed = match (self.transform)(next_chunk) {
            Ok(p) => p,
            Err(e) => {
                // If we hit data we can't parse, we should fail the job (rather than pausing),
                // under the assumption it can't simply be restarted (although in practice we may
                // restart failed jobs), but might need actual code changes
                warn!(
                    "Failed to parse part {} at offset {}: {}, failing job",
                    next_part.key, next_part.current_offset, e
                );
                self.model.fail(&self.context.db, e.to_string()).await?;
                return Ok(None);
            }
        };

        // If this is the last chunk, and we didn't consume all of it, or we didn't manage to
        // consume any of this chunk, we've got a bad chunk, and should pause the job with an error.
        if parsed.consumed < chunk_bytes && is_last_chunk || parsed.data.is_empty() {
            let msg = format!(
                "Failed to parse any data from part {} at offset {}",
                next_part.key, next_part.current_offset
            );
            warn!("{}", msg);
            self.model.pause(self.context, msg).await?;
            return Ok(None);
        }

        // We do a bit of a dance here to get a two stage commit, preemptively pausing the job such that if the commit to
        // kafka fails, we
        // If this fails, we just bail out, and then eventually someone else will pick up the job again and re-process this chunk
        self.sink.begin_write().await?;
        // If this fails, as above
        self.sink.emit(&parsed.data).await?;
        // This is where things get tricky - if we fail to commit the chunk to the sink in the next step, and we've told PG we've
        // committed the chunk, we'll bail out, and whoever comes next will end up skipping this chunk. To prevent this, we do a two
        // stage commit, where we pause the job before committing the chunk to the sink, and then only unpause it after the sink commit,
        // such that if we get interrupted between the two, the job will be paused, and manual intervention will be required to resume it.
        // This operator can then confirm whether the sink commit succeeded or not (by looking at the last event written, or by
        // looking at logs, or both). The jobs status message is set to enable this kind of debugging.
        self.begin_part_commit(next_part, parsed.consumed).await?;
        self.sink.commit_write().await?;
        self.complete_commit().await?;

        // This wasn't the last part/chunk, so we return the job to let it be processed again
        Ok(Some(self))
    }

    pub async fn successfully_complete(mut self) -> Result<(), Error> {
        self.model.complete(&self.context.db).await
    }

    // Writes the new partstate to the DB, and sets the job status to paused, such that if there's an issue with the sink commit, the job
    // will be paused, and manual intervention will be required to resume it
    pub async fn begin_part_commit(
        &mut self,
        part: PartState,
        consumed: usize,
    ) -> Result<(), Error> {
        self.state.parts.iter_mut().for_each(|p| {
            if p.key == part.key {
                p.current_offset += consumed;
            }
        });

        self.model.state = Some(self.state.clone());
        let status_message = format!(
            "Starting commit of part {} at offset {}, consumed {} bytes",
            part.key, part.current_offset, consumed
        );
        self.model.pause(self.context.clone(), status_message).await
    }

    // Unpauses the job
    pub async fn complete_commit(&mut self) -> Result<(), Error> {
        self.model.unpause(self.context.clone()).await
    }

    pub fn get_next_unfinished_part(&self) -> Option<PartState> {
        self.state.parts.iter().find(|c| !c.is_done()).cloned()
    }
}
