use std::{future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::{kafka_consumer::RecvErr, kafka_producer::KafkaProduceError};
use common_metrics::{serve, setup_metrics_routes};
use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    handle_events,
    metric_consts::{DROPPED_EVENTS, ERRORS, EVENT_PROCESSED, EVENT_RECEIVED, MAIN_LOOP_TIME},
};
use rdkafka::types::RDKafkaErrorCode;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "error tracking service"
}

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.health_registry.get_status())),
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
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();

    match &config.posthog_api_key {
        Some(key) => {
            let ph_config = posthog_rs::ClientOptionsBuilder::default()
                .api_key(key.clone())
                .api_endpoint(config.posthog_endpoint.clone())
                .build()
                .unwrap();
            posthog_rs::init_global(ph_config).await.unwrap();
            info!("Posthog client initialized");
        }
        None => {
            posthog_rs::disable_global();
            warn!("Posthog client disabled");
        }
    }

    let context = Arc::new(AppContext::new(&config).await.unwrap());

    start_health_liveness_server(&config, context.clone());

    let batch_wait_time = std::time::Duration::from_secs(config.max_event_batch_wait_seconds);
    let batch_size = config.max_events_per_batch;

    loop {
        let whole_loop = common_metrics::timing_guard(MAIN_LOOP_TIME, &[]);
        context.worker_liveness.report_healthy().await;
        // Just grab the event as a serde_json::Value and immediately drop it,
        // we can work out a real type for it later (once we're deployed etc)
        let received: Vec<Result<(ClickHouseEvent, _), _>> = context
            .kafka_consumer
            .json_recv_batch(batch_size, batch_wait_time)
            .await;

        let mut transactional_producer = context.transactional_producer.lock().await;

        let txn = match transactional_producer.begin() {
            Ok(txn) => txn,
            Err(e) => {
                error!("Failed to start kafka transaction, {:?}", e);
                panic!("Failed to start kafka transaction: {:?}", e);
            }
        };

        let mut to_process = Vec::with_capacity(received.len());
        let mut offsets = Vec::with_capacity(received.len());

        for message in received {
            match message {
                Ok((event, offset)) => {
                    to_process.push(event);
                    offsets.push(offset);
                }
                Err(RecvErr::Kafka(e)) => {
                    panic!("Kafka error: {}", e)
                }
                Err(err) => {
                    // If we failed to parse the message, or it was empty, just log and continue, our
                    // consumer has already stored the offset for us.
                    metrics::counter!(ERRORS, "cause" => "recv_err").increment(1);
                    error!("Error receiving message: {:?}", err);
                    continue;
                }
            };
            metrics::counter!(EVENT_RECEIVED).increment(1);
        }

        let processed = match handle_events(context.clone(), to_process).await {
            Ok(events) => events,
            Err((index, e)) => {
                let offset = &offsets[index];
                error!("Error handling event: {:?}; offset: {:?}", e, offset);
                panic!("Unhandled error: {:?}; offset: {:?}", e, offset);
            }
        };

        metrics::counter!(EVENT_PROCESSED).increment(processed.len() as u64);

        let results = txn
            .send_keyed_iter_to_kafka(
                &context.config.events_topic,
                |ev| Some(ev.uuid.to_string()),
                &processed,
            )
            .await;

        for (result, offset) in results.into_iter().zip(offsets.iter()) {
            match result {
                Ok(_) => {}
                Err(KafkaProduceError::KafkaProduceError { error })
                    if matches!(
                        error.rdkafka_error_code(),
                        Some(RDKafkaErrorCode::MessageSizeTooLarge)
                    ) =>
                {
                    // If we got a message too large error, just commit the offset anyway and drop the exception, there's
                    // nothing else we can do.
                    error!(
                        "Dropping exception at offset {:?} due to {:?}",
                        offset, error
                    );
                    metrics::counter!(DROPPED_EVENTS, "cause" => "message_too_large").increment(1);
                }
                Err(e) => {
                    error!(
                        "Failed to send event to kafka: {:?}, related to offset {:?}",
                        e, offset
                    );
                    panic!(
                        "Failed to send event to kafka: {:?}, related to offset {:?}",
                        e, offset
                    );
                }
            }
        }

        let metadata = context.kafka_consumer.metadata();

        // TODO - probably being over-explicit with the error handling here, and could instead
        // let main return an error and use the question mark operator, but it's good
        // to be explicit about places we drop things at the top level, so
        match txn.associate_offsets(offsets, &metadata) {
            Ok(_) => {}
            Err(e) => {
                error!(
                    "Failed to associate offsets with kafka transaction, {:?}",
                    e
                );
                panic!(
                    "Failed to associate offsets with kafka transaction, {:?}",
                    e
                );
            }
        }

        match txn.commit() {
            Ok(_) => {}
            Err(e) => {
                error!("Failed to commit kafka transaction, {:?}", e);
                panic!("Failed to commit kafka transaction, {:?}", e);
            }
        }

        whole_loop.label("finished", "true").fin();
    }
}
