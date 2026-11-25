# meep-wire

The server and replica exchange these JSON types over the Meep HTTP API. A command receipt identifies the original command and the authoritative revision of its topic.

`views::topic_rows(state, "tasks")` returns the same task rows to live and offline views. Each row retains the canonical `column` (`Todo`, `InProgress`, `NeedsYou`, or `Done`) and adds its human-readable `status` (`To do`, `In progress`, `Needs you`, or `Done`). Use `column` for logic and `status` for display.

```rust
use meep_wire::{CommandResult, CommandResults};

# fn main() -> Result<(), serde_json::Error> {
let receipt: CommandResults = serde_json::from_str(r#"{
    "results": [{
        "status": "applied",
        "id": "00000000-0000-0000-0000-000000000001",
        "topic": "00000000-0000-0000-0000-000000000002",
        "revision": 7
    }]
}"#)?;
assert!(matches!(receipt.results.as_slice(), [CommandResult::Applied { revision: 7, .. }]));
# Ok(())
# }
```
