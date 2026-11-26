use std::sync::Arc;
use std::time::{Duration, Instant};

use arc_swap::ArcSwapOption;
use async_trait::async_trait;
use tracing::warn;

use crate::pipeline::{PipelineCommand, PipelineResult};
use crate::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};

const CONNECT_COOLDOWN: Duration = Duration::from_secs(5);
const CONNECT_BUDGET_MARGIN: Duration = Duration::from_millis(500);

/// Connects on the first read, so a cache that is down at startup cannot fail or block the
/// caller. Only `zrangebyscore` works; every other method returns an error.
pub struct LazyRedisClient {
    url: String,
    response_timeout: Duration,
    connection_timeout: Duration,
    connect_cooldown: Duration,
    client: ArcSwapOption<RedisClient>,
    /// Also serializes connect attempts, so concurrent first reads start one connect.
    cooldown_started_at: tokio::sync::Mutex<Option<Instant>>,
}

impl LazyRedisClient {
    /// Do not time out reads before the connect budget ends: a dropped connect sets no cooldown.
    pub fn new(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
    ) -> Result<Self, CustomRedisError> {
        Self::with_cooldown(url, response_timeout, connection_timeout, CONNECT_COOLDOWN)
    }

    fn with_cooldown(
        url: String,
        response_timeout: Duration,
        connection_timeout: Duration,
        connect_cooldown: Duration,
    ) -> Result<Self, CustomRedisError> {
        redis::Client::open(url.as_str())?;
        Ok(Self {
            url,
            response_timeout,
            connection_timeout,
            connect_cooldown,
            client: ArcSwapOption::empty(),
            cooldown_started_at: tokio::sync::Mutex::new(None),
        })
    }

    async fn connected_client(&self) -> Result<Arc<RedisClient>, CustomRedisError> {
        if let Some(client) = self.client.load_full() {
            return Ok(client);
        }
        let mut cooldown_started_at = self.cooldown_started_at.lock().await;
        if let Some(client) = self.client.load_full() {
            return Ok(client);
        }
        if cooldown_started_at.is_some_and(|started| started.elapsed() < self.connect_cooldown) {
            return Err(not_connected());
        }
        let connect = RedisClient::with_config(
            self.url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::default(),
            Some(self.response_timeout),
            Some(self.connection_timeout),
        );
        let connect_budget = self.connection_timeout + CONNECT_BUDGET_MARGIN;
        let attempt = tokio::time::timeout(connect_budget, connect)
            .await
            .unwrap_or(Err(CustomRedisError::Timeout));
        match attempt {
            Ok(client) => {
                let client = Arc::new(client);
                self.client.store(Some(client.clone()));
                Ok(client)
            }
            Err(error) => {
                *cooldown_started_at = Some(Instant::now());
                warn!(%error, "quota Redis connect attempt failed");
                Err(error)
            }
        }
    }
}

fn not_connected() -> CustomRedisError {
    CustomRedisError::from(redis::RedisError::from((
        redis::ErrorKind::IoError,
        "quota Redis not connected; next connect attempt after the cooldown",
    )))
}

fn unsupported(method: &str) -> CustomRedisError {
    CustomRedisError::InvalidConfiguration(format!(
        "{method} is not supported by the lazy quota client"
    ))
}

#[async_trait]
impl Client for LazyRedisClient {
    async fn zrangebyscore(
        &self,
        k: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        let client = self.connected_client().await?;
        let result = client.zrangebyscore(k, min, max).await;
        if let Err(error) = &result {
            // A response timeout is not unrecoverable, but a hung connection never answers again.
            if matches!(error, CustomRedisError::Timeout) || error.is_unrecoverable_error() {
                warn!(%error, "quota Redis read failed; asking the connection to heal");
                client.heal_connection().await;
            }
        }
        result
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
    use std::sync::Mutex;

    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    use tokio::net::tcp::OwnedReadHalf;
    use tokio::net::{TcpListener, TcpStream};

    use super::*;

    const RESPONSE_TIMEOUT: Duration = Duration::from_millis(500);
    const CONNECTION_TIMEOUT: Duration = Duration::from_secs(1);
    const TEST_COOLDOWN: Duration = Duration::from_millis(500);
    const HANG_GUARD: Duration = Duration::from_secs(10);
    const KEY: &str = "@posthog/quota-limits/events";
    const MEMBER: &str = "phc_live";

    #[derive(Clone, Copy, Debug)]
    enum Fault {
        Fail,
        Hang,
        Close,
    }

    /// Fault, and the index of the first connection it spares.
    type FaultPlan = Arc<Mutex<(Option<Fault>, usize)>>;

    /// A Redis node that answers the connection setup and `ZRANGEBYSCORE`.
    struct FakeNode {
        port: u16,
        connections: Arc<AtomicUsize>,
        fault: FaultPlan,
    }

    impl FakeNode {
        async fn start() -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            let connections = Arc::new(AtomicUsize::new(0));
            let fault: FaultPlan = Arc::new(Mutex::new((None, 0)));
            let (accept_count, accept_fault) = (connections.clone(), fault.clone());
            tokio::spawn(async move {
                while let Ok((socket, _)) = listener.accept().await {
                    let index = accept_count.fetch_add(1, Ordering::SeqCst);
                    tokio::spawn(serve(socket, index, accept_fault.clone()));
                }
            });
            Self {
                port,
                connections,
                fault,
            }
        }

        fn url(&self) -> String {
            format!("redis://127.0.0.1:{}", self.port)
        }

        fn fault_every_connection(&self, fault: Option<Fault>) {
            *self.fault.lock().unwrap() = (fault, usize::MAX);
        }

        fn fault_open_connections(&self, fault: Fault) {
            *self.fault.lock().unwrap() = (Some(fault), self.connections());
        }

        fn connections(&self) -> usize {
            self.connections.load(Ordering::SeqCst)
        }
    }

    async fn serve(socket: TcpStream, index: usize, plan: FaultPlan) {
        let (read, mut write) = socket.into_split();
        let mut read = BufReader::new(read);
        while let Some(command) = read_command_name(&mut read).await {
            let (fault, first_spared) = *plan.lock().unwrap();
            let reply = match fault.filter(|_| index < first_spared) {
                Some(Fault::Hang) => continue,
                Some(Fault::Close) => return,
                Some(Fault::Fail) => "-ERR fake failure\r\n".to_string(),
                None if command.eq_ignore_ascii_case("ZRANGEBYSCORE") => {
                    format!("*1\r\n${}\r\n{MEMBER}\r\n", MEMBER.len())
                }
                None => "+OK\r\n".to_string(),
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

    fn client_for(node: &FakeNode) -> LazyRedisClient {
        LazyRedisClient::with_cooldown(
            node.url(),
            RESPONSE_TIMEOUT,
            CONNECTION_TIMEOUT,
            TEST_COOLDOWN,
        )
        .unwrap()
    }

    async fn read(client: &LazyRedisClient) -> Result<Vec<String>, CustomRedisError> {
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
                format!("{method} is not supported by the lazy quota client")
            ),
            other => panic!("{method} returned {other:?}"),
        }
    }

    #[tokio::test]
    async fn unsupported_methods_fail_without_io() {
        let node = FakeNode::start().await;
        let client =
            LazyRedisClient::new(node.url(), RESPONSE_TIMEOUT, CONNECTION_TIMEOUT).unwrap();
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

    #[test]
    fn construction_does_no_io_and_fails_only_for_a_bad_url() {
        let unroutable = "redis://192.0.2.1:6379".to_string();
        assert!(LazyRedisClient::new(unroutable, RESPONSE_TIMEOUT, CONNECTION_TIMEOUT).is_ok());

        let bad_url = "redis://:hunter2@127.0.0.1:no-port".to_string();
        let error = LazyRedisClient::new(bad_url, RESPONSE_TIMEOUT, CONNECTION_TIMEOUT)
            .err()
            .expect("a URL that does not parse must fail");
        assert!(!error.to_string().contains("hunter2"), "{error}");
    }

    #[tokio::test]
    async fn a_node_that_does_not_answer_at_startup_is_retried_after_the_cooldown() {
        let node = FakeNode::start().await;
        node.fault_every_connection(Some(Fault::Hang));
        let client = client_for(&node);

        let first = read(&client).await;
        assert!(matches!(first, Err(CustomRedisError::Timeout)), "{first:?}");
        assert_eq!(node.connections(), 1);

        assert!(read(&client).await.is_err());
        assert_eq!(
            node.connections(),
            1,
            "a read in the cooldown must not connect"
        );

        node.fault_every_connection(None);
        tokio::time::sleep(TEST_COOLDOWN).await;
        let (first, second) = tokio::join!(read(&client), read(&client));
        assert_eq!(first.unwrap(), vec![MEMBER.to_string()]);
        assert_eq!(second.unwrap(), vec![MEMBER.to_string()]);
        assert_eq!(
            node.connections(),
            2,
            "concurrent reads must share one connect"
        );
    }

    #[tokio::test]
    async fn a_failed_read_rebuilds_the_connection_only_when_it_is_broken() {
        for (fault, rebuilds) in [
            (Fault::Hang, true),
            (Fault::Close, true),
            (Fault::Fail, false),
        ] {
            let node = FakeNode::start().await;
            let client = client_for(&node);
            assert_eq!(read(&client).await.unwrap(), vec![MEMBER.to_string()]);

            node.fault_open_connections(fault);
            let error = read(&client).await.unwrap_err();
            let is_original_error = match fault {
                Fault::Hang => matches!(error, CustomRedisError::Timeout),
                Fault::Close => error.is_unrecoverable_error(),
                Fault::Fail => matches!(&error, CustomRedisError::Redis(reply)
                    if reply.kind() == redis::ErrorKind::ResponseError),
            };
            assert!(is_original_error, "{fault:?}: {error:?}");
            assert_eq!(node.connections(), 1 + usize::from(rebuilds), "{fault:?}");
            if rebuilds {
                let healed = read(&client).await;
                assert_eq!(healed.unwrap(), vec![MEMBER.to_string()], "{fault:?}");
            }
        }
    }
}
