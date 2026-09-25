//! A long-lived handle on one Delta table, owning the open/refresh orchestration
//! around [`crate::upsert::upsert_cached`].
//!
//! Production measured ~81% of an upsert's wall-clock outside plan/rewrite/commit, and
//! the cause was full Delta-log replays: the previous binding-level orchestration
//! re-opened the table from scratch once per conflict-retry attempt and once more after
//! the commit, each a checkpoint read plus every commit since. This handle loads the
//! snapshot once at open and afterwards only applies newer commits incrementally
//! (`update_incremental`), which is one log LIST plus the handful of new commit JSONs.

use std::collections::HashMap;
use std::time::Instant;

use arrow_array::RecordBatch;
use arrow_schema::SchemaRef;
use deltalake::DeltaTable;

use crate::errors::{Error, Result};
use crate::table::{open_table, wrap_multipart, MultipartConfig};
use crate::upsert::{upsert_cached, RelaxCache, UpsertOptions, UpsertStats};

/// Conflict-retry budget for one upsert call. A concurrent writer can make delta-rs
/// reject the commit with a "must rerun" conflict (it read data another transaction
/// deleted); delta-rs's own commit retries re-attempt the SAME, now-stale actions and
/// keep conflicting, so the only fix is to refresh the snapshot and re-plan.
const CONFLICT_RETRIES: usize = 5;

/// A loaded Delta table plus the per-table caches that make repeated small upserts
/// cheap: the snapshot (refreshed incrementally, never rebuilt) and the relax memo.
pub struct TableHandle {
    uri: String,
    storage_options: HashMap<String, String>,
    table: DeltaTable,
    relax_cache: RelaxCache,
}

impl TableHandle {
    /// Open an existing Delta table (one full snapshot load).
    pub async fn open(uri: String, storage_options: HashMap<String, String>) -> Result<Self> {
        let table = open_table(&uri, storage_options.clone()).await?;
        Ok(Self {
            uri,
            storage_options,
            table,
            relax_cache: RelaxCache::default(),
        })
    }

    /// The table URI this handle was opened on.
    pub fn uri(&self) -> &str {
        &self.uri
    }

    /// The loaded table, for read paths (schema, files, history).
    pub fn table(&self) -> &DeltaTable {
        &self.table
    }

    /// The table version this handle currently observes (-1 before any load).
    pub fn version(&self) -> i64 {
        self.table
            .version()
            .and_then(|v| i64::try_from(v).ok())
            .unwrap_or(-1)
    }

    /// Bring the snapshot up to date with commits made elsewhere. Incremental (applies
    /// only commits newer than the loaded version); falls back to a full re-open when
    /// the incremental path fails -- e.g. the table was deleted and recreated at a
    /// lower version, which is not reachable forward from the loaded state.
    pub async fn refresh(&mut self) -> Result<()> {
        if self.table.update_incremental(None).await.is_ok() {
            return Ok(());
        }
        self.table = open_table(&self.uri, self.storage_options.clone()).await?;
        // The old snapshot is gone; nothing the relax memo verified can be trusted.
        self.relax_cache = RelaxCache::default();
        Ok(())
    }

    /// Run one upsert, retrying data conflicts against a refreshed snapshot.
    ///
    /// Only data conflicts are retried. A concurrent schema/protocol change surfaces as
    /// `Error::Unsupported` (see core `errors.rs`), not `Conflict`, and so breaks
    /// straight out to the caller's MERGE fallback -- re-planning a blind rewrite
    /// against changed metadata could null-pad a newly-added column.
    pub async fn upsert(
        &mut self,
        source_batches: Vec<RecordBatch>,
        source_schema: SchemaRef,
        opts: UpsertOptions,
        multipart: MultipartConfig,
    ) -> Result<UpsertStats> {
        let mut open_ms = 0u64;

        // Observe commits made elsewhere since this handle last looked, so the first
        // attempt plans against current state (the previous per-call full re-open gave
        // the same guarantee at a full log-replay's cost).
        let t = Instant::now();
        self.refresh().await?;
        open_ms += t.elapsed().as_millis() as u64;

        let mut attempt = 0usize;
        loop {
            // A per-attempt view over the shared snapshot: cloning state is in-memory,
            // wrapping the store is free, and the handle keeps its own table untouched
            // for the refreshes below.
            let view = wrap_multipart(self.table.clone(), multipart);
            match upsert_cached(
                &view,
                source_batches.clone(),
                source_schema.clone(),
                opts.clone(),
                &mut self.relax_cache,
            )
            .await
            {
                Err(Error::Conflict(_)) if attempt < CONFLICT_RETRIES => {
                    attempt += 1;
                    // Short linear backoff so two upserts racing a hot table don't
                    // live-lock re-reading each other's in-flight commit.
                    tokio::time::sleep(std::time::Duration::from_millis(50 * attempt as u64)).await;
                    let t = Instant::now();
                    self.refresh().await?;
                    open_ms += t.elapsed().as_millis() as u64;
                }
                Ok(mut stats) => {
                    // Pick up our own commit (and any relax/maintenance commits), so
                    // reads through this handle observe what was just written.
                    let t = Instant::now();
                    self.refresh().await?;
                    open_ms += t.elapsed().as_millis() as u64;
                    stats.open_ms = open_ms;
                    return Ok(stats);
                }
                Err(e) => return Err(e),
            }
        }
    }
}
