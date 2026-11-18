use std::sync::Arc;

use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{GetFlagContextRequest, GroupIdentifier};
use tonic::{Code, Request};

use super::super::PersonHogReplicaService;
use super::followed::{follower_reads, own_partition};
use super::mocks::{PopulatedStorage, SuccessStorage};
use crate::service::PARTITION_HEADER;

fn request(person_id: Option<i64>) -> Request<GetFlagContextRequest> {
    Request::new(GetFlagContextRequest {
        team_id: 1,
        person_id,
        static_cohort_ids: vec![7],
        group_identifiers: vec![GroupIdentifier {
            group_type_index: 0,
            group_key: "acme".to_string(),
        }],
        ..Default::default()
    })
}

#[tokio::test]
async fn a_flag_context_holds_the_person_their_cohorts_and_the_groups() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let context = service
        .get_flag_context(request(Some(42)))
        .await
        .expect("served")
        .into_inner();

    assert_eq!(context.person.map(|person| person.id), Some(42));
    assert_eq!(context.cohort_memberships.len(), 1);
    assert_eq!(context.groups.len(), 1);
}

#[tokio::test]
async fn a_person_outside_the_team_gets_no_cohort_memberships() {
    // This storage finds no person for the team, and answers for any cohort id.
    let service = PersonHogReplicaService::new(Arc::new(SuccessStorage));

    let context = service
        .get_flag_context(request(Some(42)))
        .await
        .expect("served")
        .into_inner();

    assert!(context.person.is_none());
    assert!(context.cohort_memberships.is_empty());
}

#[tokio::test]
async fn a_flag_context_without_a_person_holds_only_the_groups() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let context = service
        .get_flag_context(request(None))
        .await
        .expect("served")
        .into_inner();

    assert!(context.person.is_none());
    assert!(context.cohort_memberships.is_empty());
    assert_eq!(context.groups.len(), 1);
}

#[tokio::test]
async fn a_flag_context_reads_its_person_from_a_follower_only_when_routed_to_one() {
    let service =
        PersonHogReplicaService::new(Arc::new(PopulatedStorage)).with_follower(follower_reads());
    let mut routed = request(Some(42));
    routed.metadata_mut().insert(
        PARTITION_HEADER,
        own_partition().to_string().parse().expect("header value"),
    );

    // This follower follows nothing, so a routed person is refused, not read from Postgres.
    let refused = service.get_flag_context(routed).await;
    let unrouted = service.get_flag_context(request(Some(42))).await;

    assert_eq!(refused.unwrap_err().code(), Code::Unavailable);
    assert!(unrouted.expect("served").into_inner().person.is_some());
}
