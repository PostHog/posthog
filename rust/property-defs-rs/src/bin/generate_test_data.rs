use std::collections::HashMap;

use envconfig::Envconfig;
use property_defs_rs::{config::Config, types::Event};
use rdkafka::{
    producer::{FutureProducer, FutureRecord},
    ClientConfig,
};

fn generate_test_event(seed: usize) -> Event {
    let team_id = (seed % 100) as i32;
    let event_name = format!("test_event_{}", seed % 8);
    let prop_key = format!("prop_{}", seed % 1000);
    let properties: HashMap<String, String> =
        (0..100) // The average event has 100 properties
            .map(|i| (prop_key.clone(), format!("val_{}", i)))
            .collect();

    Event {
        team_id,
        event: event_name,
        properties: Some(serde_json::to_string(&properties).unwrap()),
    }
}

// A simple kafka producer that pushes a million events into a topic
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env()?;
    let kafka_config: ClientConfig = (&config.kafka).into();
    let producer: FutureProducer = kafka_config.create()?;
    let topic = config.kafka.event_topic.as_str();

    let mut acks = Vec::with_capacity(1_000_000);
    for i in 0..10_000_000 {
        let event = generate_test_event(i);
        let key = event.team_id.to_string();
        let payload = serde_json::to_string(&event)?;
        let record = FutureRecord {
            topic,
            key: Some(&key),
            payload: Some(&payload),
            partition: None,
            timestamp: None,
            headers: None,
        };
        let ack = producer.send_result(record).unwrap();
        acks.push(ack);

        if i % 1000 == 0 {
            println!("Sent {} events", i);
        }
    }

    let mut i = 0;
    for ack in acks {
        ack.await?.unwrap();
        i += 1;
        if i % 1000 == 0 {
            println!("Received ack for {} events", i);
        }
    }
    Ok(())
}
