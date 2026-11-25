//! Typed records on a connection opened and configured by the host.
//! All operations also accept an existing SQLite transaction.
use anyhow::Result;
pub use rusqlite::Connection;
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::time::SystemTime;

/// Creates the records table and full-text search index, preserving existing data.
pub fn initialize(db: &Connection) -> Result<()> {
    // Publish the content table and its indexing triggers together.
    let tx = db
        .is_autocommit()
        .then(|| db.unchecked_transaction())
        .transpose()?;
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS records (
        kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
        version INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(kind,id)
    );
    CREATE TABLE IF NOT EXISTS search_documents (
        rowid INTEGER PRIMARY KEY, kind TEXT NOT NULL, id TEXT NOT NULL, text TEXT NOT NULL,
        UNIQUE(kind, id)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(text, content='search_documents');
    CREATE TRIGGER IF NOT EXISTS search_documents_insert AFTER INSERT ON search_documents BEGIN
        INSERT INTO search_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
    CREATE TRIGGER IF NOT EXISTS search_documents_delete AFTER DELETE ON search_documents BEGIN
        INSERT INTO search_fts(search_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    END;
    CREATE TRIGGER IF NOT EXISTS search_documents_update AFTER UPDATE OF text ON search_documents BEGIN
        INSERT INTO search_fts(search_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
        INSERT INTO search_fts(rowid, text) VALUES (new.rowid, new.text);
    END;",
    )?;
    if let Some(tx) = tx {
        tx.commit()?;
    }
    Ok(())
}

/// One matching document, with its excerpt and SQLite relevance score.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Hit {
    /// The application-defined kind supplied to [`index`].
    pub kind: String,
    /// The application-defined ID within this kind.
    pub id: String,
    /// A plain-text excerpt around the matching terms.
    pub snippet: String,
    /// The FTS5 BM25 score. Lower values indicate stronger matches.
    pub rank: f64,
}

/// Adds or replaces the searchable text for one (kind, id) pair.
pub fn index(db: &Connection, kind: &str, id: &str, text: &str) -> Result<()> {
    db.execute(
        "INSERT INTO search_documents(kind, id, text) VALUES (?1, ?2, ?3)
         ON CONFLICT(kind, id) DO UPDATE SET text=excluded.text
         WHERE search_documents.text <> excluded.text",
        params![kind, id, text],
    )?;
    Ok(())
}

/// Removes the searchable text for one (kind, id) pair, if present.
pub fn unindex(db: &Connection, kind: &str, id: &str) -> Result<()> {
    db.execute(
        "DELETE FROM search_documents WHERE kind=?1 AND id=?2",
        params![kind, id],
    )?;
    Ok(())
}

/// Apply changes to searchable documents inside the caller's transaction.
pub fn reindex<'a>(
    db: &Connection,
    mut previous: std::collections::BTreeMap<(&'a str, String), String>,
    current: std::collections::BTreeMap<(&'a str, String), String>,
) -> Result<()> {
    for (key, text) in current {
        if previous.remove(&key).as_ref() != Some(&text) {
            let (kind, id) = key;
            index(db, kind, &id, &text)?;
        }
    }
    for ((kind, id), _) in previous {
        unindex(db, kind, &id)?;
    }
    Ok(())
}

/// Finds documents matching every whitespace-separated term as a literal prefix.
/// Results are ordered by relevance, then by kind and ID to break ties.
pub fn search(db: &Connection, query: &str, limit: usize) -> Result<Vec<Hit>> {
    // Quote user input so operators like OR, quotes and wildcards are literal.
    // FTS5 tokenizes the contents, including diacritics and internal punctuation.
    let terms = query
        .split(|ch: char| ch.is_whitespace() || ch == '\0')
        .filter(|part| part.chars().any(char::is_alphanumeric))
        .map(|term| format!("\"{}\"*", term.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(" ");
    if terms.is_empty() || limit == 0 {
        return Ok(Vec::new());
    }
    let mut statement = db.prepare(
        "SELECT d.kind, d.id, snippet(search_fts, 0, '', '', '…', 24), rank
         FROM search_fts JOIN search_documents d ON d.rowid=search_fts.rowid
         WHERE search_fts MATCH ?1 ORDER BY rank, d.kind, d.id LIMIT ?2",
    )?;
    let hits = statement.query_map(
        params![terms, i64::try_from(limit).unwrap_or(i64::MAX)],
        |row| {
            Ok(Hit {
                kind: row.get(0)?,
                id: row.get(1)?,
                snippet: row.get(2)?,
                rank: row.get(3)?,
            })
        },
    )?;
    Ok(hits.collect::<rusqlite::Result<_>>()?)
}

/// Returns the live record with this kind and ID, if present.
pub fn get<T: DeserializeOwned>(db: &Connection, kind: &str, id: &str) -> Result<Option<T>> {
    get_json(db, kind, id)?
        .map(|body| Ok(serde_json::from_str(&body)?))
        .transpose()
}

/// Fetch a record so its caller can release the connection before decoding it.
pub fn get_json(db: &Connection, kind: &str, id: &str) -> Result<Option<String>> {
    Ok(db
        .query_row(
            "SELECT body FROM records WHERE kind=?1 AND id=?2 AND deleted=0",
            params![kind, id],
            |row| row.get(0),
        )
        .optional()?)
}

/// Lists the live records of one kind ordered by ID.
pub fn list<T: DeserializeOwned>(db: &Connection, kind: &str) -> Result<Vec<(String, T)>> {
    let mut statement =
        db.prepare("SELECT id,body FROM records WHERE kind=?1 AND deleted=0 ORDER BY id")?;
    statement
        .query_map([kind], |row| Ok((row.get(0)?, row.get::<_, String>(1)?)))?
        .map(|row| {
            let (id, body) = row?;
            Ok((id, serde_json::from_str(&body)?))
        })
        .collect()
}

fn timestamp_ms() -> i64 {
    let now = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH);
    match now {
        Ok(elapsed) => elapsed.as_millis() as i64,
        Err(before) => -(before.duration().as_millis() as i64),
    }
}

/// Upsert a serialized record. Identical writes preserve its revision.
pub fn put<T: Serialize + ?Sized>(db: &Connection, kind: &str, id: &str, value: &T) -> Result<()> {
    put_json(db, kind, id, &serde_json::to_string(value)?)
}

/// Write an already serialized JSON record inside the caller’s transaction.
pub fn put_json(db: &Connection, kind: &str, id: &str, body: &str) -> Result<()> {
    db.execute("INSERT INTO records(kind,id,body,version,updated_ms) VALUES(?1,?2,?3,1,?4)
        ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,version=records.version+1,
        updated_ms=excluded.updated_ms,deleted=0 WHERE records.body<>excluded.body OR records.deleted=1",
        params![kind, id, body, timestamp_ms()])?;
    Ok(())
}

/// Tombstone a live record, clearing its body and advancing its revision.
pub fn remove(db: &Connection, kind: &str, id: &str) -> Result<bool> {
    let changed = db.execute(
        "UPDATE records SET deleted=1,body='null',version=version+1,updated_ms=?3
         WHERE kind=?1 AND id=?2 AND deleted=0",
        params![kind, id, timestamp_ms()],
    )?;
    Ok(changed != 0)
}

/// Run a read-modify-write operation atomically, including across separate connections.
pub fn transaction<T>(db: &mut Connection, f: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let result = f(&tx)?;
    tx.commit()?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn initializing_inside_a_host_transaction_respects_its_rollback() -> Result<()> {
        let mut db = Connection::open_in_memory()?;
        let tx = db.transaction()?;
        initialize(&tx)?;
        index(&tx, "note", "draft", "Draft")?;
        assert_eq!(search(&tx, "draft", 1)?.len(), 1);
        tx.rollback()?;
        initialize(&db)?;
        assert!(search(&db, "draft", 1)?.is_empty());
        Ok(())
    }

    #[test]
    fn search_returns_ranked_excerpts_for_all_query_prefixes() -> Result<()> {
        let db = Connection::open_in_memory()?;
        initialize(&db)?;
        index(&db, "note", "a", "Pinned pinned pinned reading list")?;
        index(&db, "task", "b", "Pinned reading for tomorrow morning")?;
        index(&db, "note", "c", "Reading list")?;
        index(&db, "note", "pinned", "Unrelated text")?;
        let hits = search(&db, "PIN read", 10)?;
        assert_eq!(hits.len(), 2);
        assert_eq!((&*hits[0].kind, &*hits[0].id), ("note", "a"));
        assert!(hits[0].rank < hits[1].rank);
        assert_eq!(hits[1].snippet, "Pinned reading for tomorrow morning");
        assert_eq!(search(&db, "pin read", 1)?, hits[..1]);
        assert!(search(&db, "pin", 0)?.is_empty());
        Ok(())
    }

    #[test]
    fn query_syntax_is_literal_and_blank_queries_match_nothing() -> Result<()> {
        let db = Connection::open_in_memory()?;
        initialize(&db)?;
        index(&db, "note", "a", "Café or tea")?;
        index(&db, "note", "b", "Tea only")?;
        assert_eq!(search(&db, "cafe OR te", 2)?.len(), 1);
        assert_eq!(search(&db, "\"café\"*", 1)?[0].id, "a");
        for query in ["", "  ", "-!*()", "\0"] {
            assert!(search(&db, query, 10)?.is_empty());
        }
        Ok(())
    }

    #[test]
    fn replacements_and_removals_are_scoped_to_both_kind_and_id() -> Result<()> {
        let db = Connection::open_in_memory()?;
        initialize(&db)?;
        for (kind, id) in [("note", "a"), ("fact", "a"), ("note", "b")] {
            index(&db, kind, id, "Same text")?;
        }
        index(&db, "note", "a", "New text")?;
        index(&db, "note", "a", "New text")?;
        initialize(&db)?;
        assert_eq!(search(&db, "new", 10)?.len(), 1);
        let hits = search(&db, "same", 10)?;
        let keys: Vec<_> = hits
            .iter()
            .map(|hit| (hit.kind.as_str(), hit.id.as_str()))
            .collect();
        assert_eq!(keys, [("fact", "a"), ("note", "b")]);
        unindex(&db, "note", "a")?;
        unindex(&db, "note", "a")?;
        assert!(search(&db, "new", 10)?.is_empty());
        assert_eq!(search(&db, "same", 10)?, hits);
        Ok(())
    }

    #[test]
    fn failed_transactions_restore_search_entries_alongside_records() -> Result<()> {
        let mut db = Connection::open_in_memory()?;
        initialize(&db)?;
        index(&db, "note", "keep", "Original")?;
        let failed: Result<()> = transaction(&mut db, |tx| {
            unindex(tx, "note", "keep")?;
            put(tx, "note", "new", "Replacement")?;
            index(tx, "note", "new", "Replacement")?;
            assert_eq!(search(tx, "rep", 1)?[0].id, "new");
            anyhow::bail!("cancelled")
        });
        assert!(failed.is_err());
        assert_eq!(search(&db, "orig", 1)?[0].id, "keep");
        assert!(search(&db, "rep", 1)?.is_empty());
        assert!(get::<String>(&db, "note", "new")?.is_none());
        Ok(())
    }

    #[test]
    fn removing_and_restoring_a_record_preserves_its_revision_history() -> Result<()> {
        let db = Connection::open_in_memory()?;
        initialize(&db)?;
        put(&db, "settings", "color", "blue")?;
        put(&db, "settings", "color", "blue")?;
        assert!(remove(&db, "settings", "color")?);
        assert!(!remove(&db, "settings", "color")?);
        assert!(get::<String>(&db, "settings", "color")?.is_none());
        put(&db, "settings", "color", "green")?;
        assert_eq!(
            list::<String>(&db, "settings")?,
            [("color".into(), "green".into())]
        );
        let revision: i64 = db.query_row("SELECT version FROM records", [], |row| row.get(0))?;
        assert_eq!(revision, 3);
        Ok(())
    }
}
