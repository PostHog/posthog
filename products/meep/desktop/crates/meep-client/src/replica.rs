use crate::FileRevision;
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use meep_store::{self as store, Connection};
use meep_topic::{Changes, Command, CommandId, Envelope, TopicId, TopicState};
use meep_wire::{Connections, TopicSnapshot};
use rusqlite::{OptionalExtension, params};
use std::{collections::BTreeMap, path::Path};

const BASE: &str = "client/base";
const VISIBLE: &str = "client/visible";
const META: &str = "client/meta";

pub(crate) fn open(path: &Path) -> Result<Connection> {
    let db = Connection::open(path)?;
    db.pragma_update(None, "journal_mode", "WAL")?;
    store::initialize(&db)?;
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS client_view_outbox (seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,envelope TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS client_outbox (
            seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, topic TEXT NOT NULL, envelope TEXT NOT NULL
         );
         CREATE TABLE IF NOT EXISTS client_command_retry(id TEXT PRIMARY KEY REFERENCES client_outbox(id) ON DELETE CASCADE, due INTEGER NOT NULL, delay INTEGER NOT NULL, reason TEXT NOT NULL);
         CREATE TRIGGER IF NOT EXISTS clear_command_retry AFTER DELETE ON client_outbox BEGIN DELETE FROM client_command_retry WHERE id=old.id; END;
         CREATE INDEX IF NOT EXISTS client_topic_outbox ON client_outbox(topic,seq);
         CREATE TABLE IF NOT EXISTS client_file_outbox (
             seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, topic TEXT NOT NULL, path TEXT NOT NULL, bytes BLOB NOT NULL
         );
         CREATE TABLE IF NOT EXISTS client_rejected_files (
             id TEXT PRIMARY KEY, path TEXT NOT NULL, bytes BLOB NOT NULL
         );
         CREATE TABLE IF NOT EXISTS client_artifact_cache (
            key TEXT PRIMARY KEY, bytes BLOB NOT NULL, size INTEGER NOT NULL, used INTEGER NOT NULL
         );
         CREATE INDEX IF NOT EXISTS client_artifact_cache_used ON client_artifact_cache(used);
         CREATE TABLE IF NOT EXISTS client_files (
            topic TEXT NOT NULL, path TEXT NOT NULL, revision BLOB NOT NULL, bytes BLOB NOT NULL,
            PRIMARY KEY(topic,path)
         );",
    )?;
    // Older outboxes lacked base revisions. Recover the last confirmed local head and
    // link successive pending edits so they advance from their own predecessor.
    db.execute_batch("CREATE TABLE IF NOT EXISTS client_file_bases (
        id TEXT PRIMARY KEY, base BLOB NOT NULL, parent TEXT
    );
    CREATE TRIGGER IF NOT EXISTS clear_file_base AFTER DELETE ON client_file_outbox
        BEGIN DELETE FROM client_file_bases WHERE id=OLD.id; END;
    INSERT OR IGNORE INTO client_file_bases(id,base,parent)
        SELECT f.id,coalesce(c.revision,zeroblob(8)),
            (SELECT p.id FROM client_file_outbox p WHERE p.topic=f.topic AND p.path=f.path AND p.seq<f.seq ORDER BY p.seq DESC LIMIT 1)
        FROM client_file_outbox f LEFT JOIN client_files c ON c.topic=f.topic AND c.path=f.path;")?;
    Ok(db)
}

pub(crate) fn topics(db: &Connection) -> Result<Vec<TopicState>> {
    Ok(store::list(db, VISIBLE)?
        .into_iter()
        .map(|(_, s)| s)
        .collect())
}

pub(crate) fn visible(db: &Connection, topic: TopicId) -> Result<Option<TopicState>> {
    store::get(db, VISIBLE, &topic.to_string())
}

fn project(
    state: &mut Option<TopicState>,
    envelope: &Envelope,
) -> Result<Changes, meep_topic::TopicError> {
    if let Some(state) = state {
        state.apply(envelope)
    } else {
        let (created, changes) = envelope.create()?;
        *state = Some(created);
        Ok(changes)
    }
}

pub(crate) fn issue(
    db: &mut Connection,
    envelope: &Envelope,
    grant: Option<&str>,
) -> Result<Changes> {
    store::transaction(db, |tx| {
        let previous = visible(tx, envelope.topic)?;
        let mut envelope = envelope.clone();
        if let Command::Approve {
            task,
            expected_review,
            ..
        }
        | Command::SendBack {
            task,
            expected_review,
            ..
        } = &mut envelope.command
            && expected_review.is_none()
            && let Some(task) = previous
                .as_ref()
                .and_then(|s| s.tasks.iter().find(|t| t.id == *task))
        {
            *expected_review = Some(task.review_version);
        }
        if let Command::Answer {
            thread,
            expected_review,
            ..
        } = &mut envelope.command
            && expected_review.is_none()
            && let Some(thread) = previous
                .as_ref()
                .and_then(|s| s.threads.iter().find(|t| t.id == *thread))
        {
            *expected_review = Some(thread.review_version);
        }
        let mut state = previous.clone();
        let changes = project(&mut state, &envelope)?;
        tx.execute(
            "INSERT INTO client_outbox(id,topic,envelope) VALUES (?1,?2,?3)",
            params![
                envelope.id.to_string(),
                envelope.topic.to_string(),
                serde_json::to_string(&envelope)?
            ],
        )?;
        if let Some(connection) = grant {
            store::put(
                tx,
                "client/requested-access",
                &envelope.topic.to_string(),
                &(connection, envelope.id),
            )?;
        }
        write_visible(tx, envelope.topic, previous.as_ref(), state.as_ref())?;
        Ok(changes)
    })
}

fn write_visible(
    db: &Connection,
    topic: TopicId,
    previous: Option<&TopicState>,
    state: Option<&TopicState>,
) -> Result<bool> {
    if state == previous {
        return Ok(false);
    }
    let id = topic.to_string();
    if let Some(state) = state.filter(|s| !s.deleted) {
        store::put(db, VISIBLE, &id, state)?;
    } else {
        store::remove(db, VISIBLE, &id)?;
    }
    store::reindex(
        db,
        meep_wire::search_documents(previous),
        meep_wire::search_documents(state),
    )?;
    Ok(true)
}

pub(crate) fn requested_access(db: &Connection) -> Result<Vec<(TopicId, String, CommandId)>> {
    let mut ready = vec![];
    for (id, (connection, command)) in
        store::list::<(String, CommandId)>(db, "client/requested-access")?
    {
        let pending: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM client_outbox WHERE id=?1)",
            [command.to_string()],
            |r| r.get(0),
        )?;
        if !pending {
            ready.push((id.parse()?, connection, command));
        }
    }
    Ok(ready)
}

pub(crate) fn count(db: &Connection) -> Result<usize> {
    let count: i64 = db.query_row(
        "SELECT (SELECT count(*) FROM client_outbox) + (SELECT count(*) FROM client_file_outbox) + (SELECT count(*) FROM client_view_outbox)",
        [],
        |row| row.get(0),
    )?;
    Ok(usize::try_from(count)?
        + store::list::<crate::workflows::PendingSwitch>(db, crate::workflows::PENDING)?.len())
}

pub(crate) fn has_commands(db: &Connection, topic: TopicId) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM client_outbox WHERE topic=?1)",
        [topic.to_string()],
        |r| r.get(0),
    )?)
}

pub(crate) fn outbox_end(db: &Connection) -> Result<i64> {
    Ok(
        db.query_row("SELECT coalesce(max(seq),0) FROM client_outbox", [], |r| {
            r.get(0)
        })?,
    )
}

pub(crate) fn has_without_sort(db: &Connection) -> Result<bool> {
    Ok(db.query_row("SELECT EXISTS(SELECT 1 FROM client_outbox WHERE json_extract(envelope,'$.command.kind')='CreateTopicWithoutSort')", [], |r| r.get(0))?)
}

pub(crate) fn has_context_sources(db: &Connection) -> Result<bool> {
    Ok(db.query_row("SELECT EXISTS(SELECT 1 FROM client_outbox WHERE json_extract(envelope,'$.command.kind') IN ('SetContextSources','AddContextSource','RemoveContextSource'))", [], |r| r.get(0))?)
}

// Creation is a barrier: dependent edits require confirmation that this UUID belongs
// to the new topic, and any requested grants must precede the next command.
pub(crate) fn next_batch(
    db: &Connection,
    after: i64,
    end: i64,
    supports_without_sort: bool,
    supports_context_sources: bool,
) -> Result<(i64, Vec<Envelope>)> {
    let mut stmt = db.prepare(
        "SELECT seq,envelope FROM client_outbox WHERE seq>?1 AND seq<=?2 AND (?3 OR json_extract(envelope,'$.command.kind')!='CreateTopicWithoutSort') AND (?4 OR json_extract(envelope,'$.command.kind') NOT IN ('SetContextSources','AddContextSource','RemoveContextSource')) AND NOT EXISTS (SELECT 1 FROM client_command_retry r WHERE r.id=client_outbox.id AND r.due>unixepoch())
         AND NOT EXISTS (SELECT 1 FROM client_outbox creation WHERE creation.topic=client_outbox.topic
             AND creation.seq<client_outbox.seq AND (json_extract(creation.envelope,'$.command.kind') IN ('CreateTopic','CreateTopicWithoutSort') OR (NOT ?4 AND json_extract(creation.envelope,'$.command.kind') IN ('SetContextSources','AddContextSource','RemoveContextSource'))))
         ORDER BY seq LIMIT 64",
    )?;
    let mut rows = stmt.query(params![
        after,
        end,
        supports_without_sort,
        supports_context_sources
    ])?;
    let mut last = after;
    let mut commands = vec![];
    while let Some(row) = rows.next()? {
        last = row.get(0)?;
        let envelope: Envelope = serde_json::from_str(row.get_ref(1)?.as_str()?)?;
        let creation = matches!(
            envelope.command,
            meep_topic::Command::CreateTopic { .. }
                | meep_topic::Command::CreateTopicWithoutSort { .. }
        );
        commands.push(envelope);
        if creation {
            break;
        }
    }
    Ok((last, commands))
}

fn outbox(db: &Connection, topic: TopicId) -> Result<Vec<Envelope>> {
    let mut stmt = db.prepare("SELECT envelope FROM client_outbox WHERE topic=?1 ORDER BY seq")?;
    stmt.query_map([topic.to_string()], |row| row.get::<_, String>(0))?
        .map(|row| Ok(serde_json::from_str(&row?)?))
        .collect()
}

pub(crate) fn reject_dependents(
    db: &Connection,
    topic: TopicId,
    create: CommandId,
) -> Result<Vec<crate::Event>> {
    let topic_key = topic.to_string();
    let mut rejected = vec![];
    let mut cancel = |command, item: &str| {
        rejected.push(crate::Event::Rejected {
            command,
            reason: format!("Could not {item}: topic creation was rejected"),
        });
    };
    for e in outbox(db, topic)? {
        if e.id != create {
            cancel(e.id, "apply edit");
        }
    }
    db.execute("DELETE FROM client_outbox WHERE topic=?1", [&topic_key])?;
    let mut files = db.prepare("SELECT id,path FROM client_file_outbox WHERE topic=?1")?;
    for row in files.query_map([&topic_key], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
    })? {
        let (id, path) = row?;
        preserve_upload(db, &id)?;
        cancel(id.parse()?, &format!("upload {path}"));
    }
    db.execute(
        "DELETE FROM client_file_outbox WHERE topic=?1",
        [&topic_key],
    )?;
    for (key, change) in
        store::list::<crate::workflows::PendingSwitch>(db, crate::workflows::PENDING)?
    {
        if change.topic == topic {
            store::remove(db, crate::workflows::PENDING, &key)?;
            cancel(change.id, "switch workflow");
        }
    }
    store::remove(db, "client/requested-access", &topic_key)?;
    Ok(rejected)
}

/// Called in the same transaction that records a rejection and removes the queued upload.
pub(crate) fn preserve_upload(db: &Connection, id: &str) -> Result<()> {
    db.execute(
        "INSERT INTO client_rejected_files(id,path,bytes) SELECT id,path,bytes FROM client_file_outbox WHERE id=?1",
        [id],
    )?;
    Ok(())
}

pub(crate) fn cursor(db: &Connection) -> Result<u64> {
    Ok(store::get(db, META, "cursor")?.unwrap_or_default())
}

/// Install receipts, authoritative bases and the cursor in a single commit. A replay that
/// no longer applies stays in the outbox until the server decides its fate.
pub(crate) fn reconcile(
    db: &mut Connection,
    receipts: &[(CommandId, TopicId)],
    snapshots: &[TopicSnapshot],
    cursor: Option<u64>,
) -> Result<Vec<TopicId>> {
    store::transaction(db, |tx| reconcile_in(tx, receipts, snapshots, cursor))
}

pub(crate) fn reconcile_in(
    tx: &Connection,
    receipts: &[(CommandId, TopicId)],
    snapshots: &[TopicSnapshot],
    cursor: Option<u64>,
) -> Result<Vec<TopicId>> {
    let mut affected = BTreeMap::new();
    for (id, topic) in receipts {
        tx.execute("DELETE FROM client_outbox WHERE id=?1", [id.to_string()])?;
        affected.insert(*topic, None);
    }
    for snapshot in snapshots {
        let topic = snapshot.state.topic.id;
        let id = topic.to_string();
        let revision: Option<String> = tx
            .query_row(
                "SELECT body -> 'revision' FROM records WHERE kind=?1 AND id=?2 AND deleted=0",
                [BASE, &id],
                |r| r.get(0),
            )
            .optional()?;
        if revision
            .map(|s| s.parse::<u64>())
            .transpose()?
            .is_none_or(|base| base < snapshot.revision)
        {
            if snapshot.state.deleted {
                for table in ["client_outbox", "client_file_outbox", "client_files"] {
                    tx.execute(&format!("DELETE FROM {table} WHERE topic=?1"), [&id])?;
                }
                for kind in [
                    "client/file-list",
                    "client/requested-access",
                    "client/discovery",
                ] {
                    store::remove(tx, kind, &id)?;
                }
                tx.execute(
                    "DELETE FROM records WHERE kind='client/workflows' AND id LIKE ?1",
                    [format!("{id}/%")],
                )?;
                for (key, switch) in
                    store::list::<crate::workflows::PendingSwitch>(tx, crate::workflows::PENDING)?
                {
                    if switch.topic == topic {
                        store::remove(tx, crate::workflows::PENDING, &key)?;
                    }
                }
            } else {
                for path in snapshot.state.deleted_files.keys() {
                    tx.execute(
                        "DELETE FROM client_files WHERE topic=?1 AND path=?2",
                        [&id, path],
                    )?;
                }
            }
            store::put(tx, BASE, &id, snapshot)?;
            affected.insert(topic, Some(&snapshot.state));
        }
    }
    let mut changed = vec![];
    for (topic, incoming) in affected {
        let commands = outbox(tx, topic)?;
        let mut overlay;
        let state = match incoming {
            Some(state) if commands.is_empty() => Some(state),
            _ => {
                overlay = match incoming {
                    Some(state) => Some(state.clone()),
                    None => {
                        store::get::<TopicSnapshot>(tx, BASE, &topic.to_string())?.map(|s| s.state)
                    }
                };
                for envelope in commands {
                    let _ = project(&mut overlay, &envelope);
                }
                overlay.as_ref()
            }
        };
        let previous = visible(tx, topic)?;
        if write_visible(tx, topic, previous.as_ref(), state)? {
            changed.push(topic);
        }
    }
    if let Some(cursor) = cursor {
        store::put(tx, META, "cursor", &cursor)?;
    }
    Ok(changed)
}

pub(crate) fn connections(db: &Connection) -> Result<Connections> {
    Ok(
        store::get(db, META, "connections")?.unwrap_or_else(|| Connections {
            connections: vec![],
        }),
    )
}

pub(crate) fn health_observations(db: &Connection) -> Result<BTreeMap<String, DateTime<Utc>>> {
    Ok(store::get(db, META, "unhealthy_since")?.unwrap_or_default())
}

pub(crate) fn replace_connections(db: &Connection, list: &Connections) -> Result<Vec<TopicId>> {
    let previous = connections(db)?;
    if previous == *list {
        return Ok(vec![]);
    }
    let changed = previous
        .connections
        .iter()
        .filter(|c| !list.connections.contains(c))
        .chain(
            list.connections
                .iter()
                .filter(|c| !previous.connections.contains(c)),
        )
        .collect::<Vec<_>>();
    let mut affected = vec![];
    let mut statement =
        db.prepare("SELECT body -> 'topic' FROM records WHERE kind=?1 AND deleted=0 ORDER BY id")?;
    for row in statement.query_map([VISIBLE], |r| r.get::<_, String>(0))? {
        let topic: meep_topic::Topic = serde_json::from_str(&row?)?;
        if changed
            .iter()
            .any(|c| c.grants.contains(&topic.id) || topic.watches().any(|w| w.connection == c.id))
        {
            affected.push(topic.id);
        }
    }
    let mut since = health_observations(db)?;
    since.retain(|id, _| {
        list.connections
            .iter()
            .any(|c| c.id == *id && c.health != "ok")
    });
    for c in list.connections.iter().filter(|c| c.health != "ok") {
        since.entry(c.id.clone()).or_insert_with(Utc::now);
    }
    store::put(db, META, "unhealthy_since", &since)?;
    store::put(db, META, "connections", list)?;
    Ok(affected)
}

pub(crate) fn deleted_files(db: &Connection, topic: TopicId) -> Result<BTreeMap<String, u64>> {
    let body: Option<String> = db
        .query_row(
            "SELECT body -> 'deleted_files' FROM records WHERE kind=?1 AND id=?2 AND deleted=0",
            params![VISIBLE, topic.to_string()],
            |r| r.get(0),
        )
        .optional()?
        .flatten();
    Ok(body
        .map(|json| serde_json::from_str(&json))
        .transpose()?
        .unwrap_or_default())
}

pub(crate) fn cached_file(
    db: &Connection,
    topic: TopicId,
    path: &str,
) -> Result<Option<FileRevision>> {
    if let Some(bytes) = pending_file(db, topic, path)? {
        return Ok(Some(FileRevision { revision: 0, bytes }));
    }
    if deleted_files(db, topic)?.contains_key(path) {
        return Ok(None);
    }
    confirmed_file(db, topic, path)
}

pub(crate) fn pending_file(db: &Connection, topic: TopicId, path: &str) -> Result<Option<Vec<u8>>> {
    Ok(db.query_row("SELECT bytes FROM client_file_outbox WHERE topic=?1 AND path=?2 ORDER BY seq DESC LIMIT 1", params![topic.to_string(),path], |row| row.get(0)).optional()?)
}

fn confirmed_file(db: &Connection, topic: TopicId, path: &str) -> Result<Option<FileRevision>> {
    Ok(db
        .query_row(
            "SELECT revision,bytes FROM client_files WHERE topic=?1 AND path=?2",
            params![topic.to_string(), path],
            |row| {
                Ok(FileRevision {
                    revision: u64::from_be_bytes(row.get(0)?),
                    bytes: row.get(1)?,
                })
            },
        )
        .optional()?)
}

pub(crate) fn cache_file(
    db: &mut Connection,
    topic: TopicId,
    path: &str,
    file: FileRevision,
) -> Result<FileRevision> {
    store::transaction(db, |tx| {
        let confirmed = save_file(tx, topic, path, file)?;
        Ok(match pending_file(tx, topic, path)? {
            Some(bytes) => FileRevision { revision: 0, bytes },
            None => confirmed,
        })
    })
}

pub(crate) fn save_file(
    tx: &Connection,
    topic: TopicId,
    path: &str,
    file: FileRevision,
) -> Result<FileRevision> {
    if let Some(base) = store::get::<TopicSnapshot>(tx, BASE, &topic.to_string())? {
        anyhow::ensure!(
            !base.state.deleted
                && !base
                    .state
                    .deleted_files
                    .get(path)
                    .is_some_and(|at| *at >= file.revision),
            "File was deleted during transfer"
        );
    }
    // Reads and writes may finish out of order. Keep the newest confirmed revision.
    let written = tx.execute(
        "INSERT INTO client_files(topic,path,revision,bytes) VALUES (?1,?2,?3,?4)
             ON CONFLICT(topic,path) DO UPDATE SET revision=excluded.revision,bytes=excluded.bytes
             WHERE excluded.revision >= client_files.revision",
        params![
            topic.to_string(),
            path,
            file.revision.to_be_bytes(),
            file.bytes
        ],
    )?;
    if written > 0 {
        Ok(file)
    } else {
        confirmed_file(tx, topic, path)?.context("missing cached file")
    }
}

/// A cached artifact version, marked as just used.
pub(crate) fn cached_artifact(db: &Connection, key: &str, now: i64) -> Result<Option<Vec<u8>>> {
    let bytes = db
        .query_row(
            "SELECT bytes FROM client_artifact_cache WHERE key=?1",
            [key],
            |r| r.get(0),
        )
        .optional()?;
    if bytes.is_some() {
        db.execute(
            "UPDATE client_artifact_cache SET used=?2 WHERE key=?1",
            params![key, now],
        )?;
    }
    Ok(bytes)
}

/// Keep an artifact version, then drop the least recently used past `cap` bytes.
pub(crate) fn cache_artifact(
    db: &Connection,
    key: &str,
    bytes: &[u8],
    now: i64,
    cap: u64,
) -> Result<()> {
    if bytes.len() as u64 > cap {
        return Ok(());
    }
    db.execute(
        "INSERT OR REPLACE INTO client_artifact_cache(key,bytes,size,used) VALUES(?1,?2,?3,?4)",
        params![key, bytes, bytes.len() as i64, now],
    )?;
    db.execute(
        "DELETE FROM client_artifact_cache WHERE key IN (
            SELECT key FROM (
                SELECT key, SUM(size) OVER (ORDER BY used DESC, key) AS total
                FROM client_artifact_cache
            ) WHERE total > ?1
        )",
        [cap as i64],
    )?;
    Ok(())
}

/// Bytes held by the artifact cache.
pub(crate) fn artifact_cache_size(db: &Connection) -> Result<u64> {
    Ok(db.query_row(
        "SELECT coalesce(SUM(size),0) FROM client_artifact_cache",
        [],
        |r| r.get::<_, i64>(0),
    )? as u64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn an_older_snapshot_cannot_rewind_a_base_already_confirmed_by_a_receipt() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut db = open(&dir.path().join("replica.sqlite"))?;
        let topic = Uuid::new_v4().into();
        let mut state = TopicState::new(meep_topic::Topic::new(topic, "Accounts", Utc::now()));
        state.topic.mission = "Monitor transfers".into();
        let older = TopicSnapshot {
            revision: 1,
            state: state.clone(),
        };
        let mut latest = TopicSnapshot { revision: 2, state };
        latest.state.set_mission("Updated mission", Utc::now())?;
        reconcile(&mut db, &[], std::slice::from_ref(&latest), None)?;
        reconcile(&mut db, &[], &[older], Some(1))?;
        assert_eq!(visible(&db, topic)?, Some(latest.state));
        assert!(crate::queries::search(&db, "monitor", 2)?.hits.is_empty());
        assert_eq!(cursor(&db)?, 1);
        Ok(())
    }

    #[test]
    fn late_file_download_does_not_overwrite_a_newer_confirmed_revision() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut db = open(&dir.path().join("replica.sqlite"))?;
        let topic = Uuid::new_v4().into();
        let newest = FileRevision {
            revision: u64::MAX,
            bytes: vec![2],
        };
        cache_file(&mut db, topic, "f", newest.clone())?;
        assert_eq!(
            cache_file(
                &mut db,
                topic,
                "f",
                FileRevision {
                    revision: 7,
                    bytes: vec![1]
                }
            )?,
            newest
        );
        assert_eq!(cached_file(&db, topic, "f")?, Some(newest));
        Ok(())
    }
    #[test]
    fn a_download_finishing_after_a_local_edit_returns_the_pending_contents() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut db = open(&dir.path().join("replica.sqlite"))?;
        let topic: TopicId = Uuid::new_v4().into();
        db.execute(
            "INSERT INTO client_file_outbox(id,topic,path,bytes) VALUES ('edit',?1,'f',?2)",
            params![topic.to_string(), b"new"],
        )?;
        let remote = FileRevision {
            revision: 1,
            bytes: b"old".to_vec(),
        };
        let visible = cache_file(&mut db, topic, "f", remote.clone())?;
        assert_eq!(
            visible,
            FileRevision {
                revision: 0,
                bytes: b"new".to_vec()
            }
        );
        assert_eq!(confirmed_file(&db, topic, "f")?, Some(remote));
        Ok(())
    }
}
