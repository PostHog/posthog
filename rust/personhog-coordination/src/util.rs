use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::error::{Error, Result};
use crate::store::PersonhogStore;

pub fn now_seconds() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
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
                if stream.message().await?.is_none() {
                    return Err(Error::leadership_lost());
                }
            }
        }
    }
}
