# meep-connections

A connection identifies a service account, records its health, and lists the topics allowed to use it. The host supplies a SQLite connection and chooses where to keep credentials. Use `MemorySecrets` for fixtures or `KeychainSecrets` for a macOS host.

## Give a topic access to Slack

```rust
use chrono::Utc;
use meep_connections::{Connection, Health, Registry, TopicId};
use meep_store::Connection as Database;

# fn main() -> anyhow::Result<()> {
let mut registry = Registry::new(Database::open_in_memory()?)?;
registry.add(Connection {
    id: "team-slack".into(),
    kind: "slack".into(),
    label: "Team Slack".into(),
    account: "design-team".into(),
    health: Health::Ok { checked_at: Utc::now() },
    grants: vec![],
    unrouted: 0,
})?;

let topic: TopicId = "3542fec1-6d74-4726-a5ca-83524c67d8b4".parse()?;
registry.grant("team-slack", &topic)?;
assert!(registry.can_use(&topic, "team-slack")?);
# Ok(())
# }
```

Pass a file-backed database to keep connections across restarts. Use `check_all` with a host-provided `HealthChecker` to refresh service status. Grants survive an outage so a topic can resume work when its account recovers.
