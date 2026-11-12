use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use futures::stream::{self, StreamExt, TryStreamExt};

use crate::express::{is_replicated, Bucket};
use crate::object_store;
use object_store::path::Path;
use object_store::{ObjectStore, ObjectStoreExt, PutMode, PutOptions};

#[derive(Debug, Default, PartialEq, Eq)]
pub struct RepairReport {
    pub checked: usize,
    pub copied: usize,
    pub removed: usize,
    pub failed: usize,
}

pub struct RepairOptions {
    /// A copy can briefly precede its original, because the tee writes both at once.
    pub orphan_min_age: Duration,
    /// Each in-flight copy holds one whole SST in memory.
    pub concurrency: usize,
    pub dry_run: bool,
}

async fn replicated_ssts(
    store: &Arc<dyn ObjectStore>,
    prefix: &Path,
) -> object_store::Result<HashMap<Path, chrono::DateTime<chrono::Utc>>> {
    store
        .list(Some(prefix))
        .try_filter(|meta| std::future::ready(is_replicated(&meta.location)))
        .map_ok(|meta| (meta.location, meta.last_modified))
        .try_collect()
        .await
}

async fn copy_one(
    primary: &Arc<dyn ObjectStore>,
    bucket: &Bucket,
    location: &Path,
) -> object_store::Result<bool> {
    let body = match primary.get(location).await {
        Ok(result) => result.bytes().await?,
        // Collected since the listing, so there is nothing left to copy.
        Err(object_store::Error::NotFound { .. }) => return Ok(false),
        Err(e) => return Err(e),
    };
    bucket
        .store
        .put_opts(location, body.into(), PutOptions::from(PutMode::Overwrite))
        .await?;
    Ok(true)
}

pub async fn repair_bucket(
    primary: &Arc<dyn ObjectStore>,
    bucket: &Bucket,
    prefix: &Path,
    options: &RepairOptions,
) -> object_store::Result<RepairReport> {
    let originals = replicated_ssts(primary, prefix).await?;
    let copies = replicated_ssts(&bucket.store, prefix).await?;
    let mut report = RepairReport {
        checked: originals.len(),
        ..RepairReport::default()
    };

    let missing: Vec<&Path> = originals
        .keys()
        .filter(|p| !copies.contains_key(*p))
        .collect();
    let cutoff = chrono::Utc::now()
        - chrono::Duration::from_std(options.orphan_min_age).unwrap_or(chrono::Duration::MAX);
    let present: HashSet<&Path> = originals.keys().collect();
    let orphans: Vec<&Path> = copies
        .iter()
        .filter(|(path, modified)| !present.contains(path) && **modified < cutoff)
        .map(|(path, _)| path)
        .collect();
    if options.dry_run {
        report.copied = missing.len();
        report.removed = orphans.len();
        return Ok(report);
    }

    let copied: Vec<object_store::Result<bool>> = stream::iter(missing)
        .map(|location| copy_one(primary, bucket, location))
        .buffer_unordered(options.concurrency.max(1))
        .collect()
        .await;
    for result in copied {
        match result {
            Ok(true) => report.copied += 1,
            Ok(false) => {}
            Err(e) => {
                tracing::warn!(bucket = %bucket.name, error = %e, "copying an sst failed");
                report.failed += 1;
            }
        }
    }

    for location in orphans {
        match bucket.store.delete(location).await {
            Ok(()) | Err(object_store::Error::NotFound { .. }) => report.removed += 1,
            Err(e) => {
                tracing::warn!(bucket = %bucket.name, error = %e, "removing an orphaned copy failed");
                report.failed += 1;
            }
        }
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use object_store::memory::InMemory;
    use object_store::PutPayload;
    use rstest::rstest;

    use super::*;

    fn sst(name: &str) -> Path {
        Path::from(format!("props/shard-00000/compacted/{name}.sst"))
    }

    async fn put(store: &Arc<dyn ObjectStore>, location: &Path, body: &'static [u8]) {
        store
            .put(location, PutPayload::from_static(body))
            .await
            .unwrap();
    }

    async fn exists(store: &Arc<dyn ObjectStore>, location: &Path) -> bool {
        store.head(location).await.is_ok()
    }

    #[rstest]
    #[case::removes_old_orphans(Duration::ZERO, false, 1, 1)]
    #[case::keeps_young_orphans(Duration::from_secs(3600), false, 1, 0)]
    #[case::dry_run_changes_nothing(Duration::ZERO, true, 1, 1)]
    #[tokio::test]
    async fn a_bucket_ends_up_with_exactly_standards_ssts(
        #[case] orphan_min_age: Duration,
        #[case] dry_run: bool,
        #[case] copied: usize,
        #[case] removed: usize,
    ) {
        let primary: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let copy: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let manifest = Path::from("props/shard-00000/manifest/00000000000000000001.manifest");
        put(&primary, &sst("present"), b"present").await;
        put(&primary, &sst("missing"), b"missing").await;
        put(&primary, &manifest, b"manifest").await;
        put(&copy, &sst("present"), b"present").await;
        put(&copy, &sst("orphan"), b"orphan").await;
        let bucket = Bucket::new("copy", Arc::clone(&copy));

        let report = repair_bucket(
            &primary,
            &bucket,
            &Path::from("props"),
            &RepairOptions {
                orphan_min_age,
                concurrency: 2,
                dry_run,
            },
        )
        .await
        .unwrap();

        assert_eq!(
            report,
            RepairReport {
                checked: 2,
                copied,
                removed,
                failed: 0
            }
        );
        assert_eq!(exists(&copy, &sst("missing")).await, !dry_run);
        assert_eq!(exists(&copy, &sst("orphan")).await, dry_run || removed == 0);
        assert!(!exists(&copy, &manifest).await);
    }
}
