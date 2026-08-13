mod common;

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use common::TestContext;
use tonic::{Code, Request, Status};

use personhog_identity::leader::PropertyWriter;
use personhog_identity::lifecycle::merge::{MergeDriver, MergeOpExecutor};
use personhog_identity::service::merge::MergeEntrance;
use personhog_identity::service::validation::RequestLimits;
use personhog_identity::service::PersonHogIdentityService;
use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentity;
use personhog_proto::personhog::identity::v1::{
    GetDistinctIdsForPersonsRequest, GetOrCreatePersonByDistinctIdRequest, GetOrCreatePersonEntry,
    GetOrCreatePersonsByDistinctIdsRequest, GetPersonsByDistinctIdsRequest, PersonKey,
};
use personhog_proto::personhog::types::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};

/// Records calls and replays queued responses; defaults to an "updated, no
/// person payload" ack when the queue is empty.
#[derive(Default)]
struct MockPropertyWriter {
    calls: Mutex<Vec<UpdatePersonPropertiesRequest>>,
    responses: Mutex<VecDeque<Result<UpdatePersonPropertiesResponse, Status>>>,
}

impl MockPropertyWriter {
    fn queue(&self, response: Result<UpdatePersonPropertiesResponse, Status>) {
        self.responses.lock().unwrap().push_back(response);
    }

    fn calls(&self) -> Vec<UpdatePersonPropertiesRequest> {
        self.calls.lock().unwrap().clone()
    }
}

#[async_trait]
impl PropertyWriter for MockPropertyWriter {
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        self.calls.lock().unwrap().push(request);
        self.responses
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or_else(|| {
                Ok(UpdatePersonPropertiesResponse {
                    person: None,
                    updated: true,
                })
            })
    }
}

struct ServiceTestContext {
    ctx: TestContext,
    writer: Arc<MockPropertyWriter>,
    service: PersonHogIdentityService,
}

impl ServiceTestContext {
    async fn new() -> Self {
        Self::with_limits(RequestLimits {
            max_batch_size: 250,
            max_distinct_id_length: 400,
            max_extra_distinct_ids: 5000,
        })
        .await
    }

    async fn with_limits(limits: RequestLimits) -> Self {
        let ctx = TestContext::new().await;
        let writer = Arc::new(MockPropertyWriter::default());
        let engine = Arc::new(ctx.engine());
        let merge = MergeEntrance::new(
            ctx.storage.clone(),
            writer.clone(),
            MergeOpExecutor::new(
                engine,
                MergeDriver::new(Arc::new(common::UnusedLeader), ctx.tables.clone()),
            ),
        );
        let service =
            PersonHogIdentityService::new(ctx.storage.clone(), writer.clone(), limits, merge);
        Self {
            ctx,
            writer,
            service,
        }
    }

    fn entry(&self, distinct_id: &str) -> GetOrCreatePersonEntry {
        GetOrCreatePersonEntry {
            team_id: self.ctx.team_id,
            distinct_id: distinct_id.to_string(),
            extra_distinct_ids: vec![],
            event_name: "$identify".to_string(),
            set_properties: Vec::new(),
            set_once_properties: Vec::new(),
            created_at: 0,
            is_identified: false,
        }
    }

    async fn get_or_create_single(
        &self,
        entry: GetOrCreatePersonEntry,
    ) -> Result<(Option<i64>, bool), Status> {
        let response = self
            .service
            .get_or_create_person_by_distinct_id(Request::new(
                GetOrCreatePersonByDistinctIdRequest { entry: Some(entry) },
            ))
            .await?
            .into_inner();
        Ok((response.person.map(|p| p.id), response.created))
    }
}

#[tokio::test]
async fn creates_person_and_applies_initial_properties_through_leader() {
    let t = ServiceTestContext::new().await;
    let mut entry = t.entry("svc-user-1");
    entry.set_properties = br#"{"plan":"free"}"#.to_vec();

    let (person_id, created) = t
        .get_or_create_single(entry)
        .await
        .expect("rpc should succeed");
    assert!(created);
    let person_id = person_id.expect("person should be returned");

    let calls = t.writer.calls();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].team_id, t.ctx.team_id);
    assert_eq!(calls[0].person_id, person_id);
    assert_eq!(calls[0].event_name, "$identify");
    assert_eq!(calls[0].set_properties, br#"{"plan":"free"}"#.to_vec());

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn create_without_properties_skips_the_leader() {
    let t = ServiceTestContext::new().await;

    let (_, created) = t
        .get_or_create_single(t.entry("svc-user-2"))
        .await
        .expect("rpc should succeed");
    assert!(created);
    assert!(t.writer.calls().is_empty());

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn existing_person_is_returned_without_leader_call() {
    let t = ServiceTestContext::new().await;
    let existing_id = t.ctx.insert_person_with_distinct_id("svc-user-3").await;

    let mut entry = t.entry("svc-user-3");
    entry.set_properties = br#"{"plan":"pro"}"#.to_vec();
    let (person_id, created) = t
        .get_or_create_single(entry)
        .await
        .expect("rpc should succeed");

    assert!(!created);
    assert_eq!(person_id, Some(existing_id));
    // The exists branch never applies properties — the caller does, through
    // the normal UpdatePersonProperties path.
    assert!(t.writer.calls().is_empty());

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn leader_failure_fails_the_key_but_keeps_the_stub_for_retry() {
    let t = ServiceTestContext::new().await;
    t.writer.queue(Err(Status::unavailable("leader down")));

    let mut entry = t.entry("svc-user-4");
    entry.set_properties = br#"{"a":1}"#.to_vec();
    let status = t
        .get_or_create_single(entry.clone())
        .await
        .expect_err("rpc should fail");
    assert_eq!(status.code(), Code::Unavailable);

    // The retried key resolves to the committed stub and reports created =
    // false, so the caller applies properties through the update path.
    let (_, created) = t
        .get_or_create_single(entry)
        .await
        .expect("retry should succeed");
    assert!(!created);

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn batch_returns_per_key_outcomes_in_order() {
    let t = ServiceTestContext::new().await;
    let existing_id = t
        .ctx
        .insert_person_with_distinct_id("svc-batch-existing")
        .await;

    let invalid = GetOrCreatePersonEntry {
        distinct_id: String::new(),
        ..t.entry("")
    };
    let response = t
        .service
        .get_or_create_persons_by_distinct_ids(Request::new(
            GetOrCreatePersonsByDistinctIdsRequest {
                entries: vec![
                    t.entry("svc-batch-existing"),
                    t.entry("svc-batch-new"),
                    invalid,
                ],
            },
        ))
        .await
        .expect("batch rpc should succeed")
        .into_inner();

    assert_eq!(response.results.len(), 3);

    assert_eq!(response.results[0].distinct_id, "svc-batch-existing");
    assert!(!response.results[0].created);
    assert_eq!(
        response.results[0].person.as_ref().map(|p| p.id),
        Some(existing_id)
    );

    assert_eq!(response.results[1].distinct_id, "svc-batch-new");
    assert!(response.results[1].created);
    assert!(response.results[1].person.is_some());

    assert!(response.results[2].person.is_none());
    assert!(response.results[2]
        .error
        .as_deref()
        .unwrap()
        .contains("distinct_id"));

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn duplicate_keys_in_batch_create_exactly_once() {
    let t = ServiceTestContext::new().await;

    let response = t
        .service
        .get_or_create_persons_by_distinct_ids(Request::new(
            GetOrCreatePersonsByDistinctIdsRequest {
                entries: vec![t.entry("svc-dup"), t.entry("svc-dup")],
            },
        ))
        .await
        .expect("batch rpc should succeed")
        .into_inner();

    assert_eq!(response.results.len(), 2);
    assert!(response.results[0].created);
    assert!(!response.results[1].created);
    assert_eq!(
        response.results[0].person.as_ref().map(|p| p.id),
        response.results[1].person.as_ref().map(|p| p.id)
    );

    t.ctx.cleanup().await.ok();
}

#[tokio::test]
async fn batch_over_limit_is_rejected() {
    let t = ServiceTestContext::with_limits(RequestLimits {
        max_batch_size: 2,
        max_distinct_id_length: 400,
        max_extra_distinct_ids: 5000,
    })
    .await;

    let status = t
        .service
        .get_or_create_persons_by_distinct_ids(Request::new(
            GetOrCreatePersonsByDistinctIdsRequest {
                entries: vec![t.entry("a"), t.entry("b"), t.entry("c")],
            },
        ))
        .await
        .expect_err("batch should be rejected");
    assert_eq!(status.code(), Code::InvalidArgument);

    t.ctx.cleanup().await.ok();
}

/// The resolve-only RPC answers exactly like get-or-create for existing
/// persons and answers absence instead of creating for unknown keys — the
/// contract the node store's fetch paths rely on.
#[tokio::test]
async fn resolve_returns_existing_persons_and_absence_without_creating() {
    let t = ServiceTestContext::new().await;
    t.get_or_create_single(t.entry("known-id"))
        .await
        .expect("seed person");

    let response = t
        .service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            keys: vec![
                PersonKey {
                    team_id: t.ctx.team_id,
                    distinct_id: "known-id".to_string(),
                },
                PersonKey {
                    team_id: t.ctx.team_id,
                    distinct_id: "never-seen".to_string(),
                },
            ],
        }))
        .await
        .expect("resolve must succeed")
        .into_inner();

    assert_eq!(response.results.len(), 2);
    let known = &response.results[0];
    assert_eq!(known.distinct_id, "known-id");
    let person = known.person.as_ref().expect("known id resolves");
    assert!(person.id > 0);

    let unknown = &response.results[1];
    assert_eq!(unknown.distinct_id, "never-seen");
    assert!(unknown.person.is_none(), "resolve must not create");

    // A second resolve still finds nothing for the unknown key — the
    // first call created no row.
    let again = t
        .service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            keys: vec![PersonKey {
                team_id: t.ctx.team_id,
                distinct_id: "never-seen".to_string(),
            }],
        }))
        .await
        .expect("resolve must succeed")
        .into_inner();
    assert!(again.results[0].person.is_none());
}

/// The identity-side expansion mirrors the replica RPC's contract:
/// grouped per person, live rows only, and the per-person limit keeps
/// identified ids over anonymous ones.
#[tokio::test]
async fn distinct_id_expansion_groups_per_person_on_the_primary() {
    let t = ServiceTestContext::new().await;
    let (person_id, _) = t
        .get_or_create_single(t.entry("expansion-primary"))
        .await
        .expect("seed person");
    let person_id = person_id.expect("seeded person has an id");

    let response = t
        .service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: t.ctx.team_id,
            person_ids: vec![person_id, 999_999_999],
            limit_per_person: None,
        }))
        .await
        .expect("expansion must succeed")
        .into_inner();

    assert_eq!(
        response.person_distinct_ids.len(),
        1,
        "absent ids yield no group"
    );
    let group = &response.person_distinct_ids[0];
    assert_eq!(group.person_id, person_id);
    assert_eq!(group.distinct_ids.len(), 1);
    assert_eq!(group.distinct_ids[0].distinct_id, "expansion-primary");
}

/// Duplicate keys in one resolve request each get the person — the node
/// prefetch sends per-event keys where hot distinct ids repeat.
#[tokio::test]
async fn duplicate_resolve_keys_each_resolve() {
    let t = ServiceTestContext::new().await;
    t.get_or_create_single(t.entry("dup-id"))
        .await
        .expect("seed");
    let key = || PersonKey {
        team_id: t.ctx.team_id,
        distinct_id: "dup-id".to_string(),
    };
    let response = t
        .service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            keys: vec![key(), key(), key()],
        }))
        .await
        .expect("resolve must succeed")
        .into_inner();
    assert_eq!(response.results.len(), 3);
    for result in &response.results {
        assert!(result.person.is_some(), "every occurrence must resolve");
    }
}

/// A team_id above i32::MAX would wrap at the int4 column and read
/// another tenant's rows; both new RPCs must refuse it at the boundary.
#[tokio::test]
async fn new_rpcs_reject_wrapping_team_ids() {
    let t = ServiceTestContext::new().await;
    let bad_team = (i32::MAX as i64) + 2;

    let resolve = t
        .service
        .get_persons_by_distinct_ids(Request::new(GetPersonsByDistinctIdsRequest {
            keys: vec![PersonKey {
                team_id: bad_team,
                distinct_id: "x".to_string(),
            }],
        }))
        .await;
    assert_eq!(resolve.unwrap_err().code(), Code::InvalidArgument);

    let expand = t
        .service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: bad_team,
            person_ids: vec![1],
            limit_per_person: None,
        }))
        .await;
    assert_eq!(expand.unwrap_err().code(), Code::InvalidArgument);
}

/// A repeated person id must not multiply its rows: the limited query
/// runs its lateral lookup per occurrence, so without dedupe one group
/// would carry duplicates and exceed the advertised per-person limit.
#[tokio::test]
async fn repeated_person_ids_do_not_exceed_the_per_person_limit() {
    let t = ServiceTestContext::new().await;
    let mut entry = t.entry("dup-expand-primary");
    entry.extra_distinct_ids = vec!["dup-expand-extra".to_string()];
    let (person_id, _) = t.get_or_create_single(entry).await.expect("seed");
    let person_id = person_id.expect("seeded person has an id");

    let response = t
        .service
        .get_distinct_ids_for_persons(Request::new(GetDistinctIdsForPersonsRequest {
            team_id: t.ctx.team_id,
            person_ids: vec![person_id, person_id, person_id],
            limit_per_person: Some(1),
        }))
        .await
        .expect("expansion must succeed")
        .into_inner();

    assert_eq!(response.person_distinct_ids.len(), 1);
    let group = &response.person_distinct_ids[0];
    assert_eq!(
        group.distinct_ids.len(),
        1,
        "the per-person limit must hold under repeated ids"
    );
}
