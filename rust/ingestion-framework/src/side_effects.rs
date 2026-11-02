//! Side effects: work that outlives a step and drains with the batch.
//!
//! A Node side effect is a `Promise`, which runs from the moment it exists. A Rust future
//! runs only when something polls it, so `SideEffect::spawn` starts a tokio task to keep
//! the same eager semantics. Dropping a `SideEffect` detaches the task, as an unhandled
//! Node promise does.

use std::future::Future;
use std::sync::{Arc, Mutex};

use futures::future::BoxFuture;
use futures::FutureExt;
use tokio::task::JoinHandle;

pub struct SideEffect {
    handle: JoinHandle<anyhow::Result<()>>,
}

impl SideEffect {
    /// Starts the work now. The runtime must be a tokio runtime.
    pub fn spawn<F>(fut: F) -> Self
    where
        F: Future<Output = anyhow::Result<()>> + Send + 'static,
    {
        Self {
            handle: tokio::spawn(fut),
        }
    }

    /// A side effect that already succeeded.
    pub fn resolved() -> Self {
        Self::spawn(async { Ok(()) })
    }

    /// A side effect that already failed.
    pub fn rejected(error: anyhow::Error) -> Self {
        Self::spawn(async move { Err(error) })
    }

    pub fn is_finished(&self) -> bool {
        self.handle.is_finished()
    }

    /// Waits for the work. A panic in the task becomes an error.
    pub async fn wait(self) -> anyhow::Result<()> {
        match self.handle.await {
            Ok(result) => result,
            Err(join_error) => Err(anyhow::anyhow!("side effect task failed: {join_error}")),
        }
    }

    pub fn into_future(self) -> BoxFuture<'static, anyhow::Result<()>> {
        self.wait().boxed()
    }
}

impl std::fmt::Debug for SideEffect {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SideEffect")
            .field("finished", &self.handle.is_finished())
            .finish()
    }
}

/// Port of `PromiseSchedulerInterface`.
pub trait SideEffectScheduler: Send + Sync {
    fn schedule(&self, side_effect: SideEffect);
}

/// Port of `PromiseScheduler`: tracks scheduled work so a caller can wait for all of it.
///
/// It also keeps the first failure, like the `FailureLatchingPromiseScheduler` in the
/// metrics consumer, because a Rust task error is not reported anywhere else.
#[derive(Default, Clone)]
pub struct PromiseScheduler {
    inner: Arc<Mutex<SchedulerState>>,
}

#[derive(Default)]
struct SchedulerState {
    pending: Vec<SideEffect>,
    failure: Option<Arc<anyhow::Error>>,
}

impl PromiseScheduler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn pending_count(&self) -> usize {
        self.inner.lock().unwrap().pending.len()
    }

    /// Waits for all scheduled work. Returns the first failure, if any.
    pub async fn wait_for_all(&self) -> anyhow::Result<()> {
        loop {
            let pending = std::mem::take(&mut self.inner.lock().unwrap().pending);
            if pending.is_empty() {
                break;
            }
            for side_effect in pending {
                if let Err(error) = side_effect.wait().await {
                    let mut state = self.inner.lock().unwrap();
                    if state.failure.is_none() {
                        state.failure = Some(Arc::new(error));
                    }
                }
            }
        }
        match self.inner.lock().unwrap().failure.take() {
            Some(error) => Err(crate::errors::shared_error(error)),
            None => Ok(()),
        }
    }

    /// Waits for all scheduled work and ignores failures.
    pub async fn wait_for_all_settled(&self) {
        let _ = self.wait_for_all().await;
    }
}

impl SideEffectScheduler for PromiseScheduler {
    fn schedule(&self, side_effect: SideEffect) {
        self.inner.lock().unwrap().pending.push(side_effect);
    }
}
