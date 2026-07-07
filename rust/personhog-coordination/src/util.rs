use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tokio_util::sync::CancellationToken;

pub use assignment_coordination::util::now_seconds;

use crate::error::{Error, Result};
use crate::store::PersonhogStore;

/// Generate a handoff id unique across handoff attempts. Milliseconds
/// alone can collide when a handoff is cancelled and recreated within the
/// same instant, so a process-local sequence number disambiguates; across
/// coordinator failovers the leader election guarantees non-overlapping
/// creation windows.
pub fn new_handoff_id() -> String {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("{}-{}", millis, SEQ.fetch_add(1, Ordering::Relaxed))
}

pub async fn run_lease_keepalive(
    store: Arc<PersonhogStore>,
    lease_id: i64,
    interval: Duration,
    cancel: CancellationToken,
) -> Result<()> {
    let (mut keeper, mut stream) = store.keep_alive(lease_id).await?;

    loop {
        tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {
                keeper.keep_alive().await?;
                match stream.message().await? {
                    None => return Err(Error::leadership_lost()),
                    // etcd answers keepalives for a revoked or expired
                    // lease with a normal response carrying TTL 0 — the
                    // stream stays open, so stream-end alone never
                    // detects lease loss.
                    Some(resp) if resp.ttl() <= 0 => return Err(Error::leadership_lost()),
                    Some(_) => {}
                }
            }
        }
    }
}
