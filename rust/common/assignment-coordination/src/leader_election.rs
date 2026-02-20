use std::future::Future;
use std::time::Duration;

use etcd_client::{Client, Compare, CompareOp, PutOptions, Txn, TxnOp};
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

use crate::error::{Error, Result};

#[derive(Debug, Clone)]
pub struct LeaderElectionConfig {
    /// Identifier for this candidate (e.g. pod name).
    pub name: String,
    /// etcd key where the leader record is stored.
    pub leader_key: String,
    /// TTL for the leader lease. If the leader dies, the key expires after this.
    pub lease_ttl: i64,
    /// How often to send keepalive pings.
    pub keepalive_interval: Duration,
    /// How long to wait before retrying after failing to acquire leadership.
    pub retry_interval: Duration,
}

/// Written to the leader key when leadership is acquired.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeaderRecord {
    pub holder: String,
    pub lease_id: i64,
}

/// Run a closure as leader indefinitely.
///
/// Continuously attempts to acquire leadership via etcd CAS. When elected,
/// runs `work_fn` with a cancellation token that is cancelled when leadership
/// is lost. If `work_fn` returns (leadership lost, error, or clean shutdown),
/// waits `retry_interval` and tries again.
///
/// The outer `cancel` token stops the entire election loop.
pub async fn run_as_leader<F, Fut>(
    client: Client,
    config: LeaderElectionConfig,
    cancel: CancellationToken,
    work_fn: F,
) -> Result<()>
where
    F: Fn(CancellationToken) -> Fut,
    Fut: Future<Output = Result<()>>,
{
    loop {
        tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            result = try_lead(&client, &config, &cancel, &work_fn) => {
                match result {
                    Ok(()) => {
                        tracing::info!(name = %config.name, "leadership ended normally");
                    }
                    Err(e) => {
                        tracing::warn!(name = %config.name, error = %e, "leader loop ended with error");
                    }
                }
                tokio::select! {
                    _ = cancel.cancelled() => return Ok(()),
                    _ = tokio::time::sleep(config.retry_interval) => {}
                }
            }
        }
    }
}

async fn try_lead<F, Fut>(
    client: &Client,
    config: &LeaderElectionConfig,
    cancel: &CancellationToken,
    work_fn: &F,
) -> Result<()>
where
    F: Fn(CancellationToken) -> Fut,
    Fut: Future<Output = Result<()>>,
{
    let lease_id = client
        .clone()
        .lease_grant(config.lease_ttl, None)
        .await?
        .id();

    let acquired = try_acquire(client, &config.leader_key, &config.name, lease_id).await?;
    if !acquired {
        tracing::debug!(name = %config.name, "another candidate is leader, standing by");
        // Best-effort revoke so the lease doesn't linger
        drop(client.clone().lease_revoke(lease_id).await);
        return Ok(());
    }

    tracing::info!(name = %config.name, "acquired leadership");

    // Keepalive runs until leadership_cancel is triggered
    let leadership_cancel = cancel.child_token();
    let keepalive_handle = {
        let client = client.clone();
        let interval = config.keepalive_interval;
        let token = leadership_cancel.clone();
        tokio::spawn(async move {
            if let Err(e) = run_lease_keepalive(client, lease_id, interval, token.clone()).await {
                tracing::error!(error = %e, "leader keepalive failed, cancelling leadership");
                token.cancel();
            }
        })
    };

    let result = work_fn(leadership_cancel.clone()).await;

    // Clean up
    leadership_cancel.cancel();
    drop(keepalive_handle.await);
    drop(client.clone().lease_revoke(lease_id).await);

    result
}

/// CAS: only succeed if the leader key does not exist (version == 0).
async fn try_acquire(client: &Client, key: &str, holder: &str, lease_id: i64) -> Result<bool> {
    let record = LeaderRecord {
        holder: holder.to_string(),
        lease_id,
    };
    let value = serde_json::to_vec(&record)?;

    let txn = Txn::new()
        .when(vec![Compare::version(key, CompareOp::Equal, 0)])
        .and_then(vec![TxnOp::put(
            key,
            value,
            Some(PutOptions::new().with_lease(lease_id)),
        )])
        .or_else(vec![TxnOp::get(key, None)]);

    let resp = client.clone().txn(txn).await?;
    Ok(resp.succeeded())
}

async fn run_lease_keepalive(
    mut client: Client,
    lease_id: i64,
    interval: Duration,
    cancel: CancellationToken,
) -> Result<()> {
    let (mut keeper, mut stream) = client.lease_keep_alive(lease_id).await?;

    loop {
        tokio::select! {
            _ = cancel.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {
                keeper.keep_alive().await?;
                if stream.message().await?.is_none() {
                    return Err(Error::LeadershipLost);
                }
            }
        }
    }
}

/// Read the current leader from etcd (if any).
pub async fn get_leader(client: &Client, key: &str) -> Result<Option<LeaderRecord>> {
    let resp = client.clone().get(key, None).await?;
    match resp.kvs().first() {
        Some(kv) => Ok(Some(serde_json::from_slice(kv.value())?)),
        None => Ok(None),
    }
}
