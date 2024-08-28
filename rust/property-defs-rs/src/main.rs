use std::{sync::Arc, time::Duration};

use axum::{routing::get, Router};
use envconfig::Envconfig;
use futures::future::ready;
use property_defs_rs::{
    app_context::AppContext,
    config::Config,
    metrics_consts::{
        BATCH_ACQUIRE_TIME, CACHE_CONSUMED, EMPTY_EVENTS, EVENTS_RECEIVED, EVENT_PARSE_ERROR,
        FORCED_SMALL_BATCH, PERMIT_WAIT_TIME, RECV_DEQUEUED, TRANSACTION_LIMIT_SATURATION,
        UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT, UPDATES_SEEN, UPDATE_ISSUE_TIME,
        WORKER_BLOCKED,
    },
    types::{Event, Update},
};
use quick_cache::sync::Cache;
use rdkafka::{
    consumer::{Consumer, StreamConsumer},
    message::BorrowedMessage,
    ClientConfig, Message,
};
use serve_metrics::{serve, setup_metrics_routes};
use tokio::{
    sync::{
        mpsc::{self, error::TrySendError},
        Semaphore,
    },
    task::JoinHandle,
};
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

async fn spawn_producer_loop(
    consumer: Arc<StreamConsumer>,
    channel: mpsc::Sender<Update>,
    cache: Arc<Cache<Update, ()>>,
) {
    loop {
        let message = consumer
            .recv()
            .await
            .expect("TODO - workers panic on kafka recv fail");

        let Some(event) = message_to_event(message) else {
            continue;
        };

        let updates = event.into_updates();

        metrics::counter!(EVENTS_RECEIVED).increment(1);
        metrics::counter!(UPDATES_SEEN).increment(updates.len() as u64);
        metrics::histogram!(UPDATES_PER_EVENT).record(updates.len() as f64);

        for update in updates {
            if cache.get(&update).is_some() {
                metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                continue;
            }
            cache.insert(update.clone(), ());
            // We first try to non-blocking send, so we can get a metric on backpressure
            match channel.try_send(update) {
                Ok(_) => continue,
                Err(TrySendError::Full(u)) => {
                    metrics::counter!(WORKER_BLOCKED).increment(1);
                    channel
                        .send(u)
                        .await
                        .expect("TODO - workers panic on send fail");
                }
                Err(TrySendError::Closed(_)) => {
                    warn!("Channel closed, shutting down worker");
                    return;
                }
            };
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env()?;

    let kafka_config: ClientConfig = (&config.kafka).into();

    let consumer: Arc<StreamConsumer> = Arc::new(kafka_config.create()?);

    let context = Arc::new(AppContext::new(&config).await?);

    consumer.subscribe(&[config.kafka.event_topic.as_str()])?;

    info!("Subscribed to topic: {}", config.kafka.event_topic);

    start_health_liveness_server(&config, context.clone());

    let (tx, mut rx) = mpsc::channel(config.update_batch_size * config.channel_slots_per_worker);
    let transaction_limit = Arc::new(Semaphore::new(config.max_concurrent_transactions));
    let cache = Arc::new(Cache::new(config.cache_capacity));

    for _ in 0..config.worker_loop_count {
        tokio::spawn(spawn_producer_loop(
            consumer.clone(),
            tx.clone(),
            cache.clone(),
        ));
    }

    loop {
        let mut batch = Vec::with_capacity(config.update_batch_size);

        let batch_start = tokio::time::Instant::now();
        let batch_time = common_metrics::timing_guard(BATCH_ACQUIRE_TIME, &[]);
        while batch.len() < config.update_batch_size {
            context.worker_liveness.report_healthy().await;

            let remaining_capacity = config.update_batch_size - batch.len();
            // We race these two, so we can escape this loop and do a small batch if we've been waiting too long
            let recv = rx.recv_many(&mut batch, remaining_capacity);
            let sleep = tokio::time::sleep(Duration::from_secs(1));

            tokio::select! {
                got = recv => {
                    if got == 0 {
                        warn!("Coordinator recv failed, dying");
                        return Ok(());
                    }
                    metrics::gauge!(RECV_DEQUEUED).set(got as f64);
                    continue;
                }
                _ = sleep => {
                    if batch_start.elapsed() > Duration::from_secs(config.max_issue_period) {
                        warn!("Forcing small batch due to time limit");
                        metrics::counter!(FORCED_SMALL_BATCH).increment(1);
                        break;
                    }
                }
            }
        }
        batch_time.fin();

        metrics::gauge!(CACHE_CONSUMED).set(cache.len() as f64);

        metrics::gauge!(TRANSACTION_LIMIT_SATURATION).set(
            (config.max_concurrent_transactions - transaction_limit.available_permits()) as f64,
        );

        // We unconditionally wait to acquire a transaction permit - this is our backpressure mechanism. If we
        // fail to acquire a permit for long enough, we will fail liveness checks (but that implies our ongoing
        // transactions are halted, at which point DB health is a concern).
        let permit_acquire_time = common_metrics::timing_guard(PERMIT_WAIT_TIME, &[]);
        let permit = transaction_limit.clone().acquire_owned().await.unwrap();
        permit_acquire_time.fin();

        let context = context.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let issue_time = common_metrics::timing_guard(UPDATE_ISSUE_TIME, &[]);
            context.issue(batch).await.unwrap();
            issue_time.fin();
        });
    }
}

// This copies event properties, which means the total resident memory usage is higher than we'd like, and that constrains
// our batch size. serde_json provides no zero-copy way to parse a JSON object, so we're stuck with this for now.
fn message_to_event(msg: BorrowedMessage) -> Option<Event> {
    let Some(payload) = msg.payload() else {
        warn!("Received empty event");
        metrics::counter!(EMPTY_EVENTS).increment(1);
        return None;
    };

    let event = serde_json::from_slice::<Event>(payload);
    let event = match event {
        Ok(e) => e,
        Err(e) => {
            metrics::counter!(EVENT_PARSE_ERROR).increment(1);
            warn!("Failed to parse event: {:?}", e);
            return None;
        }
    };
    Some(event)
}

pub fn retain_from<T>(buffer: &mut Vec<T>, from: usize, predicate: impl Fn(&T) -> bool) {
    let mut i = from;
    while i < buffer.len() {
        if !predicate(&buffer[i]) {
            buffer.swap_remove(i);
        } else {
            i += 1;
        }
    }
}
