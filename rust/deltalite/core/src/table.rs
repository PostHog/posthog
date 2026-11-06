//! Table opening helpers.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use deltalake::{DeltaTable, DeltaTableBuilder};

use crate::errors::{Error, Result};
use crate::prefetch::{CheckpointCache, CheckpointPrefetchLogStore};
use crate::store::{CommitProbe, MultipartLogStore};

/// How data files are uploaded and read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MultipartConfig {
    /// Files at or above this size upload as multipart; 0 disables the rewrite.
    pub threshold: usize,
    /// Part size for multipart uploads (clamped to >= 5 MiB by the store wrapper).
    pub part_size: usize,
    /// Parts of one multipart upload in flight at once; 1 uploads them one after another.
    pub concurrency: usize,
    /// A ranged read of a data file larger than this is split into concurrent requests of
    /// this size.
    pub range_part_size: usize,
    /// Requests of one split ranged read in flight at once; 1 disables the split.
    pub range_concurrency: usize,
}

impl Default for MultipartConfig {
    fn default() -> Self {
        Self::resolve_with(None, None, None, None, None, |_, default| default)
    }
}

impl MultipartConfig {
    /// Resolve from explicit arguments, then `DELTALITE_MULTIPART_THRESHOLD_BYTES`,
    /// `DELTALITE_MULTIPART_PART_SIZE_BYTES`, `DELTALITE_MULTIPART_CONCURRENCY`,
    /// `DELTALITE_RANGE_GET_PART_SIZE_BYTES` and `DELTALITE_RANGE_GET_CONCURRENCY`, then the
    /// defaults. An explicit `Some(0)` threshold disables multipart entirely.
    ///
    /// The threshold and part size default to the serial values when the concurrency is 1,
    /// so a concurrency of 1 restores the upload behavior from before concurrent parts.
    pub fn resolve(
        threshold: Option<usize>,
        part_size: Option<usize>,
        concurrency: Option<usize>,
        range_part_size: Option<usize>,
        range_concurrency: Option<usize>,
    ) -> Self {
        Self::resolve_with(
            threshold,
            part_size,
            concurrency,
            range_part_size,
            range_concurrency,
            crate::limits::env_usize,
        )
    }

    fn resolve_with(
        threshold: Option<usize>,
        part_size: Option<usize>,
        concurrency: Option<usize>,
        range_part_size: Option<usize>,
        range_concurrency: Option<usize>,
        env: impl Fn(&str, usize) -> usize,
    ) -> Self {
        use crate::store::{
            DEFAULT_MULTIPART_CONCURRENCY, DEFAULT_MULTIPART_PART_SIZE,
            DEFAULT_MULTIPART_THRESHOLD, DEFAULT_RANGE_GET_CONCURRENCY,
            DEFAULT_RANGE_GET_PART_SIZE, SERIAL_MULTIPART_PART_SIZE, SERIAL_MULTIPART_THRESHOLD,
        };
        let concurrency = concurrency
            .unwrap_or_else(|| {
                env(
                    "DELTALITE_MULTIPART_CONCURRENCY",
                    DEFAULT_MULTIPART_CONCURRENCY,
                )
            })
            .max(1);
        let (default_threshold, default_part_size) = if concurrency > 1 {
            (DEFAULT_MULTIPART_THRESHOLD, DEFAULT_MULTIPART_PART_SIZE)
        } else {
            (SERIAL_MULTIPART_THRESHOLD, SERIAL_MULTIPART_PART_SIZE)
        };
        Self {
            threshold: threshold
                .unwrap_or_else(|| env("DELTALITE_MULTIPART_THRESHOLD_BYTES", default_threshold)),
            part_size: part_size
                .unwrap_or_else(|| env("DELTALITE_MULTIPART_PART_SIZE_BYTES", default_part_size)),
            concurrency,
            range_part_size: range_part_size
                .unwrap_or_else(|| {
                    env(
                        "DELTALITE_RANGE_GET_PART_SIZE_BYTES",
                        DEFAULT_RANGE_GET_PART_SIZE,
                    )
                })
                .max(1),
            range_concurrency: range_concurrency
                .unwrap_or_else(|| {
                    env(
                        "DELTALITE_RANGE_GET_CONCURRENCY",
                        DEFAULT_RANGE_GET_CONCURRENCY,
                    )
                })
                .max(1),
        }
    }
}

/// HTTP client settings that deltalite gives an S3 table when the caller sets none.
///
/// - `timeout` bounds one request, from connect until the response body ends. The
///   largest single requests are a whole-object read of a checkpoint (up to the
///   checkpoint prefetch cap, 128 MiB) and a single PUT below the multipart threshold
///   (up to 64 MiB when parts upload one after another). `object_store` uses 30s, which
///   cuts such a request below about 4 MB/s on one connection. 120s keeps those
///   requests above about 1 MB/s, and a timed out request is retried.
/// - `connect_timeout` is the `object_store` value, set here so that a change of that
///   default does not change deltalite.
/// - `pool_idle_timeout` stays below the 20s after which S3 closes an idle connection,
///   the same value delta-rs gives its own S3 client. A connection that a proxy or a
///   NAT drops without a reset makes the next request on it wait for the full request
///   timeout; a short idle time makes that less frequent.
///
/// An explicit storage option wins, under any spelling that `object_store` accepts
/// (`timeout`, `aws_timeout`, any case), and so does the environment variable that
/// `object_store` reads for the key (for example `AWS_TIMEOUT`).
pub const S3_CLIENT_DEFAULTS: [(&str, &str); 3] = [
    ("timeout", "120s"),
    ("connect_timeout", "5s"),
    ("pool_idle_timeout", "15s"),
];

/// The `object_store` client key that the option or environment variable `name` sets,
/// for the keys in [`S3_CLIENT_DEFAULTS`]. This is the parsing of
/// `AmazonS3ConfigKey::from_str` for those keys.
fn client_key(name: &str) -> Option<&'static str> {
    let lower = name.to_ascii_lowercase();
    let key = lower.strip_prefix("aws_").unwrap_or(&lower);
    S3_CLIENT_DEFAULTS
        .iter()
        .map(|(k, _)| *k)
        .find(|k| *k == key)
}

/// `storage_options` with each key of [`S3_CLIENT_DEFAULTS`] that neither the options
/// nor the environment (`env_names`) set. Only S3 tables get the defaults; other stores
/// do not read these keys.
fn with_s3_client_defaults<'a>(
    scheme: &str,
    mut storage_options: HashMap<String, String>,
    env_names: impl IntoIterator<Item = &'a str>,
) -> HashMap<String, String> {
    if !matches!(scheme, "s3" | "s3a") {
        return storage_options;
    }
    let set: HashSet<&'static str> = storage_options
        .keys()
        .filter_map(|k| client_key(k))
        .chain(env_names.into_iter().filter_map(client_key))
        .collect();
    for (key, value) in S3_CLIENT_DEFAULTS {
        if !set.contains(key) {
            storage_options.insert(key.to_string(), value.to_string());
        }
    }
    storage_options
}

fn storage_options_for(
    scheme: &str,
    storage_options: HashMap<String, String>,
) -> HashMap<String, String> {
    let env: Vec<String> = std::env::vars_os()
        .filter_map(|(k, _)| k.into_string().ok())
        .collect();
    with_s3_client_defaults(scheme, storage_options, env.iter().map(String::as_str))
}

/// Open and load a Delta table from `uri` with the given delta-rs `storage_options`
/// (the same keys the Python package accepts; the dict passes through unchanged, plus
/// [`S3_CLIENT_DEFAULTS`] for the keys it does not set).
///
/// The load reads its checkpoint through the prefetch wrapper (see [`crate::prefetch`])
/// and releases the prefetched bytes before returning, so the table costs no more memory
/// than a plain load once it is open.
pub async fn open_table(uri: &str, storage_options: HashMap<String, String>) -> Result<DeltaTable> {
    let (table, prefetch) = open_table_prefetched(uri, storage_options).await?;
    // Nothing clears the cache after later operations on this table, so it must not
    // collect the commit files that they read and write.
    prefetch.stop_caching_commits();
    prefetch.clear();
    Ok(table)
}

/// `deltalake.DeltaTable.is_deltatable`'s check. It loads nothing, so a table with a damaged
/// log still counts as present.
pub async fn table_exists(uri: &str, storage_options: HashMap<String, String>) -> Result<bool> {
    let Ok(url) = deltalake::ensure_table_uri(uri) else {
        return Ok(false);
    };
    let storage_options = storage_options_for(url.scheme(), storage_options);
    let Ok(builder) = DeltaTableBuilder::from_url(url) else {
        return Ok(false);
    };
    let table = builder.with_storage_options(storage_options).build()?;
    Ok(table.verify_deltatable_existence().await?)
}

/// [`open_table`] that also hands back the checkpoint cache the table's stores serve
/// from, still holding the checkpoint bytes read by this load. The caller clears it once
/// it is done and can clear it again after each later load through the same table.
pub async fn open_table_prefetched(
    uri: &str,
    storage_options: HashMap<String, String>,
) -> Result<(DeltaTable, Arc<CheckpointCache>)> {
    let url = deltalake::ensure_table_uri(uri)
        .map_err(|e| Error::NotFound(format!("invalid table uri {uri}: {e}")))?;
    let storage_options = storage_options_for(url.scheme(), storage_options);
    let built = DeltaTableBuilder::from_url(url)?
        .with_storage_options(storage_options)
        .build()?;
    let cache = Arc::new(CheckpointCache::from_env());
    let log_store = Arc::new(CheckpointPrefetchLogStore::new(
        built.log_store(),
        cache.clone(),
    ));
    let mut table = DeltaTable::new(log_store, built.config.clone());
    table.load().await?;
    Ok((table, cache))
}

/// Open a table whose data-file uploads go through the multipart-aware store wrapper
/// (see [`crate::store`]). Commit-entry writes keep the inner log store's conditional
/// -put path untouched.
pub async fn open_table_multipart(
    uri: &str,
    storage_options: HashMap<String, String>,
    multipart: MultipartConfig,
) -> Result<DeltaTable> {
    let table = open_table(uri, storage_options).await?;
    Ok(wrap_multipart(table, multipart))
}

/// Re-home an already-loaded table onto the multipart-aware store wrapper, without I/O.
/// The loaded snapshot moves across as-is: the wrapper changes how large data-file
/// `put`s are performed, never what the log contains, so replaying the log under the
/// wrapped store would rebuild an identical snapshot at a full log-replay's cost.
pub fn wrap_multipart(table: DeltaTable, multipart: MultipartConfig) -> DeltaTable {
    if multipart.threshold == 0 {
        return table;
    }
    let wrapped = Arc::new(MultipartLogStore::new(table.log_store(), multipart));
    let mut wrapped_table = DeltaTable::new(wrapped, Default::default());
    wrapped_table.state = table.state;
    wrapped_table
}

/// [`wrap_multipart`] for a handle's view of its table. `commit_probe` lets a commit
/// through the view skip the LIST before the commit put (see [`CommitProbe`]). Always
/// wraps; a zero threshold keeps every upload a single put.
pub(crate) fn wrap_multipart_view(
    table: DeltaTable,
    multipart: MultipartConfig,
    commit_probe: Option<CommitProbe>,
) -> DeltaTable {
    let multipart = MultipartConfig {
        threshold: if multipart.threshold == 0 {
            usize::MAX
        } else {
            multipart.threshold
        },
        ..multipart
    };
    let mut wrapped = MultipartLogStore::new(table.log_store(), multipart);
    if let Some(probe) = commit_probe {
        wrapped = wrapped.with_commit_probe(probe);
    }
    let mut wrapped_table = DeltaTable::new(Arc::new(wrapped), Default::default());
    wrapped_table.state = table.state;
    wrapped_table
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::{
        DEFAULT_MULTIPART_PART_SIZE, DEFAULT_MULTIPART_THRESHOLD, SERIAL_MULTIPART_PART_SIZE,
        SERIAL_MULTIPART_THRESHOLD,
    };

    #[test]
    fn s3_tables_get_client_defaults_for_keys_the_caller_does_not_set() {
        let defaults: HashMap<String, String> = S3_CLIENT_DEFAULTS
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        let opts = |pairs: &[(&str, &str)]| -> HashMap<String, String> {
            pairs
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect()
        };
        let with = |overrides: &[(&str, &str)]| {
            let mut m = defaults.clone();
            m.extend(opts(overrides));
            m
        };
        type Options = HashMap<String, String>;
        let cases: Vec<(&str, Options, Vec<&str>, Options)> = vec![
            ("s3", opts(&[]), vec![], defaults.clone()),
            ("s3a", opts(&[]), vec![], defaults.clone()),
            (
                "s3",
                opts(&[("region", "us-east-1")]),
                vec![],
                with(&[("region", "us-east-1")]),
            ),
            // An explicit value under any spelling object_store accepts wins.
            (
                "s3",
                opts(&[("timeout", "300s")]),
                vec![],
                with(&[("timeout", "300s")]),
            ),
            ("s3", opts(&[("AWS_CONNECT_TIMEOUT", "1s")]), vec![], {
                let mut m = with(&[("AWS_CONNECT_TIMEOUT", "1s")]);
                m.remove("connect_timeout");
                m
            }),
            // The environment variable object_store reads for a key also wins.
            ("s3", opts(&[]), vec!["AWS_POOL_IDLE_TIMEOUT", "HOME"], {
                let mut m = defaults.clone();
                m.remove("pool_idle_timeout");
                m
            }),
            ("file", opts(&[]), vec![], opts(&[])),
            ("memory", opts(&[("a", "b")]), vec![], opts(&[("a", "b")])),
        ];
        for (scheme, given, env, expected) in cases {
            let got = with_s3_client_defaults(scheme, given.clone(), env);
            assert_eq!(got, expected, "{scheme} {given:?}");
        }
    }

    #[test]
    fn concurrency_one_restores_the_serial_upload_defaults() {
        let no_env = |_: &str, default: usize| default;
        let parallel = MultipartConfig::resolve_with(None, None, None, None, None, no_env);
        assert_eq!(parallel.threshold, DEFAULT_MULTIPART_THRESHOLD);
        assert_eq!(parallel.part_size, DEFAULT_MULTIPART_PART_SIZE);
        assert!(parallel.concurrency > 1 && parallel.range_concurrency > 1);

        let serial = MultipartConfig::resolve_with(None, None, Some(1), None, Some(1), no_env);
        assert_eq!(serial.threshold, SERIAL_MULTIPART_THRESHOLD);
        assert_eq!(serial.part_size, SERIAL_MULTIPART_PART_SIZE);

        let env_serial = MultipartConfig::resolve_with(None, None, None, None, None, |name, d| {
            if name == "DELTALITE_MULTIPART_CONCURRENCY" {
                1
            } else {
                d
            }
        });
        assert_eq!(env_serial.threshold, SERIAL_MULTIPART_THRESHOLD);

        let explicit =
            MultipartConfig::resolve_with(Some(0), Some(6), Some(0), Some(0), Some(0), no_env);
        assert_eq!(
            (explicit.threshold, explicit.part_size, explicit.concurrency),
            (0, 6, 1)
        );
        assert_eq!(
            (explicit.range_part_size, explicit.range_concurrency),
            (1, 1)
        );
    }
}
