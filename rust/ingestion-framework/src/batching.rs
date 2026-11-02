//! Port of `batching-pipeline.ts`.
//!
//! Node spreads the batch context into each element value (`TInput & CBatch`). Here a
//! sub-pipeline value is `WithBatch<T, CB>`: the value plus a shared batch context, with
//! `Deref` to the value. Node merges the caller's feed context into the batch context;
//! here it comes back as its own field on `BatchResult`.

use std::collections::{HashMap, HashSet, VecDeque};
use std::ops::{Deref, DerefMut};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use futures::future::BoxFuture;
use futures::FutureExt;

use crate::budget::BatchBudget;
use crate::chunk_pipeline::DynChunkPipeline;
use crate::context::{create_ok_context, ChunkResults, OkResultWithContext, ResultWithContext};
use crate::metrics::{BATCH_BUDGET_EXHAUSTED_COUNTER, BATCH_BUDGET_OVERRUN_HISTOGRAM};
use crate::pipeline::DynPipeline;
use crate::results::Outcome;
use crate::side_effects::SideEffect;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FeedRejectionKind {
    AtCapacity,
    BeforeBatchFailed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FeedResult {
    Ok,
    Rejected {
        kind: FeedRejectionKind,
        reason: String,
    },
}

impl FeedResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, FeedResult::Ok)
    }
}

#[derive(Debug)]
pub struct WithBatch<T, CB> {
    pub value: T,
    pub batch: Arc<CB>,
}

impl<T, CB> Deref for WithBatch<T, CB> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}

impl<T, CB> DerefMut for WithBatch<T, CB> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.value
    }
}

impl<T: Clone, CB> Clone for WithBatch<T, CB> {
    fn clone(&self) -> Self {
        Self {
            value: self.value.clone(),
            batch: self.batch.clone(),
        }
    }
}

pub struct BeforeBatchInput<T, CI> {
    pub elements: Vec<OkResultWithContext<T, CI>>,
    pub batch_id: u64,
}

/// A beforeBatch hook may enrich elements and build the batch context, but must return
/// exactly as many elements as it received, or `feed()` fails.
pub struct BeforeBatchOutput<T, CI, CB> {
    pub elements: Vec<OkResultWithContext<T, CI>>,
    pub batch_context: CB,
    pub batch_id: u64,
}

pub struct AfterBatchInput<O, CO, CB> {
    pub elements: ChunkResults<O, CO>,
    pub batch_context: Arc<CB>,
    pub batch_id: u64,
}

pub type AfterBatchOutput<O, CO, CB> = AfterBatchInput<O, CO, CB>;

pub struct BatchResult<O, CO, CB, CF> {
    pub elements: ChunkResults<O, CO>,
    pub batch_context: Arc<CB>,
    pub feed_context: CF,
    pub batch_id: u64,
    pub side_effects: Vec<SideEffect>,
}

#[derive(Debug, Clone, Copy)]
pub struct BatchingPipelineOptions {
    pub concurrent_batches: usize,
}

impl Default for BatchingPipelineOptions {
    fn default() -> Self {
        Self {
            concurrent_batches: 1,
        }
    }
}

// The overrun is the tail the checkpoints cannot cut, because they only stop work from
// starting. It includes afterBatch, which flushes the batch's writes.
fn record_budget_overrun(budget: &BatchBudget) {
    if !budget.exhausted() {
        return;
    }
    metrics::counter!(BATCH_BUDGET_EXHAUSTED_COUNTER).increment(1);
    if let Some(at) = budget.soft_at() {
        let overrun = tokio::time::Instant::now().saturating_duration_since(at);
        metrics::histogram!(BATCH_BUDGET_OVERRUN_HISTOGRAM).record(overrun.as_secs_f64());
    }
}

struct TrackedBatch<O, CO, CB, CF> {
    batch_context: Arc<CB>,
    feed_context: Option<CF>,
    budget: BatchBudget,
    message_ids: Vec<u64>,
    inflight: HashSet<u64>,
    results: HashMap<u64, ResultWithContext<O, CO>>,
    before_side_effects: Vec<SideEffect>,
}

struct BatchingState<O, CO, CB, CF> {
    next_batch_id: u64,
    next_message_id: u64,
    batches: HashMap<u64, TrackedBatch<O, CO, CB, CF>>,
    message_to_batch: HashMap<u64, u64>,
    completed: VecDeque<BatchResult<O, CO, CB, CF>>,
}

pub struct BatchingPipeline<T, O, CI, CO, CB, CF> {
    sub: DynChunkPipeline<WithBatch<T, CB>, O, CI, CO>,
    before: DynPipeline<BeforeBatchInput<T, CI>, BeforeBatchOutput<T, CI, CB>, ()>,
    after: DynPipeline<AfterBatchInput<O, CO, CB>, AfterBatchOutput<O, CO, CB>, ()>,
    options: BatchingPipelineOptions,
    state: Mutex<BatchingState<O, CO, CB, CF>>,
    // Incremented in the same critical section that registers a batch and feeds it, so the
    // pump can tell a feed that raced its pull from messages that vanished.
    feed_epoch: AtomicU64,
    // Concurrent callers must not interleave inside the stages, which assume one caller.
    // tokio's Mutex is fair (FIFO), like `pLimit(1)`.
    feed_lock: tokio::sync::Mutex<()>,
    // The pump's work in progress lives under the pump lock, not in the `next()` future.
    // A dropped `next()` then loses nothing: the next call resumes the stored pull, the
    // results not yet routed, and the afterBatch run.
    pump: tokio::sync::Mutex<PumpState<O, CO, CB, CF>>,
}

type SubPull<O, CO> = BoxFuture<'static, anyhow::Result<Option<ChunkResults<O, CO>>>>;
type AfterRun<O, CO, CB> =
    BoxFuture<'static, anyhow::Result<ResultWithContext<AfterBatchOutput<O, CO, CB>, ()>>>;

struct PendingPull<O, CO> {
    epoch: u64,
    future: SubPull<O, CO>,
}

struct RunningAfter<O, CO, CB, CF> {
    batch_id: u64,
    batch: TrackedBatch<O, CO, CB, CF>,
    future: AfterRun<O, CO, CB>,
}

struct PumpState<O, CO, CB, CF> {
    pull: Option<PendingPull<O, CO>>,
    unrouted: VecDeque<ResultWithContext<O, CO>>,
    after: Option<RunningAfter<O, CO, CB, CF>>,
}

impl<T, O, CI, CO, CB, CF> BatchingPipeline<T, O, CI, CO, CB, CF>
where
    T: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
    CB: Send + Sync + 'static,
    CF: Send + 'static,
{
    pub fn new(
        sub: DynChunkPipeline<WithBatch<T, CB>, O, CI, CO>,
        before: DynPipeline<BeforeBatchInput<T, CI>, BeforeBatchOutput<T, CI, CB>, ()>,
        after: DynPipeline<AfterBatchInput<O, CO, CB>, AfterBatchOutput<O, CO, CB>, ()>,
        options: BatchingPipelineOptions,
    ) -> Self {
        Self {
            sub,
            before,
            after,
            options,
            state: Mutex::new(BatchingState {
                next_batch_id: 0,
                next_message_id: 0,
                batches: HashMap::new(),
                message_to_batch: HashMap::new(),
                completed: VecDeque::new(),
            }),
            feed_epoch: AtomicU64::new(0),
            feed_lock: tokio::sync::Mutex::new(()),
            pump: tokio::sync::Mutex::new(PumpState {
                pull: None,
                unrouted: VecDeque::new(),
                after: None,
            }),
        }
    }

    pub async fn feed(
        &self,
        elements: Vec<OkResultWithContext<T, CI>>,
        feed_context: CF,
        budget: Option<BatchBudget>,
    ) -> anyhow::Result<FeedResult> {
        let _guard = self.feed_lock.lock().await;
        let budget = budget.unwrap_or_else(BatchBudget::unlimited);

        // An empty feed could never complete, so it registers nothing and runs no hooks.
        if elements.is_empty() {
            return Ok(FeedResult::Ok);
        }

        let batch_id = {
            let mut state = self.state.lock().unwrap();
            if state.batches.len() >= self.options.concurrent_batches {
                return Ok(FeedResult::Rejected {
                    kind: FeedRejectionKind::AtCapacity,
                    reason: format!(
                        "at concurrent batch capacity ({})",
                        self.options.concurrent_batches
                    ),
                });
            }
            let id = state.next_batch_id;
            state.next_batch_id += 1;
            id
        };

        let fed_count = elements.len();
        let before = self
            .before
            .process(create_ok_context(
                BeforeBatchInput { elements, batch_id },
                (),
            ))
            .await?;
        let before_side_effects;
        let output = match before.result {
            Outcome::Ok(output) => {
                before_side_effects = before.context.side_effects;
                output
            }
            Outcome::NonOk(_) => {
                return Ok(FeedResult::Rejected {
                    kind: FeedRejectionKind::BeforeBatchFailed,
                    reason: format!("beforeBatch hook returned non-ok result for batch {batch_id}"),
                })
            }
        };

        // A changed element count would leave a batch that never completes. That is a broken
        // invariant, not an outcome, so it fails before anything is registered.
        if output.elements.len() != fed_count {
            anyhow::bail!(
                "batching_pipeline beforeBatch changed element count ({} -> {}) for batch {}",
                fed_count,
                output.elements.len(),
                batch_id
            );
        }

        let batch_context = Arc::new(output.batch_context);
        let mut state = self.state.lock().unwrap();
        let mut message_ids = Vec::with_capacity(fed_count);
        let mut inflight = HashSet::with_capacity(fed_count);
        let tagged: Vec<_> = output
            .elements
            .into_iter()
            .map(|element| {
                let message_id = state.next_message_id;
                state.next_message_id += 1;
                message_ids.push(message_id);
                inflight.insert(message_id);
                state.message_to_batch.insert(message_id, batch_id);
                let mut context = element.context;
                context.message_id = Some(message_id);
                context.budget = Some(budget.clone());
                OkResultWithContext {
                    value: WithBatch {
                        value: element.value,
                        batch: batch_context.clone(),
                    },
                    context,
                }
            })
            .collect();
        state.batches.insert(
            batch_id,
            TrackedBatch {
                batch_context,
                feed_context: Some(feed_context),
                budget,
                message_ids,
                inflight,
                results: HashMap::new(),
                before_side_effects,
            },
        );
        self.feed_epoch.fetch_add(1, Ordering::SeqCst);
        self.sub.feed(tagged);
        Ok(FeedResult::Ok)
    }

    /// Cancel-safe: a dropped call keeps its pull, its unrouted results and its afterBatch
    /// run in the pipeline, and the next call resumes them.
    pub async fn next(&self) -> anyhow::Result<Option<BatchResult<O, CO, CB, CF>>> {
        let mut pump = self.pump.lock().await;
        self.pump(&mut pump).await
    }

    async fn pump(
        &self,
        pump: &mut PumpState<O, CO, CB, CF>,
    ) -> anyhow::Result<Option<BatchResult<O, CO, CB, CF>>> {
        loop {
            // Finish an afterBatch run first. A dropped call may have left one.
            if let Some(running) = pump.after.as_mut() {
                let after = running.future.as_mut().await;
                let running = pump.after.take().expect("present");
                self.complete_batch(running, after)?;
            }

            while let Some(result) = pump.unrouted.pop_front() {
                if let Some(running) = self.route(result)? {
                    pump.after = Some(running);
                    break;
                }
            }
            if pump.after.is_some() {
                continue;
            }

            // Node returns a completed batch only after it routed the whole chunk.
            if let Some(done) = self.state.lock().unwrap().completed.pop_front() {
                return Ok(Some(done));
            }

            if pump.pull.is_none() {
                let sub = self.sub.clone();
                pump.pull = Some(PendingPull {
                    epoch: self.feed_epoch.load(Ordering::SeqCst),
                    future: async move { sub.next().await }.boxed(),
                });
            }
            let pulled = pump.pull.as_mut().expect("present").future.as_mut().await;
            let epoch_at_pull = pump.pull.take().expect("present").epoch;
            let Some(results) = pulled? else {
                let (batches, messages) = {
                    let state = self.state.lock().unwrap();
                    (state.batches.len(), state.message_to_batch.len())
                };
                if batches > 0 {
                    // A feed that landed during an empty pull is picked up by a retry.
                    if self.feed_epoch.load(Ordering::SeqCst) != epoch_at_pull {
                        continue;
                    }
                    anyhow::bail!(
                        "batching_pipeline sub-pipeline returned null with {batches} in-flight batches and {messages} in-flight messages"
                    );
                }
                return Ok(None);
            };
            pump.unrouted.extend(results);
        }
    }

    fn route(
        &self,
        result: ResultWithContext<O, CO>,
    ) -> anyhow::Result<Option<RunningAfter<O, CO, CB, CF>>> {
        let mut state = self.state.lock().unwrap();
        let message_id = result.context.message_id.ok_or_else(|| {
            anyhow::anyhow!("batching_pipeline received result without messageId")
        })?;
        let Some(batch_id) = state.message_to_batch.get(&message_id).copied() else {
            anyhow::bail!("batching_pipeline received result with unknown messageId {message_id}");
        };
        let Some(batch) = state.batches.get_mut(&batch_id) else {
            anyhow::bail!(
                "batching_pipeline has batchId mapping but batch {batch_id} is missing for messageId {message_id}"
            );
        };
        batch.inflight.remove(&message_id);
        batch.results.insert(message_id, result);
        if !batch.inflight.is_empty() {
            return Ok(None);
        }
        let mut batch = state.batches.remove(&batch_id).expect("present");
        for id in &batch.message_ids {
            state.message_to_batch.remove(id);
        }
        drop(state);
        let ordered: Vec<_> = batch
            .message_ids
            .iter()
            .map(|id| {
                batch
                    .results
                    .remove(id)
                    .expect("every message has a result")
            })
            .collect();
        let after = self.after.clone();
        let input = create_ok_context(
            AfterBatchInput {
                elements: ordered,
                batch_context: batch.batch_context.clone(),
                batch_id,
            },
            (),
        );
        Ok(Some(RunningAfter {
            batch_id,
            batch,
            future: async move { after.process(input).await }.boxed(),
        }))
    }

    fn complete_batch(
        &self,
        running: RunningAfter<O, CO, CB, CF>,
        after: anyhow::Result<ResultWithContext<AfterBatchOutput<O, CO, CB>, ()>>,
    ) -> anyhow::Result<()> {
        let RunningAfter {
            batch_id,
            mut batch,
            ..
        } = running;
        let after = after?;
        record_budget_overrun(&batch.budget);
        let Outcome::Ok(after_output) = after.result else {
            anyhow::bail!(
                "batching_pipeline afterBatch hook returned non-ok result for batch {batch_id}"
            );
        };
        let mut side_effects = std::mem::take(&mut batch.before_side_effects);
        side_effects.extend(after.context.side_effects);
        self.state.lock().unwrap().completed.push_back(BatchResult {
            elements: after_output.elements,
            batch_context: batch.batch_context,
            feed_context: batch.feed_context.take().expect("set at feed"),
            batch_id,
            side_effects,
        });
        Ok(())
    }
}
