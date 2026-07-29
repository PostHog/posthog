//! Python bindings for `deltalite-core` (imported as `deltalite`).
//!
//! Every entry point releases the GIL for the I/O-heavy work and runs it on a
//! process-wide tokio runtime. Errors surface as a typed exception hierarchy rooted at
//! `DeltaLiteError`, so the caller can branch on kind instead of sniffing error text.

use std::collections::HashMap;
use std::sync::{Arc, OnceLock};

use arrow::array::ArrayData;
use arrow::pyarrow::{FromPyArrow, ToPyArrow};
use arrow_array::{new_empty_array, Array, RecordBatch};
use arrow_schema::SchemaRef;
use deltalake::writer::RecordBatchWriter;
use deltalake::DeltaTable;
use deltalite_core::errors::Error;
use deltalite_core::limits::ProcessLimits;
use deltalite_core::schema::import_column;
use deltalite_core::table::{open_table, open_table_multipart, MultipartConfig};
use deltalite_core::upsert::{PruneStrategy, UpsertOptions};
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde_json::Value;

create_exception!(deltalite, DeltaLiteError, PyException);
create_exception!(deltalite, DeltaLiteCommitConflictError, DeltaLiteError);
create_exception!(deltalite, DeltaLiteSchemaMismatchError, DeltaLiteError);
create_exception!(deltalite, DeltaLiteTableNotFoundError, DeltaLiteError);
create_exception!(deltalite, DeltaLiteUnsupportedTableError, DeltaLiteError);
create_exception!(deltalite, DeltaLiteSourceTooLargeError, DeltaLiteError);

/// Map a core error onto the matching Python exception class.
fn to_py_err(e: Error) -> PyErr {
    let msg = e.to_string();
    match e {
        Error::SchemaMismatch(_) => DeltaLiteSchemaMismatchError::new_err(msg),
        Error::NotFound(_) => DeltaLiteTableNotFoundError::new_err(msg),
        Error::Unsupported(_) => DeltaLiteUnsupportedTableError::new_err(msg),
        Error::Conflict(_) => DeltaLiteCommitConflictError::new_err(msg),
        Error::SourceTooLarge(_) => DeltaLiteSourceTooLargeError::new_err(msg),
        Error::Generic(_) => DeltaLiteError::new_err(msg),
    }
}

fn runtime() -> &'static tokio::runtime::Runtime {
    static RT: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
    RT.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            // Unreachable outside of catastrophic resource exhaustion at import time;
            // there is no Python-visible fallible path to surface it on.
            .expect("failed to build tokio runtime")
    })
}

/// Ingest a pyarrow object (`pa.Table`, `pa.RecordBatch`, `pa.RecordBatchReader`).
///
/// Deliberately imported **column by column as `ArrayData`** rather than straight to a
/// `RecordBatch`. arrow-rs asserts that a `Decimal128` value buffer is 16-byte aligned
/// while constructing the *typed* array, and buffers arriving over the C Data Interface
/// from pyarrow are only guaranteed 8-byte aligned (an Arrow IPC round-trip reliably
/// produces one) -- that assert is delta-io/delta-rs#3884, and it fires *inside* the
/// import, before any `RecordBatch` exists to repair. `ArrayData` carries untyped
/// buffers and skips the assert, giving `deltalite_core::schema::realign_array_data` a
/// chance to copy-realign first.
///
/// The table's chunks are deliberately NOT combined: `combine_chunks` copies the whole
/// source into fresh contiguous buffers, and upsert consumes multiple batches natively.
/// `to_batches()` re-chunks to aligned boundaries by zero-copy slicing, so this import
/// shares the caller's buffers instead of duplicating them.
fn read_pyarrow(obj: &Bound<'_, PyAny>) -> PyResult<(SchemaRef, Vec<RecordBatch>)> {
    let py = obj.py();
    let err = |e: PyErr| DeltaLiteError::new_err(format!("pyarrow ingest: {e}"));

    // Normalise whatever we were handed into a pa.Table.
    let mut obj = obj.clone();
    if obj.hasattr("read_all").map_err(err)? {
        obj = obj.call_method0("read_all").map_err(err)?;
    }
    if !obj.hasattr("to_batches").map_err(err)? {
        let pa = py.import("pyarrow").map_err(err)?;
        obj = pa
            .getattr("Table")
            .map_err(err)?
            .call_method1("from_batches", (vec![obj.clone()],))
            .map_err(err)?;
    }
    let table = obj;

    let schema: SchemaRef = Arc::new(
        arrow_schema::Schema::from_pyarrow_bound(&table.getattr("schema").map_err(err)?)
            .map_err(err)?,
    );

    let py_batches: Vec<Bound<'_, PyAny>> = table
        .call_method0("to_batches")
        .map_err(err)?
        .extract()
        .map_err(err)?;

    let mut batches: Vec<RecordBatch> = Vec::with_capacity(py_batches.len());
    for pyb in py_batches {
        let num_rows: usize = pyb
            .getattr("num_rows")
            .map_err(err)?
            .extract()
            .map_err(err)?;

        let mut columns: Vec<Arc<dyn Array>> = Vec::with_capacity(schema.fields().len());
        for (i, field) in schema.fields().iter().enumerate() {
            let col = pyb.call_method1("column", (i,)).map_err(err)?;
            let array: Arc<dyn Array> = if num_rows == 0 {
                new_empty_array(field.data_type())
            } else {
                let data = ArrayData::from_pyarrow_bound(&col).map_err(err)?;
                import_column(data).map_err(to_py_err)?
            };
            columns.push(array);
        }
        batches.push(
            RecordBatch::try_new(schema.clone(), columns)
                .map_err(|e| DeltaLiteError::new_err(format!("assembling imported batch: {e}")))?,
        );
    }

    if batches.is_empty() {
        // A zero-chunk table produces no batches; keep the empty-source path alive
        // (an empty upsert must still land a tagged commit).
        batches.push(RecordBatch::new_empty(schema.clone()));
    }

    Ok((schema, batches))
}

/// Counters describing what one `upsert` did.
#[pyclass(module = "deltalite", skip_from_py_object)]
#[derive(Clone, Debug, Default)]
pub struct UpsertStats {
    #[pyo3(get)]
    pub version: i64,
    #[pyo3(get)]
    pub partitions_touched: usize,
    #[pyo3(get)]
    pub files_removed: usize,
    #[pyo3(get)]
    pub files_added: usize,
    #[pyo3(get)]
    pub files_carried_over: usize,
    #[pyo3(get)]
    pub files_probed: usize,
    #[pyo3(get)]
    pub rows_updated: usize,
    #[pyo3(get)]
    pub rows_inserted: usize,
    #[pyo3(get)]
    pub rows_copied: usize,
    #[pyo3(get)]
    pub source_rows: usize,
    #[pyo3(get)]
    pub null_pk_rows: usize,
}

#[pymethods]
impl UpsertStats {
    fn __repr__(&self) -> String {
        format!(
            "UpsertStats(version={}, partitions_touched={}, files_added={}, files_removed={}, \
             files_carried_over={}, files_probed={}, rows_updated={}, rows_inserted={}, \
             rows_copied={})",
            self.version,
            self.partitions_touched,
            self.files_added,
            self.files_removed,
            self.files_carried_over,
            self.files_probed,
            self.rows_updated,
            self.rows_inserted,
            self.rows_copied
        )
    }
}

impl From<deltalite_core::upsert::UpsertStats> for UpsertStats {
    fn from(s: deltalite_core::upsert::UpsertStats) -> Self {
        Self {
            version: s.version,
            partitions_touched: s.partitions_touched,
            files_removed: s.files_removed,
            files_added: s.files_added,
            files_carried_over: s.files_carried_over,
            files_probed: s.files_probed,
            rows_updated: s.rows_updated,
            rows_inserted: s.rows_inserted,
            rows_copied: s.rows_copied,
            source_rows: s.source_rows,
            null_pk_rows: s.null_pk_rows,
        }
    }
}

/// A handle on a Delta table for deltalite writes. Reads (schema, history, file
/// listing) exist for parity tooling; production read paths stay on the Python
/// `deltalake` package -- both address the same `_delta_log`.
#[pyclass(module = "deltalite")]
pub struct DeltaLiteTable {
    uri: String,
    storage_options: HashMap<String, String>,
    table: DeltaTable,
}

#[pymethods]
impl DeltaLiteTable {
    /// Open an existing Delta table.
    #[staticmethod]
    #[pyo3(signature = (uri, storage_options = None))]
    fn open(
        py: Python<'_>,
        uri: String,
        storage_options: Option<HashMap<String, String>>,
    ) -> PyResult<Self> {
        let so = storage_options.unwrap_or_default();
        let so2 = so.clone();
        let table = py
            .detach(|| runtime().block_on(open_table(&uri, so2)))
            .map_err(to_py_err)?;
        Ok(Self {
            uri,
            storage_options: so,
            table,
        })
    }

    /// Whether `uri` points at a loadable Delta table.
    #[staticmethod]
    #[pyo3(signature = (uri, storage_options = None))]
    fn is_deltatable(
        py: Python<'_>,
        uri: String,
        storage_options: Option<HashMap<String, String>>,
    ) -> PyResult<bool> {
        let so = storage_options.unwrap_or_default();
        Ok(py
            .detach(|| runtime().block_on(open_table(&uri, so)))
            .is_ok())
    }

    /// The table version this handle currently observes (-1 before any load).
    fn version(&self) -> i64 {
        self.table
            .version()
            .and_then(|v| i64::try_from(v).ok())
            .unwrap_or(-1)
    }

    /// Re-read the log so this handle observes commits made elsewhere.
    fn reload(&mut self, py: Python<'_>) -> PyResult<()> {
        let uri = self.uri.clone();
        let so = self.storage_options.clone();
        self.table = py
            .detach(|| runtime().block_on(open_table(&uri, so)))
            .map_err(to_py_err)?;
        Ok(())
    }

    /// The table's Arrow schema, as the write path will expect it.
    fn schema_arrow(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let schema = RecordBatchWriter::for_table(&self.table)
            .map_err(|e| to_py_err(Error::from(e)))?
            .arrow_schema();
        Ok(schema.to_pyarrow(py)?.into())
    }

    /// The table's partition columns (possibly empty).
    fn partition_columns(&self) -> PyResult<Vec<String>> {
        let snapshot = self.table.snapshot().map_err(|e| to_py_err(e.into()))?;
        Ok(snapshot.metadata().partition_columns().to_vec())
    }

    /// URIs of the live data files.
    fn file_uris(&self) -> PyResult<Vec<String>> {
        Ok(self
            .table
            .get_file_uris()
            .map_err(|e| to_py_err(e.into()))?
            .collect::<Vec<_>>())
    }

    /// The core replacement for `DeltaTable.merge(...).when_matched_update_all()
    /// .when_not_matched_insert_all().execute()`.
    ///
    /// `prune_strategy` selects how the rewrite set is chosen per partition:
    /// - `"none"`: rewrite every live file.
    /// - `"stats"`: skip files whose Add-action stats prove no match (min/max on the
    ///   first PK column, all-NULL PK columns).
    /// - `"probe"` (default): stats first, then read only the PK column(s) of each
    ///   surviving file and skip those that contain no matched row. Exact, like MERGE.
    ///
    /// When `prune_strategy` is not given, `skip_unmatched_files=False` maps to
    /// `"none"` and the default `True` maps to `"probe"`.
    ///
    /// `max_source_bytes` guards against oversized batches (resident source + estimated
    /// PK set); `0` disables the guard, `None` uses `DELTALITE_MAX_SOURCE_BYTES` or the
    /// built-in 2 GiB default. `multipart_threshold` / `multipart_part_size` control
    /// multipart upload of output files (`0` threshold disables).
    #[pyo3(signature = (
        data,
        primary_keys,
        partition_key = None,
        *,
        commit_metadata = None,
        max_parallel_partitions = 2,
        max_parallel_files = 4,
        max_buffered_bytes = 67108864,
        skip_unmatched_files = true,
        prune_strategy = None,
        probe_concurrency = 8,
        commit_max_retries = 15,
        read_batch_size = 8192,
        target_file_size = None,
        max_source_bytes = None,
        multipart_threshold = None,
        multipart_part_size = None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn upsert(
        &mut self,
        py: Python<'_>,
        data: &Bound<'_, PyAny>,
        primary_keys: Vec<String>,
        partition_key: Option<String>,
        commit_metadata: Option<HashMap<String, String>>,
        max_parallel_partitions: usize,
        max_parallel_files: usize,
        max_buffered_bytes: usize,
        skip_unmatched_files: bool,
        prune_strategy: Option<String>,
        probe_concurrency: usize,
        commit_max_retries: usize,
        read_batch_size: usize,
        target_file_size: Option<usize>,
        max_source_bytes: Option<usize>,
        multipart_threshold: Option<usize>,
        multipart_part_size: Option<usize>,
    ) -> PyResult<UpsertStats> {
        // Import while holding the GIL (it reads a Python object), then release it for
        // all the I/O.
        let (schema, batches) = read_pyarrow(data)?;

        let prune_strategy = match prune_strategy.as_deref() {
            Some(s) => s.parse::<PruneStrategy>().map_err(to_py_err)?,
            None if skip_unmatched_files => PruneStrategy::Probe,
            None => PruneStrategy::None,
        };

        let opts = UpsertOptions {
            primary_keys,
            partition_key,
            commit_metadata: commit_metadata.map(|m| {
                m.into_iter()
                    .map(|(k, v)| (k, Value::String(v)))
                    .collect::<HashMap<String, Value>>()
            }),
            max_parallel_partitions,
            prune_strategy,
            probe_concurrency,
            max_parallel_files,
            max_buffered_bytes,
            commit_max_retries,
            read_batch_size,
            target_file_size,
            max_source_bytes,
            // Shared with every other concurrent upsert in this process, so the
            // process-level memory bound holds regardless of thread count.
            limits: ProcessLimits::global().clone(),
        };
        let multipart = MultipartConfig::resolve(multipart_threshold, multipart_part_size);

        let uri = self.uri.clone();
        let so = self.storage_options.clone();
        let stats = py
            .detach(|| {
                runtime().block_on(async move {
                    // Take a fresh snapshot for the upsert so a retried batch never
                    // plans against stale state.
                    let table = open_table_multipart(&uri, so, multipart).await?;
                    deltalite_core::upsert::upsert(&table, batches, schema, opts).await
                })
            })
            .map_err(to_py_err)?;

        self.reload(py)?;
        Ok(stats.into())
    }

    /// Commit metadata of the most recent `limit` commits, oldest first.
    fn history(&self, py: Python<'_>, limit: usize) -> PyResult<Py<PyAny>> {
        let table = self.table.clone();
        let infos = py
            .detach(|| {
                runtime().block_on(async move {
                    let h: Vec<_> = table.history(Some(limit)).await?.collect();
                    Ok::<_, Error>(h)
                })
            })
            .map_err(to_py_err)?;

        let out = PyList::empty(py);
        for info in infos {
            let d = PyDict::new(py);
            d.set_item("operation", info.operation.clone())?;
            let flat = PyDict::new(py);
            for (k, v) in &info.info {
                flat.set_item(k, v.to_string())?;
            }
            d.set_item("info", flat)?;
            out.append(d)?;
        }
        Ok(out.into())
    }
}

#[pymodule]
fn deltalite(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<DeltaLiteTable>()?;
    m.add_class::<UpsertStats>()?;
    m.add("DeltaLiteError", m.py().get_type::<DeltaLiteError>())?;
    m.add(
        "DeltaLiteCommitConflictError",
        m.py().get_type::<DeltaLiteCommitConflictError>(),
    )?;
    m.add(
        "DeltaLiteSchemaMismatchError",
        m.py().get_type::<DeltaLiteSchemaMismatchError>(),
    )?;
    m.add(
        "DeltaLiteTableNotFoundError",
        m.py().get_type::<DeltaLiteTableNotFoundError>(),
    )?;
    m.add(
        "DeltaLiteUnsupportedTableError",
        m.py().get_type::<DeltaLiteUnsupportedTableError>(),
    )?;
    m.add(
        "DeltaLiteSourceTooLargeError",
        m.py().get_type::<DeltaLiteSourceTooLargeError>(),
    )?;
    Ok(())
}
