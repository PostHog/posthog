//! Test-only scaffolding shared across the crate.

use std::sync::Arc;
use std::time::Duration;

use common_redis::{CompressionConfig, RedisClient, RedisValueFormat};
use testcontainers::core::{IntoContainerPort, WaitFor};
use testcontainers::runners::AsyncRunner;
use testcontainers::{ContainerAsync, GenericImage};

/// A running Redis container. Callers keep it alive for the test's duration.
pub type RedisContainer = ContainerAsync<GenericImage>;

/// Boot a throwaway Redis and return a connected client. The readiness banner
/// can land a hair before the socket accepts, so both the connect and a probe
/// script are retried, otherwise the first command occasionally races the
/// container and flakes with "connection refused".
///
/// Hold on to the returned container: dropping it stops Redis.
pub async fn start_redis() -> (Arc<RedisClient>, RedisContainer) {
    let container = GenericImage::new("redis", "7-alpine")
        .with_exposed_port(6379.tcp())
        .with_wait_for(WaitFor::message_on_stdout("Ready to accept connections"))
        .start()
        .await
        .unwrap();
    let host = container.get_host().await.unwrap();
    let port = container.get_host_port_ipv4(6379).await.unwrap();
    let url = format!("redis://{host}:{port}");

    for _ in 0..20 {
        if let Ok(client) = RedisClient::with_config(
            url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            None,
            None,
        )
        .await
        {
            if client
                .eval_int_vec("return { 1 }", vec![], vec![])
                .await
                .is_ok()
            {
                return (Arc::new(client), container);
            }
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    panic!("redis container never became ready");
}
