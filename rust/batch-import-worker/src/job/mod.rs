use std::sync::Arc;

use anyhow::Error;
use common_types::InternallyCapturedEvent;
use model::{JobModel, JobState, PartState};
use tracing::info;

use crate::{context::AppContext, emit::Emitter, parse::Parsed, source::DataSource};

pub mod config;
pub mod model;

pub struct Job {
    pub context: Arc<AppContext>,
    pub model: JobModel,
    pub state: JobState,

    pub source: Box<dyn DataSource>,
    pub transform: Box<dyn Fn(Vec<u8>) -> Result<Parsed<Vec<InternallyCapturedEvent>>, Error>>,
    pub sink: Box<dyn Emitter>,
}

impl Job {
    pub async fn new(model: JobModel, context: Arc<AppContext>) -> Result<Self, Error> {
        let source = model
            .import_config
            .source
            .construct(context.clone())
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
                parts.push(PartState {
                    key,
                    current_offset: 0,
                    total_size: size,
                });
            }
            state.parts = parts;
            info!("Initialized parts list");
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
                self.model.pause(self.context, e.to_string()).await?;
                return Ok(None);
            }
        };

        let is_last_chunk = next_part.current_offset + next_chunk.len() > next_part.total_size;

        let chunk_bytes = next_chunk.len();

        // TODO - spawn blocking?
        let parsed = match (self.transform)(next_chunk) {
            Ok(p) => p,
            Err(e) => {
                // If we hit data we can't parse, we should fail the job (rather than pausing),
                // under the assumption it can't simply be restarted (although in practice we may
                // restart failed jobs)
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
            self.model.pause(self.context, msg).await?;
            return Ok(None);
        }

        // TODO - proper error handling, although maybe on emit errors we really do just
        // want to bail out, and let another worker pick up the job later, once the leased_until
        // has expired (with some special case error handling maybe?)... this depends a bit on
        // the emitter implementation (and whether non-transient errors are possible)
        self.sink.emit(&parsed.data).await?;

        self.commit_chunk(next_part, parsed.consumed).await?;

        // This wasn't the last part/chunk, so we return the job to let it be processed again
        Ok(Some(self))
    }

    pub async fn successfully_complete(self) -> Result<(), Error> {
        self.model.complete(&self.context.db).await
    }

    pub async fn commit_chunk(&mut self, part: PartState, consumed: usize) -> Result<(), Error> {
        self.state.parts.iter_mut().for_each(|p| {
            if p.key == part.key {
                p.current_offset += consumed;
            }
        });

        self.model
            .flush_state_update(&self.context.db, self.state.clone())
            .await
    }

    pub fn get_next_unfinished_part(&self) -> Option<PartState> {
        self.state.parts.iter().find(|c| !c.is_done()).cloned()
    }
}
