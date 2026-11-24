use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use personhog_leader::cache::PersonCacheKey;
use personhog_leader::pg::load_person_from_pg;
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use tokio::net::{TcpListener, TcpStream};
use tokio::task::JoinHandle;

/// Forwards to Postgres and can close every open connection while still accepting new ones,
/// the way clients see a pgbouncer pod leave its Service.
struct Pooler {
    addr: SocketAddr,
    links: Arc<Mutex<Vec<JoinHandle<()>>>>,
}

impl Pooler {
    async fn start(upstream: String) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind failed");
        let addr = listener.local_addr().expect("no local addr");
        let links: Arc<Mutex<Vec<JoinHandle<()>>>> = Arc::default();
        let accepted = links.clone();
        tokio::spawn(async move {
            while let Ok((mut client, _)) = listener.accept().await {
                let upstream = upstream.clone();
                let link = tokio::spawn(async move {
                    let mut server = TcpStream::connect(upstream).await.expect("upstream failed");
                    drop(tokio::io::copy_bidirectional(&mut client, &mut server).await);
                });
                accepted.lock().unwrap().push(link);
            }
        });
        Self { addr, links }
    }

    fn close_open_connections(&self) {
        for link in self.links.lock().unwrap().drain(..) {
            link.abort();
        }
    }
}

#[sqlx::test]
async fn a_load_on_a_connection_its_pooler_closed_succeeds(
    pool_opts: PgPoolOptions,
    connect_opts: PgConnectOptions,
) {
    let setup = pool_opts
        .connect_with(connect_opts.clone())
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

    let upstream = format!("{}:{}", connect_opts.get_host(), connect_opts.get_port());
    let pooler = Pooler::start(upstream).await;
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .test_before_acquire(false)
        .connect_with(
            connect_opts
                .host(&pooler.addr.ip().to_string())
                .port(pooler.addr.port())
                .ssl_mode(sqlx::postgres::PgSslMode::Disable),
        )
        .await
        .expect("connect through pooler failed");
    let key = PersonCacheKey {
        team_id: 1,
        person_id: 7,
    };
    load_person_from_pg(&pool, "person_probe", &key)
        .await
        .expect("warm-up load failed");
    while pool.num_idle() == 0 {
        tokio::task::yield_now().await;
    }

    pooler.close_open_connections();

    let person = load_person_from_pg(&pool, "person_probe", &key)
        .await
        .expect("the load should retry on a fresh connection")
        .expect("the person exists");
    assert_eq!(person.version, 3);

    pool.close().await;
    setup.close().await;
}
