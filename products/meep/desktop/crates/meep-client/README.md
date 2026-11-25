# meep-client

The Mac app reads topics, attention items and search results from its own SQLite file. Issuing a command updates the visible topic and saves the envelope in the same transaction. A Tokio task pushes the outbox in order, pulls server snapshots from a durable cursor and listens for live revisions. Each new snapshot becomes the base for the edits still waiting on this device.

Use `Client::pair` to open a hosted replica by server and authenticated owner. It checks `GET /v1/health` on first pairing and can reopen a previously paired device offline. Token rotation within an owner preserves its outbox. Remote servers require HTTPS. Loopback development servers may use HTTP.

```rust,no_run
use meep_client::Client;
use meep_connections::SecretStore;
use std::path::Path;

async fn connect(
    replica_dir: &Path,
    server: &str,
    token: Option<&str>,
    credentials: &mut impl SecretStore,
) -> anyhow::Result<Client> {
    Ok(Client::pair(replica_dir, server, token, credentials).await?.client)
}
```

Hosts that already manage a separate SQLite file per server and owner can still use `Client::open`.

In an app, subscribe to events and run `client.run().await` in a task for the lifetime of the session. Call `sync_now()` when network reachability returns or the person requests a refresh. A rejected command leaves the outbox and raises a UI event with the server's reason. Read pending rejections with `rejections()` and acknowledge displayed ones with `dismiss_rejection()`. File edits are saved in the replica before upload. Revision zero represents a pending edit. Synchronization retries each upload with its original key.

Chat appears immediately in Sorting. Sync delivers the server's interpretation and any resulting task or reply. `sources_for(topic)` returns model-ranked resources and `cached_sources_for(topic)` reads their last known order offline.
