//! `concurrently`, `sequentially`, and `filter_map` chunk combinators.

use super::processor::AsyncProcessor;
use crate::framework::result::{Outputs, StepResult};
use futures::stream::{self, StreamExt};

/// Process each item of a chunk concurrently, emitting results in **input (FIFO)
/// order** — Node's `concurrently` semantics. At most `max_concurrency` items are in
/// flight at once (`buffered` caps concurrency while preserving order).
///
/// `max_concurrency` is clamped to at least 1; pass `items.len()` for "unbounded".
pub async fn concurrently<P>(
    max_concurrency: usize,
    processor: &P,
    items: Vec<P::In>,
) -> Vec<StepResult<P::Out, P::Outputs>>
where
    P: AsyncProcessor,
{
    let max = max_concurrency.max(1);
    stream::iter(items)
        .map(|item| processor.process(item))
        .buffered(max)
        .collect()
        .await
}

/// Process each item strictly one at a time, in order. This is the async analog of the
/// default sync chain (`.step().step()`), provided for symmetry with [`concurrently`];
/// for sync steps, sequential composition *is* the default and needs no combinator.
pub async fn sequentially<P>(
    processor: &P,
    items: Vec<P::In>,
) -> Vec<StepResult<P::Out, P::Outputs>>
where
    P: AsyncProcessor,
{
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        out.push(processor.process(item).await);
    }
    out
}

/// Map every `Continue` value through `f` (which may itself return any verdict),
/// passing non-`Continue` verdicts through unchanged and positionally. This is the
/// synchronous core of Node's `filterMap` — "filter OK results, map them, pass the rest
/// through".
pub fn filter_map<T, U, O, F>(results: Vec<StepResult<T, O>>, f: F) -> Vec<StepResult<U, O>>
where
    O: Outputs,
    F: Fn(T) -> StepResult<U, O>,
{
    results
        .into_iter()
        .map(|r| match r {
            StepResult::Continue(v) => f(v),
            StepResult::Drop { reason } => StepResult::Drop { reason },
            StepResult::Dlq { reason } => StepResult::Dlq { reason },
            StepResult::Redirect {
                output,
                preserve_key,
            } => StepResult::Redirect {
                output,
                preserve_key,
            },
        })
        .collect()
}
