use std::{sync::Arc, time::{Duration, Instant}};

use autocomplete::{app_context::AppContext, config::Config, property_cache::handle_event_batch, types::Event};
use axum::{routing::get, Router};
use envconfig::Envconfig;
use futures::future::{join_all, ready};
use serve_metrics::{serve, setup_metrics_routes};
use rdkafka::{consumer::{Consumer, StreamConsumer}, ClientConfig, Message};
use tokio::{select, task::JoinHandle, time::sleep};
use tracing::{debug, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>, EnvFilter, tracing_subscriber::Registry> = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry()
        .with(log_layer)
        .init();

}

pub async fn index() -> &'static str {
    "property definitions service"
}

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(context.liveness.get_status())));
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

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

    start_health_liveness_server(&config, context.clone());

    let mut batch = Vec::with_capacity(config.max_batch_size);
    let mut last_receive = Instant::now();
    loop {
        batch.clear();
        context.worker_liveness.report_healthy().await;

        metrics::gauge!("time_since_last_receive").set(last_receive.elapsed().as_secs_f64());
        while batch.len() < config.max_batch_size {
            // Try to grab from the consumer, but use a select! to timeout if we'd block for more than some time
            select! {
            res = consumer.recv() => {
                    batch.push(res);
                }
                _ = sleep(Duration::from_millis(config.next_event_wait_timeout_ms)) => {
                    break;
                }
            }
        }

        if batch.is_empty() {
            continue;
        }

        metrics::counter!("event_batch_recieved").increment(batch.len() as u64);
        let chunks = batch.chunks(config.max_batch_size / config.max_concurrent_transactions);

        let mut handle_futs = Vec::with_capacity(config.max_concurrent_transactions);

        for chunk in chunks {
            let mut events = vec![];
            for res in chunk {
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
                            metrics::counter!("event_no_payload").increment(1);
                            continue;
                        };

                        let Ok(payload) = payload else {
                            warn!("Payload not UTF8 compatible: {:?}", message);
                            metrics::counter!("event_payload_not_utf8").increment(1);
                            continue;
                        };
                        let Ok(event) = serde_json::from_str::<Event>(payload) else {
                            warn!("Error deserializing event: {:?}", payload);
                            metrics::counter!("event_deserialization_error").increment(1);
                            continue;
                        };

                        debug!("Received event: {:?}", event);

                        events.push(event);
            
                    }
                    Err(e) => {
                        metrics::counter!("event_receive_error").increment(1);
                        warn!("Error receiving message: {:?}", e);
                    }
                }
            }

            let moved_context = context.clone();
            let fut = tokio::spawn(async move {
                if let Err(e) = handle_event_batch(events, &moved_context).await {
                    warn!("Error handling event batch: {:?}", e);
                }
            });
            handle_futs.push(fut);
        }

        info!("Waiting for {} transaction batches to complete", handle_futs.len());
        join_all(handle_futs).await;

        last_receive = Instant::now();
    }
}
