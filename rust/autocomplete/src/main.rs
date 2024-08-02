use std::{sync::Arc, time::{Duration, Instant}};

use autocomplete::{app_context::AppContext, config::Config, property_cache::handle_event, types::Event};
use envconfig::Envconfig;
use futures::future::join_all;
use rdkafka::{consumer::{Consumer, StreamConsumer}, ClientConfig, Message};
use tokio::{select, time::sleep};
use tracing::{debug, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>, EnvFilter, tracing_subscriber::Registry> = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry()
        .with(log_layer)
        .init();

}

// Right now, the true concurrency limit is the PG connection count, because we do one transaction
// per event - this is just the batch size of events we'll hold in memory before processing. I'd like
// to start breaking a 10_000 event batch into 10 or so transaction batches, but that's a future optimization,
// we should see how hard it is to keep up first.
const CONCURRENCY_LIMIT: usize = 100;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>>{
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env()?;

    let kafka_config: ClientConfig = (&config.kafka).into();

    let consumer: StreamConsumer = kafka_config.create()?;

    let context = Arc::new(AppContext::new(&config).await?);

    consumer.subscribe(&[config.kafka.event_topic.as_str()])?;

    info!("Subscribed to topic: {}", config.kafka.event_topic);

    let mut batch = Vec::with_capacity(CONCURRENCY_LIMIT);
    let mut handle_futs = Vec::with_capacity(CONCURRENCY_LIMIT);
    loop {

        while batch.len() < CONCURRENCY_LIMIT {
            // Try to grab from the consumer, but use a select! to timeout if we'd block for more than 10ms
            select! {
            res = consumer.recv() => {
                    batch.push(res);
                }
                _ = sleep(Duration::from_millis(10)) => {
                    break;
                }
            }
        }

        if batch.is_empty() {
            continue;
        }

        // Report batch size
        info!("Received batch of {} messages", batch.len());
        let start = Instant::now();

        for res in batch.drain(..) {
            match res {
                Ok(message) => {
                    let payload: Option<Result<&str, std::str::Utf8Error>> = message.payload_view::<str>();

                    // Since property definitions are idempotent, we're allowed to risk re-processing by not committing here, and letting
                    // autocommit handle it. If we move to batching, we can either continue to store and rely on autocommit, or switch to
                    // manual commits - we should make that decision based on performance testing.
                    // NOTE: we commit all messages seen, even if we fail to process them... the thinking here is that we don't want
                    // poison pills to block the whole event queue, but we should probably not commit if e.g. the DB is down. Error
                    // handling for later.
                    consumer.store_offset_from_message(&message)?;
    
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

                    let moved_context = context.clone();
                    let fut = tokio::spawn(async move {
                        if let Err(e) = handle_event(event, &moved_context).await {
                            warn!("Error handling event: {:?}", e);
                        }
                    });

                    handle_futs.push(fut);
    
                }
                Err(e) => {
                    warn!("Error receiving message: {:?}", e);
                }
            }

            join_all(handle_futs.drain(..)).await;

        }

        let elapsed = start.elapsed();
        info!("Batch processed in {}ms", elapsed.as_millis());
    }
}
