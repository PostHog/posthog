//! End-to-end shuffler test against an in-process rdkafka `MockCluster` (no external broker or DB).
//! Asserts that only forwardable events land, that each `(team_id, person_id)` lands on a single
//! partition, and that the envelope payload maps every field.

use std::sync::Arc;
use std::time::{Duration, Instant};

use cohort_event_shuffler::config::Config;
use cohort_event_shuffler::consumer::EventShuffler;
use cohort_event_shuffler::event::CohortStreamEvent;
use cohort_event_shuffler::filter_team_index::TeamIndex;
use cohort_event_shuffler::producer::CohortStreamProducer;
use common_kafka::kafka_consumer::SingleTopicConsumer;
use common_types::cohort::TeamAllowlist;
use common_types::{ClickHouseEvent, PersonMode};
use lifecycle::{ComponentOptions, Manager};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::{ClientConfig, Message};
use uuid::Uuid;

const INPUT_TOPIC: &str = "clickhouse_events_json";
const OUTPUT_TOPIC: &str = "cohort_stream_events";
const OUTPUT_PARTITIONS: i32 = 8;

struct InputSpec {
    team_id: i32,
    person_id: Option<&'static str>,
    event: &'static str,
    forwardable: bool,
}

fn test_config(bootstrap: &str) -> Config {
    Config {
        bind_host: "0.0.0.0".to_string(),
        bind_port: 0,
        export_prometheus: false,
        kafka_hosts: bootstrap.to_string(),
        kafka_tls: false,
        kafka_client_rack: String::new(),
        kafka_client_id: String::new(),
        input_topic: INPUT_TOPIC.to_string(),
        kafka_consumer_group: "shuffler-itest".to_string(),
        kafka_consumer_offset_reset: "earliest".to_string(),
        output_topic: OUTPUT_TOPIC.to_string(),
        kafka_producer_partitioner: "murmur2_random".to_string(),
        kafka_compression_codec: "none".to_string(),
        database_url: String::new(), // unused: test loads the team index directly
        min_pg_connections: 0,
        max_pg_connections: 1,
        pg_acquire_timeout_secs: 5,
        pg_statement_timeout_ms: 0,
        team_index_refresh_secs: 300,
        team_index_refresh_jitter_secs: 0,
        team_allowlist: TeamAllowlist::All,
        recv_batch_size: 100,
        recv_batch_timeout_ms: 200,
    }
}

fn clickhouse_event(uuid: Uuid, spec: &InputSpec) -> ClickHouseEvent {
    ClickHouseEvent {
        uuid,
        team_id: spec.team_id,
        project_id: Some(spec.team_id as i64),
        event: spec.event.to_string(),
        distinct_id: format!("did-{}", spec.person_id.unwrap_or("anon")),
        properties: Some(r#"{"$current_url":"/pricing"}"#.to_string()),
        person_id: spec.person_id.map(str::to_string),
        timestamp: "2026-05-26 12:34:56.789000".to_string(),
        created_at: "2026-05-26 12:34:57.000000".to_string(),
        captured_at: None,
        elements_chain: Some("a:href".to_string()),
        person_created_at: None,
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        group0_properties: None,
        group1_properties: None,
        group2_properties: None,
        group3_properties: None,
        group4_properties: None,
        group0_created_at: None,
        group1_created_at: None,
        group2_created_at: None,
        group3_created_at: None,
        group4_created_at: None,
        person_mode: PersonMode::Full,
        historical_migration: None,
    }
}

/// Drains until `expected` envelopes arrive, then reads a short grace window to catch
/// over-forwarding, bounded by `deadline`.
async fn collect_output(
    bootstrap: &str,
    expected: usize,
    deadline: Duration,
) -> Vec<(i32, CohortStreamEvent)> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap)
        .set("group.id", "shuffler-itest-output-reader")
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .create()
        .expect("failed to create output reader");
    consumer
        .subscribe(&[OUTPUT_TOPIC])
        .expect("failed to subscribe to output topic");

    let mut collected = Vec::new();
    let start = Instant::now();
    let mut grace_until: Option<Instant> = None;

    while start.elapsed() < deadline {
        if let Some(grace) = grace_until {
            if Instant::now() >= grace {
                break;
            }
        }
        match tokio::time::timeout(Duration::from_millis(250), consumer.recv()).await {
            Ok(Ok(msg)) => {
                if let Some(payload) = msg.payload() {
                    let envelope: CohortStreamEvent = serde_json::from_slice(payload)
                        .expect("output payload must be an envelope");
                    collected.push((msg.partition(), envelope));
                    if collected.len() >= expected && grace_until.is_none() {
                        grace_until = Some(Instant::now() + Duration::from_secs(1));
                    }
                }
            }
            Ok(Err(err)) => panic!("output consumer error: {err}"),
            Err(_) => {}
        }
    }
    collected
}

#[tokio::test]
async fn shuffler_forwards_only_gated_events_with_stable_partitioning() {
    let (cluster, input_producer): (_, FutureProducer<_>) =
        common_kafka::test::create_mock_kafka().await;
    cluster
        .create_topic(INPUT_TOPIC, 1, 1)
        .expect("create input topic");
    cluster
        .create_topic(OUTPUT_TOPIC, OUTPUT_PARTITIONS, 1)
        .expect("create output topic");
    let bootstrap = cluster.bootstrap_servers();
    let config = test_config(&bootstrap);

    let team_index = Arc::new(TeamIndex::from_teams([2, 7])); // team 99 is absent (no realtime cohorts)

    let inputs = [
        InputSpec {
            team_id: 2,
            person_id: Some("pA"),
            event: "$pageview",
            forwardable: true,
        },
        InputSpec {
            team_id: 2,
            person_id: Some("pA"),
            event: "$click",
            forwardable: true,
        },
        InputSpec {
            team_id: 99,
            person_id: Some("pX"),
            event: "$pageview",
            forwardable: false,
        },
        InputSpec {
            team_id: 2,
            person_id: None,
            event: "$pageview",
            forwardable: false,
        },
        InputSpec {
            team_id: 7,
            person_id: Some("pB"),
            event: "$pageview",
            forwardable: true,
        },
        InputSpec {
            team_id: 2,
            person_id: Some("pA"),
            event: "$identify",
            forwardable: true,
        },
        InputSpec {
            team_id: 99,
            person_id: None,
            event: "$autocapture",
            forwardable: false,
        },
        InputSpec {
            team_id: 7,
            person_id: Some("pC"),
            event: "$pageview",
            forwardable: true,
        },
    ];

    let mut uuid_by_index = Vec::new();
    for (index, spec) in inputs.iter().enumerate() {
        let uuid = Uuid::from_u128(0xC0_0000 + index as u128);
        uuid_by_index.push(uuid);
        let payload = serde_json::to_string(&clickhouse_event(uuid, spec)).unwrap();
        let key = uuid.to_string();
        input_producer
            .send_result(FutureRecord::to(INPUT_TOPIC).key(&key).payload(&payload))
            .expect("enqueue input")
            .await
            .expect("input produce canceled")
            .expect("input produce failed");
    }

    let expected_forwardable: usize = inputs.iter().filter(|s| s.forwardable).count();

    let mut manager = Manager::builder("shuffler-itest")
        .with_trap_signals(false)
        .build();
    let handle = manager.register(
        "consumer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();

    let consumer =
        SingleTopicConsumer::new(config.build_kafka_config(), config.build_consumer_config())
            .expect("create shuffler consumer");
    let producer =
        CohortStreamProducer::new(&config.build_kafka_config(), OUTPUT_TOPIC.to_string())
            .await
            .expect("create shuffler producer");
    let shuffler = EventShuffler::new(
        consumer,
        producer,
        team_index,
        handle,
        config.recv_batch_size,
        config.recv_batch_timeout(),
    );
    tokio::spawn(async move { shuffler.process().await });

    // MockCluster group coordination can be slow to start; collect_output returns early once the
    // expected count arrives.
    let output = collect_output(&bootstrap, expected_forwardable, Duration::from_secs(40)).await;

    assert_eq!(
        output.len(),
        expected_forwardable,
        "expected {expected_forwardable} forwarded events, got {}",
        output.len(),
    );

    let forwardable_uuids: std::collections::HashSet<String> = inputs
        .iter()
        .enumerate()
        .filter(|(_, s)| s.forwardable)
        .map(|(i, _)| uuid_by_index[i].to_string())
        .collect();
    let output_uuids: std::collections::HashSet<String> =
        output.iter().map(|(_, e)| e.uuid.clone()).collect();
    assert_eq!(
        output_uuids, forwardable_uuids,
        "wrong set of forwarded events"
    );

    use std::collections::HashMap;
    let mut partitions_by_key: HashMap<(i32, String), std::collections::HashSet<i32>> =
        HashMap::new();
    for (partition, envelope) in &output {
        assert!(
            (0..OUTPUT_PARTITIONS).contains(partition),
            "partition {partition} out of range",
        );
        partitions_by_key
            .entry((envelope.team_id, envelope.person_id.clone()))
            .or_default()
            .insert(*partition);
    }
    let pa_partitions = &partitions_by_key[&(2, "pA".to_string())];
    assert_eq!(
        pa_partitions.len(),
        1,
        "events for (2, pA) split across partitions {pa_partitions:?}",
    );
    for ((team, person), partitions) in &partitions_by_key {
        assert_eq!(
            partitions.len(),
            1,
            "({team}, {person}) split across partitions {partitions:?}",
        );
    }

    let first = output
        .iter()
        .map(|(_, e)| e)
        .find(|e| e.uuid == uuid_by_index[0].to_string())
        .expect("first forwardable event must be present");
    assert_eq!(first.team_id, 2);
    assert_eq!(first.person_id, "pA");
    assert_eq!(first.event, "$pageview");
    assert_eq!(first.distinct_id, "did-pA");
    assert_eq!(
        first.properties.as_deref(),
        Some(r#"{"$current_url":"/pricing"}"#)
    );
    assert_eq!(first.source_partition, 0);
    assert_eq!(
        first.source_offset, 0,
        "first produced event has input offset 0"
    );
}
