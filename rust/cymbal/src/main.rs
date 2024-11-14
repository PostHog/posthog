use std::{future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    handle_event,
    metric_consts::{ERRORS, EVENT_RECEIVED, MAIN_LOOP_TIME, STACK_PROCESSED},
};
use envconfig::Envconfig;
use tokio::task::JoinHandle;
use tracing::{error, info};
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

    let config = Config::init_from_env().unwrap();
    let context = Arc::new(AppContext::new(&config).await.unwrap());

    start_health_liveness_server(&config, context.clone());

    loop {
        let whole_loop = common_metrics::timing_guard(MAIN_LOOP_TIME, &[]);
        context.worker_liveness.report_healthy().await;
        // Just grab the event as a serde_json::Value and immediately drop it,
        // we can work out a real type for it later (once we're deployed etc)
        let (event, offset): (ClickHouseEvent, _) = match context.kafka_consumer.json_recv().await {
            Ok(r) => r,
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

        let _processed_event = match handle_event(&context, event).await {
            Ok(r) => {
                offset.store().unwrap();
                r
            }
            Err(e) => {
                error!("Error handling event: {:?}", e);
                // If we get an unhandled error, it means we have some logical error in the code, or a
                // dependency is down, and we should just fall over.
                panic!("Unhandled error: {:?}", e);
            }
        };

        // TODO - emit the event to the next Kafka topic

        metrics::counter!(STACK_PROCESSED).increment(1);
        whole_loop.label("finished", "true").fin();
    }
}
