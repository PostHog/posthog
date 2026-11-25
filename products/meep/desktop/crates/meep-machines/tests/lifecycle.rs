use anyhow::Result;
use async_trait::async_trait;
use meep_machines::{Connection, Connector, RetryPolicy, Session, Status};
use std::{
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};
use tokio::sync::{mpsc, oneshot, watch};

struct Driver(mpsc::UnboundedSender<oneshot::Sender<Result<Box<dyn Session>>>>);
#[async_trait]
impl Connector for Driver {
    async fn connect(&self) -> Result<Box<dyn Session>> {
        let (tx, rx) = oneshot::channel();
        self.0
            .send(tx)
            .map_err(|_| anyhow::anyhow!("fixture ended"))?;
        rx.await?
    }
}
struct Link {
    lost: oneshot::Receiver<()>,
    closed: Arc<AtomicUsize>,
}
#[async_trait]
impl Session for Link {
    async fn closed(&mut self) -> Result<()> {
        (&mut self.lost).await?;
        anyhow::bail!("peer disconnected")
    }
    async fn disconnect(self: Box<Self>) -> Result<()> {
        self.closed.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}
async fn at(status: &mut watch::Receiver<Status>, expected: Status) {
    status.wait_for(|s| *s == expected).await.unwrap();
}

#[tokio::test(start_paused = true)]
async fn recover_replace_and_stop() {
    let (tx, mut attempts) = mpsc::unbounded_channel();
    let c = Connection::start(Driver(tx), RetryPolicy::default());
    let mut status = c.subscribe();
    let closed = Arc::new(AtomicUsize::new(0));
    let (drop_peer, lost) = oneshot::channel();
    attempts
        .recv()
        .await
        .unwrap()
        .send(Ok(Box::new(Link {
            lost,
            closed: closed.clone(),
        })))
        .ok()
        .unwrap();
    at(&mut status, Status::Connected).await;
    drop_peer.send(()).unwrap();
    at(
        &mut status,
        Status::Retrying {
            error: "peer disconnected".into(),
            delay: Duration::from_secs(1),
        },
    )
    .await;
    tokio::time::advance(Duration::from_secs(1)).await;
    attempts
        .recv()
        .await
        .unwrap()
        .send(Err(anyhow::anyhow!("offline")))
        .ok()
        .unwrap();
    at(
        &mut status,
        Status::Retrying {
            error: "offline".into(),
            delay: Duration::from_secs(2),
        },
    )
    .await;
    c.reconnect();
    let (_alive, lost) = oneshot::channel();
    attempts
        .recv()
        .await
        .unwrap()
        .send(Ok(Box::new(Link {
            lost,
            closed: closed.clone(),
        })))
        .ok()
        .unwrap();
    at(&mut status, Status::Connected).await;
    c.reconnect();
    let pending = attempts.recv().await.unwrap();
    assert_eq!(closed.load(Ordering::SeqCst), 1);
    c.shutdown().await.unwrap();
    assert!(pending.is_closed());
    at(&mut status, Status::Stopped).await;
    assert!(attempts.recv().await.is_none());
}

#[tokio::test(start_paused = true)]
async fn drop_disconnects_a_live_peer() {
    let (tx, mut attempts) = mpsc::unbounded_channel();
    let c = Connection::start(Driver(tx), RetryPolicy::default());
    let mut status = c.subscribe();
    let closed = Arc::new(AtomicUsize::new(0));
    let (_alive, lost) = oneshot::channel();
    attempts
        .recv()
        .await
        .unwrap()
        .send(Ok(Box::new(Link {
            lost,
            closed: closed.clone(),
        })))
        .ok()
        .unwrap();
    at(&mut status, Status::Connected).await;
    drop(c);
    at(&mut status, Status::Stopped).await;
    assert_eq!(closed.load(Ordering::SeqCst), 1);
}

#[cfg(unix)]
#[test]
fn accepts_host_aliases_and_addresses_only() {
    use meep_machines::ssh::OpenSsh;
    for target in [
        "dev-box",
        "me@host",
        "ssh://user@[::1]:22",
        "ssh://host:2222",
        "ssh://host",
        "::1",
    ] {
        assert!(OpenSsh::new(target).is_ok());
    }
    for target in [
        "",
        "-Ffoo",
        "ssh://host:0",
        "host name",
        "user@host\ncommand",
    ] {
        assert!(OpenSsh::new(target).is_err());
    }
}

#[tokio::test(start_paused = true)]
async fn a_failed_disconnect_does_not_disable_reconnects() {
    struct FailedClose;
    #[async_trait]
    impl Session for FailedClose {
        async fn closed(&mut self) -> Result<()> {
            std::future::pending().await
        }
        async fn disconnect(self: Box<Self>) -> Result<()> {
            anyhow::bail!("close failed")
        }
    }
    let (tx, mut attempts) = mpsc::unbounded_channel();
    let connection = Connection::start(Driver(tx), RetryPolicy::default());
    let mut status = connection.subscribe();
    assert!(
        attempts
            .recv()
            .await
            .unwrap()
            .send(Ok(Box::new(FailedClose)))
            .is_ok()
    );
    at(&mut status, Status::Connected).await;
    connection.reconnect();
    at(
        &mut status,
        Status::Retrying {
            error: "close failed".into(),
            delay: Duration::from_secs(1),
        },
    )
    .await;
    tokio::time::advance(Duration::from_secs(1)).await;
    let pending = attempts.recv().await.unwrap();
    connection.shutdown().await.unwrap();
    assert!(pending.is_closed());
}
