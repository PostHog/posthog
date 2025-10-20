use std::sync::Arc;

use common_kafka::{
    config::KafkaConfig,
    kafka_producer::{create_kafka_producer, send_iter_to_kafka},
};
use common_types::ClickHouseEvent;

use cymbal::pipeline::exception::get_props;
use envconfig::Envconfig;
use health::HealthRegistry;

const EXCEPTION_DATA: &str = include_str!("../../tests/static/raw_ch_exception_list.json");

#[tokio::main]
async fn main() {
    let config = KafkaConfig::init_from_env().unwrap();
    let health = Arc::new(HealthRegistry::new("test"));
    let handle = health
        .register("rdkafka".to_string(), std::time::Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&config, handle).await.unwrap();

    let exception: ClickHouseEvent = serde_json::from_str(EXCEPTION_DATA).unwrap();
    let exceptions = (0..10000).map(|_| exception.clone()).collect::<Vec<_>>();
    get_props(&exception).unwrap();

    loop {
        println!("Sending {} exception kafka", exceptions.len());
        send_iter_to_kafka(&producer, "exceptions_ingestion", &exceptions)
            .await
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}
