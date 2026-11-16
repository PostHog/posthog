use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use tokio::task::JoinHandle;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, ResultWithContext};
use crate::errors::join_error;
use crate::interleaving::{InterleavingCallbacks, InterleavingChunkPipeline, PullOutcome};
use crate::pipeline::DynPipeline;
use crate::sync::FifoLimiter;

enum Queued<O, C> {
    Ready(ResultWithContext<O, C>),
    Running(JoinHandle<anyhow::Result<ResultWithContext<O, C>>>),
}

struct ConcurrentCallbacks<I, M, O, CI, CO> {
    processor: DynPipeline<M, O, CO>,
    previous: DynChunkPipeline<I, M, CI, CO>,
    limit: Option<Arc<FifoLimiter>>,
    queue: Mutex<VecDeque<Queued<O, CO>>>,
}

#[async_trait]
impl<I, M, O, CI, CO> InterleavingCallbacks<I, O, CI, CO> for ConcurrentCallbacks<I, M, O, CI, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    fn on_feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements);
    }

    async fn on_source_pull(&self) -> anyhow::Result<PullOutcome<O, CO>> {
        let Some(previous) = self.previous.next().await? else {
            return Ok(PullOutcome::Drained);
        };
        let mut queue = self.queue.lock().unwrap();
        for item in previous {
            match item.into_ok() {
                Ok(ok) => {
                    let processor = self.processor.clone();
                    // Admission is reserved in pull order, so the head of the queue gets a slot first and emission order holds.
                    let permit = self.limit.as_ref().map(|limit| limit.acquire());
                    queue.push_back(Queued::Running(tokio::spawn(async move {
                        let _permit = match permit {
                            Some(permit) => Some(permit.await),
                            None => None,
                        };
                        processor.process(ok).await
                    })));
                }
                Err((non_ok, context)) => queue.push_back(Queued::Ready(
                    ResultWithContext::<M, CO>::non_ok(non_ok, context),
                )),
            }
        }
        Ok(PullOutcome::Drain)
    }

    async fn on_process_pull(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        let head = self.queue.lock().unwrap().pop_front();
        match head {
            None => Ok(None),
            Some(Queued::Ready(result)) => Ok(Some(vec![result])),
            Some(Queued::Running(handle)) => Ok(Some(vec![handle.await.map_err(join_error)??])),
        }
    }
}

pub struct ConcurrentChunkProcessingPipeline<I, M, O, CI, CO> {
    inner: Inner<I, M, O, CI, CO>,
}

type Inner<I, M, O, CI, CO> =
    InterleavingChunkPipeline<I, O, CI, CO, ConcurrentCallbacks<I, M, O, CI, CO>>;

impl<I, M, O, CI, CO> ConcurrentChunkProcessingPipeline<I, M, O, CI, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn new(
        processor: DynPipeline<M, O, CO>,
        previous: DynChunkPipeline<I, M, CI, CO>,
        max_concurrency: Option<usize>,
    ) -> Self {
        Self {
            inner: InterleavingChunkPipeline::new(Arc::new(ConcurrentCallbacks {
                processor,
                previous,
                limit: max_concurrency.map(FifoLimiter::new),
                queue: Mutex::new(VecDeque::new()),
            })),
        }
    }
}

#[async_trait]
impl<I, M, O, CI, CO> ChunkPipeline<I, O, CI, CO>
    for ConcurrentChunkProcessingPipeline<I, M, O, CI, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.inner.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        self.inner.next().await
    }
}
