# meep-client

The Mac app reads topics, attention items and search results from its own SQLite file. Issuing a command updates the visible topic and saves the envelope in the same transaction. A Tokio task pushes the outbox in order, pulls server snapshots from a durable cursor and listens for live revisions. Each new snapshot becomes the base for the edits still waiting on this device.

Use `Client::open` with a separate database path for each PostHog origin, project and user.

In an app, subscribe to events and run `client.run().await` in a task for the lifetime of the session. Call `sync_now()` when network reachability returns or the person requests a refresh. A rejected command leaves the outbox and raises a UI event with the server's reason. Read pending rejections with `rejections()` and acknowledge displayed ones with `dismiss_rejection()`. File edits are saved in the replica before upload. Revision zero represents a pending edit. Synchronization retries each upload with its original key.

Chat appears immediately in Sorting. Sync delivers the server's interpretation and any resulting task or reply. `sources_for(topic)` returns model-ranked resources and `cached_sources_for(topic)` reads their last known order offline.
