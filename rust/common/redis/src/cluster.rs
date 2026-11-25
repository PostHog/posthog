use std::collections::BTreeSet;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use arc_swap::ArcSwapOption;
use async_trait::async_trait;
use redis::cluster::{ClusterClient, ClusterClientBuilder};
use redis::cluster_async::ClusterConnection;
use redis::AsyncCommands;
use tracing::{info, warn};

use crate::pipeline::{PipelineCommand, PipelineResult};
use crate::{Client, CustomRedisError, RedisValueFormat};

/// Time after a failed connect attempt or a dropped connection before the next attempt.
const CONNECT_COOLDOWN: Duration = Duration::from_secs(5);
/// The cluster connection heals a lost node by itself, but a hung node sends no MOVED and a
/// fully down cluster makes every read retry every node. Rebuild it after this many failures.
const FAILURES_BEFORE_RECONNECT: u32 = 3;

/// A read client for a cluster-protocol cache such as ElastiCache Serverless.
///
/// It builds no connection in `new`, so a cache that is down at startup cannot fail or
/// block the caller. The first read connects; once connected, the cluster connection
/// reconnects and refreshes its slots on its own. Only sorted-set range reads are
/// supported; every other `Client` method returns `InvalidConfiguration`.
#[derive(Clone)]
pub struct RedisClusterClient {
    inner: Arc<Inner>,
}

struct Inner {
    client: ClusterClient,
    connection: ArcSwapOption<ClusterConnection>,
    /// Also serializes connect attempts, so concurrent first reads start one connect.
    cooldown_started_at: tokio::sync::Mutex<Option<Instant>>,
    connect_cooldown: Duration,
    connect_budget: Duration,
    consecutive_failures: AtomicU32,
}

impl RedisClusterClient {
    pub fn new(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
        read_from_replicas: bool,
    ) -> Result<Self, CustomRedisError> {
        Self::with_connect_cooldown(
            url,
            response_timeout,
            connection_timeout,
            read_from_replicas,
            CONNECT_COOLDOWN,
        )
    }

    fn with_connect_cooldown(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
        read_from_replicas: bool,
        connect_cooldown: Duration,
    ) -> Result<Self, CustomRedisError> {
        if response_timeout.is_zero() || connection_timeout.is_zero() {
            return Err(CustomRedisError::InvalidConfiguration(
                "cluster client timeouts must be greater than zero".to_string(),
            ));
        }
        let mut builder = ClusterClientBuilder::new([url])
            .response_timeout(response_timeout)
            .connection_timeout(connection_timeout)
            .retries(1);
        if read_from_replicas {
            builder = builder.read_from_replicas();
        }
        let client = builder.build()?;
        Ok(Self {
            inner: Arc::new(Inner {
                client,
                connection: ArcSwapOption::empty(),
                cooldown_started_at: tokio::sync::Mutex::new(None),
                connect_cooldown,
                // Seed connect, PING or READONLY, CLUSTER SLOTS, then the per-node connects.
                connect_budget: connection_timeout * 2 + response_timeout * 3,
                consecutive_failures: AtomicU32::new(0),
            }),
        })
    }

    async fn connection(&self) -> Result<ClusterConnection, CustomRedisError> {
        if let Some(connection) = self.inner.connection.load_full() {
            return Ok(ClusterConnection::clone(&connection));
        }
        let mut cooldown_started_at = self.inner.cooldown_started_at.lock().await;
        if let Some(connection) = self.inner.connection.load_full() {
            return Ok(ClusterConnection::clone(&connection));
        }
        if cooldown_started_at
            .is_some_and(|started| started.elapsed() < self.inner.connect_cooldown)
        {
            return Err(not_connected());
        }
        let attempt = match tokio::time::timeout(
            self.inner.connect_budget,
            self.inner.client.get_async_connection(),
        )
        .await
        {
            Ok(attempt) => attempt.map_err(CustomRedisError::from),
            Err(_) => Err(CustomRedisError::Timeout),
        };
        match attempt {
            Ok(connection) => {
                self.inner
                    .connection
                    .store(Some(Arc::new(connection.clone())));
                log_cluster_nodes(connection.clone()).await;
                Ok(connection)
            }
            Err(error) => {
                // The cooldown starts when the attempt ends, so an attempt that runs for the
                // whole connection timeout still leaves a quiet period after it.
                *cooldown_started_at = Some(Instant::now());
                warn!(%error, "cluster connect attempt failed");
                Err(error)
            }
        }
    }

    fn after_result<T>(&self, result: redis::RedisResult<T>) -> Result<T, CustomRedisError> {
        match result {
            Ok(value) => {
                self.inner.consecutive_failures.store(0, Ordering::Relaxed);
                Ok(value)
            }
            Err(error) => Err(self.after_error(error)),
        }
    }

    fn after_error(&self, error: redis::RedisError) -> CustomRedisError {
        let failures = self
            .inner
            .consecutive_failures
            .fetch_add(1, Ordering::Relaxed)
            + 1;
        if failures >= FAILURES_BEFORE_RECONNECT {
            if let Ok(mut cooldown_started_at) = self.inner.cooldown_started_at.try_lock() {
                self.inner.consecutive_failures.store(0, Ordering::Relaxed);
                self.inner.connection.store(None);
                *cooldown_started_at = Some(Instant::now());
                warn!(%error, "cluster connection dropped; reconnecting after the cooldown");
            }
        }
        error.into()
    }
}

/// Logs the topology the new connection found, because the dev and prod checks of a managed
/// cache need its node list. The log holds node addresses only, never the URL or a password.
async fn log_cluster_nodes(mut connection: ClusterConnection) {
    let slots: redis::RedisResult<redis::Value> = redis::cmd("CLUSTER")
        .arg("SLOTS")
        .query_async(&mut connection)
        .await;
    match slots {
        Ok(slots) => {
            let (primaries, replicas) = cluster_nodes(&slots);
            info!(?primaries, ?replicas, "cluster connection established");
        }
        Err(error) => warn!(%error, "cluster connection established; CLUSTER SLOTS failed"),
    }
}

/// Splits a `CLUSTER SLOTS` reply into sorted primary and replica addresses. The first node of
/// each slot range is its primary. An empty host means the node that answered.
fn cluster_nodes(slots: &redis::Value) -> (Vec<String>, Vec<String>) {
    let mut primaries = BTreeSet::new();
    let mut replicas = BTreeSet::new();
    let ranges: Vec<Vec<redis::Value>> = redis::from_redis_value(slots).unwrap_or_default();
    for range in &ranges {
        for (position, node) in range.iter().skip(2).enumerate() {
            let Ok(node) = redis::from_redis_value::<Vec<redis::Value>>(node) else {
                continue;
            };
            let (Some(host), Some(port)) = (node.first(), node.get(1)) else {
                continue;
            };
            let host: String = redis::from_redis_value(host).unwrap_or_default();
            let port: i64 = redis::from_redis_value(port).unwrap_or_default();
            let addresses = if position == 0 {
                &mut primaries
            } else {
                &mut replicas
            };
            addresses.insert(format!("{host}:{port}"));
        }
    }
    (
        primaries.into_iter().collect(),
        replicas.into_iter().collect(),
    )
}

fn not_connected() -> CustomRedisError {
    CustomRedisError::from(redis::RedisError::from((
        redis::ErrorKind::IoError,
        "cluster not connected; next connect attempt after the cooldown",
    )))
}

fn unsupported(method: &str) -> CustomRedisError {
    CustomRedisError::InvalidConfiguration(format!(
        "{method} is not supported by the quota cluster client"
    ))
}

#[async_trait]
impl Client for RedisClusterClient {
    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        let mut connection = self.connection().await?;
        let result: redis::RedisResult<Vec<String>> = connection.zrangebyscore(k, min, max).await;
        self.after_result(result)
    }

    async fn zrangebyscore_limit(
        &self,
        k: String,
        min: String,
        max: String,
        offset: isize,
        count: isize,
    ) -> Result<Vec<String>, CustomRedisError> {
        let mut connection = self.connection().await?;
        let result: redis::RedisResult<Vec<String>> = connection
            .zrangebyscore_limit(k, min, max, offset, count)
            .await;
        self.after_result(result)
    }

    async fn zadd(&self, _k: String, _m: String, _s: i64) -> Result<(), CustomRedisError> {
        Err(unsupported("zadd"))
    }
    async fn zadd_nx(&self, _k: String, _m: String, _s: i64) -> Result<(), CustomRedisError> {
        Err(unsupported("zadd_nx"))
    }
    async fn zrem(&self, _k: String, _m: String) -> Result<(), CustomRedisError> {
        Err(unsupported("zrem"))
    }
    async fn hincrby(&self, _k: String, _v: String, _c: i64) -> Result<(), CustomRedisError> {
        Err(unsupported("hincrby"))
    }
    async fn get(&self, _k: String) -> Result<String, CustomRedisError> {
        Err(unsupported("get"))
    }
    async fn get_with_format(
        &self,
        _k: String,
        _f: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        Err(unsupported("get_with_format"))
    }
    async fn get_raw_bytes(&self, _k: String) -> Result<Vec<u8>, CustomRedisError> {
        Err(unsupported("get_raw_bytes"))
    }
    async fn set_bytes(
        &self,
        _k: String,
        _v: Vec<u8>,
        _t: Option<u64>,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("set_bytes"))
    }
    async fn set(&self, _k: String, _v: String) -> Result<(), CustomRedisError> {
        Err(unsupported("set"))
    }
    async fn set_with_format(
        &self,
        _k: String,
        _v: String,
        _f: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("set_with_format"))
    }
    async fn setex(&self, _k: String, _v: String, _s: u64) -> Result<(), CustomRedisError> {
        Err(unsupported("setex"))
    }
    async fn setex_with_format(
        &self,
        _k: String,
        _v: String,
        _s: u64,
        _f: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("setex_with_format"))
    }
    async fn set_nx_ex(&self, _k: String, _v: String, _s: u64) -> Result<bool, CustomRedisError> {
        Err(unsupported("set_nx_ex"))
    }
    async fn set_nx_ex_with_format(
        &self,
        _k: String,
        _v: String,
        _s: u64,
        _f: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        Err(unsupported("set_nx_ex_with_format"))
    }
    async fn batch_incr_by_expire_nx(
        &self,
        _i: Vec<(String, i64)>,
        _t: usize,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("batch_incr_by_expire_nx"))
    }
    async fn batch_incr_by_expire(
        &self,
        _i: Vec<(String, i64)>,
        _t: usize,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("batch_incr_by_expire"))
    }
    async fn batch_incr_by_expire_at(
        &self,
        _i: Vec<(String, i64, i64)>,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("batch_incr_by_expire_at"))
    }
    async fn del(&self, _k: String) -> Result<(), CustomRedisError> {
        Err(unsupported("del"))
    }
    async fn hget(&self, _k: String, _f: String) -> Result<String, CustomRedisError> {
        Err(unsupported("hget"))
    }
    async fn scard(&self, _k: String) -> Result<u64, CustomRedisError> {
        Err(unsupported("scard"))
    }
    async fn mget(&self, _k: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        Err(unsupported("mget"))
    }
    async fn get_multiple(
        &self,
        _k: Vec<String>,
    ) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        Err(unsupported("get_multiple"))
    }
    async fn scard_multiple(&self, _k: Vec<String>) -> Result<Vec<u64>, CustomRedisError> {
        Err(unsupported("scard_multiple"))
    }
    async fn batch_sadd_expire(
        &self,
        _i: Vec<(String, String)>,
        _t: usize,
    ) -> Result<(), CustomRedisError> {
        Err(unsupported("batch_sadd_expire"))
    }
    async fn batch_set_nx_ex(
        &self,
        _i: Vec<(String, String, usize)>,
    ) -> Result<Vec<bool>, CustomRedisError> {
        Err(unsupported("batch_set_nx_ex"))
    }
    async fn batch_del(&self, _k: Vec<String>) -> Result<(), CustomRedisError> {
        Err(unsupported("batch_del"))
    }
    async fn execute_pipeline(
        &self,
        _c: Vec<PipelineCommand>,
    ) -> Result<Vec<Result<PipelineResult, CustomRedisError>>, CustomRedisError> {
        Err(unsupported("execute_pipeline"))
    }
}

#[cfg(test)]
mod tests {
    use std::fmt::Debug;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};

    use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
    use tokio::net::tcp::OwnedReadHalf;
    use tokio::net::{TcpListener, TcpStream};

    use super::*;

    const RESPONSE_TIMEOUT: Duration = Duration::from_millis(500);
    const CONNECTION_TIMEOUT: Duration = Duration::from_secs(1);
    const TEST_COOLDOWN: Duration = Duration::from_millis(200);
    const HANG_GUARD: Duration = Duration::from_secs(10);
    const KEY: &str = "@posthog/quota-limits/events";
    const MEMBER: &str = "phc_live";

    #[derive(Clone, Copy, PartialEq)]
    enum NodeMode {
        Answer,
        Hang,
    }

    /// A one-node cluster on a local port. It speaks enough RESP2 for the client: the connection
    /// setup, `CLUSTER SLOTS` with itself as the only primary, and `ZRANGEBYSCORE`. A connection
    /// that sees `Hang` stops answering for good, like a frozen node.
    struct FakeNode {
        port: u16,
        mode: Arc<Mutex<NodeMode>>,
        connections: Arc<AtomicUsize>,
    }

    impl FakeNode {
        async fn start(mode: NodeMode) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            let mode = Arc::new(Mutex::new(mode));
            let connections = Arc::new(AtomicUsize::new(0));
            let (accept_mode, accept_count) = (mode.clone(), connections.clone());
            tokio::spawn(async move {
                while let Ok((socket, _)) = listener.accept().await {
                    accept_count.fetch_add(1, Ordering::SeqCst);
                    tokio::spawn(serve(socket, port, accept_mode.clone()));
                }
            });
            Self {
                port,
                mode,
                connections,
            }
        }

        fn url(&self) -> String {
            format!("redis://127.0.0.1:{}", self.port)
        }

        fn set_mode(&self, mode: NodeMode) {
            *self.mode.lock().unwrap() = mode;
        }

        fn connections(&self) -> usize {
            self.connections.load(Ordering::SeqCst)
        }
    }

    async fn serve(socket: TcpStream, port: u16, mode: Arc<Mutex<NodeMode>>) {
        let (read, mut write) = socket.into_split();
        let mut read = BufReader::new(read);
        let mut hung = false;
        while let Some(command) = read_command(&mut read).await {
            hung |= *mode.lock().unwrap() == NodeMode::Hang;
            if hung {
                continue;
            }
            let reply = match command[0].to_ascii_uppercase().as_str() {
                "PING" => "+PONG\r\n".to_string(),
                "CLUSTER" => {
                    format!("*1\r\n*3\r\n:0\r\n:16383\r\n*2\r\n$9\r\n127.0.0.1\r\n:{port}\r\n")
                }
                "ZRANGEBYSCORE" => format!("*1\r\n${}\r\n{MEMBER}\r\n", MEMBER.len()),
                _ => "+OK\r\n".to_string(),
            };
            if write.write_all(reply.as_bytes()).await.is_err() {
                return;
            }
        }
    }

    async fn read_command(read: &mut BufReader<OwnedReadHalf>) -> Option<Vec<String>> {
        let mut line = String::new();
        read.read_line(&mut line)
            .await
            .ok()
            .filter(|read| *read > 0)?;
        let count: usize = line.trim_end().strip_prefix('*')?.parse().ok()?;
        let mut command = Vec::with_capacity(count);
        for _ in 0..count {
            line.clear();
            read.read_line(&mut line).await.ok()?;
            let length: usize = line.trim_end().strip_prefix('$')?.parse().ok()?;
            let mut argument = vec![0; length + 2];
            read.read_exact(&mut argument).await.ok()?;
            argument.truncate(length);
            command.push(String::from_utf8(argument).ok()?);
        }
        Some(command)
    }

    fn client_for(node: &FakeNode) -> RedisClusterClient {
        RedisClusterClient::with_connect_cooldown(
            node.url(),
            RESPONSE_TIMEOUT,
            CONNECTION_TIMEOUT,
            false,
            TEST_COOLDOWN,
        )
        .unwrap()
    }

    async fn read(client: &RedisClusterClient) -> Result<Vec<String>, CustomRedisError> {
        tokio::time::timeout(
            HANG_GUARD,
            client.zrangebyscore(KEY.to_string(), "0".to_string(), "+inf".to_string()),
        )
        .await
        .expect("a read must end within its timeouts")
    }

    fn assert_unsupported<T: Debug>(result: Result<T, CustomRedisError>, method: &str) {
        match result {
            Err(CustomRedisError::InvalidConfiguration(message)) => {
                assert!(message.contains(method), "{message}");
                assert!(message.contains("not supported by the quota cluster client"));
            }
            other => panic!("{method} returned {other:?}"),
        }
    }

    #[test]
    fn new_rejects_zero_timeouts_but_not_an_unreachable_cache() {
        let unroutable = "redis://192.0.2.1:6379".to_string();
        let second = Duration::from_secs(1);
        assert!(RedisClusterClient::new(unroutable.clone(), second, second, true).is_ok());
        for (response_timeout, connection_timeout) in
            [(Duration::ZERO, second), (second, Duration::ZERO)]
        {
            assert!(matches!(
                RedisClusterClient::new(
                    unroutable.clone(),
                    response_timeout,
                    connection_timeout,
                    true
                ),
                Err(CustomRedisError::InvalidConfiguration(_))
            ));
        }
    }

    #[tokio::test]
    async fn unsupported_methods_fail_without_io() {
        let node = FakeNode::start(NodeMode::Answer).await;
        let client = client_for(&node);
        let key = || KEY.to_string();
        let format = RedisValueFormat::Utf8;

        assert_unsupported(client.zadd(key(), key(), 1).await, "zadd");
        assert_unsupported(client.zadd_nx(key(), key(), 1).await, "zadd_nx");
        assert_unsupported(client.zrem(key(), key()).await, "zrem");
        assert_unsupported(client.hincrby(key(), key(), 1).await, "hincrby");
        assert_unsupported(client.get(key()).await, "get");
        assert_unsupported(
            client.get_with_format(key(), format).await,
            "get_with_format",
        );
        assert_unsupported(client.get_raw_bytes(key()).await, "get_raw_bytes");
        assert_unsupported(client.set_bytes(key(), vec![], None).await, "set_bytes");
        assert_unsupported(client.set(key(), key()).await, "set");
        assert_unsupported(
            client.set_with_format(key(), key(), format).await,
            "set_with_format",
        );
        assert_unsupported(client.setex(key(), key(), 1).await, "setex");
        assert_unsupported(
            client.setex_with_format(key(), key(), 1, format).await,
            "setex_with_format",
        );
        assert_unsupported(client.set_nx_ex(key(), key(), 1).await, "set_nx_ex");
        assert_unsupported(
            client.set_nx_ex_with_format(key(), key(), 1, format).await,
            "set_nx_ex_with_format",
        );
        assert_unsupported(
            client.batch_incr_by_expire_nx(vec![(key(), 1)], 1).await,
            "batch_incr_by_expire_nx",
        );
        assert_unsupported(
            client.batch_incr_by_expire(vec![(key(), 1)], 1).await,
            "batch_incr_by_expire",
        );
        assert_unsupported(
            client.batch_incr_by_expire_at(vec![(key(), 1, 1)]).await,
            "batch_incr_by_expire_at",
        );
        assert_unsupported(client.del(key()).await, "del");
        assert_unsupported(client.hget(key(), key()).await, "hget");
        assert_unsupported(client.scard(key()).await, "scard");
        assert_unsupported(client.mget(vec![key()]).await, "mget");
        assert_unsupported(client.get_multiple(vec![key()]).await, "get_multiple");
        assert_unsupported(client.scard_multiple(vec![key()]).await, "scard_multiple");
        assert_unsupported(
            client.batch_sadd_expire(vec![(key(), key())], 1).await,
            "batch_sadd_expire",
        );
        assert_unsupported(
            client.batch_set_nx_ex(vec![(key(), key(), 1)]).await,
            "batch_set_nx_ex",
        );
        assert_unsupported(client.batch_del(vec![key()]).await, "batch_del");
        assert_unsupported(client.execute_pipeline(vec![]).await, "execute_pipeline");

        assert_eq!(node.connections(), 0);
    }

    #[tokio::test]
    async fn a_node_that_does_not_answer_at_startup_is_retried_after_the_cooldown() {
        let node = FakeNode::start(NodeMode::Hang).await;
        let client = client_for(&node);

        assert!(read(&client).await.is_err());
        let after_first_attempt = node.connections();
        assert!(after_first_attempt > 0);

        let in_cooldown = read(&client).await.unwrap_err();
        assert!(!in_cooldown.is_unrecoverable_error());
        assert_eq!(node.connections(), after_first_attempt);

        node.set_mode(NodeMode::Answer);
        tokio::time::sleep(TEST_COOLDOWN).await;
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);
        assert!(node.connections() > after_first_attempt);
        assert_eq!(
            client
                .zrangebyscore_limit(KEY.to_string(), "0".to_string(), "+inf".to_string(), 0, 1)
                .await
                .unwrap(),
            vec![MEMBER.to_string()]
        );
    }

    #[tokio::test]
    async fn three_failed_reads_in_a_row_rebuild_the_connection() {
        let node = FakeNode::start(NodeMode::Answer).await;
        let client = client_for(&node);
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);

        node.set_mode(NodeMode::Hang);
        for _ in 0..3 {
            assert!(matches!(
                read(&client).await,
                Err(CustomRedisError::Timeout)
            ));
        }
        node.set_mode(NodeMode::Answer);
        let before_rebuild = node.connections();

        let in_cooldown = read(&client).await.unwrap_err();
        assert!(!in_cooldown.is_unrecoverable_error());
        assert_eq!(node.connections(), before_rebuild);

        tokio::time::sleep(TEST_COOLDOWN).await;
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);
        assert!(node.connections() > before_rebuild);
    }

    #[test]
    fn cluster_nodes_splits_primaries_from_replicas() {
        let node = |host: &str, port: i64| {
            redis::Value::Array(vec![
                redis::Value::BulkString(host.as_bytes().to_vec()),
                redis::Value::Int(port),
                redis::Value::BulkString(b"node-id".to_vec()),
            ])
        };
        let slots = redis::Value::Array(vec![
            redis::Value::Array(vec![
                redis::Value::Int(0),
                redis::Value::Int(8191),
                node("cache.example.com", 6379),
                node("cache.example.com", 6380),
            ]),
            redis::Value::Array(vec![
                redis::Value::Int(8192),
                redis::Value::Int(16383),
                node("cache.example.com", 6379),
                node("", 6380),
            ]),
        ]);

        let (primaries, replicas) = cluster_nodes(&slots);

        assert_eq!(primaries, vec!["cache.example.com:6379"]);
        assert_eq!(replicas, vec![":6380", "cache.example.com:6380"]);
    }
}
