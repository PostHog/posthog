#[path = "common/utils.rs"]
mod utils;
use utils::*;

use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::Result;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::DefaultProducerContext;
use rdkafka::{ClientConfig, Message, Offset, TopicPartitionList};
use reqwest::StatusCode;
use serde_json::json;

use capture::config::Config;
use capture::fallback::{ARMING_VALUE, FALLBACK_BROKERS_VAR};
use capture::v1::test_utils::{batch_payload, valid_event};

const TOKEN: &str = "phc_fallback_test_token";
const FALLBACK_EVENTS_TOPIC: &str = "fallback_events";
const DEAD_PRIMARY_BROKERS: &str = "127.0.0.1:1";

fn fallback_cluster(missing: Option<&str>) -> MockCluster<'static, DefaultProducerContext> {
    let cluster = MockCluster::new(1).expect("mock cluster");
    let outputs = &DEFAULT_CONFIG.outputs;
    let topics = [
        FALLBACK_EVENTS_TOPIC,
        &outputs.analytics_overflow_topic,
        &outputs.analytics_historical_topic,
        &outputs.heatmaps_topic,
        &outputs.client_warnings_topic,
        &outputs.error_tracking_topic,
        &outputs.dlq_topic,
        &outputs.ai_main_topic,
        &outputs.ai_overflow_topic,
    ];
    let topics: std::collections::BTreeSet<&str> = topics.into_iter().collect();
    for topic in topics {
        if missing != Some(topic) {
            cluster.create_topic(topic, 1, 1).expect("create topic");
        }
    }
    cluster
}

fn fallback_env(
    primary_brokers: &str,
    fallback: &MockCluster<'static, DefaultProducerContext>,
) -> HashMap<String, String> {
    [
        (
            "KAFKA_INGESTION_PRODUCER_METADATA_BROKER_LIST",
            primary_brokers.to_string(),
        ),
        (FALLBACK_BROKERS_VAR, fallback.bootstrap_servers()),
        ("KAFKA_FALLBACK_PRODUCER_LINGER_MS", "0".to_string()),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect()
}

fn fallback_config() -> Config {
    let mut config = DEFAULT_CONFIG.clone();
    config.fallback_outputs.analytics_main_topic = Some(FALLBACK_EVENTS_TOPIC.to_string());
    config
}

fn read_events(brokers: &str, topic: &str, count: usize) -> Vec<serde_json::Value> {
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .set("group.id", random_string("fallback_it", 8))
        .set("enable.auto.commit", "false")
        .create()
        .expect("consumer");
    let mut assignment = TopicPartitionList::new();
    assignment
        .add_partition_offset(topic, 0, Offset::Beginning)
        .expect("assignment");
    consumer.assign(&assignment).expect("assign");

    let deadline = Instant::now() + Duration::from_secs(15);
    let mut events = Vec::new();
    while events.len() < count && Instant::now() < deadline {
        if let Some(Ok(message)) = consumer.poll(Duration::from_millis(200)) {
            let payload = message.payload().expect("payload");
            events.push(serde_json::from_slice(payload).expect("json payload"));
        }
    }
    events
}

fn v0_event(distinct_id: &str) -> String {
    json!({
        "token": TOKEN,
        "event": "fallback_event",
        "distinct_id": distinct_id,
        "properties": {}
    })
    .to_string()
}

#[tokio::test]
async fn armed_v0_and_v1_events_land_on_the_fallback_cluster() -> Result<()> {
    setup_tracing();
    let fallback = fallback_cluster(None);
    let mut config = fallback_config();
    config.kafka_emergency_fallback = Some(ARMING_VALUE.to_string());
    let server = ServerHandle::for_config_with_sink_env(
        config,
        fallback_env(DEAD_PRIMARY_BROKERS, &fallback),
    )
    .await;

    let res = server.capture_to_batch(v0_event("v0-user")).await;
    assert_eq!(res.status(), StatusCode::OK);
    let mut v1_event = valid_event();
    v1_event.distinct_id = "v1-user".to_string();
    let res = server
        .capture_v1(TOKEN, batch_payload(std::slice::from_ref(&v1_event)))
        .await;
    assert_eq!(res.status(), StatusCode::OK);

    let events = read_events(&fallback.bootstrap_servers(), FALLBACK_EVENTS_TOPIC, 2);
    let distinct_ids: Vec<&str> = events
        .iter()
        .map(|event| event["distinct_id"].as_str().unwrap())
        .collect();
    assert_eq!(distinct_ids, vec!["v0-user", "v1-user"]);
    Ok(())
}

#[tokio::test]
#[should_panic(
    expected = "fallback target failed its topic check: topic \"events_plugin_ingestion_dlq\""
)]
async fn armed_with_a_missing_fallback_topic_refuses_boot() {
    setup_tracing();
    let fallback = fallback_cluster(Some(&DEFAULT_CONFIG.outputs.dlq_topic));
    let mut config = fallback_config();
    config.kafka_emergency_fallback = Some(ARMING_VALUE.to_string());

    ServerHandle::for_config_with_sink_env(config, fallback_env(TEST_KAFKA_HOSTS, &fallback)).await;
}

#[tokio::test]
#[should_panic(
    expected = "fallback target failed its topic check: topic \"events_plugin_ingestion_dlq\""
)]
async fn strict_refuses_boot_on_a_missing_idle_fallback_topic() {
    setup_tracing();
    let fallback = fallback_cluster(Some(&DEFAULT_CONFIG.outputs.dlq_topic));
    let mut config = fallback_config();
    config.kafka_emergency_fallback_check = Some("strict".to_string());

    ServerHandle::for_config_with_sink_env(config, fallback_env(TEST_KAFKA_HOSTS, &fallback)).await;
}

#[tokio::test]
async fn unarmed_events_stay_on_the_primary_despite_a_broken_idle_fallback() -> Result<()> {
    setup_tracing();
    let main = EphemeralTopic::new().await;
    let historical = EphemeralTopic::new().await;
    let fallback = fallback_cluster(Some(FALLBACK_EVENTS_TOPIC));
    let mut config = fallback_config();
    config.outputs.analytics_main_topic = main.topic_name().to_string();
    config.outputs.analytics_historical_topic = historical.topic_name().to_string();
    let server =
        ServerHandle::for_config_with_sink_env(config, fallback_env(TEST_KAFKA_HOSTS, &fallback))
            .await;

    let res = server.capture_to_batch(v0_event("primary-user")).await;
    assert_eq!(res.status(), StatusCode::OK);

    assert_eq!(main.next_event()?["distinct_id"], "primary-user");
    Ok(())
}
