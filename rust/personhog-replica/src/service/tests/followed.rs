use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use personhog_coordination::changelog::LiveChangelog;
use personhog_coordination::types::ChangelogConfig;
use personhog_leader::cache::{DirtyIndex, PartitionedCache};
use personhog_leader::follow::{FollowConfig, Follower};
use personhog_leader::recovery::{ChangelogRecovery, RecoveryConfig};
use personhog_leader::warming::{WarmClientPools, WarmingConfig, WarmingRetryPolicy};
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{GetPersonByUuidRequest, GetPersonRequest};
use rstest::rstest;
use tonic::{Code, Request};

use super::mocks::PopulatedStorage;
use crate::service::{
    FollowerReads, PersonHogReplicaService, EPOCH_HEADER, PARTITION_HEADER, PERSON_ID_HEADER,
};

const PARTITIONS: u32 = 8;
const EPOCH: u64 = 3;

/// A follower that follows nothing, so every partition is behind. No broker is dialed.
fn follower_reads() -> FollowerReads {
    let kafka = KafkaConfig::init_from_hashmap(&HashMap::new()).expect("kafka config");
    let warming = WarmingConfig {
        kafka: kafka.clone(),
        pod_name: "test".to_string(),
        writer_consumer_group: "writers".to_string(),
        committed_offsets_timeout: Duration::from_secs(1),
        fetch_watermarks_timeout: Duration::from_secs(1),
        recv_timeout: Duration::from_secs(1),
        retry: WarmingRetryPolicy {
            max_attempts: 1,
            initial_backoff: Duration::from_millis(1),
            max_backoff: Duration::from_millis(1),
        },
    };
    let pools = Arc::new(WarmClientPools::new(&kafka, "test", "writers"));
    let recovery = ChangelogRecovery::new(RecoveryConfig {
        kafka,
        pod_name: "test".to_string(),
        recv_timeout: Duration::from_secs(1),
        pool_size: 1,
        cluster: None,
    })
    .expect("recovery");
    let follower = Follower::new(
        FollowConfig {
            staleness_threshold: Duration::from_millis(500),
            end_check_interval: Duration::from_millis(100),
            min_warm: Duration::ZERO,
        },
        warming,
        pools,
        Arc::new(PartitionedCache::new(1 << 20)),
        Arc::new(DirtyIndex::new(1000)),
        Arc::new(recovery),
    );
    let changelog = LiveChangelog::new(ChangelogConfig {
        topic: "changelog".to_string(),
        partitions: PARTITIONS,
        cluster: None,
        epoch: EPOCH,
        writer_group: "writers".to_string(),
        retire_groups: Vec::new(),
        draining: Vec::new(),
    });
    FollowerReads {
        follower: Arc::new(follower),
        changelog,
        pool: sqlx::postgres::PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("lazy pool"),
        table: "posthog_person".to_string(),
    }
}

fn other_partition() -> u64 {
    let own = personhog_common::partitioning::partition_for_person(1, 42, PARTITIONS);
    u64::from((own + 1) % PARTITIONS)
}

#[rstest]
#[case::behind(&[(PARTITION_HEADER, own_partition())], Code::Unavailable, "not current")]
#[case::routed_under_a_newer_config(
    &[(PARTITION_HEADER, own_partition()), (EPOCH_HEADER, EPOCH + 1)],
    Code::Unavailable,
    "changelog config"
)]
#[case::routed_to_another_partition(
    &[(PARTITION_HEADER, other_partition())],
    Code::FailedPrecondition,
    "another partition"
)]
#[tokio::test]
async fn a_follower_refuses_a_person_it_cannot_serve_fresh(
    #[case] headers: &[(&'static str, u64)],
    #[case] expected: Code,
    #[case] reason: &str,
) {
    let service =
        PersonHogReplicaService::new(Arc::new(PopulatedStorage)).with_follower(follower_reads());

    let status = service
        .get_person(stamped(by_id(), headers))
        .await
        .unwrap_err();

    assert_eq!(status.code(), expected);
    assert!(status.message().contains(reason), "{}", status.message());
}

fn stamped<T>(message: T, headers: &[(&'static str, u64)]) -> Request<T> {
    let mut request = Request::new(message);
    for (name, value) in headers {
        request
            .metadata_mut()
            .insert(*name, value.to_string().parse().expect("header value"));
    }
    request
}

fn own_partition() -> u64 {
    u64::from(personhog_common::partitioning::partition_for_person(
        1, 42, PARTITIONS,
    ))
}

fn by_id() -> GetPersonRequest {
    GetPersonRequest {
        team_id: 1,
        person_id: 42,
        ..Default::default()
    }
}

fn by_uuid() -> GetPersonByUuidRequest {
    GetPersonByUuidRequest {
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        ..Default::default()
    }
}

#[tokio::test]
async fn a_single_person_read_routed_to_a_follower_is_never_answered_from_postgres() {
    let service =
        PersonHogReplicaService::new(Arc::new(PopulatedStorage)).with_follower(follower_reads());
    let routed = [(PARTITION_HEADER, own_partition()), (PERSON_ID_HEADER, 42)];

    let by_id_status = service.get_person(stamped(by_id(), &routed)).await;
    let by_uuid_status = service
        .get_person_by_uuid(stamped(by_uuid(), &routed))
        .await;

    assert_eq!(by_id_status.unwrap_err().code(), Code::Unavailable);
    assert_eq!(by_uuid_status.unwrap_err().code(), Code::Unavailable);
}

#[tokio::test]
async fn a_single_person_read_that_was_not_routed_is_answered_from_postgres() {
    let service =
        PersonHogReplicaService::new(Arc::new(PopulatedStorage)).with_follower(follower_reads());

    let by_id = service.get_person(Request::new(by_id())).await;
    let by_uuid = service.get_person_by_uuid(Request::new(by_uuid())).await;

    assert!(by_id.expect("served").into_inner().person.is_some());
    assert!(by_uuid.expect("served").into_inner().person.is_some());
}

#[tokio::test]
async fn a_replica_that_does_not_follow_refuses_a_routed_person() {
    let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));

    let person = service
        .get_person(stamped(by_id(), &[(PARTITION_HEADER, own_partition())]))
        .await;

    assert_eq!(person.unwrap_err().code(), Code::FailedPrecondition);
}
