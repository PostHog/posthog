use std::{collections::HashSet, sync::Arc, time::Duration};

use autocomplete::{
    app_context::AppContext,
    config::Config,
    metrics_consts::{BATCH_SKIPPED, EVENTS_RECEIVED, FORCED_SMALL_BATCH, SMALL_BATCH_SLEEP},
    types::{Event, Update},
};
use axum::{routing::get, Router};
use envconfig::Envconfig;
use futures::future::ready;
use rdkafka::{
    consumer::{Consumer, StreamConsumer},
    message::BorrowedMessage,
    ClientConfig, Message,
};
use serve_metrics::{serve, setup_metrics_routes};
use tokio::{select, task::JoinHandle, time::sleep};
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "property definitions service"
}

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.liveness.get_status())),
        );
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
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

    let mut sleep_count = 0;
    loop {
        context.worker_liveness.report_healthy().await;

        while batch.len() < config.max_batch_size {
            // Try to grab from the consumer, but use a select! to timeout if we'd block for more than some time
            select! {
                res = consumer.recv() => {
                    batch.push(res?); // Workers die on an kafka error
                }
                _ = sleep(Duration::from_millis(config.next_event_wait_timeout_ms)) => {
                    break;
                }
            }
        }

        // We only process batches over a certain threshold, unless we haven't received anything in a while, to reduce DB load
        if batch.len() < config.min_batch_size {
            sleep_count += 1;
            info!("Batch size is less than min_batch_size, sleeping for 2 seconds");
            metrics::counter!(BATCH_SKIPPED).increment(1);
            sleep(Duration::from_millis(2000)).await;
            if sleep_count > 10 {
                warn!("Slept too many times, continuing with a small batch");
                metrics::counter!(FORCED_SMALL_BATCH).increment(1);
            } else {
                metrics::counter!(SMALL_BATCH_SLEEP).increment(1);
                continue;
            }
        }
        sleep_count = 0;

        metrics::counter!(EVENTS_RECEIVED).increment(batch.len() as u64);

        let updates: HashSet<Update> = batch
            .drain(..)
            .filter_map(message_to_event)
            .flat_map(Event::into_updates)
            .filter_map(filter_cached)
            .collect();

        context.issue(updates).await?;
    }
}

// This copies event properties, which means the total resident memory usage is higher than we'd like, and that constrains
// our batch size. serde_json provides no zero-copy way to parse a JSON object, so we're stuck with this for now.
fn message_to_event(msg: BorrowedMessage) -> Option<Event> {
    let Some(payload) = msg.payload() else {
        warn!("Received empty event");
        metrics::counter!("empty_event").increment(1);
        return None;
    };

    let event = serde_json::from_slice::<Event>(payload);
    let event = match event {
        Ok(e) => e,
        Err(e) => {
            metrics::counter!("event_parse_error").increment(1);
            warn!("Failed to parse event: {:?}", e);
            return None;
        }
    };
    Some(event)
}

// TODO: this is where caching would go, if we had any. Could probably use a bloom filter or something,
// rather than storing the entire update in memory, if we wanted to store some HUGE number of updates and
// be /really/ good about not hitting the DB when we don't need to. Right now this is just a no-op.
fn filter_cached(update: Update) -> Option<Update> {
    Some(update)
}
