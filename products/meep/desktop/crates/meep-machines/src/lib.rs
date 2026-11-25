//! One owned connection per host-selected endpoint. A host can watch status or reconnect on wake.
use anyhow::Result;
use async_trait::async_trait;
use std::time::Duration;
use tokio::{
    sync::{mpsc, watch},
    task::JoinHandle,
    time::Instant,
};

#[cfg(unix)]
pub mod ssh;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Status {
    Connecting,
    Connected,
    Retrying { error: String, delay: Duration },
    Stopped,
}

/// Return only after the peer has authenticated. Dropping a pending connect must cancel it.
#[async_trait]
pub trait Connector: Send + Sync + 'static {
    async fn connect(&self) -> Result<Box<dyn Session>>;
}

#[async_trait]
pub trait Session: Send {
    /// Wait for the transport to close. The supervisor may cancel this wait.
    async fn closed(&mut self) -> Result<()>;
    /// Release the owned connection before a manual reconnect or shutdown.
    async fn disconnect(self: Box<Self>) -> Result<()>;
}

pub struct RetryPolicy {
    delays: Vec<Duration>,
    stable_after: Duration,
}

impl RetryPolicy {
    /// Failures advance through the schedule and repeat its last delay.
    pub fn new(delays: Vec<Duration>, stable_after: Duration) -> Result<Self> {
        anyhow::ensure!(
            !delays.is_empty() && delays.iter().all(|d| !d.is_zero()),
            "Supply at least one positive retry delay"
        );
        Ok(Self {
            delays,
            stable_after,
        })
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            delays: [1, 2, 5, 15, 30, 60, 120].map(Duration::from_secs).to_vec(),
            stable_after: Duration::from_secs(60),
        }
    }
}

pub struct Connection {
    wake: mpsc::Sender<()>,
    status: watch::Receiver<Status>,
    job: JoinHandle<Result<()>>,
}

impl Connection {
    /// Spawns on the current Tokio runtime. Dropping the handle signals shutdown.
    pub fn start(connector: impl Connector, retry: RetryPolicy) -> Self {
        let (wake, control) = mpsc::channel(1);
        let (state, status) = watch::channel(Status::Connecting);
        let job = tokio::spawn(async move {
            let result = supervise(connector, retry, &state, control).await;
            state.send_replace(Status::Stopped);
            result
        });
        Self { wake, status, job }
    }

    pub fn subscribe(&self) -> watch::Receiver<Status> {
        self.status.clone()
    }

    /// Interrupt a pending retry or replace the current session. Requests coalesce.
    pub fn reconnect(&self) {
        let _ = self.wake.try_send(());
    }

    pub async fn shutdown(self) -> Result<()> {
        drop(self.wake);
        self.job.await?
    }
}

async fn supervise(
    connector: impl Connector,
    retry: RetryPolicy,
    state: &watch::Sender<Status>,
    mut control: mpsc::Receiver<()>,
) -> Result<()> {
    let mut failures = 0;
    while !control.is_closed() {
        state.send_replace(Status::Connecting);
        let result = tokio::select! {
            biased;
            _ = control.recv() => { failures = 0; continue; }
            result = connector.connect() => result,
        };
        let error = match result {
            Err(error) => error,
            Ok(mut session) => {
                let since = Instant::now();
                state.send_replace(Status::Connected);
                let ended = tokio::select! {
                    biased;
                    request = control.recv() => {
                        let closed = session.disconnect().await;
                        if request.is_none() {
                            return closed;
                        }
                        if closed.is_ok() {
                            failures = 0;
                            continue;
                        }
                        closed
                    }
                    ended = session.closed() => ended,
                };
                if since.elapsed() >= retry.stable_after {
                    failures = 0;
                }
                ended
                    .err()
                    .unwrap_or_else(|| anyhow::anyhow!("Connection closed by peer"))
            }
        };
        let delay = retry.delays[failures];
        failures = (failures + 1).min(retry.delays.len() - 1);
        state.send_replace(Status::Retrying {
            error: format!("{error:#}"),
            delay,
        });
        tokio::select! {
            _ = control.recv() => failures = 0,
            _ = tokio::time::sleep(delay) => {}
        }
    }
    Ok(())
}
