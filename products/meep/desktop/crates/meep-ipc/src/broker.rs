//! Bounded local request admission. The host implements authorization and dispatch.
use anyhow::{Context, Result, bail};
use meep_protocol::Rpc;
use serde_json::json;
use std::{sync::Arc, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWriteExt, BufReader},
    net::UnixStream,
};

/// The product supplies session ownership and dispatch after transport admission.
#[async_trait::async_trait]
pub trait RpcService: Send + Sync + 'static {
    fn authorize_session(&self, rpc: &Rpc) -> Result<()>;
    async fn handle(self: Arc<Self>, stream: UnixStream, token: &str, rpc: Rpc) -> Result<()>;
}

pub fn authenticated(expected: &str, supplied: Option<&str>) -> bool {
    let Some(supplied) = supplied else {
        return false;
    };
    expected.len() == 64 && same_secret(expected, supplied)
}

/// Whether two secrets are equal, in time that depends only on their length.
pub fn same_secret(expected: &str, supplied: &str) -> bool {
    use subtle::ConstantTimeEq;
    bool::from(expected.as_bytes().ct_eq(supplied.as_bytes()))
}

use crate::socket::caller_closed;

/// Maximum encoded request frame, including its newline.
pub const MAX_RPC_BYTES: usize = 256_000;
pub const BUSY_REPLY: &[u8] =
    b"{\"error\":\"Service is busy. Wait for a request to finish and try again.\"}\n";

/// Give overloaded callers the standard JSON error.
#[derive(Default)]
pub struct BusyReplies(crate::socket::BusyReplies);

impl BusyReplies {
    pub fn reject(&mut self, stream: UnixStream) {
        self.0.reject(stream, BUSY_REPLY);
    }
}

pub struct RpcConnections {
    pending: tokio::task::JoinSet<()>,
    reading: Arc<tokio::sync::Semaphore>,
    rejections: BusyReplies,
    sessions: Arc<tokio::sync::Semaphore>,
}

impl Default for RpcConnections {
    fn default() -> Self {
        Self::new(256, 64)
    }
}
impl RpcConnections {
    pub fn new(readers: usize, sessions: usize) -> Self {
        Self {
            pending: tokio::task::JoinSet::new(),
            // Each linked stream can be awaiting its first request at once.
            // Another link's calls may be refused, but never evict a reader.
            reading: Arc::new(tokio::sync::Semaphore::new(readers)),
            rejections: BusyReplies::default(),
            sessions: Arc::new(tokio::sync::Semaphore::new(sessions)),
        }
    }
}

impl RpcConnections {
    pub async fn join_next(&mut self) -> Option<Result<(), tokio::task::JoinError>> {
        self.pending.join_next().await
    }
    pub fn accept(
        &mut self,
        core: Arc<impl RpcService>,
        mut stream: UnixStream,
        token: Arc<String>,
    ) {
        let Ok(reading) = self.reading.clone().try_acquire_owned() else {
            self.rejections.reject(stream);
            return;
        };
        let sessions = self.sessions.clone();
        self.pending.spawn(async move {
            let admitted = async {
                let rpc = read_rpc(&mut stream).await?;
                if caller_closed(&stream) {
                    return Ok(None);
                }
                let slot = if rpc.session_token.is_some() {
                    core.authorize_session(&rpc)?;
                    Some(sessions.try_acquire_owned().context(
                        "Too many session requests; wait for a request to finish and retry",
                    )?)
                } else {
                    if !authenticated(&token, rpc.params["_host_auth"].as_str()) {
                        bail!("Host authentication required");
                    }
                    None
                };
                anyhow::Ok(Some((rpc, slot)))
            }
            .await;
            drop(reading);
            match admitted {
                Ok(Some((rpc, slot))) => {
                    // Watches and in-flight calls no longer occupy admission slots.
                    tokio::spawn(async move {
                        let _slot = slot;
                        if let Err(error) = core.handle(stream, &token, rpc).await {
                            eprintln!("IPC: {error}");
                        }
                    });
                }
                Ok(None) => {}
                Err(error) => {
                    let reply = format!("{}\n", json!({"error":error.to_string()}));
                    if let Err(error) = tokio::time::timeout(
                        Duration::from_secs(1),
                        stream.write_all(reply.as_bytes()),
                    )
                    .await
                    .map_err(std::io::Error::from)
                    .and_then(|sent| sent)
                    {
                        eprintln!("Could not send the request error: {error}");
                    }
                }
            }
        });
    }
}

pub async fn read_rpc(read: impl AsyncRead + Unpin) -> Result<Rpc> {
    let mut bytes = Vec::new();
    let mut input = BufReader::new(read.take((MAX_RPC_BYTES + 1) as u64));
    tokio::time::timeout(Duration::from_secs(5), input.read_until(b'\n', &mut bytes)).await??;
    anyhow::ensure!(
        bytes.len() <= MAX_RPC_BYTES && bytes.last() == Some(&b'\n'),
        "Invalid local request frame"
    );
    Ok(serde_json::from_slice(&bytes)?)
}

#[cfg(test)]
mod credential_tests {
    use super::*;
    #[test]
    fn host_auth_requires_the_entire_expected_credential() {
        let key = "a".repeat(64);
        let different = format!("{}b", &key[..63]);
        assert!(authenticated(&key, Some(&key)));
        for supplied in [None, Some(&key[..63]), Some(different.as_str())] {
            assert!(!authenticated(&key, supplied));
        }
        assert!(!authenticated("", Some("")));
    }
}
