//! Loads person properties from Postgres into the property store while the writer group is
//! empty, for one team or every team. Rewriting a row is harmless because the store keeps the higher version.

use std::collections::HashMap;
use std::sync::Arc;

use bytes::Bytes;
use futures::future::try_join_all;
use personhog_common::properties::parse_stored_properties;
use personhog_property_store::object_store::path::Path as ObjectPath;
use personhog_property_store::object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use personhog_property_store::{shard_for, PartitionKey, PropertyRecord, PropertyWriter, PutError};
use serde_json::json;
use sqlx::{PgPool, Row};

const GENERATION: u64 = 1;

#[derive(Debug, thiserror::Error)]
pub enum BackfillError {
    #[error("{0}")]
    Config(String),
    #[error("postgres: {0}")]
    Postgres(#[from] sqlx::Error),
    #[error("object store: {0}")]
    ObjectStore(#[from] personhog_property_store::object_store::Error),
    #[error("property store: {0}")]
    Store(#[from] personhog_property_store::PropertyStoreError),
    #[error("writing partition {partition}: {source}")]
    Put { partition: u32, source: PutError },
    #[error("progress record unreadable: {0}")]
    Progress(String),
}

#[derive(Debug, Clone)]
pub enum Scanned {
    Record(PropertyRecord),
    Reject {
        team_id: i64,
        person_id: i64,
        reason: String,
    },
}

impl Scanned {
    fn cursor(&self) -> Cursor {
        match self {
            Scanned::Record(record) => Cursor {
                team_id: record.team_id,
                person_id: record.person_id,
            },
            Scanned::Reject {
                team_id, person_id, ..
            } => Cursor {
                team_id: *team_id,
                person_id: *person_id,
            },
        }
    }
}

/// The last row a page held; the next page starts after it in `(team_id, id)` order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cursor {
    pub team_id: i64,
    pub person_id: i64,
}

pub struct Scan {
    pool: PgPool,
    query: String,
    team_id: Option<i32>,
    page_size: i64,
}

impl Scan {
    pub fn new(
        pool: PgPool,
        table: &str,
        team_id: Option<i64>,
        page_size: i64,
    ) -> Result<Self, BackfillError> {
        validate_name(table, false)?;
        let team_id = team_id
            .map(|team| {
                i32::try_from(team)
                    .map_err(|_| BackfillError::Config(format!("team {team} exceeds int4")))
            })
            .transpose()?;
        // A single team keeps `team_id = $1` so the scan stays in that team's hash partition.
        let filter = match team_id {
            Some(_) => "team_id = $1 AND id > $2",
            None => "(team_id, id) > ($1, $2)",
        };
        Ok(Self {
            pool,
            query: format!(
                "SELECT team_id, id, version, is_deleted, \
                 CASE WHEN is_deleted THEN NULL ELSE properties::text END AS properties \
                 FROM {table} WHERE {filter} ORDER BY team_id, id LIMIT $3"
            ),
            team_id,
            page_size: page_size.max(1),
        })
    }

    pub fn start(&self) -> Cursor {
        Cursor {
            team_id: i64::from(self.team_id.unwrap_or(i32::MIN)),
            person_id: i64::MIN,
        }
    }

    pub async fn page(&self, after: Cursor) -> Result<Vec<Scanned>, BackfillError> {
        let after_team = i32::try_from(after.team_id).map_err(|_| {
            BackfillError::Progress(format!("cursor team {} exceeds int4", after.team_id))
        })?;
        let rows = sqlx::query(&self.query)
            .bind(self.team_id.unwrap_or(after_team))
            .bind(after.person_id)
            .bind(self.page_size)
            .fetch_all(&self.pool)
            .await?;
        Ok(rows
            .iter()
            .map(|row| {
                let team_id: i32 = row.get("team_id");
                let person_id: i64 = row.get("id");
                let version: Option<i64> = row.get("version");
                let deleted: bool = row.get("is_deleted");
                let text: Option<&str> = row.get("properties");
                to_scanned(
                    i64::from(team_id),
                    person_id,
                    version.unwrap_or(0),
                    deleted,
                    text,
                )
            })
            .collect())
    }
}

/// Matches the leader's Postgres load, so the store serves the bytes the leader would have.
fn to_scanned(
    team_id: i64,
    person_id: i64,
    version: i64,
    deleted: bool,
    text: Option<&str>,
) -> Scanned {
    let properties = match (deleted, text) {
        (true, _) | (false, None) => Bytes::new(),
        (false, Some(text)) => match parse_stored_properties(text)
            .map_err(|e| e.to_string())
            .and_then(|parsed| serde_json::to_vec(&parsed.value).map_err(|e| e.to_string()))
        {
            Ok(bytes) => Bytes::from(bytes),
            Err(reason) => {
                return Scanned::Reject {
                    team_id,
                    person_id,
                    reason,
                }
            }
        },
    };
    Scanned::Record(PropertyRecord {
        team_id,
        person_id,
        version,
        deleted,
        properties,
    })
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Counts {
    pub read: u64,
    pub written: u64,
    pub deleted: u64,
    pub rejected: u64,
}

impl Counts {
    fn to_json(self, after: Cursor) -> Vec<u8> {
        json!({
            "after_team_id": after.team_id,
            "after_person_id": after.person_id,
            "read": self.read,
            "written": self.written,
            "deleted": self.deleted,
            "rejected": self.rejected,
        })
        .to_string()
        .into_bytes()
    }

    fn from_json(raw: &[u8]) -> Result<(Cursor, Self), BackfillError> {
        let value: serde_json::Value =
            serde_json::from_slice(raw).map_err(|e| BackfillError::Progress(e.to_string()))?;
        let field = |name: &str| {
            value[name]
                .as_u64()
                .ok_or_else(|| BackfillError::Progress(format!("missing {name}")))
        };
        let position = |name: &str| {
            value[name]
                .as_i64()
                .ok_or_else(|| BackfillError::Progress(format!("missing {name}")))
        };
        Ok((
            Cursor {
                team_id: position("after_team_id")?,
                person_id: position("after_person_id")?,
            },
            Self {
                read: field("read")?,
                written: field("written")?,
                deleted: field("deleted")?,
                rejected: field("rejected")?,
            },
        ))
    }
}

pub struct Progress {
    store: Arc<dyn ObjectStore>,
    root: String,
}

impl Progress {
    pub fn new(
        store: Arc<dyn ObjectStore>,
        prefix: &str,
        run_id: &str,
    ) -> Result<Self, BackfillError> {
        validate_name(run_id, true)?;
        Ok(Self {
            store,
            root: format!("{}/maintenance/backfill/{run_id}", prefix.trim_matches('/')),
        })
    }

    fn path(&self, name: &str) -> ObjectPath {
        ObjectPath::from(format!("{}/{name}", self.root))
    }

    async fn read(&self, name: &str) -> Result<Option<Bytes>, BackfillError> {
        match self.store.get(&self.path(name)).await {
            Ok(found) => Ok(Some(found.bytes().await?)),
            Err(personhog_property_store::object_store::Error::NotFound { .. }) => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    async fn write(&self, name: &str, body: Vec<u8>) -> Result<(), BackfillError> {
        self.store
            .put(&self.path(name), PutPayload::from(body))
            .await?;
        Ok(())
    }

    pub async fn finished(&self) -> Result<Option<Counts>, BackfillError> {
        self.read("done")
            .await?
            .map(|raw| Counts::from_json(&raw).map(|(_, counts)| counts))
            .transpose()
    }

    async fn resume_point(&self, start: Cursor) -> Result<(Cursor, Counts), BackfillError> {
        match self.read("cursor").await? {
            Some(raw) => Counts::from_json(&raw),
            None => Ok((start, Counts::default())),
        }
    }

    async fn reject(
        &self,
        team_id: i64,
        person_id: i64,
        reason: &str,
    ) -> Result<(), BackfillError> {
        self.write(
            &format!("rejects/{team_id}-{person_id}"),
            reason.as_bytes().to_vec(),
        )
        .await
    }
}

pub enum Outcome {
    Finished(Counts),
    AlreadyDone(Counts),
}

/// Writes every page durably before recording it, so a crash repeats at most one page.
pub async fn run(
    scan: &Scan,
    writer: &PropertyWriter,
    progress: &Progress,
    topic: &str,
    partitions: u32,
    shards: u32,
) -> Result<Outcome, BackfillError> {
    if let Some(counts) = progress.finished().await? {
        return Ok(Outcome::AlreadyDone(counts));
    }
    let topic: Arc<str> = Arc::from(topic);
    let keys: Vec<PartitionKey> = (0..partitions)
        .map(|partition| PartitionKey {
            topic: Arc::clone(&topic),
            partition,
        })
        .collect();
    for key in &keys {
        writer.assign(key, GENERATION, partitions, || true).await?;
    }

    let start = scan.start();
    let (mut after, mut counts) = progress.resume_point(start).await?;
    if after != start {
        tracing::info!(?after, ?counts, "resuming backfill");
    }
    loop {
        let page = scan.page(after).await?;
        let Some(last) = page.last().map(Scanned::cursor) else {
            break;
        };
        let mut by_partition: HashMap<u32, Vec<PropertyRecord>> = HashMap::new();
        for scanned in page.iter() {
            counts.read += 1;
            match scanned {
                Scanned::Record(record) => {
                    let partition =
                        shard_for(record.team_id, record.person_id, shards) % partitions;
                    if record.deleted {
                        counts.deleted += 1;
                    }
                    counts.written += 1;
                    by_partition
                        .entry(partition)
                        .or_default()
                        .push(record.clone());
                }
                Scanned::Reject {
                    team_id,
                    person_id,
                    reason,
                } => {
                    tracing::warn!(team_id, person_id, reason, "row rejected");
                    progress.reject(*team_id, *person_id, reason).await?;
                    counts.rejected += 1;
                }
            }
        }
        try_join_all(by_partition.into_iter().map(|(partition, records)| {
            let key = &keys[partition as usize];
            async move {
                writer
                    .put(key, GENERATION, &records)
                    .await
                    .map_err(|source| BackfillError::Put { partition, source })
            }
        }))
        .await?;
        after = last;
        progress.write("cursor", counts.to_json(after)).await?;
        tracing::info!(?after, ?counts, "page written");
    }
    progress.write("done", counts.to_json(after)).await?;
    Ok(Outcome::Finished(counts))
}

/// The writer group's live members; the backfill refuses to open shards while any exist.
pub fn group_members(
    base: &rdkafka::ClientConfig,
    group: &str,
    timeout: std::time::Duration,
) -> Result<usize, BackfillError> {
    use rdkafka::consumer::{BaseConsumer, Consumer};
    let consumer: BaseConsumer = base
        .create()
        .map_err(|e| BackfillError::Config(format!("kafka client: {e}")))?;
    let groups = consumer
        .fetch_group_list(Some(group), timeout)
        .map_err(|e| BackfillError::Config(format!("describing group {group}: {e}")))?;
    Ok(groups
        .groups()
        .iter()
        .filter(|g| g.name() == group)
        .map(|g| g.members().len())
        .sum())
}

/// The table is interpolated into SQL and the run id into an object path.
fn validate_name(value: &str, allow_dash: bool) -> Result<(), BackfillError> {
    let mut chars = value.chars();
    let valid = chars
        .next()
        .is_some_and(|c| c.is_ascii_lowercase() || c == '_')
        && chars.all(|c| {
            c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || (allow_dash && c == '-')
        });
    if valid {
        Ok(())
    } else {
        Err(BackfillError::Config(format!(
            "{value:?} is not a plain lowercase name"
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(scanned: Scanned) -> PropertyRecord {
        match scanned {
            Scanned::Record(record) => record,
            Scanned::Reject { reason, .. } => panic!("rejected: {reason}"),
        }
    }

    #[test]
    fn rows_are_stored_as_the_leader_would_load_them() {
        let live = record(to_scanned(7, 1, 3, false, Some(r#"{"a": 1, "b": "x"}"#)));
        assert_eq!(&live.properties[..], br#"{"a":1,"b":"x"}"#);

        let huge = format!(r#"{{"n": 1{}}}"#, "0".repeat(400));
        let rewritten = record(to_scanned(7, 2, 3, false, Some(&huge)));
        let expected = parse_stored_properties(&huge).unwrap();
        assert!(
            expected.rewritten,
            "the fixture must need the numeric rewrite"
        );
        assert_eq!(
            rewritten.properties,
            Bytes::from(serde_json::to_vec(&expected.value).unwrap())
        );

        let deleted = record(to_scanned(7, 3, 5, true, None));
        assert!(deleted.deleted && deleted.properties.is_empty());
    }

    #[test]
    fn a_row_no_parse_can_read_is_rejected_with_its_person() {
        let nested = format!("{}1{}", "[".repeat(200), "]".repeat(200));
        match to_scanned(7, 9, 1, false, Some(&nested)) {
            Scanned::Reject { person_id, .. } => assert_eq!(person_id, 9),
            Scanned::Record(_) => panic!("a document serde cannot parse was accepted"),
        }
    }

    #[test]
    fn only_plain_names_reach_sql_or_object_paths() {
        for (value, allow_dash, ok) in [
            ("personhog_person_tmp", false, true),
            ("team-2", true, true),
            ("team-2", false, false),
            ("person; drop table x", false, false),
            ("../escape", true, false),
            ("Team", true, false),
            ("", true, false),
        ] {
            assert_eq!(validate_name(value, allow_dash).is_ok(), ok, "{value}");
        }
    }
}
