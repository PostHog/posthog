use std::{future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    error::Error,
    metric_consts::{ERRORS, EVENT_RECEIVED, MAIN_LOOP_TIME, PER_STACK_TIME, STACK_PROCESSED},
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
        let whole_loop = common_metrics::timing_guard(MAIN_LOOP_TIME, &[]);
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
                metrics::counter!(ERRORS, "cause" => "recv_err").increment(1);
                error!("Error receiving message: {:?}", err);
                continue;
            }
        };
        metrics::counter!(EVENT_RECEIVED).increment(1);

        offset.store().unwrap();

        if event.event != "$exception" {
            error!("event of type {}", event.event);
            continue;
        }

        let Some(properties) = &event.properties else {
            metrics::counter!(ERRORS, "cause" => "no_properties").increment(1);
            continue;
        };

        let properties: ErrProps = match serde_json::from_str(properties) {
            Ok(r) => r,
            Err(err) => {
                metrics::counter!(ERRORS, "cause" => "invalid_exception_properties").increment(1);
                error!("Error parsing properties: {:?}", err);
                continue;
            }
        };

        let Some(exception_list) = &properties.exception_list else {
            // Known issue that $exception_list didn't exist on old clients
            continue;
        };

        if exception_list.is_empty() {
            metrics::counter!(ERRORS, "cause" => "no_exception_list").increment(1);
            continue;
        }

        // TODO - we should resolve all traces
        let Some(trace) = exception_list[0].stacktrace.as_ref() else {
            metrics::counter!(ERRORS, "cause" => "no_stack_trace").increment(1);
            continue;
        };

        let stack_trace: &Vec<RawFrame> = &trace.frames;

        let per_stack = common_metrics::timing_guard(PER_STACK_TIME, &[]);
        let mut frames = Vec::with_capacity(stack_trace.len());
        for frame in stack_trace {
            match frame.resolve(event.team_id, &context.catalog).await {
                Ok(r) => frames.push(r),
                Err(err) => {
                    metrics::counter!(ERRORS, "cause" => "frame_not_parsable").increment(1);
                    error!("Error parsing stack frame: {:?}", err);
                    continue;
                }
            };
        }
        per_stack
            .label(
                "resolved_any",
                if frames.is_empty() { "true" } else { "false" },
            )
            .fin();
        whole_loop.label("had_frame", "true").fin();

        metrics::counter!(STACK_PROCESSED).increment(1);
    }
}
