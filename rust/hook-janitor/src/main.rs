use axum::Router;
use cleanup::{Cleaner, CleanerModeName};
use config::Config;
use envconfig::Envconfig;
use eyre::Result;
use futures::future::{select, Either};
use health::{HealthHandle, HealthRegistry};
use kafka_producer::create_kafka_producer;
use std::{str::FromStr, time::Duration};
use tokio::sync::Semaphore;
use webhooks::WebhookCleaner;

use hook_common::metrics::setup_metrics_routes;

mod cleanup;
mod config;
mod handlers;
mod kafka_producer;
mod webhooks;

async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

async fn cleanup_loop(cleaner: Box<dyn Cleaner>, interval_secs: u64, liveness: HealthHandle) {
    let semaphore = Semaphore::new(1);
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));

    loop {
        let _permit = semaphore.acquire().await;
        interval.tick().await;
        liveness.report_healthy().await;
        cleaner.cleanup().await;
        drop(_permit);
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("failed to load configuration from env");

    let mode_name = CleanerModeName::from_str(&config.mode)
        .unwrap_or_else(|_| panic!("invalid cleaner mode: {}", config.mode));

    let liveness = HealthRegistry::new("liveness");

    let cleaner = match mode_name {
        CleanerModeName::Webhooks => {
            let kafka_liveness = liveness
                .register("rdkafka".to_string(), time::Duration::seconds(30))
                .await;
            let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness)
                .await
                .expect("failed to create kafka producer");

            Box::new(
                WebhookCleaner::new(
                    &config.database_url,
                    kafka_producer,
                    config.kafka.app_metrics_topic.to_owned(),
                )
                .expect("unable to create webhook cleaner"),
            )
        }
    };

    let cleanup_liveness = liveness
        .register(
            "cleanup_loop".to_string(),
            time::Duration::seconds(config.cleanup_interval_secs as i64 * 2),
        )
        .await;
    let cleanup_loop = Box::pin(cleanup_loop(
        cleaner,
        config.cleanup_interval_secs,
        cleanup_liveness,
    ));

    let app = setup_metrics_routes(handlers::app(liveness));
    let http_server = Box::pin(listen(app, config.bind()));

    match select(http_server, cleanup_loop).await {
        Either::Left((listen_result, _)) => match listen_result {
            Ok(_) => {}
            Err(e) => tracing::error!("failed to start hook-janitor http server, {}", e),
        },
        Either::Right((_, _)) => {
            tracing::error!("hook-janitor cleanup task exited")
        }
    };
}
