# meep-store

Store application-defined records keyed by `(kind, id)`. Record bodies use Serde JSON. Copy this directory and add `meep-store = { path = "path/to/meep-store" }` to your manifest.

Open a SQLite connection and call `initialize` to create the records table and search index. Use `get` and `put` with your own types. `list` returns the live records of one kind ordered by ID. An identical write preserves the stored revision. `remove` clears the body and records a deletion.

```rust
use meep_store::{Connection, index, initialize, put, search, transaction};

fn main() -> anyhow::Result<()> {
    let mut db = Connection::open_in_memory()?;
    initialize(&db)?;
    transaction(&mut db, |tx| {
        put(tx, "notes", "one", "Pinned reading list")?;
        index(tx, "notes", "one", "Pinned reading list")
    })?;
    let hits = search(&db, "pin", 10)?;
    assert_eq!(hits[0].id, "one");
    Ok(())
}
```

`transaction` acquires a write transaction before calling the closure and commits on success. If the host already owns a transaction, pass it directly to the record functions to combine them with other tables.

The host chooses the text to search. Call `index` to replace it and `unindex` to remove it. Use the same transaction as `put` or `remove` to keep record and search updates together. Search accepts plain text, matches term prefixes, and returns a snippet and BM25 rank for each hit, best matches first.

The default build bundles SQLite with FTS5. A host that configures SQLCipher can disable default features, select an FTS5-enabled SQLCipher build on its own `rusqlite` dependency, and pass in an unlocked connection. Each application owns its key policy, schema migrations, and cross-record invariants.
