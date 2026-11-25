//! Bundled example scripts. User-generated views and revisions live in SQLite.

/// Script source for a bundled example, by its view kind ID.
pub fn source(id: &str) -> Option<&'static str> {
    match id {
        "github" | "inbox" => Some(include_str!("../agent/examples/inbox.js")),
        "notes" => Some(include_str!("../agent/examples/notes.js")),
        "tasks" => Some(include_str!("../agent/examples/tasks.js")),
        "native" => Some(include_str!("../agent/examples/native.js")),
        "table" => Some(include_str!("../agent/examples/table.js")),
        "record" => Some(include_str!("../agent/examples/record.js")),
        "board" => Some(include_str!("../agent/examples/board.js")),
        "agents" => Some(include_str!("../agent/examples/agents.js")),
        _ => None,
    }
}
