use std::time::Duration;

use etcd_client::{
    Client, Compare, CompareOp, ConnectOptions, DeleteOptions, GetOptions, PutOptions, Txn, TxnOp,
    TxnResponse, WatchOptions, WatchStream,
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

/// Records one etcd operation's wall time on drop, so every return path
/// (including errors) lands in the histogram. Includes this layer's
/// (de)serialization, which is negligible next to the etcd round trip.
///
/// Public so an operation driven outside this store still lands in the
/// same histogram: a lease renewal runs off the `LeaseKeeper` this store
/// handed out, never through a method here, and it is the highest-rate
/// etcd call the fleet makes.
pub struct OpTimer {
    op: &'static str,
    start: std::time::Instant,
}

impl OpTimer {
    pub fn new(op: &'static str) -> Self {
        Self {
            op,
            start: std::time::Instant::now(),
        }
    }
}

impl Drop for OpTimer {
    fn drop(&mut self) {
        metrics::histogram!("assignment_coordination_etcd_op_ms", "op" => self.op)
            .record(self.start.elapsed().as_secs_f64() * 1000.0);
    }
}

/// Bytes moved by one etcd operation, keys included. Payload size is the
/// axis on which coordination outgrows its store — etcd caps a request at
/// `--max-request-bytes`, and a record whose size scales with fleet size
/// crosses that limit long before op counts or latency show strain — so
/// it is measured next to duration rather than inferred from it.
fn record_payload_bytes(op: &'static str, bytes: usize) {
    metrics::histogram!("assignment_coordination_etcd_payload_bytes", "op" => op)
        .record(bytes as f64);
}

fn kvs_bytes(kvs: &[etcd_client::KeyValue]) -> usize {
    kvs.iter().map(|kv| kv.key().len() + kv.value().len()).sum()
}

impl EtcdStore {
    pub async fn connect(config: StoreConfig) -> Result<Self> {
        // Transport-level liveness so a silent network partition fails
        // fast instead of hanging until TCP retransmission gives up
        // (minutes — far past any lease TTL): HTTP/2 pings ride every
        // connection, including idle ones and long-lived watch streams,
        // and error all in-flight requests within roughly one ping
        // interval plus its timeout of the peer going dark. Deliberately
        // no per-request timeout — it would apply to the whole lifetime
        // of a watch stream and kill healthy watches.
        // The ping interval must clear etcd's server-side gRPC keepalive
        // enforcement (--grpc-keepalive-min-time, default 5s): pings at or
        // under the floor are strikes, and two strikes close the
        // connection with GOAWAY. Idle pings are likewise strikes unless
        // the server permits them, so they stay off — every component
        // that matters holds an active watch or keepalive stream, and an
        // idle channel is revalidated on next use within the connect
        // timeout.
        let options = ConnectOptions::new()
            .with_connect_timeout(Duration::from_secs(5))
            .with_keep_alive(Duration::from_secs(10), Duration::from_secs(5))
            .with_keep_alive_while_idle(false);
        let client = Client::connect(&config.endpoints, Some(options)).await?;
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

    // ── Raw (non-JSON) helpers ────────────────────────────────────

    pub async fn get_raw(&self, key: &str) -> Result<Option<Vec<u8>>> {
        let _t = OpTimer::new("get_raw");
        let resp = self.client.clone().get(key, None).await?;
        record_payload_bytes("get_raw", kvs_bytes(resp.kvs()));
        Ok(resp.kvs().first().map(|kv| kv.value().to_vec()))
    }

    pub async fn put_raw(&self, key: &str, value: impl Into<Vec<u8>>) -> Result<()> {
        let _t = OpTimer::new("put_raw");
        let value = value.into();
        record_payload_bytes("put_raw", key.len() + value.len());
        self.client.clone().put(key, value, None).await?;
        Ok(())
    }

    // ── JSON helpers ─────────────────────────────────────────────

    pub async fn get<T: DeserializeOwned>(&self, key: &str) -> Result<Option<T>> {
        let _t = OpTimer::new("get");
        let resp = self.client.clone().get(key, None).await?;
        record_payload_bytes("get", kvs_bytes(resp.kvs()));
        match resp.kvs().first() {
            Some(kv) => Ok(Some(serde_json::from_slice(kv.value())?)),
            None => Ok(None),
        }
    }

    pub async fn get_versioned<T: DeserializeOwned>(&self, key: &str) -> Result<Option<(T, i64)>> {
        let _t = OpTimer::new("get_versioned");
        let resp = self.client.clone().get(key, None).await?;
        record_payload_bytes("get_versioned", kvs_bytes(resp.kvs()));
        match resp.kvs().first() {
            Some(kv) => {
                let value = serde_json::from_slice(kv.value())?;
                Ok(Some((value, kv.version())))
            }
            None => Ok(None),
        }
    }

    /// Like `get_versioned`, but returns the key's `mod_revision` instead
    /// of its per-key `version` counter. Compare-and-swap guards that must
    /// not match across a delete-and-recreate of the same key MUST use
    /// this: `version` resets to 1 when a key is recreated, so a guard on
    /// `version` can accept a different incarnation of the key, while
    /// `mod_revision` is globally monotonic and never repeats.
    pub async fn get_with_mod_revision<T: DeserializeOwned>(
        &self,
        key: &str,
    ) -> Result<Option<(T, i64)>> {
        let _t = OpTimer::new("get_with_mod_revision");
        let resp = self.client.clone().get(key, None).await?;
        record_payload_bytes("get_with_mod_revision", kvs_bytes(resp.kvs()));
        match resp.kvs().first() {
            Some(kv) => {
                let value = serde_json::from_slice(kv.value())?;
                Ok(Some((value, kv.mod_revision())))
            }
            None => Ok(None),
        }
    }

    /// Like `get`, but also returns the store revision the read was
    /// taken at, to anchor a `watch_key_from` so a key that vanishes
    /// before the watch attaches is still reported. The revision comes
    /// from the response header, so it is meaningful even when the key
    /// is absent — exactly the case a waiter anchors on.
    pub async fn get_with_revision<T: DeserializeOwned>(
        &self,
        key: &str,
    ) -> Result<(Option<T>, i64)> {
        let _t = OpTimer::new("get_with_revision");
        let resp = self.client.clone().get(key, None).await?;
        record_payload_bytes("get_with_revision", kvs_bytes(resp.kvs()));
        let revision = resp.header().map(|h| h.revision()).unwrap_or(0);
        match resp.kvs().first() {
            Some(kv) => Ok((Some(serde_json::from_slice(kv.value())?), revision)),
            None => Ok((None, revision)),
        }
    }

    pub async fn list<T: DeserializeOwned>(&self, prefix: &str) -> Result<Vec<T>> {
        Ok(self.list_with_revision(prefix).await?.0)
    }

    /// The keys under `prefix`, without their values. For callers that
    /// need to know what exists rather than what it says — etcd leaves
    /// the values out of the response, so the cost does not scale with
    /// how large the records are.
    pub async fn list_keys(&self, prefix: &str) -> Result<Vec<String>> {
        let _t = OpTimer::new("list_keys");
        let options = GetOptions::new().with_prefix().with_keys_only();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        record_payload_bytes("list_keys", kvs_bytes(resp.kvs()));
        Ok(resp
            .kvs()
            .iter()
            .filter_map(|kv| kv.key_str().ok().map(str::to_string))
            .collect())
    }

    /// Like `list_keys`, with each key's mod_revision — for callers that
    /// guard a later write on the key being unchanged since this look.
    pub async fn list_keys_with_mod_revisions(&self, prefix: &str) -> Result<Vec<(String, i64)>> {
        let _t = OpTimer::new("list_keys_with_mod_revisions");
        let options = GetOptions::new().with_prefix().with_keys_only();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        record_payload_bytes("list_keys_with_mod_revisions", kvs_bytes(resp.kvs()));
        Ok(resp
            .kvs()
            .iter()
            .filter_map(|kv| {
                kv.key_str()
                    .ok()
                    .map(|k| (k.to_string(), kv.mod_revision()))
            })
            .collect())
    }

    /// Like `list`, but also returns the etcd store revision the snapshot
    /// was taken at. Pair with `watch_from(prefix, revision + 1)` for a
    /// gap-free snapshot-then-watch handshake: every event at or before
    /// the revision is in the snapshot, every later one is delivered by
    /// the watch, no matter when the watch actually attaches.
    pub async fn list_with_revision<T: DeserializeOwned>(
        &self,
        prefix: &str,
    ) -> Result<(Vec<T>, i64)> {
        let _t = OpTimer::new("list_with_revision");
        let options = GetOptions::new().with_prefix();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        record_payload_bytes("list_with_revision", kvs_bytes(resp.kvs()));
        let revision = resp.header().map(|h| h.revision()).unwrap_or(0);
        let items = resp
            .kvs()
            .iter()
            .map(|kv| serde_json::from_slice(kv.value()).map_err(Error::from))
            .collect::<Result<Vec<T>>>()?;
        Ok((items, revision))
    }

    /// Like `list`, but pairs each value with its key's `mod_revision` —
    /// the per-key version an optimistic transaction compares against to
    /// assert the record is unchanged since this read.
    pub async fn list_with_mod_revisions<T: DeserializeOwned>(
        &self,
        prefix: &str,
    ) -> Result<Vec<(T, i64)>> {
        let _t = OpTimer::new("list_with_mod_revisions");
        let options = GetOptions::new().with_prefix();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        record_payload_bytes("list_with_mod_revisions", kvs_bytes(resp.kvs()));
        resp.kvs()
            .iter()
            .map(|kv| Ok((serde_json::from_slice(kv.value())?, kv.mod_revision())))
            .collect()
    }

    /// The current etcd store revision, for anchoring watches when no
    /// snapshot read is involved.
    pub async fn current_revision(&self) -> Result<i64> {
        let _t = OpTimer::new("current_revision");
        let options = GetOptions::new().with_prefix().with_count_only();
        let resp = self
            .client
            .clone()
            .get(self.config.prefix.clone(), Some(options))
            .await?;
        Ok(resp.header().map(|h| h.revision()).unwrap_or(0))
    }

    pub async fn put<T: Serialize>(
        &self,
        key: &str,
        value: &T,
        lease_id: Option<i64>,
    ) -> Result<()> {
        let _t = OpTimer::new("put");
        let value = serde_json::to_string(value)?;
        record_payload_bytes("put", key.len() + value.len());
        let options = lease_id.map(|id| PutOptions::new().with_lease(id));
        self.client.clone().put(key, value, options).await?;
        Ok(())
    }

    pub async fn delete(&self, key: &str) -> Result<()> {
        let _t = OpTimer::new("delete");
        self.client.clone().delete(key, None).await?;
        Ok(())
    }

    pub async fn delete_prefix(&self, prefix: &str) -> Result<()> {
        let _t = OpTimer::new("delete_prefix");
        let options = DeleteOptions::new().with_prefix();
        self.client.clone().delete(prefix, Some(options)).await?;
        Ok(())
    }

    pub async fn watch(&self, prefix: &str) -> Result<WatchStream> {
        let _t = OpTimer::new("watch");
        let options = WatchOptions::new().with_prefix();
        let stream = self.client.clone().watch(prefix, Some(options)).await?;
        Ok(stream)
    }

    /// Watch the prefix starting from an explicit revision (inclusive).
    /// Events since that revision are replayed even if they predate the
    /// watch's creation, which removes the missed-event window between a
    /// snapshot read and the watch attaching. If etcd has compacted past
    /// the requested revision the stream is cancelled with an error; the
    /// caller's watch loop treats that as fatal and the component restarts
    /// with a fresh snapshot.
    pub async fn watch_from(&self, prefix: &str, start_revision: i64) -> Result<WatchStream> {
        let _t = OpTimer::new("watch_from");
        let options = WatchOptions::new()
            .with_prefix()
            .with_start_revision(start_revision);
        let stream = self.client.clone().watch(prefix, Some(options)).await?;
        Ok(stream)
    }

    /// Watch a single key — not a prefix — from an explicit revision
    /// (inclusive). Waiters on one key use this so an unrelated sibling
    /// key sharing the same string prefix cannot wake them.
    pub async fn watch_key_from(&self, key: &str, start_revision: i64) -> Result<WatchStream> {
        let _t = OpTimer::new("watch_key_from");
        let options = WatchOptions::new().with_start_revision(start_revision);
        let stream = self.client.clone().watch(key, Some(options)).await?;
        Ok(stream)
    }

    // ── Transactions ─────────────────────────────────────────────

    /// Deliberately not in `record_payload_bytes`: a transaction's size
    /// lives in the request, which is no longer reachable once the `Txn`
    /// is built, and its response carries only what its reads returned —
    /// nothing, for the plan transaction that actually approaches
    /// `--max-request-bytes`. A histogram here would sit at zero under
    /// the name an operator reaches for first. `apply_plan` measures the
    /// request side directly instead.
    pub async fn txn(&self, txn: Txn) -> Result<TxnResponse> {
        let _t = OpTimer::new("txn");
        Ok(self.client.clone().txn(txn).await?)
    }

    /// Atomically create `key` bound to `lease_id`, only if it does not
    /// exist; returns whether this call created it. The building block
    /// for single-holder claims: the key lives and dies with the lease,
    /// so revocation or expiry frees the claim for the next contender.
    pub async fn put_if_absent(&self, key: &str, value: Vec<u8>, lease_id: i64) -> Result<bool> {
        let _t = OpTimer::new("put_if_absent");
        let txn = Txn::new()
            .when(vec![Compare::version(key, CompareOp::Equal, 0)])
            .and_then(vec![TxnOp::put(
                key,
                value,
                Some(PutOptions::new().with_lease(lease_id)),
            )]);
        let resp = self.client.clone().txn(txn).await?;
        Ok(resp.succeeded())
    }

    // ── Lease operations ─────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        let _t = OpTimer::new("grant_lease");
        let resp = self.client.clone().lease_grant(ttl, None).await?;
        Ok(resp.id())
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        let _t = OpTimer::new("keep_alive");
        let (keeper, stream) = self.client.clone().lease_keep_alive(lease_id).await?;
        Ok((keeper, stream))
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        let _t = OpTimer::new("revoke_lease");
        self.client.clone().lease_revoke(lease_id).await?;
        Ok(())
    }

    // ── Cleanup ──────────────────────────────────────────────────

    pub async fn delete_all(&self) -> Result<()> {
        if self.config.prefix.is_empty() || self.config.prefix == "/" {
            return Err(Error::InvalidState(
                "refusing delete_all with empty or root prefix".to_string(),
            ));
        }
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
