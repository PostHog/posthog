use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;

use health::{ComponentStatus, HealthRegistry};
use time::Duration;
use tokio::net::TcpListener;

use crate::config::CaptureMode;
use crate::config::Config;

use crate::limiters::overflow::OverflowLimiter;
use crate::limiters::redis::{
    QuotaResource, RedisLimiter, OVERFLOW_LIMITER_CACHE_KEY, QUOTA_LIMITER_CACHE_KEY,
};
use crate::redis::RedisClient;
use crate::router;
use crate::router::BATCH_BODY_SIZE;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::print::PrintSink;

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    let liveness = HealthRegistry::new("liveness");

    let redis_client =
        Arc::new(RedisClient::new(config.redis_url).expect("failed to create redis client"));

    let replay_overflow_limiter = match config.capture_mode {
        CaptureMode::Recordings => Some(
            RedisLimiter::new(
                Duration::seconds(5),
                redis_client.clone(),
                OVERFLOW_LIMITER_CACHE_KEY.to_string(),
                config.redis_key_prefix.clone(),
                QuotaResource::Replay,
            )
            .expect("failed to start replay overflow limiter"),
        ),
        _ => None,
    };

    let billing_limiter = RedisLimiter::new(
        Duration::seconds(5),
        redis_client.clone(),
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        config.redis_key_prefix,
        match config.capture_mode {
            CaptureMode::Events => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        },
    )
    .expect("failed to create billing limiter");

    // In Recordings capture mode, we unpack a batch of events, and then pack them back up into
    // a big blob and send to kafka all at once - so we should abort unpacking a batch if the data
    // size crosses the kafka limit. In the Events mode, we can unpack the batch and send each
    // event individually, so we should instead allow for some small multiple of our max compressed
    // body size to be unpacked. If a single event is still too big, we'll drop it at kafka send time.
    let event_max_bytes = match config.capture_mode {
        CaptureMode::Events => BATCH_BODY_SIZE * 5, // To allow for some compression ratio, but still have a limit of 100MB.
        CaptureMode::Recordings => config.kafka.kafka_producer_message_max_bytes as usize,
    };

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
            billing_limiter,
            config.export_prometheus,
            config.capture_mode,
            config.concurrency_limit,
            event_max_bytes,
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
        let sink = KafkaSink::new(
            config.kafka,
            sink_liveness,
            partition,
            replay_overflow_limiter,
        )
        .expect("failed to start Kafka sink");

        router::router(
            crate::time::SystemTime {},
            liveness,
            sink,
            redis_client,
            billing_limiter,
            config.export_prometheus,
            config.capture_mode,
            config.concurrency_limit,
            event_max_bytes,
        )
    };

    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`
    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .unwrap()
}
