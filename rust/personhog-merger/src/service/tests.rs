use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;

use crate::lock::InMemoryLockService;
use crate::state::{
    CompletedState, DistinctIdsMergedState, InMemoryMergeStateRepository, MergeState,
    MergeStateRepository, MergeStep, PropertiesMergedState, SourcesMarkedState, StartedState,
    TargetClearedState, TargetMarkedState,
};
use crate::testing::Breakpoint;
use crate::types::{
    ApiResult, DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
    VersionedProperty,
};
use crate::PersonMergeService;

fn create_lock_service() -> Arc<InMemoryLockService> {
    Arc::new(InMemoryLockService::new())
}

type CallRecorder<T> = Arc<Mutex<Vec<T>>>;

#[derive(Clone, Debug)]
struct SetMergingTargetCall {
    distinct_id: String,
    version: i64,
}

#[derive(Clone, Debug)]
struct SetMergingSourceCall {
    distinct_ids: Vec<String>,
    version: i64,
}

#[derive(Clone, Debug)]
struct SetMergedCall {
    distinct_id: String,
    person_uuid: String,
    #[allow(dead_code)]
    version: i64,
}

#[derive(Clone, Debug)]
struct GetPersonsForMergeCall {
    target_person_uuid: String,
    source_person_uuids: Vec<String>,
}

#[derive(Clone, Debug)]
struct MergePersonPropertiesCall {
    target_person_uuid: String,
    source_persons: Vec<Person>,
}

#[derive(Clone, Debug)]
struct DeletePersonCall {
    #[allow(dead_code)]
    person_uuid: String,
}

struct MockPersonPropertiesApi {
    get_persons_for_merge_result: Mutex<Option<ApiResult<GetPersonsForMergeResult>>>,
    merge_person_properties_result: Mutex<Option<ApiResult<()>>>,
    delete_person_result: Mutex<Option<ApiResult<()>>>,
    get_persons_for_merge_calls: CallRecorder<GetPersonsForMergeCall>,
    merge_person_properties_calls: CallRecorder<MergePersonPropertiesCall>,
    delete_person_calls: CallRecorder<DeletePersonCall>,
    #[allow(dead_code)]
    get_persons_for_merge_breakpoint: Mutex<Option<Breakpoint<()>>>,
    #[allow(dead_code)]
    merge_person_properties_breakpoint: Mutex<Option<Breakpoint<()>>>,
}

impl MockPersonPropertiesApi {
    fn new() -> Self {
        Self {
            get_persons_for_merge_result: Mutex::new(None),
            merge_person_properties_result: Mutex::new(None),
            delete_person_result: Mutex::new(None),
            get_persons_for_merge_calls: Arc::new(Mutex::new(Vec::new())),
            merge_person_properties_calls: Arc::new(Mutex::new(Vec::new())),
            delete_person_calls: Arc::new(Mutex::new(Vec::new())),
            get_persons_for_merge_breakpoint: Mutex::new(None),
            merge_person_properties_breakpoint: Mutex::new(None),
        }
    }

    fn set_get_persons_for_merge_result(
        &self,
        target_person: Person,
        source_persons: HashMap<String, Person>,
    ) {
        *self.get_persons_for_merge_result.lock().unwrap() = Some(Ok(GetPersonsForMergeResult {
            target_person,
            source_persons,
        }));
    }

    #[allow(dead_code)]
    fn set_get_persons_for_merge_error(&self, error: impl Into<String>) {
        *self.get_persons_for_merge_result.lock().unwrap() = Some(Err(error.into().into()));
    }

    fn set_merge_person_properties_result(&self, result: ApiResult<()>) {
        *self.merge_person_properties_result.lock().unwrap() = Some(result);
    }

    #[allow(dead_code)]
    fn set_delete_person_error(&self, error: impl Into<String>) {
        *self.delete_person_result.lock().unwrap() = Some(Err(error.into().into()));
    }

    fn get_persons_for_merge_call_count(&self) -> usize {
        self.get_persons_for_merge_calls.lock().unwrap().len()
    }

    fn merge_person_properties_call_count(&self) -> usize {
        self.merge_person_properties_calls.lock().unwrap().len()
    }

    fn get_get_persons_for_merge_calls(&self) -> Vec<GetPersonsForMergeCall> {
        self.get_persons_for_merge_calls.lock().unwrap().clone()
    }

    fn get_merge_person_properties_calls(&self) -> Vec<MergePersonPropertiesCall> {
        self.merge_person_properties_calls.lock().unwrap().clone()
    }

    fn get_delete_person_calls(&self) -> Vec<DeletePersonCall> {
        self.delete_person_calls.lock().unwrap().clone()
    }
}

#[async_trait]
impl PersonPropertiesApi for MockPersonPropertiesApi {
    async fn get_persons_for_merge(
        &self,
        target_person_uuid: &str,
        source_person_uuids: &[String],
    ) -> ApiResult<GetPersonsForMergeResult> {
        self.get_persons_for_merge_calls
            .lock()
            .unwrap()
            .push(GetPersonsForMergeCall {
                target_person_uuid: target_person_uuid.to_string(),
                source_person_uuids: source_person_uuids.to_vec(),
            });

        self.get_persons_for_merge_result
            .lock()
            .unwrap()
            .take()
            .unwrap_or_else(|| {
                Ok(GetPersonsForMergeResult {
                    target_person: Person {
                        person_uuid: target_person_uuid.to_string(),
                        properties: HashMap::new(),
                    },
                    source_persons: HashMap::new(),
                })
            })
    }

    async fn merge_person_properties(
        &self,
        target_person_uuid: &str,
        source_persons: &[Person],
    ) -> ApiResult<()> {
        self.merge_person_properties_calls
            .lock()
            .unwrap()
            .push(MergePersonPropertiesCall {
                target_person_uuid: target_person_uuid.to_string(),
                source_persons: source_persons.to_vec(),
            });

        self.merge_person_properties_result
            .lock()
            .unwrap()
            .take()
            .unwrap_or(Ok(()))
    }

    async fn delete_person(&self, person_uuid: &str) -> ApiResult<()> {
        self.delete_person_calls
            .lock()
            .unwrap()
            .push(DeletePersonCall {
                person_uuid: person_uuid.to_string(),
            });

        self.delete_person_result
            .lock()
            .unwrap()
            .take()
            .unwrap_or(Ok(()))
    }
}

struct MockPersonDistinctIdsApi {
    set_merging_target_result: Mutex<Option<ApiResult<SetMergingTargetResult>>>,
    set_merging_source_result: Mutex<Option<ApiResult<Vec<SetMergingSourceResult>>>>,
    #[allow(dead_code)]
    set_merged_results: Mutex<Vec<ApiResult<DistinctIdInfo>>>,
    set_merging_target_calls: CallRecorder<SetMergingTargetCall>,
    set_merging_source_calls: CallRecorder<SetMergingSourceCall>,
    set_merged_calls: CallRecorder<SetMergedCall>,
    #[allow(dead_code)]
    set_merging_target_breakpoint: Mutex<Option<Breakpoint<()>>>,
    #[allow(dead_code)]
    set_merging_source_breakpoint: Mutex<Option<Breakpoint<()>>>,
    #[allow(dead_code)]
    set_merged_breakpoints: Mutex<Vec<Breakpoint<()>>>,
}

impl MockPersonDistinctIdsApi {
    fn new() -> Self {
        Self {
            set_merging_target_result: Mutex::new(None),
            set_merging_source_result: Mutex::new(None),
            set_merged_results: Mutex::new(Vec::new()),
            set_merging_target_calls: Arc::new(Mutex::new(Vec::new())),
            set_merging_source_calls: Arc::new(Mutex::new(Vec::new())),
            set_merged_calls: Arc::new(Mutex::new(Vec::new())),
            set_merging_target_breakpoint: Mutex::new(None),
            set_merging_source_breakpoint: Mutex::new(None),
            set_merged_breakpoints: Mutex::new(Vec::new()),
        }
    }

    fn set_merging_target_result(&self, result: SetMergingTargetResult) {
        *self.set_merging_target_result.lock().unwrap() = Some(Ok(result));
    }

    #[allow(dead_code)]
    fn set_merging_target_error(&self, error: impl Into<String>) {
        *self.set_merging_target_result.lock().unwrap() = Some(Err(error.into().into()));
    }

    fn set_merging_source_result(&self, result: Vec<SetMergingSourceResult>) {
        *self.set_merging_source_result.lock().unwrap() = Some(Ok(result));
    }

    #[allow(dead_code)]
    fn set_merging_source_error(&self, error: impl Into<String>) {
        *self.set_merging_source_result.lock().unwrap() = Some(Err(error.into().into()));
    }

    fn get_set_merging_target_calls(&self) -> Vec<SetMergingTargetCall> {
        self.set_merging_target_calls.lock().unwrap().clone()
    }

    fn get_set_merging_source_calls(&self) -> Vec<SetMergingSourceCall> {
        self.set_merging_source_calls.lock().unwrap().clone()
    }

    fn get_set_merged_calls(&self) -> Vec<SetMergedCall> {
        self.set_merged_calls.lock().unwrap().clone()
    }
}

#[async_trait]
impl PersonDistinctIdsApi for MockPersonDistinctIdsApi {
    async fn add_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn delete_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_person_uuid(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_merging_source(
        &self,
        distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<Vec<SetMergingSourceResult>> {
        self.set_merging_source_calls
            .lock()
            .unwrap()
            .push(SetMergingSourceCall {
                distinct_ids: distinct_ids.to_vec(),
                version,
            });

        self.set_merging_source_result
            .lock()
            .unwrap()
            .take()
            .unwrap_or_else(|| Ok(Vec::new()))
    }

    async fn set_merging_target(
        &self,
        distinct_id: &str,
        version: i64,
    ) -> ApiResult<SetMergingTargetResult> {
        self.set_merging_target_calls
            .lock()
            .unwrap()
            .push(SetMergingTargetCall {
                distinct_id: distinct_id.to_string(),
                version,
            });

        self.set_merging_target_result
            .lock()
            .unwrap()
            .take()
            .unwrap_or_else(|| {
                Ok(SetMergingTargetResult::Ok {
                    distinct_id: distinct_id.to_string(),
                    person_uuid: "default-person-uuid".to_string(),
                })
            })
    }

    async fn set_merged(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        self.set_merged_calls.lock().unwrap().push(SetMergedCall {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
            version,
        });

        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }
}

fn create_person(person_uuid: &str, properties: Vec<(&str, serde_json::Value, i64)>) -> Person {
    let mut props = HashMap::new();
    for (key, value, version) in properties {
        props.insert(key.to_string(), VersionedProperty { value, version });
    }
    Person {
        person_uuid: person_uuid.to_string(),
        properties: props,
    }
}

/// Helper to create a TargetMarkedState
fn create_target_marked_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
) -> TargetMarkedState {
    TargetMarkedState {
        started: StartedState {
            merge_id: merge_id.to_string(),
            target_distinct_id: target_distinct_id.to_string(),
            source_distinct_ids,
            version,
        },
        target_person_uuid: target_person_uuid.to_string(),
    }
}

/// Helper to create a SourcesMarkedState
fn create_sources_marked_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
    valid_sources: HashMap<String, String>,
    source_person_uuids: Vec<String>,
) -> SourcesMarkedState {
    SourcesMarkedState {
        merge_id: merge_id.to_string(),
        target_distinct_id: target_distinct_id.to_string(),
        source_distinct_ids,
        version,
        target_person_uuid: target_person_uuid.to_string(),
        valid_sources,
        source_person_uuids,
        conflicts: Vec::new(),
    }
}

/// Helper to create a PropertiesMergedState
fn create_properties_merged_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
    valid_sources: HashMap<String, String>,
    source_person_uuids: Vec<String>,
) -> PropertiesMergedState {
    PropertiesMergedState {
        merge_id: merge_id.to_string(),
        target_distinct_id: target_distinct_id.to_string(),
        source_distinct_ids,
        version,
        target_person_uuid: target_person_uuid.to_string(),
        valid_sources,
        source_person_uuids,
        conflicts: Vec::new(),
    }
}

/// Helper to create a DistinctIdsMergedState
fn create_distinct_ids_merged_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
    valid_sources: HashMap<String, String>,
    source_person_uuids: Vec<String>,
) -> DistinctIdsMergedState {
    DistinctIdsMergedState {
        merge_id: merge_id.to_string(),
        target_distinct_id: target_distinct_id.to_string(),
        source_distinct_ids,
        version,
        target_person_uuid: target_person_uuid.to_string(),
        valid_sources,
        source_person_uuids,
        conflicts: Vec::new(),
    }
}

/// Helper to create a TargetClearedState
fn create_target_cleared_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
    valid_sources: HashMap<String, String>,
    source_person_uuids: Vec<String>,
) -> TargetClearedState {
    TargetClearedState {
        merge_id: merge_id.to_string(),
        target_distinct_id: target_distinct_id.to_string(),
        source_distinct_ids,
        version,
        target_person_uuid: target_person_uuid.to_string(),
        valid_sources,
        source_person_uuids,
        conflicts: Vec::new(),
    }
}

/// Helper to create a CompletedState
fn create_completed_state(
    merge_id: &str,
    target_distinct_id: &str,
    source_distinct_ids: Vec<String>,
    version: i64,
    target_person_uuid: &str,
    valid_sources: HashMap<String, String>,
    source_person_uuids: Vec<String>,
) -> CompletedState {
    CompletedState {
        merge_id: merge_id.to_string(),
        target_distinct_id: target_distinct_id.to_string(),
        source_distinct_ids,
        version,
        target_person_uuid: target_person_uuid.to_string(),
        valid_sources,
        source_person_uuids,
        conflicts: Vec::new(),
    }
}

#[tokio::test]
async fn test_merges_single_source_into_target() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 1000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(
        source_person_uuid,
        vec![("email", serde_json::json!("source@example.com"), 1)],
    );
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person.clone());
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await
        .unwrap();

    assert_eq!(
        result.merged,
        vec![DistinctIdInfo {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        }]
    );
    assert!(result.conflicts.is_empty());

    // Verify API calls
    let target_calls = distinct_ids_api.get_set_merging_target_calls();
    assert_eq!(target_calls.len(), 1);
    assert_eq!(target_calls[0].distinct_id, target_distinct_id);
    assert_eq!(target_calls[0].version, version);

    let source_calls = distinct_ids_api.get_set_merging_source_calls();
    assert_eq!(source_calls.len(), 1);
    assert_eq!(source_calls[0].distinct_ids, vec![source_distinct_id]);
    assert_eq!(source_calls[0].version, version);

    let get_persons_for_merge_calls = properties_api.get_get_persons_for_merge_calls();
    assert_eq!(get_persons_for_merge_calls.len(), 1);
    assert_eq!(
        get_persons_for_merge_calls[0].target_person_uuid,
        target_person_uuid
    );
    assert_eq!(
        get_persons_for_merge_calls[0].source_person_uuids,
        vec![source_person_uuid]
    );

    let merge_props_calls = properties_api.get_merge_person_properties_calls();
    assert_eq!(merge_props_calls.len(), 1);
    assert_eq!(merge_props_calls[0].target_person_uuid, target_person_uuid);
    assert_eq!(merge_props_calls[0].source_persons, vec![source_person]);

    let set_merged_calls = distinct_ids_api.get_set_merged_calls();
    assert_eq!(set_merged_calls.len(), 2);
    // One for source, one for target
    assert!(set_merged_calls
        .iter()
        .any(|c| c.distinct_id == source_distinct_id && c.person_uuid == target_person_uuid));
    assert!(set_merged_calls
        .iter()
        .any(|c| c.distinct_id == target_distinct_id && c.person_uuid == target_person_uuid));

    // Source person should be deleted
    let delete_person_calls = properties_api.get_delete_person_calls();
    assert_eq!(delete_person_calls.len(), 1);
    assert_eq!(delete_person_calls[0].person_uuid, source_person_uuid);
}

#[tokio::test]
async fn test_merges_multiple_sources_into_target() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_ids = vec![
        "source-1".to_string(),
        "source-2".to_string(),
        "source-3".to_string(),
    ];
    let target_person_uuid = "target-person-uuid";
    let source_person_uuids = ["source-person-1", "source-person-2", "source-person-3"];
    let version = 2000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(
        source_distinct_ids
            .iter()
            .zip(source_person_uuids.iter())
            .map(|(did, uuid)| SetMergingSourceResult::Ok {
                distinct_id: did.clone(),
                person_uuid: uuid.to_string(),
            })
            .collect(),
    );

    let target_person = create_person(target_person_uuid, vec![]);
    let source_persons: Vec<Person> = source_person_uuids
        .iter()
        .enumerate()
        .map(|(i, uuid)| {
            create_person(
                uuid,
                vec![(
                    &format!("prop{}", i),
                    serde_json::json!(format!("value{}", i)),
                    1,
                )],
            )
        })
        .collect();

    let mut source_persons_map = HashMap::new();
    for person in &source_persons {
        source_persons_map.insert(person.person_uuid.clone(), person.clone());
    }
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    assert_eq!(result.merged.len(), 3);
    assert!(result.conflicts.is_empty());

    let source_calls = distinct_ids_api.get_set_merging_source_calls();
    assert_eq!(source_calls[0].distinct_ids, source_distinct_ids);

    let set_merged_calls = distinct_ids_api.get_set_merged_calls();
    assert_eq!(set_merged_calls.len(), 4); // 3 sources + 1 target

    // All 3 source persons should be deleted
    let delete_person_calls = properties_api.get_delete_person_calls();
    assert_eq!(delete_person_calls.len(), 3);
}

#[tokio::test]
async fn test_deduplicates_source_person_uuids_when_multiple_distinct_ids_belong_to_same_person() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_ids = vec!["source-1".to_string(), "source-2".to_string()];
    let target_person_uuid = "target-person-uuid";
    let shared_source_person_uuid = "shared-source-person-uuid";
    let version = 3000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    // Both distinct IDs point to the same person
    distinct_ids_api.set_merging_source_result(vec![
        SetMergingSourceResult::Ok {
            distinct_id: "source-1".to_string(),
            person_uuid: shared_source_person_uuid.to_string(),
        },
        SetMergingSourceResult::Ok {
            distinct_id: "source-2".to_string(),
            person_uuid: shared_source_person_uuid.to_string(),
        },
    ]);

    let target_person = create_person(target_person_uuid, vec![]);
    let shared_person = create_person(
        shared_source_person_uuid,
        vec![("shared", serde_json::json!("property"), 1)],
    );
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(shared_source_person_uuid.to_string(), shared_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let _result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    // Should only fetch the person once even though two distinct IDs reference it
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 1);
    assert_eq!(properties_api.merge_person_properties_call_count(), 1);

    // Should only delete the person once (deduplicated)
    let delete_person_calls = properties_api.get_delete_person_calls();
    assert_eq!(delete_person_calls.len(), 1);
    assert_eq!(
        delete_person_calls[0].person_uuid,
        shared_source_person_uuid
    );
}

#[tokio::test]
async fn test_handles_source_person_with_no_properties() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 4000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    // Return empty source_persons map - person not found
    let target_person = create_person(target_person_uuid, vec![]);
    properties_api.set_get_persons_for_merge_result(target_person, HashMap::new());

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let _result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await
        .unwrap();

    // get_persons_for_merge should be called
    let get_persons_for_merge_calls = properties_api.get_get_persons_for_merge_calls();
    assert_eq!(get_persons_for_merge_calls.len(), 1);
    assert_eq!(
        get_persons_for_merge_calls[0].target_person_uuid,
        target_person_uuid
    );
    assert_eq!(
        get_persons_for_merge_calls[0].source_person_uuids,
        vec![source_person_uuid]
    );

    // merge_person_properties should NOT be called since no persons were found
    assert_eq!(properties_api.merge_person_properties_call_count(), 0);
}

#[tokio::test]
async fn test_returns_conflicts_when_source_distinct_ids_are_already_merging() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_ids = vec![
        "source-1".to_string(),
        "source-2".to_string(),
        "source-3".to_string(),
    ];
    let target_person_uuid = "target-person-uuid";
    let version = 5000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![
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

    let target_person = create_person(target_person_uuid, vec![]);
    let valid_source_person =
        create_person("person-1", vec![("prop", serde_json::json!("value"), 1)]);
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert("person-1".to_string(), valid_source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    assert_eq!(
        result.merged,
        vec![DistinctIdInfo {
            distinct_id: "source-1".to_string(),
            person_uuid: target_person_uuid.to_string(),
        }]
    );

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

    // Only person-1 should be fetched
    let get_persons_for_merge_calls = properties_api.get_get_persons_for_merge_calls();
    assert_eq!(get_persons_for_merge_calls.len(), 1);
    assert_eq!(
        get_persons_for_merge_calls[0].source_person_uuids,
        vec!["person-1"]
    );

    // set_merged should only be called for source-1 and target, not source-2 or source-3
    let set_merged_calls = distinct_ids_api.get_set_merged_calls();
    assert!(set_merged_calls
        .iter()
        .any(|c| c.distinct_id == "source-1" && c.person_uuid == target_person_uuid));
    assert!(!set_merged_calls.iter().any(|c| c.distinct_id == "source-2"));
    assert!(!set_merged_calls.iter().any(|c| c.distinct_id == "source-3"));
}

#[tokio::test]
async fn test_clears_target_merge_status_when_all_sources_conflict() {
    let target_distinct_id = "target-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_distinct_ids = vec!["source-1".to_string(), "source-2".to_string()];
    let version = 6000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    // All sources conflict
    distinct_ids_api.set_merging_source_result(vec![
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

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    assert!(result.merged.is_empty());
    assert_eq!(result.conflicts.len(), 2);

    // Target merge status should be cleared
    let set_merged_calls = distinct_ids_api.get_set_merged_calls();
    assert_eq!(set_merged_calls.len(), 1);
    assert_eq!(set_merged_calls[0].distinct_id, target_distinct_id);
    assert_eq!(set_merged_calls[0].person_uuid, target_person_uuid);

    // get_persons_for_merge should NOT be called
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);

    // No persons should be deleted since no merges succeeded
    assert!(properties_api.get_delete_person_calls().is_empty());
}

#[tokio::test]
async fn test_returns_conflict_when_target_is_being_merged_into_another_distinct_id() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_ids = vec!["source-1".to_string()];
    let version = 7000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Target is already a source in another merge
    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Conflict {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: "target-person-uuid".to_string(),
        merging_into_distinct_id: "other-target-distinct-id".to_string(),
    });

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    assert!(result.merged.is_empty());
    assert_eq!(result.conflicts.len(), 1);
    assert_eq!(
        result.conflicts[0],
        MergeConflict::TargetIsSourceInAnotherMerge {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: "target-person-uuid".to_string(),
            merging_into_distinct_id: "other-target-distinct-id".to_string(),
        }
    );

    // set_merging_source should NOT be called
    assert!(distinct_ids_api.get_set_merging_source_calls().is_empty());

    // get_persons_for_merge should NOT be called
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);

    // set_merged should NOT be called
    assert!(distinct_ids_api.get_set_merged_calls().is_empty());

    // No persons should be deleted
    assert!(properties_api.get_delete_person_calls().is_empty());
}

#[tokio::test]
async fn test_state_is_tracked_throughout_merge() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 8000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(
        source_person_uuid,
        vec![("email", serde_json::json!("test@example.com"), 1)],
    );
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await
        .unwrap();

    assert!(!result.merged.is_empty());
    assert!(result.conflicts.is_empty());

    // Verify final state (stored by merge_id)
    let final_state = state_repo.get("merge-1").await.unwrap();
    assert!(final_state.is_some());

    let state = final_state.unwrap();
    assert_eq!(state.step(), MergeStep::Completed);
    assert_eq!(state.target_person_uuid(), Some(target_person_uuid));
    assert_eq!(state.target_distinct_id(), Some(target_distinct_id));
    assert_eq!(state.version(), version);
    assert_eq!(
        state.valid_source_distinct_ids(),
        vec![source_distinct_id.to_string()]
    );
}

#[tokio::test]
async fn test_merge_reraises_api_errors_from_set_merging_target() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_ids = vec!["source-1".to_string()];
    let version = 9000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Inject error on set_merging_target
    distinct_ids_api.set_merging_target_error("network disconnection");

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await;

    assert!(result.is_err());
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("network disconnection"));
}

#[tokio::test]
async fn test_merge_reraises_api_errors_from_set_merging_source() {
    let target_distinct_id = "target-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_distinct_ids = vec!["source-1".to_string()];
    let version = 9001;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    // Inject error on set_merging_source
    distinct_ids_api.set_merging_source_error("connection timeout");

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge("merge-1", target_distinct_id, &source_distinct_ids, version)
        .await;

    assert!(result.is_err());
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("connection timeout"));
}

#[tokio::test]
async fn test_merge_reraises_api_errors_from_get_persons_for_merge() {
    let target_distinct_id = "target-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 9002;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    // Inject error on get_persons_for_merge
    properties_api.set_get_persons_for_merge_error("database unavailable");

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await;

    assert!(result.is_err());
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("database unavailable"));
}

#[tokio::test]
async fn test_merge_reraises_api_errors_from_delete_person() {
    let target_distinct_id = "target-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 9003;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(source_person_uuid, vec![]);
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    // Inject error on delete_person
    properties_api.set_delete_person_error("storage failure");

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        create_lock_service(),
    );

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await;

    assert!(result.is_err());
    assert!(result.unwrap_err().to_string().contains("storage failure"));
}

#[tokio::test]
async fn test_resume_from_started_step() {
    let target_person_uuid = "target-person-uuid";
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 10010;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Set up expected responses for resume
    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });

    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(source_person_uuid, vec![]);
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    // Pre-populate state at Started step
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let initial_state = MergeState::new(
        "merge-1".to_string(),
        target_distinct_id.to_string(),
        vec![source_distinct_id.to_string()],
        version,
    );
    state_repo.set(initial_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 1);
    let (merge_id, result) = &results[0];
    assert_eq!(merge_id, "merge-1");
    assert!(result.is_ok());

    let merge_result = result.as_ref().unwrap();
    assert_eq!(merge_result.merged.len(), 1);

    // Verify final state
    let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
    assert_eq!(final_state.step(), MergeStep::Completed);

    // Verify set_merging_target was called (idempotent retry)
    assert_eq!(distinct_ids_api.get_set_merging_target_calls().len(), 1);
    assert_eq!(distinct_ids_api.get_set_merging_source_calls().len(), 1);
}

#[tokio::test]
async fn test_resume_from_target_marked_step() {
    let target_person_uuid = "target-person-uuid";
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 10011;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Set up expected responses for resume
    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(source_person_uuid, vec![]);
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    // Pre-populate state at TargetMarked step
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let initial_state = MergeState::TargetMarked(create_target_marked_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
    ));
    state_repo.set(initial_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_ok());

    // Verify final state
    let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
    assert_eq!(final_state.step(), MergeStep::Completed);

    // set_merging_target should NOT be called (already done)
    assert!(distinct_ids_api.get_set_merging_target_calls().is_empty());
    // set_merging_source SHOULD be called
    assert_eq!(distinct_ids_api.get_set_merging_source_calls().len(), 1);
}

#[tokio::test]
async fn test_resume_from_sources_marked_step() {
    let target_person_uuid = "target-person-uuid";
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 10000;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Set up expected responses for resume
    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(
        source_person_uuid,
        vec![("email", serde_json::json!("test@example.com"), 1)],
    );
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    // Pre-populate state at SourcesMarked step
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::SourcesMarked(create_sources_marked_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    // Resume all incomplete merges
    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 1);
    let (merge_id, result) = &results[0];
    assert_eq!(merge_id, "merge-1");
    assert!(result.is_ok());

    let merge_result = result.as_ref().unwrap();
    assert_eq!(merge_result.merged.len(), 1);
    assert_eq!(merge_result.merged[0].distinct_id, source_distinct_id);
    assert_eq!(merge_result.merged[0].person_uuid, target_person_uuid);

    // Verify final state
    let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
    assert_eq!(final_state.step(), MergeStep::Completed);

    // Verify API calls were made
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 1);
    assert_eq!(properties_api.merge_person_properties_call_count(), 1);
    assert_eq!(properties_api.get_delete_person_calls().len(), 1);
}

#[tokio::test]
async fn test_resume_from_properties_merged_step() {
    let target_person_uuid = "target-person-uuid";
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 10001;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Pre-populate state at PropertiesMerged step
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::PropertiesMerged(create_properties_merged_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_ok());

    // Properties API should NOT be called (already merged)
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);
    assert_eq!(properties_api.merge_person_properties_call_count(), 0);

    // But delete should be called
    assert_eq!(properties_api.get_delete_person_calls().len(), 1);

    // And set_merged should be called
    let set_merged_calls = distinct_ids_api.get_set_merged_calls();
    assert!(set_merged_calls.len() >= 2); // source + target
}

#[tokio::test]
async fn test_resume_from_target_cleared_step() {
    let target_person_uuid = "target-person-uuid";
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let source_person_uuid = "source-person-uuid";
    let version = 10002;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Pre-populate state at TargetCleared step
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::TargetCleared(create_target_cleared_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_ok());

    // Only delete should be called
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);
    assert_eq!(properties_api.get_delete_person_calls().len(), 1);

    // set_merged should NOT be called (already done)
    assert!(distinct_ids_api.get_set_merged_calls().is_empty());
}

#[tokio::test]
async fn test_resume_skips_completed_and_failed_states() {
    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Add a completed state
    let completed_state = MergeState::Completed(create_completed_state(
        "completed-merge",
        "completed-did",
        vec![],
        1,
        "person-uuid",
        HashMap::new(),
        vec![],
    ));
    state_repo.set(completed_state).await.unwrap();

    // Add a failed state
    let failed_state = MergeState::Failed {
        merge_id: "failed-merge".to_string(),
        error: "previous error".to_string(),
    };
    state_repo.set(failed_state).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    // Should be empty - no incomplete states
    assert!(results.is_empty());
}

#[tokio::test]
async fn test_resume_multiple_incomplete_merges() {
    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Add first incomplete state at DistinctIdsMerged
    let mut valid_sources1 = HashMap::new();
    valid_sources1.insert("source-1".to_string(), "source-person-1".to_string());
    let state1 = MergeState::DistinctIdsMerged(create_distinct_ids_merged_state(
        "merge-1",
        "did-1",
        vec!["source-1".to_string()],
        1,
        "person-1",
        valid_sources1,
        vec!["source-person-1".to_string()],
    ));
    state_repo.set(state1).await.unwrap();

    // Add second incomplete state at TargetCleared
    let mut valid_sources2 = HashMap::new();
    valid_sources2.insert("source-2".to_string(), "source-person-2".to_string());
    let state2 = MergeState::TargetCleared(create_target_cleared_state(
        "merge-2",
        "did-2",
        vec!["source-2".to_string()],
        2,
        "person-2",
        valid_sources2,
        vec!["source-person-2".to_string()],
    ));
    state_repo.set(state2).await.unwrap();

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        create_lock_service(),
    );

    let results = merge_service.resume_all().await.unwrap();

    assert_eq!(results.len(), 2);

    // Both should succeed
    for (_, result) in &results {
        assert!(result.is_ok());
    }

    // Verify both are now completed
    let final_state1 = state_repo.get("merge-1").await.unwrap().unwrap();
    let final_state2 = state_repo.get("merge-2").await.unwrap().unwrap();
    assert_eq!(final_state1.step(), MergeStep::Completed);
    assert_eq!(final_state2.step(), MergeStep::Completed);
}

/// Test: Fail at set_merging_source (after TargetMarked), resume completes
#[tokio::test]
async fn test_service_restart_fail_at_sources_marked() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 20001;

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // --- First service: fails at set_merging_source ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        distinct_ids_api.set_merging_source_error("connection lost");

        let service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo.clone(),
            create_lock_service(),
        );

        let result = service
            .merge(
                "merge-1",
                target_distinct_id,
                &[source_distinct_id.to_string()],
                version,
            )
            .await;

        assert!(result.is_err());
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::TargetMarked);
    }

    // --- Second service: resume completes ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        // Set up responses for resumed operations
        distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: source_person_uuid.to_string(),
        }]);

        let target_person = create_person(target_person_uuid, vec![]);
        let source_person = create_person(source_person_uuid, vec![]);
        let mut source_persons_map = HashMap::new();
        source_persons_map.insert(source_person_uuid.to_string(), source_person);
        properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
        properties_api.set_merge_person_properties_result(Ok(()));

        let service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            create_lock_service(),
        );

        let results = service.resume_all().await.unwrap();
        assert_eq!(results.len(), 1);
        assert!(results[0].1.is_ok(), "Resume failed: {:?}", results[0].1);

        let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(final_state.step(), MergeStep::Completed);

        // Verify set_merging_source was called on resume
        assert_eq!(distinct_ids_api.get_set_merging_source_calls().len(), 1);
        // Verify set_merging_target was NOT called (already done)
        assert!(distinct_ids_api.get_set_merging_target_calls().is_empty());
    }
}

/// Test: Fail at get_persons_for_merge (after SourcesMarked), resume completes
#[tokio::test]
async fn test_service_restart_fail_at_properties_merged() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 20002;

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // --- First service: fails at get_persons_for_merge ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: source_person_uuid.to_string(),
        }]);
        properties_api.set_get_persons_for_merge_error("database timeout");

        let service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo.clone(),
            create_lock_service(),
        );

        let result = service
            .merge(
                "merge-1",
                target_distinct_id,
                &[source_distinct_id.to_string()],
                version,
            )
            .await;

        assert!(result.is_err());
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::SourcesMarked);
        assert_eq!(
            state.source_person_uuids().unwrap(),
            &[source_person_uuid.to_string()]
        );
    }

    // --- Second service: resume completes ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        let target_person = create_person(target_person_uuid, vec![]);
        let source_person = create_person(source_person_uuid, vec![]);
        let mut source_persons_map = HashMap::new();
        source_persons_map.insert(source_person_uuid.to_string(), source_person);
        properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
        properties_api.set_merge_person_properties_result(Ok(()));

        let service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            create_lock_service(),
        );

        let results = service.resume_all().await.unwrap();
        assert_eq!(results.len(), 1);
        assert!(results[0].1.is_ok(), "Resume failed: {:?}", results[0].1);

        let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(final_state.step(), MergeStep::Completed);

        // Verify properties API was called on resume
        assert_eq!(properties_api.get_persons_for_merge_call_count(), 1);
        // Verify marking APIs were NOT called (already done)
        assert!(distinct_ids_api.get_set_merging_target_calls().is_empty());
        assert!(distinct_ids_api.get_set_merging_source_calls().is_empty());
    }
}

/// Test: Fail at set_merged for sources (after PropertiesMerged), resume completes
#[tokio::test]
async fn test_service_restart_fail_at_distinct_ids_merged() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 20003;

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // --- First service: fails at set_merged for sources ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockSetMergedFailsOnceApi::new(
            target_distinct_id,
            target_person_uuid,
            source_distinct_id,
            source_person_uuid,
        ));

        let target_person = create_person(target_person_uuid, vec![]);
        let source_person = create_person(source_person_uuid, vec![]);
        let mut source_persons_map = HashMap::new();
        source_persons_map.insert(source_person_uuid.to_string(), source_person);
        properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
        properties_api.set_merge_person_properties_result(Ok(()));

        let service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo.clone(),
            create_lock_service(),
        );

        let result = service
            .merge(
                "merge-1",
                target_distinct_id,
                &[source_distinct_id.to_string()],
                version,
            )
            .await;

        assert!(result.is_err());
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::PropertiesMerged);
    }

    // --- Second service: resume completes ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        let service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            create_lock_service(),
        );

        let results = service.resume_all().await.unwrap();
        assert_eq!(results.len(), 1);
        assert!(results[0].1.is_ok(), "Resume failed: {:?}", results[0].1);

        let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(final_state.step(), MergeStep::Completed);

        // Verify set_merged was called on resume (for source and target)
        assert_eq!(distinct_ids_api.get_set_merged_calls().len(), 2);
        // Verify properties API was NOT called (already done)
        assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);
    }
}

/// Test: Fail at delete_person (after TargetCleared), resume completes
#[tokio::test]
async fn test_service_restart_fail_at_delete_person() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 20004;

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // --- First service: fails at delete_person ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
            distinct_id: target_distinct_id.to_string(),
            person_uuid: target_person_uuid.to_string(),
        });
        distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
            distinct_id: source_distinct_id.to_string(),
            person_uuid: source_person_uuid.to_string(),
        }]);

        let target_person = create_person(target_person_uuid, vec![]);
        let source_person = create_person(source_person_uuid, vec![]);
        let mut source_persons_map = HashMap::new();
        source_persons_map.insert(source_person_uuid.to_string(), source_person);
        properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
        properties_api.set_merge_person_properties_result(Ok(()));
        properties_api.set_delete_person_error("storage failure");

        let service = PersonMergeService::new(
            properties_api,
            distinct_ids_api,
            state_repo.clone(),
            create_lock_service(),
        );

        let result = service
            .merge(
                "merge-1",
                target_distinct_id,
                &[source_distinct_id.to_string()],
                version,
            )
            .await;

        assert!(result.is_err());
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::TargetCleared);
    }

    // --- Second service: resume completes ---
    {
        let properties_api = Arc::new(MockPersonPropertiesApi::new());
        let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

        let service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            create_lock_service(),
        );

        let results = service.resume_all().await.unwrap();
        assert_eq!(results.len(), 1);
        assert!(results[0].1.is_ok(), "Resume failed: {:?}", results[0].1);

        let final_state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(final_state.step(), MergeStep::Completed);

        // Verify delete_person was called on resume
        assert_eq!(properties_api.get_delete_person_calls().len(), 1);
        // Verify other APIs were NOT called (already done)
        assert!(distinct_ids_api.get_set_merging_target_calls().is_empty());
        assert!(distinct_ids_api.get_set_merged_calls().is_empty());
    }
}

// =============================================================================
// Lock acquisition tests
// =============================================================================

use crate::lock::{BreakpointedLockService, InjectedLockError};

#[tokio::test]
async fn test_lock_failure_prevents_api_calls_at_started_step() {
    // This test verifies that lock is acquired BEFORE any API calls at the Started step
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let version = 30001;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject a timeout error for the lock
    lock_service
        .inject_error(InjectedLockError::timeout("merge-1"))
        .await;

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo,
        lock_service,
    );

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await;

    // Lock acquisition should fail
    assert!(result.is_err());

    // No API calls should have been made since lock acquisition failed first
    assert!(distinct_ids_api.get_set_merging_target_calls().is_empty());
    assert!(distinct_ids_api.get_set_merging_source_calls().is_empty());
}

#[tokio::test]
async fn test_lock_timeout_at_started_step_returns_error() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let version = 30002;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject a timeout error
    lock_service
        .inject_error(InjectedLockError::timeout("merge-1"))
        .await;

    let merge_service =
        PersonMergeService::new(properties_api, distinct_ids_api, state_repo, lock_service);

    let result = merge_service
        .merge(
            "merge-1",
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await;

    assert!(result.is_err());
    assert!(result.unwrap_err().to_string().contains("timed out"));
}

#[tokio::test]
async fn test_lock_lost_at_sources_marked_step_returns_error() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 30003;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Pre-populate state at SourcesMarked step
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::SourcesMarked(create_sources_marked_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject lock lost error when resuming
    lock_service
        .inject_error(InjectedLockError::lock_lost("merge-1"))
        .await;

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api,
        state_repo.clone(),
        lock_service,
    );

    let results = merge_service.resume_all().await.unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_err());
    assert!(results[0]
        .1
        .as_ref()
        .unwrap_err()
        .to_string()
        .contains("lost"));

    // No API calls should have been made
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 0);
}

#[tokio::test]
async fn test_lock_lost_at_properties_merged_step_returns_error() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 30004;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Pre-populate state at PropertiesMerged step
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::PropertiesMerged(create_properties_merged_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject lock lost error
    lock_service
        .inject_error(InjectedLockError::lock_lost("merge-1"))
        .await;

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        lock_service,
    );

    let results = merge_service.resume_all().await.unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_err());
    assert!(results[0]
        .1
        .as_ref()
        .unwrap_err()
        .to_string()
        .contains("lost"));

    // No set_merged calls should have been made
    assert!(distinct_ids_api.get_set_merged_calls().is_empty());
}

#[tokio::test]
async fn test_lock_lost_at_distinct_ids_merged_step_returns_error() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 30005;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Pre-populate state at DistinctIdsMerged step
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::DistinctIdsMerged(create_distinct_ids_merged_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject lock lost error
    lock_service
        .inject_error(InjectedLockError::lock_lost("merge-1"))
        .await;

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        lock_service,
    );

    let results = merge_service.resume_all().await.unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_err());

    // No API calls should have been made
    assert!(distinct_ids_api.get_set_merged_calls().is_empty());
}

#[tokio::test]
async fn test_lock_lost_at_target_cleared_step_returns_error() {
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 30006;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());
    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // Pre-populate state at TargetCleared step
    let mut valid_sources = HashMap::new();
    valid_sources.insert(
        source_distinct_id.to_string(),
        source_person_uuid.to_string(),
    );
    let initial_state = MergeState::TargetCleared(create_target_cleared_state(
        "merge-1",
        target_distinct_id,
        vec![source_distinct_id.to_string()],
        version,
        target_person_uuid,
        valid_sources,
        vec![source_person_uuid.to_string()],
    ));
    state_repo.set(initial_state).await.unwrap();

    let inner_lock = crate::lock::InMemoryLockService::new();
    let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

    // Inject lock lost error
    lock_service
        .inject_error(InjectedLockError::lock_lost("merge-1"))
        .await;

    let merge_service = PersonMergeService::new(
        properties_api.clone(),
        distinct_ids_api.clone(),
        state_repo.clone(),
        lock_service,
    );

    let results = merge_service.resume_all().await.unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].1.is_err());

    // No delete calls should have been made
    assert!(properties_api.get_delete_person_calls().is_empty());
}

#[tokio::test]
async fn test_lock_acquired_before_each_step_when_resuming() {
    // This test verifies that lock is acquired at each step by injecting errors at different steps
    let target_distinct_id = "target-distinct-id";
    let source_distinct_id = "source-distinct-id";
    let target_person_uuid = "target-person-uuid";
    let source_person_uuid = "source-person-uuid";
    let version = 30007;

    let properties_api = Arc::new(MockPersonPropertiesApi::new());
    let distinct_ids_api = Arc::new(MockPersonDistinctIdsApi::new());

    // Set up successful responses for all API calls
    distinct_ids_api.set_merging_target_result(SetMergingTargetResult::Ok {
        distinct_id: target_distinct_id.to_string(),
        person_uuid: target_person_uuid.to_string(),
    });
    distinct_ids_api.set_merging_source_result(vec![SetMergingSourceResult::Ok {
        distinct_id: source_distinct_id.to_string(),
        person_uuid: source_person_uuid.to_string(),
    }]);

    let target_person = create_person(target_person_uuid, vec![]);
    let source_person = create_person(source_person_uuid, vec![]);
    let mut source_persons_map = HashMap::new();
    source_persons_map.insert(source_person_uuid.to_string(), source_person);
    properties_api.set_get_persons_for_merge_result(target_person, source_persons_map);
    properties_api.set_merge_person_properties_result(Ok(()));

    let state_repo = Arc::new(InMemoryMergeStateRepository::new());

    // First run: should fail on first lock acquisition, leaving state at Started
    {
        let inner_lock = crate::lock::InMemoryLockService::new();
        let lock_service = Arc::new(BreakpointedLockService::new(inner_lock));

        lock_service
            .inject_error(InjectedLockError::timeout("merge-1"))
            .await;

        let merge_service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            lock_service,
        );

        let result = merge_service
            .merge(
                "merge-1",
                target_distinct_id,
                &[source_distinct_id.to_string()],
                version,
            )
            .await;

        assert!(result.is_err());
        // State should be at Started since lock acquisition failed before any work
        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::Started);
    }

    // Second run: lock works, complete the merge
    {
        let lock_service = create_lock_service();

        let merge_service = PersonMergeService::new(
            properties_api.clone(),
            distinct_ids_api.clone(),
            state_repo.clone(),
            lock_service,
        );

        let results = merge_service.resume_all().await.unwrap();
        assert_eq!(results.len(), 1);
        assert!(results[0].1.is_ok());

        let state = state_repo.get("merge-1").await.unwrap().unwrap();
        assert_eq!(state.step(), MergeStep::Completed);
    }
}

/// Mock that fails on the first set_merged call, succeeds after
struct MockSetMergedFailsOnceApi {
    target_distinct_id: String,
    target_person_uuid: String,
    source_distinct_id: String,
    source_person_uuid: String,
    set_merged_call_count: Mutex<usize>,
}

impl MockSetMergedFailsOnceApi {
    fn new(
        target_distinct_id: &str,
        target_person_uuid: &str,
        source_distinct_id: &str,
        source_person_uuid: &str,
    ) -> Self {
        Self {
            target_distinct_id: target_distinct_id.to_string(),
            target_person_uuid: target_person_uuid.to_string(),
            source_distinct_id: source_distinct_id.to_string(),
            source_person_uuid: source_person_uuid.to_string(),
            set_merged_call_count: Mutex::new(0),
        }
    }
}

#[async_trait]
impl PersonDistinctIdsApi for MockSetMergedFailsOnceApi {
    async fn add_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn delete_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_person_uuid(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_merging_source(
        &self,
        _distinct_ids: &[String],
        _version: i64,
    ) -> ApiResult<Vec<SetMergingSourceResult>> {
        Ok(vec![SetMergingSourceResult::Ok {
            distinct_id: self.source_distinct_id.clone(),
            person_uuid: self.source_person_uuid.clone(),
        }])
    }

    async fn set_merging_target(
        &self,
        _distinct_id: &str,
        _version: i64,
    ) -> ApiResult<SetMergingTargetResult> {
        Ok(SetMergingTargetResult::Ok {
            distinct_id: self.target_distinct_id.clone(),
            person_uuid: self.target_person_uuid.clone(),
        })
    }

    async fn set_merged(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        let mut count = self.set_merged_call_count.lock().unwrap();
        *count += 1;
        if *count == 1 {
            return Err("set_merged failed".into());
        }
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }
}
