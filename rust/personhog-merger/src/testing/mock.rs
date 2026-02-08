//! Generic mock infrastructure with breakpoint support.
//!
//! Provides a `MockMethod` type that can be used to build mock implementations
//! of async traits with built-in support for:
//! - Queuing expected calls with return values
//! - Pausing execution until the test releases
//! - Capturing call arguments for assertions
//!
//! # Example
//!
//! ```ignore
//! struct MockApi {
//!     get_user: MockMethod<GetUserArgs, User>,
//! }
//!
//! // In test setup:
//! let mock = MockApi::new();
//! let call = mock.get_user.expect(User { name: "Alice" });
//!
//! // Start the operation being tested
//! let handle = spawn(async { service.do_something().await });
//!
//! // Wait for the call - this blocks until get_user is called
//! let guard = call.await;
//! assert_eq!(guard.user_id, 123);
//!
//! // Mock is paused here - can inspect intermediate state
//! // ...
//!
//! // Guard drop releases the mock to continue
//! drop(guard);
//!
//! // Or just let it go out of scope
//! ```

use std::collections::VecDeque;
use std::future::Future;
use std::ops::Deref;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};

use tokio::sync::oneshot;

/// Internal state for coordinating between mock and test.
struct ExpectationChannels<Args> {
    /// Receives args when the mock is called
    args_rx: oneshot::Receiver<Args>,
    /// Sends release signal when guard is dropped
    release_tx: Option<oneshot::Sender<()>>,
}

/// Held by the mock method to send args and wait for release.
struct MockSide<Args> {
    args_tx: oneshot::Sender<Args>,
    release_rx: oneshot::Receiver<()>,
}

/// A future that resolves when the expected call happens.
///
/// Await this to wait for the mock to be called. The returned `CallGuard`
/// contains the arguments passed to the mock and keeps the mock paused
/// until dropped or `release()` is called.
///
/// For convenience, use `complete().await` to wait and release immediately.
pub struct ExpectedCall<Args> {
    channels: Option<ExpectationChannels<Args>>,
}

impl<Args> ExpectedCall<Args> {
    /// Wait for the call, release the mock, and return the captured arguments.
    ///
    /// This is a convenience method equivalent to:
    /// ```ignore
    /// let guard = call.await;
    /// let args = guard.into_args();
    /// ```
    ///
    /// Use this when you want to verify arguments without holding the mock paused:
    /// ```ignore
    /// let args = call.complete().await;
    /// assert_eq!(args.distinct_id, "expected");
    /// ```
    pub async fn complete(self) -> Args {
        self.await.into_args()
    }
}

// ExpectedCall is Unpin because it doesn't contain self-referential data
impl<Args> Unpin for ExpectedCall<Args> {}

impl<Args> Future for ExpectedCall<Args> {
    type Output = CallGuard<Args>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let channels = this
            .channels
            .as_mut()
            .expect("ExpectedCall polled after completion");

        match Pin::new(&mut channels.args_rx).poll(cx) {
            Poll::Ready(Ok(args)) => {
                let channels = this.channels.take().unwrap();
                Poll::Ready(CallGuard {
                    args: Some(args),
                    release_tx: channels.release_tx,
                })
            }
            Poll::Ready(Err(_)) => panic!("Mock was dropped without being called"),
            Poll::Pending => Poll::Pending,
        }
    }
}

/// Guard that holds the call arguments and releases the mock when dropped.
///
/// The mock method that created this guard is paused until this guard is dropped
/// or `release()` is called. Use `Deref` to access the arguments directly.
pub struct CallGuard<Args> {
    args: Option<Args>,
    release_tx: Option<oneshot::Sender<()>>,
}

impl<Args> CallGuard<Args> {
    /// Explicitly release the mock to continue execution.
    /// This consumes the guard.
    pub fn release(self) {
        // Drop will send the release signal
    }

    /// Release the mock and return the captured arguments.
    /// This is useful when you want to verify the args after releasing.
    pub fn into_args(mut self) -> Args {
        self.args.take().expect("args already taken")
        // Drop sends the release signal
    }
}

impl<Args> Deref for CallGuard<Args> {
    type Target = Args;

    fn deref(&self) -> &Self::Target {
        self.args.as_ref().expect("args already taken")
    }
}

impl<Args> Drop for CallGuard<Args> {
    fn drop(&mut self) {
        if let Some(tx) = self.release_tx.take() {
            let _ = tx.send(());
        }
    }
}

/// Expectation stored in the mock method's queue.
struct QueuedExpectation<Args, Ret> {
    return_value: Ret,
    mock_side: MockSide<Args>,
}

/// A mock method that queues expected calls and pauses until released.
///
/// Each call to `expect()` adds an expectation to the queue. When the mock
/// is called via `call()`, it pops the next expectation, sends the arguments
/// to the waiting future, and pauses until the `CallGuard` is dropped.
pub struct MockMethod<Args, Ret> {
    expectations: Mutex<VecDeque<QueuedExpectation<Args, Ret>>>,
    name: String,
}

impl<Args, Ret> MockMethod<Args, Ret> {
    /// Create a new mock method with the given name (for error messages).
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            expectations: Mutex::new(VecDeque::new()),
            name: name.into(),
        }
    }

    /// Add an expected call with the given return value.
    ///
    /// Returns a future that resolves when the call happens. The future
    /// yields a `CallGuard` containing the actual arguments passed.
    /// The mock is paused until the guard is dropped.
    pub fn expect(&self, return_value: Ret) -> ExpectedCall<Args> {
        let (args_tx, args_rx) = oneshot::channel();
        let (release_tx, release_rx) = oneshot::channel();

        self.expectations
            .lock()
            .unwrap()
            .push_back(QueuedExpectation {
                return_value,
                mock_side: MockSide {
                    args_tx,
                    release_rx,
                },
            });

        ExpectedCall {
            channels: Some(ExpectationChannels {
                args_rx,
                release_tx: Some(release_tx),
            }),
        }
    }

    /// Called by the mock implementation when the method is invoked.
    ///
    /// This pops the next expectation, stores the arguments, notifies
    /// the waiting future, and pauses until the `CallGuard` is dropped.
    ///
    /// # Panics
    ///
    /// Panics if no expectations are queued.
    pub async fn call(&self, args: Args) -> Ret
    where
        Ret: Clone,
    {
        let expectation = self
            .expectations
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or_else(|| panic!("Unexpected call to mock method '{}'", self.name));

        // Send args to the waiting future
        drop(expectation.mock_side.args_tx.send(args));

        // Wait for the test to release us
        let _ = expectation.mock_side.release_rx.await;

        expectation.return_value
    }

    /// Check if there are any pending expectations.
    pub fn has_pending_expectations(&self) -> bool {
        !self.expectations.lock().unwrap().is_empty()
    }

    /// Get the number of pending expectations.
    pub fn pending_count(&self) -> usize {
        self.expectations.lock().unwrap().len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    const TEST_TIMEOUT: Duration = Duration::from_secs(2);

    #[derive(Debug, Clone, PartialEq)]
    struct TestArgs {
        id: i32,
        name: String,
    }

    #[derive(Debug, Clone, PartialEq)]
    struct TestResult {
        value: String,
    }

    #[tokio::test]
    async fn test_mock_method_basic_flow() {
        timeout(TEST_TIMEOUT, async {
            let mock: Arc<MockMethod<TestArgs, TestResult>> =
                Arc::new(MockMethod::new("test_method"));

            let expected_call = mock.expect(TestResult {
                value: "result".to_string(),
            });

            let mock_clone = mock.clone();
            let caller = tokio::spawn(async move {
                mock_clone
                    .call(TestArgs {
                        id: 42,
                        name: "test".to_string(),
                    })
                    .await
            });

            let guard = expected_call.await;
            assert_eq!(guard.id, 42);
            assert_eq!(guard.name, "test");
            drop(guard);

            let result = caller.await.expect("Join should succeed");
            assert_eq!(result.value, "result");
        })
        .await
        .expect("Test timed out");
    }

    #[tokio::test]
    async fn test_mock_method_pauses_until_guard_dropped() {
        timeout(TEST_TIMEOUT, async {
            let mock: Arc<MockMethod<TestArgs, TestResult>> =
                Arc::new(MockMethod::new("test_method"));
            let call_completed = Arc::new(std::sync::atomic::AtomicBool::new(false));
            let call_completed_clone = call_completed.clone();

            let expected_call = mock.expect(TestResult {
                value: "result".to_string(),
            });

            let mock_clone = mock.clone();
            let caller = tokio::spawn(async move {
                let result = mock_clone
                    .call(TestArgs {
                        id: 1,
                        name: "x".to_string(),
                    })
                    .await;
                call_completed_clone.store(true, std::sync::atomic::Ordering::SeqCst);
                result
            });

            let guard = expected_call.await;

            // Give some time - call should NOT complete yet
            tokio::time::sleep(Duration::from_millis(50)).await;
            assert!(
                !call_completed.load(std::sync::atomic::Ordering::SeqCst),
                "Call should be paused"
            );

            drop(guard);

            let _result = caller.await.expect("Join should succeed");
            assert!(
                call_completed.load(std::sync::atomic::Ordering::SeqCst),
                "Call should have completed"
            );
        })
        .await
        .expect("Test timed out");
    }

    #[tokio::test]
    async fn test_mock_method_multiple_calls() {
        timeout(TEST_TIMEOUT, async {
            let mock: Arc<MockMethod<TestArgs, TestResult>> =
                Arc::new(MockMethod::new("test_method"));

            let call1 = mock.expect(TestResult {
                value: "first".to_string(),
            });
            let call2 = mock.expect(TestResult {
                value: "second".to_string(),
            });

            assert_eq!(mock.pending_count(), 2);

            let mock_clone = mock.clone();
            let caller = tokio::spawn(async move {
                let r1 = mock_clone
                    .call(TestArgs {
                        id: 1,
                        name: "a".to_string(),
                    })
                    .await;
                let r2 = mock_clone
                    .call(TestArgs {
                        id: 2,
                        name: "b".to_string(),
                    })
                    .await;
                (r1, r2)
            });

            let guard1 = call1.await;
            assert_eq!(guard1.id, 1);
            drop(guard1);

            let guard2 = call2.await;
            assert_eq!(guard2.id, 2);
            drop(guard2);

            let (r1, r2) = caller.await.expect("Join should succeed");

            assert_eq!(r1.value, "first");
            assert_eq!(r2.value, "second");
            assert!(!mock.has_pending_expectations());
        })
        .await
        .expect("Test timed out");
    }

    #[tokio::test]
    async fn test_deref_to_args() {
        timeout(TEST_TIMEOUT, async {
            let mock: Arc<MockMethod<TestArgs, TestResult>> =
                Arc::new(MockMethod::new("test_method"));

            let expected_call = mock.expect(TestResult {
                value: "x".to_string(),
            });

            let mock_clone = mock.clone();
            let handle = tokio::spawn(async move {
                mock_clone
                    .call(TestArgs {
                        id: 99,
                        name: "deref_test".to_string(),
                    })
                    .await
            });

            let guard = expected_call.await;

            assert_eq!(guard.id, 99);
            assert_eq!(guard.name, "deref_test");

            drop(guard);
            let _result = handle.await.expect("Join should succeed");
        })
        .await
        .expect("Test timed out");
    }
}
