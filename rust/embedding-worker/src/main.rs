use std::{collections::HashMap, future::ready, sync::Arc};

use axum::{
    extract::{Json, State},
    http::StatusCode,
    routing::get,
    Router,
};
use chrono::{DateTime, Utc};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::embedding::{EmbeddingRecord, EmbeddingRequest};
use embedding_worker::{
    ad_hoc::{handle_ad_hoc_request, AdHocEmbeddingRequest, AdHocEmbeddingResponse},
    app_context::AppContext,
    config::Config,
    handle_batch,
    metrics_utils::DROPPED_REQUESTS,
    recently_seen::{dedup_seen, DocumentKey, SeenRecord},
};

use metrics::counter;
use serde::{Deserialize, Serialize};
use tokio::task::JoinHandle;
use tracing::level_filters::LevelFilter;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};
use uuid::Uuid;

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("pyroscope=warn".parse().unwrap()),
    );
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
            error!("Ad hoc embedding request failed: {:?}", e);
            Err(StatusCode::INTERNAL_SERVER_ERROR)
        }
    }
}

/// Lookup request for the recently-seen store. `team_id` is the one shared dimension;
/// every other dimension varies per document, so each entry carries its full key.
#[derive(Deserialize)]
struct RecentlySeenRequest {
    team_id: i32,
    documents: Vec<DocumentKey>,
}

#[derive(Serialize)]
struct RecentlySeenResult {
    product: String,
    document_type: String,
    rendering: String,
    document_id: String,
    // RFC3339 emit time, or null if the document was never emitted (or has expired).
    emitted_at: Option<DateTime<Utc>>,
}

#[derive(Serialize)]
struct RecentlySeenResponse {
    results: Vec<RecentlySeenResult>,
}

fn recently_seen_results(
    documents: Vec<DocumentKey>,
    lookup: &HashMap<DocumentKey, Option<DateTime<Utc>>>,
) -> Vec<RecentlySeenResult> {
    documents
        .into_iter()
        .map(|key| RecentlySeenResult {
            emitted_at: lookup.get(&key).cloned().flatten(),
            product: key.product,
            document_type: key.document_type,
            rendering: key.rendering,
            document_id: key.document_id,
        })
        .collect()
}

async fn recently_seen_handler(
    State(context): State<Arc<AppContext>>,
    Json(request): Json<RecentlySeenRequest>,
) -> Json<RecentlySeenResponse> {
    let documents = request.documents;
    let lookup = context
        .recently_seen
        .lookup(request.team_id, documents.clone())
        .await;

    Json(RecentlySeenResponse {
        results: recently_seen_results(documents, &lookup),
    })
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
        .route("/recently_seen", axum::routing::post(recently_seen_handler))
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

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            error!("Failed to start continuous profiling agent: {e:?}");
            None
        }
    };

    common_posthog::init(
        "embedding-worker",
        config.posthog_api_key.as_deref(),
        &config.posthog_endpoint,
    )
    .await
    .unwrap();

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
                    counter!(DROPPED_REQUESTS, &[("cause", "recv_err")]).increment(1);
                    continue;
                }
            };
        }

        let responses = match handle_batch(to_process, &offsets, context.clone()).await {
            Ok(embeddings) => embeddings,
            Err(failure) => {
                error!("Error handling batch: {failure:?}");
                panic!("Unhandled error: {failure:?}");
            }
        };

        let txn = match transactional_producer.begin() {
            Ok(txn) => txn,
            Err(e) => {
                error!("Failed to start kafka transaction, {:?}", e);
                panic!("Failed to start kafka transaction: {e:?}");
            }
        };

        // Write the callback messages
        let emit_results = txn
            .send_keyed_iter_to_kafka(
                &context.config.response_topic,
                |_| Some(Uuid::now_v7().to_string()),
                &responses,
            )
            .await;

        for res in emit_results.into_iter() {
            res.expect("We can emit to kafka");
        }

        // Capture each document's emit time before `responses` is consumed.
        let mut emitted_at: HashMap<(i32, DocumentKey), DateTime<Utc>> = HashMap::new();
        for response in &responses {
            let req = &response.request;
            let key = DocumentKey {
                product: req.product.clone(),
                document_type: req.document_type.clone(),
                rendering: req.rendering.clone(),
                document_id: req.document_id.clone(),
            };
            emitted_at
                .entry((req.team_id, key))
                .or_insert(req.timestamp);
        }

        // Write the embedding records to CH
        let records: Vec<EmbeddingRecord> = responses
            .into_iter()
            .flat_map(Vec::<EmbeddingRecord>::from)
            .collect();

        let emit_results = txn
            .send_keyed_iter_to_kafka(
                &context.config.output_topic,
                |_| Some(Uuid::now_v7().to_string()),
                &records,
            )
            .await;

        for res in emit_results.into_iter() {
            res.expect("We can emit to kafka");
        }

        let metadata = context.kafka_consumer.metadata();

        // Associate the embedding request records with the offsets
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

        // Commit the transaction
        match txn.commit() {
            Ok(_) => {}
            Err(e) => {
                error!("Failed to commit kafka transaction, {:?}", e);
                panic!("Failed to commit kafka transaction, {e:?}");
            }
        }

        // Record the documents we just emitted in the recently-seen store, so callers can
        // cheaply check processing status. Best effort - better to write the same document
        // twice to CH (where it'll be de-duped anyway) than falsely advertise that we
        // processed it
        let seen = dedup_seen(records.iter().filter_map(|record| {
            let key = DocumentKey {
                product: record.product.clone(),
                document_type: record.document_type.clone(),
                rendering: record.rendering.clone(),
                document_id: record.document_id.clone(),
            };
            emitted_at
                .get(&(record.team_id, key.clone()))
                .map(|ts| SeenRecord {
                    team_id: record.team_id,
                    key,
                    emitted_at: *ts,
                })
        }));
        if !seen.is_empty() {
            context.recently_seen.record(&seen).await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn document(document_id: &str) -> DocumentKey {
        DocumentKey {
            product: "signals".to_string(),
            document_type: "signal".to_string(),
            rendering: "plain".to_string(),
            document_id: document_id.to_string(),
        }
    }

    #[test]
    fn recently_seen_results_preserve_request_order_and_duplicates() {
        let first = document("first");
        let second = document("second");
        let emitted_at = Utc::now();
        let lookup = HashMap::from([(first.clone(), Some(emitted_at)), (second.clone(), None)]);

        let results =
            recently_seen_results(vec![first.clone(), second.clone(), first.clone()], &lookup);

        assert_eq!(results.len(), 3);
        assert_eq!(results[0].document_id, first.document_id);
        assert_eq!(results[0].emitted_at, Some(emitted_at));
        assert_eq!(results[1].document_id, second.document_id);
        assert_eq!(results[1].emitted_at, None);
        assert_eq!(results[2].document_id, first.document_id);
        assert_eq!(results[2].emitted_at, Some(emitted_at));
    }
}
