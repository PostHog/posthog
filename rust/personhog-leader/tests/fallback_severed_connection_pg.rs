use std::io;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use personhog_leader::cache::PersonCacheKey;
use personhog_leader::pg::{load_person_from_pg, LoadError};
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions, PgSslMode};
use tokio::net::{TcpListener, TcpStream};
use tokio::task::JoinHandle;

const KEY: PersonCacheKey = PersonCacheKey {
    team_id: 1,
    person_id: 7,
};

/// Closing its open connections is what pooled clients see when a pgbouncer pod leaves.
struct Pooler {
    addr: SocketAddr,
    links: Arc<Mutex<Vec<JoinHandle<()>>>>,
    hang_new: Arc<AtomicBool>,
}

impl Pooler {
    async fn start(upstream: String) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind failed");
        let addr = listener.local_addr().expect("no local addr");
        let links: Arc<Mutex<Vec<JoinHandle<()>>>> = Arc::default();
        let hang_new = Arc::new(AtomicBool::new(false));
        let (accepted, hang) = (links.clone(), hang_new.clone());
        tokio::spawn(async move {
            while let Ok((mut client, _)) = listener.accept().await {
                let upstream = upstream.clone();
                let hang = hang.load(Ordering::SeqCst);
                let link = tokio::spawn(async move {
                    if hang {
                        std::future::pending::<()>().await;
                    }
                    let mut server = TcpStream::connect(upstream).await.expect("upstream failed");
                    drop(tokio::io::copy_bidirectional(&mut client, &mut server).await);
                });
                accepted.lock().unwrap().push(link);
            }
        });
        Self {
            addr,
            links,
            hang_new,
        }
    }

    fn close_open_connections(&self) {
        for link in self.links.lock().unwrap().drain(..) {
            link.abort();
        }
    }
}

async fn seed_person(pool_opts: PgPoolOptions, connect_opts: PgConnectOptions) -> PgPool {
    let setup = pool_opts
        .connect_with(connect_opts)
        .await
        .expect("connect failed");
    sqlx::query(
        "CREATE TABLE person_probe (id bigint, team_id int, uuid uuid, properties jsonb, \
         created_at timestamptz, version bigint, is_identified bool, last_seen_at timestamptz, \
         is_deleted bool)",
    )
    .execute(&setup)
    .await
    .expect("create failed");
    sqlx::query(
        "INSERT INTO person_probe VALUES (7, 1, gen_random_uuid(), '{\"plan\":\"free\"}', now(), \
         3, true, NULL, false)",
    )
    .execute(&setup)
    .await
    .expect("insert failed");
    setup
}

/// Opens `size` connections through the pooler and waits until all of them sit idle. sqlx pings
/// a returned connection before it goes idle, and a close during that ping would replace it.
async fn warm_pool_behind(pooler: &Pooler, connect_opts: PgConnectOptions, size: u32) -> PgPool {
    let pool = PgPoolOptions::new()
        .max_connections(size)
        .acquire_timeout(Duration::from_secs(30))
        .test_before_acquire(false)
        .connect_lazy_with(
            connect_opts
                .host(&pooler.addr.ip().to_string())
                .port(pooler.addr.port())
                .ssl_mode(PgSslMode::Disable),
        );
    let mut held = Vec::new();
    for _ in 0..size {
        let mut conn = pool.acquire().await.expect("connect through pooler failed");
        sqlx::query("SELECT 1")
            .execute(&mut *conn)
            .await
            .expect("warm-up failed");
        held.push(conn);
    }
    drop(held);
    while pool.num_idle() < size as usize {
        tokio::task::yield_now().await;
    }
    pool
}

#[sqlx::test]
async fn a_load_after_its_pooler_closed_every_connection_succeeds(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let setup = seed_person(pool_opts, connect_opts.clone()).await;
    let upstream = format!("{}:{}", connect_opts.get_host(), connect_opts.get_port());
    let pooler = Pooler::start(upstream).await;
    let pool = warm_pool_behind(&pooler, connect_opts, 3).await;

    pooler.close_open_connections();

    let person = load_person_from_pg(&pool, "person_probe", &KEY)
        .await
        .expect("the load should retry on a live connection")
        .expect("the person exists");
    assert_eq!(person.version, 3);

    pool.close().await;
    setup.close().await;
}

#[sqlx::test]
async fn a_retry_that_reaches_no_live_connection_ends_at_the_query_deadline(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let setup = seed_person(pool_opts, connect_opts.clone()).await;
    let upstream = format!("{}:{}", connect_opts.get_host(), connect_opts.get_port());
    let pooler = Pooler::start(upstream).await;
    let pool = warm_pool_behind(&pooler, connect_opts, 1).await;

    pooler.hang_new.store(true, Ordering::SeqCst);
    pooler.close_open_connections();

    let err = load_person_from_pg(&pool, "person_probe", &KEY)
        .await
        .expect_err("no connection can answer");
    assert!(
        matches!(&err, LoadError::Query(sqlx::Error::Io(e)) if e.kind() == io::ErrorKind::TimedOut),
        "expected the deadline error, got {err:?}"
    );

    pooler.close_open_connections();
    pool.close().await;
    setup.close().await;
}
