//! A Node side effect is a `Promise`. An async function runs its body up to the first
//! `await` when it is called, and the rest runs on the event loop. `SideEffect::spawn`
//! keeps that: it polls the future once on the caller's thread, and only moves the
//! unfinished rest to a tokio task. So produce calls start in the order that the side
//! effects are created, as they do in Node. Dropping a `SideEffect` detaches the task, as
//! an unhandled Node promise does.

use std::future::Future;
use std::panic::AssertUnwindSafe;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};

use futures::future::BoxFuture;
use futures::FutureExt;
use tokio::task::JoinHandle;

enum State {
    Running(JoinHandle<anyhow::Result<()>>),
    Settled(Option<anyhow::Result<()>>),
}

pub struct SideEffect {
    state: State,
}

fn panic_error() -> anyhow::Error {
    anyhow::anyhow!("side effect task failed: panicked")
}

impl SideEffect {
    pub fn spawn<F>(fut: F) -> Self
    where
        F: Future<Output = anyhow::Result<()>> + Send + 'static,
    {
        let mut fut = Box::pin(fut);
        let mut cx = Context::from_waker(futures::task::noop_waker_ref());
        // A Node async function that throws before its first await rejects its promise. It
        // does not throw to the caller, so a panic here becomes a failed side effect.
        match std::panic::catch_unwind(AssertUnwindSafe(|| fut.as_mut().poll(&mut cx))) {
            Ok(Poll::Ready(result)) => Self::settled(result),
            // The task polls again with a real waker, so the no-op waker loses no wake-up.
            Ok(Poll::Pending) => Self {
                state: State::Running(tokio::spawn(fut)),
            },
            Err(_) => Self::settled(Err(panic_error())),
        }
    }

    fn settled(result: anyhow::Result<()>) -> Self {
        Self {
            state: State::Settled(Some(result)),
        }
    }

    pub fn resolved() -> Self {
        Self::settled(Ok(()))
    }

    pub fn rejected(error: anyhow::Error) -> Self {
        Self::settled(Err(error))
    }

    pub fn is_finished(&self) -> bool {
        match &self.state {
            State::Running(handle) => handle.is_finished(),
            State::Settled(_) => true,
        }
    }

    /// Returns the result if the work has finished, and `None` while it runs. After it
    /// returns `Some`, the side effect has no result left and waits as a success.
    pub fn try_take(&mut self) -> Option<anyhow::Result<()>> {
        match &mut self.state {
            State::Settled(result) => result.take(),
            State::Running(handle) => {
                if !handle.is_finished() {
                    return None;
                }
                // Unconstrained: a JoinHandle poll spends the task's coop budget, and a
                // prune of many handles would run it out and read finished tasks as pending.
                let result = match tokio::task::unconstrained(handle).now_or_never()? {
                    Ok(result) => result,
                    Err(join_error) => Err(join_failure(join_error)),
                };
                self.state = State::Settled(None);
                Some(result)
            }
        }
    }

    pub async fn wait(self) -> anyhow::Result<()> {
        match self.state {
            State::Settled(result) => result.unwrap_or(Ok(())),
            State::Running(handle) => match handle.await {
                Ok(result) => result,
                Err(join_error) => Err(join_failure(join_error)),
            },
        }
    }

    pub fn into_future(self) -> BoxFuture<'static, anyhow::Result<()>> {
        self.wait().boxed()
    }
}

fn join_failure(join_error: tokio::task::JoinError) -> anyhow::Error {
    anyhow::anyhow!("side effect task failed: {join_error}")
}

impl std::fmt::Debug for SideEffect {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SideEffect")
            .field("finished", &self.is_finished())
            .finish()
    }
}

pub trait SideEffectScheduler: Send + Sync {
    fn schedule(&self, side_effect: SideEffect);
}

/// Node removes a promise from its set when it settles. Here a settled side effect is
/// removed at the next `schedule()` that finds the set grown, or at `pending_count()`, so
/// the set stays proportional to the work that still runs.
///
/// Unlike Node, it keeps the first failure, as the `FailureLatchingPromiseScheduler` in the
/// metrics consumer does. A failure that settles before `wait_for_all()` is otherwise
/// lost, and the consumer would then store the offsets of a batch whose side effect failed.
#[derive(Default, Clone)]
pub struct PromiseScheduler {
    inner: Arc<Mutex<SchedulerState>>,
}

// Pruning runs when the set reaches this size, then at twice the size that survived the
// last prune. This keeps the cost of a schedule() constant on average.
const MIN_PRUNE_AT: usize = 64;

struct SchedulerState {
    pending: Vec<SideEffect>,
    prune_at: usize,
    failure: Option<Arc<anyhow::Error>>,
}

impl Default for SchedulerState {
    fn default() -> Self {
        Self {
            pending: Vec::new(),
            prune_at: MIN_PRUNE_AT,
            failure: None,
        }
    }
}

impl SchedulerState {
    fn latch(&mut self, error: anyhow::Error) {
        if self.failure.is_none() {
            self.failure = Some(Arc::new(error));
        }
    }

    fn prune(&mut self) {
        let mut failures = Vec::new();
        self.pending
            .retain_mut(|side_effect| match side_effect.try_take() {
                None => true,
                Some(Ok(())) => false,
                Some(Err(error)) => {
                    failures.push(error);
                    false
                }
            });
        for error in failures {
            self.latch(error);
        }
        self.prune_at = (self.pending.len() * 2).max(MIN_PRUNE_AT);
    }
}

impl PromiseScheduler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn pending_count(&self) -> usize {
        let mut state = self.inner.lock().unwrap();
        state.prune();
        state.pending.len()
    }

    /// Waits for the side effects that are pending now, as Node's `Promise.all` over the
    /// current set does. Returns the first failure, if any.
    pub async fn wait_for_all(&self) -> anyhow::Result<()> {
        let pending = std::mem::take(&mut self.inner.lock().unwrap().pending);
        for side_effect in pending {
            if let Err(error) = side_effect.wait().await {
                self.inner.lock().unwrap().latch(error);
            }
        }
        match self.inner.lock().unwrap().failure.take() {
            Some(error) => Err(crate::errors::shared_error(error)),
            None => Ok(()),
        }
    }

    pub async fn wait_for_all_settled(&self) {
        let _ = self.wait_for_all().await;
    }
}

impl SideEffectScheduler for PromiseScheduler {
    fn schedule(&self, mut side_effect: SideEffect) {
        let mut state = self.inner.lock().unwrap();
        // A side effect that settled on creation never enters the set, as a Node promise
        // that settles leaves it.
        match side_effect.try_take() {
            Some(Ok(())) => return,
            Some(Err(error)) => {
                state.latch(error);
                return;
            }
            None => {}
        }
        state.pending.push(side_effect);
        if state.pending.len() >= state.prune_at {
            state.prune();
        }
    }
}
