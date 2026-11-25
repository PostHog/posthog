use std::sync::{Arc, Mutex, PoisonError};
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
/// Limiters that share one client refresh together, so a rebuild also needs the streak to span
/// more than one refresh round.
const FAILURE_STREAK_MIN_AGE: Duration = Duration::from_secs(4);

/// Connects on the first read, so a cache that is down at startup cannot fail or block the
/// caller. Only `zrangebyscore` works; every other method returns an error.
pub struct RedisClusterClient {
    client: ClusterClient,
    connection: ArcSwapOption<ClusterConnection>,
    /// Also serializes connect attempts, so concurrent first reads start one connect.
    cooldown_started_at: tokio::sync::Mutex<Option<Instant>>,
    connect_cooldown: Duration,
    connect_budget: Duration,
    failure_streak_min_age: Duration,
    failure_streak: Mutex<FailureStreak>,
}

#[derive(Default)]
struct FailureStreak {
    failures: u32,
    started_at: Option<Instant>,
}

impl RedisClusterClient {
    /// Do not time out reads before the connect budget ends: a dropped connect sets no cooldown.
    pub fn new(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
        read_from_replicas: bool,
    ) -> Result<Self, CustomRedisError> {
        Self::with_timings(
            url,
            response_timeout,
            connection_timeout,
            read_from_replicas,
            CONNECT_COOLDOWN,
            FAILURE_STREAK_MIN_AGE,
        )
    }

    fn with_timings(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
        read_from_replicas: bool,
        connect_cooldown: Duration,
        failure_streak_min_age: Duration,
    ) -> Result<Self, CustomRedisError> {
        let mut builder = ClusterClientBuilder::new([url])
            .response_timeout(response_timeout)
            .connection_timeout(connection_timeout)
            .retries(1);
        if read_from_replicas {
            builder = builder.read_from_replicas();
        }
        Ok(Self {
            client: builder.build()?,
            connection: ArcSwapOption::empty(),
            cooldown_started_at: tokio::sync::Mutex::new(None),
            connect_cooldown,
            // Seed connect, PING or READONLY, CLUSTER SLOTS, then the per-node connects.
            connect_budget: connection_timeout * 2 + response_timeout * 3,
            failure_streak_min_age,
            failure_streak: Mutex::new(FailureStreak::default()),
        })
    }

    async fn connection(&self) -> Result<ClusterConnection, CustomRedisError> {
        if let Some(connection) = self.connection.load_full() {
            return Ok(ClusterConnection::clone(&connection));
        }
        let mut cooldown_started_at = self.cooldown_started_at.lock().await;
        if let Some(connection) = self.connection.load_full() {
            return Ok(ClusterConnection::clone(&connection));
        }
        if cooldown_started_at.is_some_and(|started| started.elapsed() < self.connect_cooldown) {
            return Err(not_connected());
        }
        let attempt =
            match tokio::time::timeout(self.connect_budget, self.client.get_async_connection())
                .await
            {
                Ok(attempt) => attempt.map_err(CustomRedisError::from),
                Err(_) => Err(CustomRedisError::Timeout),
            };
        match attempt {
            Ok(connection) => {
                self.connection.store(Some(Arc::new(connection.clone())));
                log_cluster_slots(connection.clone()).await;
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
                *self.failure_streak() = FailureStreak::default();
                Ok(value)
            }
            Err(error) => Err(self.after_error(error)),
        }
    }

    fn after_error(&self, error: redis::RedisError) -> CustomRedisError {
        let rebuild = {
            let mut streak = self.failure_streak();
            streak.failures += 1;
            let started_at = *streak.started_at.get_or_insert_with(Instant::now);
            streak.failures >= FAILURES_BEFORE_RECONNECT
                && started_at.elapsed() >= self.failure_streak_min_age
        };
        if rebuild {
            if let Ok(mut cooldown_started_at) = self.cooldown_started_at.try_lock() {
                *self.failure_streak() = FailureStreak::default();
                self.connection.store(None);
                *cooldown_started_at = Some(Instant::now());
                warn!(%error, "cluster connection dropped; reconnecting after the cooldown");
            }
        }
        error.into()
    }

    fn failure_streak(&self) -> std::sync::MutexGuard<'_, FailureStreak> {
        self.failure_streak
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

/// Logs the slot map the new connection found, because the dev and prod checks of a managed
/// cache need its node list. The reply holds node addresses and IDs, never the URL or a password.
async fn log_cluster_slots(mut connection: ClusterConnection) {
    let slots: redis::RedisResult<redis::Value> = redis::cmd("CLUSTER")
        .arg("SLOTS")
        .query_async(&mut connection)
        .await;
    match slots {
        Ok(slots) => info!(?slots, "cluster connection established"),
        Err(error) => warn!(%error, "cluster connection established; CLUSTER SLOTS failed"),
    }
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
        _k: String,
        _min: String,
        _max: String,
        _o: isize,
        _c: isize,
    ) -> Result<Vec<String>, CustomRedisError> {
        Err(unsupported("zrangebyscore_limit"))
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

    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    use tokio::net::tcp::OwnedReadHalf;
    use tokio::net::{TcpListener, TcpStream};

    use super::*;

    const RESPONSE_TIMEOUT: Duration = Duration::from_millis(500);
    const CONNECTION_TIMEOUT: Duration = Duration::from_secs(1);
    const TEST_COOLDOWN: Duration = Duration::from_millis(200);
    const TEST_STREAK_MIN_AGE: Duration = Duration::from_millis(400);
    const HANG_GUARD: Duration = Duration::from_secs(10);
    const KEY: &str = "@posthog/quota-limits/events";
    const MEMBER: &str = "phc_live";

    #[derive(Clone, Copy, PartialEq)]
    enum NodeMode {
        Answer,
        Fail,
        Hang,
    }

    /// A one-node cluster that answers the connection setup, `CLUSTER SLOTS` and `ZRANGEBYSCORE`.
    /// A connection that sees `Hang` stops answering for good, like a frozen node.
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
        while let Some(command) = read_command_name(&mut read).await {
            let current = *mode.lock().unwrap();
            hung |= current == NodeMode::Hang;
            if hung {
                continue;
            }
            let reply = match command.to_ascii_uppercase().as_str() {
                "PING" => "+PONG\r\n".to_string(),
                "CLUSTER" => {
                    format!("*1\r\n*3\r\n:0\r\n:16383\r\n*2\r\n$9\r\n127.0.0.1\r\n:{port}\r\n")
                }
                "ZRANGEBYSCORE" if current == NodeMode::Fail => "-ERR fake failure\r\n".to_string(),
                "ZRANGEBYSCORE" => format!("*1\r\n${}\r\n{MEMBER}\r\n", MEMBER.len()),
                _ => "+OK\r\n".to_string(),
            };
            if write.write_all(reply.as_bytes()).await.is_err() {
                return;
            }
        }
    }

    /// Reads each argument as one line, so no argument may hold CRLF.
    async fn read_command_name(read: &mut BufReader<OwnedReadHalf>) -> Option<String> {
        let mut line = String::new();
        read.read_line(&mut line)
            .await
            .ok()
            .filter(|read| *read > 0)?;
        let count: usize = line.trim_end().strip_prefix('*')?.parse().ok()?;
        let mut name = String::new();
        for index in 0..count * 2 {
            line.clear();
            read.read_line(&mut line).await.ok()?;
            if index == 1 {
                name = line.trim_end().to_string();
            }
        }
        Some(name)
    }

    fn client_for(node: &FakeNode) -> RedisClusterClient {
        RedisClusterClient::with_timings(
            node.url(),
            RESPONSE_TIMEOUT,
            CONNECTION_TIMEOUT,
            false,
            TEST_COOLDOWN,
            TEST_STREAK_MIN_AGE,
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
            Err(CustomRedisError::InvalidConfiguration(message)) => assert_eq!(
                message,
                format!("{method} is not supported by the quota cluster client")
            ),
            other => panic!("{method} returned {other:?}"),
        }
    }

    #[tokio::test]
    async fn unsupported_methods_fail_without_io() {
        let node = FakeNode::start(NodeMode::Answer).await;
        let client =
            RedisClusterClient::new(node.url(), RESPONSE_TIMEOUT, CONNECTION_TIMEOUT, true)
                .unwrap();
        let key = || KEY.to_string();
        let format = RedisValueFormat::Utf8;

        assert_unsupported(
            client.zrangebyscore_limit(key(), key(), key(), 0, 1).await,
            "zrangebyscore_limit",
        );
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
    }

    #[tokio::test]
    async fn three_failed_reads_in_a_row_rebuild_the_connection() {
        let node = FakeNode::start(NodeMode::Answer).await;
        let client = client_for(&node);
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);

        node.set_mode(NodeMode::Hang);
        for _ in 0..3 {
            let result = read(&client).await;
            assert!(
                matches!(result, Err(CustomRedisError::Timeout)),
                "{result:?}"
            );
        }
        node.set_mode(NodeMode::Answer);
        let before_rebuild = node.connections();

        let in_cooldown = read(&client).await.unwrap_err();
        assert!(
            !matches!(in_cooldown, CustomRedisError::Timeout),
            "the third failure must drop the hung connection"
        );
        assert!(!in_cooldown.is_unrecoverable_error());
        assert_eq!(node.connections(), before_rebuild);

        tokio::time::sleep(TEST_COOLDOWN).await;
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);
        assert!(node.connections() > before_rebuild);
    }

    #[tokio::test]
    async fn a_success_clears_the_failure_streak() {
        let node = FakeNode::start(NodeMode::Fail).await;
        let client = client_for(&node);
        assert!(read(&client).await.is_err());
        tokio::time::sleep(TEST_STREAK_MIN_AGE).await;
        node.set_mode(NodeMode::Answer);
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);

        node.set_mode(NodeMode::Fail);
        for _ in 0..3 {
            assert!(read(&client).await.is_err());
        }
        node.set_mode(NodeMode::Answer);
        let connections = node.connections();
        assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);
        assert_eq!(node.connections(), connections);
    }
}
