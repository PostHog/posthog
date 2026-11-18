mod common;

use std::sync::atomic::Ordering;

use common::{
    create_client, create_test_person, start_test_replica, start_test_router_raw_with_followers,
    TestReplicaService,
};
use personhog_proto::personhog::types::v1::{GetPersonByUuidRequest, GetPersonRequest};
use tonic::{Code, Request};

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

fn refusing() -> TestReplicaService {
    TestReplicaService::new().sheds(usize::MAX)
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
async fn an_instance_that_refuses_or_has_no_owner_is_passed_over() {
    let behind = refusing();
    let behind_calls = behind.calls.clone();
    let replica = start_test_replica(TestReplicaService::new()).await;
    let router = start_test_router_raw_with_followers(
        replica,
        vec![
            None,
            Some(start_test_replica(behind).await),
            Some(start_test_replica(TestReplicaService::with_person(create_test_person())).await),
        ],
    )
    .await;

    let response = create_client(router)
        .await
        .get_person(for_person())
        .await
        .expect("served by the last instance");

    assert!(response.get_ref().person.is_some());
    assert_eq!(behind_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn a_follower_that_never_answers_does_not_hold_the_read() {
    // Accepts connections and says nothing, as a dead pod's address does until its lease expires.
    let silent = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let silent_addr = silent.local_addr().unwrap();
    let replica = start_test_replica(TestReplicaService::new()).await;
    let router = start_test_router_raw_with_followers(
        replica,
        vec![
            Some(silent_addr),
            Some(start_test_replica(TestReplicaService::with_person(create_test_person())).await),
        ],
    )
    .await;

    let started = std::time::Instant::now();
    let response = create_client(router)
        .await
        .get_person(for_person())
        .await
        .expect("served by the second instance");

    assert!(response.get_ref().person.is_some());
    assert!(started.elapsed() < std::time::Duration::from_secs(2));
    drop(silent);
}

#[tokio::test]
async fn the_caller_is_told_to_retry_only_when_every_instance_refuses() {
    let refusals: [fn() -> TestReplicaService; 2] = [refusing, || {
        TestReplicaService::new().following_another_partition()
    }];
    for refusal in refusals {
        let replica = start_test_replica(TestReplicaService::new()).await;
        let router = start_test_router_raw_with_followers(
            replica,
            vec![
                Some(start_test_replica(refusal()).await),
                Some(start_test_replica(refusal()).await),
            ],
        )
        .await;

        let status = create_client(router)
            .await
            .get_person(for_person())
            .await
            .unwrap_err();

        assert_eq!(status.code(), Code::Unavailable);
    }
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
