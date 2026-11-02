use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use metrics_util::debugging::{DebugValue, DebuggingRecorder};
use personhog_changelog_relay::consumer::{consumer_client_config, ChangelogConsumer};
use personhog_changelog_relay::relay::Relay;
use personhog_coordination::follow::Follower;
use personhog_coordination::types::{ChangelogConfig, Generation};
use personhog_proto::personhog::types::v1::Person;
use prost::Message as _;
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::message::{Headers, Message};
use rdkafka::producer::FutureRecord;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

const CHANGELOG: &str = "personhog_updates_test";
const OUTPUT: &str = "clickhouse_person_test";
const DLQ: &str = "relay_dlq_test";
const GROUP: &str = "relay-test";

fn person(id: i64) -> Person {
    Person {
        id,
        uuid: format!("0192f3a1-7c4e-7a3b-9d2e-{id:012}"),
        team_id: 1,
        properties: b"{}".to_vec(),
        created_at: 1_700_000_000_000,
        version: 1,
        ..Default::default()
    }
}

/// Every record on `topic`, read from the beginning until `count` arrive.
fn read_all(bootstrap: &str, topic: &str, count: usize) -> Vec<rdkafka::message::OwnedMessage> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", format!("reader-{topic}"))
        .create()
        .unwrap();
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(topic, 0, Offset::Beginning)
        .unwrap();
    consumer.assign(&tpl).unwrap();
    let mut out = Vec::new();
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while out.len() < count && std::time::Instant::now() < deadline {
        if let Some(Ok(message)) = consumer.poll(Duration::from_millis(100)) {
            out.push(message.detach());
        }
    }
    out
}

/// Good records reach the output as Node's rows with no key; a record that is
/// not a proto, and one whose row the output rejects as too large, reach the
/// DLQ as their original bytes; the group commits past all of them.
#[tokio::test]
async fn a_batch_is_relayed_dead_lettered_and_committed() {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    for topic in [CHANGELOG, OUTPUT, DLQ] {
        cluster.create_topic(topic, 1, 1).unwrap();
    }
    let bootstrap = cluster.bootstrap_servers();
    // Escaping roughly doubles these properties in the row, past the output's
    // size limit, while the record itself stays under it.
    let oversized = Person {
        properties: format!(r#"{{"k":"{}"}}"#, r#"\""#.repeat(400)).into_bytes(),
        ..person(3)
    };
    let payloads = [
        person(1).encode_to_vec(),
        vec![0xFF; 8],
        person(2).encode_to_vec(),
        oversized.encode_to_vec(),
    ];
    for payload in &payloads {
        producer
            .send(
                FutureRecord::<(), _>::to(CHANGELOG)
                    .partition(0)
                    .payload(payload),
                Duration::from_secs(5),
            )
            .await
            .unwrap();
    }

    let kafka = KafkaConfig::init_from_hashmap(&HashMap::from([
        ("KAFKA_HOSTS".to_string(), bootstrap.clone()),
        (
            "KAFKA_PRODUCER_MESSAGE_MAX_BYTES".to_string(),
            "1500".to_string(),
        ),
    ]))
    .unwrap();
    let consumer = Arc::new(
        ChangelogConsumer::new(
            &consumer_client_config(&kafka, GROUP),
            CHANGELOG.to_string(),
        )
        .unwrap(),
    );
    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "relay",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();
    let output = common_kafka::kafka_producer::create_kafka_producer(&kafka, handle.clone())
        .await
        .unwrap();
    let relay = Relay::new(
        Arc::clone(&consumer),
        output,
        OUTPUT.to_string(),
        DLQ.to_string(),
        10,
        Duration::from_millis(500),
    );
    let run_handle = handle.clone();
    let running = tokio::spawn(async move { relay.run(&run_handle).await });

    let rows = tokio::task::spawn_blocking({
        let bootstrap = bootstrap.clone();
        move || read_all(&bootstrap, OUTPUT, 2)
    })
    .await
    .unwrap();
    let dead = tokio::task::spawn_blocking({
        let bootstrap = bootstrap.clone();
        move || read_all(&bootstrap, DLQ, 2)
    })
    .await
    .unwrap();

    assert_eq!(rows.len(), 2);
    for row in &rows {
        assert!(row.key().is_none());
        assert!(row.headers().is_none());
        let value: serde_json::Value = serde_json::from_slice(row.payload().unwrap()).unwrap();
        assert_eq!(value["created_at"], "2023-11-14 22:13:20");
    }
    assert_eq!(dead.len(), 2);
    let headers = |message: &rdkafka::message::OwnedMessage| -> HashMap<String, Vec<u8>> {
        message
            .headers()
            .unwrap()
            .iter()
            .map(|h| (h.key.to_string(), h.value.unwrap_or_default().to_vec()))
            .collect()
    };
    for (message, payload, offset, reason) in [
        (&dead[0], &payloads[1], "1", "decode"),
        (&dead[1], &payloads[3], "3", "rejected"),
    ] {
        assert_eq!(message.payload(), Some(&payload[..]));
        let headers = headers(message);
        assert_eq!(headers["source_topic"], CHANGELOG.as_bytes());
        assert_eq!(headers["source_offset"], offset.as_bytes());
        assert_eq!(headers["reason"], reason.as_bytes());
    }

    let committed = tokio::task::spawn_blocking(move || {
        let deadline = std::time::Instant::now() + Duration::from_secs(10);
        loop {
            let mut tpl = TopicPartitionList::new();
            tpl.add_partition(CHANGELOG, 0);
            let probe: BaseConsumer = ClientConfig::new()
                .set("bootstrap.servers", &bootstrap)
                .set("group.id", GROUP)
                .create()
                .unwrap();
            let offset = probe
                .committed_offsets(tpl, Duration::from_secs(5))
                .unwrap()
                .find_partition(CHANGELOG, 0)
                .map(|e| e.offset());
            if offset == Some(Offset::Offset(4)) || std::time::Instant::now() > deadline {
                return offset;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    })
    .await
    .unwrap();
    assert_eq!(committed, Some(Offset::Offset(4)));

    handle.request_shutdown();
    tokio::time::timeout(Duration::from_secs(5), running)
        .await
        .expect("the relay stops on shutdown")
        .unwrap();
}

/// The local broker (docker), which the writer's suites use too: the mock
/// broker never answers the rejoin a changed subscription sends.
const BROKER: &str = "localhost:9092";

async fn broker_topics(topics: &[&str]) {
    let admin: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", BROKER)
        .create()
        .unwrap();
    let new: Vec<_> = topics
        .iter()
        .map(|t| NewTopic::new(t, 1, TopicReplication::Fixed(1)))
        .collect();
    for result in admin
        .create_topics(new.iter(), &AdminOptions::new())
        .await
        .unwrap()
    {
        result.unwrap();
    }
}

/// Once the old generation is drained the subscription moves to the live
/// topic, and relays what the leaders produced there before the move.
#[tokio::test]
async fn a_move_to_the_live_topic_relays_it_from_its_first_record() {
    let tag = uuid::Uuid::new_v4().simple().to_string();
    let (old, new, output, dlq, group) = (
        format!("relay_old_{tag}"),
        format!("relay_new_{tag}"),
        format!("relay_out_{tag}"),
        format!("relay_dlq_{tag}"),
        format!("relay_{tag}"),
    );
    broker_topics(&[&old, &new, &output, &dlq]).await;

    let kafka = KafkaConfig::init_from_hashmap(&HashMap::from([(
        "KAFKA_HOSTS".to_string(),
        BROKER.to_string(),
    )]))
    .unwrap();
    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "relay",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();
    let producer = common_kafka::kafka_producer::create_kafka_producer(&kafka, handle.clone())
        .await
        .unwrap();
    for (topic, id) in [(&old, 1), (&new, 2)] {
        producer
            .send(
                FutureRecord::<(), _>::to(topic)
                    .partition(0)
                    .payload(&person(id).encode_to_vec()),
                Duration::from_secs(5),
            )
            .await
            .unwrap();
    }

    let consumer = Arc::new(
        ChangelogConsumer::new(&consumer_client_config(&kafka, &group), old.clone()).unwrap(),
    );
    let relay = Relay::new(
        Arc::clone(&consumer),
        producer,
        output.clone(),
        dlq,
        10,
        Duration::from_millis(200),
    );
    let run_handle = handle.clone();
    let running = tokio::spawn(async move { relay.run(&run_handle).await });
    let read = |count: usize| {
        let output = output.clone();
        tokio::task::spawn_blocking(move || {
            read_all(BROKER, &output, count)
                .iter()
                .map(|row| {
                    let value: serde_json::Value =
                        serde_json::from_slice(row.payload().unwrap()).unwrap();
                    value["id"].as_str().unwrap().to_string()
                })
                .collect::<Vec<_>>()
        })
    };

    assert_eq!(read(1).await.unwrap(), vec![person(1).uuid]);

    let flipped = ChangelogConfig {
        topic: new.clone(),
        partitions: 1,
        epoch: 2,
        writer_group: "writer".to_string(),
        retire_groups: vec![group],
        draining: vec![Generation {
            topic: old.clone(),
            partitions: 1,
            epoch: 1,
        }],
    };
    let moved = Follower::default()
        .follow_once(consumer.as_ref(), &flipped, |_| async { Ok(true) })
        .await
        .unwrap();
    assert_eq!(moved, Some(old));

    assert_eq!(read(2).await.unwrap(), vec![person(1).uuid, person(2).uuid]);

    handle.request_shutdown();
    tokio::time::timeout(Duration::from_secs(5), running)
        .await
        .expect("the relay stops on shutdown")
        .unwrap();
}

/// While a delivery retries, here into a DLQ too small for the record, the
/// lag gauge climbs from the stuck record's age instead of freezing.
#[tokio::test]
async fn the_lag_climbs_while_a_delivery_retries() {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    for topic in [CHANGELOG, OUTPUT, DLQ] {
        cluster.create_topic(topic, 1, 1).unwrap();
    }
    let produced_at = chrono::Utc::now().timestamp_millis() - 60_000;
    producer
        .send(
            FutureRecord::<(), _>::to(CHANGELOG)
                .partition(0)
                .timestamp(produced_at)
                .payload(&vec![0xFF; 2_000]),
            Duration::from_secs(5),
        )
        .await
        .unwrap();

    let kafka = KafkaConfig::init_from_hashmap(&HashMap::from([
        ("KAFKA_HOSTS".to_string(), cluster.bootstrap_servers()),
        (
            "KAFKA_PRODUCER_MESSAGE_MAX_BYTES".to_string(),
            "1500".to_string(),
        ),
    ]))
    .unwrap();
    let consumer = Arc::new(
        ChangelogConsumer::new(
            &consumer_client_config(&kafka, GROUP),
            CHANGELOG.to_string(),
        )
        .unwrap(),
    );
    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "relay",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();
    let output = common_kafka::kafka_producer::create_kafka_producer(&kafka, handle.clone())
        .await
        .unwrap();
    let recorder = DebuggingRecorder::new();
    let snapshotter = recorder.snapshotter();
    let relay = metrics::with_local_recorder(&recorder, || {
        Relay::new(
            Arc::clone(&consumer),
            output,
            OUTPUT.to_string(),
            DLQ.to_string(),
            10,
            Duration::from_millis(200),
        )
    });
    let run_handle = handle.clone();
    let running = tokio::spawn(async move { relay.run(&run_handle).await });

    let lag = || {
        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find(|(key, _, _, _)| key.key().name() == "personhog_changelog_relay_lag_seconds")
            .map(|(_, _, _, value)| match value {
                DebugValue::Gauge(value) => value.into_inner(),
                _ => panic!("the lag is a gauge"),
            })
            .unwrap_or_default()
    };
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while lag() < 60.0 && std::time::Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert!(lag() >= 60.0, "lag {} while the DLQ send retries", lag());

    handle.request_shutdown();
    tokio::time::timeout(Duration::from_secs(5), running)
        .await
        .expect("the relay stops on shutdown")
        .unwrap();
}
