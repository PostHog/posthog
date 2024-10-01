use std::{future::ready, sync::Arc};

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::RecvErr;
use common_metrics::{serve, setup_metrics_routes};
use common_types::{CapturedEvent, Team};
use envconfig::Envconfig;
use error_tracking::{app_context::AppContext, config::Config, error::Error};
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
        context.worker_liveness.report_healthy().await;
        let (event, offset): (CapturedEvent, _) = match context.consumer.json_recv().await {
            Ok(r) => r,
            Err(RecvErr::Kafka(e)) => {
                return Err(e.into()); // Just die if we recieve a Kafka error
            }
            Err(err) => {
                // If we failed to parse the message, or it was empty, just log and continue, our
                // consumer has already stored the offset for us.
                metrics::counter!("error_tracking_errors").increment(1);
                error!("Error receiving message: {:?}", err);
                continue;
            }
        };
        metrics::counter!("error_tracking_events_received").increment(1);

        // Team verification
        // If we encounter a sqlx error, just die. The by_token call explicitly
        // returns an Option<Team>, so any error here is a PG failure, and us falling
        // over sheds load.
        let token = &event.token;
        let pool = &context.pool;
        let team = context
            .team_cache
            .get_or_insert_with(token, async move { Ok(Team::by_token(pool, token).await?) })
            .await?;

        match team {
            Some(t) => t,
            None => {
                // If we failed to find the team, just store the offset and drop the event, we don't care about it
                offset.store().unwrap();
                warn!("Team not found for token: {}", event.token);
                metrics::counter!("error_tracking_team_not_found").increment(1);
                continue;
            }
        };

        // This is where the rest of the processing would go
        offset.store().unwrap();
    }
}
