//! The pull is a boxed future in a field, not a spawned task, because a spawn per `next()` costs a cross-thread wake.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use futures::future::BoxFuture;
use futures::FutureExt;

use crate::context::{ChunkResults, OkResultWithContext};
use crate::errors::shared_error;
use crate::sync::ResettableSignal;

pub enum PullOutcome<O, C> {
    Emit(ChunkResults<O, C>),
    Drain,
    Drained,
}

#[async_trait]
pub trait InterleavingCallbacks<I, O, CI, CO>: Send + Sync + 'static {
    fn on_feed(&self, elements: Vec<OkResultWithContext<I, CI>>);
    async fn on_source_pull(&self) -> anyhow::Result<PullOutcome<O, CO>>;
    async fn on_process_pull(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>>;
}

type SubPull<O, CO> = BoxFuture<'static, anyhow::Result<Option<ChunkResults<O, CO>>>>;

pub struct InterleavingChunkPipeline<I, O, CI, CO, Cb> {
    callbacks: Arc<Cb>,
    new_input: ResettableSignal,
    sub_pending: Mutex<Option<SubPull<O, CO>>>,
    failure: Mutex<Option<Arc<anyhow::Error>>>,
    _marker: std::marker::PhantomData<fn(I, CI)>,
}

impl<I, O, CI, CO, Cb> InterleavingChunkPipeline<I, O, CI, CO, Cb>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
    Cb: InterleavingCallbacks<I, O, CI, CO>,
{
    pub fn new(callbacks: Arc<Cb>) -> Self {
        Self {
            callbacks,
            new_input: ResettableSignal::new(),
            sub_pending: Mutex::new(None),
            failure: Mutex::new(None),
            _marker: std::marker::PhantomData,
        }
    }

    pub fn callbacks(&self) -> &Arc<Cb> {
        &self.callbacks
    }

    pub fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.callbacks.on_feed(elements);
        self.new_input.resolve();
    }

    fn take_or_start_sub_pull(&self) -> SubPull<O, CO> {
        if let Some(pending) = self.sub_pending.lock().unwrap().take() {
            return pending;
        }
        let callbacks = self.callbacks.clone();
        async move { callbacks.on_process_pull().await }.boxed()
    }

    fn latch(&self, error: anyhow::Error) -> Arc<anyhow::Error> {
        let mut failure = self.failure.lock().unwrap();
        failure.get_or_insert_with(|| Arc::new(error)).clone()
    }

    pub async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        if self.failure.lock().unwrap().is_some() {
            return self.drain_then_reject().await;
        }

        loop {
            // Arm a fresh wake-up before the pull, so a stale feed signal does not pull the next chunk early.
            self.new_input.reset();

            let pulled = match self.callbacks.on_source_pull().await {
                Ok(pulled) => pulled,
                Err(error) => {
                    self.latch(error);
                    return self.drain_then_reject().await;
                }
            };
            let source_drained = match pulled {
                PullOutcome::Emit(chunk) => return Ok(Some(chunk)),
                PullOutcome::Drain => false,
                PullOutcome::Drained => true,
            };

            let mut pending = self.take_or_start_sub_pull();
            let wake = self.new_input.wait();
            let sub_result = tokio::select! {
                biased;
                result = &mut pending => result,
                _ = wake => {
                    *self.sub_pending.lock().unwrap() = Some(pending);
                    continue;
                }
            };

            match sub_result {
                Err(error) => {
                    let shared = self.latch(error);
                    return Err(shared_error(shared));
                }
                Ok(Some(chunk)) => return Ok(Some(chunk)),
                Ok(None) => {
                    if source_drained {
                        return Ok(None);
                    }
                }
            }
        }
    }

    async fn drain_then_reject(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        let pending = self.take_or_start_sub_pull();
        if let Ok(Some(chunk)) = pending.await {
            return Ok(Some(chunk));
        }
        let failure = self
            .failure
            .lock()
            .unwrap()
            .clone()
            .expect("failure is latched");
        Err(shared_error(failure))
    }
}
