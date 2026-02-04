use std::collections::HashSet;
use std::sync::Arc;

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
/// 5. Delete source persons (handled by garbage collection)
pub struct PersonMergeService {
    person_properties_api: Arc<dyn PersonPropertiesApi>,
    person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
}

impl PersonMergeService {
    pub fn new(
        person_properties_api: Arc<dyn PersonPropertiesApi>,
        person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
    ) -> Self {
        Self {
            person_properties_api,
            person_distinct_ids_api,
        }
    }

    pub async fn merge(
        &self,
        target_distinct_id: &str,
        source_distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<MergeResult> {
        let mut conflicts: Vec<MergeConflict> = Vec::new();

        // 1. Mark target distinct ID as merging target
        //
        // This can return a conflict if:
        // - The target is already a source in another merge operation (merging_source status).
        //   This means someone else is merging this distinct ID into a different target.
        //   The client should perform a transitive merge: instead of merging into this target,
        //   merge into the distinct ID returned in `merging_into_distinct_id`.
        //
        // - The target is already a target in another merge (merging_target status).
        //   This shouldn't happen if the merge service is sharded by target distinct ID,
        //   since all merges to the same target would go to the same shard and be serialized.
        //   If this occurs, it indicates a cleanup is needed for a stale merge state.
        let target_result = self
            .person_distinct_ids_api
            .set_merging_target(target_distinct_id, version)
            .await?;

        let target_person_uuid = match target_result {
            SetMergingTargetResult::Ok { person_uuid, .. } => person_uuid,
            SetMergingTargetResult::Conflict {
                distinct_id,
                person_uuid,
                merging_into_distinct_id,
            } => {
                conflicts.push(MergeConflict::TargetIsSourceInAnotherMerge {
                    distinct_id,
                    person_uuid,
                    merging_into_distinct_id,
                });
                return Ok(MergeResult {
                    merged: Vec::new(),
                    conflicts,
                });
            }
        };

        // 2. Mark all source distinct IDs as merging source
        //
        // Source conflicts are handled differently based on the current merge status:
        //
        // - merging_source: The source is already being merged into another target.
        //   First writer wins, so we drop this source and proceed with the remaining sources.
        //   The conflict is informational only (source_already_merging_elsewhere).
        //
        // - merging_target: The source is currently a target of another merge operation.
        //   We cannot merge it yet because the other merge might change its person UUID.
        //   The client should retry this source later (source_is_merge_target).
        let source_results = self
            .person_distinct_ids_api
            .set_merging_source(source_distinct_ids, version)
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

        if ok_results.is_empty() {
            self.person_distinct_ids_api
                .set_merged(target_distinct_id, &target_person_uuid, version)
                .await?;
            return Ok(MergeResult {
                merged: Vec::new(),
                conflicts,
            });
        }

        let valid_source_distinct_ids: Vec<String> =
            ok_results.iter().map(|(d, _)| d.clone()).collect();

        // 3. Copy properties from source persons to target person
        //
        // We fetch source person properties and merge them into the target. Conflicts are
        // resolved using per-property version numbers - the property with the highest version wins.
        //
        // Note: We may need a different method like `get_persons_for_merge` here, which would
        // lock the source person rows to prevent other processes from updating them after
        // we've copied the properties but before we've deleted the source persons.
        let source_person_uuids: Vec<String> = ok_results
            .iter()
            .map(|(_, uuid)| uuid.clone())
            .collect::<HashSet<_>>()
            .into_iter()
            .collect();

        let source_persons_map = self
            .person_properties_api
            .get_persons(&source_person_uuids)
            .await?;

        let source_persons: Vec<Person> = source_person_uuids
            .iter()
            .filter_map(|uuid| source_persons_map.get(uuid).cloned())
            .collect();

        if !source_persons.is_empty() {
            self.person_properties_api
                .merge_person_properties(&target_person_uuid, &source_persons)
                .await?;
        }

        // 4. Second phase of distinct ID update - move source distinct IDs to the target person
        //    and mark the merge as finished. After this, the distinct IDs point to the target
        //    person UUID and are no longer in a merging state.
        let set_merged_futures: Vec<_> = valid_source_distinct_ids
            .iter()
            .map(|distinct_id| {
                self.person_distinct_ids_api
                    .set_merged(distinct_id, &target_person_uuid, version)
            })
            .collect();

        futures::future::try_join_all(set_merged_futures).await?;

        // 5. Clear merge status on target (also marks the merge as finished for the target)
        self.person_distinct_ids_api
            .set_merged(target_distinct_id, &target_person_uuid, version)
            .await?;

        // Source persons are not deleted here - they will be garbage collected by a separate
        // process that identifies persons with no distinct IDs pointing to them.

        let merged: Vec<DistinctIdInfo> = valid_source_distinct_ids
            .into_iter()
            .map(|distinct_id| DistinctIdInfo {
                distinct_id,
                person_uuid: target_person_uuid.clone(),
            })
            .collect();

        Ok(MergeResult { merged, conflicts })
    }
}
