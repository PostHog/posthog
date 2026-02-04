use async_trait::async_trait;
use std::collections::HashMap;
use std::sync::Mutex;

use crate::types::ApiResult;

#[cfg(test)]
pub mod breakpointed;

/// Represents the current step in the merge process.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeStep {
    /// Initial state when merge is created
    Started,
    /// Target distinct ID has been marked as merging target
    TargetMarked,
    /// Source distinct IDs have been marked as merging source
    SourcesMarked,
    /// Properties have been copied from source persons to target
    PropertiesMerged,
    /// Distinct ID mappings have been updated
    DistinctIdsMerged,
    /// Target merge status has been cleared
    TargetCleared,
    /// Source persons have been deleted
    SourcesDeleted,
    /// Merge completed successfully
    Completed,
    /// Merge failed
    Failed,
}

/// State of a merge operation for a specific target person.
/// Contains all information needed to resume a merge operation after service restart.
#[derive(Debug, Clone, PartialEq)]
pub struct MergeState {
    /// The target person UUID that sources are being merged into.
    pub target_person_uuid: String,

    /// The target distinct ID used to initiate the merge.
    pub target_distinct_id: String,

    /// All source distinct IDs that were requested to be merged.
    pub source_distinct_ids: Vec<String>,

    /// Mapping of successfully marked source distinct IDs to their person UUIDs.
    /// Only populated after SourcesMarked step. Sources that had conflicts are not included.
    pub valid_sources: HashMap<String, String>,

    /// Deduplicated list of source person UUIDs to be merged.
    /// Derived from valid_sources but stored for quick access during property merge and deletion.
    pub source_person_uuids: Vec<String>,

    /// Current step in the merge process.
    pub step: MergeStep,

    /// Version number for the merge operation (used for conflict resolution).
    pub version: i64,

    /// Error message if the merge failed.
    pub error: Option<String>,
}

impl MergeState {
    pub fn new(
        target_person_uuid: String,
        target_distinct_id: String,
        source_distinct_ids: Vec<String>,
        version: i64,
    ) -> Self {
        Self {
            target_person_uuid,
            target_distinct_id,
            source_distinct_ids,
            valid_sources: HashMap::new(),
            source_person_uuids: Vec::new(),
            step: MergeStep::Started,
            version,
            error: None,
        }
    }

    /// Get the list of valid source distinct IDs (those that were successfully marked).
    pub fn valid_source_distinct_ids(&self) -> Vec<String> {
        self.valid_sources.keys().cloned().collect()
    }
}

/// Repository for storing merge state.
#[async_trait]
pub trait MergeStateRepository: Send + Sync {
    /// Get the current merge state for a target person.
    async fn get(&self, target_person_uuid: &str) -> ApiResult<Option<MergeState>>;

    /// Set the merge state for a target person.
    async fn set(&self, state: MergeState) -> ApiResult<()>;

    /// Delete the merge state for a target person.
    async fn delete(&self, target_person_uuid: &str) -> ApiResult<()>;
}

/// In-memory implementation of MergeStateRepository for testing.
pub struct InMemoryMergeStateRepository {
    states: Mutex<HashMap<String, MergeState>>,
}

impl InMemoryMergeStateRepository {
    pub fn new() -> Self {
        Self {
            states: Mutex::new(HashMap::new()),
        }
    }

    pub fn get_all_states(&self) -> HashMap<String, MergeState> {
        self.states.lock().unwrap().clone()
    }
}

impl Default for InMemoryMergeStateRepository {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl MergeStateRepository for InMemoryMergeStateRepository {
    async fn get(&self, target_person_uuid: &str) -> ApiResult<Option<MergeState>> {
        Ok(self.states.lock().unwrap().get(target_person_uuid).cloned())
    }

    async fn set(&self, state: MergeState) -> ApiResult<()> {
        self.states
            .lock()
            .unwrap()
            .insert(state.target_person_uuid.clone(), state);
        Ok(())
    }

    async fn delete(&self, target_person_uuid: &str) -> ApiResult<()> {
        self.states.lock().unwrap().remove(target_person_uuid);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_in_memory_repository_basic_operations() {
        let repo = InMemoryMergeStateRepository::new();

        // Initially empty
        let state = repo.get("person-1").await.unwrap();
        assert!(state.is_none());

        // Set state
        let merge_state = MergeState::new(
            "person-1".to_string(),
            "target-did".to_string(),
            vec!["source-did".to_string()],
            1000,
        );
        repo.set(merge_state.clone()).await.unwrap();

        // Get state
        let retrieved = repo.get("person-1").await.unwrap();
        assert_eq!(retrieved, Some(merge_state));

        // Update state
        let mut updated_state = MergeState::new(
            "person-1".to_string(),
            "target-did".to_string(),
            vec!["source-did".to_string()],
            1000,
        );
        updated_state.step = MergeStep::TargetMarked;
        repo.set(updated_state.clone()).await.unwrap();

        let retrieved = repo.get("person-1").await.unwrap();
        assert_eq!(retrieved.unwrap().step, MergeStep::TargetMarked);

        // Delete state
        repo.delete("person-1").await.unwrap();
        let state = repo.get("person-1").await.unwrap();
        assert!(state.is_none());
    }

    #[tokio::test]
    async fn test_in_memory_repository_multiple_states() {
        let repo = InMemoryMergeStateRepository::new();

        let state1 = MergeState::new(
            "person-1".to_string(),
            "target-1".to_string(),
            vec!["source-1".to_string()],
            1000,
        );
        let state2 = MergeState::new(
            "person-2".to_string(),
            "target-2".to_string(),
            vec!["source-2".to_string()],
            2000,
        );

        repo.set(state1.clone()).await.unwrap();
        repo.set(state2.clone()).await.unwrap();

        assert_eq!(repo.get("person-1").await.unwrap(), Some(state1));
        assert_eq!(repo.get("person-2").await.unwrap(), Some(state2));

        let all_states = repo.get_all_states();
        assert_eq!(all_states.len(), 2);
    }
}
