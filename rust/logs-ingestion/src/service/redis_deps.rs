//! Redis: a connection that reconnects after a failure, as ioredis does, and `QuotaLimiting`.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use futures::FutureExt;
use redis::aio::{ConnectionLike, MultiplexedConnection};
use redis::{
    AsyncConnectionConfig, Client, Cmd, ConnectionAddr, ConnectionInfo, Pipeline, RedisFuture,
    Value,
};
use tokio::sync::Mutex;

use crate::pipeline::QuotaLimiting;
use crate::rate_limiter::Clock;

use super::config::RedisTarget;
use super::lazy_loader::{LazyLoader, LazyLoaderOptions};

/// The ioredis reading of a connection setting: a `scheme://` URL, or a bare host. The port,
/// password and TLS options win over the URL, as ioredis merges its options last.
pub fn connection_info(target: &RedisTarget) -> anyhow::Result<ConnectionInfo> {
    use redis::IntoConnectionInfo;
    let url = if target.url_or_host.contains("://") {
        target.url_or_host.clone()
    } else {
        format!("redis://{}", target.url_or_host)
    };
    let mut info = url.as_str().into_connection_info()?;
    let (host, port) = match &info.addr {
        ConnectionAddr::Tcp(h, p)
        | ConnectionAddr::TcpTls {
            host: h, port: p, ..
        } => (h.clone(), *p),
        other => anyhow::bail!("unsupported Redis address {other:?}"),
    };
    let port = target.port.unwrap_or(port);
    let tls = target.tls || matches!(info.addr, ConnectionAddr::TcpTls { .. });
    info.addr = if tls {
        ConnectionAddr::TcpTls {
            host,
            port,
            insecure: false,
            tls_params: None,
        }
    } else {
        ConnectionAddr::Tcp(host, port)
    };
    if let Some(password) = &target.password {
        info.redis.password = Some(password.clone());
    }
    Ok(info)
}

/// A multiplexed connection that is rebuilt on the next call after an I/O failure.
#[derive(Clone)]
pub struct ReconnectingRedis {
    client: Client,
    conn: Arc<Mutex<Option<MultiplexedConnection>>>,
}

impl ReconnectingRedis {
    pub fn new(info: ConnectionInfo) -> anyhow::Result<Self> {
        Ok(Self {
            client: Client::open(info)?,
            conn: Arc::new(Mutex::new(None)),
        })
    }

    async fn connection(&self) -> redis::RedisResult<MultiplexedConnection> {
        let mut guard = self.conn.lock().await;
        if let Some(c) = guard.as_ref() {
            return Ok(c.clone());
        }
        let config = AsyncConnectionConfig::new()
            .set_connection_timeout(Duration::from_secs(5))
            .set_response_timeout(Duration::from_secs(5));
        let c = self
            .client
            .get_multiplexed_async_connection_with_config(&config)
            .await?;
        *guard = Some(c.clone());
        Ok(c)
    }

    async fn on_error(&self, error: &redis::RedisError) {
        if error.is_io_error()
            || error.is_connection_dropped()
            || error.is_timeout()
            || error.is_unrecoverable_error()
        {
            *self.conn.lock().await = None;
        }
    }
}

impl ConnectionLike for ReconnectingRedis {
    fn req_packed_command<'a>(&'a mut self, cmd: &'a Cmd) -> RedisFuture<'a, Value> {
        async move {
            let mut c = self.connection().await?;
            let result = c.req_packed_command(cmd).await;
            if let Err(e) = &result {
                self.on_error(e).await;
            }
            result
        }
        .boxed()
    }

    fn req_packed_commands<'a>(
        &'a mut self,
        cmd: &'a Pipeline,
        offset: usize,
        count: usize,
    ) -> RedisFuture<'a, Vec<Value>> {
        async move {
            let mut c = self.connection().await?;
            let result = c.req_packed_commands(cmd, offset, count).await;
            if let Err(e) = &result {
                self.on_error(e).await;
            }
            result
        }
        .boxed()
    }

    fn get_db(&self) -> i64 {
        0
    }
}

pub const QUOTA_LIMITER_CACHE_KEY: &str = "@posthog/quota-limits/";

/// `QuotaLimiting`: the limited tokens of a resource from `ZRANGEBYSCORE`, cached for an hour and
/// refreshed in the background after a minute. A Redis error reads as no limited tokens. It
/// only ever reads.
pub struct RedisQuotaLimiting {
    // Shared, so a cache hit clones a pointer instead of every limited token.
    loader: LazyLoader<Arc<HashMap<String, f64>>>,
    clock: Clock,
}

impl RedisQuotaLimiting {
    pub fn new(redis: ReconnectingRedis, clock: Clock) -> Self {
        let mut options = LazyLoaderOptions::new("quota_limited_tokens", Duration::from_secs(3600));
        options.background_age = Some(Duration::from_secs(60));
        let load_clock = clock.clone();
        let loader = LazyLoader::new(
            options,
            Arc::new(move |resources: Vec<String>| {
                let mut redis = redis.clone();
                let clock = load_clock.clone();
                async move {
                    let now_seconds = clock() / 1000.0;
                    let mut out = HashMap::new();
                    for resource in resources {
                        let key = format!("{QUOTA_LIMITER_CACHE_KEY}{resource}");
                        let reply: redis::RedisResult<Vec<(String, String)>> = redis::cmd("ZRANGEBYSCORE")
                            .arg(&key)
                            .arg(crate::js::number_to_string(now_seconds))
                            .arg("+inf")
                            .arg("WITHSCORES")
                            .query_async(&mut redis)
                            .await;
                        let tokens = match reply {
                            Ok(pairs) => pairs
                                .into_iter()
                                .filter(|(token, score)| !token.is_empty() && !score.is_empty())
                                .map(|(token, score)| {
                                    let ms = (crate::metric_rules::js_parse_float(
                                        &crate::js::JsString::from(score),
                                    ) * 1000.0)
                                        .floor();
                                    (token, ms)
                                })
                                .collect(),
                            Err(error) => {
                                tracing::error!(resource, error = %error, "[QuotaLimiting] Error loading limited tokens from Redis");
                                HashMap::new()
                            }
                        };
                        out.insert(resource, Some(Arc::new(tokens)));
                    }
                    Ok(out)
                }
                .boxed()
            }),
        );
        Self { loader, clock }
    }
}

#[async_trait]
impl QuotaLimiting for RedisQuotaLimiting {
    async fn is_team_token_quota_limited(
        &self,
        token: &str,
        resource: &str,
    ) -> anyhow::Result<bool> {
        let now = (self.clock)();
        let limited = self.loader.get(resource).await?;
        Ok(limited
            .and_then(|m| m.get(token).copied())
            .is_some_and(|until| until != 0.0 && !until.is_nan() && until > now))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redis_targets_read_like_ioredis() {
        let info = connection_info(&RedisTarget {
            url_or_host: "logs-redis.internal".into(),
            port: Some(6380),
            password: None,
            tls: true,
        })
        .unwrap();
        assert!(
            matches!(info.addr, ConnectionAddr::TcpTls { ref host, port: 6380, .. } if host == "logs-redis.internal")
        );
        let info = connection_info(&RedisTarget {
            url_or_host: "redis://127.0.0.1".into(),
            port: None,
            password: Some("pw".into()),
            tls: false,
        })
        .unwrap();
        assert!(matches!(info.addr, ConnectionAddr::Tcp(_, 6379)));
        assert_eq!(info.redis.password.as_deref(), Some("pw"));
    }
}
