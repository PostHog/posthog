use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures::stream::{BoxStream, StreamExt};
use personhog_property_store::{
    shard_for, Compression, PartitionKey, PropertyReader, PropertyRecord, PropertyStoreConfig,
    PropertyStoreError, PropertyWriter, PutError, StoredProperties,
};
use slatedb::admin::Admin;
use slatedb::config::{GarbageCollectorDirectoryOptions, GarbageCollectorOptions};
use slatedb::object_store::local::LocalFileSystem;
use slatedb::object_store::path::Path as ObjectPath;
use slatedb::object_store::{
    self as object_store, CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload,
    ObjectMeta, ObjectStore, PutMultipartOptions, PutOptions, PutPayload, PutResult,
};
use slatedb_common::clock::MockSystemClock;

const SHARDS: u32 = 4;

fn config() -> PropertyStoreConfig {
    PropertyStoreConfig {
        reader_poll_ms: 20,
        ..PropertyStoreConfig::local("props", SHARDS)
    }
}

fn store(dir: &tempfile::TempDir) -> Arc<dyn ObjectStore> {
    Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap())
}

fn sole_partition() -> PartitionKey {
    PartitionKey {
        topic: Arc::from("changelog"),
        partition: 0,
    }
}

fn record(person_id: i64, version: i64, properties: &'static str) -> PropertyRecord {
    PropertyRecord {
        team_id: 7,
        person_id,
        version,
        deleted: false,
        created_at: 0,
        properties: Bytes::from_static(properties.as_bytes()),
    }
}

async fn assigned_writer(dir: &tempfile::TempDir, generation: u64) -> PropertyWriter {
    let writer = PropertyWriter::new(&config(), store(dir));
    writer
        .assign(&sole_partition(), generation, 1, || true)
        .await
        .unwrap();
    writer
}

async fn read_at_version(
    reader: &PropertyReader,
    person_id: i64,
    version: i64,
) -> Option<StoredProperties> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let stored = reader.get(7, person_id).await.unwrap();
        if stored.as_ref().is_some_and(|s| s.version >= version) || Instant::now() > deadline {
            return stored;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_reader_sees_the_version_the_writer_made_durable() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    writer
        .put(&sole_partition(), 1, &[record(1, 3, r#"{"plan":"paid"}"#)])
        .await
        .unwrap();

    let reader = PropertyReader::new(&config(), store(&dir));
    let stored = read_at_version(&reader, 1, 3).await.unwrap();
    assert_eq!(
        stored,
        StoredProperties {
            version: 3,
            deleted: false,
            created_at: 0,
            properties: Bytes::from_static(br#"{"plan":"paid"}"#),
        }
    );
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_reader_that_skips_the_wal_sees_a_write_once_the_memtable_flushes() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    writer
        .put(&sole_partition(), 1, &[record(1, 3, r#"{"plan":"paid"}"#)])
        .await
        .unwrap();
    let reader = PropertyReader::new(
        &PropertyStoreConfig {
            reader_skip_wal: true,
            ..config()
        },
        store(&dir),
    );

    let before_flush = reader.get(7, 1).await.unwrap();
    writer.flush_memtables().await;
    let after_flush = read_at_version(&reader, 1, 3).await;

    assert_eq!(before_flush, None, "a write only in the WAL is not visible");
    assert_eq!(after_flush.map(|s| s.version), Some(3));
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn maintenance_flushes_memtables_at_their_own_interval() {
    let dir = tempfile::tempdir().unwrap();
    let config = PropertyStoreConfig {
        memtable_flush_secs: 1,
        reader_skip_wal: true,
        ..config()
    };
    let writer = Arc::new(PropertyWriter::new(&config, store(&dir)));
    writer
        .assign(&sole_partition(), 1, 1, || true)
        .await
        .unwrap();
    let maintenance = writer.spawn_maintenance();
    writer
        .put(&sole_partition(), 1, &[record(1, 3, r#"{"plan":"paid"}"#)])
        .await
        .unwrap();
    let reader = PropertyReader::new(&config, store(&dir));

    let flushed = read_at_version(&reader, 1, 3).await;

    assert_eq!(flushed.map(|s| s.version), Some(3));
    maintenance.abort();
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_older_version_never_replaces_a_newer_one() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let key = sole_partition();
    writer
        .put(&key, 1, &[record(1, 5, r#"{"plan":"paid"}"#)])
        .await
        .unwrap();
    writer.flush_memtables().await;
    writer
        .put(&key, 1, &[record(1, 4, r#"{"plan":"free"}"#)])
        .await
        .unwrap();

    let reader = PropertyReader::new(&config(), store(&dir));
    let stored = read_at_version(&reader, 1, 5).await.unwrap();
    assert_eq!(stored.properties, Bytes::from_static(br#"{"plan":"paid"}"#));
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_delete_keeps_its_version_so_an_older_replay_cannot_resurrect_properties() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let key = sole_partition();
    writer
        .put(&key, 1, &[record(1, 2, r#"{"email":"a@example.com"}"#)])
        .await
        .unwrap();
    writer
        .put(
            &key,
            1,
            &[PropertyRecord {
                deleted: true,
                ..record(1, 3, "{}")
            }],
        )
        .await
        .unwrap();
    writer
        .put(&key, 1, &[record(1, 2, r#"{"email":"a@example.com"}"#)])
        .await
        .unwrap();

    let reader = PropertyReader::new(&config(), store(&dir));
    let stored = read_at_version(&reader, 1, 3).await.unwrap();
    assert!(stored.deleted);
    assert!(stored.properties.is_empty());
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn only_an_open_shard_without_the_person_reads_as_missing() {
    let uncreated = tempfile::tempdir().unwrap();
    let reader = PropertyReader::new(&config(), store(&uncreated));
    assert!(reader.open_partition(0, 1).await.is_err());
    assert!(reader.get(7, 1).await.is_err());
    assert!(reader.get_fresh(7, 1).await.is_err());
    reader.close().await;

    let created = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&created, 1).await;
    let reader = PropertyReader::new(&config(), store(&created));
    reader.open_partition(0, 1).await.unwrap();
    assert_eq!(reader.get(7, 1).await.unwrap(), None);
    assert_eq!(reader.get_fresh(7, 1).await.unwrap(), None);
    reader.close().await;
    writer.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owned_partitions_shards_stay_open_until_it_is_released() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let config = PropertyStoreConfig {
        reader_idle_secs: 1,
        ..config()
    };
    let reader = PropertyReader::new(&config, store(&dir));
    // A second warm of the same partition holds it once.
    reader.open_partition(0, 2).await.unwrap();
    reader.open_partition(0, 2).await.unwrap();
    reader.open_partition(0, 4).await.unwrap();
    let unowned = (1..)
        .find(|&person_id| shard_for(7, person_id, SHARDS) % 2 == 1)
        .unwrap();
    reader.get(7, unowned).await.unwrap();

    tokio::time::sleep(Duration::from_millis(1100)).await;
    assert_eq!(reader.close_idle().await, 2);
    reader.release_partition(0, 4);
    assert_eq!(
        reader.close_idle().await,
        2,
        "partition 0 of 2 still holds shard 0"
    );
    reader.release_partition(0, 2);
    assert_eq!(reader.close_idle().await, 0);
    reader.close().await;
    writer.close().await;
}

#[test]
fn shards_must_divide_evenly_into_changelog_partitions() {
    let dir = tempfile::tempdir().unwrap();
    let writer = PropertyWriter::new(&config(), store(&dir));
    assert!(writer.check_partitions(2).is_ok());
    assert!(writer.check_partitions(3).is_err());
}

#[tokio::test(flavor = "multi_thread")]
async fn a_write_from_a_superseded_or_revoked_assignment_is_lost() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let key = sole_partition();

    writer.assign(&key, 2, 1, || true).await.unwrap();
    assert!(matches!(
        writer.put(&key, 1, &[record(1, 1, "{}")]).await,
        Err(PutError::Lost)
    ));

    writer.revoke(&key, 2).await;
    let started = Instant::now();
    assert!(matches!(
        writer.put(&key, 2, &[record(1, 1, "{}")]).await,
        Err(PutError::Lost)
    ));
    assert!(
        started.elapsed() < Duration::from_secs(1),
        "a revoked write must not wait for an open"
    );
    writer.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_assign_that_arrives_after_its_revoke_never_fences_the_new_owner() {
    let dir = tempfile::tempdir().unwrap();
    let key = sole_partition();
    let new_owner = assigned_writer(&dir, 1).await;
    let old_owner = PropertyWriter::new(&config(), store(&dir));

    // Ownership events run concurrently, so a revoke can land before its assign.
    old_owner.revoke(&key, 1).await;
    old_owner.assign(&key, 1, 1, || true).await.unwrap();
    old_owner.assign(&key, 2, 1, || false).await.unwrap();

    new_owner
        .put(&key, 1, &[record(1, 1, "{}")])
        .await
        .expect("the new owner still holds its shards");
    old_owner.close().await;
    new_owner.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_new_owner_fences_the_old_one_and_its_write_never_lands() {
    let dir = tempfile::tempdir().unwrap();
    let key = sole_partition();
    let old = assigned_writer(&dir, 1).await;
    old.put(&key, 1, &[record(1, 1, r#"{"by":"old"}"#)])
        .await
        .unwrap();

    let new = assigned_writer(&dir, 1).await;
    new.put(&key, 1, &[record(1, 2, r#"{"by":"new"}"#)])
        .await
        .unwrap();
    assert!(matches!(
        old.put(&key, 1, &[record(1, 3, r#"{"by":"old"}"#)]).await,
        Err(PutError::Lost)
    ));

    let reader = PropertyReader::new(&config(), store(&dir));
    tokio::time::sleep(Duration::from_millis(200)).await;
    let stored = read_at_version(&reader, 1, 2).await.unwrap();
    assert_eq!(stored.version, 2);
    assert_eq!(stored.properties, Bytes::from_static(br#"{"by":"new"}"#));
    old.close().await;
    new.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_fenced_writer_that_still_owns_the_partition_reopens_after_a_backoff() {
    let dir = tempfile::tempdir().unwrap();
    let key = sole_partition();
    let owner = assigned_writer(&dir, 1).await;
    let late = assigned_writer(&dir, 1).await;

    assert!(matches!(
        owner.put(&key, 1, &[record(1, 1, "{}")]).await,
        Err(PutError::Lost)
    ));
    assert!(matches!(
        owner.put(&key, 1, &[record(1, 1, "{}")]).await,
        Err(PutError::Lost)
    ));
    tokio::time::sleep(Duration::from_millis(1100)).await;
    owner
        .put(&key, 1, &[record(1, 2, r#"{"by":"owner"}"#)])
        .await
        .unwrap();
    assert!(matches!(
        late.put(&key, 1, &[record(1, 3, "{}")]).await,
        Err(PutError::Lost)
    ));
    owner.close().await;
    late.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_record_outside_the_partition_is_an_invariant_violation() {
    let dir = tempfile::tempdir().unwrap();
    let writer = PropertyWriter::new(&config(), store(&dir));
    let partition_zero = PartitionKey {
        topic: Arc::from("changelog"),
        partition: 0,
    };
    writer.assign(&partition_zero, 1, 2, || true).await.unwrap();
    let outside = (1..)
        .find(|&person_id| shard_for(7, person_id, SHARDS) % 2 == 1)
        .unwrap();
    assert!(matches!(
        writer
            .put(&partition_zero, 1, &[record(outside, 1, "{}")])
            .await,
        Err(PutError::Invariant(_))
    ));
    writer.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_write_waits_for_its_assignment_to_finish_opening() {
    let dir = tempfile::tempdir().unwrap();
    let writer = Arc::new(PropertyWriter::new(&config(), store(&dir)));
    let key = sole_partition();
    let put = tokio::spawn({
        let writer = Arc::clone(&writer);
        let key = key.clone();
        async move { writer.put(&key, 1, &[record(1, 1, "{}")]).await }
    });
    tokio::time::sleep(Duration::from_millis(50)).await;
    writer.assign(&key, 1, 1, || true).await.unwrap();
    put.await
        .unwrap()
        .expect("the write lands once the assignment opens");
    writer.close().await;
}

fn files_containing(dir: &std::path::Path, needle: &[u8]) -> Vec<std::path::PathBuf> {
    let mut found = Vec::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                pending.push(path);
            } else if std::fs::read(&path)
                .map(|bytes| bytes.windows(needle.len()).any(|w| w == needle))
                .unwrap_or(false)
            {
                found.push(path);
            }
        }
    }
    found
}

#[tokio::test(flavor = "multi_thread")]
async fn a_deleted_persons_properties_leave_object_storage_while_writes_continue() {
    let dir = tempfile::tempdir().unwrap();
    let config = PropertyStoreConfig {
        compression: Compression::None,
        full_compaction_secs: 1,
        ..config()
    };
    let key = sole_partition();
    let shard = shard_for(7, 1, SHARDS);
    let neighbour = (2..).find(|&id| shard_for(7, id, SHARDS) == shard).unwrap();
    let admin = Admin::builder(format!("props/shard-{shard:05}"), store(&dir)).build();

    // The properties settle into a sorted run before the delete arrives.
    let writer = PropertyWriter::new(&config, store(&dir));
    writer.assign(&key, 1, 1, || true).await.unwrap();
    // Enough other persons that routine compaction never merges this run.
    let filler: &'static str =
        Box::leak(format!("{{\"bio\":\"{}\"}}", "x".repeat(512)).into_boxed_str());
    let mut first = vec![record(1, 1, r#"{"email":"deleted-person@example.com"}"#)];
    first.extend(
        (1000..)
            .filter(|&id| shard_for(7, id, SHARDS) == shard)
            .take(8_000)
            .map(|id| record(id, 1, filler)),
    );
    writer.put(&key, 1, &first).await.unwrap();
    writer.flush_memtables().await;
    assert!(
        !files_containing(dir.path(), b"deleted-person@example.com").is_empty(),
        "the properties are stored uncompressed, so the scan can find them"
    );
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        tokio::time::sleep(Duration::from_millis(1100)).await;
        writer.compact_due().await;
        let manifest = admin.read_manifest(None).await.unwrap().unwrap();
        if manifest.l0().is_empty() && !manifest.compacted().is_empty() {
            break;
        }
        assert!(Instant::now() < deadline, "the properties never left L0");
    }
    writer
        .put(
            &key,
            1,
            &[PropertyRecord {
                deleted: true,
                ..record(1, 2, "{}")
            }],
        )
        .await
        .unwrap();
    writer.flush_memtables().await;
    writer.close().await;
    let writer = PropertyWriter::new(&config, store(&dir));
    writer.assign(&key, 2, 1, || true).await.unwrap();

    let collect_now = GarbageCollectorDirectoryOptions {
        interval: None,
        min_age: Duration::ZERO,
        dry_run: false,
    };
    let gc = GarbageCollectorOptions {
        manifest_options: Some(collect_now),
        wal_options: Some(collect_now),
        compacted_options: Some(collect_now),
        compactions_options: Some(collect_now),
        ..GarbageCollectorOptions::default()
    };
    // Collect after compaction checkpoints expire.
    let later = std::time::SystemTime::now() + Duration::from_secs(3600);
    let later_ms = later
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let collector = Admin::builder(format!("props/shard-{shard:05}"), store(&dir))
        .with_system_clock(Arc::new(MockSystemClock::with_time(later_ms)))
        .build();
    let deadline = Instant::now() + Duration::from_secs(90);
    let mut version = 1;
    let remaining = loop {
        version += 1;
        writer
            .put(&key, 2, &[record(neighbour, version, "{}")])
            .await
            .unwrap();
        writer.flush_memtables().await;
        writer.compact_due().await;
        collector.run_gc_once(gc.clone()).await.unwrap();
        let remaining = files_containing(dir.path(), b"deleted-person@example.com");
        if remaining.is_empty() || Instant::now() > deadline {
            break remaining;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    };
    writer.close().await;
    assert!(remaining.is_empty(), "still stored in {remaining:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn an_assign_after_close_never_fences_the_owner() {
    let dir = tempfile::tempdir().unwrap();
    let key = sole_partition();
    let owner = assigned_writer(&dir, 1).await;
    let closed = PropertyWriter::new(&config(), store(&dir));
    closed.close().await;

    closed.assign(&key, 2, 1, || true).await.unwrap();

    owner
        .put(&key, 1, &[record(1, 1, "{}")])
        .await
        .expect("the owner still holds its shards");
    owner.close().await;
}

/// Requests under one shard's prefix hang, wait `delay`, or fail at once with an error SlateDB does not retry.
#[derive(Debug)]
struct StalledShard {
    inner: Arc<dyn ObjectStore>,
    shard: String,
    fail: bool,
    delay: Option<Duration>,
}

impl std::fmt::Display for StalledShard {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "StalledShard({})", self.shard)
    }
}

impl StalledShard {
    async fn pass(&self, path: &ObjectPath) -> object_store::Result<()> {
        if !path.as_ref().contains(&self.shard) {
            return Ok(());
        }
        if self.fail {
            return Err(object_store::Error::NotSupported {
                source: "unavailable".into(),
            });
        }
        match self.delay {
            Some(delay) => {
                tokio::time::sleep(delay).await;
                Ok(())
            }
            None => std::future::pending().await,
        }
    }
}

#[async_trait::async_trait]
impl ObjectStore for StalledShard {
    async fn put_opts(
        &self,
        location: &ObjectPath,
        payload: PutPayload,
        opts: PutOptions,
    ) -> object_store::Result<PutResult> {
        self.pass(location).await?;
        self.inner.put_opts(location, payload, opts).await
    }

    async fn put_multipart_opts(
        &self,
        location: &ObjectPath,
        opts: PutMultipartOptions,
    ) -> object_store::Result<Box<dyn MultipartUpload>> {
        self.pass(location).await?;
        self.inner.put_multipart_opts(location, opts).await
    }

    async fn get_opts(
        &self,
        location: &ObjectPath,
        options: GetOptions,
    ) -> object_store::Result<GetResult> {
        self.pass(location).await?;
        self.inner.get_opts(location, options).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<ObjectPath>>,
    ) -> BoxStream<'static, object_store::Result<ObjectPath>> {
        self.inner.delete_stream(locations)
    }

    fn list(
        &self,
        prefix: Option<&ObjectPath>,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        if prefix.is_some_and(|p| p.as_ref().contains(&self.shard)) {
            if let Some(delay) = self.delay {
                let listed = self.inner.list(prefix);
                return futures::stream::once(async move {
                    tokio::time::sleep(delay).await;
                    listed
                })
                .flatten()
                .boxed();
            }
            if self.fail {
                return futures::stream::once(async {
                    Err(object_store::Error::NotSupported {
                        source: "unavailable".into(),
                    })
                })
                .boxed();
            }
            return futures::stream::pending().boxed();
        }
        self.inner.list(prefix)
    }

    async fn list_with_delimiter(
        &self,
        prefix: Option<&ObjectPath>,
    ) -> object_store::Result<ListResult> {
        if let Some(prefix) = prefix {
            self.pass(prefix).await?;
        }
        self.inner.list_with_delimiter(prefix).await
    }

    async fn copy_opts(
        &self,
        from: &ObjectPath,
        to: &ObjectPath,
        options: CopyOptions,
    ) -> object_store::Result<()> {
        self.pass(from).await?;
        self.inner.copy_opts(from, to, options).await
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_shard_whose_store_hangs_times_out_without_blocking_other_shards() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let person_in = |shard: u32| (1..).find(|&id| shard_for(7, id, SHARDS) == shard).unwrap();
    writer
        .put(
            &sole_partition(),
            1,
            &[record(person_in(0), 1, "{}"), record(person_in(1), 1, "{}")],
        )
        .await
        .unwrap();
    writer.close().await;
    let reader = PropertyReader::new(
        &PropertyStoreConfig {
            read_timeout_ms: 200,
            ..config()
        },
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-00001".to_string(),
            fail: false,
            delay: None,
        }),
    );

    let started = Instant::now();
    let stuck = reader.get(7, person_in(1)).await;
    assert!(matches!(stuck, Err(PropertyStoreError::Timeout)));
    assert!(started.elapsed() < Duration::from_secs(2));

    let other = reader.get(7, person_in(0)).await;
    assert!(
        matches!(other, Ok(Some(_))),
        "the other shard's read must not wait for the hung open"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn opening_a_partition_may_take_longer_than_a_point_read() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    writer.close().await;
    let reader = PropertyReader::new(
        &PropertyStoreConfig {
            read_timeout_ms: 50,
            ..config()
        },
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-00000".to_string(),
            fail: false,
            delay: Some(Duration::from_millis(30)),
        }),
    );

    let opened = reader.open_partition(0, SHARDS).await;

    assert!(opened.is_ok(), "{opened:?}");
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_writer_runs_a_bounded_number_of_full_compactions_at_once() {
    let dir = tempfile::tempdir().unwrap();
    let shards = 8;
    let writer = PropertyWriter::new(
        &PropertyStoreConfig {
            full_compaction_secs: 1,
            ..PropertyStoreConfig::local("props", shards)
        },
        store(&dir),
    );
    writer
        .assign(&sole_partition(), 1, 1, || true)
        .await
        .unwrap();
    let everywhere: Vec<PropertyRecord> = (0..shards)
        .map(|shard| {
            let person = (1..).find(|&id| shard_for(7, id, shards) == shard).unwrap();
            record(person, 1, "{}")
        })
        .collect();
    for _ in 0..2 {
        writer.put(&sole_partition(), 1, &everywhere).await.unwrap();
        writer.flush_memtables().await;
    }
    tokio::time::sleep(Duration::from_secs(1)).await;

    let first = writer.compact_due().await;
    let second = writer.compact_due().await;

    writer.close().await;
    assert_eq!((first, second), (4, 0));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_shard_whose_store_fails_reads_as_unavailable_not_missing() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let person = (1..).find(|&id| shard_for(7, id, SHARDS) == 1).unwrap();
    writer
        .put(&sole_partition(), 1, &[record(person, 1, "{}")])
        .await
        .unwrap();
    writer.close().await;
    let reader = PropertyReader::new(
        &config(),
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-00001".to_string(),
            fail: true,
            delay: None,
        }),
    );

    let read = reader.get(7, person).await;

    assert!(
        matches!(
            read,
            Err(PropertyStoreError::ShardUnavailable { shard: 1, .. })
        ),
        "{read:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_revoke_wakes_a_write_waiting_for_its_partition_to_open() {
    let dir = tempfile::tempdir().unwrap();
    let writer = Arc::new(PropertyWriter::new(&config(), store(&dir)));
    let waiting = {
        let writer = Arc::clone(&writer);
        tokio::spawn(async move {
            writer
                .put(&sole_partition(), 1, &[record(1, 1, "{}")])
                .await
        })
    };
    tokio::time::sleep(Duration::from_millis(100)).await;

    writer.revoke(&sole_partition(), 1).await;

    let put = tokio::time::timeout(Duration::from_secs(5), waiting).await;
    assert!(matches!(put, Ok(Ok(Err(PutError::Lost)))), "{put:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn one_off_reads_against_a_hung_store_are_bounded() {
    let dir = tempfile::tempdir().unwrap();
    let reader = PropertyReader::new(
        &PropertyStoreConfig {
            read_timeout_ms: 100,
            ..config()
        },
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-".to_string(),
            fail: false,
            delay: None,
        }),
    );
    for person in 0..8 {
        assert!(matches!(
            reader.get_fresh(7, person).await,
            Err(PropertyStoreError::Timeout)
        ));
    }

    let started = Instant::now();
    let refused = reader.get_fresh(7, 100).await;

    assert!(
        matches!(refused, Err(PropertyStoreError::ShardUnavailable { .. })),
        "{refused:?}"
    );
    assert!(started.elapsed() < Duration::from_millis(50));
}

/// Compacted table reads fail with an error SlateDB retries once `failing` is set, and every one is counted.
#[derive(Debug)]
struct FailingTables {
    inner: Arc<dyn ObjectStore>,
    failing: std::sync::atomic::AtomicBool,
    table_reads: std::sync::atomic::AtomicUsize,
}

impl std::fmt::Display for FailingTables {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "FailingTables")
    }
}

#[async_trait::async_trait]
impl ObjectStore for FailingTables {
    async fn put_opts(
        &self,
        location: &ObjectPath,
        payload: PutPayload,
        opts: PutOptions,
    ) -> object_store::Result<PutResult> {
        self.inner.put_opts(location, payload, opts).await
    }

    async fn put_multipart_opts(
        &self,
        location: &ObjectPath,
        opts: PutMultipartOptions,
    ) -> object_store::Result<Box<dyn MultipartUpload>> {
        self.inner.put_multipart_opts(location, opts).await
    }

    async fn get_opts(
        &self,
        location: &ObjectPath,
        options: GetOptions,
    ) -> object_store::Result<GetResult> {
        use std::sync::atomic::Ordering;
        if location.as_ref().contains("/compacted/") && self.failing.load(Ordering::SeqCst) {
            self.table_reads.fetch_add(1, Ordering::SeqCst);
            return Err(object_store::Error::Generic {
                store: "FailingTables",
                source: "unavailable".into(),
            });
        }
        self.inner.get_opts(location, options).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<ObjectPath>>,
    ) -> BoxStream<'static, object_store::Result<ObjectPath>> {
        self.inner.delete_stream(locations)
    }

    fn list(
        &self,
        prefix: Option<&ObjectPath>,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        self.inner.list(prefix)
    }

    async fn list_with_delimiter(
        &self,
        prefix: Option<&ObjectPath>,
    ) -> object_store::Result<ListResult> {
        self.inner.list_with_delimiter(prefix).await
    }

    async fn copy_opts(
        &self,
        from: &ObjectPath,
        to: &ObjectPath,
        options: CopyOptions,
    ) -> object_store::Result<()> {
        self.inner.copy_opts(from, to, options).await
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_read_abandoned_during_an_outage_stops_retrying() {
    use std::sync::atomic::Ordering;
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    writer
        .put(&sole_partition(), 1, &[record(1, 1, "{}")])
        .await
        .unwrap();
    writer.flush_memtables().await;
    writer.close().await;
    let tables = Arc::new(FailingTables {
        inner: store(&dir),
        failing: std::sync::atomic::AtomicBool::new(false),
        table_reads: std::sync::atomic::AtomicUsize::new(0),
    });
    let reader = PropertyReader::new(
        &PropertyStoreConfig {
            read_timeout_ms: 200,
            ..config()
        },
        tables.clone(),
    );
    reader.open_partition(0, 1).await.unwrap();
    tables.failing.store(true, Ordering::SeqCst);

    let read = reader.get(7, 1).await;
    tokio::time::sleep(Duration::from_secs(6)).await;
    let settled = tables.table_reads.load(Ordering::SeqCst);
    tokio::time::sleep(Duration::from_secs(3)).await;

    assert!(matches!(read, Err(PropertyStoreError::Timeout)), "{read:?}");
    assert!(settled > 0, "the read never reached the failing tables");
    assert_eq!(tables.table_reads.load(Ordering::SeqCst), settled);
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn erasing_a_team_removes_its_keys_and_no_others() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let key = sole_partition();
    let other_team = PropertyRecord {
        team_id: 8,
        ..record(1, 1, "{}")
    };
    writer
        .put(
            &key,
            1,
            &[record(1, 1, "{}"), record(2, 1, "{}"), other_team],
        )
        .await
        .unwrap();
    let reader = PropertyReader::new(&config(), store(&dir));
    read_at_version(&reader, 2, 1).await.unwrap();
    assert!(reader.team_has_keys(7).await.unwrap());

    assert_eq!(writer.erase_team(7).await.unwrap(), 2);

    assert_eq!(reader.get_fresh(7, 1).await.unwrap(), None);
    assert_eq!(reader.get_fresh(7, 2).await.unwrap(), None);
    assert!(reader.get_fresh(8, 1).await.unwrap().is_some());
    let deadline = Instant::now() + Duration::from_secs(10);
    while reader.team_has_keys(7).await.unwrap() {
        assert!(
            Instant::now() < deadline,
            "the reader never saw the erasure"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(reader.team_has_keys(8).await.unwrap());
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_team_larger_than_one_batch_is_erased_in_full() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    let persons: Vec<PropertyRecord> = (1..=7).map(|id| record(id, 1, "{}")).collect();
    writer.put(&sole_partition(), 1, &persons).await.unwrap();

    assert_eq!(
        writer
            .erase_team_in_batches(7, 2, Duration::from_secs(30))
            .await
            .unwrap(),
        7
    );

    let reader = PropertyReader::new(&config(), store(&dir));
    for id in 1..=7 {
        assert_eq!(reader.get_fresh(7, id).await.unwrap(), None, "person {id}");
    }
    writer.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_erasure_leaves_a_shard_whose_store_does_not_answer_and_erases_the_rest() {
    let dir = tempfile::tempdir().unwrap();
    let person_in = |shard: u32| (1..).find(|&id| shard_for(7, id, SHARDS) == shard).unwrap();
    let writer = assigned_writer(&dir, 1).await;
    writer
        .put(
            &sole_partition(),
            1,
            &[record(person_in(0), 1, "{}"), record(person_in(1), 1, "{}")],
        )
        .await
        .unwrap();
    // In SSTs, so the erasure's scan has to read the store rather than a replayed memtable.
    writer.flush_memtables().await;
    writer.close().await;
    // Shard 0 stalls and comes first, so the healthy shard is only reached by going on past it.
    let slow = PropertyWriter::new(
        &config(),
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-00000".to_string(),
            fail: false,
            delay: Some(Duration::from_millis(400)),
        }),
    );
    slow.assign(&sole_partition(), 2, 1, || true).await.unwrap();

    let erased = tokio::time::timeout(
        Duration::from_secs(20),
        slow.erase_team_in_batches(7, 2, Duration::from_millis(100)),
    )
    .await
    .expect("every batch is bounded");

    assert!(
        matches!(erased, Err(PropertyStoreError::Timeout)),
        "{erased:?}"
    );
    let reader = PropertyReader::new(&config(), store(&dir));
    assert!(
        reader.get_fresh(7, person_in(0)).await.unwrap().is_some(),
        "the stalled shard keeps its keys for the next pass"
    );
    assert_eq!(
        reader.get_fresh(7, person_in(1)).await.unwrap(),
        None,
        "the healthy shard after it was erased"
    );
    slow.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_erasure_on_a_slow_store_advances_by_smaller_batches() {
    let dir = tempfile::tempdir().unwrap();
    let writer = assigned_writer(&dir, 1).await;
    // A value of a block each, so every key the scan reaches costs the store one request.
    let value: &'static str =
        Box::leak(format!(r#"{{"blob":"{}"}}"#, "x".repeat(64 * 1024)).into_boxed_str());
    let persons: Vec<i64> = (1..)
        .filter(|&id| shard_for(7, id, SHARDS) == 0)
        .take(20)
        .collect();
    let records: Vec<PropertyRecord> = persons.iter().map(|&id| record(id, 1, value)).collect();
    writer.put(&sole_partition(), 1, &records).await.unwrap();
    writer.flush_memtables().await;
    writer.close().await;
    let slow = PropertyWriter::new(
        &config(),
        Arc::new(StalledShard {
            inner: store(&dir),
            shard: "shard-00000".to_string(),
            fail: false,
            delay: Some(Duration::from_millis(200)),
        }),
    );
    slow.assign(&sole_partition(), 2, 1, || true).await.unwrap();

    let erased = slow
        .erase_team_in_batches(7, 100, Duration::from_secs(3))
        .await;

    assert_eq!(erased.unwrap(), persons.len());
    let reader = PropertyReader::new(&config(), store(&dir));
    for id in &persons {
        assert_eq!(reader.get_fresh(7, *id).await.unwrap(), None, "person {id}");
    }
    slow.close().await;
    reader.close().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_erasure_scan_abandoned_during_an_outage_stops_reading() {
    use std::sync::atomic::Ordering;
    let dir = tempfile::tempdir().unwrap();
    let tables = Arc::new(FailingTables {
        inner: store(&dir),
        failing: std::sync::atomic::AtomicBool::new(false),
        table_reads: std::sync::atomic::AtomicUsize::new(0),
    });
    let earlier = assigned_writer(&dir, 1).await;
    earlier
        .put(&sole_partition(), 1, &[record(1, 1, "{}")])
        .await
        .unwrap();
    earlier.flush_memtables().await;
    earlier.close().await;
    // A new owner has none of the table's metadata cached, so the scan has to load it.
    let writer = PropertyWriter::new(&config(), tables.clone());
    writer
        .assign(&sole_partition(), 2, 1, || true)
        .await
        .unwrap();
    tables.failing.store(true, Ordering::SeqCst);

    let erased = writer
        .erase_team_in_batches(7, 100, Duration::from_millis(200))
        .await;
    tokio::time::sleep(Duration::from_secs(6)).await;
    let settled = tables.table_reads.load(Ordering::SeqCst);
    tokio::time::sleep(Duration::from_secs(3)).await;

    assert!(erased.is_err(), "{erased:?}");
    assert!(settled > 0, "the scan never reached the failing tables");
    assert_eq!(tables.table_reads.load(Ordering::SeqCst), settled);
    writer.close().await;
}
