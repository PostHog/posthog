# meep-engine

The engine runs topic automation on the server. Apply a person's command with its original ID to make outbox retries harmless. Each committed topic revision is available through the change cursor and the live event stream.

```rust
use meep_engine::Engine;
use meep_topic::{Command, Envelope};
use chrono::DateTime;

# #[tokio::main(flavor = "current_thread")]
# async fn main() -> anyhow::Result<()> {
let engine = Engine::in_memory().await?;
let (topic, _) = engine.create_topic("Navigation", "Keep the rail easy to use.").await?;
let request = Envelope {
    id: "00000000-0000-0000-0000-000000000001".parse()?,
    topic,
    issued_at: DateTime::UNIX_EPOCH,
    command: Command::AddTask {

        id: "00000000-0000-0000-0000-000000000002".parse()?,
        title: "Review the pinned menu".into(),
    },
};
let applied = engine.apply(request.clone()).await?;
assert!(engine.apply(request).await?.changes.is_empty());
assert_eq!(engine.snapshot(topic)?.revision, applied.revision);
assert_eq!(engine.search("pinned")?[0].topic, topic);
# Ok(())
# }
```

`Engine::open` uses a private directory with `SqliteStore` and `DirBlobs`. Clone the engine to share its workers. A replica starts at cursor zero, calls `changes_since`, then reads each changed topic with `snapshot`. Save the new cursor after updating the replica. A lagged broadcast receiver can resume from its saved cursor.

`Engine::with_backends` accepts a store, blob storage, routine backends, limits, agent, sorter and clock. With the `posthog` feature, bind an existing flow using `PostHogRoutines` and `bind_routine`. Configure the flow's HTTP step with the returned callback secret. The public routine list is in `snapshot.state.topic.routines`. The host can dispatch with `start_routine`, inspect an invocation with `routine_status`, and refresh availability with `routine_health`.

PostHog workflows can submit authenticated operations including `AddTask`, `AddFact`, `Ask`, `Send` and `Note`. The `fixtures` feature supplies the six-topic `demo()`. An injected `ManualClock` advances workers when the host calls `tick`.

The server supplies a `ModelSorter` backed by the topic’s PostHog grant. Ingest returns after committing the message in Sorting. A topic worker classifies it and saves the decision, sourced facts and revision together. Tests can drive this step with `sort_pending`. A standalone engine without a gateway sends decisions to Needs you with a connection diagnostic.
