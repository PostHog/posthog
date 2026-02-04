use std::collections::HashSet;
use std::sync::Arc;

use crate::state::{MergeState, MergeStateRepository, MergeStep};
use crate::types::{
    ApiResult, DistinctIdInfo, MergeConflict, MergeResult, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
};

#[cfg(test)]
mod tests;

/// Implements person merging with conflict detection for concurrent merge operations.
///
/// The merge process:
/// 1. Mark target as merging target
/// 2. Mark sources as merging source
/// 3. Copy properties from source persons to target
/// 4. Update distinct ID mappings
/// 5. Clear merge status on target
/// 6. Delete source persons
/// 7. Completed
pub struct PersonMergeService<S: MergeStateRepository> {
    person_properties_api: Arc<dyn PersonPropertiesApi>,
    person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
    state_repository: Arc<S>,
}

impl<S: MergeStateRepository> PersonMergeService<S> {
    pub fn new(
        person_properties_api: Arc<dyn PersonPropertiesApi>,
        person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
        state_repository: Arc<S>,
    ) -> Self {
        Self {
            person_properties_api,
            person_distinct_ids_api,
            state_repository,
        }
    }

    async fn update_state(&self, state: &mut MergeState, step: MergeStep) -> ApiResult<()> {
        state.step = step;
        self.state_repository.set(state.clone()).await
    }

    /// Get the target person UUID from state, returning an error if not set.
    /// This should only be called after the TargetMarked step.
    fn get_target_person_uuid(state: &MergeState) -> ApiResult<String> {
        state
            .target_person_uuid
            .clone()
            .ok_or_else(|| "target_person_uuid not set".into())
    }

    #[allow(dead_code)]
    async fn set_failed(&self, state: &mut MergeState, error: String) -> ApiResult<()> {
        state.step = MergeStep::Failed;
        state.error = Some(error);
        self.state_repository.set(state.clone()).await
    }

    /// Start a new merge operation.
    ///
    /// The merge process:
    /// 1. Mark target as merging target
    /// 2. Mark sources as merging source
    /// 3. Copy properties from source persons to target
    /// 4. Update distinct ID mappings
    /// 5. Clear merge status on target
    /// 6. Delete source persons
    /// 7. Completed
    ///
    /// All merge logic is implemented in the `resume_from_*` methods. This method
    /// creates the initial state and delegates to `resume_from_started`.
    ///
    /// # Arguments
    /// * `merge_id` - Unique identifier for this merge operation, used for tracking and resumption
    /// * `target_distinct_id` - The distinct ID to merge sources into
    /// * `source_distinct_ids` - The distinct IDs to merge into the target
    /// * `version` - Version number for idempotent operations
    pub async fn merge(
        &self,
        merge_id: &str,
        target_distinct_id: &str,
        source_distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<MergeResult> {
        // Create initial merge state
        let mut state = MergeState::new(
            merge_id.to_string(),
            target_distinct_id.to_string(),
            source_distinct_ids.to_vec(),
            version,
        );

        // Save initial state and delegate to the resume flow
        self.state_repository.set(state.clone()).await?;
        self.resume_from_started(&mut state).await
    }

    /// Resume all incomplete merges from the state repository concurrently.
    /// Returns a list of (merge_id, result) pairs for each resumed merge.
    pub async fn resume_all(&self) -> ApiResult<Vec<(String, ApiResult<MergeResult>)>> {
        let incomplete_states = self.state_repository.list_incomplete().await?;

        let resume_futures: Vec<_> = incomplete_states
            .into_iter()
            .map(|state| {
                let merge_id = state.merge_id.clone();
                async move {
                    let result = self.resume_merge(state).await;
                    (merge_id, result)
                }
            })
            .collect();

        Ok(futures::future::join_all(resume_futures).await)
    }

    /// Resume a single merge from its saved state.
    /// Assumes the underlying APIs are idempotent when called with the same version.
    pub async fn resume_merge(&self, mut state: MergeState) -> ApiResult<MergeResult> {
        match state.step {
            MergeStep::Started => {
                self.resume_from_started(&mut state).await
            }
            MergeStep::TargetMarked => {
                self.resume_from_target_marked(&mut state).await
            }
            MergeStep::SourcesMarked => {
                self.resume_from_sources_marked(&mut state).await
            }
            MergeStep::PropertiesMerged => {
                self.resume_from_properties_merged(&mut state).await
            }
            MergeStep::DistinctIdsMerged => {
                self.resume_from_distinct_ids_merged(&mut state).await
            }
            MergeStep::TargetCleared => {
                self.resume_from_target_cleared(&mut state).await
            }
            MergeStep::SourcesDeleted => {
                self.resume_from_sources_deleted(&mut state).await
            }
            MergeStep::Completed | MergeStep::Failed => {
                // Nothing to do - return current state as result
                let target_person_uuid = state.target_person_uuid.clone().unwrap_or_default();
                Ok(MergeResult {
                    merged: state
                        .valid_source_distinct_ids()
                        .into_iter()
                        .map(|distinct_id| DistinctIdInfo {
                            distinct_id,
                            person_uuid: target_person_uuid.clone(),
                        })
                        .collect(),
                    conflicts: Vec::new(),
                })
            }
        }
    }

    /// Resume merge from Started step - need to mark target and continue.
    async fn resume_from_started(&self, state: &mut MergeState) -> ApiResult<MergeResult> {
        // Re-mark target as merging (idempotent with same version)
        let target_result = self
            .person_distinct_ids_api
            .set_merging_target(&state.target_distinct_id, state.version)
            .await?;

        match target_result {
            SetMergingTargetResult::Ok { person_uuid, .. } => {
                // Update state with the person UUID
                state.target_person_uuid = Some(person_uuid);
            }
            SetMergingTargetResult::Conflict {
                distinct_id,
                person_uuid,
                merging_into_distinct_id,
            } => {
                // Target is being merged elsewhere - cannot resume
                self.set_failed(
                    state,
                    format!(
                        "Target {} is being merged into {}",
                        distinct_id, merging_into_distinct_id
                    ),
                )
                .await?;
                return Ok(MergeResult {
                    merged: Vec::new(),
                    conflicts: vec![MergeConflict::TargetIsSourceInAnotherMerge {
                        distinct_id,
                        person_uuid,
                        merging_into_distinct_id,
                    }],
                });
            }
        }

        self.update_state(state, MergeStep::TargetMarked).await?;
        self.resume_from_target_marked(state).await
    }

    /// Resume merge from TargetMarked step - need to mark sources and continue.
    async fn resume_from_target_marked(&self, state: &mut MergeState) -> ApiResult<MergeResult> {
        let mut conflicts: Vec<MergeConflict> = Vec::new();

        // Re-mark sources as merging (idempotent with same version)
        let source_results = self
            .person_distinct_ids_api
            .set_merging_source(&state.source_distinct_ids, state.version)
            .await?;

        let mut ok_results: Vec<(String, String)> = Vec::new();

        for result in source_results {
            match result {
                SetMergingSourceResult::Ok {
                    distinct_id,
                    person_uuid,
                } => {
                    ok_results.push((distinct_id, person_uuid));
                }
                SetMergingSourceResult::Conflict {
                    distinct_id,
                    person_uuid,
                    current_merge_status,
                } => match current_merge_status {
                    MergeStatus::MergingSource => {
                        conflicts.push(MergeConflict::SourceAlreadyMergingElsewhere {
                            distinct_id,
                            person_uuid,
                        });
                    }
                    MergeStatus::MergingTarget => {
                        conflicts.push(MergeConflict::SourceIsMergeTarget {
                            distinct_id,
                            person_uuid,
                        });
                    }
                },
            }
        }

        // Update state with valid sources
        state.valid_sources = ok_results
            .iter()
            .map(|(did, uuid)| (did.clone(), uuid.clone()))
            .collect();
        state.source_person_uuids = ok_results
            .iter()
            .map(|(_, uuid)| uuid.clone())
            .collect::<HashSet<_>>()
            .into_iter()
            .collect();

        self.update_state(state, MergeStep::SourcesMarked).await?;

        if ok_results.is_empty() {
            // No valid sources - clear target and complete
            let target_person_uuid = Self::get_target_person_uuid(state)?;
            self.person_distinct_ids_api
                .set_merged(
                    &state.target_distinct_id,
                    &target_person_uuid,
                    state.version,
                )
                .await?;
            self.update_state(state, MergeStep::Completed).await?;
            return Ok(MergeResult {
                merged: Vec::new(),
                conflicts,
            });
        }

        // Continue with property merge
        let mut result = self.resume_from_sources_marked(state).await?;
        result.conflicts = conflicts;
        Ok(result)
    }

    /// Resume merge from SourcesMarked step - properties need to be merged.
    async fn resume_from_sources_marked(&self, state: &mut MergeState) -> ApiResult<MergeResult> {
        let target_person_uuid = Self::get_target_person_uuid(state)?;

        if state.source_person_uuids.is_empty() {
            // No sources to merge, just clear target and complete
            self.person_distinct_ids_api
                .set_merged(&state.target_distinct_id, &target_person_uuid, state.version)
                .await?;
            self.update_state(state, MergeStep::Completed).await?;
            return Ok(MergeResult {
                merged: Vec::new(),
                conflicts: Vec::new(),
            });
        }

        // Merge properties
        let merge_result = self
            .person_properties_api
            .get_persons_for_merge(&target_person_uuid, &state.source_person_uuids)
            .await?;

        let source_persons: Vec<Person> = state
            .source_person_uuids
            .iter()
            .filter_map(|uuid| merge_result.source_persons.get(uuid).cloned())
            .collect();

        if !source_persons.is_empty() {
            self.person_properties_api
                .merge_person_properties(&target_person_uuid, &source_persons)
                .await?;
        }

        self.update_state(state, MergeStep::PropertiesMerged).await?;

        // Continue with the rest
        self.resume_from_properties_merged(state).await
    }

    /// Resume merge from PropertiesMerged step - distinct IDs need to be updated.
    async fn resume_from_properties_merged(
        &self,
        state: &mut MergeState,
    ) -> ApiResult<MergeResult> {
        let target_person_uuid = Self::get_target_person_uuid(state)?;
        let valid_source_distinct_ids = state.valid_source_distinct_ids();

        let set_merged_futures: Vec<_> = valid_source_distinct_ids
            .iter()
            .map(|distinct_id| {
                self.person_distinct_ids_api
                    .set_merged(distinct_id, &target_person_uuid, state.version)
            })
            .collect();

        futures::future::try_join_all(set_merged_futures).await?;

        self.update_state(state, MergeStep::DistinctIdsMerged)
            .await?;

        self.resume_from_distinct_ids_merged(state).await
    }

    /// Resume merge from DistinctIdsMerged step - target needs to be cleared.
    async fn resume_from_distinct_ids_merged(
        &self,
        state: &mut MergeState,
    ) -> ApiResult<MergeResult> {
        let target_person_uuid = Self::get_target_person_uuid(state)?;
        self.person_distinct_ids_api
            .set_merged(
                &state.target_distinct_id,
                &target_person_uuid,
                state.version,
            )
            .await?;

        self.update_state(state, MergeStep::TargetCleared).await?;

        self.resume_from_target_cleared(state).await
    }

    /// Resume merge from TargetCleared step - source persons need to be deleted.
    async fn resume_from_target_cleared(&self, state: &mut MergeState) -> ApiResult<MergeResult> {
        let delete_futures: Vec<_> = state
            .source_person_uuids
            .iter()
            .map(|person_uuid| self.person_properties_api.delete_person(person_uuid))
            .collect();

        futures::future::try_join_all(delete_futures).await?;

        self.update_state(state, MergeStep::SourcesDeleted).await?;

        self.resume_from_sources_deleted(state).await
    }

    /// Resume merge from SourcesDeleted step - just mark as completed.
    async fn resume_from_sources_deleted(&self, state: &mut MergeState) -> ApiResult<MergeResult> {
        let target_person_uuid = Self::get_target_person_uuid(state)?;
        self.update_state(state, MergeStep::Completed).await?;

        Ok(MergeResult {
            merged: state
                .valid_source_distinct_ids()
                .into_iter()
                .map(|distinct_id| DistinctIdInfo {
                    distinct_id,
                    person_uuid: target_person_uuid.clone(),
                })
                .collect(),
            conflicts: Vec::new(),
        })
    }
}
