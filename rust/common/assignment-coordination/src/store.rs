use etcd_client::{
    Client, DeleteOptions, GetOptions, PutOptions, Txn, TxnResponse, WatchOptions, WatchStream,
};
use serde::de::DeserializeOwned;
use serde::Serialize;

use crate::error::{Error, Result};

#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub endpoints: Vec<String>,
    /// Key prefix for all operations.
    /// e.g. "/kafka-assigner/deduplicator/" or "/personhog/"
    pub prefix: String,
}

/// Prefixed etcd client with typed JSON helpers.
///
/// Provides the generic building blocks that domain-specific stores compose:
/// get, list, put, delete, watch, lease management, and transactions.
///
/// `Client` is `Clone` (wraps an inner `Arc`), so each method clones it cheaply.
#[derive(Clone)]
pub struct EtcdStore {
    client: Client,
    config: StoreConfig,
}

impl EtcdStore {
    pub async fn connect(config: StoreConfig) -> Result<Self> {
        let client = Client::connect(&config.endpoints, None).await?;
        Ok(Self { client, config })
    }

    #[cfg(test)]
    pub fn from_client(client: Client, config: StoreConfig) -> Self {
        Self { client, config }
    }

    pub fn prefix(&self) -> &str {
        &self.config.prefix
    }

    pub fn client(&self) -> &Client {
        &self.client
    }

    // ── JSON helpers ─────────────────────────────────────────────

    pub async fn get<T: DeserializeOwned>(&self, key: &str) -> Result<Option<T>> {
        let resp = self.client.clone().get(key, None).await?;
        match resp.kvs().first() {
            Some(kv) => Ok(Some(serde_json::from_slice(kv.value())?)),
            None => Ok(None),
        }
    }

    pub async fn get_versioned<T: DeserializeOwned>(&self, key: &str) -> Result<Option<(T, i64)>> {
        let resp = self.client.clone().get(key, None).await?;
        match resp.kvs().first() {
            Some(kv) => {
                let value = serde_json::from_slice(kv.value())?;
                Ok(Some((value, kv.version())))
            }
            None => Ok(None),
        }
    }

    pub async fn list<T: DeserializeOwned>(&self, prefix: &str) -> Result<Vec<T>> {
        let options = GetOptions::new().with_prefix();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        resp.kvs()
            .iter()
            .map(|kv| serde_json::from_slice(kv.value()).map_err(Error::from))
            .collect()
    }

    pub async fn put<T: Serialize>(
        &self,
        key: &str,
        value: &T,
        lease_id: Option<i64>,
    ) -> Result<()> {
        let value = serde_json::to_string(value)?;
        let options = lease_id.map(|id| PutOptions::new().with_lease(id));
        self.client.clone().put(key, value, options).await?;
        Ok(())
    }

    pub async fn delete(&self, key: &str) -> Result<()> {
        self.client.clone().delete(key, None).await?;
        Ok(())
    }

    pub async fn delete_prefix(&self, prefix: &str) -> Result<()> {
        let options = DeleteOptions::new().with_prefix();
        self.client.clone().delete(prefix, Some(options)).await?;
        Ok(())
    }

    pub async fn watch(&self, prefix: &str) -> Result<WatchStream> {
        let options = WatchOptions::new().with_prefix();
        let stream = self.client.clone().watch(prefix, Some(options)).await?;
        Ok(stream)
    }

    // ── Transactions ─────────────────────────────────────────────

    pub async fn txn(&self, txn: Txn) -> Result<TxnResponse> {
        Ok(self.client.clone().txn(txn).await?)
    }

    // ── Lease operations ─────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        let resp = self.client.clone().lease_grant(ttl, None).await?;
        Ok(resp.id())
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        let (keeper, stream) = self.client.clone().lease_keep_alive(lease_id).await?;
        Ok((keeper, stream))
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        self.client.clone().lease_revoke(lease_id).await?;
        Ok(())
    }

    // ── Cleanup ──────────────────────────────────────────────────

    pub async fn delete_all(&self) -> Result<()> {
        self.delete_prefix(&self.config.prefix).await
    }
}

/// Parse a watch event's value as JSON.
pub fn parse_watch_value<T: DeserializeOwned>(
    event: &etcd_client::Event,
) -> std::result::Result<T, Error> {
    let kv = event
        .kv()
        .ok_or_else(|| Error::InvalidState("watch event missing kv".to_string()))?;
    serde_json::from_slice(kv.value()).map_err(Error::from)
}
