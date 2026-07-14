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
