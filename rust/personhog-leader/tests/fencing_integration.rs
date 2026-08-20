//! Broker-enforced fencing, proven against a real broker: a partition's
//! new owner initializing its transactional id must make the previous
//! owner's producer unusable. Without the fence, a stale owner's writes
//! land in the changelog silently — the exact zombie hazard this
//! mechanism exists to close.

mod common;

use std::sync::Arc;
use std::time::Duration;

use envconfig::Envconfig;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::pod::HandoffHandler;
use personhog_leader::fencing::{
    heal_fence, FenceGuard, FencedChangelogProducers, FencedProduceError, FencedProducerConfig,
    HealOutcome,
};
use personhog_leader::inflight::InflightTracker;
use personhog_proto::personhog::types::v1::Person;
use tokio::sync::Notify;
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

fn fenced_producers_with_window_and_fill(
    topic: &str,
    window: Duration,
    window_max_writes: usize,
) -> FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: topic.to_string(),
        init_timeout: Duration::from_secs(10),
        commit_timeout: Duration::from_secs(10),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window,
        window_max_writes,
        settle_budget: window + Duration::from_secs(5),
    })
}

fn fenced_producers_with_window(topic: &str, window: Duration) -> FencedChangelogProducers {
    fenced_producers_with_window_and_fill(topic, window, 32)
}

fn fenced_producers(topic: &str) -> FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: topic.to_string(),
        init_timeout: Duration::from_secs(10),
        commit_timeout: Duration::from_secs(10),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window: Duration::from_millis(5),
        window_max_writes: 32,
        settle_budget: Duration::from_secs(5),
    })
}

/// The prepared path must fence exactly as the cold path does: a
/// connection built ahead of acquisition carries no broker transactional
/// state, so the epoch bump happens at `acquire` — and the previous
/// owner must find itself fenced by it.
#[tokio::test]
async fn a_prepared_connection_still_fences_the_previous_owner() {
    let topic = format!("fence_prepared_{}", uuid::Uuid::new_v4().simple());

    let first = fenced_producers(&topic);
    first.acquire(0).await.expect("first owner acquires");
    first
        .produce(0, &test_person(1))
        .await
        .expect("first owner produces while unfenced");

    let second = fenced_producers(&topic);
    second.preconnect(0).await;
    assert!(second.has_prepared(0), "preconnect parks a connection");
    // The property the phase split exists for: the parked connection has
    // touched no broker transactional state, so the serving owner is
    // still unfenced. Only the acquire below may cut it off.
    first
        .produce(0, &test_person(10))
        .await
        .expect("a parked connection must not fence the serving owner");
    second.acquire(0).await.expect("second owner acquires");
    assert!(
        !second.has_prepared(0),
        "acquisition consumes the parked connection"
    );
    second
        .produce(0, &test_person(2))
        .await
        .expect("an acquisition through a prepared connection serves writes");

    match first.produce(0, &test_person(3)).await {
        Err(FencedProduceError::Fenced) | Err(FencedProduceError::NotAcquired) => {}
        other => panic!("the prepared path must still fence the stale owner, got {other:?}"),
    }
}

/// A parked connection nothing consumed must not outlive the sweep: a
/// cancelled inbound handoff leaves no convergence behind to discard it,
/// so the periodic sweep is the only owner its lifetime has.
#[tokio::test]
async fn the_sweep_discards_parked_connections() {
    let topic = format!("fence_prepared_{}", uuid::Uuid::new_v4().simple());
    let producers = fenced_producers(&topic);
    producers.preconnect(6).await;
    assert!(producers.has_prepared(6), "preconnect parks a connection");

    producers.sweep_prepared();

    assert!(
        !producers.has_prepared(6),
        "the sweep must discard a parked connection"
    );
}

/// A partition released with a connection still parked must not keep the
/// client alive: release is the one moment ownership says the connection
/// has no future consumer.
#[tokio::test]
async fn a_released_partition_discards_its_prepared_connection() {
    let topic = format!("fence_prepared_{}", uuid::Uuid::new_v4().simple());
    let producers = fenced_producers(&topic);
    producers.preconnect(5).await;
    assert!(producers.has_prepared(5), "preconnect parks a connection");
    producers.release(5);
    assert!(
        !producers.has_prepared(5),
        "release must discard the parked connection"
    );
}

/// The trigger fires on every convergence pass through a drain window,
/// so concurrent preconnects for one partition are the normal case, and
/// each dial is a full TLS client. Without single-flight they stack
/// until the pod runs out of memory; the claim must collapse them to
/// one dial.
#[tokio::test]
async fn concurrent_preconnects_collapse_to_one_dial() {
    let topic = format!("fence_prepared_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));

    let calls: Vec<_> = (0..20)
        .map(|_| {
            let p = Arc::clone(&producers);
            tokio::spawn(async move { p.preconnect(3).await })
        })
        .collect();
    for call in calls {
        call.await.unwrap();
    }

    assert_eq!(
        producers.connect_attempts_for_test(),
        1,
        "twenty concurrent preconnects must share one dial"
    );
    assert!(
        producers.has_prepared(3),
        "the one dial parks its connection"
    );
}

/// A failed dial must release its claim: the claim exists to suppress
/// concurrent dials, not to wedge the partition out of preconnecting
/// after a broker hiccup.
#[tokio::test]
async fn a_failed_preconnect_releases_its_claim() {
    let mut kafka = test_kafka_config();
    // An unroutable broker fails the dial at its bounded metadata ping.
    kafka.kafka_hosts = "127.0.0.1:1".to_string();
    let producers = FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: "fence_unroutable".to_string(),
        init_timeout: Duration::from_secs(2),
        commit_timeout: Duration::from_secs(2),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window: Duration::from_millis(5),
        window_max_writes: 32,
        settle_budget: Duration::from_secs(5),
    });

    producers.preconnect(0).await;
    assert!(!producers.has_prepared(0), "a failed dial parks nothing");

    producers.preconnect(0).await;
    assert_eq!(
        producers.connect_attempts_for_test(),
        2,
        "the failed dial's claim must not block the retry"
    );
}

/// A dial whose claim was removed mid-flight must not resolve the
/// replacement claim that took its place: releasing another dial's
/// claim lets convergence start yet more dials, recreating the churn
/// single-flight exists to stop.
#[tokio::test]
async fn a_stale_dials_failure_leaves_the_replacements_claim() {
    let mut kafka = test_kafka_config();
    // An unroutable broker holds the dial open until its 2s bound, so
    // the mid-flight claim churn below happens while it is in flight.
    kafka.kafka_hosts = "127.0.0.1:1".to_string();
    let producers = Arc::new(FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: "fence_unroutable".to_string(),
        init_timeout: Duration::from_secs(2),
        commit_timeout: Duration::from_secs(2),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window: Duration::from_millis(5),
        window_max_writes: 32,
        settle_budget: Duration::from_secs(5),
    }));

    let dial = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.preconnect(0).await })
    };
    while !producers.has_connecting_claim_for_test(0) {
        tokio::task::yield_now().await;
    }
    // Ownership churn mid-dial: the claim is discarded and a
    // replacement dial claims the slot.
    producers.release(0);
    producers.stage_connecting_for_test(0, Duration::ZERO);

    dial.await.unwrap();

    assert!(
        producers.has_connecting_claim_for_test(0),
        "the stale dial's failure must not release the replacement's claim"
    );
}

/// The sweep clears a claim only past the dial bound: an old claim has
/// no live owner (its task died), and leaving it would silently disable
/// preconnect for the partition, while a young claim is a live dial
/// whose head start the sweep must not discard.
#[tokio::test]
async fn the_sweep_clears_orphaned_claims_but_not_live_ones() {
    let topic = format!("fence_prepared_{}", uuid::Uuid::new_v4().simple());
    let producers = fenced_producers(&topic);

    producers.stage_connecting_for_test(1, Duration::from_secs(60));
    producers.stage_connecting_for_test(2, Duration::from_secs(0));
    producers.sweep_prepared();

    producers.preconnect(1).await;
    assert!(
        producers.has_prepared(1),
        "the orphaned claim must clear so preconnect works again"
    );
    producers.preconnect(2).await;
    assert_eq!(
        producers.connect_attempts_for_test(),
        1,
        "the live claim must survive the sweep and keep coalescing"
    );
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

/// A window that reaches its fill threshold commits immediately rather
/// than holding for its timer. The window here is far longer than the
/// test's own bound, so the acks can only arrive through the fill
/// close.
#[tokio::test]
async fn a_filled_window_commits_before_its_timer() {
    let topic = format!("fence_test_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window_and_fill(
        &topic,
        Duration::from_secs(60),
        3,
    ));
    producers.acquire(0).await.expect("acquire");

    let writes: Vec<_> = (1..=3i64)
        .map(|v| {
            let p = Arc::clone(&producers);
            tokio::spawn(async move { p.produce(0, &test_person(v)).await })
        })
        .collect();
    tokio::time::timeout(Duration::from_secs(20), async {
        for write in writes {
            write.await.unwrap().expect("a filled window must commit");
        }
    })
    .await
    .expect("acks waited on the 60s timer — the fill close never fired");
    assert_eq!(read_committed_count(&topic).await, 3);
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
        let _guard = FenceGuard::new(Arc::clone(&producers), 0, "warm");
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
    FenceGuard::new(Arc::clone(&producers), 0, "warm").keep();

    producers
        .produce(0, &test_person(1))
        .await
        .expect("a completed warm keeps a usable fence");
}

/// A condemnation must nudge its own repair: the fix for a condemned
/// producer is a convergence-driven heal, and without the nudge that
/// convergence waits for the next reconcile tick while every write on
/// the partition bounces. Once per producer: the unusable swap, not the
/// notify, bounds the nudges.
#[tokio::test]
async fn a_condemnation_nudges_repair_once() {
    let topic = format!("fence_repair_{}", uuid::Uuid::new_v4().simple());
    let nudge = Arc::new(Notify::new());
    let producers = fenced_producers(&topic).with_repair_nudge(Arc::clone(&nudge));
    producers.acquire(3).await.expect("acquire the fence");

    producers.condemn_for_test(3);
    tokio::time::timeout(Duration::from_secs(5), nudge.notified())
        .await
        .expect("a condemnation must nudge the repair pass");

    // The permit was consumed above; a second condemnation of the same
    // producer takes the unusable-swap early exit and stores no new one.
    producers.condemn_for_test(3);
    assert!(
        tokio::time::timeout(Duration::from_millis(250), nudge.notified())
            .await
            .is_err(),
        "a second condemnation of the same producer must not nudge again"
    );
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
    let stale = FenceGuard::new(Arc::clone(&producers), 0, "warm");

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

/// A partition can end up served without a fence — a broker rejection
/// evicted it, an abort exhausted its retries, a stale pod took the
/// epoch and stepped back. Convergence sees such a partition warmed and
/// unfenced and does nothing, so this is what gets it writable again
/// before the next handoff.
#[tokio::test]
async fn healing_retakes_a_fence_for_a_served_partition() {
    let topic = format!("fence_heal_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let inflight = InflightTracker::new();
    let clock = AuthorityClock::unclaimed();
    clock.begin_session(Duration::from_secs(30), std::time::Instant::now());

    let outcome = heal_fence(&producers, &inflight, Some(&clock), 0).await;
    assert_eq!(
        outcome,
        Ok(HealOutcome::Healed),
        "the caller marks the partition freshly fenced on this answer"
    );

    producers
        .produce(0, &test_person(1))
        .await
        .expect("a served partition must regain a usable fence");
}

/// Healing takes the partition's epoch from whoever holds it, so a pod
/// that cannot vouch for its own claim must not start the round trip at
/// all — `init_transactions` cannot be undone once it returns, and the
/// post-acquire check can only stop *this* pod from building on a fence
/// it already stole.
///
/// The assertion is therefore on the victim. Asking only whether we
/// ended up holding a fence cannot tell the pre-check from the
/// post-check: both leave us empty-handed, and only one of them leaves
/// the legitimate owner still able to write.
#[tokio::test]
async fn healing_without_standing_does_not_steal_the_epoch() {
    let topic = format!("fence_heal_{}", uuid::Uuid::new_v4().simple());
    let inflight = InflightTracker::new();

    // The partition's real owner, holding a working fence.
    let owner = Arc::new(fenced_producers(&topic));
    owner.acquire(0).await.expect("the owner takes its fence");
    owner
        .produce(0, &test_person(1))
        .await
        .expect("the owner can write");

    // A pod whose claim is gone tries to heal the same partition.
    let zombie = Arc::new(fenced_producers(&topic));
    let lapsed = AuthorityClock::unclaimed();
    lapsed.begin_session(Duration::from_secs(30), std::time::Instant::now());
    lapsed.surrender();
    let outcome = heal_fence(&zombie, &inflight, Some(&lapsed), 0).await;
    assert_eq!(outcome, Ok(HealOutcome::Intact));

    owner
        .produce(0, &test_person(2))
        .await
        .expect("a pod with no standing must not take the epoch from the real owner");
}

/// A partition a handoff is already moving belongs to the incoming
/// owner, so healing must leave it alone for the same reason.
#[tokio::test]
async fn healing_skips_a_partition_under_handoff() {
    let topic = format!("fence_heal_{}", uuid::Uuid::new_v4().simple());
    let inflight = InflightTracker::new();

    let owner = Arc::new(fenced_producers(&topic));
    owner.acquire(0).await.expect("the owner takes its fence");

    let other = Arc::new(fenced_producers(&topic));
    let valid = AuthorityClock::unclaimed();
    valid.begin_session(Duration::from_secs(30), std::time::Instant::now());
    inflight.fence(0);
    let outcome = heal_fence(&other, &inflight, Some(&valid), 0).await;
    assert_eq!(outcome, Ok(HealOutcome::Intact));

    owner
        .produce(0, &test_person(1))
        .await
        .expect("a partition being handed off is not ours to take");
}

/// Standing can lapse *during* the broker round trip, by which point the
/// fence is installed. Keeping it is not passive: the write path trusts
/// the broker epoch rather than re-checking the claim, so a request
/// landing here would ack a mutation with an epoch taken from the
/// partition's real owner.
#[tokio::test]
async fn healing_gives_back_a_fence_it_lost_standing_for() {
    let topic = format!("fence_heal_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let inflight = InflightTracker::new();

    let clock = Arc::new(AuthorityClock::unclaimed());
    clock.begin_session(Duration::from_secs(30), std::time::Instant::now());
    let losing = Arc::clone(&clock);
    let lease_loss = tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(5)).await;
        losing.surrender();
    });

    let outcome = heal_fence(&producers, &inflight, Some(&clock), 0).await;
    assert_ne!(
        outcome,
        Ok(HealOutcome::Healed),
        "a fence taken while standing lapsed must not be reported serving"
    );
    lease_loss.await.unwrap();

    match producers.produce(0, &test_person(1)).await {
        Err(FencedProduceError::NotAcquired) => {}
        other => panic!("a fence taken without standing must be given back, got {other:?}"),
    }
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

/// Healing must leave a partition it already holds alone. Re-acquiring
/// runs `init_transactions`, which bumps the broker epoch — so a healing
/// pass that ignored the fence it is already holding would fence this
/// pod's own producer on every reconcile tick.
///
/// The damage lands on writes already in flight, not on the next one: a
/// fresh write simply uses whichever producer is installed. So the write
/// here is mid-window when the tick runs.
#[tokio::test]
async fn healing_leaves_a_fence_it_already_holds_alone() {
    let topic = format!("fence_heal_noop_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_millis(600),
    ));
    let inflight = InflightTracker::new();
    let clock = AuthorityClock::unclaimed();
    clock.begin_session(Duration::from_secs(30), std::time::Instant::now());

    producers.acquire(0).await.expect("take the fence");

    // In flight: the window is open and its commit has not fired.
    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    tokio::time::sleep(Duration::from_millis(100)).await;

    // A reconcile tick with everything healthy.
    let outcome = heal_fence(&producers, &inflight, Some(&clock), 0).await;
    assert_eq!(outcome, Ok(HealOutcome::Intact));

    let result = writing.await.expect("the write task must not panic");
    assert!(
        result.is_ok(),
        "a healing pass must not fence the window this pod is already \
         filling, got {result:?}"
    );
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

/// A drain that arrives while the window's commit is already running must
/// wait for it.
///
/// At that point the gate reads idle in every field but `committing`: the
/// window is closed to joiners and no sends are outstanding, yet
/// `commit_transaction` is still mid round trip. A settle that asked only
/// whether the window was open would return there and let the drain ack,
/// handing the successor a partition whose last records are still racing
/// its `init_transactions` — the race settling exists to end.
#[tokio::test]
async fn a_drain_waits_for_a_commit_that_is_already_running() {
    let topic = format!("fence_settle_mid_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire the fence");

    // The gate a commit in flight leaves behind.
    producers.begin_committing_for_test(0);

    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));
    let draining = tokio::spawn(async move { handler.drain_partition_inflight(0).await });
    sleep(Duration::from_millis(300)).await;
    assert!(
        !draining.is_finished(),
        "the drain acked while this window's commit was still in flight"
    );

    producers.finish_committing_for_test(0);
    tokio::time::timeout(Duration::from_secs(10), draining)
        .await
        .expect("the drain must return once the commit finishes")
        .expect("the drain task must not panic")
        .expect("the drain must not fail");
}

/// A resume records the fence it took itself, not only the one warming
/// left behind.
///
/// A handoff cancelled after the drain reaches `resume_partition` with no
/// mark — the drain retires it — so this resume acquires. A convergence
/// torn down before `apply` files the resume runs the same one again, and
/// without a mark of its own that retry re-acquires, bumping the epoch out
/// from under everything the first resume just admitted.
#[tokio::test]
async fn a_resume_that_took_the_fence_itself_does_not_take_it_again() {
    let topic = format!("fence_resume_own_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_secs(10),
    ));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    producers.acquire(0).await.expect("seed the topic");
    // Handed away, then cancelled: the drain retires the mark and the
    // resume has to take the fence — and record it — on its own.
    handler
        .drain_partition_inflight(0)
        .await
        .expect("the drain must not fail");
    handler.resume_partition(0).await.expect("first resume");

    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    sleep(Duration::from_millis(300)).await;

    handler.resume_partition(0).await.expect("retried resume");

    let result = writing.await.expect("the write task must not panic");
    assert!(
        result.is_ok(),
        "a resume must record the fence it took itself, or the retry fences the window it \
         admitted, got {result:?}"
    );
}

/// Warming without a confirmed renewal must not take the epoch.
///
/// `init_transactions` grants the epoch to whoever initializes last, not
/// to whoever the protocol says owns the partition — so a zombie warming
/// on its way to noticing it is dead would fence the legitimate owner.
#[tokio::test]
async fn warming_without_a_confirmed_lease_does_not_take_the_epoch() {
    let topic = format!("fence_warm_auth_{}", uuid::Uuid::new_v4().simple());
    let owner = Arc::new(fenced_producers(&topic));
    owner.acquire(0).await.expect("the owner takes its fence");
    owner
        .produce(0, &test_person(1))
        .await
        .expect("the owner can write");

    let lapsed = common::live_authority();
    lapsed.surrender();
    let zombie = Arc::new(fenced_producers(&topic));
    let handler = common::test_handoff_handler_with_authority(&topic, Arc::clone(&zombie), lapsed);
    handler
        .warm_partition(0)
        .await
        .expect_err("a pod with no confirmed renewal must not warm");

    owner
        .produce(0, &test_person(2))
        .await
        .expect("a warm with no standing must not take the epoch from the real owner");
}

/// A resume without a confirmed renewal must not take the epoch either —
/// the same act, reached through the branch that cancels a handoff.
#[tokio::test]
async fn a_resume_without_a_confirmed_lease_does_not_take_the_epoch() {
    let topic = format!("fence_resume_auth_{}", uuid::Uuid::new_v4().simple());
    let owner = Arc::new(fenced_producers(&topic));
    owner.acquire(0).await.expect("the owner takes its fence");
    owner
        .produce(0, &test_person(1))
        .await
        .expect("the owner can write");

    let lapsed = common::live_authority();
    lapsed.surrender();
    let zombie = Arc::new(fenced_producers(&topic));
    let handler = common::test_handoff_handler_with_authority(&topic, Arc::clone(&zombie), lapsed);
    handler
        .resume_partition(0)
        .await
        .expect_err("a pod with no confirmed renewal must not resume");

    owner
        .produce(0, &test_person(2))
        .await
        .expect("a resume with no standing must not take the epoch from the real owner");
}

/// The claim can lapse *during* the acquire, by which point the epoch has
/// already moved. The pod cannot undo that, but it can decline to build on
/// a claim it no longer holds: it drops the fence and fails the
/// convergence, so the partition's real owner heals back to it instead of
/// finding a zombie serving on a stolen epoch.
#[tokio::test]
async fn a_warm_that_loses_its_claim_mid_acquire_gives_the_fence_back() {
    let topic = format!("fence_warm_midauth_{}", uuid::Uuid::new_v4().simple());
    // Seeded through a separate owner so the warm below is a real one: a
    // warm that fails for want of a topic would leave the fence behind
    // through its guard and prove nothing about this branch.
    let seed = fenced_producers(&topic);
    seed.acquire(0).await.expect("seed the topic");
    seed.produce(0, &test_person(1)).await.expect("seed record");

    let producers = Arc::new(fenced_producers(&topic));
    let clock = common::live_authority();
    let handler = common::test_handoff_handler_with_authority(
        &topic,
        Arc::clone(&producers),
        Arc::clone(&clock),
    );

    let losing = Arc::clone(&clock);
    let lease_loss = tokio::spawn(async move {
        sleep(Duration::from_millis(5)).await;
        losing.surrender();
    });
    let outcome = handler.warm_partition(0).await;
    lease_loss.await.unwrap();

    match outcome {
        // The surrender landed inside the warm: whichever check saw it,
        // an epoch taken across a lapsed claim is not this pod's to
        // keep.
        Err(_) => match producers.produce(0, &test_person(2)).await {
            Err(FencedProduceError::NotAcquired) => {}
            other => {
                panic!("a fence taken across a lapsed claim must be given back, got {other:?}")
            }
        },
        // The surrender lost the race outright — the claim was valid at
        // both checks, so the warm keeps its fence legitimately. A fast
        // broker reaches this branch; asserting the fence works keeps
        // the test meaningful there instead of panicking on good
        // behavior.
        Ok(()) => {
            producers
                .produce(0, &test_person(2))
                .await
                .expect("a warm whose claim never lapsed keeps a working fence");
        }
    }
}

/// The same window on the resume path.
#[tokio::test]
async fn a_resume_that_loses_its_claim_mid_acquire_gives_the_fence_back() {
    let topic = format!("fence_resume_midauth_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let clock = common::live_authority();
    let handler = common::test_handoff_handler_with_authority(
        &topic,
        Arc::clone(&producers),
        Arc::clone(&clock),
    );

    let losing = Arc::clone(&clock);
    let lease_loss = tokio::spawn(async move {
        sleep(Duration::from_millis(5)).await;
        losing.surrender();
    });
    let outcome = handler.resume_partition(0).await;
    lease_loss.await.unwrap();

    match outcome {
        // The surrender landed inside the resume: the fence it took
        // across a lapsed claim is not this pod's to keep.
        Err(_) => match producers.produce(0, &test_person(1)).await {
            Err(FencedProduceError::NotAcquired) => {}
            other => {
                panic!("a fence taken across a lapsed claim must be given back, got {other:?}")
            }
        },
        // The surrender lost the race outright — the claim held at both
        // checks and the resume keeps a working fence.
        Ok(()) => {
            producers
                .produce(0, &test_person(1))
                .await
                .expect("a resume whose claim never lapsed keeps a working fence");
        }
    }
}

/// The drain closes admissions before it waits, not after.
///
/// Waiting first leaves a window where a request admitted during the wait
/// acks after the count reached zero — a write landing above the watermark
/// the successor's warm is about to read, which is the loss the drain
/// exists to prevent.
#[tokio::test]
async fn the_drain_refuses_new_writes_while_it_is_still_waiting() {
    let topic = format!("fence_drain_order_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let inflight = Arc::new(InflightTracker::new());
    producers.acquire(0).await.expect("acquire the fence");

    let handler = common::test_handoff_handler_with_inflight(
        &topic,
        Arc::clone(&producers),
        Arc::clone(&inflight),
    );
    // One request in flight, so the drain cannot get past its wait.
    let seat = inflight.begin(0);
    let draining = tokio::spawn(async move { handler.drain_partition_inflight(0).await });
    sleep(Duration::from_millis(200)).await;

    assert!(
        inflight.try_begin(0).is_none(),
        "the drain admitted a write while it was still waiting for the last one"
    );

    drop(seat);
    tokio::time::timeout(Duration::from_secs(10), draining)
        .await
        .expect("the drain must finish once its last request leaves")
        .expect("the drain task must not panic")
        .expect("the drain must not fail");
}

/// Releasing a partition retires its fresh-fence mark.
///
/// The mark says "this convergence already holds the epoch". Left behind
/// across a release — which drops the producer — a later resume trusts it,
/// skips the acquire, and re-admits writes to a partition with no fence
/// installed at all.
#[tokio::test]
async fn releasing_a_partition_retires_its_fresh_fence_mark() {
    let topic = format!("fence_release_mark_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    producers.acquire(0).await.expect("seed the topic");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("seed record");
    handler.warm_partition(0).await.expect("warm the partition");
    handler
        .release_partition(0)
        .await
        .expect("release the partition");
    handler.resume_partition(0).await.expect("resume it again");

    producers
        .produce(0, &test_person(2))
        .await
        .expect("a resume after a release must take the fence again");
}

/// The repair pass has to actually run for a condemned partition.
///
/// `heal_fence` knows how to retake an epoch this pod gave up on, but
/// convergence only reaches it through `verify_serving`. Without that
/// call a condemned partition stays warmed, unfenced, and unwritable for
/// the life of the process, with no branch left to re-acquire.
#[tokio::test]
async fn verifying_a_served_partition_retakes_a_condemned_fence() {
    let topic = format!("fence_verify_heal_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));
    producers.acquire(0).await.expect("acquire the fence");

    // The state a failed abort or an unknown commit leaves behind.
    producers.condemn_for_test(0);
    assert!(
        !producers.holds(0),
        "a condemned producer must not still claim the partition"
    );

    let repaired = handler
        .verify_serving(0)
        .await
        .expect("verifying a served partition must not fail");
    assert!(
        repaired,
        "a heal that re-took the epoch is applied work, and must count as progress"
    );

    assert!(
        producers.holds(0),
        "a served partition whose fence was condemned must be healed back into service"
    );
}

/// A heal that cannot acquire must not fail the convergence run: the
/// run's failure budgets escalate to process death, which would trade
/// one partition's writes for every partition's reads. The wedge stays
/// visible through the partition-labeled failure counter and stays
/// retried by the reconcile tick — and the partition must still answer
/// as unfenced, never as quietly repaired.
#[tokio::test]
async fn a_heal_that_cannot_acquire_does_not_fail_the_run() {
    let topic = format!("fence_heal_err_{}", uuid::Uuid::new_v4().simple());
    let mut kafka = test_kafka_config();
    // Nothing listens here: the acquire's init round trip must fail.
    kafka.kafka_hosts = "127.0.0.1:1".to_string();
    let producers = Arc::new(FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: topic.clone(),
        init_timeout: Duration::from_secs(2),
        commit_timeout: Duration::from_secs(2),
        broker_txn_timeout: BROKER_TXN_TIMEOUT,
        window: Duration::from_millis(5),
        window_max_writes: 32,
        settle_budget: Duration::from_secs(1),
    }));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    let outcome = handler.verify_serving(0).await;
    assert!(
        !outcome.expect("a wedged heal must not fail the run"),
        "an unhealed partition is not applied work"
    );
    assert!(
        !producers.holds(0),
        "a partition that could not be healed must still answer as unfenced"
    );
}

/// A heal is an acquisition like any other: the same convergence's
/// resume step must trust its fence rather than bump the epoch again.
/// Re-acquiring on resume would fence the very window the heal just made
/// writable — the double-acquire the fresh-fence mark exists to prevent.
#[tokio::test]
async fn a_healed_fence_is_not_reacquired_by_the_same_convergences_resume() {
    let topic = format!("fence_heal_mark_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers_with_window(
        &topic,
        Duration::from_millis(600),
    ));
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));

    // A served partition with no usable fence — the state heal repairs.
    handler
        .verify_serving(0)
        .await
        .expect("healing a served partition must succeed");

    // In flight: the healed fence's window is open and uncommitted.
    let writing = {
        let p = Arc::clone(&producers);
        tokio::spawn(async move { p.produce(0, &test_person(1)).await })
    };
    sleep(Duration::from_millis(100)).await;

    handler
        .resume_partition(0)
        .await
        .expect("resuming a served partition must succeed");

    let result = writing.await.expect("the write task must not panic");
    assert!(
        result.is_ok(),
        "a resume in the same convergence must trust the healed fence, \
         not fence the window it is filling, got {result:?}"
    );
}

/// A committer that unwinds with subscribers still queued must condemn
/// the producer, not strand them.
///
/// The mark's drop used to clear `committing` and nothing else: the
/// orphaned waiter list blocked every later window (nothing opens while
/// waiters remain) while `is_usable` kept reporting the fence healthy —
/// every write on the partition parked until its own deadline, silently,
/// forever. Condemning routes it into the same bounce-and-recover story
/// as every other producer no window can be begun from.
#[tokio::test]
async fn an_unwound_committer_condemns_rather_than_stranding_its_waiters() {
    let topic = format!("fence_orphan_{}", uuid::Uuid::new_v4().simple());
    let producers = Arc::new(fenced_producers(&topic));
    producers.acquire(0).await.expect("acquire the fence");
    producers
        .produce(0, &test_person(1))
        .await
        .expect("a healthy fence writes");

    producers.orphan_committer_for_test(0);

    // Bounded: the pre-fix behavior parks this produce forever, and a
    // hung test reports a stuck runner rather than the defect.
    let outcome = tokio::time::timeout(
        Duration::from_secs(5),
        producers.produce(0, &test_person(2)),
    )
    .await
    .expect("a write after an unwound committer must answer, not park");
    match outcome {
        Err(FencedProduceError::NotAcquired) => {}
        other => panic!("an unwound committer's partition must answer as unowned, got {other:?}"),
    }
}

/// One run of the whole composition at the values production derives,
/// not the test constants: window 5ms, txn ~1.2s, settle 2s, broker
/// patience ~6s at the production lease. The per-arm tests pin each
/// mechanism with generous constants; this pins that the *derived*
/// numbers compose against a real broker — windows turn over, commits
/// land inside their budgets, and a drain (with its settle) finishes
/// inside the lease runway the arithmetic promises.
#[tokio::test]
async fn the_derived_production_timescales_compose_against_a_real_broker() {
    let mut config =
        personhog_leader::config::Config::init_from_env().expect("defaults are constructible");
    config.kafka_transactional_fencing = true;
    config.lease_gated_authority = true;
    config.lease_ttl = 30;
    config.fencing_txn_timeout_ms = 0;
    config.fencing_message_timeout_ms = 0;
    config
        .validate_fencing_timescales()
        .expect("the production lease supports fencing");

    let topic = format!("fence_derived_{}", uuid::Uuid::new_v4().simple());
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    let producers = Arc::new(FencedChangelogProducers::new(FencedProducerConfig {
        kafka,
        topic: topic.clone(),
        init_timeout: config.fencing_init_timeout(),
        commit_timeout: config.fencing_txn_timeout(),
        broker_txn_timeout: config.fencing_broker_txn_timeout(),
        window: Duration::from_millis(config.fencing_window_ms),
        window_max_writes: config.fencing_window_max_writes,
        settle_budget: config.fencing_settle_budget(),
    }));
    producers
        .acquire(0)
        .await
        .expect("acquire at derived init timeout");

    // Sustained concurrent writes across many real 5ms window turnovers.
    let mut writers = Vec::new();
    for w in 0..4 {
        let p = Arc::clone(&producers);
        writers.push(tokio::spawn(async move {
            let mut acked = 0u32;
            for i in 0..25 {
                p.produce(0, &test_person(i64::from(w * 100 + i)))
                    .await
                    .expect("a write inside the derived budgets must ack");
                acked += 1;
            }
            acked
        }));
    }
    let mut acked = 0;
    for writer in writers {
        acked += writer.await.expect("writer task");
    }
    assert_eq!(acked, 100);

    // The drain — wait plus settle — must fit the runway the validator
    // sized it against.
    let handler = common::test_handoff_handler(&topic, Arc::clone(&producers));
    let drain_started = std::time::Instant::now();
    handler
        .drain_partition_inflight(0)
        .await
        .expect("the drain succeeds at derived timescales");
    assert!(
        drain_started.elapsed() < config.lease_fence_runway(),
        "the drain must fit the lease runway it is budgeted for, took {:?} of {:?}",
        drain_started.elapsed(),
        config.lease_fence_runway()
    );

    // Everything acked is committed and visible to a read_committed
    // consumer, which is the property every consumer relies on.
    assert_eq!(
        read_committed_count(&topic).await,
        100,
        "every acked write must be committed once the drain settles"
    );
}
