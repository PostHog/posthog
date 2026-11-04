//! Persons DB faults under steady load, with production pool and timeout settings, except the
//! longer persons statement timeout that `Fault::LockWait` needs.
//! Ignored because the faults lock `posthog_person` and would stall other tests: run alone with
//! `cargo nextest run -p feature-flags -E 'binary(stall_recovery)' --run-ignored only --test-threads=1`.

pub mod common;
#[path = "stall_recovery/persons_db_proxy.rs"]
mod persons_db_proxy;

use std::net::SocketAddr;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use feature_flags::api::types::{FlagDetails, FlagsResponse};
use feature_flags::config::{Config, FlexBool, DEFAULT_TEST_CONFIG};
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use reqwest::{header::CONTENT_TYPE, StatusCode};
use serde_json::json;
use sqlx::{Connection, PgConnection};
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use common::ServerHandle;
use persons_db_proxy::PersonsDbProxy;

const DB_FREE_FLAG: &str = "db-free";
const PERSON_FLAG: &str = "person";
const DISTINCT_ID: &str = "stall_user";
const PERSON_EMAIL: &str = "stall@example.com";

const BASELINE: Duration = Duration::from_secs(3);
const RECOVERY_LIMIT: Duration = Duration::from_secs(10);
/// Load continues this long after recovery, so connections reopened after the fault show.
const SETTLE: Duration = Duration::from_secs(5);
/// Longer than the 3 s acquire timeout.
const SLOW_CONNECT: Duration = Duration::from_secs(5);

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "locks posthog_person, which stalls other tests"]
async fn test_cancels_heard_late_for_16s() {
    let report = Scenario::new(Fault::CancelsHeardLate, Duration::from_secs(16))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    report.assert_connections_reopen();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "locks posthog_person, which stalls other tests"]
async fn test_cancels_heard_late_for_30s() {
    let report = Scenario::new(Fault::CancelsHeardLate, Duration::from_secs(30))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    report.assert_connections_reopen();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "locks posthog_person, which stalls other tests"]
async fn test_lock_wait_for_16s() {
    let report = Scenario::new(Fault::LockWait, Duration::from_secs(16))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    report.assert_connections_reopen();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_connects_slower_than_the_acquire_timeout_for_16s() {
    let report = Scenario::new(Fault::SlowConnects, Duration::from_secs(16))
        .run()
        .await;
    report.assert_degrades_then_recovers();
    assert!(
        report.connect_attempts_during() > 0,
        "the pool made no connect attempt during the fault"
    );
    assert_eq!(
        report.connections_opened_during(),
        0,
        "today no connect succeeds during the fault; #122930 and #122931 change this"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "timing-sensitive, so it runs alone"]
async fn test_request_timeout_counts_as_an_error_that_needed_persons() {
    let proxy = PersonsDbProxy::start(&DEFAULT_TEST_CONFIG.persons_read_database_url).await;
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
enum Fault {
    /// Postgres cancels person queries on time, and the proxy holds the cancels until the end.
    CancelsHeardLate,
    /// Person queries wait on a lock past the persons DB deadline, and Postgres cancels them on time.
    LockWait,
    /// Every new connection takes longer than the acquire timeout.
    SlowConnects,
}

impl Fault {
    fn persons_statement_timeout_ms(self) -> u64 {
        match self {
            // Between the 3.5 s persons DB deadline and the lock.
            Fault::LockWait => 5_000,
            Fault::CancelsHeardLate | Fault::SlowConnects => 1_000,
        }
    }

    /// Returns when the fault took effect.
    async fn inject(self, proxy: &PersonsDbProxy, admin: &mut PgConnection) -> Instant {
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
        }
    }

    async fn lift(self, proxy: &PersonsDbProxy, admin: &mut PgConnection) {
        match self {
            Fault::CancelsHeardLate => {
                unlock_person_table(admin).await;
                proxy.release_replies();
            }
            Fault::LockWait => unlock_person_table(admin).await,
            Fault::SlowConnects => proxy.delay_connects(Duration::ZERO),
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
    fault: Fault,
    fault_length: Duration,
    clients: usize,
    max_concurrency: usize,
}

impl Scenario {
    fn new(fault: Fault, fault_length: Duration) -> Self {
        Self {
            fault,
            fault_length,
            clients: 20,
            max_concurrency: 100,
        }
    }

    fn server_config(&self, persons_url: &str) -> Config {
        Config {
            acquire_timeout_secs: 3,
            persons_db_deadline_ms: 3_500,
            persons_db_deadline_reserve_ms: 500,
            request_timeout_ms: 4_500,
            max_pg_connections: 8,
            max_concurrency: self.max_concurrency,
            persons_reader_statement_timeout_ms: self.fault.persons_statement_timeout_ms(),
            test_before_acquire: FlexBool(true),
            persons_read_database_url: persons_url.to_string(),
            persons_write_database_url: persons_url.to_string(),
            ..Config::default_test_config()
        }
    }

    async fn run(&self) -> Report {
        let persons_url = &DEFAULT_TEST_CONFIG.persons_read_database_url;
        let proxy = PersonsDbProxy::start(persons_url).await;
        let mut admin = PgConnection::connect(persons_url).await.unwrap();
        let token = seed().await;
        let server = ServerHandle::for_config(self.server_config(proxy.url())).await;
        server.wait_until_ready().await;

        let load = Load::start(server.addr, &token, self.clients);
        assert!(
            load.wait_until_healthy(Instant::now(), RECOVERY_LIMIT)
                .await,
            "no healthy answer before the fault"
        );
        tokio::time::sleep(BASELINE).await;

        let at_start = Counts::read(&proxy);
        let fault_start = self.fault.inject(&proxy, &mut admin).await;
        tokio::time::sleep_until(fault_start + self.fault_length).await;
        let at_end = Counts::read(&proxy);
        let fault_end = Instant::now();
        self.fault.lift(&proxy, &mut admin).await;

        load.wait_until_healthy(fault_end, RECOVERY_LIMIT).await;
        tokio::time::sleep(SETTLE).await;
        let at_finish = Counts::read(&proxy);

        let report = Report {
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
            "{:?} for {:?}",
            self.fault,
            self.fault_end - self.fault_start
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
            "  connect attempts at the proxy: {} during, {} after",
            self.connect_attempts_during(),
            self.at_finish.connect_attempts - self.at_end.connect_attempts
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
