mod common;

use std::net::SocketAddr;
use std::sync::atomic::Ordering;

use common::{
    create_client, create_test_person, start_test_replica, start_test_router_raw_following,
    start_test_router_raw_with_followers, TestReplicaService,
};
use personhog_proto::personhog::types::v1::{
    GetFlagContextRequest, GetPersonByUuidRequest, GetPersonRequest,
};
use tonic::Request;

fn for_person() -> Request<GetPersonRequest> {
    routed(by_id())
}

fn routed<T>(message: T) -> Request<T> {
    let mut request = Request::new(message);
    request
        .metadata_mut()
        .insert("x-team-id", "1".parse().unwrap());
    request
        .metadata_mut()
        .insert("x-person-id", "42".parse().unwrap());
    request
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

fn shedding() -> TestReplicaService {
    TestReplicaService::new().sheds(usize::MAX)
}

fn with_the_person() -> TestReplicaService {
    TestReplicaService::with_person(create_test_person())
}

#[tokio::test]
async fn a_followed_read_goes_to_the_preferred_instance_stamped_with_partition_and_epoch() {
    let preferred = TestReplicaService::with_person(create_test_person());
    let other = TestReplicaService::new();
    let (preferred_calls, other_calls) = (preferred.calls.clone(), other.calls.clone());
    let replica = start_test_replica(TestReplicaService::new()).await;
    let router = start_test_router_raw_with_followers(
        replica,
        vec![
            Some(start_test_replica(preferred).await),
            Some(start_test_replica(other).await),
        ],
    )
    .await;

    let response = create_client(router)
        .await
        .get_person(for_person())
        .await
        .expect("served");

    let stamped = |name: &str| response.metadata().get(name).and_then(|v| v.to_str().ok());
    assert_eq!(
        (stamped("x-partition"), stamped("x-changelog-epoch")),
        (Some("0"), Some("1"))
    );
    assert!(response.get_ref().person.is_some());
    assert_eq!(
        (
            preferred_calls.load(Ordering::SeqCst),
            other_calls.load(Ordering::SeqCst)
        ),
        (1, 0)
    );
}

#[tokio::test]
async fn an_instance_that_cannot_take_the_read_is_passed_over() {
    let overloaded = shedding();
    let overloaded_calls = overloaded.calls.clone();
    // An address nothing listens on, as a pod that died leaves until its lease expires.
    let gone = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let gone_addr = gone.local_addr().unwrap();
    drop(gone);
    let replica = start_test_replica(TestReplicaService::new()).await;
    let router = start_test_router_raw_with_followers(
        replica,
        vec![
            None,
            Some(gone_addr),
            Some(start_test_replica(overloaded).await),
            Some(start_test_replica(with_the_person()).await),
        ],
    )
    .await;

    let response = create_client(router)
        .await
        .get_person(for_person())
        .await
        .expect("served by the last instance");

    assert!(response.get_ref().person.is_some());
    assert_eq!(overloaded_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn a_read_no_follower_can_take_is_answered_by_a_replica() {
    // A router that has not joined its follower instances yet, and one whose instances
    // have no owner for the partition.
    let cases: [Option<Vec<Option<SocketAddr>>>; 2] = [None, Some(vec![None, None])];
    for followers in cases {
        let replica = start_test_replica(with_the_person()).await;
        let router = start_test_router_raw_following(replica, followers).await;
        let mut client = create_client(router).await;

        let by_id = client.get_person(for_person()).await.expect("served");
        let by_uuid = client
            .get_person_by_uuid(routed(by_uuid()))
            .await
            .expect("served");
        let context = client
            .get_flag_context(routed(GetFlagContextRequest {
                team_id: 1,
                person_id: Some(42),
                ..Default::default()
            }))
            .await
            .expect("served");

        assert!(by_id.get_ref().person.is_some());
        assert!(by_uuid.get_ref().person.is_some());
        assert!(context.get_ref().person.is_some());
    }
}

#[tokio::test]
async fn a_read_with_routing_headers_the_router_cannot_read_is_answered_by_a_replica() {
    let follower = with_the_person();
    let follower_calls = follower.calls.clone();
    let replica = start_test_replica(with_the_person()).await;
    let router = start_test_router_raw_with_followers(
        replica,
        vec![Some(start_test_replica(follower).await)],
    )
    .await;
    let mut request = Request::new(by_id());
    request
        .metadata_mut()
        .insert("x-team-id", "one".parse().unwrap());
    request
        .metadata_mut()
        .insert("x-person-id", "42".parse().unwrap());

    let response = create_client(router)
        .await
        .get_person(request)
        .await
        .expect("served by a replica");

    assert!(response.get_ref().person.is_some());
    assert_eq!(follower_calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn a_follower_that_takes_too_long_hands_the_read_to_a_replica_and_no_other_follower() {
    let other = with_the_person();
    let other_calls = other.calls.clone();
    let replica = with_the_person();
    let replica_calls = replica.calls.clone();
    let router = start_test_router_raw_with_followers(
        start_test_replica(replica).await,
        vec![
            Some(start_test_replica(TestReplicaService::new().holding_person_reads()).await),
            Some(start_test_replica(other).await),
        ],
    )
    .await;

    let response = create_client(router)
        .await
        .get_person(for_person())
        .await
        .expect("served by a replica");

    assert!(response.get_ref().person.is_some());
    assert_eq!(
        (
            replica_calls.load(Ordering::SeqCst),
            other_calls.load(Ordering::SeqCst)
        ),
        (1, 0)
    );
}

#[tokio::test]
async fn a_single_person_read_goes_to_a_follower_only_with_the_routing_headers() {
    let plain = TestReplicaService::new();
    let follower = TestReplicaService::new();
    let (plain_calls, follower_calls) = (plain.calls.clone(), follower.calls.clone());
    let router = start_test_router_raw_with_followers(
        start_test_replica(plain).await,
        vec![Some(start_test_replica(follower).await)],
    )
    .await;
    let mut client = create_client(router).await;
    let seen = || {
        (
            plain_calls.load(Ordering::SeqCst),
            follower_calls.load(Ordering::SeqCst),
        )
    };

    client.get_person(routed(by_id())).await.expect("served");
    client
        .get_person_by_uuid(routed(by_uuid()))
        .await
        .expect("served");
    let with_headers = seen();
    let mut person_only = Request::new(by_id());
    person_only
        .metadata_mut()
        .insert("x-person-id", "42".parse().unwrap());
    client.get_person(person_only).await.expect("served");
    client
        .get_person(Request::new(by_id()))
        .await
        .expect("served");
    client
        .get_person_by_uuid(Request::new(by_uuid()))
        .await
        .expect("served");

    assert_eq!((with_headers, seen()), ((0, 2), (3, 2)));
}

#[tokio::test]
async fn a_flag_context_goes_to_a_follower_only_when_it_names_a_person_in_the_headers() {
    let plain = TestReplicaService::new();
    let follower = TestReplicaService::new();
    let (plain_calls, follower_calls) = (plain.calls.clone(), follower.calls.clone());
    let router = start_test_router_raw_with_followers(
        start_test_replica(plain).await,
        vec![Some(start_test_replica(follower).await)],
    )
    .await;
    let mut client = create_client(router).await;
    let context = |person_id| GetFlagContextRequest {
        team_id: 1,
        person_id,
        ..Default::default()
    };

    client
        .get_flag_context(routed(context(Some(42))))
        .await
        .expect("served");
    let with_headers = (
        plain_calls.load(Ordering::SeqCst),
        follower_calls.load(Ordering::SeqCst),
    );
    client
        .get_flag_context(Request::new(context(None)))
        .await
        .expect("served");

    assert_eq!(with_headers, (0, 1));
    assert_eq!(
        (
            plain_calls.load(Ordering::SeqCst),
            follower_calls.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
}
