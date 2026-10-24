#![allow(dead_code)]

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use anyhow::Result;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::watch;
use url::Url;

#[derive(Clone, Copy, Default)]
struct Faults {
    freeze_needle: Option<&'static [u8]>,
    frozen: bool,
    /// Connections with an ID below this value get no replies from Postgres.
    hold_replies_below: u64,
    stall_new_connections: bool,
}

/// A TCP proxy in front of the test persons database. Each fault keeps every socket open, so the
/// client sees a database that has stopped answering, not a closed connection. `resume` clears all
/// faults, and held traffic then continues.
pub struct PersonsDbProxy {
    url: String,
    faults: Arc<watch::Sender<Faults>>,
    connections_opened: Arc<AtomicU64>,
}

impl PersonsDbProxy {
    pub async fn start() -> Result<Self> {
        let mut url = Url::parse(&DEFAULT_TEST_CONFIG.persons_read_database_url)?;
        let upstream = format!(
            "{}:{}",
            url.host_str().expect("the persons database URL has a host"),
            url.port().unwrap_or(5432)
        );
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let proxy_port = listener.local_addr()?.port();
        let faults = Arc::new(watch::Sender::new(Faults::default()));
        let connections_opened = Arc::new(AtomicU64::new(0));

        tokio::spawn({
            let faults = faults.clone();
            let connections_opened = connections_opened.clone();
            async move {
                while let Ok((client, _)) = listener.accept().await {
                    let id = connections_opened.fetch_add(1, Ordering::SeqCst);
                    let stalled = faults.borrow().stall_new_connections;
                    tokio::spawn(proxy_connection(
                        client,
                        upstream.clone(),
                        id,
                        stalled,
                        faults.clone(),
                    ));
                }
            }
        });

        url.set_host(Some("127.0.0.1"))?;
        url.set_port(Some(proxy_port))
            .expect("a postgres URL accepts a port");
        // The proxy matches query bytes in plaintext, so the connection must not use TLS.
        url.query_pairs_mut().append_pair("sslmode", "disable");
        Ok(Self {
            url: url.to_string(),
            faults,
            connections_opened,
        })
    }

    pub fn url(&self) -> String {
        self.url.clone()
    }

    /// When a client sends bytes that contain `needle`, the proxy sends nothing more to Postgres
    /// on any connection. Postgres never receives the frozen query. Its statement timeout
    /// therefore cannot end the query.
    pub fn freeze_on_query_containing(&self, needle: &'static [u8]) {
        self.faults.send_modify(|f| f.freeze_needle = Some(needle));
    }

    /// Postgres replies on the connections that are open now reach the client only after
    /// `resume`. Connections that open later are not affected.
    pub fn hold_replies_on_open_connections(&self) {
        let opened = self.connections_opened.load(Ordering::SeqCst);
        self.faults.send_modify(|f| f.hold_replies_below = opened);
    }

    /// The proxy accepts new connections but connects them to Postgres only after `resume`. The
    /// client therefore cannot finish its connection handshake. Open connections are not affected.
    pub fn stall_new_connections(&self) {
        self.faults.send_modify(|f| f.stall_new_connections = true);
    }

    pub fn resume(&self) {
        self.faults.send_replace(Faults::default());
    }
}

async fn proxy_connection(
    client: TcpStream,
    upstream: String,
    id: u64,
    stalled: bool,
    faults: Arc<watch::Sender<Faults>>,
) {
    if stalled {
        let mut changes = faults.subscribe();
        if changes
            .wait_for(|f| !f.stall_new_connections)
            .await
            .is_err()
        {
            return;
        }
    }
    let Ok(server) = TcpStream::connect(&upstream).await else {
        return;
    };
    let (client_reader, client_writer) = client.into_split();
    let (server_reader, server_writer) = server.into_split();
    tokio::spawn(forward_replies(
        server_reader,
        client_writer,
        id,
        faults.subscribe(),
    ));
    forward_queries(client_reader, server_writer, &faults).await;
}

async fn forward_queries(
    mut from: OwnedReadHalf,
    mut to: OwnedWriteHalf,
    faults: &watch::Sender<Faults>,
) {
    let mut changes = faults.subscribe();
    let mut buf = vec![0; 16 * 1024];
    // Keeps the end of the previous read so that a needle split across two reads still matches.
    let mut window = Vec::new();
    loop {
        let n = match from.read(&mut buf).await {
            Ok(0) | Err(_) => return,
            Ok(n) => n,
        };
        let needle = faults.borrow().freeze_needle;
        if let Some(needle) = needle {
            window.extend_from_slice(&buf[..n]);
            if window.windows(needle.len()).any(|w| w == needle) {
                faults.send_modify(|f| f.frozen = true);
            }
            window.drain(..window.len().saturating_sub(needle.len() - 1));
        } else {
            window.clear();
        }
        if changes.wait_for(|f| !f.frozen).await.is_err() {
            return;
        }
        if to.write_all(&buf[..n]).await.is_err() {
            return;
        }
    }
}

async fn forward_replies(
    mut from: OwnedReadHalf,
    mut to: OwnedWriteHalf,
    id: u64,
    mut faults: watch::Receiver<Faults>,
) {
    let mut buf = vec![0; 16 * 1024];
    loop {
        let n = match from.read(&mut buf).await {
            Ok(0) | Err(_) => return,
            Ok(n) => n,
        };
        if faults
            .wait_for(|f| id >= f.hold_replies_below)
            .await
            .is_err()
        {
            return;
        }
        if to.write_all(&buf[..n]).await.is_err() {
            return;
        }
    }
}
