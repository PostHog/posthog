//! End-to-end against rdkafka's `MockCluster`. The test plays the transport
//! side: it reads the feed and sends completions, so every seam rule is
//! exercised from outside the crate.
//!
//! The mock coordinator delays the first join by 3 s and every later round by
//! `session.timeout.ms` minus one second; a session timeout below that first
//! delay expires while the member waits for its JoinGroup response, so the
//! consumers here use 4 s: the floor, and 3 s rounds.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::config::ConsumerConfigBuilder;
use common_kafka_consumer::consumer_loop::{
    Completion, ConsumerLoop, ConsumerLoopConfig, ConsumerLoopError, Feed, TransportHandle,
};
use common_kafka_consumer::events::Observer;
use common_kafka_consumer::types::{AssignmentEpoch, DrainHarvest, Offset, Partition, RawMessage};
use common_kafka_consumer::{Charge, Group, GroupCompletion};
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer, FutureRecord};
use rdkafka::{ClientConfig, TopicPartitionList};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

const TOPIC: &str = "t";
const GROUP: &str = "loop-tests";
const WAIT: Duration = Duration::from_secs(15);

type Cluster = MockCluster<'static, DefaultProducerContext>;

#[derive(Debug, Clone, PartialEq, Eq)]
enum Ev {
    Assigned(Vec<Partition>),
    Revoked(Vec<Partition>, bool),
    Drained(Partition, bool),
    Committed(Vec<(Partition, Offset)>),
    Gate(bool),
    Stalled(Vec<Partition>),
}

#[derive(Clone, Default)]
struct Recorder(Arc<Mutex<Vec<Ev>>>);

impl Recorder {
    fn events(&self) -> Vec<Ev> {
        self.0.lock().unwrap().clone()
    }

    async fn wait_for(&self, what: &str, pred: impl Fn(&Ev) -> bool) -> Ev {
        let deadline = Instant::now() + WAIT;
        loop {
            if let Some(ev) = self.events().into_iter().find(|e| pred(e)) {
                return ev;
            }
            assert!(
                Instant::now() < deadline,
                "timed out waiting for {what}; events: {:?}",
                self.events()
            );
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

    fn committed(&self, p: Partition) -> Option<Offset> {
        self.events().iter().rev().find_map(|e| match e {
            Ev::Committed(batch) => batch.iter().find(|(q, _)| *q == p).map(|(_, o)| *o),
            _ => None,
        })
    }
}

impl Observer for Recorder {
    fn assigned(&self, partitions: &[Partition], _epoch: AssignmentEpoch) {
        self.0
            .lock()
            .unwrap()
            .push(Ev::Assigned(partitions.to_vec()));
    }
    fn revoked(&self, partitions: &[Partition], lost: bool) {
        self.0
            .lock()
            .unwrap()
            .push(Ev::Revoked(partitions.to_vec(), lost));
    }
    fn drained(&self, harvest: &DrainHarvest, committed: bool) {
        self.0
            .lock()
            .unwrap()
            .push(Ev::Drained(harvest.partition, committed));
    }
    fn committed(&self, offsets: &[(Partition, Offset)]) {
        self.0.lock().unwrap().push(Ev::Committed(offsets.to_vec()));
    }
    fn gate_closed(&self, closed: bool, _used: Charge) {
        self.0.lock().unwrap().push(Ev::Gate(closed));
    }
    fn stalled(&self, partitions: &[Partition]) {
        self.0
            .lock()
            .unwrap()
            .push(Ev::Stalled(partitions.to_vec()));
    }
}

/// Leaked on purpose: the loop tasks close their consumers during the test
/// runtime's teardown, after the test body's locals are gone, and a close
/// against a dropped cluster never completes.
fn cluster(partitions: i32) -> &'static Cluster {
    let cluster = MockCluster::new(1).expect("mock cluster");
    cluster
        .create_topic(TOPIC, partitions, 1)
        .expect("create topic");
    Box::leak(Box::new(cluster))
}

fn client_config(cluster: &Cluster, client_id: &str) -> ClientConfig {
    let mut config = ConsumerConfigBuilder::for_batch_consumer(&cluster.bootstrap_servers(), GROUP)
        .with_sticky_partition_assignment(Some(client_id), false)
        .with_session_timeout_ms(4000)
        .with_heartbeat_interval_ms(1000)
        .with_fetch_wait_max_ms(50)
        .build();
    config.set("auto.offset.reset", "earliest");
    config
}

fn loop_config(cluster: &Cluster, client_id: &str) -> ConsumerLoopConfig {
    let mut config = ConsumerLoopConfig::new(client_config(cluster, client_id), TOPIC);
    config.tick_interval = Duration::from_millis(50);
    config.commit_interval = Duration::from_millis(100);
    config.commit_monitor_interval = Duration::from_millis(200);
    config.stall_timeout = Duration::from_secs(60);
    config
}

struct Running {
    handle: TransportHandle,
    recorder: Recorder,
    shutdown: CancellationToken,
    task: JoinHandle<Result<(), ConsumerLoopError>>,
}

fn start(config: ConsumerLoopConfig) -> Running {
    drop(
        tracing_subscriber::fmt()
            .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
            .with_test_writer()
            .try_init(),
    );
    let recorder = Recorder::default();
    let (consumer_loop, handle) = ConsumerLoop::build(config, recorder.clone()).expect("build");
    let shutdown = CancellationToken::new();
    let task = tokio::spawn(consumer_loop.run(shutdown.clone()));
    Running {
        handle,
        recorder,
        shutdown,
        task,
    }
}

fn producer(cluster: &Cluster) -> FutureProducer {
    ClientConfig::new()
        .set("bootstrap.servers", cluster.bootstrap_servers())
        .set("message.timeout.ms", "5000")
        .create()
        .expect("producer")
}

async fn produce(producer: &FutureProducer, partition: i32, key: &str, payload: &str) {
    producer
        .send(
            FutureRecord::to(TOPIC)
                .partition(partition)
                .key(key)
                .payload(payload),
            Duration::from_secs(5),
        )
        .await
        .expect("produce");
}

/// Whole-group completions for the transport side to send back.
fn completions(groups: &[Group<RawMessage>]) -> Vec<GroupCompletion> {
    groups.iter().map(Group::completion).collect()
}

/// The next feed item, or a timeout failure.
async fn next(feed: &mut mpsc::UnboundedReceiver<Feed>, what: &str) -> Feed {
    tokio::time::timeout(WAIT, feed.recv())
        .await
        .unwrap_or_else(|_| panic!("timed out waiting for {what}"))
        .expect("feed closed")
}

/// Read batches until `n` messages have arrived; returns their groups.
async fn groups_until(
    feed: &mut mpsc::UnboundedReceiver<Feed>,
    n: usize,
) -> Vec<Group<RawMessage>> {
    let mut groups = Vec::new();
    let mut seen = 0;
    while seen < n {
        match next(feed, &format!("{n} messages ({seen} so far)")).await {
            Feed::Batch(acc) => {
                for g in acc.into_groups() {
                    seen += g.messages.len();
                    groups.push(g);
                }
            }
            Feed::Revoked { .. } => panic!("unexpected revoke while collecting"),
        }
    }
    groups
}

/// What the broker holds as the group's committed offset.
fn broker_committed(cluster: &Cluster, partition: i32) -> Option<i64> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", cluster.bootstrap_servers())
        .set("group.id", GROUP)
        .create()
        .expect("probe consumer");
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(TOPIC, partition);
    let committed = consumer
        .committed_offsets(tpl, Duration::from_secs(5))
        .expect("committed_offsets");
    match committed.elements()[0].offset() {
        rdkafka::Offset::Offset(o) => Some(o),
        _ => None,
    }
}

async fn wait_for_broker_committed(cluster: &Cluster, partition: i32, expected: i64) {
    let deadline = Instant::now() + WAIT;
    loop {
        let committed = broker_committed(cluster, partition);
        if committed == Some(expected) {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "broker committed offset for p{partition} is {committed:?}, expected {expected}"
        );
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

fn p(i: i32) -> Partition {
    Partition(i)
}

// ---- tests ----

#[tokio::test]
async fn commits_land_at_the_frontier_only() {
    let cluster = cluster(1);
    let producer = producer(cluster);
    for i in 0..6 {
        produce(&producer, 0, &format!("k{}", i / 2), &format!("m{i}")).await;
    }
    let mut running = start(loop_config(cluster, "a"));
    let groups = groups_until(&mut running.handle.feed, 6).await;

    // Complete the last key first: nothing may commit past the gap.
    let (last, rest): (Vec<Group<RawMessage>>, Vec<Group<RawMessage>>) = groups
        .into_iter()
        .partition(|g| g.offsets.contains(&Offset(5)));
    running
        .handle
        .completions
        .send(Completion::Completed(completions(&last)))
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert_eq!(
        running.recorder.committed(p(0)),
        None,
        "committed past a gap"
    );

    running
        .handle
        .completions
        .send(Completion::Completed(completions(&rest)))
        .await
        .unwrap();
    running
        .recorder
        .wait_for(
            "commit at 6",
            |e| matches!(e, Ev::Committed(b) if b.contains(&(p(0), Offset(6)))),
        )
        .await;
    wait_for_broker_committed(cluster, 0, 6).await;

    running.shutdown.cancel();
    answer_shutdown(&mut running).await;
    running.task.await.unwrap().expect("clean stop");
}

#[tokio::test]
async fn revoke_drains_commits_then_hands_back_and_the_new_owner_resumes_after_the_commit() {
    let cluster = cluster(2);
    let producer = producer(cluster);
    for i in 0..4 {
        produce(&producer, 0, "k", &format!("p0-{i}")).await;
        produce(&producer, 1, "k", &format!("p1-{i}")).await;
    }
    let mut a = start(loop_config(cluster, "a"));
    a.recorder
        .wait_for(
            "A owns both",
            |e| matches!(e, Ev::Assigned(ps) if ps.len() == 2),
        )
        .await;
    let held = groups_until(&mut a.handle.feed, 8).await;

    let mut b = start(loop_config(cluster, "b"));
    let revoked = a
        .recorder
        .wait_for(
            "A revoked one",
            |e| matches!(e, Ev::Revoked(ps, false) if ps.len() == 1),
        )
        .await;
    let Ev::Revoked(moved, _) = revoked else {
        unreachable!()
    };
    let moved = moved[0];
    match next(&mut a.handle.feed, "revoke marker").await {
        Feed::Revoked { partition, epoch } => {
            assert_eq!(partition, moved);
            // B must not own the partition while A still holds it.
            assert!(!b
                .recorder
                .events()
                .iter()
                .any(|e| matches!(e, Ev::Assigned(_))));
            // Settle the in-flight work, then answer the marker.
            let (for_moved, others): (Vec<_>, Vec<_>) =
                held.into_iter().partition(|g| g.partition == moved);
            a.handle
                .completions
                .send(Completion::Completed(completions(&for_moved)))
                .await
                .unwrap();
            a.handle
                .completions
                .send(Completion::Drained { partition, epoch })
                .await
                .unwrap();
            drop(others);
        }
        Feed::Batch(_) => panic!("expected the revoke marker"),
    }
    a.recorder
        .wait_for("A drained with commit", |e| *e == Ev::Drained(moved, true))
        .await;
    assert_eq!(a.recorder.committed(moved), Some(Offset(4)));

    b.recorder
        .wait_for("B owns the moved partition", |e| {
            *e == Ev::Assigned(vec![moved])
        })
        .await;
    // B starts after A's final commit: no replay of the drained work.
    produce(&producer, moved.0, "k", "after").await;
    let groups = groups_until(&mut b.handle.feed, 1).await;
    assert_eq!(groups[0].offsets, vec![Offset(4)]);

    a.shutdown.cancel();
    b.shutdown.cancel();
    // The drains at shutdown: answer every marker.
    for running in [&mut a, &mut b] {
        answer_shutdown(running).await;
    }
    a.task.await.unwrap().expect("A stops");
    b.task.await.unwrap().expect("B stops");
}

/// Play a transport that drops everything at shutdown: answer each revoke
/// marker with `Drained` and ignore batches.
async fn answer_shutdown(running: &mut Running) {
    loop {
        match tokio::time::timeout(Duration::from_secs(5), running.handle.feed.recv()).await {
            Ok(Some(Feed::Revoked { partition, epoch })) => {
                running
                    .handle
                    .completions
                    .send(Completion::Drained { partition, epoch })
                    .await
                    .unwrap();
            }
            Ok(Some(Feed::Batch(_))) => {}
            Ok(None) | Err(_) => return,
        }
    }
}

#[tokio::test]
async fn the_gate_closes_at_cap_and_reopens_at_low() {
    let cluster = cluster(1);
    let producer = producer(cluster);
    for i in 0..10 {
        produce(&producer, 0, &format!("k{i}"), "m").await;
    }
    let mut config = loop_config(cluster, "a");
    config.budget = Charge {
        events: 4,
        bytes: u64::MAX,
    };
    config.budget_low_ratio = 0.5;
    config.poll_max_messages = 2;
    let mut running = start(config);

    let held = groups_until(&mut running.handle.feed, 4).await;
    running
        .recorder
        .wait_for("gate closed", |e| *e == Ev::Gate(true))
        .await;
    // Nothing more arrives while closed.
    assert!(
        tokio::time::timeout(Duration::from_millis(500), running.handle.feed.recv())
            .await
            .is_err(),
        "polled past the cap"
    );

    // One refund leaves used=3, above low=2: still closed.
    let mut held = held.into_iter();
    running
        .handle
        .completions
        .send(Completion::Completed(vec![held
            .next()
            .unwrap()
            .completion()]))
        .await
        .unwrap();
    running
        .recorder
        .wait_for("first commit", |e| matches!(e, Ev::Committed(_)))
        .await;
    assert!(
        tokio::time::timeout(Duration::from_millis(400), running.handle.feed.recv())
            .await
            .is_err(),
        "reopened above low"
    );

    running
        .handle
        .completions
        .send(Completion::Completed(vec![held
            .next()
            .unwrap()
            .completion()]))
        .await
        .unwrap();
    running
        .recorder
        .wait_for("gate reopened", |e| *e == Ev::Gate(false))
        .await;
    let more = groups_until(&mut running.handle.feed, 2).await;
    assert_eq!(more.len(), 2);

    running.shutdown.cancel();
    answer_shutdown(&mut running).await;
    running.task.await.unwrap().expect("clean stop");
}

#[tokio::test]
async fn the_stall_watchdog_fires_only_without_progress() {
    let cluster = cluster(1);
    let producer = producer(cluster);
    for i in 0..4 {
        produce(&producer, 0, &format!("k{i}"), "m").await;
    }
    let mut config = loop_config(cluster, "a");
    config.stall_timeout = Duration::from_millis(600);
    let mut running = start(config);
    let mut held = groups_until(&mut running.handle.feed, 4).await.into_iter();

    // Progress inside the window resets the deadline.
    tokio::time::sleep(Duration::from_millis(400)).await;
    running
        .handle
        .completions
        .send(Completion::Completed(vec![held
            .next()
            .unwrap()
            .completion()]))
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert!(
        !running.task.is_finished(),
        "stalled despite progress 400 ms ago"
    );

    // Then nothing lands for a full window: the loop fails.
    let result = tokio::time::timeout(Duration::from_secs(3), running.task)
        .await
        .expect("loop exits on stall")
        .unwrap();
    assert!(matches!(result, Err(ConsumerLoopError::Stalled(ps)) if ps == vec![p(0)]));
    assert!(running.recorder.events().contains(&Ev::Stalled(vec![p(0)])));
}

#[tokio::test]
async fn a_completion_after_teardown_dies_by_epoch() {
    let cluster = cluster(2);
    let producer = producer(cluster);
    for i in 0..3 {
        produce(&producer, 0, "k", &format!("p0-{i}")).await;
        produce(&producer, 1, "k", &format!("p1-{i}")).await;
    }
    let mut a = start(loop_config(cluster, "a"));
    let held = groups_until(&mut a.handle.feed, 6).await;

    let mut b = start(loop_config(cluster, "b"));
    let moved = match next(&mut a.handle.feed, "revoke marker").await {
        Feed::Revoked { partition, epoch } => {
            // Drop the work instead of settling it: hand back at once.
            a.handle
                .completions
                .send(Completion::Drained { partition, epoch })
                .await
                .unwrap();
            partition
        }
        Feed::Batch(_) => panic!("expected the revoke marker"),
    };
    a.recorder
        .wait_for("A drained", |e| *e == Ev::Drained(moved, true))
        .await;
    assert_eq!(
        a.recorder.committed(moved),
        None,
        "nothing completed, nothing to commit"
    );

    // The straggler: completions for the torn-down partition.
    let (stale, live): (Vec<_>, Vec<_>) = held.into_iter().partition(|g| g.partition == moved);
    a.handle
        .completions
        .send(Completion::Completed(completions(&stale)))
        .await
        .unwrap();
    // The loop is unharmed: the retained partition still commits.
    a.handle
        .completions
        .send(Completion::Completed(completions(&live)))
        .await
        .unwrap();
    let retained = p(1 - moved.0);
    a.recorder
        .wait_for(
            "retained commits",
            |e| matches!(e, Ev::Committed(b) if b.contains(&(retained, Offset(3)))),
        )
        .await;
    assert_eq!(a.recorder.committed(moved), None, "the straggler committed");

    b.recorder
        .wait_for("B owns the moved partition", |e| {
            *e == Ev::Assigned(vec![moved])
        })
        .await;
    // B replays the dropped work from the start.
    let groups = groups_until(&mut b.handle.feed, 3).await;
    let offsets: Vec<Offset> = groups.iter().flat_map(|g| g.offsets.clone()).collect();
    assert_eq!(offsets, vec![Offset(0), Offset(1), Offset(2)]);

    a.shutdown.cancel();
    b.shutdown.cancel();
    answer_shutdown(&mut a).await;
    answer_shutdown(&mut b).await;
    a.task.await.unwrap().expect("A stops");
    b.task.await.unwrap().expect("B stops");
}

#[tokio::test]
async fn shutdown_drains_commits_and_leaves() {
    let cluster = cluster(2);
    let producer = producer(cluster);
    for i in 0..3 {
        produce(&producer, 0, "k", &format!("p0-{i}")).await;
        produce(&producer, 1, "k", &format!("p1-{i}")).await;
    }
    let mut running = start(loop_config(cluster, "a"));
    let held = groups_until(&mut running.handle.feed, 6).await;

    running.shutdown.cancel();
    // Both markers arrive; settle the in-flight work behind each.
    let mut markers = Vec::new();
    for _ in 0..2 {
        match next(&mut running.handle.feed, "shutdown marker").await {
            Feed::Revoked { partition, epoch } => markers.push((partition, epoch)),
            Feed::Batch(_) => panic!("polled during shutdown"),
        }
    }
    assert!(!running.task.is_finished(), "left before the drain");
    running
        .handle
        .completions
        .send(Completion::Completed(completions(&held)))
        .await
        .unwrap();
    for (partition, epoch) in markers {
        running
            .handle
            .completions
            .send(Completion::Drained { partition, epoch })
            .await
            .unwrap();
    }
    tokio::time::timeout(WAIT, running.task)
        .await
        .expect("loop stops")
        .unwrap()
        .expect("clean stop");

    assert_eq!(broker_committed(cluster, 0), Some(3));
    assert_eq!(broker_committed(cluster, 1), Some(3));

    // The next member of the group starts where the commit left off.
    produce(&producer, 0, "k", "after").await;
    let mut next_owner = start(loop_config(cluster, "b"));
    let groups = groups_until(&mut next_owner.handle.feed, 1).await;
    assert_eq!(groups[0].offsets, vec![Offset(3)]);
    next_owner.shutdown.cancel();
    answer_shutdown(&mut next_owner).await;
    next_owner.task.await.unwrap().expect("clean stop");
}
