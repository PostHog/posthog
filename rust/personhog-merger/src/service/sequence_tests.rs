//! Tests that verify the exact sequence and arguments of merge service operations.

use std::collections::HashMap;
use std::sync::Arc;

use tokio::time::{timeout, Duration};

use crate::lock::InMemoryLockService;
use crate::state::{InMemoryMergeStateRepository, MergeStateRepository, MergeStep};
use crate::testing::mock_apis::{MockPersonDistinctIdsApi, MockPersonPropertiesApi};
use crate::types::{
    DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeStatus, Person,
    SetMergingSourceResult, SetMergingTargetResult,
};
use crate::PersonMergeService;

const TEST_TIMEOUT: Duration = Duration::from_secs(5);

fn create_lock_service() -> Arc<InMemoryLockService> {
    Arc::new(InMemoryLockService::new())
}

fn create_person(uuid: &str) -> Person {
    Person {
        person_uuid: uuid.to_string(),
        properties: HashMap::new(),
    }
}

/// Test that verifies the exact sequence of operations during a merge.
#[tokio::test]
async fn test_single_source_merge_operations_happen_in_order() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let source_distinct_id = "source-did";
        let target_person_uuid = "target-uuid";
        let source_person_uuid = "source-uuid";
        let version = 50000;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source =
            distinct_ids_api
                .set_merging_source
                .expect(vec![SetMergingSourceResult::Ok {
                    distinct_id: source_distinct_id.to_string(),
                    person_uuid: source_person_uuid.to_string(),
                }]);

        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: [(
                        source_person_uuid.to_string(),
                        create_person(source_person_uuid),
                    )]
                    .into_iter()
                    .collect(),
                });

        let call_merge_props = properties_api.merge_person_properties.expect(());

        let call_set_merged_source = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        let call_delete = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &[source_distinct_id.to_string()],
                    version,
                )
                .await
        });

        let args = call_set_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);
        assert_eq!(args.version, version);

        let args = call_set_source.complete().await;
        assert_eq!(args.distinct_ids, vec![source_distinct_id]);

        let args = call_get_persons.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);
        assert_eq!(args.source_person_uuids, vec![source_person_uuid]);

        let args = call_merge_props.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);

        let args = call_set_merged_source.complete().await;
        assert_eq!(args.distinct_id, source_distinct_id);

        let args = call_set_merged_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let args = call_delete.complete().await;
        assert_eq!(args.person_uuid, source_person_uuid);

        let result = merge_handle.await.unwrap().unwrap();
        assert_eq!(result.merged.len(), 1);
        assert!(result.conflicts.is_empty());
    })
    .await
    .expect("Test timed out");
}

/// Test sequence with multiple sources
#[tokio::test]
async fn test_multiple_sources_merge_operations() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let target_person_uuid = "target-uuid";
        let version = 50001;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source = distinct_ids_api.set_merging_source.expect(vec![
            SetMergingSourceResult::Ok {
                distinct_id: "source-1".to_string(),
                person_uuid: "source-uuid-1".to_string(),
            },
            SetMergingSourceResult::Ok {
                distinct_id: "source-2".to_string(),
                person_uuid: "source-uuid-2".to_string(),
            },
        ]);

        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: [
                        ("source-uuid-1".to_string(), create_person("source-uuid-1")),
                        ("source-uuid-2".to_string(), create_person("source-uuid-2")),
                    ]
                    .into_iter()
                    .collect(),
                });

        let call_merge_props = properties_api.merge_person_properties.expect(());

        let call_set_merged_1 = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: "source-1".to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_2 = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: "source-2".to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        let call_delete_1 = properties_api.delete_person.expect(());
        let call_delete_2 = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &["source-1".to_string(), "source-2".to_string()],
                    version,
                )
                .await
        });

        let args = call_set_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);
        assert_eq!(args.version, version);

        let args = call_set_source.complete().await;
        assert_eq!(args.distinct_ids, vec!["source-1", "source-2"]);

        let args = call_get_persons.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);
        assert_eq!(args.source_person_uuids.len(), 2);

        let args = call_merge_props.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);
        assert_eq!(args.source_persons.len(), 2);

        // Source distinct IDs are processed in non-deterministic order
        let merged_1 = call_set_merged_1.complete().await;
        let merged_2 = call_set_merged_2.complete().await;
        let mut merged_dids: Vec<_> = vec![merged_1.distinct_id, merged_2.distinct_id];
        merged_dids.sort();
        assert_eq!(merged_dids, vec!["source-1", "source-2"]);

        let args = call_set_merged_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let delete_1 = call_delete_1.complete().await;
        let delete_2 = call_delete_2.complete().await;
        let mut deleted_uuids: Vec<_> = vec![delete_1.person_uuid, delete_2.person_uuid];
        deleted_uuids.sort();
        assert_eq!(deleted_uuids, vec!["source-uuid-1", "source-uuid-2"]);

        let result = merge_handle.await.unwrap().unwrap();
        assert_eq!(result.merged.len(), 2);
        assert!(result.conflicts.is_empty());
    })
    .await
    .expect("Test timed out");
}

/// Test that state is saved and can be inspected while mock is paused
#[tokio::test]
async fn test_state_saved_after_each_step() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let source_distinct_id = "source-did";
        let target_person_uuid = "target-uuid";
        let source_person_uuid = "source-uuid";
        let version = 50002;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source =
            distinct_ids_api
                .set_merging_source
                .expect(vec![SetMergingSourceResult::Ok {
                    distinct_id: source_distinct_id.to_string(),
                    person_uuid: source_person_uuid.to_string(),
                }]);

        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: [(
                        source_person_uuid.to_string(),
                        create_person(source_person_uuid),
                    )]
                    .into_iter()
                    .collect(),
                });

        let call_merge_props = properties_api.merge_person_properties.expect(());
        let call_set_merged_source = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_delete = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo.clone(),
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &[source_distinct_id.to_string()],
                    version,
                )
                .await
        });

        call_set_target.complete().await;
        tokio::task::yield_now().await;
        let state = state_repo.get("merge-1").await.unwrap();
        assert!(
            state.is_some(),
            "State should exist after set_merging_target"
        );

        call_set_source.complete().await;
        call_get_persons.complete().await;
        tokio::task::yield_now().await;
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert!(
            matches!(
                state.step(),
                MergeStep::SourcesMarked
                    | MergeStep::PropertiesMerged
                    | MergeStep::DistinctIdsMerged
            ),
            "Should be at SourcesMarked or later, got {:?}",
            state.step()
        );

        call_merge_props.complete().await;
        call_set_merged_source.complete().await;
        call_set_merged_target.complete().await;
        call_delete.complete().await;

        let result = merge_handle.await.unwrap().unwrap();
        assert!(!result.merged.is_empty());

        let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(final_state.step(), MergeStep::Completed);
    })
    .await
    .expect("Test timed out");
}

/// Test that source person UUIDs are deduplicated when multiple distinct IDs point to same person
#[tokio::test]
async fn test_deduplicates_source_person_uuids() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let target_person_uuid = "target-uuid";
        let shared_person_uuid = "shared-uuid";
        let version = 50003;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source = distinct_ids_api.set_merging_source.expect(vec![
            SetMergingSourceResult::Ok {
                distinct_id: "source-1".to_string(),
                person_uuid: shared_person_uuid.to_string(),
            },
            SetMergingSourceResult::Ok {
                distinct_id: "source-2".to_string(),
                person_uuid: shared_person_uuid.to_string(),
            },
        ]);

        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: [(
                        shared_person_uuid.to_string(),
                        create_person(shared_person_uuid),
                    )]
                    .into_iter()
                    .collect(),
                });

        let call_merge_props = properties_api.merge_person_properties.expect(());

        let call_set_merged_1 = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: "source-1".to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_2 = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: "source-2".to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        // Only one delete: both distinct IDs map to the same person
        let call_delete = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &["source-1".to_string(), "source-2".to_string()],
                    version,
                )
                .await
        });

        let args = call_set_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let args = call_set_source.complete().await;
        assert_eq!(args.distinct_ids, vec!["source-1", "source-2"]);

        // Source person UUIDs are deduplicated
        let args = call_get_persons.complete().await;
        assert_eq!(args.source_person_uuids.len(), 1);
        assert_eq!(args.source_person_uuids[0], shared_person_uuid);

        let args = call_merge_props.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);

        let merged_1 = call_set_merged_1.complete().await;
        let merged_2 = call_set_merged_2.complete().await;
        let mut merged_dids: Vec<_> = vec![merged_1.distinct_id, merged_2.distinct_id];
        merged_dids.sort();
        assert_eq!(merged_dids, vec!["source-1", "source-2"]);

        let args = call_set_merged_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let args = call_delete.complete().await;
        assert_eq!(args.person_uuid, shared_person_uuid);

        let result = merge_handle.await.unwrap().unwrap();
        assert_eq!(result.merged.len(), 2);
    })
    .await
    .expect("Test timed out");
}

/// Test that merge_person_properties is skipped when no source persons found
#[tokio::test]
async fn test_handles_source_person_with_no_properties() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let source_distinct_id = "source-did";
        let target_person_uuid = "target-uuid";
        let source_person_uuid = "source-uuid";
        let version = 50004;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source =
            distinct_ids_api
                .set_merging_source
                .expect(vec![SetMergingSourceResult::Ok {
                    distinct_id: source_distinct_id.to_string(),
                    person_uuid: source_person_uuid.to_string(),
                }]);

        // Source person not found in DB
        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: HashMap::new(),
                });

        // merge_person_properties is skipped when no source persons found
        let call_set_merged_source = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        // delete is still called based on distinct_id mapping, not person properties
        let call_delete = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &[source_distinct_id.to_string()],
                    version,
                )
                .await
        });

        call_set_target.complete().await;
        call_set_source.complete().await;
        call_get_persons.complete().await;
        call_set_merged_source.complete().await;
        call_set_merged_target.complete().await;
        call_delete.complete().await;

        let result = merge_handle.await.unwrap().unwrap();
        assert_eq!(result.merged.len(), 1);
        assert!(!properties_api
            .merge_person_properties
            .has_pending_expectations());
    })
    .await
    .expect("Test timed out");
}

/// Test that conflicts are returned when source distinct IDs are already merging
#[tokio::test]
async fn test_returns_conflicts_when_sources_already_merging() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let target_person_uuid = "target-uuid";
        let version = 50005;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source = distinct_ids_api.set_merging_source.expect(vec![
            SetMergingSourceResult::Ok {
                distinct_id: "source-1".to_string(),
                person_uuid: "person-1".to_string(),
            },
            SetMergingSourceResult::Conflict {
                distinct_id: "source-2".to_string(),
                person_uuid: "person-2".to_string(),
                current_merge_status: MergeStatus::MergingSource,
            },
            SetMergingSourceResult::Conflict {
                distinct_id: "source-3".to_string(),
                person_uuid: "person-3".to_string(),
                current_merge_status: MergeStatus::MergingTarget,
            },
        ]);

        // Conflicting sources are excluded
        let call_get_persons =
            properties_api
                .get_persons_for_merge
                .expect(GetPersonsForMergeResult {
                    target_person: create_person(target_person_uuid),
                    source_persons: [("person-1".to_string(), create_person("person-1"))]
                        .into_iter()
                        .collect(),
                });

        let call_merge_props = properties_api.merge_person_properties.expect(());

        let call_set_merged_1 = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: "source-1".to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        let call_delete = properties_api.delete_person.expect(());

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &[
                        "source-1".to_string(),
                        "source-2".to_string(),
                        "source-3".to_string(),
                    ],
                    version,
                )
                .await
        });

        let args = call_set_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let args = call_set_source.complete().await;
        assert_eq!(args.distinct_ids, vec!["source-1", "source-2", "source-3"]);

        let args = call_get_persons.complete().await;
        assert_eq!(args.source_person_uuids, vec!["person-1"]);

        let args = call_merge_props.complete().await;
        assert_eq!(args.target_person_uuid, target_person_uuid);

        let args = call_set_merged_1.complete().await;
        assert_eq!(args.distinct_id, "source-1");

        let args = call_set_merged_target.complete().await;
        assert_eq!(args.distinct_id, target_distinct_id);

        let args = call_delete.complete().await;
        assert_eq!(args.person_uuid, "person-1");

        let result = merge_handle.await.unwrap().unwrap();
        assert_eq!(result.merged.len(), 1);
        assert_eq!(result.merged[0].distinct_id, "source-1");
        assert_eq!(result.conflicts.len(), 2);
        assert!(result
            .conflicts
            .contains(&MergeConflict::SourceAlreadyMergingElsewhere {
                distinct_id: "source-2".to_string(),
                person_uuid: "person-2".to_string(),
            }));
        assert!(result
            .conflicts
            .contains(&MergeConflict::SourceIsMergeTarget {
                distinct_id: "source-3".to_string(),
                person_uuid: "person-3".to_string(),
            }));
    })
    .await
    .expect("Test timed out");
}

/// Test that when all sources conflict, only target status is cleared
#[tokio::test]
async fn test_clears_target_when_all_sources_conflict() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let target_person_uuid = "target-uuid";
        let version = 50006;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Ok {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: target_person_uuid.to_string(),
                });

        let call_set_source = distinct_ids_api.set_merging_source.expect(vec![
            SetMergingSourceResult::Conflict {
                distinct_id: "source-1".to_string(),
                person_uuid: "person-1".to_string(),
                current_merge_status: MergeStatus::MergingSource,
            },
            SetMergingSourceResult::Conflict {
                distinct_id: "source-2".to_string(),
                person_uuid: "person-2".to_string(),
                current_merge_status: MergeStatus::MergingTarget,
            },
        ]);

        // All sources conflict: skip properties merge and delete, just clear target status
        let call_set_merged_target = distinct_ids_api.set_merged.expect(DistinctIdInfo {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api,
            state_repo,
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &["source-1".to_string(), "source-2".to_string()],
                    version,
                )
                .await
        });

        call_set_target.complete().await;
        call_set_source.complete().await;
        call_set_merged_target.complete().await;

        let result = merge_handle.await.unwrap().unwrap();

        assert!(result.merged.is_empty());
        assert_eq!(result.conflicts.len(), 2);
        assert!(!properties_api
            .get_persons_for_merge
            .has_pending_expectations());
    })
    .await
    .expect("Test timed out");
}

/// Test target conflict stops merge early
#[tokio::test]
async fn test_stops_early_on_target_conflict() {
    timeout(TEST_TIMEOUT, async {
        let target_distinct_id = "target-did";
        let version = 50007;

        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
        let properties_api = Arc::new(MockPersonPropertiesApi::new());

        let call_set_target =
            distinct_ids_api
                .set_merging_target
                .expect(SetMergingTargetResult::Conflict {
                    distinct_id: target_distinct_id.to_string(),
                    person_uuid: "target-uuid".to_string(),
                    merging_into_distinct_id: "other-target".to_string(),
                });

        let state_repo = Arc::new(InMemoryMergeStateRepository::new());
        let merge_service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            create_lock_service(),
        );

        let merge_handle = tokio::spawn(async move {
            merge_service
                .merge(
                    "merge-1",
                    target_distinct_id,
                    &["source-did".to_string()],
                    version,
                )
                .await
        });

        call_set_target.complete().await;

        let result = merge_handle.await.unwrap().unwrap();

        assert!(result.merged.is_empty());
        assert_eq!(result.conflicts.len(), 1);
        assert!(matches!(
            &result.conflicts[0],
            MergeConflict::TargetIsSourceInAnotherMerge { .. }
        ));

        assert!(!distinct_ids_api
            .set_merging_source
            .has_pending_expectations());

        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::Started);
    })
    .await
    .expect("Test timed out");
}
