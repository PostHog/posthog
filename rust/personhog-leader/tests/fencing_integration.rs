//! Broker-enforced fencing, proven against a real broker: a partition's
//! new owner initializing its transactional id must make the previous
//! owner's producer unusable. Without the fence, a stale owner's writes
//! land in the changelog silently — the exact zombie hazard this
//! mechanism exists to close.

mod common;

use std::sync::Arc;
use std::time::Duration;

use personhog_coordination::pod::HandoffHandler;
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
    // Bounded for the same reason as the turnover test below: a write
    // that parks instead of answering reports as a stuck runner rather
    // than a failure, and the stale owner's produce is exactly the call
    // that would park.
    tokio::time::timeout(Duration::from_secs(60), async {
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
    })
    .await
    .expect("writes parked forever — a window_closed wakeup was lost");
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
    // Bounded: a lost `window_closed` wakeup parks every writer forever,
    // and an unbounded test reports that as a stuck runner rather than a
    // failure.
    tokio::time::timeout(Duration::from_secs(60), async {
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
    })
    .await
    .expect("writes parked forever — a window_closed wakeup was lost");
}

/// A commit nobody observed is not a commit that did not happen.
///
/// The committer can stop without answering — its task dropped at runtime
/// teardown, or unwound — and `spawn_blocking` work is not cancelled when
/// its handle is dropped, so the commit it was running may well have
/// landed. Reporting that as a definite abort frees a version whose record
/// may exist: the retry derives the same number, and the writer's
/// first-wins guard then discards whichever record arrived second, which
/// is the acked one.
#[tokio::test]
async fn a_committer_that_vanishes_leaves_the_outcome_in_doubt() {
    let topic = format!("fence_orphan_{}", uuid::Uuid::new_v4().simple());
    // A long window keeps the committer asleep, so the write is parked on
    // an outcome that is still nobody's to report.
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_secs(30),
    ));
    producers.acquire(0).await.expect("acquire the fence");

    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    sleep(Duration::from_millis(300)).await;

    producers.abandon_waiters_for_test(0);

    match writing.await.expect("the write task must not panic") {
        Err(FencedProduceError::Indeterminate(_)) => {}
        other => {
            panic!("an unobserved commit must not be reported as a definite abort, got {other:?}")
        }
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
        // Long enough for the send to reach the broker, far too short
        // for the window to close.
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

    // Zero is also what a partition nothing was ever produced to looks
    // like, so the same sequence without a successor has to show the
    // record arriving. Otherwise this test passes just as well when the
    // send never left the client.
    let control_topic = format!("fence_abort_control_{}", uuid::Uuid::new_v4().simple());
    let lone = Arc::new(fenced_producers_with_window(
        &control_topic,
        Duration::from_secs(1),
    ));
    lone.acquire(0).await.expect("control owner acquires");
    {
        let p = Arc::clone(&lone);
        let mut inflight = Box::pin(async move { p.produce(0, &test_person(1)).await });
        tokio::time::timeout(Duration::from_millis(200), &mut inflight)
            .await
            .ok();
    }
    tokio::time::sleep(Duration::from_secs(3)).await;
    assert_eq!(
        read_committed_count(&control_topic).await,
        1,
        "with no successor the abandoned record commits — without this the assertion \
         above cannot tell an aborted window from a send that never happened"
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

/// A producer whose abort exhausted its retries, or whose commit outcome
/// stayed unknown, is left in a transaction state it cannot begin another
/// window from. It is still installed, so nothing that checks for the
/// *presence* of a fence can tell it apart from a working one.
///
/// The partition must therefore stop reporting itself as fenced and start
/// answering writes as an ownership question, which is what a router can
/// act on and what a repair pass looks for. Reporting a retryable failure
/// instead leaves every write on the partition failing for as long as the
/// process lives, with reads still served and nothing to escalate.
#[tokio::test]
async fn a_condemned_producer_stops_claiming_the_partition() {
    let topic = format!("fence_condemned_{}", uuid::Uuid::new_v4().simple());
    let producers = fenced_producers(&topic);
    producers.acquire(0).await.expect("acquire the fence");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("a healthy fence writes");

    producers.condemn_for_test(0);

    match producers.produce(0, &test_person(2)).await {
        Err(FencedProduceError::NotAcquired) => {}
        other => panic!("a condemned producer must not answer as a live fence, got {other:?}"),
    }

    // And it must have been given up rather than merely refused once: a
    // re-acquisition is the only thing that makes the partition writable
    // again, and it can only run against a partition this pod no longer
    // claims to fence.
    producers.acquire(0).await.expect("re-acquire the fence");
    producers
        .produce(0, &test_person(3))
        .await
        .expect("a re-acquired fence writes again");
}

/// A guard outlives the fence it was taken for when a warm is abandoned
/// and the partition is re-acquired before the guard drops. Releasing by
/// partition alone would then evict the *replacement* — a live fence, on
/// a partition this pod legitimately owns — and every write would fail as
/// unowned until something re-acquired again.
#[tokio::test]
async fn an_abandoned_guard_does_not_evict_its_replacement() {
    let topic = format!("fence_guard_id_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("first acquire");

    // A warm takes the fence, then never finishes.
    let stale = FenceGuard::new(Arc::clone(&producers), 0);

    // Meanwhile the partition is released and taken again, so what is
    // installed is no longer what the guard is answerable for.
    producers.release(0);
    producers.acquire(0).await.expect("re-acquire");

    drop(stale);

    producers
        .produce(0, &test_person(1))
        .await
        .expect("the replacement fence must survive the stale guard");
}

/// A writer parked behind a committing window is woken by the very commit
/// that condemns the producer. Checking usability only before the park
/// skips exactly that writer: it wakes, finds the gate idle, and opens a
/// window on a producer that cannot begin one — answering with a
/// retryable failure the client retries against a pod that cannot write
/// the partition, instead of the ownership bounce that moves it.
#[tokio::test]
async fn a_writer_woken_onto_a_condemned_producer_is_bounced() {
    let topic = format!("fence_woken_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire the fence");

    // Stage the gate exactly as a commit in flight leaves it, so the
    // write below parks rather than opening its own window.
    producers.begin_committing_for_test(0);
    let parked = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    tokio::time::sleep(Duration::from_millis(100)).await;

    // The commit resolves badly and condemns the producer, then releases
    // the gate and wakes the parked writer — production's exact order.
    producers.condemn_for_test(0);
    producers.finish_committing_for_test(0);

    match parked.await.expect("the parked task must not panic") {
        Err(FencedProduceError::NotAcquired) => {}
        other => {
            panic!("a writer woken onto a condemned producer must answer as unowned, got {other:?}")
        }
    }
}

/// A commit task that never reports its outcome must condemn the producer.
///
/// `spawn_blocking` work is not cancelled when its handle drops, so the
/// commit may well have landed — the caller therefore learns nothing, and
/// the version stays spent. What matters here is the producer: its
/// transaction is left open, and without the condemn `holds()` keeps
/// answering yes, the repair pass sees nothing to do, and every later
/// write for the partition fails for the life of the process.
#[tokio::test]
async fn a_committer_that_never_reports_condemns_its_producer() {
    let topic = format!("fence_lost_commit_{}", uuid::Uuid::new_v4().simple());
    let producers = fenced_producers(&topic);
    producers.acquire(0).await.expect("acquire the fence");

    producers.panic_next_commit_for_test(0);

    match producers.produce(0, &test_person(1)).await {
        Err(FencedProduceError::Indeterminate(_)) => {}
        other => panic!("a lost committer settles nothing, got {other:?}"),
    }

    // The partition must now read as unfenced, which is what lets the
    // repair pass re-acquire it.
    match producers.produce(0, &test_person(2)).await {
        Err(FencedProduceError::NotAcquired) => {}
        other => {
            panic!("a producer with an open transaction still claimed the partition: {other:?}")
        }
    }
}

/// Settling before the drained ack lands a cancelled write instead of
/// leaving it to the successor to abort.
///
/// `a_successors_init_aborts_the_predecessors_open_window` shows the
/// safety net: an abandoned record can never become visible once the
/// successor owns the partition. This shows the boundary the drain is
/// supposed to be — the record is committed *before* the handoff
/// advances, so the successor reads it as ordinary history rather than
/// racing the predecessor's committer for it.
///
/// The window is far longer than the reads below take. A shorter one
/// closes on its own while the consumer is starting up, and then the
/// test passes whether or not the settle does anything.
#[tokio::test]
async fn settling_commits_an_abandoned_record_before_the_handoff_advances() {
    let topic = format!("fence_settle_{}", uuid::Uuid::new_v4().simple());

    let first = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_secs(15),
    ));
    first.acquire(0).await.expect("first owner acquires");
    {
        let p = Arc::clone(&first);
        let mut inflight = Box::pin(async move { p.produce(0, &test_person(1)).await });
        tokio::time::timeout(Duration::from_millis(200), &mut inflight)
            .await
            .ok();
    }

    // Nothing is readable yet: the record sits in an open window.
    assert_eq!(
        read_committed_count(&topic).await,
        0,
        "the record must still be uncommitted, or this proves nothing"
    );

    // Through the drain, not `settle` directly: the wiring is the part
    // that can be deleted, and calling the method under test by hand
    // proves only that the method exists.
    let handler = common::test_handoff_handler(&topic, Arc::clone(&first));
    handler
        .drain_partition_inflight(0)
        .await
        .expect("the drain must not fail");

    assert_eq!(
        read_committed_count(&topic).await,
        1,
        "a settled drain must leave the abandoned record committed, not waiting on a \
         successor to decide its fate"
    );

    // And it settled before the successor existed, which is what makes
    // the ack a boundary rather than the start of a race.
    let second = fenced_producers(&topic);
    second.acquire(0).await.expect("successor acquires");
    assert_eq!(
        read_committed_count(&topic).await,
        1,
        "the successor's init must find nothing left to abort"
    );
}

/// A resume must not take the fence its own convergence's warm already
/// took.
///
/// Warming acquires the partition's transactional id and then re-admits
/// writes as its last act. The resume that can follow in the same
/// convergence exists for a cancelled handoff whose target got as far as
/// taking the epoch — but if it runs after this pod's own warm, its
/// `init_transactions` bumps the epoch out from under every write the
/// warm just admitted, and the pod fences its own live window.
///
/// The mark that prevents this has two halves, and either one alone is
/// useless: warming records the fence it took, and the resume honours
/// that record. This covers both — delete either and the in-flight write
/// below is fenced by its own pod.
#[tokio::test]
async fn a_resume_does_not_fence_the_window_its_own_warm_admitted() {
    let topic = format!("fence_resume_{}", uuid::Uuid::new_v4().simple());
    // Long enough that the write is still sitting in an open window when
    // the resume runs — a window that closed first would be committed
    // already and could not be fenced.
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_secs(10),
    ));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    // A record for the warm to read, which also brings the topic into
    // existence — `fetch_watermarks` has nothing to answer for a topic
    // no one has produced to.
    producers.acquire(0).await.expect("seed the topic");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("seed record");

    // Warming takes the epoch and admits writes on the way out, which is
    // the pair of facts the resume below has to respect.
    handler.warm_partition(0).await.expect("warm the partition");

    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(2)).await })
    };
    // Long enough for the send to reach the broker and open the window.
    sleep(Duration::from_millis(300)).await;

    handler.resume_partition(0).await.expect("resume");

    let result = writing.await.expect("the write task must not panic");
    assert!(
        result.is_ok(),
        "a resume must not fence the window this convergence's own warm \
         admitted, got {result:?}"
    );
}

/// A poisoned window must be aborted, and a failed abort must condemn.
///
/// A send that fails inside a window leaves records the transaction can
/// never be allowed to commit, so the commit path aborts instead. Skip
/// the abort and the producer is left in its abortable state — where
/// every later `begin_transaction` fails — while the code reports a
/// clean abort, so nothing condemns it and nothing re-acquires. The
/// partition then refuses every write for the life of the process.
#[tokio::test]
async fn a_poisoned_window_is_aborted_rather_than_committed() {
    let topic = format!("fence_poison_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window(&topic, Duration::from_secs(1)));
    producers.acquire(0).await.expect("acquire the fence");

    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    sleep(Duration::from_millis(300)).await;
    producers.poison_window_for_test(0);

    match writing.await.expect("the write task must not panic") {
        Err(FencedProduceError::Failed(_)) => {}
        other => panic!("a poisoned window must not report success, got {other:?}"),
    }

    // The abort landed, so the records are definitively not in the log
    // and the producer is still usable for the next window.
    assert_eq!(
        read_committed_count(&topic).await,
        0,
        "a poisoned window's records must never become visible"
    );
    producers
        .produce(0, &test_person(2))
        .await
        .expect("an aborted window leaves the producer able to open another");
}

/// A window that cannot be settled must not hold the partition hostage.
///
/// The drain fences writes as its first act, and the only branch that
/// lifts that fence runs after the handoff completes — which needs the
/// ack this drain is about to write. So a drain that refuses to ack over
/// an unsettled window strands the partition rejecting every write for
/// the life of the process, while reads carry on and the convergence
/// reports success.
///
/// Refusing would buy nothing anyway: a producer that cannot report its
/// outcome is one the broker accepts no further record from, and the
/// incoming owner's `init_transactions` aborts whatever is left, exactly
/// as it did before the drain waited at all.
#[tokio::test]
async fn a_window_that_cannot_settle_still_lets_the_handoff_proceed() {
    let topic = format!("fence_unsettled_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire the fence");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("a healthy fence writes");

    // The state an abort that never landed, or a commit whose outcome
    // stayed unknown, leaves behind.
    producers.condemn_for_test(0);

    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));
    handler
        .drain_partition_inflight(0)
        .await
        .expect("a condemned producer must not fail the drain");
}

/// A resume that skipped its acquire must leave the mark for the retry.
///
/// The skip branch consumed the mark, so a convergence torn down after
/// the resume returned — but before `apply` recorded it — retried with
/// the partition still listed as fenced and nothing to say the fence was
/// already held. That retry re-acquires and bumps the epoch out from
/// under the writes the first resume admitted.
#[tokio::test]
async fn a_repeated_resume_does_not_fence_the_window_the_first_one_admitted() {
    let topic = format!("fence_resume_twice_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_secs(10),
    ));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    producers.acquire(0).await.expect("seed the topic");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("seed record");
    handler.warm_partition(0).await.expect("warm the partition");
    handler.resume_partition(0).await.expect("first resume");

    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(2)).await })
    };
    sleep(Duration::from_millis(300)).await;

    // The convergence was torn down before it could record the resume,
    // so the same one runs again.
    handler.resume_partition(0).await.expect("retried resume");

    let result = writing.await.expect("the write task must not panic");
    assert!(
        result.is_ok(),
        "a retried resume must not fence the window the first one admitted, got {result:?}"
    );
}
