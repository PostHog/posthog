use anyhow::Context;
use assignment_coordination::store::{EtcdStore, StoreConfig};
use etcd_client::{Client, GetOptions, SortOrder, SortTarget};
use serde::Serialize;
use tokio::sync::Mutex;

use crate::config::Config;

/// Lazily connected etcd client shared by the explorer and the personhog
/// topology tools. Connecting lazily keeps the service starting (and its
/// other tools working) when etcd is unreachable; the first request that
/// needs etcd pays the connect and surfaces the error.
pub struct EtcdHandle {
    endpoints: Vec<String>,
    client: Mutex<Option<Client>>,
}

impl EtcdHandle {
    /// `None` when `ETCD_ENDPOINTS` is unset, which disables the etcd tools.
    pub fn from_config(config: &Config) -> Option<Self> {
        let endpoints = config.etcd_endpoint_list();
        if endpoints.is_empty() {
            return None;
        }
        Some(Self {
            endpoints,
            client: Mutex::new(None),
        })
    }

    /// `Client` clones share one gRPC channel, and the channel reconnects on
    /// its own, so a connection established once is reused for the process
    /// lifetime.
    pub async fn client(&self) -> anyhow::Result<Client> {
        let mut guard = self.client.lock().await;
        if let Some(client) = guard.as_ref() {
            return Ok(client.clone());
        }
        // Connect through EtcdStore so its transport tuning (connect
        // timeout, HTTP/2 keepalive) stays defined in one place.
        let store = EtcdStore::connect(StoreConfig {
            endpoints: self.endpoints.clone(),
            prefix: String::new(),
        })
        .await
        .with_context(|| format!("connecting to etcd at {:?}", self.endpoints))?;
        let client = store.client().clone();
        *guard = Some(client.clone());
        Ok(client)
    }
}

/// The exclusive upper bound of the key range sharing `prefix`: the prefix
/// with its last non-0xff byte incremented (trailing 0xff bytes dropped).
/// Falls back to etcd's "all keys from here" sentinel (`[0]`) when every
/// byte is 0xff.
fn prefix_range_end(prefix: &[u8]) -> Vec<u8> {
    let mut end = prefix.to_vec();
    while let Some(last) = end.last_mut() {
        if *last < 0xff {
            *last += 1;
            return end;
        }
        end.pop();
    }
    vec![0]
}

#[derive(Serialize)]
pub struct KeyMeta {
    pub key: String,
    pub create_revision: i64,
    pub mod_revision: i64,
    pub version: i64,
    /// 0 when no lease is attached.
    pub lease: i64,
    pub value_bytes: usize,
}

#[derive(Serialize)]
pub struct KeyList {
    pub keys: Vec<KeyMeta>,
    /// More keys exist under the prefix beyond this page.
    pub more: bool,
    /// Total keys under the prefix (not just this page).
    pub count: i64,
    pub revision: i64,
    /// Cursor for the next page; pass as `from_key`.
    pub next_from_key: Option<String>,
}

#[derive(Serialize)]
pub struct KeyDetail {
    pub key: String,
    /// Lossy UTF-8 rendering of the value; check `value_is_utf8` before
    /// editing and writing it back.
    pub value: String,
    pub value_is_utf8: bool,
    pub value_bytes: usize,
    pub create_revision: i64,
    pub mod_revision: i64,
    pub version: i64,
    pub lease: i64,
    /// Remaining seconds on the attached lease, when one exists and the
    /// lookup succeeded.
    pub lease_ttl_secs: Option<i64>,
    pub lease_granted_ttl_secs: Option<i64>,
}

pub async fn list_keys(
    client: &Client,
    prefix: &str,
    from_key: Option<&str>,
    limit: i64,
) -> anyhow::Result<KeyList> {
    let start = from_key.filter(|k| k.as_bytes() > prefix.as_bytes());
    let options = GetOptions::new()
        .with_range(prefix_range_end(prefix.as_bytes()))
        .with_limit(limit)
        .with_sort(SortTarget::Key, SortOrder::Ascend);
    let resp = client
        .clone()
        .get(start.unwrap_or(prefix), Some(options))
        .await
        .context("etcd range read")?;

    let keys: Vec<KeyMeta> = resp
        .kvs()
        .iter()
        .map(|kv| KeyMeta {
            key: String::from_utf8_lossy(kv.key()).into_owned(),
            create_revision: kv.create_revision(),
            mod_revision: kv.mod_revision(),
            version: kv.version(),
            lease: kv.lease(),
            value_bytes: kv.value().len(),
        })
        .collect();
    // The next page starts just after the last key: its bytes plus a zero
    // byte is the smallest possible successor.
    let next_from_key = if resp.more() {
        keys.last().map(|meta| format!("{}\0", meta.key))
    } else {
        None
    };
    Ok(KeyList {
        more: resp.more(),
        count: resp.count(),
        revision: resp.header().map(|h| h.revision()).unwrap_or(0),
        next_from_key,
        keys,
    })
}

pub async fn get_key(client: &Client, key: &str) -> anyhow::Result<Option<KeyDetail>> {
    let resp = client
        .clone()
        .get(key, None)
        .await
        .context("etcd key read")?;
    let Some(kv) = resp.kvs().first() else {
        return Ok(None);
    };

    let (lease_ttl_secs, lease_granted_ttl_secs) = if kv.lease() != 0 {
        match client.clone().lease_time_to_live(kv.lease(), None).await {
            Ok(lease) => (Some(lease.ttl()), Some(lease.granted_ttl())),
            // The lease can expire between the key read and this lookup;
            // the key detail is still useful without it.
            Err(_) => (None, None),
        }
    } else {
        (None, None)
    };

    Ok(Some(KeyDetail {
        key: String::from_utf8_lossy(kv.key()).into_owned(),
        value: String::from_utf8_lossy(kv.value()).into_owned(),
        value_is_utf8: std::str::from_utf8(kv.value()).is_ok(),
        value_bytes: kv.value().len(),
        create_revision: kv.create_revision(),
        mod_revision: kv.mod_revision(),
        version: kv.version(),
        lease: kv.lease(),
        lease_ttl_secs,
        lease_granted_ttl_secs,
    }))
}

/// Plain put, never attaching a lease: writing a value to a lease-backed
/// key detaches it from its lease, which the UI warns about before saving.
pub async fn put_key(client: &Client, key: &str, value: &str) -> anyhow::Result<i64> {
    let resp = client
        .clone()
        .put(key, value, None)
        .await
        .context("etcd put")?;
    Ok(resp.header().map(|h| h.revision()).unwrap_or(0))
}

/// Single-key delete only; the explorer deliberately has no prefix delete.
pub async fn delete_key(client: &Client, key: &str) -> anyhow::Result<bool> {
    let resp = client
        .clone()
        .delete(key, None)
        .await
        .context("etcd delete")?;
    Ok(resp.deleted() > 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prefix_range_end_increments_the_last_byte() {
        assert_eq!(prefix_range_end(b"/personhog/"), b"/personhog0".to_vec());
        assert_eq!(prefix_range_end(b"/"), b"0".to_vec());
    }

    #[test]
    fn prefix_range_end_handles_trailing_0xff() {
        assert_eq!(prefix_range_end(&[b'a', 0xff]), vec![b'b']);
        assert_eq!(prefix_range_end(&[0xff, 0xff]), vec![0]);
    }
}
