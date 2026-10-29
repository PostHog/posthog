//! A TCP proxy between the persons pools and Postgres that injects the faults of a persons DB
//! stall.

use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{
    tcp::{OwnedReadHalf, OwnedWriteHalf},
    TcpListener, TcpStream,
};
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use url::Url;

#[derive(Clone, Copy, Default)]
struct Faults {
    hold_replies: bool,
    connect_delay: Duration,
}

pub struct PersonsDbProxy {
    url: String,
    faults: watch::Sender<Faults>,
    accepted: Arc<AtomicUsize>,
    open_connections: Arc<Mutex<CancellationToken>>,
    accept_loop: JoinHandle<()>,
}

impl PersonsDbProxy {
    /// Proxies the Postgres server of `database_url`. [`Self::url`] reaches the same database
    /// through the proxy.
    pub async fn start(database_url: &str) -> Self {
        let mut url = Url::parse(database_url).expect("valid database URL");
        let upstream = (
            url.host_str().expect("database URL has a host").to_string(),
            url.port().unwrap_or(5432),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        url.set_host(Some("127.0.0.1")).unwrap();
        url.set_port(Some(listener.local_addr().unwrap().port()))
            .unwrap();

        let (faults, faults_rx) = watch::channel(Faults::default());
        let accepted = Arc::new(AtomicUsize::new(0));
        let open_connections = Arc::new(Mutex::new(CancellationToken::new()));
        let accept_loop = tokio::spawn(accept(
            listener,
            upstream,
            faults_rx,
            accepted.clone(),
            open_connections.clone(),
        ));

        Self {
            url: url.to_string(),
            faults,
            accepted,
            open_connections,
            accept_loop,
        }
    }

    pub fn url(&self) -> &str {
        &self.url
    }

    /// Connections the proxy accepted, which counts connect attempts whether they succeed or not.
    pub fn accepted(&self) -> usize {
        self.accepted.load(Ordering::Relaxed)
    }

    /// Holds every server-to-client byte, on open and new connections alike, until
    /// [`Self::release_replies`].
    pub fn hold_replies(&self) {
        self.faults.send_modify(|faults| faults.hold_replies = true);
    }

    pub fn release_replies(&self) {
        self.faults
            .send_modify(|faults| faults.hold_replies = false);
    }

    /// Waits this long before connecting each newly accepted connection to Postgres.
    pub fn delay_connects(&self, delay: Duration) {
        self.faults
            .send_modify(|faults| faults.connect_delay = delay);
    }

    pub fn close_connections(&self) {
        let mut open = self.open_connections.lock().unwrap();
        open.cancel();
        *open = CancellationToken::new();
    }
}

impl Drop for PersonsDbProxy {
    fn drop(&mut self) {
        self.accept_loop.abort();
        self.close_connections();
    }
}

async fn accept(
    listener: TcpListener,
    upstream: (String, u16),
    faults: watch::Receiver<Faults>,
    accepted: Arc<AtomicUsize>,
    open_connections: Arc<Mutex<CancellationToken>>,
) {
    while let Ok((client, _)) = listener.accept().await {
        accepted.fetch_add(1, Ordering::Relaxed);
        let connect_delay = faults.borrow().connect_delay;
        let closed = open_connections.lock().unwrap().clone();
        let relay = relay(client, upstream.clone(), connect_delay, faults.clone());
        tokio::spawn(async move {
            tokio::select! {
                _ = closed.cancelled() => {}
                _ = relay => {}
            }
        });
    }
}

async fn relay(
    client: TcpStream,
    (host, port): (String, u16),
    connect_delay: Duration,
    faults: watch::Receiver<Faults>,
) {
    tokio::time::sleep(connect_delay).await;
    let Ok(server) = TcpStream::connect((host.as_str(), port)).await else {
        return;
    };
    let (mut client_read, client_write) = client.into_split();
    let (server_read, mut server_write) = server.into_split();
    tokio::select! {
        _ = tokio::io::copy(&mut client_read, &mut server_write) => {}
        _ = forward_replies(server_read, client_write, faults) => {}
    }
}

async fn forward_replies(
    mut server: OwnedReadHalf,
    mut client: OwnedWriteHalf,
    mut faults: watch::Receiver<Faults>,
) -> std::io::Result<()> {
    let mut buf = vec![0; 16 * 1024];
    loop {
        let read = server.read(&mut buf).await?;
        if read == 0 {
            return Ok(());
        }
        if faults
            .wait_for(|faults| !faults.hold_replies)
            .await
            .is_err()
        {
            return Ok(());
        }
        client.write_all(&buf[..read]).await?;
    }
}
