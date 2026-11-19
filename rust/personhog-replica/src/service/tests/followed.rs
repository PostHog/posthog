use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use personhog_common::client::{CHANGELOG_EPOCH_HEADER, PARTITION_HEADER, PERSON_ID_HEADER};
use personhog_coordination::changelog::LiveChangelog;
use personhog_coordination::types::ChangelogConfig;
use personhog_leader::cache::{CachedPerson, PartitionedCache};
use personhog_leader::follow::{FollowConfig, Follower};
use personhog_leader::warming::{WarmClientPools, WarmingConfig, WarmingRetryPolicy};
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplica;
use personhog_proto::personhog::types::v1::{GetPersonByUuidRequest, GetPersonRequest, Person};
use rstest::rstest;
use tonic::Request;

use super::mocks::PopulatedStorage;
use crate::service::followed::followed_or_stored;
use crate::service::{Attached, FollowerReads, PersonHogReplicaService};

const PARTITIONS: u32 = 8;
const EPOCH: u64 = 3;

/// A follower that follows nothing, so it answers for no partition. No broker is dialed.
fn follower_reads() -> FollowerReads {
    let reads = FollowerReads::default();
    reads.attach(|| {
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
        let follower = Follower::new(
            FollowConfig {
                staleness_threshold: Duration::from_millis(500),
                end_check_interval: Duration::from_millis(100),
            },
            warming,
            pools,
            Arc::new(PartitionedCache::new(1 << 20)),
        );
        Attached {
            follower: Arc::new(follower),
            changelog: LiveChangelog::new(ChangelogConfig {
                topic: "changelog".to_string(),
                partitions: PARTITIONS,
                cluster: None,
                epoch: EPOCH,
                writer_group: "writers".to_string(),
                retire_groups: Vec::new(),
                draining: Vec::new(),
            }),
        }
    });
    reads
}

fn other_partition() -> u64 {
    let own = personhog_common::partitioning::partition_for_person(1, 42, PARTITIONS);
    u64::from((own + 1) % PARTITIONS)
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

#[rstest]
#[case::not_routed(Some(follower_reads()), &[])]
#[case::a_replica_that_does_not_follow(None, &[(PARTITION_HEADER, own_partition())])]
#[case::a_follower_not_attached_yet(
    Some(FollowerReads::default()),
    &[(PARTITION_HEADER, own_partition())]
)]
#[case::a_partition_it_does_not_follow(
    Some(follower_reads()),
    &[(PARTITION_HEADER, own_partition())]
)]
#[case::routed_under_a_newer_config(
    Some(follower_reads()),
    &[(PARTITION_HEADER, own_partition()), (CHANGELOG_EPOCH_HEADER, EPOCH + 1)]
)]
#[case::routed_to_another_partition(
    Some(follower_reads()),
    &[(PARTITION_HEADER, other_partition())]
)]
#[tokio::test]
async fn a_person_the_follower_cannot_answer_for_is_read_from_postgres(
    #[case] follower: Option<FollowerReads>,
    #[case] headers: &[(&'static str, u64)],
) {
    let mut service = PersonHogReplicaService::new(Arc::new(PopulatedStorage));
    if let Some(follower) = follower {
        service = service.with_follower(follower);
    }
    let mut named = headers.to_vec();
    named.push((PERSON_ID_HEADER, 42));

    let by_id = service.get_person(stamped(by_id(), headers)).await;
    let by_uuid = service.get_person_by_uuid(stamped(by_uuid(), &named)).await;

    assert!(by_id.expect("served").into_inner().person.is_some());
    assert!(by_uuid.expect("served").into_inner().person.is_some());
}

#[tokio::test]
async fn a_read_with_routing_headers_it_cannot_read_is_read_from_postgres() {
    let own = own_partition().to_string();
    let unreadable: [&[(&str, &str)]; 4] = [
        &[(PARTITION_HEADER, "zero")],
        &[(PARTITION_HEADER, &own), (CHANGELOG_EPOCH_HEADER, "new")],
        &[(PARTITION_HEADER, &own), (PERSON_ID_HEADER, "-42")],
        // Not routed at all: the header is then no part of the read.
        &[(PERSON_ID_HEADER, "someone")],
    ];
    for headers in unreadable {
        let service = PersonHogReplicaService::new(Arc::new(PopulatedStorage))
            .with_follower(follower_reads());
        let (mut id_read, mut uuid_read) = (Request::new(by_id()), Request::new(by_uuid()));
        for (name, value) in headers {
            let value: tonic::metadata::MetadataValue<_> = value.parse().expect("header value");
            id_read.metadata_mut().insert(*name, value.clone());
            uuid_read.metadata_mut().insert(*name, value);
        }

        let by_id = service.get_person(id_read).await;
        let by_uuid = service.get_person_by_uuid(uuid_read).await;

        assert!(by_id.expect("served").into_inner().person.is_some());
        assert!(by_uuid.expect("served").into_inner().person.is_some());
    }
}

fn person(version: i64, is_deleted: bool) -> Person {
    Person {
        id: 42,
        team_id: 1,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        properties: b"{}".to_vec(),
        version,
        is_deleted,
        ..Default::default()
    }
}

#[rstest]
#[case::a_live_person_without_asking_postgres(Some((5, false)), None, Some(5))]
#[case::a_person_created_again_after_their_death(Some((6, true)), Some(Some(7)), Some(7))]
#[case::a_death_postgres_has_not_applied(Some((6, true)), Some(Some(6)), None)]
#[case::a_death_postgres_has_applied(Some((6, true)), Some(None), None)]
#[case::a_person_it_does_not_hold(None, Some(Some(3)), Some(3))]
#[case::a_person_nobody_has(None, Some(None), None)]
#[tokio::test]
async fn a_followed_answer_is_served_unless_postgres_must_be_asked(
    #[case] followed: Option<(i64, bool)>,
    #[case] stored: Option<Option<i64>>,
    #[case] served: Option<i64>,
) {
    let followed = followed.map(|(version, is_deleted)| {
        CachedPerson::try_from(person(version, is_deleted)).expect("a valid person")
    });

    let answer = followed_or_stored(followed, || async {
        let row = stored.expect("this read must not ask Postgres");
        Ok(row.map(|version| person(version, false)))
    })
    .await;

    assert_eq!(answer.expect("answered").map(|p| p.version), served);
}
