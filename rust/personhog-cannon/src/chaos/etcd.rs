use anyhow::{bail, Context, Result};
use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{
    HandoffState, PartitionAssignment, RegisteredPod, RegisteredRouter,
};
use std::time::Duration;

pub struct EtcdState {
    store: PersonhogStore,
}

impl EtcdState {
    pub async fn connect(endpoints: &str, prefix: &str) -> Result<Self> {
        let endpoint_list: Vec<String> = endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let config = StoreConfig {
            endpoints: endpoint_list,
            prefix: prefix.to_string(),
        };

        let inner = EtcdStore::connect(config)
            .await
            .context("failed to connect to etcd")?;

        Ok(Self {
            store: PersonhogStore::new(inner),
        })
    }

    pub async fn list_pods(&self) -> Result<Vec<RegisteredPod>> {
        Ok(self.store.list_pods().await?)
    }

    pub async fn list_assignments(&self) -> Result<Vec<PartitionAssignment>> {
        Ok(self.store.list_assignments().await?)
    }

    pub async fn list_handoffs(&self) -> Result<Vec<HandoffState>> {
        Ok(self.store.list_handoffs().await?)
    }

    pub async fn list_routers(&self) -> Result<Vec<RegisteredRouter>> {
        Ok(self.store.list_routers().await?)
    }

    pub async fn get_total_partitions(&self) -> Result<u32> {
        Ok(self.store.get_total_partitions().await?)
    }

    pub async fn revoke_pod_lease(&self, pod_name: &str) -> Result<()> {
        let prefix = self.store.inner().prefix();
        let key = format!("{prefix}pods/{pod_name}");

        let resp = self
            .store
            .inner()
            .client()
            .clone()
            .get(key.clone(), None)
            .await
            .context("failed to get pod key from etcd")?;

        let kv = resp
            .kvs()
            .first()
            .ok_or_else(|| anyhow::anyhow!("pod {pod_name} not found in etcd"))?;

        let lease_id = kv.lease();
        if lease_id == 0 {
            bail!("pod {pod_name} has no lease attached (lease_id=0)");
        }

        self.store
            .inner()
            .client()
            .clone()
            .lease_revoke(lease_id)
            .await
            .context("failed to revoke lease")?;

        Ok(())
    }

    pub async fn wait_for_pod(&self, pod_name: &str, timeout: Duration) -> Result<()> {
        let start = std::time::Instant::now();
        while start.elapsed() < timeout {
            let pods = self.list_pods().await?;
            if pods.iter().any(|p| p.pod_name == pod_name) {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
        bail!(
            "pod {pod_name} did not appear in etcd within {}s",
            timeout.as_secs()
        );
    }

    pub async fn wait_for_stable(&self, timeout: Duration) -> Result<()> {
        let total = self.get_total_partitions().await?;
        let start = std::time::Instant::now();
        while start.elapsed() < timeout {
            let handoffs = self.list_handoffs().await?;
            let assignments = self.list_assignments().await?;
            if handoffs.is_empty() && assignments.len() == total as usize {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
        bail!(
            "coordination did not stabilize within {}s",
            timeout.as_secs()
        );
    }
}
