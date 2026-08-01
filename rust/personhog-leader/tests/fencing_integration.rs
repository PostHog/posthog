//! Broker-enforced fencing, proven against a real broker: a partition's
//! new owner initializing its transactional id must make the previous
//! owner's producer unusable. Without the fence, a stale owner's writes
//! land in the changelog silently — the exact zombie hazard this
//! mechanism exists to close.

mod common;

use std::sync::Arc;
use std::time::Duration;

use personhog_leader::fencing::{FenceGuard, FencedChangelogProducers, FencedProduceError};
use personhog_proto::personhog::types::v1::Person;
use tokio::time::sleep;

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

/// Count the records a `read_committed` consumer can see on partition 0
/// — the same isolation the warming path uses.
async fn read_committed_count(topic: &str) -> usize {
    use rdkafka::consumer::{Consumer, StreamConsumer};
    use rdkafka::{ClientConfig, Message, Offset, TopicPartitionList};

    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BOOTSTRAP)
        .set(
            "group.id",
            format!("fence-abort-probe-{}", uuid::Uuid::new_v4()),
        )
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("isolation.level", "read_committed")
        .create()
        .expect("probe consumer");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(topic, 0, Offset::Beginning)
        .expect("assign");
    consumer.assign(&tpl).expect("assign");

    let mut seen = 0;
    // Anything committed is available immediately; the quiet period only
    // has to outlast delivery, not a transaction timeout.
    while let Ok(Ok(message)) =
        tokio::time::timeout(Duration::from_millis(750), consumer.recv()).await
    {
        if message.payload().is_some() {
            seen += 1;
        }
    }
    seen
}

/// Comfortably above the test config's 5s `message.timeout.ms`, which
/// librdkafka requires the broker bound to cover.
const BROKER_TXN_TIMEOUT: Duration = Duration::from_secs(30);

fn fenced_producers_with_window(topic: &str, window: Duration) -> FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    FencedChangelogProducers::new(
        kafka,
        topic.to_string(),
        Duration::from_secs(10),
        Duration::from_secs(10),
        BROKER_TXN_TIMEOUT,
        window,
    )
}

fn fenced_producers(topic: &str) -> FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    FencedChangelogProducers::new(
        kafka,
        topic.to_string(),
        Duration::from_secs(10),
        Duration::from_secs(10),
        BROKER_TXN_TIMEOUT,
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
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire");

    let a = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    let b = {
        let p = Arc::clone(&producers);
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
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire");

    let writes: Vec<_> = (0..200i64)
        .map(|k| {
            let p = Arc::clone(&producers);
            tokio::spawn(async move {
                sleep(Duration::from_millis(((k * 7) % 97) as u64)).await;
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

/// A request that vanishes mid-produce — tonic drops the handler future
/// when the client's deadline expires — must return its seat in the
/// window. Without that, the committer waits on an in-flight count that
/// never reaches zero and every later write on the partition parks
/// forever behind it.
#[tokio::test]
async fn a_cancelled_produce_does_not_wedge_the_partition() {
    let topic = format!("fence_cancel_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire");

    {
        let p = Arc::clone(&producers);
        let mut inflight = Box::pin(async move { p.produce(0, &test_person(1)).await });
        // Far too little time to finish: the future is dropped mid-send.
        tokio::time::timeout(Duration::from_micros(200), &mut inflight)
            .await
            .ok();
    }

    tokio::time::timeout(
        Duration::from_secs(10),
        producers.produce(0, &test_person(2)),
    )
    .await
    .expect("a later write must not hang behind the cancelled one")
    .expect("and must succeed");
}

/// Does a successor's `init_transactions` abort the predecessor's open
/// transaction, or merely stop it from committing?
///
/// The drain does not wait for open transaction windows, which is only
/// safe if a record abandoned in one cannot become visible after the
/// partition moves. This pins that: the successor's acquire — which
/// precedes its warm read — leaves the predecessor unable to commit.
///
/// Without this guarantee the drain would have to wait out every open
/// window before acking, so the assertion is load-bearing rather than
/// incidental.
#[tokio::test]
async fn a_successors_init_aborts_the_predecessors_open_window() {
    let topic = format!("fence_abort_{}", uuid::Uuid::new_v4().simple());

    // Predecessor: open a window and get a record enqueued into it, then
    // abandon it exactly as a cancelled request would. The window is
    // short on purpose — its committer must fire *after* the successor
    // has taken the epoch, because "invisible while uncommitted" proves
    // nothing. What has to be shown is that the record can never become
    // visible once the successor owns the partition.
    let first = Arc::new(fenced_producers_with_window(&topic, Duration::from_secs(1)));
    first.acquire(0).await.expect("first owner acquires");
    {
        let p = Arc::clone(&first);
        let mut inflight = Box::pin(async move { p.produce(0, &test_person(1)).await });
        // Long enough for the send to reach the broker, far too short for
        // the 30s window to close.
        tokio::time::timeout(Duration::from_millis(200), &mut inflight)
            .await
            .ok();
    }

    // Successor takes the partition before that window closes, as a
    // warming new owner does.
    let second = fenced_producers(&topic);
    second.acquire(0).await.expect("successor acquires");

    // Now let the predecessor's committer run. This is the moment the
    // drain's wait exists to prevent: an abandoned record committing
    // after the successor is already the owner.
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Read the partition the way warming does.
    let visible = read_committed_count(&topic).await;
    assert_eq!(
        visible, 0,
        "an abandoned record must not become readable after the successor's init — \
         if this fails, the drain must wait for open windows before acking"
    );
}

/// A warm that never finishes must not leave this process holding the
/// partition's broker epoch.
///
/// The pod records a partition as held only once the warm returns, so a
/// fence taken by a warm whose future is dropped — what a lost lease
/// does to an in-flight attempt — belongs to no partition the local
/// self-fence knows to release. The process would keep the epoch while
/// owning nothing, and the real owner's writes would fail as fenced.
#[tokio::test]
async fn a_fence_taken_for_an_unfinished_warm_is_given_back() {
    let topic = format!("fence_guard_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));

    {
        producers.acquire(0).await.expect("acquire");
        let _guard = FenceGuard::new(Arc::clone(&producers), 0);
        // The warm ends here without returning, as a torn-down attempt
        // does.
    }

    match producers.produce(0, &test_person(1)).await {
        Err(FencedProduceError::NotAcquired) => {}
        other => panic!("the fence should have been given back, got {other:?}"),
    }
}

/// A warm that finishes keeps what it took.
#[tokio::test]
async fn a_completed_warm_keeps_its_fence() {
    let topic = format!("fence_guard_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));

    producers.acquire(0).await.expect("acquire");
    FenceGuard::new(Arc::clone(&producers), 0).keep();

    producers
        .produce(0, &test_person(1))
        .await
        .expect("a completed warm keeps a usable fence");
}

/// A commit whose outcome is unknown must not be reported as a failure.
///
/// "Aborted" invites a retry, and a retry against a cache still holding
/// the pre-write version produces a second record carrying the same
/// version as the one that may already have committed — which the
/// writer's strict guard resolves in favour of whichever arrived first,
/// discarding the acked one. The doubt has to survive as doubt.
#[test]
fn an_unknown_commit_outcome_is_not_reported_as_a_failure() {
    let indeterminate = FencedProduceError::Indeterminate("timed out".to_string());
    let aborted = FencedProduceError::Failed("aborted: send failed".to_string());

    assert!(
        !matches!(indeterminate, FencedProduceError::Failed(_)),
        "an unknown outcome must be distinguishable from a known abort"
    );
    assert!(matches!(aborted, FencedProduceError::Failed(_)));
    assert!(
        indeterminate.to_string().contains("unknown"),
        "the message must say what is actually known: {indeterminate}"
    );
}
