use std::env;

use autocomplete::{cache::PropertyCacheManager, config::Config, types::Event};
use envconfig::Envconfig;
use rdkafka::{consumer::{Consumer, StreamConsumer}, ClientConfig, Message};
use tracing::{debug, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry()
        .with(log_layer)
        .init();

}


#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>>{
    // Default to debug logging
    env::set_var("RUST_LOG", "debug");
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env()?;

    let kafka_config: ClientConfig = (&config.kafka).into();

    let consumer: StreamConsumer = kafka_config.create()?;

    let cache = PropertyCacheManager::new(&config).await?;

    consumer.subscribe(&[config.kafka.event_topic.as_str()])?;

    info!("Subscribed to topic: {}", config.kafka.event_topic);

    loop {
        match consumer.recv().await {
            Ok(message) => {
                let payload = message.payload_view::<str>();


                let Some(payload) = payload else {
                    warn!("No payload recieved in message: {:?}", message);
                    continue;
                };
                let Ok(payload) = payload else {
                    warn!("Payload not UTF8 compatible: {:?}", message);
                    continue;
                };
                let Ok(event) = serde_json::from_str::<Event>(payload) else {
                    warn!("Error deserializing event: {:?}", payload);
                    continue;
                };

                debug!("Received event: {:?}", event);

                if let Err(e) = cache.handle_event(event).await {
                    warn!("Error handling event: {:?}", e);
                }

            }
            Err(e) => {
                warn!("Error receiving message: {:?}", e);
            }
        }
    }
}
