//! Scans person properties out of Postgres onto the backfill topic in planned key ranges.
//! A rewritten row is harmless because the property store keeps the higher version.

use std::sync::Arc;
use std::time::Instant;

use bytes::Bytes;
use common_kafka::kafka_producer::KafkaContext;
use futures::future::try_join_all;
use metrics::{counter, histogram};
use personhog_common::partitioning::partition_for_person;
use personhog_common::properties::{
    parse_stored_properties, trim_properties_to_fit_size, TrimResult,
};
use personhog_property_store::object_store::path::Path as ObjectPath;
use personhog_property_store::object_store::{
    ObjectStore, ObjectStoreExt, PutMode, PutOptions, PutPayload,
};
use personhog_property_store::{PropertyRecord, PropertyStoreError};
use personhog_proto::personhog::types::v1::Person;
use prost::Message;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use serde_json::json;
use sqlx::{PgPool, Row};

const SAMPLES_PER_RANGE: f64 = 100.0;

#[derive(Debug, thiserror::Error)]
pub enum BackfillError {
    #[error("{0}")]
    Config(String),
    #[error("postgres: {0}")]
    Postgres(#[from] sqlx::Error),
    #[error("object store: {0}")]
    ObjectStore(#[from] personhog_property_store::object_store::Error),
    #[error("producing to the backfill topic: {0}")]
    Produce(String),
    #[error("progress record unreadable: {0}")]
    Progress(String),
    #[error("property store: {0}")]
    Store(#[from] PropertyStoreError),
}

#[derive(Debug, Clone)]
pub enum Scanned {
    Record(PropertyRecord),
    /// A record whose document was over the backfill topic's limit and was trimmed to fit.
    Trimmed(PropertyRecord),
    Reject {
        team_id: i64,
        person_id: i64,
        reason: String,
    },
}

impl Scanned {
    pub(crate) fn cursor(&self) -> Cursor {
        match self {
            Scanned::Record(record) | Scanned::Trimmed(record) => Cursor {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Cursor {
    pub team_id: i64,
    pub person_id: i64,
}

impl Cursor {
    fn to_json(self) -> serde_json::Value {
        json!({"team_id": self.team_id, "person_id": self.person_id})
    }

    fn from_json(value: &serde_json::Value) -> Result<Self, BackfillError> {
        let field = |name: &str| {
            value[name]
                .as_i64()
                .ok_or_else(|| BackfillError::Progress(format!("missing {name}")))
        };
        Ok(Self {
            team_id: field("team_id")?,
            person_id: field("person_id")?,
        })
    }
}

/// The rows of one table after `after` and through `through`; an absent bound is open.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyRange {
    pub table: String,
    pub after: Option<Cursor>,
    pub through: Option<Cursor>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan {
    pub ranges: Vec<KeyRange>,
}

impl Plan {
    fn to_json(&self) -> Vec<u8> {
        let ranges: Vec<_> = self
            .ranges
            .iter()
            .map(|range| {
                json!({
                    "table": range.table,
                    "after": range.after.map(Cursor::to_json),
                    "through": range.through.map(Cursor::to_json),
                })
            })
            .collect();
        json!({ "ranges": ranges }).to_string().into_bytes()
    }

    fn from_json(raw: &[u8]) -> Result<Self, BackfillError> {
        let value: serde_json::Value =
            serde_json::from_slice(raw).map_err(|e| BackfillError::Progress(e.to_string()))?;
        let ranges = value["ranges"]
            .as_array()
            .ok_or_else(|| BackfillError::Progress("missing ranges".to_string()))?;
        let bound = |range: &serde_json::Value, name: &str| match &range[name] {
            serde_json::Value::Null => Ok(None),
            cursor => Cursor::from_json(cursor).map(Some),
        };
        let ranges = ranges
            .iter()
            .map(|range| {
                let table = range["table"]
                    .as_str()
                    .ok_or_else(|| BackfillError::Progress("missing table".to_string()))?;
                validate_name(table, false)?;
                Ok(KeyRange {
                    table: table.to_string(),
                    after: bound(range, "after")?,
                    through: bound(range, "through")?,
                })
            })
            .collect::<Result<_, BackfillError>>()?;
        Ok(Self { ranges })
    }
}

/// A partitioned table's ranges come from its partitions, so no range spans two of them.
pub async fn plan(pool: &PgPool, table: &str, rows_per_range: i64) -> Result<Plan, BackfillError> {
    validate_name(table, false)?;
    let children: Vec<String> = sqlx::query_scalar(
        "SELECT c.relname::text FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid \
         WHERE i.inhparent = $1::text::regclass ORDER BY c.relname",
    )
    .bind(table)
    .fetch_all(pool)
    .await?;
    let tables = if children.is_empty() {
        vec![table.to_string()]
    } else {
        children
    };
    let mut ranges = Vec::new();
    for table in tables {
        validate_name(&table, false)?;
        let bounds = boundaries(pool, &table, rows_per_range.max(1)).await?;
        let mut after = None;
        for through in bounds {
            ranges.push(KeyRange {
                table: table.clone(),
                after,
                through: Some(through),
            });
            after = Some(through);
        }
        ranges.push(KeyRange {
            table,
            after,
            through: None,
        });
    }
    Ok(Plan { ranges })
}

async fn boundaries(
    pool: &PgPool,
    table: &str,
    rows_per_range: i64,
) -> Result<Vec<Cursor>, BackfillError> {
    // The planner's estimate, so no count runs over the table. -1 means never analyzed.
    let rows: f64 =
        sqlx::query_scalar("SELECT reltuples::float8 FROM pg_class WHERE oid = $1::text::regclass")
            .bind(table)
            .fetch_one(pool)
            .await?;
    if rows < 0.0 {
        tracing::warn!(
            table,
            "no row estimate; ANALYZE the table to split it into ranges"
        );
    }
    let ranges = (rows / rows_per_range as f64).ceil();
    if ranges <= 1.0 {
        return Ok(Vec::new());
    }
    let percent = (100.0 * ranges * SAMPLES_PER_RANGE / rows).min(100.0);
    let sample: Vec<(i32, i64)> = sqlx::query_as(&format!(
        "SELECT team_id, id FROM {table} TABLESAMPLE SYSTEM ($1) ORDER BY team_id, id"
    ))
    .bind(percent)
    .fetch_all(pool)
    .await?;
    let ranges = ranges as usize;
    let mut bounds: Vec<Cursor> = (1..ranges)
        .filter_map(|k| sample.get(sample.len() * k / ranges))
        .map(|&(team_id, person_id)| Cursor {
            team_id: i64::from(team_id),
            person_id,
        })
        .collect();
    bounds.dedup();
    Ok(bounds)
}

pub struct Scan {
    pool: PgPool,
    query: String,
    range: KeyRange,
    page_size: i64,
    limits: SizeLimits,
}

impl Scan {
    pub fn new(
        pool: PgPool,
        range: KeyRange,
        page_size: i64,
        limits: SizeLimits,
    ) -> Result<Self, BackfillError> {
        validate_name(&range.table, false)?;
        let upper = if range.through.is_some() {
            " AND (team_id, id) <= ($4, $5)"
        } else {
            ""
        };
        Ok(Self {
            pool,
            query: format!(
                "SELECT team_id, id, version, is_deleted, created_at, \
                 CASE WHEN is_deleted THEN NULL ELSE properties::text END AS properties \
                 FROM {} WHERE (team_id, id) > ($1, $2){upper} ORDER BY team_id, id LIMIT $3",
                range.table
            ),
            range,
            page_size: page_size.max(1),
            limits,
        })
    }

    pub fn start(&self) -> Cursor {
        self.range.after.unwrap_or(Cursor {
            team_id: i64::from(i32::MIN),
            person_id: i64::MIN,
        })
    }

    pub async fn page(&self, after: Cursor) -> Result<Vec<Scanned>, BackfillError> {
        let int4 = |team: i64| {
            i32::try_from(team)
                .map_err(|_| BackfillError::Progress(format!("cursor team {team} exceeds int4")))
        };
        let mut query = sqlx::query(&self.query)
            .bind(int4(after.team_id)?)
            .bind(after.person_id)
            .bind(self.page_size);
        if let Some(through) = self.range.through {
            query = query.bind(int4(through.team_id)?).bind(through.person_id);
        }
        let rows = query.fetch_all(&self.pool).await?;
        Ok(rows
            .iter()
            .map(|row| {
                let team_id: i32 = row.get("team_id");
                let person_id: i64 = row.get("id");
                let version: Option<i64> = row.get("version");
                let deleted: bool = row.get("is_deleted");
                let created_at: chrono::DateTime<chrono::Utc> = row.get("created_at");
                let text: Option<&str> = row.get("properties");
                to_scanned(
                    i64::from(team_id),
                    person_id,
                    version.unwrap_or(0),
                    deleted,
                    created_at.timestamp_millis(),
                    text,
                    &self.limits,
                )
            })
            .collect())
    }
}

pub struct TopicSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
    partitions: u32,
}

impl TopicSink {
    pub fn new(producer: FutureProducer<KafkaContext>, topic: String, partitions: u32) -> Self {
        Self {
            producer,
            topic,
            partitions,
        }
    }

    pub async fn send(&self, records: &[PropertyRecord]) -> Result<(), BackfillError> {
        let encoded: Vec<(String, Vec<u8>, i32)> = records
            .iter()
            .map(|record| {
                let person = Person {
                    team_id: record.team_id,
                    id: record.person_id,
                    version: record.version,
                    is_deleted: record.deleted,
                    created_at: record.created_at,
                    properties: record.properties.to_vec(),
                    ..Default::default()
                };
                let partition =
                    partition_for_person(record.team_id, record.person_id, self.partitions);
                (
                    format!("{}:{}", record.team_id, record.person_id),
                    person.encode_to_vec(),
                    partition as i32,
                )
            })
            .collect();
        try_join_all(encoded.iter().map(|(key, payload, partition)| async move {
            self.producer
                .send(
                    FutureRecord::to(&self.topic)
                        .partition(*partition)
                        .key(key)
                        .payload(payload),
                    Timeout::Never,
                )
                .await
                .map_err(|(e, _)| {
                    counter!("personhog_backfill_produce_errors_total").increment(1);
                    BackfillError::Produce(e.to_string())
                })
        }))
        .await?;
        Ok(())
    }
}

/// The backfill topic's message limit, and the size the leader trims a document to when it is
/// over its own threshold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SizeLimits {
    pub message_bytes: usize,
    pub trim_target: usize,
}

/// Matches the leader's Postgres load, so the store serves the bytes the leader would have. A
/// document the backfill topic would refuse is trimmed the way the leader trims one over its
/// threshold, since the leader would do that on the person's next write anyway.
pub(crate) fn to_scanned(
    team_id: i64,
    person_id: i64,
    version: i64,
    deleted: bool,
    created_at: i64,
    text: Option<&str>,
    limits: &SizeLimits,
) -> Scanned {
    let reject = |reason: String| Scanned::Reject {
        team_id,
        person_id,
        reason,
    };
    let (properties, trimmed) = match (deleted, text) {
        (true, _) | (false, None) => (Bytes::new(), false),
        (false, Some(text)) => {
            let parsed = match parse_stored_properties(text) {
                Ok(parsed) => parsed,
                Err(e) => return reject(e.to_string()),
            };
            match fit(&parsed.value, limits) {
                Ok((bytes, trimmed)) => (Bytes::from(bytes), trimmed),
                Err(reason) => return reject(reason),
            }
        }
    };
    let record = PropertyRecord {
        team_id,
        person_id,
        version,
        deleted,
        created_at,
        properties,
    };
    if trimmed {
        Scanned::Trimmed(record)
    } else {
        Scanned::Record(record)
    }
}

fn fit(value: &serde_json::Value, limits: &SizeLimits) -> Result<(Vec<u8>, bool), String> {
    let bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    if bytes.len() <= limits.message_bytes {
        return Ok((bytes, false));
    }
    let trimmed = match trim_properties_to_fit_size(value, limits.trim_target) {
        TrimResult::Trimmed(trimmed) => trimmed,
        TrimResult::Fits | TrimResult::CannotFit => {
            return Err(format!(
                "{} bytes exceed the backfill message limit and nothing can be trimmed",
                bytes.len()
            ))
        }
    };
    let bytes = serde_json::to_vec(&trimmed).map_err(|e| e.to_string())?;
    if bytes.len() <= limits.message_bytes {
        Ok((bytes, true))
    } else {
        Err(format!(
            "{} bytes still exceed the backfill message limit after trimming to {}",
            bytes.len(),
            limits.trim_target
        ))
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Counts {
    pub read: u64,
    pub written: u64,
    pub deleted: u64,
    pub trimmed: u64,
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
            "trimmed": self.trimmed,
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
                trimmed: field("trimmed")?,
                rejected: field("rejected")?,
            },
        ))
    }
}

pub struct Run {
    store: Arc<dyn ObjectStore>,
    root: String,
}

impl Run {
    /// A run's plan and progress live under `backfill/<run>` in the backfill state store.
    pub fn new(store: Arc<dyn ObjectStore>, run_id: &str) -> Result<Self, BackfillError> {
        validate_name(run_id, true)?;
        Ok(Self {
            store,
            root: format!("backfill/{run_id}"),
        })
    }

    fn plan_path(&self) -> ObjectPath {
        ObjectPath::from(format!("{}/plan", self.root))
    }

    /// A run keeps the plan it started with: its ranges' cursors refer to it.
    pub async fn save_plan(&self, plan: &Plan) -> Result<(), BackfillError> {
        match self
            .store
            .put_opts(
                &self.plan_path(),
                PutPayload::from(plan.to_json()),
                PutOptions::from(PutMode::Create),
            )
            .await
        {
            Ok(_) => Ok(()),
            Err(personhog_property_store::object_store::Error::AlreadyExists { .. }) => Err(
                BackfillError::Config(format!("{} already has a plan", self.root)),
            ),
            Err(e) => Err(e.into()),
        }
    }

    pub async fn plan(&self) -> Result<Plan, BackfillError> {
        match self.store.get(&self.plan_path()).await {
            Ok(found) => Plan::from_json(&found.bytes().await?),
            Err(personhog_property_store::object_store::Error::NotFound { .. }) => {
                Err(BackfillError::Config(format!(
                    "{} has no plan; run backfill-plan first",
                    self.root
                )))
            }
            Err(e) => Err(e.into()),
        }
    }

    pub fn range(&self, number: usize) -> Progress {
        Progress {
            store: Arc::clone(&self.store),
            root: format!("{}/ranges/{number:05}", self.root),
        }
    }
}

pub struct Progress {
    store: Arc<dyn ObjectStore>,
    root: String,
}

impl Progress {
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
}

pub enum Outcome {
    Finished(Counts),
    AlreadyDone(Counts),
}

/// Publishes every page before recording it, so a crash repeats at most one page.
pub async fn run_range(
    scan: &Scan,
    sink: &TopicSink,
    progress: &Progress,
) -> Result<Outcome, BackfillError> {
    if let Some(counts) = progress.finished().await? {
        return Ok(Outcome::AlreadyDone(counts));
    }
    let start = scan.start();
    let (mut after, mut counts) = progress.resume_point(start).await?;
    if after != start {
        tracing::info!(?after, ?counts, "resuming range");
    }
    loop {
        let started = Instant::now();
        let page = scan.page(after).await?;
        histogram!("personhog_backfill_page_seconds").record(started.elapsed().as_secs_f64());
        let Some(last) = page.last().map(Scanned::cursor) else {
            break;
        };
        let before = counts;
        let mut records = Vec::with_capacity(page.len());
        for scanned in page {
            counts.read += 1;
            if let Scanned::Trimmed(record) = &scanned {
                tracing::warn!(
                    team_id = record.team_id,
                    person_id = record.person_id,
                    "document trimmed to fit the backfill topic"
                );
                counts.trimmed += 1;
            }
            match scanned {
                Scanned::Record(record) | Scanned::Trimmed(record) => {
                    if record.deleted {
                        counts.deleted += 1;
                    }
                    counts.written += 1;
                    records.push(record);
                }
                Scanned::Reject {
                    team_id,
                    person_id,
                    reason,
                } => {
                    tracing::warn!(team_id, person_id, reason, "row rejected");
                    counts.rejected += 1;
                }
            }
        }
        for (outcome, rows) in [
            ("read", counts.read - before.read),
            ("written", counts.written - before.written),
            ("deleted", counts.deleted - before.deleted),
            ("trimmed", counts.trimmed - before.trimmed),
            ("rejected", counts.rejected - before.rejected),
        ] {
            counter!("personhog_backfill_rows_total", "outcome" => outcome).increment(rows);
        }
        sink.send(&records).await?;
        after = last;
        progress.write("cursor", counts.to_json(after)).await?;
        tracing::debug!(?after, ?counts, "page published");
    }
    progress.write("done", counts.to_json(after)).await?;
    Ok(Outcome::Finished(counts))
}

pub async fn run_worker(
    pool: &PgPool,
    sink: &TopicSink,
    run: &Run,
    index: usize,
    workers: usize,
    page_size: i64,
    limits: SizeLimits,
) -> Result<Counts, BackfillError> {
    if workers == 0 || index >= workers {
        return Err(BackfillError::Config(format!(
            "worker index {index} is outside {workers} workers"
        )));
    }
    let plan = run.plan().await?;
    let mut total = Counts::default();
    for (number, range) in plan
        .ranges
        .into_iter()
        .enumerate()
        .skip(index)
        .step_by(workers)
    {
        tracing::info!(number, ?range, "scanning range");
        let scan = Scan::new(pool.clone(), range, page_size, limits)?;
        let (outcome, counts) = match run_range(&scan, sink, &run.range(number)).await? {
            Outcome::Finished(counts) => ("finished", counts),
            Outcome::AlreadyDone(counts) => ("already_done", counts),
        };
        counter!("personhog_backfill_ranges_total", "outcome" => outcome).increment(1);
        tracing::info!(number, ?counts, "range finished");
        total.read += counts.read;
        total.written += counts.written;
        total.deleted += counts.deleted;
        total.trimmed += counts.trimmed;
        total.rejected += counts.rejected;
    }
    Ok(total)
}

/// The table is interpolated into SQL and the run id into an object path.
pub(crate) fn validate_name(value: &str, allow_dash: bool) -> Result<(), BackfillError> {
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

    const UNBOUNDED: SizeLimits = SizeLimits {
        message_bytes: usize::MAX,
        trim_target: usize::MAX,
    };

    fn record(scanned: Scanned) -> PropertyRecord {
        match scanned {
            Scanned::Record(record) => record,
            Scanned::Trimmed(record) => panic!("trimmed: {record:?}"),
            Scanned::Reject { reason, .. } => panic!("rejected: {reason}"),
        }
    }

    #[test]
    fn rows_are_stored_as_the_leader_would_load_them() {
        let live = record(to_scanned(
            7,
            1,
            3,
            false,
            1_700_000_000_000,
            Some(r#"{"a": 1, "b": "x"}"#),
            &UNBOUNDED,
        ));
        assert_eq!(&live.properties[..], br#"{"a":1,"b":"x"}"#);
        assert_eq!(live.created_at, 1_700_000_000_000);

        let huge = format!(r#"{{"n": 1{}}}"#, "0".repeat(400));
        let rewritten = record(to_scanned(7, 2, 3, false, 0, Some(&huge), &UNBOUNDED));
        let expected = parse_stored_properties(&huge).unwrap();
        assert!(
            expected.rewritten,
            "the fixture must need the numeric rewrite"
        );
        assert_eq!(
            rewritten.properties,
            Bytes::from(serde_json::to_vec(&expected.value).unwrap())
        );

        let deleted = record(to_scanned(7, 3, 5, true, 0, None, &UNBOUNDED));
        assert!(deleted.deleted && deleted.properties.is_empty());
    }

    #[test]
    fn a_row_no_parse_can_read_is_rejected_with_its_person() {
        let nested = format!("{}1{}", "[".repeat(200), "]".repeat(200));
        match to_scanned(7, 9, 1, false, 0, Some(&nested), &UNBOUNDED) {
            Scanned::Reject { person_id, .. } => assert_eq!(person_id, 9),
            Scanned::Record(_) | Scanned::Trimmed(_) => {
                panic!("a document serde cannot parse was accepted")
            }
        }
    }

    #[test]
    fn a_document_over_the_message_limit_is_trimmed_like_the_leader_would() {
        let big = "x".repeat(600);
        let text = format!(r#"{{"email": "keep", "note": "{big}", "tag": "{big}"}}"#);
        let limits = SizeLimits {
            message_bytes: 700,
            trim_target: 300,
        };

        let trimmed = match to_scanned(7, 4, 2, false, 0, Some(&text), &limits) {
            Scanned::Trimmed(record) => record,
            other => panic!("expected a trimmed record, got {other:?}"),
        };
        let document: serde_json::Value = serde_json::from_slice(&trimmed.properties).unwrap();

        assert!(trimmed.properties.len() <= limits.message_bytes);
        assert_eq!(document["email"], "keep");
        assert!(matches!(
            to_scanned(
                7,
                5,
                2,
                false,
                0,
                Some(&text),
                &SizeLimits {
                    message_bytes: 10,
                    trim_target: 300
                }
            ),
            Scanned::Reject { person_id: 5, .. }
        ));
    }

    #[test]
    fn a_plan_reads_back_as_written() {
        let cursor = |team_id, person_id| Cursor { team_id, person_id };
        let plan = Plan {
            ranges: vec![
                KeyRange {
                    table: "posthog_person_p0".to_string(),
                    after: None,
                    through: Some(cursor(7, i64::MAX)),
                },
                KeyRange {
                    table: "posthog_person_p0".to_string(),
                    after: Some(cursor(7, i64::MAX)),
                    through: None,
                },
            ],
        };

        assert_eq!(Plan::from_json(&plan.to_json()).unwrap(), plan);
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
