//! Persons DB faults under steady load, with production pool and timeout settings, except the
//! longer persons statement timeout that `Fault::LockWait` needs. Each fault runs in the
//! production topology, through PgBouncer, and most also run straight to Postgres as a baseline.
//! Ignored because the faults lock `posthog_person` and would stall other tests: run alone with
//! `cargo nextest run -p feature-flags -E 'binary(stall_recovery)' --run-ignored only --test-threads=1`.
//! The PgBouncer topology needs Docker.

pub mod common;
#[path = "stall_recovery/persons_db_proxy.rs"]
mod persons_db_proxy;
#[path = "stall_recovery/pgbouncer.rs"]
mod pgbouncer;

use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use feature_flags::api::types::{FlagDetails, FlagsResponse};
use feature_flags::config::{Config, FlexBool, DEFAULT_TEST_CONFIG};
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use reqwest::{header::CONTENT_TYPE, StatusCode};
use rstest::rstest;
use serde_json::json;
use sqlx::{Connection, PgConnection};
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use common::ServerHandle;
use persons_db_proxy::PersonsDbProxy;
use pgbouncer::{PgBouncer, PoolerSettings};

const DB_FREE_FLAG: &str = "db-free";
const PERSON_FLAG: &str = "person";
const DISTINCT_ID: &str = "stall_user";
const PERSON_EMAIL: &str = "stall@example.com";

const BASELINE: Duration = Duration::from_secs(3);
const RECOVERY_LIMIT: Duration = Duration::from_secs(10);
/// Load continues this long after recovery, so connections reopened after the fault show.
const SETTLE: Duration = Duration::from_secs(5);
/// Production sizes the persons read pool of a zone to the client connections of its minimum
/// flags pods, and the write pool to a fifth of that.
const POOLER_READ_POOL_SIZE: u32 = 8;
const POOLER_WRITE_POOL_SIZE: u32 = 2;
/// Longer than the 3 s acquire timeout and PgBouncer's 5 s server_connect_timeout.
const SLOW_CONNECT: Duration = Duration::from_secs(6);

#[rstest]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "locks posthog_person, which stalls other tests"]
async fn test_cancels_heard_late(
    #[values(Topology::Direct, Topology::PgBouncer)] topology: Topology,
    #[values(16, 30)] fault_secs: u64,
) {
    let report = Scenario::new(
        topology,
        Fault::CancelsHeardLate,
        Duration::from_secs(fault_secs),
    )
    .run()
    .await;
    report.assert_degrades_then_recovers();
    report.assert_connections_reopen();
    if let Topology::PgBouncer = topology {
        report.assert_server_connections_survive();
    }
}

#[rstest]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "locks posthog_person, which stalls other tests"]
async fn test_lock_wait_for_16s(
    #[values(Topology::Direct, Topology::PgBouncer)] topology: Topology,
) {
    let report = Scenario::new(topology, Fault::LockWait, Duration::from_secs(16))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    report.assert_connections_reopen();
    if let Topology::PgBouncer = topology {
        report.assert_server_connections_survive();
    }
}

#[rstest]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_connects_slower_than_the_acquire_timeout_for_16s(
    #[values(Topology::Direct, Topology::PgBouncer)] topology: Topology,
) {
    let report = Scenario::new(topology, Fault::SlowConnects, Duration::from_secs(16))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    assert!(
        report.connect_attempts_during() > 0,
        "no connect attempt reached the database during the fault"
    );
    match topology {
        Topology::Direct => assert_eq!(
            report.connections_opened_during(),
            0,
            "today no connect succeeds during the fault; #122930 and #122931 change this"
        ),
        Topology::PgBouncer => {
            report.assert_database_logins_bounded();
            assert!(
                report.connections_opened_during() > 0,
                "today PgBouncer accepts each connect and closes it while its own logins fail, so the pool reconnects in a loop"
            );
        }
    }
}

#[rstest]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_silent_pooler_connections(#[values(16, 30)] fault_secs: u64) {
    let report = Scenario::new(
        Topology::PgBouncer,
        Fault::SilentConnections,
        Duration::from_secs(fault_secs),
    )
    .run()
    .await;
    report.assert_degrades_then_recovers();
    report.assert_database_logins_bounded();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_pooler_restart() {
    let report = Scenario::new(
        Topology::PgBouncer,
        Fault::PoolerRestart,
        Duration::from_secs(10),
    )
    .run()
    .await;
    report.assert_degrades_then_recovers();
    report.assert_database_logins_bounded();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_request_timeout_counts_as_an_error_that_needed_persons() {
    let proxy = PersonsDbProxy::start(
        &DEFAULT_TEST_CONFIG.persons_read_database_url,
        Ipv4Addr::LOCALHOST.into(),
    )
    .await;
    let token = seed().await;
    let server = ServerHandle::for_config(Config {
        request_timeout_ms: 1_000,
        persons_db_deadline_ms: 0,
        persons_read_database_url: proxy.url().to_string(),
        persons_write_database_url: proxy.url().to_string(),
        ..Config::default_test_config()
    })
    .await;
    server.wait_until_ready().await;
    let errors_before = persons_requests("error");

    proxy.hold_replies();
    let response = server
        .send_flags_request(RequestKind::BothFlags.body(&token), Some("2"), None)
        .await;
    proxy.release_replies();

    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(persons_requests("error") - errors_before, 1);
}

#[derive(Clone, Copy, Debug)]
enum Topology {
    /// flags server -> fault proxy -> Postgres.
    Direct,
    /// flags server -> PgBouncer -> fault proxy -> Postgres, as in production.
    PgBouncer,
}

/// The persons DB as the flags server reaches it in a topology.
struct PersonsDb {
    proxy: PersonsDbProxy,
    pooler: Option<PgBouncer>,
}

impl PersonsDb {
    async fn start(topology: Topology, pooler_settings: &PoolerSettings) -> Self {
        let postgres_url = &DEFAULT_TEST_CONFIG.persons_read_database_url;
        match topology {
            Topology::Direct => Self {
                proxy: PersonsDbProxy::start(postgres_url, Ipv4Addr::LOCALHOST.into()).await,
                pooler: None,
            },
            Topology::PgBouncer => {
                // The PgBouncer container reaches the proxy through the Docker host gateway.
                let proxy =
                    PersonsDbProxy::start(postgres_url, IpAddr::V4(Ipv4Addr::UNSPECIFIED)).await;
                let pooler = PgBouncer::start(postgres_url, proxy.port(), pooler_settings).await;
                Self {
                    proxy,
                    pooler: Some(pooler),
                }
            }
        }
    }

    fn read_url(&self) -> String {
        match &self.pooler {
            Some(pooler) => pooler.url(pgbouncer::READ_DATABASE),
            None => self.proxy.url().to_string(),
        }
    }

    fn write_url(&self) -> String {
        match &self.pooler {
            Some(pooler) => pooler.url(pgbouncer::WRITE_DATABASE),
            None => self.proxy.url().to_string(),
        }
    }

    fn pooler(&self) -> &PgBouncer {
        self.pooler
            .as_ref()
            .expect("this fault runs in the PgBouncer topology")
    }
}

#[derive(Clone, Copy, Debug)]
enum Fault {
    /// Postgres cancels person queries on time, and the proxy holds the cancels until the end.
    CancelsHeardLate,
    /// Person queries wait on a lock past the persons DB deadline, and Postgres cancels them on time.
    LockWait,
    /// Every new connection takes longer than the acquire timeout.
    SlowConnects,
    /// Connections between PgBouncer and Postgres go silent: the proxy holds every reply, and
    /// releases them when the fault ends. Postgres answers on time.
    SilentConnections,
    /// PgBouncer stops, closing every client and server connection, and starts again empty.
    PoolerRestart,
}

impl Fault {
    fn persons_statement_timeout_ms(self) -> u64 {
        match self {
            // Between the 3.5 s persons DB deadline and the lock.
            Fault::LockWait => 5_000,
            Fault::CancelsHeardLate
            | Fault::SlowConnects
            | Fault::SilentConnections
            | Fault::PoolerRestart => 1_000,
        }
    }

    /// Returns when the fault took effect.
    async fn inject(self, db: &PersonsDb, admin: &mut PgConnection) -> Instant {
        let proxy = &db.proxy;
        match self {
            Fault::CancelsHeardLate => {
                lock_person_table(admin).await;
                let start = Instant::now();
                // Less than the statement timeout, so each pooled connection is waiting on the
                // lock when the replies stop, and parks on a held cancel.
                tokio::time::sleep(Duration::from_millis(500)).await;
                proxy.hold_replies();
                start
            }
            Fault::LockWait => {
                lock_person_table(admin).await;
                Instant::now()
            }
            Fault::SlowConnects => {
                proxy.delay_connects(SLOW_CONNECT);
                proxy.close_connections();
                Instant::now()
            }
            Fault::SilentConnections => {
                proxy.hold_replies();
                Instant::now()
            }
            Fault::PoolerRestart => {
                // The pooler serves transactions until it exits.
                db.pooler().stop().await;
                Instant::now()
            }
        }
    }

    async fn lift(self, db: &PersonsDb, admin: &mut PgConnection) {
        let proxy = &db.proxy;
        match self {
            Fault::CancelsHeardLate => {
                unlock_person_table(admin).await;
                proxy.release_replies();
            }
            Fault::LockWait => unlock_person_table(admin).await,
            Fault::SlowConnects => proxy.delay_connects(Duration::ZERO),
            Fault::SilentConnections => proxy.release_replies(),
            Fault::PoolerRestart => db.pooler().start_again().await,
        }
    }
}

async fn lock_person_table(admin: &mut PgConnection) {
    sqlx::query("BEGIN").execute(&mut *admin).await.unwrap();
    sqlx::query("LOCK TABLE posthog_person IN ACCESS EXCLUSIVE MODE")
        .execute(&mut *admin)
        .await
        .unwrap();
}

async fn unlock_person_table(admin: &mut PgConnection) {
    sqlx::query("ROLLBACK").execute(admin).await.unwrap();
}

struct Scenario {
    topology: Topology,
    fault: Fault,
    fault_length: Duration,
    clients: usize,
    max_concurrency: usize,
}

impl Scenario {
    fn new(topology: Topology, fault: Fault, fault_length: Duration) -> Self {
        Self {
            topology,
            fault,
            fault_length,
            clients: 20,
            max_concurrency: 100,
        }
    }

    fn server_config(&self, db: &PersonsDb) -> Config {
        let base = Config {
            acquire_timeout_secs: 3,
            persons_db_deadline_ms: 3_500,
            persons_db_deadline_reserve_ms: 500,
            request_timeout_ms: 4_500,
            max_pg_connections: 8,
            max_concurrency: self.max_concurrency,
            persons_reader_statement_timeout_ms: self.fault.persons_statement_timeout_ms(),
            test_before_acquire: FlexBool(true),
            persons_read_database_url: db.read_url(),
            persons_write_database_url: db.write_url(),
            ..Config::default_test_config()
        };
        match self.topology {
            Topology::Direct => base,
            // The persons pools behind PgBouncer as production configures them.
            Topology::PgBouncer => Config {
                pooler_statement_timeout_pools: "persons_reader,persons_writer".parse().unwrap(),
                min_persons_reader_connections: 2,
                min_persons_writer_connections: 2,
                ..base
            },
        }
    }

    fn pooler_settings(&self) -> PoolerSettings {
        PoolerSettings {
            read_pool_size: POOLER_READ_POOL_SIZE,
            write_pool_size: POOLER_WRITE_POOL_SIZE,
            read_statement_timeout_ms: self.fault.persons_statement_timeout_ms(),
            write_statement_timeout_ms: DEFAULT_TEST_CONFIG.writer_statement_timeout_ms,
        }
    }

    async fn run(&self) -> Report {
        let db = PersonsDb::start(self.topology, &self.pooler_settings()).await;
        let proxy = &db.proxy;
        let mut admin = PgConnection::connect(&DEFAULT_TEST_CONFIG.persons_read_database_url)
            .await
            .unwrap();
        let token = seed().await;
        let server = ServerHandle::for_config(self.server_config(&db)).await;
        server.wait_until_ready().await;

        let load = Load::start(server.addr, &token, self.clients);
        assert!(
            load.wait_until_healthy(Instant::now(), RECOVERY_LIMIT)
                .await,
            "no healthy answer before the fault"
        );
        tokio::time::sleep(BASELINE).await;

        let at_start = Counts::read(proxy);
        let fault_start = self.fault.inject(&db, &mut admin).await;
        tokio::time::sleep_until(fault_start + self.fault_length).await;
        let at_end = Counts::read(proxy);
        let fault_end = Instant::now();
        self.fault.lift(&db, &mut admin).await;

        load.wait_until_healthy(fault_end, RECOVERY_LIMIT).await;
        tokio::time::sleep(SETTLE).await;
        let at_finish = Counts::read(proxy);

        let report = Report {
            topology: self.topology,
            fault: self.fault,
            fault_start,
            fault_end,
            samples: load.stop().await,
            at_start,
            at_end,
            at_finish,
        };
        report.print();
        report
    }
}

/// Returns the team token.
async fn seed() -> String {
    let redis = setup_redis_client(Some(DEFAULT_TEST_CONFIG.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis.clone()).await.unwrap();
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    context
        .insert_person(
            team.id,
            DISTINCT_ID.to_string(),
            Some(json!({ "email": PERSON_EMAIL })),
        )
        .await
        .unwrap();
    let flags = json!([
        {
            "id": 1,
            "key": DB_FREE_FLAG,
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]}
        },
        {
            "id": 2,
            "key": PERSON_FLAG,
            "active": true,
            "deleted": false,
            "team_id": team.id,
            "filters": {"groups": [{
                "properties": [{"key": "email", "value": PERSON_EMAIL, "type": "person", "operator": "exact"}],
                "rollout_percentage": 100
            }]}
        }
    ]);
    insert_flags_for_team_in_redis(redis, team.id, Some(flags.to_string()))
        .await
        .unwrap();
    team.api_token
}

/// One global recorder per process, so each test compares how much a counter grew between two
/// reads, never its absolute value.
fn metrics() -> &'static Snapshotter {
    static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
    SNAPSHOTTER.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        recorder
            .install()
            .expect("no other global metrics recorder");
        snapshotter
    })
}

struct Counts {
    persons_connections: u64,
    connect_attempts: usize,
    degraded_persons_requests: u64,
    ok_persons_requests: u64,
}

fn counter(name: &str, labels: &[(&str, &str)]) -> u64 {
    metrics()
        .snapshot()
        .into_vec()
        .into_iter()
        .filter(|(key, ..)| {
            let key = key.key();
            key.name() == name
                && labels.iter().all(|(label, value)| {
                    key.labels()
                        .any(|l| l.key() == *label && l.value() == *value)
                })
        })
        .map(|(.., value)| match value {
            DebugValue::Counter(count) => count,
            other => panic!("{name} is not a counter: {other:?}"),
        })
        .sum()
}

fn persons_requests(outcome: &str) -> u64 {
    counter(
        "flags_request_outcome_total",
        &[("outcome", outcome), ("needs_persons", "true")],
    )
}

impl Counts {
    fn read(proxy: &PersonsDbProxy) -> Self {
        Self {
            persons_connections: counter(
                "db_connection_created_total",
                &[("pool", "persons_reader")],
            ),
            connect_attempts: proxy.accepted(),
            degraded_persons_requests: persons_requests("degraded"),
            ok_persons_requests: persons_requests("ok"),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RequestKind {
    BothFlags,
    /// Only the database-free flag, through `flag_keys`, to time database-free work alone.
    DbFreeOnly,
}

impl RequestKind {
    fn body(self, token: &str) -> String {
        match self {
            RequestKind::BothFlags => json!({"token": token, "distinct_id": DISTINCT_ID}),
            RequestKind::DbFreeOnly => {
                json!({"token": token, "distinct_id": DISTINCT_ID, "flag_keys": [DB_FREE_FLAG]})
            }
        }
        .to_string()
    }

    /// What every request of this kind answers while the persons DB is down.
    fn answer_during_fault(self) -> Answer {
        match self {
            RequestKind::BothFlags => Answer::PersonFlagFailed,
            RequestKind::DbFreeOnly => Answer::Healthy,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Answer {
    /// 200, and every requested flag evaluated.
    Healthy,
    /// 200, the database-free flag evaluated, and the person flag failed with
    /// `errorsWhileComputingFlags` set.
    PersonFlagFailed,
    Unexpected(String),
}

impl Answer {
    async fn read(kind: RequestKind, response: reqwest::Result<reqwest::Response>) -> Self {
        let response = match response {
            Ok(response) if response.status() == StatusCode::OK => response,
            Ok(response) => return Self::Unexpected(format!("HTTP {}", response.status())),
            Err(e) => return Self::Unexpected(e.to_string()),
        };
        let flags = match response.json::<FlagsResponse>().await {
            Ok(flags) => flags,
            Err(e) => return Self::Unexpected(e.to_string()),
        };
        let evaluated = |flag: &FlagDetails| flag.enabled && !flag.failed;
        let db_free = flags.flags.get(DB_FREE_FLAG);
        let person = flags.flags.get(PERSON_FLAG);
        let person_evaluated = match kind {
            RequestKind::BothFlags => person.is_some_and(evaluated),
            RequestKind::DbFreeOnly => person.is_none(),
        };
        match (db_free, person, flags.errors_while_computing_flags) {
            (Some(db_free), _, false) if evaluated(db_free) && person_evaluated => Self::Healthy,
            (Some(db_free), Some(person), true) if evaluated(db_free) && person.failed => {
                Self::PersonFlagFailed
            }
            (db_free, person, errors) => {
                Self::Unexpected(format!("{db_free:?} {person:?} errors={errors}"))
            }
        }
    }
}

struct Sample {
    kind: RequestKind,
    started: Instant,
    finished: Instant,
    answer: Answer,
}

/// When the first healthy request for both flags that started at or after `since` finished.
fn first_healthy_since(samples: &[Sample], since: Instant) -> Option<Instant> {
    samples
        .iter()
        .filter(|s| {
            s.kind == RequestKind::BothFlags && s.started >= since && s.answer == Answer::Healthy
        })
        .map(|s| s.finished)
        .min()
}

/// `clients` loop requests for both flags, and one more client loops database-free requests.
struct Load {
    samples: Arc<Mutex<Vec<Sample>>>,
    stop: CancellationToken,
    clients: Vec<JoinHandle<()>>,
}

impl Load {
    fn start(addr: SocketAddr, token: &str, clients: usize) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .unwrap();
        let url = format!("http://{addr}/flags?v=2");
        let samples: Arc<Mutex<Vec<Sample>>> = Arc::default();
        let stop = CancellationToken::new();
        let clients = std::iter::repeat_n(RequestKind::BothFlags, clients)
            .chain([RequestKind::DbFreeOnly])
            .map(|kind| {
                let (http, url, body) = (http.clone(), url.clone(), kind.body(token));
                let (samples, stop) = (samples.clone(), stop.clone());
                tokio::spawn(async move {
                    while !stop.is_cancelled() {
                        let started = Instant::now();
                        let response = http
                            .post(&url)
                            .header(CONTENT_TYPE, "application/json")
                            .body(body.clone())
                            .send()
                            .await;
                        let answer = Answer::read(kind, response).await;
                        samples.lock().unwrap().push(Sample {
                            kind,
                            started,
                            finished: Instant::now(),
                            answer,
                        });
                    }
                })
            })
            .collect();
        Self {
            samples,
            stop,
            clients,
        }
    }

    async fn wait_until_healthy(&self, since: Instant, limit: Duration) -> bool {
        while Instant::now() < since + limit {
            if first_healthy_since(&self.samples.lock().unwrap(), since).is_some() {
                return true;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        false
    }

    async fn stop(self) -> Vec<Sample> {
        self.stop.cancel();
        for client in self.clients {
            client.await.unwrap();
        }
        std::mem::take(&mut *self.samples.lock().unwrap())
    }
}

struct Report {
    topology: Topology,
    fault: Fault,
    fault_start: Instant,
    fault_end: Instant,
    samples: Vec<Sample>,
    at_start: Counts,
    at_end: Counts,
    at_finish: Counts,
}

impl Report {
    fn before(&self) -> impl Iterator<Item = &Sample> {
        self.samples
            .iter()
            .filter(|s| s.finished <= self.fault_start)
    }

    fn during(&self) -> impl Iterator<Item = &Sample> {
        self.samples
            .iter()
            .filter(|s| s.started >= self.fault_start && s.finished <= self.fault_end)
    }

    fn recovery(&self) -> Option<Duration> {
        first_healthy_since(&self.samples, self.fault_end).map(|finished| finished - self.fault_end)
    }

    fn connections_opened_during(&self) -> u64 {
        self.at_end.persons_connections - self.at_start.persons_connections
    }

    fn connections_opened_after(&self) -> u64 {
        self.at_finish.persons_connections - self.at_end.persons_connections
    }

    fn connect_attempts_during(&self) -> usize {
        self.at_end.connect_attempts - self.at_start.connect_attempts
    }

    fn connect_attempts_after(&self) -> usize {
        self.at_finish.connect_attempts - self.at_end.connect_attempts
    }

    fn print(&self) {
        let db_free = |s: &&Sample| s.kind == RequestKind::DbFreeOnly;
        let both_flags: Vec<_> = self
            .during()
            .filter(|s| s.kind == RequestKind::BothFlags)
            .collect();
        let failed = both_flags
            .iter()
            .filter(|s| s.answer == Answer::PersonFlagFailed)
            .count();
        println!(
            "{:?} for {:?}, {:?} topology",
            self.fault,
            self.fault_end - self.fault_start,
            self.topology
        );
        println!(
            "  database-free latency: before {}, during {}",
            latency_summary(self.before().filter(db_free)),
            latency_summary(self.during().filter(db_free))
        );
        println!(
            "  person flag failed in {failed} of {} requests during the fault",
            both_flags.len()
        );
        println!("  first success after the fault: {:?}", self.recovery());
        println!(
            "  persons_reader connections opened: {} during, {} after",
            self.connections_opened_during(),
            self.connections_opened_after()
        );
        println!(
            "  connect attempts at Postgres: {} during, {} after",
            self.connect_attempts_during(),
            self.connect_attempts_after()
        );
    }

    /// Holds today and after every later change to the persons data path.
    fn assert_degrades_then_recovers(&self) {
        let mut during = self.during().peekable();
        assert!(during.peek().is_some(), "no request ran inside the fault");
        for sample in during {
            assert_eq!(
                sample.answer,
                sample.kind.answer_during_fault(),
                "{:?} request {:?} into the fault",
                sample.kind,
                sample.started - self.fault_start
            );
        }

        let recovery = self.recovery();
        assert!(
            recovery.is_some_and(|recovery| recovery <= RECOVERY_LIMIT),
            "no success within {RECOVERY_LIMIT:?} of the fault ending: {recovery:?}"
        );

        assert!(
            self.at_end.degraded_persons_requests > self.at_start.degraded_persons_requests,
            "no degraded persons request counted during the fault"
        );
        assert!(
            self.at_finish.ok_persons_requests > self.at_end.ok_persons_requests,
            "no ok persons request counted after the fault"
        );
    }

    /// No new login reaches Postgres, because PgBouncer keeps its server connections.
    fn assert_server_connections_survive(&self) {
        assert_eq!(
            self.connect_attempts_during() + self.connect_attempts_after(),
            0,
            "PgBouncer opened new server connections"
        );
    }

    /// Logins at Postgres stay within twice PgBouncer's server connections, whatever the
    /// request rate. Straight to Postgres, a slow-connect fault makes about 100.
    fn assert_database_logins_bounded(&self) {
        let limit = 2 * (POOLER_READ_POOL_SIZE + POOLER_WRITE_POOL_SIZE) as usize;
        let logins = self.connect_attempts_during() + self.connect_attempts_after();
        assert!(
            logins <= limit,
            "{logins} connect attempts reached Postgres, more than {limit}"
        );
    }

    fn assert_connections_reopen(&self) {
        assert!(
            self.connections_opened_during() + self.connections_opened_after() > 0,
            "today the pool reopens persons connections; #122930 flips this"
        );
    }
}

fn latency_summary<'a>(samples: impl Iterator<Item = &'a Sample>) -> String {
    let mut latencies: Vec<Duration> = samples.map(|s| s.finished - s.started).collect();
    latencies.sort();
    match (latencies.get(latencies.len() / 2), latencies.last()) {
        (Some(p50), Some(max)) => {
            format!("p50 {p50:?}, max {max:?} over {} requests", latencies.len())
        }
        _ => "no requests".to_string(),
    }
}
