//! Port of `concurrently-grouping-chunk-pipeline.ts`.

use std::collections::{HashSet, VecDeque};
use std::hash::Hash;
use std::panic::AssertUnwindSafe;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use futures::future::BoxFuture;
use futures::FutureExt;
use indexmap::IndexMap;

use crate::chunk_pipeline::{process_sequentially, ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, ResultWithContext};
use crate::errors::call_user_fn;
use crate::interleaving::{InterleavingCallbacks, InterleavingChunkPipeline, PullOutcome};
use crate::pipeline::DynPipeline;
use crate::sync::{FifoLimiter, ResettableSignal};

pub type GroupingFunction<T, K> = Arc<dyn Fn(&T) -> K + Send + Sync>;

pub type GroupChunkProcessor<T, U, C> = Arc<
    dyn Fn(ChunkResults<T, C>) -> BoxFuture<'static, anyhow::Result<ChunkResults<U, C>>>
        + Send
        + Sync,
>;

pub fn process_group_chunk_sequentially<T, U, C>(
    processor: DynPipeline<T, U, C>,
) -> GroupChunkProcessor<T, U, C>
where
    T: Send + 'static,
    U: Send + 'static,
    C: Send + 'static,
{
    Arc::new(move |items| {
        let processor = processor.clone();
        async move { process_sequentially(&processor, items).await }.boxed()
    })
}

struct GroupState<K, M, O, C> {
    // Insertion order matters: groups start in the order their keys first arrived.
    queues: IndexMap<K, Vec<ResultWithContext<M, C>>>,
    active: HashSet<K>,
    completed: VecDeque<ChunkResults<O, C>>,
    failure: Option<Arc<anyhow::Error>>,
}

struct GroupingShared<K, M, O, C> {
    processor: GroupChunkProcessor<M, O, C>,
    limit: Option<Arc<FifoLimiter>>,
    state: Mutex<GroupState<K, M, O, C>>,
    // Resolves when any group finishes, so a parked drain also wakes for a group started later.
    group_completed: ResettableSignal,
}

impl<K, M, O, C> GroupingShared<K, M, O, C>
where
    K: Hash + Eq + Clone + Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    C: Send + 'static,
{
    /// A completing group calls this for its own key. Every key left in `queues` then belongs to a
    /// running group, so their order no longer matters and the remove can be a `swap_remove`.
    fn start_group_if_queued(self: &Arc<Self>, state: &mut GroupState<K, M, O, C>, key: &K) {
        if state.active.contains(key) {
            return;
        }
        let Some(queue) = state.queues.swap_remove(key) else {
            return;
        };
        if queue.is_empty() {
            return;
        }
        self.spawn_group(state, key.clone(), queue);
    }

    /// One pass in key-arrival order, so a pull costs O(keys) and not O(keys²).
    fn start_available(self: &Arc<Self>, state: &mut GroupState<K, M, O, C>) {
        let mut ready = Vec::new();
        let GroupState { queues, active, .. } = &mut *state;
        queues.retain(|key, queue| {
            if active.contains(key) || queue.is_empty() {
                return true;
            }
            ready.push((key.clone(), std::mem::take(queue)));
            false
        });
        for (key, queue) in ready {
            self.spawn_group(state, key, queue);
        }
    }

    fn spawn_group(
        self: &Arc<Self>,
        state: &mut GroupState<K, M, O, C>,
        key: K,
        queue: Vec<ResultWithContext<M, C>>,
    ) {
        // The key is claimed now, so per-key order holds even while the group waits for a slot.
        state.active.insert(key.clone());

        let shared = self.clone();
        let permit = self.limit.as_ref().map(|limit| limit.acquire());
        tokio::spawn(async move {
            let _permit = match permit {
                Some(permit) => Some(permit.await),
                None => None,
            };
            // The processor call is guarded, so a panic before it returns its future fails the group.
            let outcome = AssertUnwindSafe(async { (shared.processor)(queue).await })
                .catch_unwind()
                .await;
            let mut state = shared.state.lock().unwrap();
            match outcome {
                Ok(Ok(results)) => {
                    state.completed.push_back(results);
                    state.active.remove(&key);
                    shared.start_group_if_queued(&mut state, &key);
                }
                Ok(Err(error)) => {
                    // Poison. The key stays active, so later items for it never start.
                    state.failure.get_or_insert_with(|| Arc::new(error));
                }
                Err(payload) => {
                    let message = crate::errors::panic_message(payload.as_ref());
                    state.failure.get_or_insert_with(|| {
                        Arc::new(anyhow::anyhow!("group processor panicked: {message}"))
                    });
                }
            }
            drop(state);
            shared.group_completed.resolve();
        });
    }
}

struct GroupingCallbacks<I, K, M, O, CI, CO> {
    grouping: GroupingFunction<M, K>,
    previous: DynChunkPipeline<I, M, CI, CO>,
    shared: Arc<GroupingShared<K, M, O, CO>>,
}

#[async_trait]
impl<I, K, M, O, CI, CO> InterleavingCallbacks<I, O, CI, CO>
    for GroupingCallbacks<I, K, M, O, CI, CO>
where
    I: Send + 'static,
    K: Hash + Eq + Clone + Send + Sync + 'static,
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
        // The grouping function is user code, so it runs before the lock is taken.
        let mut routed = Vec::with_capacity(previous.len());
        let mut non_ok = Vec::new();
        for item in previous {
            match &item.result {
                crate::results::Outcome::Ok(value) => {
                    let key = call_user_fn(
                        "Grouping function",
                        "groupingFn",
                        item.context.debug_context.as_ref(),
                        || (self.grouping)(value),
                    )?;
                    routed.push((key, item));
                }
                crate::results::Outcome::NonOk(_) => {
                    let (n, context) = item.into_ok().err().expect("non-OK");
                    non_ok.push(ResultWithContext::<M, CO>::non_ok(n, context));
                }
            }
        }
        let mut state = self.shared.state.lock().unwrap();
        for (key, item) in routed {
            state.queues.entry(key).or_default().push(item);
        }
        if !non_ok.is_empty() {
            state.completed.push_back(non_ok);
        }
        self.shared.start_available(&mut state);
        Ok(PullOutcome::Drain)
    }

    async fn on_process_pull(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        loop {
            let wait = {
                let mut state = self.shared.state.lock().unwrap();
                if let Some(completed) = state.completed.pop_front() {
                    return Ok(Some(completed));
                }
                // Surface a failure only after everything that completed has drained.
                if let Some(failure) = &state.failure {
                    return Err(crate::errors::shared_error(failure.clone()));
                }
                if state.active.is_empty() {
                    return Ok(None);
                }
                self.shared.group_completed.reset();
                self.shared.group_completed.wait()
            };
            wait.await;
        }
    }
}

pub struct ConcurrentlyGroupingChunkPipeline<I, K, M, O, CI, CO> {
    inner: Inner<I, K, M, O, CI, CO>,
}

type Inner<I, K, M, O, CI, CO> =
    InterleavingChunkPipeline<I, O, CI, CO, GroupingCallbacks<I, K, M, O, CI, CO>>;

impl<I, K, M, O, CI, CO> ConcurrentlyGroupingChunkPipeline<I, K, M, O, CI, CO>
where
    I: Send + 'static,
    K: Hash + Eq + Clone + Send + Sync + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn new(
        grouping: GroupingFunction<M, K>,
        processor: GroupChunkProcessor<M, O, CO>,
        previous: DynChunkPipeline<I, M, CI, CO>,
        max_concurrency: Option<usize>,
    ) -> Self {
        let shared = Arc::new(GroupingShared {
            processor,
            limit: max_concurrency.map(FifoLimiter::new),
            state: Mutex::new(GroupState {
                queues: IndexMap::new(),
                active: HashSet::new(),
                completed: VecDeque::new(),
                failure: None,
            }),
            group_completed: ResettableSignal::new(),
        });
        Self {
            inner: InterleavingChunkPipeline::new(Arc::new(GroupingCallbacks {
                grouping,
                previous,
                shared,
            })),
        }
    }
}

#[async_trait]
impl<I, K, M, O, CI, CO> ChunkPipeline<I, O, CI, CO>
    for ConcurrentlyGroupingChunkPipeline<I, K, M, O, CI, CO>
where
    I: Send + 'static,
    K: Hash + Eq + Clone + Send + Sync + 'static,
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
