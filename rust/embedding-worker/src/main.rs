use std::{future::ready, sync::Arc};

use axum::{
    extract::{Json, State},
    http::StatusCode,
    routing::get,
    Router,
};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::embedding::EmbeddingRequest;
use embedding_worker::{
    ad_hoc::{handle_ad_hoc_request, AdHocEmbeddingRequest, AdHocEmbeddingResponse},
    app_context::AppContext,
    config::Config,
    handle_batch,
};

use tokio::task::JoinHandle;
use tracing::{error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};
use uuid::Uuid;

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
    "error tracking embedding service"
}

async fn ad_hoc_handler(
    State(context): State<Arc<AppContext>>,
    Json(request): Json<AdHocEmbeddingRequest>,
) -> Result<Json<AdHocEmbeddingResponse>, StatusCode> {
    match handle_ad_hoc_request(context, request).await {
        Ok(response) => Ok(Json(response)),
        Err(e) => {
            // TODO - this is a hack until I do a proper pass and add real error enums
            error!("Ad hoc embedding request failed: {}", e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let liveness_context = context.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(liveness_context.health_registry.get_status())),
        )
        .route("/generate/ad_hoc", axum::routing::post(ad_hoc_handler))
        .with_state(context);
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

    let context = Arc::new(AppContext::new(config.clone()).await.unwrap());

    start_health_liveness_server(&config, context.clone());

    let batch_wait_time = std::time::Duration::from_secs(config.max_event_batch_wait_seconds);
    let batch_size = config.max_events_per_batch;

    loop {
        context.worker_liveness.report_healthy().await;
        // Just grab the event as a serde_json::Value and immediately drop it,
        // we can work out a real type for it later (once we're deployed etc)
        let received: Vec<Result<(EmbeddingRequest, _), _>> = context
            .kafka_consumer
            .json_recv_batch(batch_size, batch_wait_time)
            .await;

        let mut transactional_producer = context.transactional_producer.lock().await;

        let mut to_process = Vec::with_capacity(received.len());
        let mut offsets = Vec::with_capacity(received.len());

        for message in received {
            match message {
                Ok((event, offset)) => {
                    to_process.push(event);
                    offsets.push(offset);
                }
                Err(RecvErr::Kafka(e)) => {
                    panic!("Kafka error: {e}")
                }
                Err(err) => {
                    // If we failed to parse the message, or it was empty, just log and continue, our
                    // consumer has already stored the offset for us.
                    error!("Error receiving message: {:?}", err);
                    continue;
                }
            };
        }

        let embeddings = match handle_batch(to_process, &offsets, context.clone()).await {
            Ok(embeddings) => embeddings,
            Err(failure) => {
                error!("Error handling batch: {failure}");
                panic!("Unhandled error: {failure}");
            }
        };

        let txn = match transactional_producer.begin() {
            Ok(txn) => txn,
            Err(e) => {
                error!("Failed to start kafka transaction, {:?}", e);
                panic!("Failed to start kafka transaction: {e:?}");
            }
        };

        let results = txn
            .send_keyed_iter_to_kafka(
                &context.config.output_topic,
                |_| Some(Uuid::now_v7().to_string()),
                embeddings,
            )
            .await;

        for result in results.into_iter() {
            result.expect("We can emit to kafka");
        }

        let metadata = context.kafka_consumer.metadata();

        match txn.associate_offsets(offsets, &metadata) {
            Ok(_) => {}
            Err(e) => {
                error!(
                    "Failed to associate offsets with kafka transaction, {:?}",
                    e
                );
                panic!("Failed to associate offsets with kafka transaction, {e:?}");
            }
        }

        match txn.commit() {
            Ok(_) => {}
            Err(e) => {
                error!("Failed to commit kafka transaction, {:?}", e);
                panic!("Failed to commit kafka transaction, {e:?}");
            }
        }
    }
}
