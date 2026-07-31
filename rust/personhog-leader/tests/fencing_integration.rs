//! Broker-enforced fencing, proven against a real broker: a partition's
//! new owner initializing its transactional id must make the previous
//! owner's producer unusable. Without the fence, a stale owner's writes
//! land in the changelog silently — the exact zombie hazard this
//! mechanism exists to close.

mod common;

use std::time::Duration;

use personhog_leader::fencing::{FencedChangelogProducers, FencedProduceError};
use personhog_proto::personhog::types::v1::Person;

use common::{test_kafka_config, KAFKA_BOOTSTRAP};

fn test_person(version: i64) -> Person {
    Person {
        id: 7,
        uuid: "00000000-0000-0000-0000-000000000007".to_string(),
        team_id: 1,
        properties: b"{}".to_vec(),
        version,
        ..Default::default()
    }
}

fn fenced_producers(topic: &str) -> FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    FencedChangelogProducers::new(
        kafka,
        topic.to_string(),
        Duration::from_secs(10),
        Duration::from_secs(10),
        Duration::from_millis(5),
    )
}

/// The core fencing guarantee: after a second owner acquires the
/// partition, the first owner's produce fails as fenced instead of
/// landing in the changelog.
#[tokio::test]
async fn second_acquisition_fences_the_first_producer() {
    let topic = format!("fence_test_{}", uuid::Uuid::new_v4().simple());

    let first = fenced_producers(&topic);
    first.acquire(0).await.expect("first owner acquires");
    first
        .produce(0, &test_person(1))
        .await
        .expect("first owner produces while unfenced");

    let second = fenced_producers(&topic);
    second.acquire(0).await.expect("second owner acquires");
    second
        .produce(0, &test_person(2))
        .await
        .expect("new owner produces");

    match first.produce(0, &test_person(3)).await {
        Err(FencedProduceError::Fenced) | Err(FencedProduceError::NotAcquired) => {}
        other => panic!("stale owner must be fenced, got {other:?}"),
    }
}

/// Concurrent same-partition writes share a transaction window: both
/// succeed with distinct offsets, through one producer, without
/// serializing on per-write commits.
#[tokio::test]
async fn concurrent_writes_share_a_window() {
    let topic = format!("fence_test_{}", uuid::Uuid::new_v4().simple());
    let producers = std::sync::Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire");

    let a = {
        let p = std::sync::Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    let b = {
        let p = std::sync::Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(2)).await })
    };
    let (a, b) = (a.await.unwrap().unwrap(), b.await.unwrap().unwrap());
    assert_ne!(a, b, "each write must get its own offset");
}

/// Sustained open-loop arrivals across many window turnovers: every
/// write must land and every waiter must be woken through dozens of
/// open → drain → commit cycles. A lost `window_closed` wakeup or a
/// dropped commit-outcome waiter hangs this test; the single-window
/// tests above never exercise turnover.
#[tokio::test]
async fn sustained_writes_across_window_boundaries() {
    let topic = format!("fence_test_{}", uuid::Uuid::new_v4().simple());
    let producers = std::sync::Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire");

    let writes: Vec<_> = (0..200i64)
        .map(|k| {
            let p = std::sync::Arc::clone(&producers);
            tokio::spawn(async move {
                tokio::time::sleep(Duration::from_millis(((k * 7) % 97) as u64)).await;
                p.produce(0, &test_person(k)).await
            })
        })
        .collect();
    for write in writes {
        write
            .await
            .unwrap()
            .expect("every write must land across window boundaries");
    }
}
