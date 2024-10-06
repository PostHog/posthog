use std::{future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    error::Error,
    types::{frames::RawFrame, ErrProps},
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
async fn main() -> Result<(), Error> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env()?;
    let context = Arc::new(AppContext::new(&config).await?);

    start_health_liveness_server(&config, context.clone());

    loop {
        context.worker_liveness.report_healthy().await;
        // Just grab the event as a serde_json::Value and immediately drop it,
        // we can work out a real type for it later (once we're deployed etc)
        let (event, offset): (ClickHouseEvent, _) = match context.consumer.json_recv().await {
            Ok(r) => r,
            Err(RecvErr::Kafka(e)) => {
                return Err(e.into()); // Just die if we recieve a Kafka error
            }
            Err(err) => {
                // If we failed to parse the message, or it was empty, just log and continue, our
                // consumer has already stored the offset for us.
                metrics::counter!("cymbal_errors", "cause" => "recv_err").increment(1);
                error!("Error receiving message: {:?}", err);
                continue;
            }
        };
        metrics::counter!("cymbal_events_received").increment(1);

        offset.store().unwrap();

        if event.event != "$exception" {
            error!("event of type {}", event.event);
            continue;
        }

        let Some(properties) = &event.properties else {
            metrics::counter!("cymbal_errors", "cause" => "no_properties").increment(1);
            continue;
        };

        let properties: ErrProps = match serde_json::from_str(properties) {
            Ok(r) => r,
            Err(err) => {
                metrics::counter!("cymbal_errors", "cause" => "invalid_exception_properties")
                    .increment(1);
                error!("Error parsing properties: {:?}", err);
                continue;
            }
        };

        let Some(trace) = properties.exception_stack_trace_raw.as_ref() else {
            metrics::counter!("cymbal_errors", "cause" => "no_stack_trace").increment(1);
            continue;
        };

        let _stack_trace: Vec<RawFrame> = match serde_json::from_str(trace) {
            Ok(r) => r,
            Err(err) => {
                metrics::counter!("cymbal_errors", "cause" => "invalid_stack_trace").increment(1);
                error!("Error parsing stack trace: {:?}", err);
                continue;
            }
        };

        metrics::counter!("cymbal_stack_track_processed").increment(1);
    }
}
