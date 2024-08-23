use axum::extract::connect_info::IntoMakeServiceWithConnectInfo;
use axum::Router;

use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;

use health::{ComponentStatus, HealthRegistry};
use time::Duration;
use tokio::net::TcpListener;

use crate::config::Config;

use crate::limiters::billing::BillingLimiter;
use crate::limiters::overflow::OverflowLimiter;
use crate::redis::RedisClient;
use crate::router;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::print::PrintSink;

pub async fn serve_app(config: Config) -> IntoMakeServiceWithConnectInfo<Router, SocketAddr> {
    let liveness = HealthRegistry::new("liveness");

    let redis_client =
        Arc::new(RedisClient::new(config.redis_url).expect("failed to create redis client"));

    let billing = BillingLimiter::new(
        Duration::seconds(5),
        redis_client.clone(),
        config.redis_key_prefix,
    )
    .expect("failed to create billing limiter");

    let app = if config.print_sink {
        // Print sink is only used for local debug, don't allow a container with it to run on prod
        liveness
            .register("print_sink".to_string(), Duration::seconds(30))
            .await
            .report_status(ComponentStatus::Unhealthy)
            .await;

        router::router(
            crate::time::SystemTime {},
            liveness,
            PrintSink {},
            redis_client,
            billing,
            config.export_prometheus,
            config.capture_mode,
        )
    } else {
        let sink_liveness = liveness
            .register("rdkafka".to_string(), Duration::seconds(30))
            .await;

        let partition = match config.overflow_enabled {
            false => None,
            true => {
                let partition = OverflowLimiter::new(
                    config.overflow_per_second_limit,
                    config.overflow_burst_limit,
                    config.overflow_forced_keys,
                );
                if config.export_prometheus {
                    let partition = partition.clone();
                    tokio::spawn(async move {
                        partition.report_metrics().await;
                    });
                }
                {
                    // Ensure that the rate limiter state does not grow unbounded
                    let partition = partition.clone();
                    tokio::spawn(async move {
                        partition.clean_state().await;
                    });
                }
                Some(partition)
            }
        };
        let sink = KafkaSink::new(config.kafka, sink_liveness, partition)
            .expect("failed to start Kafka sink");

        router::router(
            crate::time::SystemTime {},
            liveness,
            sink,
            redis_client,
            billing,
            config.export_prometheus,
            config.capture_mode,
        )
    };

    app.into_make_service_with_connect_info::<SocketAddr>()
}

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`
    let app = serve_app(config).await;

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown)
        .await
        .unwrap()
}
