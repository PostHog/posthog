#[path = "common/utils.rs"]
mod utils;
use utils::*;

use std::collections::HashMap;

use anyhow::Result;
use rdkafka::mocking::MockCluster;
use rdkafka::producer::DefaultProducerContext;
use reqwest::StatusCode;
use serde_json::json;

use capture::config::Config;
use capture::fallback::FALLBACK_BROKERS_VAR;

const TOKEN: &str = "phc_fallback_test_token";
const FALLBACK_EVENTS_TOPIC: &str = "fallback_events";

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
    config.secondary_outputs.analytics_main_topic = Some(FALLBACK_EVENTS_TOPIC.to_string());
    config
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
#[should_panic(expected = "fallback target failed its topic check: output DLQ")]
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
