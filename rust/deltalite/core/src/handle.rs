//! A long-lived handle on one Delta table, owning the open/refresh orchestration
//! around [`crate::upsert::upsert_cached`].
//!
//! Production measured ~81% of an upsert's wall-clock outside plan/rewrite/commit, and
//! the cause was full Delta-log replays: the previous binding-level orchestration
//! re-opened the table from scratch once per conflict-retry attempt and once more after
//! the commit, each a checkpoint read plus every commit since. This handle loads the
//! snapshot once at open and afterwards only applies newer commits incrementally
//! (`update_incremental`), which is one log LIST plus the handful of new commit JSONs.
//! After its own commit it does not read the log at all: it adopts the state delta-rs
//! derived for that commit.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use arrow_array::RecordBatch;
use arrow_schema::SchemaRef;
use deltalake::DeltaTable;

use crate::errors::{Error, Result};
use crate::prefetch::CheckpointCache;
use crate::table::{open_table_prefetched, wrap_multipart, MultipartConfig};
use crate::upsert::{upsert_cached_with_state, RelaxCache, UpsertOptions, UpsertStats};

/// Conflict-retry budget for one upsert call. A concurrent writer can make delta-rs
/// reject the commit with a "must rerun" conflict (it read data another transaction
/// deleted); delta-rs's own commit retries re-attempt the SAME, now-stale actions and
/// keep conflicting, so the only fix is to refresh the snapshot and re-plan.
const CONFLICT_RETRIES: usize = 5;

/// Kill switch for adopting the commit's own snapshot after an upsert; `0` (or `false`,
/// `off`, `no`) restores the post-commit log refresh. Unset or any other value keeps
/// the adoption on.
pub const ADOPT_COMMIT_SNAPSHOT_ENV: &str = "DELTALITE_ADOPT_COMMIT_SNAPSHOT";

/// Whether the setting `value` of [`ADOPT_COMMIT_SNAPSHOT_ENV`] keeps the adoption on.
pub fn adopt_commit_snapshot_setting(value: Option<&str>) -> bool {
    match value {
        Some(v) => !matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "0" | "false" | "off" | "no"
        ),
        None => true,
    }
}

fn adopt_commit_snapshot_from_env() -> bool {
    adopt_commit_snapshot_setting(std::env::var(ADOPT_COMMIT_SNAPSHOT_ENV).ok().as_deref())
}

/// One live data file as the loaded snapshot records it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LiveFile {
    /// Path relative to the table root, URL-decoded.
    pub path: String,
    /// Size in bytes from the Add action.
    pub size: i64,
    /// Modification time in milliseconds since the Unix epoch, from the Add action.
    pub modification_time: i64,
    /// Partition column values as the log stores them (strings; `None` is a null
    /// partition value). Empty for an unpartitioned table.
    pub partition_values: HashMap<String, Option<String>>,
}

/// A loaded Delta table plus the per-table caches that make repeated small upserts
/// cheap: the snapshot (refreshed incrementally, never rebuilt) and the relax memo.
pub struct TableHandle {
    uri: String,
    storage_options: HashMap<String, String>,
    table: DeltaTable,
    relax_cache: RelaxCache,
    /// Checkpoint bytes the table's stores served the last load from; cleared after
    /// every load so a handle idling between upserts holds only its snapshot.
    prefetch: Arc<CheckpointCache>,
    adopt_commit_snapshot: bool,
    initial_open_ms: u64,
    initial_open_reported: bool,
}

impl TableHandle {
    /// Open an existing Delta table (one full snapshot load).
    pub async fn open(uri: String, storage_options: HashMap<String, String>) -> Result<Self> {
        let started = Instant::now();
        let (table, prefetch) = open_table_prefetched(&uri, storage_options.clone()).await?;
        prefetch.clear();
        Ok(Self {
            uri,
            storage_options,
            table,
            relax_cache: RelaxCache::default(),
            prefetch,
            adopt_commit_snapshot: adopt_commit_snapshot_from_env(),
            initial_open_ms: started.elapsed().as_millis() as u64,
            initial_open_reported: false,
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

    /// Wall-clock ms the full snapshot load in [`TableHandle::open`] took.
    pub fn initial_open_ms(&self) -> u64 {
        self.initial_open_ms
    }

    /// Whether an upsert adopts its commit's snapshot instead of refreshing afterwards
    /// (see [`ADOPT_COMMIT_SNAPSHOT_ENV`]).
    pub fn adopt_commit_snapshot(&self) -> bool {
        self.adopt_commit_snapshot
    }

    /// Override the [`ADOPT_COMMIT_SNAPSHOT_ENV`] setting for this handle.
    pub fn set_adopt_commit_snapshot(&mut self, adopt: bool) {
        self.adopt_commit_snapshot = adopt;
    }

    /// The table id from the snapshot's metadata action.
    pub fn table_id(&self) -> Result<String> {
        Ok(self.table.snapshot()?.metadata().id().to_string())
    }

    /// The table configuration (`delta.*` properties and any custom keys).
    pub fn configuration(&self) -> Result<HashMap<String, String>> {
        Ok(self.table.snapshot()?.metadata().configuration().clone())
    }

    /// The Delta schema of the loaded snapshot as its JSON document
    /// (`{"type":"struct","fields":[...]}`).
    pub fn schema_json(&self) -> Result<String> {
        let schema = self.table.snapshot()?.schema();
        serde_json::to_string(schema.as_ref())
            .map_err(|e| Error::Generic(format!("serialising table schema: {e}")))
    }

    /// Number of live data files in the loaded snapshot.
    pub fn num_files(&self) -> Result<usize> {
        Ok(self.table.snapshot()?.log_data().num_files())
    }

    /// The live data files of the loaded snapshot, served from memory.
    pub fn files(&self) -> Result<Vec<LiveFile>> {
        let snapshot = self.table.snapshot()?;
        Ok(snapshot
            .log_data()
            .iter()
            .map(|view| {
                // The only public accessor for the raw partition-value strings; the
                // parsed form would need re-encoding and can be narrowed by a predicate.
                #[allow(deprecated)]
                let add = view.add_action();
                LiveFile {
                    path: add.path,
                    size: add.size,
                    modification_time: add.modification_time,
                    partition_values: add.partition_values,
                }
            })
            .collect())
    }

    /// Bring the snapshot up to date with commits made elsewhere. Incremental (applies
    /// only commits newer than the loaded version); falls back to a full re-open when
    /// the incremental path fails -- e.g. the table was deleted and recreated at a
    /// lower version, which is not reachable forward from the loaded state.
    pub async fn refresh(&mut self) -> Result<()> {
        if self.table.update_incremental(None).await.is_ok() {
            self.prefetch.clear();
            return Ok(());
        }
        let (table, prefetch) =
            open_table_prefetched(&self.uri, self.storage_options.clone()).await?;
        prefetch.clear();
        self.table = table;
        self.prefetch = prefetch;
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
            match upsert_cached_with_state(
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
                Ok((mut stats, state)) => {
                    // Reads through this handle must observe what was just written. The
                    // commit already yielded the resulting state (a relax commit sits
                    // under it; a checkpoint written by maintenance describes the same
                    // version and the next refresh adopts it), so adopting it costs no
                    // I/O. The refresh stays as the kill-switch path.
                    let t = Instant::now();
                    if self.adopt_commit_snapshot {
                        self.table.state = Some(state);
                        self.prefetch.clear();
                    } else {
                        self.refresh().await?;
                    }
                    open_ms += t.elapsed().as_millis() as u64;
                    stats.open_ms = open_ms;
                    stats.initial_open_ms = self.take_initial_open_ms();
                    return Ok(stats);
                }
                Err(e) => return Err(e),
            }
        }
    }

    /// The open cost, handed out once so per-upsert stats sum to the handle's total.
    fn take_initial_open_ms(&mut self) -> u64 {
        if self.initial_open_reported {
            return 0;
        }
        self.initial_open_reported = true;
        self.initial_open_ms
    }
}

#[cfg(test)]
mod tests {
    use super::adopt_commit_snapshot_setting;

    #[test]
    fn adoption_is_on_unless_the_switch_turns_it_off() {
        assert!(adopt_commit_snapshot_setting(None));
        assert!(adopt_commit_snapshot_setting(Some("1")));
        assert!(adopt_commit_snapshot_setting(Some("true")));
        assert!(adopt_commit_snapshot_setting(Some("")));
        for off in ["0", "false", "off", "no", " OFF ", "False"] {
            assert!(!adopt_commit_snapshot_setting(Some(off)), "{off:?}");
        }
    }
}
