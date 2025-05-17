use common_kafka::kafka_producer::{send_keyed_iter_to_kafka, KafkaContext};
use common_types::{ClickHouseEvent, PersonMode};
use rdkafka::producer::FutureProducer;
use serde::Serialize;
use uuid::Uuid;

pub fn create_clickhouse_event<T: Serialize>(
    team_id: i32,
    event: String,
    distinct_id: String,
    properties: Option<T>,
) -> ClickHouseEvent {
    let timestamp = chrono::Utc::now()
        .format("%Y-%m-%d %H:%M:%S%.3f")
        .to_string();

    ClickHouseEvent {
        uuid: Uuid::now_v7(),
        team_id,
        project_id: None,
        event,
        distinct_id,
        properties: serde_json::to_string(&properties).ok(),
        person_id: None,
        created_at: timestamp.clone(),
        timestamp,
        elements_chain: None,
        person_created_at: None,
        person_properties: None,
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
        person_mode: PersonMode::Propertyless,
    }
}

pub async fn publish_event(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    event: ClickHouseEvent,
) {
    send_keyed_iter_to_kafka(producer, topic, |ev| Some(ev.uuid.to_string()), [event]).await;
}
