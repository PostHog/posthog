//! End-to-end tests for the emergency Kafka fallback switch.
//!
//! These boot the real server through `config_resolution::resolve`, so they
//! exercise the whole chain an outage would: env snapshot -> resolution ->
//! sink construction -> HTTP -> real Kafka.
//!
//! Each test points the primary and backup clusters at opposite ends, one live
//! and one dead. An event only reaches its topic if the switch resolved the way
//! the test says it should, so a fallback that failed to apply (or applied when
//! dormant) produces into a black hole and the consumer times out.
//!
//! Requires Docker Kafka (same rig as the other integration tests).

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use common_types::CapturedEvent;
use serde_json::json;
use uuid::Uuid;

use capture::config_resolution::{HOSTS_VAR, TRIGGER_VALUE, TRIGGER_VAR};
use capture::v1::analytics::types::Event;
use capture::v1::test_utils::{batch_payload, valid_event};

const TOKEN: &str = "phc_emergency_fallback_token";

/// A broker address nothing listens on. Reserved as "discard" by RFC 6335, so
/// it cannot collide with a service someone runs locally.
const DEAD_HOSTS: &str = "127.0.0.1:9";

fn pageview(distinct_id: &str) -> Event {
    let mut e = valid_event();
    e.uuid = Uuid::new_v4().to_string();
    e.distinct_id = distinct_id.to_string();
    e
}

/// Boots capture with the v0 and v1 lanes both configured, `primary_hosts` as
/// the cluster every producer is configured with, and the backup cluster set
/// to the real broker. `armed` decides which one the events should reach.
async fn server_with(
    primary_hosts: &str,
    backup_hosts: &str,
    armed: bool,
    v0_topic: &EphemeralTopic,
    v1_topic: &EphemeralTopic,
) -> ServerHandle {
    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = v0_topic.topic_name().to_string();
    config.kafka.kafka_hosts = primary_hosts.to_string();
    config.capture_v1_sinks = "msk".to_string();

    let mut sink_env = v1_sink_env_for_topic("msk", v1_topic.topic_name());
    sink_env.insert(
        "CAPTURE_V1_SINK_MSK_KAFKA_HOSTS".to_string(),
        primary_hosts.to_string(),
    );
    sink_env.insert(HOSTS_VAR.to_string(), backup_hosts.to_string());
    if armed {
        sink_env.insert(TRIGGER_VAR.to_string(), TRIGGER_VALUE.to_string());
    }

    ServerHandle::for_config_with_sink_env(config, sink_env).await
}

/// The outage case: every producer is configured with a cluster that is gone,
/// and only the fallback can get an event to a broker. Covers both lanes,
/// because the v0 sink and the v1 sinks are parsed from separate env
/// namespaces and could regress independently.
#[tokio::test]
async fn armed_fallback_produces_to_the_backup_cluster() -> Result<()> {
    setup_tracing();
    let v0_topic = EphemeralTopic::new().await;
    let v1_topic = EphemeralTopic::new().await;
    let real_broker = DEFAULT_CONFIG.kafka.kafka_hosts.clone();

    let server = server_with(DEAD_HOSTS, &real_broker, true, &v0_topic, &v1_topic).await;

    let distinct_id = random_string("v0", 12);
    let res = server
        .capture_events(
            json!([{ "token": TOKEN, "event": "$pageview", "distinct_id": distinct_id }])
                .to_string(),
        )
        .await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let event = v0_topic.next_event()?;
    assert_eq!(event["distinct_id"], distinct_id);
    assert_eq!(event["token"], TOKEN);

    let v1_event = pageview("v1-armed-user");
    let res = server
        .capture_v1(TOKEN, batch_payload(std::slice::from_ref(&v1_event)))
        .await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let captured: CapturedEvent = serde_json::from_value(v1_topic.next_event()?)?;
    assert_eq!(captured.distinct_id, "v1-armed-user");

    Ok(())
}

/// The steady state every deployment sits in: the backup settings are present
/// but the trigger is not, so nothing is repointed. The backup here is the dead
/// address, so an over-eager fallback loses the events instead of hiding behind
/// a broker that happens to work.
#[tokio::test]
async fn dormant_fallback_leaves_traffic_on_the_primary_cluster() -> Result<()> {
    setup_tracing();
    let v0_topic = EphemeralTopic::new().await;
    let v1_topic = EphemeralTopic::new().await;
    let real_broker = DEFAULT_CONFIG.kafka.kafka_hosts.clone();

    let server = server_with(&real_broker, DEAD_HOSTS, false, &v0_topic, &v1_topic).await;

    let distinct_id = random_string("v0", 12);
    let res = server
        .capture_events(
            json!([{ "token": TOKEN, "event": "$pageview", "distinct_id": distinct_id }])
                .to_string(),
        )
        .await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let event = v0_topic.next_event()?;
    assert_eq!(event["distinct_id"], distinct_id);

    let v1_event = pageview("v1-dormant-user");
    let res = server
        .capture_v1(TOKEN, batch_payload(std::slice::from_ref(&v1_event)))
        .await;
    assert_eq!(res.status(), reqwest::StatusCode::OK);

    let captured: CapturedEvent = serde_json::from_value(v1_topic.next_event()?)?;
    assert_eq!(captured.distinct_id, "v1-dormant-user");

    Ok(())
}
