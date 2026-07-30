use anyhow::{bail, Context, Result};
use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_coordination::store::PersonhogStore;

pub async fn connect(endpoints: &str, prefix: &str) -> Result<PersonhogStore> {
    let config = StoreConfig {
        endpoints: endpoints.split(',').map(str::to_string).collect(),
        prefix: prefix.to_string(),
    };
    let store = EtcdStore::connect(config)
        .await
        .context("connecting to etcd")?;
    Ok(PersonhogStore::new(store))
}

/// Wipe all coordination state under the harness prefix and set the
/// partition count, giving each run a clean slate.
pub async fn reset(store: &PersonhogStore, partitions: u32) -> Result<()> {
    store.delete_all().await.context("clearing etcd prefix")?;
    store
        .set_total_partitions(partitions)
        .await
        .context("setting total_partitions")?;
    Ok(())
}

/// Revoke the etcd lease attached to a pod's registration. Deleting the key
/// through the lease makes the coordinator detect the pod's death
/// immediately instead of waiting out the lease TTL — the "fast" half of a
/// kill.
pub async fn revoke_pod_lease(store: &PersonhogStore, pod_name: &str) -> Result<()> {
    revoke_registration_lease(store, &format!("pods/{pod_name}")).await
}

/// Revoke the lease attached to a router's registration, so the coordinator
/// stops counting the dead router toward freeze-ack quorums immediately.
pub async fn revoke_router_lease(store: &PersonhogStore, router_name: &str) -> Result<()> {
    revoke_registration_lease(store, &format!("routers/{router_name}")).await
}

/// If `holder` currently holds the coordinator election, revoke the
/// election lease so a surviving router can win immediately. Without this
/// a killed coordinator blocks the election for the full lease TTL (15s by
/// default), during which no handoffs can be created at all.
pub async fn revoke_coordinator_lease_if_held_by(
    store: &PersonhogStore,
    holder: &str,
) -> Result<bool> {
    let Some(leader) = store
        .get_leader()
        .await
        .context("reading coordinator election key")?
    else {
        return Ok(false);
    };
    if leader.holder != holder {
        return Ok(false);
    }

    store
        .inner()
        .client()
        .clone()
        .lease_revoke(leader.lease_id)
        .await
        .context("revoking coordinator election lease")?;
    tracing::info!(
        holder,
        lease_id = leader.lease_id,
        "revoked coordinator election lease"
    );
    Ok(true)
}

/// Wait until `holder` owns the coordinator election. Used at bring-up so
/// chaos that targets "the coordinator" is deterministic instead of
/// depending on which router won the initial campaign.
pub async fn wait_for_leader(
    store: &PersonhogStore,
    holder: &str,
    deadline: std::time::Duration,
) -> Result<()> {
    let start = std::time::Instant::now();
    loop {
        if let Some(leader) = store.get_leader().await.unwrap_or(None) {
            if leader.holder == holder {
                return Ok(());
            }
        }
        if start.elapsed() > deadline {
            bail!("{holder} did not acquire coordinator leadership within {deadline:?}");
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
}

async fn revoke_registration_lease(store: &PersonhogStore, key_suffix: &str) -> Result<()> {
    let prefix = store.inner().prefix();
    let key = format!("{prefix}{key_suffix}");

    let resp = store
        .inner()
        .client()
        .clone()
        .get(key.clone(), None)
        .await
        .context("reading registration key from etcd")?;

    let kv = resp
        .kvs()
        .first()
        .with_context(|| format!("{key} not registered in etcd"))?;

    let lease_id = kv.lease();
    if lease_id == 0 {
        bail!("{key} has no lease attached");
    }

    store
        .inner()
        .client()
        .clone()
        .lease_revoke(lease_id)
        .await
        .context("revoking registration lease")?;

    tracing::info!(key, lease_id, "revoked etcd lease");
    Ok(())
}

/// One readiness probe: the coordinator has assigned every partition and
/// initial handoffs have completed — N registered pods, all partitions
/// Active, no in-flight handoffs. Returns `None` when ready, or a progress
/// report while waiting.
pub async fn check_ready(
    store: &PersonhogStore,
    partitions: u32,
    leaders: u32,
) -> Result<Option<String>> {
    let pods = store.list_pods().await.unwrap_or_default();
    let assignments = store.list_assignments().await.unwrap_or_default();
    let handoffs = store.list_handoffs().await.unwrap_or_default();

    let assigned = assignments.len() as u32;
    if pods.len() as u32 >= leaders && assigned == partitions && handoffs.is_empty() {
        return Ok(None);
    }

    Ok(Some(format!(
        "pods {}/{}, partitions {}/{}, handoffs in flight {}",
        pods.len(),
        leaders,
        assigned,
        partitions,
        handoffs.len()
    )))
}
