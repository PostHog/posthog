pub mod mock;
pub mod mock_apis;

use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::sync::oneshot;

pub use mock::{CallGuard, ExpectedCall, MockMethod};

// Re-export for convenience
#[allow(unused_imports)]
pub use std::sync::Arc;

/// A breakpoint that can be used to coordinate async operations in tests.
/// The `wait` future will block until `complete` is called.
pub struct Breakpoint<T = ()> {
    receiver: oneshot::Receiver<T>,
    sender: Option<oneshot::Sender<T>>,
}

impl<T> Breakpoint<T> {
    pub fn new() -> Self {
        let (sender, receiver) = oneshot::channel();
        Self {
            receiver,
            sender: Some(sender),
        }
    }

    /// Complete the breakpoint with a value, unblocking any waiters.
    pub fn complete(&mut self, value: T) {
        if let Some(sender) = self.sender.take() {
            // Ignore the result - we don't care if the receiver was dropped
            drop(sender.send(value));
        }
    }

    /// Returns a future that resolves when `complete` is called.
    pub fn wait(&mut self) -> BreakpointWait<'_, T> {
        BreakpointWait {
            receiver: &mut self.receiver,
        }
    }
}

impl<T> Default for Breakpoint<T> {
    fn default() -> Self {
        Self::new()
    }
}

pub struct BreakpointWait<'a, T> {
    receiver: &'a mut oneshot::Receiver<T>,
}

impl<T> Future for BreakpointWait<'_, T> {
    type Output = T;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.receiver).poll(cx) {
            Poll::Ready(Ok(value)) => Poll::Ready(value),
            Poll::Ready(Err(_)) => panic!("Breakpoint sender dropped without completing"),
            Poll::Pending => Poll::Pending,
        }
    }
}

/// A sequence executor that waits for a series of futures in order.
pub struct SequenceExecutor {
    waiters: Vec<Pin<Box<dyn Future<Output = ()> + Send>>>,
}

impl SequenceExecutor {
    pub fn new() -> Self {
        Self {
            waiters: Vec::new(),
        }
    }

    /// Add a future to wait for in the sequence.
    pub fn add<F>(&mut self, future: F)
    where
        F: Future<Output = ()> + Send + 'static,
    {
        self.waiters.push(Box::pin(future));
    }

    /// Run all waiters in sequence.
    pub async fn run(self) {
        for waiter in self.waiters {
            waiter.await;
        }
    }
}

impl Default for SequenceExecutor {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn test_breakpoint_completes_with_value() {
        let mut bp = Breakpoint::<i32>::new();
        bp.complete(42);
        let result = bp.wait().await;
        assert_eq!(result, 42);
    }

    #[tokio::test]
    async fn test_breakpoint_void_type() {
        let mut bp = Breakpoint::<()>::new();

        // Complete before waiting
        bp.complete(());

        let result = timeout(Duration::from_millis(100), bp.wait()).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_sequence_executor_runs_in_order() {
        let order = Arc::new(std::sync::Mutex::new(Vec::new()));

        let mut bp1 = Breakpoint::<()>::new();
        let mut bp2 = Breakpoint::<()>::new();
        let mut bp3 = Breakpoint::<()>::new();

        let order1 = order.clone();
        let order2 = order.clone();
        let order3 = order.clone();

        // Complete all breakpoints immediately for this test
        bp1.complete(());
        bp2.complete(());
        bp3.complete(());

        let mut executor = SequenceExecutor::new();
        executor.add(async move {
            bp1.wait().await;
            order1.lock().unwrap().push(1);
        });
        executor.add(async move {
            bp2.wait().await;
            order2.lock().unwrap().push(2);
        });
        executor.add(async move {
            bp3.wait().await;
            order3.lock().unwrap().push(3);
        });

        executor.run().await;

        assert_eq!(*order.lock().unwrap(), vec![1, 2, 3]);
    }

    #[tokio::test]
    async fn test_create_test_sequence_with_add() {
        let mut bp1 = Breakpoint::<()>::new();
        let mut bp2 = Breakpoint::<()>::new();
        let mut bp3 = Breakpoint::<()>::new();

        bp1.complete(());
        bp2.complete(());
        bp3.complete(());

        let finished = Arc::new(AtomicBool::new(false));
        let finished_clone = finished.clone();

        let mut executor = SequenceExecutor::new();
        executor.add(async move { bp1.wait().await });
        executor.add(async move { bp2.wait().await });
        executor.add(async move {
            bp3.wait().await;
            finished_clone.store(true, Ordering::SeqCst);
        });

        executor.run().await;
        assert!(finished.load(Ordering::SeqCst));
    }
}
