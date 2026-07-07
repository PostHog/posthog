use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

pub use assignment_coordination::util::now_seconds;

use crate::error::{Error, Result};
use crate::store::PersonhogStore;

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
