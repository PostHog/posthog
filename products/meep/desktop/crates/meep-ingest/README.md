# meep-ingest

A connector supplies events with a stable account and external ID. Match watches with `route`, read an explicit thread hint with `group_key`, and record successful delivery with a `Deduper`. A file-backed `StoreSeenStore` remembers deliveries across restarts.

```rust
use meep_ingest::{Deduper, Event, MemorySeenStore, group_key};
use serde_json::json;

# fn main() -> anyhow::Result<()> {
let event: Event = serde_json::from_value(json!({
    "connection":"slack", "kind":"channel", "external_id":"42", "channel":"#rail",
    "author":"Mia", "at":"2025-11-19T14:31:00Z", "text":"Design notes",
    "attributes":{}, "thread_hint":"slack-thread-7"
}))?;
let mut delivered = Deduper::new(MemorySeenStore::default());
assert_eq!(group_key(&event), Some("slack-thread-7"));
assert!(delivered.record(&event)?);
assert!(!delivered.record(&event)?);
# Ok(())
# }
```
