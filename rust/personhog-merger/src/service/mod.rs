use std::sync::Arc;

use crate::lock::{LockError, LockService};
use crate::process::{MergeContext, ProcessResult};
use crate::state::{MergeState, MergeStateRepository, StartedState};
use crate::types::{ApiResult, MergeResult, PersonDistinctIdsApi, PersonPropertiesApi};

#[cfg(test)]
mod sequence_tests;
#[cfg(test)]
mod tests;

/// Executes merge operations using a state machine pattern.
///
/// The executor runs a loop that:
/// 1. Acquires a lock for the merge
/// 2. Processes the current state
/// 3. Saves the new state
/// 4. Repeats until completion or failure
pub struct MergeExecutor<S: MergeStateRepository, L: LockService> {
    context: MergeContext,
    state_repository: Arc<S>,
    lock_service: Arc<L>,
}

impl<S: MergeStateRepository, L: LockService> MergeExecutor<S, L> {
    pub fn new(
        person_properties_api: Arc<dyn PersonPropertiesApi>,
        person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
        state_repository: Arc<S>,
        lock_service: Arc<L>,
    ) -> Self {
        Self {
            context: MergeContext::new(person_properties_api, person_distinct_ids_api),
            state_repository,
            lock_service,
        }
    }

    /// Start a new merge operation.
    pub async fn merge(
        &self,
        merge_id: &str,
        target_distinct_id: &str,
        source_distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<MergeResult> {
        let started_data = StartedState::new(
            merge_id.to_string(),
            target_distinct_id.to_string(),
            source_distinct_ids.to_vec(),
            version,
        );

        // Save initial state
        self.state_repository
            .set(MergeState::Started(started_data.clone()))
            .await?;

        // Run the state machine
        self.run(merge_id, MergeState::Started(started_data)).await
    }

    /// Resume all incomplete merges from the state repository.
    pub async fn resume_all(&self) -> ApiResult<Vec<(String, ApiResult<MergeResult>)>> {
        let incomplete_states = self.state_repository.list_incomplete().await?;

        let resume_futures: Vec<_> = incomplete_states
            .into_iter()
            .map(|state| {
                let merge_id = state.merge_id().to_string();
                async move {
                    let result = self.run(&merge_id, state).await;
                    (merge_id, result)
                }
            })
            .collect();

        Ok(futures::future::join_all(resume_futures).await)
    }

    /// Run the state machine loop until completion or failure.
    async fn run(&self, merge_id: &str, initial_state: MergeState) -> ApiResult<MergeResult> {
        let mut state = initial_state;

        loop {
            // Acquire lock before processing
            self.acquire_lock(merge_id).await?;

            // Process current state
            match state.process(&self.context).await {
                ProcessResult::Next(next_state) => {
                    // Save state and continue
                    self.state_repository.set(next_state.clone()).await?;
                    state = next_state;
                }
                ProcessResult::Completed(result, completed_state) => {
                    // Save completed state and return
                    if let Some(completed) = completed_state {
                        self.state_repository.set(completed).await?;
                    }
                    return Ok(result);
                }
                ProcessResult::Failed(error) => {
                    // Bubble up the error
                    return Err(error);
                }
            }
        }
    }

    async fn acquire_lock(&self, merge_id: &str) -> ApiResult<()> {
        self.lock_service
            .acquire(merge_id)
            .await
            .map_err(|e| match e {
                LockError::Timeout => format!("Lock acquisition timed out for merge {}", merge_id),
                LockError::LockLost => format!("Lock lost for merge {}", merge_id),
                LockError::AlreadyHeld => {
                    format!(
                        "Lock already held by another process for merge {}",
                        merge_id
                    )
                }
            })?;
        Ok(())
    }
}

// Keep the old name as an alias for backwards compatibility
pub type PersonMergeService<S, L> = MergeExecutor<S, L>;
