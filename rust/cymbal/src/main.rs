use std::{collections::HashMap, future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::ClickHouseEvent;
use cymbal::{
    app_context::AppContext,
    config::Config,
    error::Error,
    fingerprinting,
    metric_consts::{ERRORS, EVENT_RECEIVED, MAIN_LOOP_TIME, STACK_PROCESSED},
    types::{ErrProps, Stacktrace},
};
use envconfig::Envconfig;
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
        let (event, offset): (ClickHouseEvent, _) = match context.kafka_consumer.json_recv().await {
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
            warn!("event of type {}", event.event);
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
                error!(
                    "Error parsing properties: {:?} from properties {:?}",
                    err, properties
                );
                continue;
            }
        };

        let Some(mut exception_list) = properties.exception_list else {
            // Known issue that $exception_list didn't exist on old clients
            metrics::counter!(ERRORS, "cause" => "no_exception_list").increment(1);
            continue;
        };

        if exception_list.is_empty() {
            metrics::counter!(ERRORS, "cause" => "no_exception_list").increment(1);
            continue;
        }

        for exception in exception_list.iter_mut() {
            let stack = std::mem::take(&mut exception.stack);
            let Some(Stacktrace::Raw { frames }) = stack else {
                continue;
            };

            if frames.is_empty() {
                metrics::counter!(ERRORS, "cause" => "no_frames").increment(1);
                continue;
            }

            let team_id = event.team_id;
            let mut results = Vec::with_capacity(frames.len());

            // Cluster the frames by symbol set
            let mut groups = HashMap::new();
            for (i, frame) in frames.into_iter().enumerate() {
                let group = groups
                    .entry(frame.symbol_set_ref())
                    .or_insert_with(Vec::new);
                group.push((i, frame.clone()));
            }

            for (_, frames) in groups.into_iter() {
                context.worker_liveness.report_healthy().await; // TODO - we shouldn't need to do this, but we do for now.
                for (i, frame) in frames {
                    let resolved_frame = context
                        .resolver
                        .resolve(&frame, team_id, &context.pool, &context.catalog)
                        .await?;
                    results.push((i, resolved_frame));
                }
            }

            results.sort_unstable_by_key(|(i, _)| *i);

            exception.stack = Some(Stacktrace::Resolved {
                frames: results.into_iter().map(|(_, frame)| frame).collect(),
            });
        }

        let _fingerprint = fingerprinting::generate_fingerprint(&exception_list);

        metrics::counter!(STACK_PROCESSED).increment(1);
        whole_loop.label("finished", "true").fin();
    }
}
