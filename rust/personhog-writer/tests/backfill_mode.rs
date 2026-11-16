mod common;

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use common::{kafka_config, make_person, unique_team_id, TOPIC};
use common_kafka::kafka_producer::KafkaContext;
use lifecycle::{ComponentOptions, Manager};
use personhog_property_store::object_store::local::LocalFileSystem;
use personhog_property_store::object_store::ObjectStore;
use personhog_property_store::{
    shard_for, PartitionKey, PropertyReader, PropertyStoreConfig, PropertyWriter,
};
use personhog_writer::backfill::start;
use personhog_writer::backfill_mode::BackfillTopic;
use personhog_writer::catch_up::{self, CatchUp, Range};
use personhog_writer::consumer::ConsumerTask;
use personhog_writer::kafka::{PersonConsumer, Source};
use personhog_writer::pg::PgStore;
use personhog_writer::property_ownership;
use personhog_writer::writer::WriterTask;
use prost::Message;
use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer};
use rdkafka::message::Message as KafkaMessage;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::sync::mpsc;

const BACKFILL_TOPIC: &str = "personhog_backfill";

async fn wait_until(limit: Duration, mut ready: impl FnMut() -> bool) -> Result<(), ()> {
    let deadline = tokio::time::Instant::now() + limit;
    while !ready() {
        if tokio::time::Instant::now() >= deadline {
            return Err(());
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    Ok(())
}

async fn produce(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    partition: i32,
    team_id: i64,
    id: i64,
) {
    let payload = make_person(team_id, id, 3).encode_to_vec();
    let key = format!("{team_id}:{id}");
    producer
        .send_result(
            FutureRecord::to(topic)
                .partition(partition)
                .key(&key)
                .payload(&payload),
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

fn person_in(team_id: i64, partition: i32, partitions: i32) -> i64 {
    (1..)
        .find(|&id| shard_for(team_id, id, partitions as u32) as i32 == partition)
        .unwrap()
}

fn backfill_consumer(bootstrap: &str, group: &str) -> Arc<PersonConsumer> {
    Arc::new(
        PersonConsumer::for_backfill(
            &kafka_config(bootstrap),
            group,
            TOPIC.to_string(),
            BACKFILL_TOPIC.to_string(),
        )
        .unwrap(),
    )
}

fn backfill_topic() -> BackfillTopic {
    BackfillTopic {
        topic: Arc::from(BACKFILL_TOPIC),
        changelog: Arc::from(TOPIC),
    }
}

fn partitions_of(consumer: &PersonConsumer, topic: &str) -> HashSet<i32> {
    consumer
        .assigned_partitions()
        .ok()
        .flatten()
        .unwrap_or_default()
        .into_iter()
        .filter(|source| &*source.topic == topic)
        .map(|source| source.partition)
        .collect()
}

fn committed(probe: &BaseConsumer, topic: &str, partition: i32) -> Option<i64> {
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(topic, partition);
    probe
        .committed_offsets(tpl, Duration::from_secs(2))
        .ok()?
        .elements()
        .first()
        .and_then(|e| match e.offset() {
            Offset::Offset(offset) => Some(offset),
            _ => None,
        })
}

/// A group with a commit starts there, whatever its reset policy.
fn commit(bootstrap: &str, group: &str, offsets: &[(&str, i32, i64)]) {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()
        .unwrap();
    let mut tpl = TopicPartitionList::new();
    for &(topic, partition, offset) in offsets {
        tpl.add_partition_offset(topic, partition, Offset::Offset(offset))
            .unwrap();
    }
    consumer.assign(&tpl).unwrap();
    // The first commits fail until the client finds the group's coordinator.
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while let Err(e) = consumer.commit(&tpl, CommitMode::Sync) {
        assert!(std::time::Instant::now() < deadline, "commit: {e}");
        consumer.poll(Duration::from_millis(100));
    }
}

#[tokio::test]
async fn backfill_rows_write_the_shards_of_their_changelog_partition() {
    let partitions = 2;
    let (cluster, producer) = common::create_mock_kafka_with_partitions(partitions).await;
    cluster.create_topic(BACKFILL_TOPIC, partitions, 1).unwrap();
    let bootstrap = cluster.bootstrap_servers();
    let team_id = i64::from(unique_team_id());
    for partition in 0..partitions {
        let id = person_in(team_id, partition, partitions);
        produce(&producer, BACKFILL_TOPIC, partition, team_id, id).await;
    }

    let dir = tempfile::tempdir().unwrap();
    let object_store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let config = PropertyStoreConfig::local("props", partitions as u32);
    let properties = Arc::new(PropertyWriter::new(&config, Arc::clone(&object_store)));
    let group = "test-backfill-rows";
    let start: Vec<_> = (0..partitions).map(|p| (BACKFILL_TOPIC, p, 0)).collect();
    commit(&bootstrap, group, &start);
    let consumer = backfill_consumer(&bootstrap, group);

    let mut manager = Manager::builder("test").with_trap_signals(false).build();
    let ownership_handle = manager.register("property-ownership", ComponentOptions::new());
    let writer_handle = manager.register("writer", ComponentOptions::new());
    let consumer_handle = manager.register("consumer", ComponentOptions::new());
    let _monitor = manager.monitor_background();
    tokio::spawn(property_ownership::run(
        Arc::clone(&consumer),
        Arc::clone(&properties),
        consumer.take_ownership_events().unwrap(),
        Some(backfill_topic()),
        None,
        ownership_handle,
    ));
    let (tx, rx) = mpsc::channel(2);
    let writer = WriterTask::<PgStore, _>::new(Arc::clone(&consumer), None, rx, writer_handle)
        .with_properties(Arc::clone(&properties))
        .with_backfill(backfill_topic());
    tokio::spawn(writer.run());
    let consumer_task = ConsumerTask::new(
        Arc::clone(&consumer),
        vec![tx],
        100,
        Duration::from_millis(100),
        50,
        consumer_handle,
    )
    .with_backfill(backfill_topic());
    tokio::spawn(consumer_task.run());

    let probe: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", &bootstrap)
        .set("group.id", group)
        .create()
        .unwrap();
    wait_until(Duration::from_secs(30), || {
        (0..partitions).all(|p| committed(&probe, BACKFILL_TOPIC, p) == Some(1))
    })
    .await
    .expect("every backfill partition commits once its rows are durable");

    properties.close().await;
    let reader = PropertyReader::new(&config, object_store);
    for partition in 0..partitions {
        let id = person_in(team_id, partition, partitions);
        let stored = reader.get_fresh(team_id, id).await.unwrap();
        assert_eq!(stored.map(|s| s.version), Some(3), "partition {partition}");
    }
    reader.close().await;
}

#[tokio::test]
async fn backfill_members_own_the_same_partitions_of_both_topics() {
    let partitions = 3;
    let (cluster, _producer) = common::create_mock_kafka_with_partitions(partitions).await;
    cluster.create_topic(BACKFILL_TOPIC, partitions, 1).unwrap();
    let bootstrap = cluster.bootstrap_servers();
    let members = [0, 1].map(|_| backfill_consumer(&bootstrap, "test-backfill-colocation"));
    // Keeps each client polled, so rebalances land.
    for member in &members {
        let member = Arc::clone(member);
        tokio::spawn(async move {
            loop {
                drop(member.recv().await);
            }
        });
    }

    wait_until(Duration::from_secs(30), || {
        let owned: usize = members.iter().map(|m| partitions_of(m, TOPIC).len()).sum();
        owned == partitions as usize && members.iter().all(|m| !partitions_of(m, TOPIC).is_empty())
    })
    .await
    .expect("both members take changelog partitions");

    for member in &members {
        assert_eq!(
            partitions_of(member, TOPIC),
            partitions_of(member, BACKFILL_TOPIC)
        );
    }
}

#[tokio::test]
async fn the_backfill_topic_waits_while_the_changelog_lags() {
    let (cluster, producer) = common::create_mock_kafka_with_partitions(1).await;
    cluster.create_topic(BACKFILL_TOPIC, 1, 1).unwrap();
    let team_id = i64::from(unique_team_id());
    let live_rows = 30;
    for id in 1..=live_rows {
        produce(&producer, TOPIC, 0, team_id, id).await;
    }
    produce(&producer, BACKFILL_TOPIC, 0, team_id, live_rows + 1).await;
    let bootstrap = cluster.bootstrap_servers();
    commit(
        &bootstrap,
        "test-backfill-pace",
        &[(TOPIC, 0, 0), (BACKFILL_TOPIC, 0, 0)],
    );
    let consumer = backfill_consumer(&bootstrap, "test-backfill-pace");
    let pace = |consumer: &Arc<PersonConsumer>| {
        let consumer = Arc::clone(consumer);
        tokio::task::spawn_blocking(move || {
            consumer.pace_backfill(10, Duration::from_secs(5)).unwrap()
        })
    };
    let live = Source {
        topic: Arc::from(TOPIC),
        partition: 0,
    };

    // The first record means the member joined and started fetching.
    drop(consumer.recv().await.unwrap());
    let lagging = pace(&consumer).await.unwrap();
    while consumer.positions().unwrap().get(&live) != Some(&live_rows) {
        drop(
            tokio::time::timeout(Duration::from_secs(10), consumer.recv())
                .await
                .expect("the changelog keeps flowing while the backfill topic waits"),
        );
    }
    let caught_up = pace(&consumer).await.unwrap();

    assert!(
        lagging.paused && lagging.live_lag >= live_rows - 1,
        "{lagging:?}"
    );
    assert!(
        !caught_up.paused && caught_up.live_lag == 0,
        "{caught_up:?}"
    );
}

#[tokio::test]
async fn a_dual_writer_replays_the_changelog_the_backfill_group_never_committed() {
    let (cluster, producer) = common::create_mock_kafka_with_partitions(1).await;
    let bootstrap = cluster.bootstrap_servers();
    let team_id = i64::from(unique_team_id());
    // Person `id` sits at offset `id - 1`.
    let persons = 6;
    for id in 1..=persons {
        produce(&producer, TOPIC, 0, team_id, id).await;
    }
    let cases = [
        (
            "the backfill group is behind",
            Some(2),
            Some(5),
            Some(Range { from: 2, to: 5 }),
            false,
        ),
        (
            "the backfill group never committed",
            None,
            Some(5),
            Some(Range { from: 0, to: 5 }),
            false,
        ),
        ("the backfill group is ahead", Some(5), Some(3), None, false),
        ("this group never committed", Some(2), None, None, false),
        (
            "a late opener fenced this owner",
            Some(2),
            Some(5),
            Some(Range { from: 2, to: 5 }),
            true,
        ),
    ];
    let mut manager = Manager::builder("test").with_trap_signals(false).build();
    let handle = manager.register("property-ownership", ComponentOptions::new());
    let _monitor = manager.monitor_background();

    for (case, (name, backfill_commit, own_commit, expected, fenced)) in
        cases.into_iter().enumerate()
    {
        let catch_up = CatchUp {
            base: ClientConfig::new()
                .set("bootstrap.servers", &bootstrap)
                .clone(),
            backfill_group: format!("backfill-{case}"),
            own_group: format!("dual-{case}"),
            permits: Arc::new(tokio::sync::Semaphore::new(4)),
        };
        if let Some(offset) = backfill_commit {
            commit(&bootstrap, &catch_up.backfill_group, &[(TOPIC, 0, offset)]);
        }
        if let Some(offset) = own_commit {
            commit(&bootstrap, &catch_up.own_group, &[(TOPIC, 0, offset)]);
        }
        let range = {
            let catch_up = catch_up.clone();
            tokio::task::spawn_blocking(move || catch_up.range(TOPIC, 0))
                .await
                .unwrap()
                .unwrap()
        };
        assert_eq!(range, expected, "{name}");

        let dir = tempfile::tempdir().unwrap();
        let object_store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let config = PropertyStoreConfig::local("props", 1);
        let writer = PropertyWriter::new(&config, Arc::clone(&object_store));
        let key = PartitionKey {
            topic: Arc::from(TOPIC),
            partition: 0,
        };
        writer.assign(&key, 1, 1, || true).await.unwrap();
        let late_opener = PropertyWriter::new(&config, Arc::clone(&object_store));
        if fenced {
            late_opener.assign(&key, 1, 1, || true).await.unwrap();
        }
        if let Some(range) = range {
            let outcome = catch_up::replay(&catch_up, &writer, &key, 1, range, &handle, || true)
                .await
                .unwrap();
            let rows = (range.to - range.from) as u64;
            assert_eq!(outcome, catch_up::Outcome::Finished { rows }, "{name}");
        }
        writer.close().await;
        late_opener.close().await;

        let reader = PropertyReader::new(&config, object_store);
        for id in 1..=persons {
            let replayed = range.is_some_and(|r| (r.from..r.to).contains(&(id - 1)));
            let stored = reader.get_fresh(team_id, id).await.unwrap();
            assert_eq!(stored.is_some(), replayed, "{name}: person {id}");
        }
        reader.close().await;
    }
}

#[tokio::test]
async fn a_backfill_group_starts_where_the_writer_group_committed() {
    let (cluster, producer) = common::create_mock_kafka_with_partitions(1).await;
    cluster.create_topic(BACKFILL_TOPIC, 1, 1).unwrap();
    let bootstrap = cluster.bootstrap_servers();
    let team_id = i64::from(unique_team_id());
    for id in 1..=4 {
        produce(&producer, TOPIC, 0, team_id, id).await;
    }
    produce(&producer, BACKFILL_TOPIC, 0, team_id, 1).await;
    commit(&bootstrap, "test-writer-start", &[(TOPIC, 0, 2)]);
    let base = ClientConfig::new()
        .set("bootstrap.servers", &bootstrap)
        .clone();

    let copied = tokio::task::spawn_blocking(move || {
        start::copy_writer_offsets(&base, "test-writer-start", "test-backfill-start", TOPIC, 1)
    })
    .await
    .unwrap()
    .unwrap();

    assert_eq!(copied.get(&0), Some(&2));
    let consumer = backfill_consumer(&bootstrap, "test-backfill-start");
    let mut received = HashSet::new();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
    while received.len() < 3 {
        assert!(
            tokio::time::Instant::now() < deadline,
            "saw only {received:?}"
        );
        match tokio::time::timeout(Duration::from_millis(500), consumer.recv()).await {
            Ok(Ok(message)) => {
                received.insert((message.topic().to_string(), message.offset()));
            }
            Ok(Err(rdkafka::error::KafkaError::PartitionEOF(_))) | Err(_) => {}
            Ok(Err(e)) => panic!("{e}"),
        }
    }
    let expected: HashSet<(String, i64)> = [(TOPIC, 2), (TOPIC, 3), (BACKFILL_TOPIC, 0)]
        .into_iter()
        .map(|(topic, offset)| (topic.to_string(), offset))
        .collect();
    assert_eq!(received, expected);
}

#[tokio::test]
async fn a_start_refuses_the_writer_group_a_started_group_and_a_partial_writer() {
    let (cluster, _producer) = common::create_mock_kafka_with_partitions(2).await;
    let bootstrap = cluster.bootstrap_servers();
    commit(&bootstrap, "test-writer-refuse", &[(TOPIC, 0, 5)]);
    commit(
        &bootstrap,
        "test-backfill-started",
        &[(TOPIC, 0, 5), (TOPIC, 1, 5)],
    );
    let base = ClientConfig::new()
        .set("bootstrap.servers", &bootstrap)
        .clone();

    let refusals = tokio::task::spawn_blocking(move || {
        [
            ("test-writer-refuse", "test-writer-refuse"),
            ("test-writer-refuse", "test-backfill-started"),
            ("test-writer-refuse", "test-backfill-fresh"),
        ]
        .map(|(writer, backfill)| start::copy_writer_offsets(&base, writer, backfill, TOPIC, 2))
    })
    .await
    .unwrap();

    assert!(
        matches!(refusals[0], Err(start::StartError::WriterGroup(_))),
        "{:?}",
        refusals[0]
    );
    assert!(
        matches!(&refusals[1], Err(start::StartError::Started(p)) if p == &[0, 1]),
        "{:?}",
        refusals[1]
    );
    assert!(
        matches!(&refusals[2], Err(start::StartError::WriterMissing(p)) if p == &[1]),
        "{:?}",
        refusals[2]
    );
}

#[tokio::test]
async fn replays_wait_for_a_permit() {
    let (cluster, producer) = common::create_mock_kafka_with_partitions(1).await;
    let bootstrap = cluster.bootstrap_servers();
    let team_id = i64::from(unique_team_id());
    produce(&producer, TOPIC, 0, team_id, 1).await;
    let catch_up = CatchUp {
        base: ClientConfig::new()
            .set("bootstrap.servers", &bootstrap)
            .clone(),
        backfill_group: "backfill-permit".to_string(),
        own_group: "dual-permit".to_string(),
        permits: Arc::new(tokio::sync::Semaphore::new(1)),
    };
    let dir = tempfile::tempdir().unwrap();
    let object_store: Arc<dyn ObjectStore> =
        Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
    let config = PropertyStoreConfig::local("props", 1);
    let writer = PropertyWriter::new(&config, Arc::clone(&object_store));
    let key = PartitionKey {
        topic: Arc::from(TOPIC),
        partition: 0,
    };
    writer.assign(&key, 1, 1, || true).await.unwrap();
    let mut manager = Manager::builder("test").with_trap_signals(false).build();
    let handle = manager.register("property-ownership", ComponentOptions::new());
    let _monitor = manager.monitor_background();
    let range = Range { from: 0, to: 1 };

    let held = catch_up.permits.clone().try_acquire_owned().unwrap();
    let replay = catch_up::replay(&catch_up, &writer, &key, 1, range, &handle, || true);
    let waiting = tokio::time::timeout(Duration::from_secs(2), replay).await;
    assert!(waiting.is_err(), "a replay ran without a permit");
    drop(held);

    let outcome = catch_up::replay(&catch_up, &writer, &key, 1, range, &handle, || true)
        .await
        .unwrap();
    assert_eq!(outcome, catch_up::Outcome::Finished { rows: 1 });
    writer.close().await;
}
