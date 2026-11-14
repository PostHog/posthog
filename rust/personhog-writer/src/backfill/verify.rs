//! Compares a Postgres snapshot with SlateDB person by person, by version. A SlateDB record newer
//! than the snapshot is a write after it; anything else that differs is a divergence, logged by id.

use std::sync::Arc;
use std::time::Duration;

use metrics::counter;
use personhog_common::properties::parse_stored_properties;
use personhog_property_store::object_store::path::Path as ObjectPath;
use personhog_property_store::object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use personhog_property_store::{
    PropertyReader, PropertyRecord, PropertyStoreError, StoredProperties,
};
use serde_json::json;
use sqlx::{PgPool, Row};

use crate::backfill::scanner::{
    to_scanned, validate_name, BackfillError, Run, Scan, Scanned, SizeLimits,
};

const READ_RETRIES: usize = 3;
const READ_RETRY_BACKOFF: Duration = Duration::from_secs(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Match,
    /// The same version with different content: the stores disagree about one write.
    Differs,
    /// A write the snapshot predates.
    NewerInSlatedb,
    /// A write the snapshot has and SlateDB lacks.
    Behind,
    Missing,
}

impl Verdict {
    pub fn label(self) -> &'static str {
        match self {
            Verdict::Match => "match",
            Verdict::Differs => "differs",
            Verdict::NewerInSlatedb => "newer_in_slatedb",
            Verdict::Behind => "behind",
            Verdict::Missing => "missing",
        }
    }
}

pub fn judge(row: &PropertyRecord, stored: Option<&StoredProperties>) -> Verdict {
    let Some(stored) = stored else {
        // Identity creates empty stubs at version 0 without a changelog record, and a full
        // compaction may have removed a deleted person's marker.
        return if row.deleted || (row.version == 0 && empty_document(&row.properties)) {
            Verdict::Match
        } else {
            Verdict::Missing
        };
    };
    if stored.version > row.version {
        return Verdict::NewerInSlatedb;
    }
    // Identity revives a deleted person empty, above the marker's version, without a record.
    if stored.deleted && stored.version < row.version && !row.deleted {
        return if empty_document(&row.properties) {
            Verdict::Match
        } else {
            Verdict::Behind
        };
    }
    if stored.version < row.version {
        return Verdict::Behind;
    }
    if row.deleted || stored.deleted {
        return if row.deleted == stored.deleted {
            Verdict::Match
        } else {
            Verdict::Differs
        };
    }
    if same_json(&row.properties, &stored.properties) {
        Verdict::Match
    } else {
        Verdict::Differs
    }
}

fn empty_document(bytes: &[u8]) -> bool {
    bytes.is_empty() || bytes == b"{}"
}

/// Postgres normalizes `jsonb`, so the bytes differ even when the documents do not.
fn same_json(a: &[u8], b: &[u8]) -> bool {
    match (
        serde_json::from_slice::<serde_json::Value>(a),
        serde_json::from_slice::<serde_json::Value>(b),
    ) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

/// The snapshot went through Postgres `jsonb`, which prints a float such as `1.7e18` as an integer,
/// so SlateDB's document takes the same path before it is compared again.
async fn same_through_postgres(
    pool: &PgPool,
    snapshot: &[u8],
    slatedb: &[u8],
) -> Result<bool, BackfillError> {
    let Ok(slatedb) = std::str::from_utf8(slatedb) else {
        return Ok(false);
    };
    let printed: String = match sqlx::query_scalar("SELECT $1::jsonb::text")
        .bind(slatedb)
        .fetch_one(pool)
        .await
    {
        Ok(printed) => printed,
        Err(sqlx::Error::Database(e)) if e.code().is_some_and(|code| code.starts_with("22")) => {
            return Ok(false);
        }
        Err(e) => return Err(e.into()),
    };
    let Ok(printed) = parse_stored_properties(&printed) else {
        return Ok(false);
    };
    Ok(serde_json::from_slice::<serde_json::Value>(snapshot)
        .is_ok_and(|snapshot| snapshot == printed.value))
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct VerifyCounts {
    pub checked: u64,
    pub matched: u64,
    pub differs: u64,
    pub behind: u64,
    pub missing: u64,
    pub newer_in_slatedb: u64,
    pub rejected: u64,
}

impl VerifyCounts {
    fn add(&mut self, outcome: &str) {
        self.checked += 1;
        match outcome {
            "match" => self.matched += 1,
            "differs" => self.differs += 1,
            "behind" => self.behind += 1,
            "missing" => self.missing += 1,
            "newer_in_slatedb" => self.newer_in_slatedb += 1,
            _ => self.rejected += 1,
        }
    }

    fn merge(&mut self, other: VerifyCounts) {
        self.checked += other.checked;
        self.matched += other.matched;
        self.differs += other.differs;
        self.behind += other.behind;
        self.missing += other.missing;
        self.newer_in_slatedb += other.newer_in_slatedb;
        self.rejected += other.rejected;
    }

    pub fn divergent(&self) -> u64 {
        self.differs + self.behind + self.missing + self.rejected
    }

    fn to_json(self) -> Vec<u8> {
        json!({
            "checked": self.checked,
            "matched": self.matched,
            "differs": self.differs,
            "behind": self.behind,
            "missing": self.missing,
            "newer_in_slatedb": self.newer_in_slatedb,
            "rejected": self.rejected,
        })
        .to_string()
        .into_bytes()
    }

    fn from_json(raw: &[u8]) -> Result<Self, BackfillError> {
        let value: serde_json::Value =
            serde_json::from_slice(raw).map_err(|e| BackfillError::Progress(e.to_string()))?;
        let field = |name: &str| {
            value[name]
                .as_u64()
                .ok_or_else(|| BackfillError::Progress(format!("missing {name}")))
        };
        Ok(Self {
            checked: field("checked")?,
            matched: field("matched")?,
            differs: field("differs")?,
            behind: field("behind")?,
            missing: field("missing")?,
            newer_in_slatedb: field("newer_in_slatedb")?,
            rejected: field("rejected")?,
        })
    }
}

/// A verification run's progress, under `verify/<run>` in the backfill state store.
pub struct Verification {
    store: Arc<dyn ObjectStore>,
    root: String,
}

impl Verification {
    pub fn new(store: Arc<dyn ObjectStore>, run_id: &str) -> Result<Self, BackfillError> {
        validate_name(run_id, true)?;
        Ok(Self {
            store,
            root: format!("verify/{run_id}"),
        })
    }

    fn path(&self, name: &str) -> ObjectPath {
        ObjectPath::from(format!("{}/{name}", self.root))
    }

    pub async fn finished(&self, number: usize) -> Result<Option<VerifyCounts>, BackfillError> {
        match self
            .store
            .get(&self.path(&format!("ranges/{number:05}/done")))
            .await
        {
            Ok(found) => Ok(Some(VerifyCounts::from_json(&found.bytes().await?)?)),
            Err(personhog_property_store::object_store::Error::NotFound { .. }) => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    async fn mark_done(&self, number: usize, counts: VerifyCounts) -> Result<(), BackfillError> {
        self.store
            .put(
                &self.path(&format!("ranges/{number:05}/done")),
                PutPayload::from(counts.to_json()),
            )
            .await?;
        Ok(())
    }
}

/// The live database's row for one person, which `properties get` shows beside SlateDB's.
pub struct Live {
    pool: PgPool,
    query: String,
    limits: SizeLimits,
}

impl Live {
    pub fn new(pool: PgPool, table: &str, limits: SizeLimits) -> Result<Self, BackfillError> {
        validate_name(table, false)?;
        Ok(Self {
            pool,
            query: format!(
                "SELECT version, is_deleted, created_at, \
                 CASE WHEN is_deleted THEN NULL ELSE properties::text END AS properties \
                 FROM {table} WHERE team_id = $1 AND id = $2"
            ),
            limits,
        })
    }

    pub async fn row(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<Scanned>, BackfillError> {
        let team = i32::try_from(team_id)
            .map_err(|_| BackfillError::Progress(format!("team {team_id} exceeds int4")))?;
        let row = sqlx::query(&self.query)
            .bind(team)
            .bind(person_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.map(|row| {
            let version: Option<i64> = row.get("version");
            let deleted: bool = row.get("is_deleted");
            let created_at: chrono::DateTime<chrono::Utc> = row.get("created_at");
            let text: Option<&str> = row.get("properties");
            to_scanned(
                team_id,
                person_id,
                version.unwrap_or(0),
                deleted,
                created_at.timestamp_millis(),
                text,
                &self.limits,
            )
        }))
    }
}

/// SlateDB answers a read eventually; a few retries cover a slow open or a timeout.
async fn read(
    reader: &PropertyReader,
    team_id: i64,
    person_id: i64,
) -> Result<Option<StoredProperties>, BackfillError> {
    retrying(team_id, person_id, || reader.get(team_id, person_id)).await
}

async fn retrying<F, Fut>(
    team_id: i64,
    person_id: i64,
    mut read: F,
) -> Result<Option<StoredProperties>, BackfillError>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<Option<StoredProperties>, PropertyStoreError>>,
{
    let mut attempt = 0;
    loop {
        match read().await {
            Ok(stored) => return Ok(stored),
            Err(e) if attempt < READ_RETRIES => {
                attempt += 1;
                tracing::debug!(team_id, person_id, error = %e, "property store read failed; retrying");
                tokio::time::sleep(READ_RETRY_BACKOFF).await;
            }
            Err(e) => return Err(e.into()),
        }
    }
}

/// The outcome for one snapshot row, with the row and record the verdict rests on.
async fn check(
    reader: &PropertyReader,
    pool: &PgPool,
    row: PropertyRecord,
) -> Result<(&'static str, PropertyRecord, Option<StoredProperties>), BackfillError> {
    let stored = read(reader, row.team_id, row.person_id).await?;
    let verdict = match (judge(&row, stored.as_ref()), &stored) {
        (Verdict::Differs, Some(record)) if !row.deleted && !record.deleted => {
            if same_through_postgres(pool, &row.properties, &record.properties).await? {
                Verdict::Match
            } else {
                Verdict::Differs
            }
        }
        (verdict, _) => verdict,
    };
    Ok((verdict.label(), row, stored))
}

/// The stores a verification reads, and where it records what it finds.
pub struct Verifier<'a> {
    pub pool: &'a PgPool,
    pub reader: &'a PropertyReader,
    pub verification: &'a Verification,
    /// The scanner's limits, so a document the scan trimmed compares in its trimmed form.
    pub limits: SizeLimits,
}

impl Verifier<'_> {
    /// A restarted worker redoes an unfinished range from its start, since every row is judged alone.
    pub async fn run_range(
        &self,
        scan: &Scan,
        number: usize,
        sample_every: usize,
    ) -> Result<VerifyCounts, BackfillError> {
        if let Some(counts) = self.verification.finished(number).await? {
            counter!("personhog_verify_ranges_total", "outcome" => "already_done").increment(1);
            return Ok(counts);
        }
        let step = sample_every.max(1);
        let mut counts = VerifyCounts::default();
        let mut after = scan.start();
        loop {
            let page = scan.page(after).await?;
            let Some(last) = page.last().map(Scanned::cursor) else {
                break;
            };
            for scanned in page.into_iter().step_by(step) {
                let (outcome, row, stored) = match scanned {
                    Scanned::Record(row) | Scanned::Trimmed(row) => {
                        check(self.reader, self.pool, row).await?
                    }
                    Scanned::Reject {
                        team_id,
                        person_id,
                        reason,
                    } => {
                        tracing::warn!(team_id, person_id, reason, "row rejected");
                        counts.add("rejected");
                        counter!("personhog_verify_persons_total", "outcome" => "rejected")
                            .increment(1);
                        continue;
                    }
                };
                counts.add(outcome);
                counter!("personhog_verify_persons_total", "outcome" => outcome).increment(1);
                if matches!(outcome, "differs" | "behind" | "missing") {
                    tracing::warn!(
                        team_id = row.team_id,
                        person_id = row.person_id,
                        outcome,
                        postgres_version = row.version,
                        postgres_deleted = row.deleted,
                        slatedb_version = stored.as_ref().map(|s| s.version),
                        slatedb_deleted = stored.as_ref().map(|s| s.deleted),
                        "person differs between postgres and slatedb"
                    );
                }
            }
            after = last;
        }
        self.verification.mark_done(number, counts).await?;
        counter!("personhog_verify_ranges_total", "outcome" => "finished").increment(1);
        Ok(counts)
    }

    pub async fn run_worker(
        &self,
        run: &Run,
        index: usize,
        workers: usize,
        page_size: i64,
        sample_every: usize,
    ) -> Result<VerifyCounts, BackfillError> {
        if workers == 0 || index >= workers {
            return Err(BackfillError::Config(format!(
                "worker index {index} is outside {workers} workers"
            )));
        }
        let plan = run.plan().await?;
        let mut total = VerifyCounts::default();
        for (number, range) in plan
            .ranges
            .into_iter()
            .enumerate()
            .skip(index)
            .step_by(workers)
        {
            tracing::info!(number, ?range, "verifying range");
            let scan = Scan::new(self.pool.clone(), range, page_size, self.limits)?;
            let counts = self.run_range(&scan, number, sample_every).await?;
            tracing::info!(number, ?counts, "range verified");
            total.merge(counts);
        }
        Ok(total)
    }
}

#[cfg(test)]
mod tests {
    use personhog_property_store::bytes::Bytes;

    use super::*;

    fn row(version: i64, deleted: bool, properties: &'static str) -> PropertyRecord {
        PropertyRecord {
            team_id: 7,
            person_id: 1,
            version,
            deleted,
            created_at: 0,
            properties: Bytes::from_static(properties.as_bytes()),
        }
    }

    fn stored(version: i64, deleted: bool, properties: &'static str) -> StoredProperties {
        StoredProperties {
            version,
            deleted,
            created_at: 0,
            properties: Bytes::from_static(properties.as_bytes()),
        }
    }

    #[test]
    fn a_verdict_rests_on_the_version_first_and_the_document_second() {
        let cases = [
            (
                "same version, same document",
                row(4, false, r#"{"a":1,"b":2}"#),
                Some(stored(4, false, r#"{"b":2,"a":1}"#)),
                Verdict::Match,
            ),
            (
                "same version, different document",
                row(4, false, r#"{"a":1}"#),
                Some(stored(4, false, r#"{"a":2}"#)),
                Verdict::Differs,
            ),
            (
                "slatedb newer",
                row(4, false, "{}"),
                Some(stored(5, false, "{}")),
                Verdict::NewerInSlatedb,
            ),
            (
                "slatedb behind",
                row(4, false, "{}"),
                Some(stored(3, false, "{}")),
                Verdict::Behind,
            ),
            (
                "missing live person",
                row(4, false, "{}"),
                None,
                Verdict::Missing,
            ),
            (
                "untouched identity stub",
                row(0, false, "{}"),
                None,
                Verdict::Match,
            ),
            (
                "version-0 row with properties and no record",
                row(0, false, r#"{"a":1}"#),
                None,
                Verdict::Missing,
            ),
            (
                "deleted row, marker compacted away",
                row(4, true, ""),
                None,
                Verdict::Match,
            ),
            (
                "deleted row, marker at its version",
                row(4, true, ""),
                Some(stored(4, true, "")),
                Verdict::Match,
            ),
            (
                "empty identity revival over the marker",
                row(6, false, "{}"),
                Some(stored(5, true, "")),
                Verdict::Match,
            ),
            (
                "revival with properties the marker predates",
                row(6, false, r#"{"a":1}"#),
                Some(stored(5, true, "")),
                Verdict::Behind,
            ),
            (
                "deleted row, live record at its version",
                row(4, true, ""),
                Some(stored(4, false, "{}")),
                Verdict::Differs,
            ),
        ];
        for (name, row, stored, expected) in cases {
            assert_eq!(judge(&row, stored.as_ref()), expected, "{name}");
        }
    }

    #[test]
    fn the_cutover_gate_counts_rows_the_scan_rejected() {
        let counts = VerifyCounts {
            rejected: 1,
            ..VerifyCounts::default()
        };

        assert_eq!(counts.divergent(), 1);
    }
}
