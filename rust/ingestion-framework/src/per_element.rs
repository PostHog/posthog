//! Port of `per-element-step.ts`.

use std::future::Future;
use std::sync::{Arc, Mutex};

use futures::stream::{FuturesOrdered, StreamExt};

use crate::steps::{ChunkProcessingStep, ProcessingStep};
use crate::sync::FifoLimiter;

/// `join_all` with the output sized up front. Above `JOIN_ALL_SMALL`, `join_all` grows its output
/// one push at a time, which copies a chunk of large results on every growth. Poll order is the same.
async fn join_all_presized<F: Future>(runs: Vec<F>) -> Vec<F::Output> {
    if runs.len() <= JOIN_ALL_SMALL {
        return futures::future::join_all(runs).await;
    }
    let mut results = Vec::with_capacity(runs.len());
    let mut ordered: FuturesOrdered<F> = runs.into_iter().collect();
    while let Some(result) = ordered.next().await {
        results.push(result);
    }
    results
}

/// Mirrors `futures_util::future::join_all::SMALL`.
const JOIN_ALL_SMALL: usize = 30;

/// Results keep input order. With `max_concurrency`, values start FIFO like `concurrently`. The
/// steps run inside the one chunk-step future, not as tasks, as Node runs them on one event loop.
/// The first error fails the chunk, as `Promise.all` rejects. Nothing cancels the other values in
/// Node, so they run to the end, but here the chunk step returns only after they end.
/// Panics on `Some(0)`, as Node's `pLimit(0)` throws.
pub fn per_element<T, U>(
    step: ProcessingStep<T, U>,
    max_concurrency: Option<usize>,
) -> ChunkProcessingStep<T, U>
where
    T: Send + 'static,
    U: Send + 'static,
{
    let limit = max_concurrency.map(FifoLimiter::new);
    let name = step.name().clone();
    ChunkProcessingStep::new(&name, move |values: Vec<T>| {
        let step = step.clone();
        let limit = limit.clone();
        let first_error: Arc<Mutex<Option<anyhow::Error>>> = Arc::default();
        // Every slot is taken here, in input order, before any step starts.
        let runs: Vec<_> = values
            .into_iter()
            .map(|value| {
                let permit = limit.as_ref().map(|limit| limit.acquire());
                let step = step.clone();
                let first_error = first_error.clone();
                async move {
                    let _permit = match permit {
                        Some(permit) => Some(permit.await),
                        None => None,
                    };
                    let result = step.call(value).await;
                    match result {
                        Ok(result) => Some(result),
                        Err(error) => {
                            first_error.lock().unwrap().get_or_insert(error);
                            None
                        }
                    }
                }
            })
            .collect();
        async move {
            let results = join_all_presized(runs).await;
            if let Some(error) = first_error.lock().unwrap().take() {
                return Err(error);
            }
            Ok(results
                .into_iter()
                .map(|result| result.expect("no error was recorded"))
                .collect())
        }
    })
}
