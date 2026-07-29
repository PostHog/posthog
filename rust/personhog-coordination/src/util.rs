use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub use assignment_coordination::util::{now_millis, now_seconds};

use crate::error::{Error, Result};
use crate::store::PersonhogStore;

/// Generate a handoff id unique across handoff attempts. The uuid makes
/// uniqueness structural — ids cannot collide across coordinator
/// failovers even if the wall clock steps backward — while the millis
/// prefix keeps ids sortable and debuggable.
pub fn new_handoff_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("{}-{}", millis, Uuid::new_v4())
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
                // Each round is deadline-bounded: a silent network
                // partition black-holes packets without erroring the
                // stream, so an unbounded await here would leave the
                // component serving while its lease expires server-side.
                // A round that cannot confirm renewal within one interval
                // is therefore treated as lease loss — with the interval
                // at a third of the TTL, detection lands at worst two
                // thirds of the way in, leaving the final third for the
                // self-fence.
                let round = async {
                    keeper.keep_alive().await?;
                    match stream.message().await? {
                        None => Err(Error::leadership_lost()),
                        // etcd answers keepalives for a revoked or expired
                        // lease with a normal response carrying TTL 0 — the
                        // stream stays open, so stream-end alone never
                        // detects lease loss.
                        Some(resp) if resp.ttl() <= 0 => Err(Error::leadership_lost()),
                        Some(_) => Ok(()),
                    }
                };
                match tokio::time::timeout(interval, round).await {
                    Ok(result) => result?,
                    Err(_) => {
                        return Err(Error::invalid_state(format!(
                            "lease keepalive round unanswered within {interval:?}; treating as lease loss"
                        )));
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::new_handoff_id;

    /// Quorum correlation and cancellation detection hang off id
    /// uniqueness; ids minted in the same instant (a handoff cancelled
    /// and recreated within one millisecond) must never collide.
    #[test]
    fn new_handoff_id_is_unique_within_same_instant() {
        let ids: HashSet<String> = (0..1000).map(|_| new_handoff_id()).collect();
        assert_eq!(ids.len(), 1000);
    }
}
