//! Test-only scaffolding shared across the crate.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{
    CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat, ScriptRunner,
};
use testcontainers::core::{IntoContainerPort, WaitFor};
use testcontainers::runners::AsyncRunner;
use testcontainers::{ContainerAsync, GenericImage};

/// Dropping this stops the container, so tests hold it for their duration.
pub type RedisContainer = ContainerAsync<GenericImage>;

/// Boot a throwaway Redis and return a connected client. The readiness banner can
/// land just before the socket accepts, so the connect and a probe script are
/// retried, otherwise the first command flakes with "connection refused".
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

/// A [`ScriptRunner`] that never touches Redis: a canned reply, or an error.
pub struct FakeRunner {
    reply: Option<Vec<i64>>,
}

impl FakeRunner {
    pub fn returning(reply: Vec<i64>) -> Arc<Self> {
        Arc::new(Self { reply: Some(reply) })
    }

    pub fn failing() -> Arc<Self> {
        Arc::new(Self { reply: None })
    }
}

#[async_trait]
impl ScriptRunner for FakeRunner {
    async fn eval_int_vec(
        &self,
        _script: &str,
        _keys: Vec<String>,
        _args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError> {
        self.reply.clone().ok_or(CustomRedisError::Timeout)
    }
}
