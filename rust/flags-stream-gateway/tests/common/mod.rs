//! In-process integration harness (plan §2.12): the real `server::serve` path
//! with a [`MockRedisClient`] wired into both tiers and the team-metadata
//! reader, following the feature-flags `tests/common/mod.rs` pattern
//! (build-test-manager + spawn-serve + poll-readiness).
//!
//! [`SwappableRedis`] wraps the mock in a `Mutex` so a running test can flip an
//! etag mid-stream — the mock's `*_ret` maps are plain owned `HashMap`s, so
//! without the wrapper a mock handed to the server could never change again.

#![allow(dead_code)]

use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{
    Client, CustomRedisError, MockRedisClient, PipelineCommand, PipelineResult, RedisValueFormat,
};
use futures::StreamExt;
use lifecycle::Manager;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use flags_stream_gateway::config::Config;
use flags_stream_gateway::server;

/// The token/team pair most tests use.
pub const VALID_TOKEN: &str = "phc_valid_token";
pub const TEAM_ID: i32 = 123;
pub const ETAG_A: &str = "0123456789abcdef";
pub const ETAG_B: &str = "fedcba9876543210";

/// Pickle-frame a string the way Django's cache writes values, so the mock's
/// raw bytes decode through the real HyperCache read path.
pub fn pickled(s: &str) -> Vec<u8> {
    serde_pickle::to_vec(&s.to_string(), Default::default()).expect("pickle serializes")
}

/// The team-metadata cache key for a token (token-based layout).
pub fn team_metadata_key(token: &str) -> String {
    format!("posthog:1:cache/team_tokens/{token}/team_metadata/full_metadata.json")
}

/// The companion etag key the sweep reads for a team+value.
pub fn etag_key(team_id: i32, hypercache_value: &str) -> String {
    format!("posthog:1:cache/teams/{team_id}/feature_flags/{hypercache_value}:etag")
}

/// A mock that resolves `VALID_TOKEN` to `TEAM_ID`. Chain more setup onto it.
pub fn mock_with_valid_team() -> MockRedisClient {
    let team_json = format!(r#"{{"id":{TEAM_ID}}}"#);
    MockRedisClient::new()
        .get_raw_bytes_ret(&team_metadata_key(VALID_TOKEN), Ok(pickled(&team_json)))
}

/// A `common_redis::Client` whose inner [`MockRedisClient`] can be swapped while
/// the server holds it. Each call snapshots the current mock under the lock and
/// drops the guard before awaiting (no lock across await).
#[derive(Clone)]
pub struct SwappableRedis {
    inner: Arc<Mutex<MockRedisClient>>,
}

impl SwappableRedis {
    pub fn new(mock: MockRedisClient) -> Self {
        Self {
            inner: Arc::new(Mutex::new(mock)),
        }
    }

    /// Replace the inner mock — the next Redis call (e.g. the next sweep tick)
    /// sees the new state.
    pub fn swap(&self, mock: MockRedisClient) {
        *self.inner.lock().expect("mock lock") = mock;
    }

    fn snap(&self) -> MockRedisClient {
        self.inner.lock().expect("mock lock").clone()
    }
}

#[async_trait]
impl Client for SwappableRedis {
    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        self.snap().zrangebyscore(k, min, max).await
    }

    async fn zadd(&self, k: String, member: String, score: i64) -> Result<(), CustomRedisError> {
        self.snap().zadd(k, member, score).await
    }

    async fn hincrby(&self, k: String, v: String, count: i64) -> Result<(), CustomRedisError> {
        self.snap().hincrby(k, v, count).await
    }

    async fn get(&self, k: String) -> Result<String, CustomRedisError> {
        self.snap().get(k).await
    }

    async fn get_with_format(
        &self,
        k: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        self.snap().get_with_format(k, format).await
    }

    async fn get_raw_bytes(&self, k: String) -> Result<Vec<u8>, CustomRedisError> {
        self.snap().get_raw_bytes(k).await
    }

    async fn set_bytes(
        &self,
        k: String,
        v: Vec<u8>,
        ttl_seconds: Option<u64>,
    ) -> Result<(), CustomRedisError> {
        self.snap().set_bytes(k, v, ttl_seconds).await
    }

    async fn set(&self, k: String, v: String) -> Result<(), CustomRedisError> {
        self.snap().set(k, v).await
    }

    async fn set_with_format(
        &self,
        k: String,
        v: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        self.snap().set_with_format(k, v, format).await
    }

    async fn setex(&self, k: String, v: String, seconds: u64) -> Result<(), CustomRedisError> {
        self.snap().setex(k, v, seconds).await
    }

    async fn setex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        self.snap().setex_with_format(k, v, seconds, format).await
    }

    async fn set_nx_ex(
        &self,
        k: String,
        v: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        self.snap().set_nx_ex(k, v, seconds).await
    }

    async fn set_nx_ex_with_format(
        &self,
        k: String,
        v: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        self.snap()
            .set_nx_ex_with_format(k, v, seconds, format)
            .await
    }

    async fn batch_incr_by_expire_nx(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.snap()
            .batch_incr_by_expire_nx(items, ttl_seconds)
            .await
    }

    async fn batch_incr_by_expire(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.snap().batch_incr_by_expire(items, ttl_seconds).await
    }

    async fn del(&self, k: String) -> Result<(), CustomRedisError> {
        self.snap().del(k).await
    }

    async fn hget(&self, k: String, field: String) -> Result<String, CustomRedisError> {
        self.snap().hget(k, field).await
    }

    async fn scard(&self, k: String) -> Result<u64, CustomRedisError> {
        self.snap().scard(k).await
    }

    async fn mget(&self, keys: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        self.snap().mget(keys).await
    }

    async fn mget_with_format(
        &self,
        keys: Vec<String>,
        format: RedisValueFormat,
    ) -> Result<Vec<Option<String>>, CustomRedisError> {
        self.snap().mget_with_format(keys, format).await
    }

    async fn scard_multiple(&self, keys: Vec<String>) -> Result<Vec<u64>, CustomRedisError> {
        self.snap().scard_multiple(keys).await
    }

    async fn batch_sadd_expire(
        &self,
        items: Vec<(String, String)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.snap().batch_sadd_expire(items, ttl_seconds).await
    }

    async fn batch_set_nx_ex(
        &self,
        items: Vec<(String, String, usize)>,
    ) -> Result<Vec<bool>, CustomRedisError> {
        self.snap().batch_set_nx_ex(items).await
    }

    async fn batch_del(&self, keys: Vec<String>) -> Result<(), CustomRedisError> {
        self.snap().batch_del(keys).await
    }

    async fn execute_pipeline(
        &self,
        commands: Vec<PipelineCommand>,
    ) -> Result<Vec<Result<PipelineResult, CustomRedisError>>, CustomRedisError> {
        self.snap().execute_pipeline(commands).await
    }

    async fn publish(&self, channel: String, message: String) -> Result<(), CustomRedisError> {
        self.snap().publish(channel, message).await
    }
}

/// An in-process gateway with a swappable mock behind both Redis tiers.
pub struct TestServer {
    pub addr: std::net::SocketAddr,
    pub redis: SwappableRedis,
    shutdown: CancellationToken,
}

impl TestServer {
    /// Start the gateway on `127.0.0.1:0` with test-tuned defaults (sweep 50 ms,
    /// heartbeat 5 s, metrics off, hints off — no real network anywhere). `tweak`
    /// adjusts the raw config before validation.
    pub async fn start(mock: MockRedisClient, tweak: impl FnOnce(&mut Config)) -> TestServer {
        let mut raw = Config::default_test_config();
        raw.sweep_interval_ms = 50;
        // Long enough that silence-window assertions are never raced by a
        // heartbeat; the heartbeat test dials it down itself.
        raw.heartbeat_interval_secs = 5;
        raw.enable_metrics = false;
        raw.hints_enabled = false;
        tweak(&mut raw);
        let config = raw.validate().expect("valid test config");

        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let addr = listener.local_addr().expect("local addr");
        let shutdown = CancellationToken::new();
        let mut manager = Manager::builder("flags-stream-gateway-test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(shutdown.clone())
            .with_global_shutdown_timeout(Duration::from_secs(10))
            .build();
        let handles = server::register_components(&mut manager, &config);
        let monitor = manager.monitor_background();

        let redis = SwappableRedis::new(mock);
        let shared: Arc<dyn Client + Send + Sync> = Arc::new(redis.clone());
        let flags = shared.clone();
        tokio::spawn(async move {
            server::serve(config, shared, flags, listener, handles).await;
            // Drain the monitor so the supervisor exits cleanly; a failing
            // shutdown shouldn't fail the test unless asserted explicitly.
            if let Err(e) = monitor.wait().await {
                eprintln!("test lifecycle monitor reported: {e}");
            }
        });

        let server = TestServer {
            addr,
            redis,
            shutdown,
        };
        server.wait_until_ready().await;
        server
    }

    /// Trigger the pod-drain path (the external shutdown token IS the lifecycle
    /// root token, so streams and readiness react immediately).
    pub fn drain(&self) {
        self.shutdown.cancel();
    }

    pub async fn wait_until_ready(&self) {
        let client = reqwest::Client::new();
        let url = format!("http://{}/_readiness", self.addr);
        for _ in 0..100 {
            match client.get(&url).send().await {
                Ok(resp) if resp.status().is_success() => return,
                _ => tokio::time::sleep(Duration::from_millis(50)).await,
            }
        }
        panic!("server failed to become ready within 5 seconds");
    }

    /// Open a `/stream/v1` connection; returns the raw response (status +
    /// headers), unconsumed.
    pub async fn connect(&self, kind: &str, token: &str) -> reqwest::Response {
        reqwest::Client::new()
            .get(format!(
                "http://{}/stream/v1?token={token}&kind={kind}",
                self.addr
            ))
            .send()
            .await
            .expect("request sends")
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.shutdown.cancel();
    }
}

/// Incremental SSE frame reader over `reqwest`'s byte stream, with explicit
/// timeouts — never an unbounded read.
pub struct SseFrames {
    stream:
        std::pin::Pin<Box<dyn futures::Stream<Item = Result<bytes::Bytes, reqwest::Error>> + Send>>,
    buf: String,
}

impl SseFrames {
    pub fn new(response: reqwest::Response) -> Self {
        Self {
            stream: Box::pin(response.bytes_stream()),
            buf: String::new(),
        }
    }

    /// The next SSE frame (a block terminated by a blank line), or `None` on
    /// stream end (clean EOF or transport close). Panics on timeout.
    pub async fn next_frame(&mut self, timeout: Duration) -> Option<String> {
        tokio::time::timeout(timeout, self.next_frame_inner())
            .await
            .expect("timed out waiting for an SSE frame")
    }

    /// Read frames until one satisfies `predicate` (bounded by `timeout` per
    /// read), panicking on EOF. Used when heartbeats may interleave.
    pub async fn frame_matching(
        &mut self,
        timeout: Duration,
        predicate: impl Fn(&str) -> bool,
    ) -> String {
        loop {
            let frame = self
                .next_frame(timeout)
                .await
                .expect("stream ended while waiting for a matching frame");
            if predicate(&frame) {
                return frame;
            }
        }
    }

    /// Assert no frame arrives within `window`.
    pub async fn expect_silence(&mut self, window: Duration) {
        match tokio::time::timeout(window, self.next_frame_inner()).await {
            Ok(Some(frame)) => panic!("expected silence, got frame: {frame:?}"),
            Ok(None) => panic!("stream ended during expected silence"),
            Err(_) => {} // timed out — silent, as expected
        }
    }

    async fn next_frame_inner(&mut self) -> Option<String> {
        loop {
            if let Some(idx) = self.buf.find("\n\n") {
                let frame: String = self.buf.drain(..idx + 2).collect();
                let frame = frame.trim_end().to_string();
                if frame.trim().is_empty() {
                    continue;
                }
                return Some(frame);
            }
            match self.stream.next().await {
                Some(Ok(bytes)) => self.buf.push_str(&String::from_utf8_lossy(&bytes)),
                Some(Err(_)) | None => return None,
            }
        }
    }
}
