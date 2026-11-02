//! Port of `fan-out-fan-in-chunk-pipeline.ts`.
//!
//! Node tags each sub-element context with a symbol-keyed parent token. Here the
//! sub-context type is `FanOutSubContext`, which holds an opaque parent id.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, PipelineContext, ResultWithContext};
use crate::interleaving::{InterleavingCallbacks, InterleavingChunkPipeline, PullOutcome};
use crate::results::{NonOk, Outcome};

/// Splits one element into its sub-elements. Must be cheap: heavy work belongs in the
/// sub-pipeline.
pub type FanOutFunction<T, S> = Arc<dyn Fn(&T) -> Vec<S> + Send + Sync>;

/// Folds the OK sub-results back into the original element.
pub type FanInFunction<T, SO, U> = Arc<dyn Fn(T, Vec<SO>) -> U + Send + Sync>;

/// The opaque token that ties a sub-element to its parent.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct FanOutParentRef(u64);

/// The context type of sub-elements: only the parent token.
#[derive(Debug, Clone)]
pub struct FanOutSubContext {
    parent: FanOutParentRef,
}

impl FanOutSubContext {
    pub fn parent(&self) -> FanOutParentRef {
        self.parent
    }
}

struct PendingParent<T, SO, C> {
    original: T,
    context: PipelineContext<C>,
    outstanding: usize,
    total: usize,
    collected: Vec<SO>,
    dlq_failures: Vec<(String, Option<Arc<anyhow::Error>>)>,
    dlq_last_step: Option<Arc<str>>,
    timed_out: Option<(String, Option<Arc<str>>)>,
}

struct FanState<T, SO, U, C> {
    pending: HashMap<FanOutParentRef, PendingParent<T, SO, C>>,
    ready: Vec<ResultWithContext<U, C>>,
}

struct FanCallbacks<I, T, S, SO, U, CI, C> {
    previous: DynChunkPipeline<I, T, CI, C>,
    fan_out: FanOutFunction<T, S>,
    sub: DynChunkPipeline<S, SO, FanOutSubContext, FanOutSubContext>,
    fan_in: FanInFunction<T, SO, U>,
    fan_out_name: Arc<str>,
    fan_in_name: Arc<str>,
    next_ref: AtomicU64,
    state: Mutex<FanState<T, SO, U, C>>,
}

impl<I, T, S, SO, U, CI, C> FanCallbacks<I, T, S, SO, U, CI, C> {
    fn complete_parent(
        &self,
        original: T,
        mut context: PipelineContext<C>,
        collected: Vec<SO>,
    ) -> ResultWithContext<U, C> {
        context.last_step = Some(self.fan_in_name.clone());
        ResultWithContext {
            result: Outcome::Ok((self.fan_in)(original, collected)),
            context,
        }
    }

    fn settle(
        &self,
        state: &mut FanState<T, SO, U, C>,
        sub: ResultWithContext<SO, FanOutSubContext>,
    ) -> anyhow::Result<()> {
        let parent_ref = sub.context.data.parent;
        let Some(parent) = state.pending.get_mut(&parent_ref) else {
            anyhow::bail!(
                "Fan-out/fan-in ({}/{}) received a sub-result without a known parent tag — the subpipeline must preserve context",
                self.fan_out_name,
                self.fan_in_name
            );
        };
        let mut sub_context = sub.context;
        parent
            .context
            .side_effects
            .append(&mut sub_context.side_effects);
        parent.context.warnings.append(&mut sub_context.warnings);
        match sub.result {
            Outcome::Ok(value) => parent.collected.push(value),
            Outcome::NonOk(NonOk::Timeout { reason }) => {
                if parent.timed_out.is_none() {
                    parent.timed_out = Some((reason, sub_context.last_step.clone()));
                }
            }
            Outcome::NonOk(NonOk::Dlq { reason, error }) => {
                parent.dlq_failures.push((reason, error));
                parent.dlq_last_step = sub_context.last_step.clone();
            }
            Outcome::NonOk(NonOk::Drop { .. }) => {}
            Outcome::NonOk(redirect @ NonOk::Redirect { .. }) => {
                tracing::warn!(
                    fan_out_step = %self.fan_out_name,
                    fan_in_step = %self.fan_in_name,
                    reason = redirect.reason(),
                    "Fan-out subpipeline produced a redirect result; excluding it"
                );
            }
        }
        parent.outstanding -= 1;
        if parent.outstanding > 0 {
            return Ok(());
        }
        let mut parent = state.pending.remove(&parent_ref).expect("present");
        let result = if let Some((reason, last_step)) = parent.timed_out.take() {
            parent.context.last_step = last_step;
            ResultWithContext {
                result: Outcome::NonOk(NonOk::Timeout {
                    reason: format!("fan-out sub-element timed out: {reason}"),
                }),
                context: parent.context,
            }
        } else if !parent.dlq_failures.is_empty() {
            let mut reasons: Vec<&str> = Vec::new();
            for (reason, _) in &parent.dlq_failures {
                if !reasons.contains(&reason.as_str()) {
                    reasons.push(reason);
                }
            }
            let reason = format!(
                "{}/{} fan-out sub-elements dlq'd: {}",
                parent.dlq_failures.len(),
                parent.total,
                reasons.join("; ")
            );
            let errors: Vec<String> = parent
                .dlq_failures
                .iter()
                .map(|(r, e)| {
                    e.as_ref()
                        .map(|e| e.to_string())
                        .unwrap_or_else(|| r.clone())
                })
                .collect();
            parent.context.last_step = parent.dlq_last_step.take();
            ResultWithContext {
                result: Outcome::NonOk(NonOk::Dlq {
                    error: Some(Arc::new(anyhow::anyhow!(
                        "{reason} [{}]",
                        errors.join(", ")
                    ))),
                    reason,
                }),
                context: parent.context,
            }
        } else {
            self.complete_parent(parent.original, parent.context, parent.collected)
        };
        state.ready.push(result);
        Ok(())
    }
}

#[async_trait]
impl<I, T, S, SO, U, CI, C> InterleavingCallbacks<I, U, CI, C>
    for FanCallbacks<I, T, S, SO, U, CI, C>
where
    I: Send + 'static,
    T: Send + 'static,
    S: Send + 'static,
    SO: Send + 'static,
    U: Send + 'static,
    CI: Send + 'static,
    C: Send + 'static,
{
    fn on_feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements);
    }

    async fn on_source_pull(&self) -> anyhow::Result<PullOutcome<U, C>> {
        let Some(previous) = self.previous.next().await? else {
            return Ok(PullOutcome::Drained);
        };
        let mut settled = Vec::new();
        let mut subs = Vec::new();
        {
            let mut state = self.state.lock().unwrap();
            for element in previous {
                let ok = match element.into_ok() {
                    Ok(ok) => ok,
                    Err((n, context)) => {
                        settled.push(ResultWithContext::<T, C>::non_ok(n, context));
                        continue;
                    }
                };
                let sub_values = (self.fan_out)(&ok.value);
                if sub_values.is_empty() {
                    settled.push(self.complete_parent(ok.value, ok.context, Vec::new()));
                    continue;
                }
                let parent_ref = FanOutParentRef(self.next_ref.fetch_add(1, Ordering::Relaxed));
                let total = sub_values.len();
                for sub in sub_values {
                    let mut context = PipelineContext::new(FanOutSubContext { parent: parent_ref });
                    context.debug_context = ok.context.debug_context.clone();
                    context.budget = ok.context.budget.clone();
                    subs.push(OkResultWithContext {
                        value: sub,
                        context,
                    });
                }
                state.pending.insert(
                    parent_ref,
                    PendingParent {
                        original: ok.value,
                        context: ok.context,
                        outstanding: total,
                        total,
                        collected: Vec::new(),
                        dlq_failures: Vec::new(),
                        dlq_last_step: None,
                        timed_out: None,
                    },
                );
            }
        }
        let fed = !subs.is_empty();
        if fed {
            self.sub.feed(subs);
        }
        if !settled.is_empty() {
            return Ok(PullOutcome::Emit(settled));
        }
        if !fed {
            return Ok(PullOutcome::Emit(Vec::new()));
        }
        Ok(PullOutcome::Drain)
    }

    async fn on_process_pull(&self) -> anyhow::Result<Option<ChunkResults<U, C>>> {
        loop {
            {
                let mut state = self.state.lock().unwrap();
                if !state.ready.is_empty() {
                    return Ok(Some(std::mem::take(&mut state.ready)));
                }
            }
            let Some(sub_results) = self.sub.next().await? else {
                let pending = self.state.lock().unwrap().pending.len();
                if pending > 0 {
                    anyhow::bail!(
                        "Fan-out/fan-in ({}/{}) subpipeline drained with {} parent(s) still pending — sub-results were lost",
                        self.fan_out_name,
                        self.fan_in_name,
                        pending
                    );
                }
                return Ok(None);
            };
            let mut state = self.state.lock().unwrap();
            for sub_result in sub_results {
                self.settle(&mut state, sub_result)?;
            }
        }
    }
}

/// Fans each OK element out into sub-elements, runs them through a sub-pipeline, and folds
/// the results back. N parents in, N results out; parents come out as they complete.
/// A DLQ sub-result fails its parent, a timeout times the parent out, a drop excludes the
/// sub-element, and a redirect is excluded with a warning.
pub struct FanOutFanInChunkPipeline<I, T, S, SO, U, CI, C> {
    inner: Inner<I, T, S, SO, U, CI, C>,
}

type Inner<I, T, S, SO, U, CI, C> =
    InterleavingChunkPipeline<I, U, CI, C, FanCallbacks<I, T, S, SO, U, CI, C>>;

impl<I, T, S, SO, U, CI, C> FanOutFanInChunkPipeline<I, T, S, SO, U, CI, C>
where
    I: Send + 'static,
    T: Send + 'static,
    S: Send + 'static,
    SO: Send + 'static,
    U: Send + 'static,
    CI: Send + 'static,
    C: Send + 'static,
{
    pub fn new(
        previous: DynChunkPipeline<I, T, CI, C>,
        fan_out_name: &str,
        fan_out: FanOutFunction<T, S>,
        sub: DynChunkPipeline<S, SO, FanOutSubContext, FanOutSubContext>,
        fan_in_name: &str,
        fan_in: FanInFunction<T, SO, U>,
    ) -> Self {
        Self {
            inner: InterleavingChunkPipeline::new(Arc::new(FanCallbacks {
                previous,
                fan_out,
                sub,
                fan_in,
                fan_out_name: Arc::from(fan_out_name),
                fan_in_name: Arc::from(fan_in_name),
                next_ref: AtomicU64::new(0),
                state: Mutex::new(FanState {
                    pending: HashMap::new(),
                    ready: Vec::new(),
                }),
            })),
        }
    }
}

#[async_trait]
impl<I, T, S, SO, U, CI, C> ChunkPipeline<I, U, CI, C>
    for FanOutFanInChunkPipeline<I, T, S, SO, U, CI, C>
where
    I: Send + 'static,
    T: Send + 'static,
    S: Send + 'static,
    SO: Send + 'static,
    U: Send + 'static,
    CI: Send + 'static,
    C: Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.inner.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<U, C>>> {
        self.inner.next().await
    }
}
