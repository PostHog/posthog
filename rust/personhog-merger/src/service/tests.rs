use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;

use crate::state::InMemoryMergeStateRepository;
use crate::testing::Breakpoint;
use crate::types::{
    ApiResult, DistinctIdInfo, GetPersonsForMergeResult, MergeConflict, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
    VersionedProperty,
};
use crate::PersonMergeService;

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
        *self.get_persons_for_merge_result.lock().unwrap() =
            Some(Ok(GetPersonsForMergeResult {
                target_person,
                source_persons,
            }));
    }

    fn set_merge_person_properties_result(&self, result: ApiResult<()>) {
        *self.merge_person_properties_result.lock().unwrap() = Some(result);
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

        Ok(())
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

    fn set_merging_source_result(&self, result: Vec<SetMergingSourceResult>) {
        *self.set_merging_source_result.lock().unwrap() = Some(Ok(result));
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let result = merge_service
        .merge(
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
    let source_person_uuids = vec!["source-person-1", "source-person-2", "source-person-3"];
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let result = merge_service
        .merge(target_distinct_id, &source_distinct_ids, version)
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let _result = merge_service
        .merge(target_distinct_id, &source_distinct_ids, version)
        .await
        .unwrap();

    // Should only fetch the person once even though two distinct IDs reference it
    assert_eq!(properties_api.get_persons_for_merge_call_count(), 1);
    assert_eq!(properties_api.merge_person_properties_call_count(), 1);

    // Should only delete the person once (deduplicated)
    let delete_person_calls = properties_api.get_delete_person_calls();
    assert_eq!(delete_person_calls.len(), 1);
    assert_eq!(delete_person_calls[0].person_uuid, shared_source_person_uuid);
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let _result = merge_service
        .merge(
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let result = merge_service
        .merge(target_distinct_id, &source_distinct_ids, version)
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
    assert!(!set_merged_calls
        .iter()
        .any(|c| c.distinct_id == "source-2"));
    assert!(!set_merged_calls
        .iter()
        .any(|c| c.distinct_id == "source-3"));
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let result = merge_service
        .merge(target_distinct_id, &source_distinct_ids, version)
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
    let merge_service = PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo);

    let result = merge_service
        .merge(target_distinct_id, &source_distinct_ids, version)
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
    use crate::state::{MergeStateRepository, MergeStep};

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
    let merge_service =
        PersonMergeService::new(properties_api.clone(), distinct_ids_api.clone(), state_repo.clone());

    let result = merge_service
        .merge(
            target_distinct_id,
            &[source_distinct_id.to_string()],
            version,
        )
        .await
        .unwrap();

    assert!(!result.merged.is_empty());
    assert!(result.conflicts.is_empty());

    // Verify final state
    let final_state = state_repo.get(target_person_uuid).await.unwrap();
    assert!(final_state.is_some());

    let state = final_state.unwrap();
    assert_eq!(state.target_person_uuid, target_person_uuid);
    assert_eq!(state.target_distinct_id, target_distinct_id);
    assert_eq!(state.source_distinct_ids, vec![source_distinct_id]);
    assert_eq!(state.source_person_uuids, vec![source_person_uuid]);
    assert_eq!(state.step, MergeStep::Completed);
    assert_eq!(state.version, version);
    assert!(state.error.is_none());

    // Verify valid_sources mapping is populated
    assert_eq!(state.valid_sources.len(), 1);
    assert_eq!(
        state.valid_sources.get(source_distinct_id),
        Some(&source_person_uuid.to_string())
    );
    assert_eq!(
        state.valid_source_distinct_ids(),
        vec![source_distinct_id.to_string()]
    );
}
