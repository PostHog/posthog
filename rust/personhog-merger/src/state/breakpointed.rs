use async_trait::async_trait;
use std::sync::Arc;
use tokio::sync::{Mutex, Notify};

use crate::state::{MergeState, MergeStateRepository, MergeStep};
use crate::types::ApiResult;

/// Identifies a specific operation on the repository.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RepositoryOperation {
    Get { target_person_uuid: String },
    Set { target_person_uuid: String, step: MergeStep },
    Delete { target_person_uuid: String },
}

/// A breakpoint that fires before a repository operation.
/// Uses Notify which can be cloned and awaited without holding the lock.
pub struct OperationBreakpoint {
    pub operation: RepositoryOperation,
    notify: Arc<Notify>,
}

impl OperationBreakpoint {
    pub fn new(operation: RepositoryOperation) -> Self {
        Self {
            operation,
            notify: Arc::new(Notify::new()),
        }
    }

    pub fn before_get(target_person_uuid: &str) -> Self {
        Self::new(RepositoryOperation::Get {
            target_person_uuid: target_person_uuid.to_string(),
        })
    }

    pub fn before_set(target_person_uuid: &str, step: MergeStep) -> Self {
        Self::new(RepositoryOperation::Set {
            target_person_uuid: target_person_uuid.to_string(),
            step,
        })
    }

    pub fn before_delete(target_person_uuid: &str) -> Self {
        Self::new(RepositoryOperation::Delete {
            target_person_uuid: target_person_uuid.to_string(),
        })
    }

    /// Complete this breakpoint, allowing waiters to proceed.
    pub fn complete(&self) {
        self.notify.notify_one();
    }

    /// Get a clone of the notify handle for waiting.
    fn get_notify(&self) -> Arc<Notify> {
        self.notify.clone()
    }
}

/// A repository wrapper that pauses at breakpoints before operations.
/// Useful for testing race conditions and timing-dependent behavior.
pub struct BreakpointedRepository<R: MergeStateRepository> {
    inner: R,
    breakpoints: Arc<Mutex<Vec<OperationBreakpoint>>>,
}

impl<R: MergeStateRepository> BreakpointedRepository<R> {
    pub fn new(inner: R) -> Self {
        Self {
            inner,
            breakpoints: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Add a breakpoint that will pause execution before the matching operation.
    pub async fn add_breakpoint(&self, breakpoint: OperationBreakpoint) {
        self.breakpoints.lock().await.push(breakpoint);
    }

    /// Complete a breakpoint, allowing the paused operation to proceed.
    pub async fn complete_breakpoint(&self, operation: &RepositoryOperation) {
        let breakpoints = self.breakpoints.lock().await;
        if let Some(bp) = breakpoints.iter().find(|bp| &bp.operation == operation) {
            bp.complete();
        }
    }

    /// Complete all pending breakpoints.
    pub async fn complete_all_breakpoints(&self) {
        let breakpoints = self.breakpoints.lock().await;
        for bp in breakpoints.iter() {
            bp.complete();
        }
    }

    async fn wait_for_breakpoint(&self, operation: &RepositoryOperation) {
        let notify = {
            let breakpoints = self.breakpoints.lock().await;
            breakpoints
                .iter()
                .find(|bp| &bp.operation == operation)
                .map(|bp| bp.get_notify())
        };

        if let Some(notify) = notify {
            notify.notified().await;
        }
    }
}

#[async_trait]
impl<R: MergeStateRepository> MergeStateRepository for BreakpointedRepository<R> {
    async fn get(&self, target_person_uuid: &str) -> ApiResult<Option<MergeState>> {
        let operation = RepositoryOperation::Get {
            target_person_uuid: target_person_uuid.to_string(),
        };
        self.wait_for_breakpoint(&operation).await;
        self.inner.get(target_person_uuid).await
    }

    async fn set(&self, state: MergeState) -> ApiResult<()> {
        let operation = RepositoryOperation::Set {
            target_person_uuid: state.target_person_uuid.clone(),
            step: state.step,
        };
        self.wait_for_breakpoint(&operation).await;
        self.inner.set(state).await
    }

    async fn delete(&self, target_person_uuid: &str) -> ApiResult<()> {
        let operation = RepositoryOperation::Delete {
            target_person_uuid: target_person_uuid.to_string(),
        };
        self.wait_for_breakpoint(&operation).await;
        self.inner.delete(target_person_uuid).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::InMemoryMergeStateRepository;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn test_breakpointed_repository_pauses_on_set() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));

        // Add breakpoint before set with TargetMarked step
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "person-1",
            MergeStep::TargetMarked,
        ))
        .await;

        let repo_clone = repo.clone();
        let handle = tokio::spawn(async move {
            let mut state = MergeState::new(
                "person-1".to_string(),
                "target".to_string(),
                vec![],
                1000,
            );
            state.step = MergeStep::TargetMarked;
            repo_clone.set(state).await.unwrap();
        });

        // Give the task time to reach the breakpoint
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Task should still be running (blocked at breakpoint)
        assert!(!handle.is_finished());

        // Complete the breakpoint
        repo.complete_breakpoint(&RepositoryOperation::Set {
            target_person_uuid: "person-1".to_string(),
            step: MergeStep::TargetMarked,
        })
        .await;

        // Task should complete
        timeout(Duration::from_millis(100), handle)
            .await
            .expect("Task should complete")
            .unwrap();
    }

    #[tokio::test]
    async fn test_breakpointed_repository_controls_operation_order() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));
        let order = Arc::new(Mutex::new(Vec::new()));

        // Add breakpoints for two different operations
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "person-1",
            MergeStep::Started,
        ))
        .await;
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "person-2",
            MergeStep::Started,
        ))
        .await;

        let repo1 = repo.clone();
        let order1 = order.clone();
        let task1 = tokio::spawn(async move {
            let state = MergeState::new(
                "person-1".to_string(),
                "target-1".to_string(),
                vec![],
                1000,
            );
            repo1.set(state).await.unwrap();
            order1.lock().await.push(1);
        });

        let repo2 = repo.clone();
        let order2 = order.clone();
        let task2 = tokio::spawn(async move {
            let state = MergeState::new(
                "person-2".to_string(),
                "target-2".to_string(),
                vec![],
                2000,
            );
            repo2.set(state).await.unwrap();
            order2.lock().await.push(2);
        });

        // Give tasks time to reach breakpoints
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Complete task2's breakpoint first
        repo.complete_breakpoint(&RepositoryOperation::Set {
            target_person_uuid: "person-2".to_string(),
            step: MergeStep::Started,
        })
        .await;

        // Give task2 time to complete
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Then complete task1's breakpoint
        repo.complete_breakpoint(&RepositoryOperation::Set {
            target_person_uuid: "person-1".to_string(),
            step: MergeStep::Started,
        })
        .await;

        // Wait for both tasks
        timeout(Duration::from_millis(100), task1)
            .await
            .expect("Task 1 should complete")
            .unwrap();
        timeout(Duration::from_millis(100), task2)
            .await
            .expect("Task 2 should complete")
            .unwrap();

        // Verify order: task2 completed before task1
        assert_eq!(*order.lock().await, vec![2, 1]);
    }

    #[tokio::test]
    async fn test_breakpointed_repository_without_breakpoint_proceeds_normally() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // No breakpoints added - operations should proceed immediately
        let state = MergeState::new(
            "person-1".to_string(),
            "target".to_string(),
            vec![],
            1000,
        );
        repo.set(state).await.unwrap();

        let retrieved = repo.get("person-1").await.unwrap();
        assert!(retrieved.is_some());

        repo.delete("person-1").await.unwrap();
        let retrieved = repo.get("person-1").await.unwrap();
        assert!(retrieved.is_none());
    }

    #[tokio::test]
    async fn test_complete_all_breakpoints() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));
        let counter = Arc::new(AtomicUsize::new(0));

        // Add multiple breakpoints
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "person-1",
            MergeStep::Started,
        ))
        .await;
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "person-2",
            MergeStep::Started,
        ))
        .await;

        let repo1 = repo.clone();
        let counter1 = counter.clone();
        let task1 = tokio::spawn(async move {
            let state = MergeState::new(
                "person-1".to_string(),
                "target-1".to_string(),
                vec![],
                1000,
            );
            repo1.set(state).await.unwrap();
            counter1.fetch_add(1, Ordering::SeqCst);
        });

        let repo2 = repo.clone();
        let counter2 = counter.clone();
        let task2 = tokio::spawn(async move {
            let state = MergeState::new(
                "person-2".to_string(),
                "target-2".to_string(),
                vec![],
                2000,
            );
            repo2.set(state).await.unwrap();
            counter2.fetch_add(1, Ordering::SeqCst);
        });

        // Give tasks time to reach breakpoints
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert_eq!(counter.load(Ordering::SeqCst), 0);

        // Complete all breakpoints at once
        repo.complete_all_breakpoints().await;

        // Both tasks should complete
        timeout(Duration::from_millis(100), task1)
            .await
            .expect("Task 1 should complete")
            .unwrap();
        timeout(Duration::from_millis(100), task2)
            .await
            .expect("Task 2 should complete")
            .unwrap();

        assert_eq!(counter.load(Ordering::SeqCst), 2);
    }
}
