//! Port of `per-element-step.ts`.

use std::sync::{Arc, Mutex};

use crate::steps::{ChunkProcessingStep, ProcessingStep};
use crate::sync::FifoLimiter;

/// Runs a single-item step over every value of a chunk, as one chunk step. The framework
/// instruments a chunk step once per chunk, and an element step once per element. For a
/// cheap step, such as a header parse or a passthrough produce, the per-element cost is
/// most of the work.
///
/// Results keep input order. With `max_concurrency`, values start in input order (FIFO),
/// like `concurrently`. The steps run as futures of the one chunk-step future, not as
/// tasks, as Node runs them on one event loop.
///
/// A step that fails fails the chunk with the first error to occur, as `Promise.all`
/// rejects. The other values still run to the end, because nothing cancels them in Node.
/// Here the chunk step returns only after they end; Node rejects at once.
///
/// # Panics
///
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
            let results = futures::future::join_all(runs).await;
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
