use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::Context;
use async_trait::async_trait;
use aws_sdk_s3::error::ProvideErrorMetadata;
use aws_sdk_s3::primitives::ByteStream;
use etcd_client::EventType;
use personhog_coordination::store::PersonhogStore;
use serde::Serialize;

use crate::changelog;
use crate::etcd::EtcdHandle;

const RETRY_INITIAL: Duration = Duration::from_secs(1);
const RETRY_MAX: Duration = Duration::from_secs(60);

/// One stored copy of the changelog config.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BackupVersion {
    pub version_id: String,
    pub last_modified: Option<String>,
    pub is_latest: bool,
    pub size: i64,
}

/// A versioned object store holding one key per backed-up config.
#[async_trait]
pub trait BackupStore: Send + Sync {
    /// The current version, or the named one; `None` when it does not exist.
    async fn get(&self, key: &str, version_id: Option<&str>) -> anyhow::Result<Option<Vec<u8>>>;
    async fn put(&self, key: &str, value: &[u8]) -> anyhow::Result<()>;
    /// Newest first.
    async fn versions(&self, key: &str) -> anyhow::Result<Vec<BackupVersion>>;
}

pub struct S3BackupStore {
    client: aws_sdk_s3::Client,
    bucket: String,
}

impl S3BackupStore {
    pub fn new(client: aws_sdk_s3::Client, bucket: String) -> Self {
        Self { client, bucket }
    }

    pub async fn from_env(bucket: String) -> Self {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        // Local S3 (an `AWS_ENDPOINT_URL` such as the dev stack's SeaweedFS)
        // serves buckets by path, not by virtual host.
        let s3_config = aws_sdk_s3::config::Builder::from(&config)
            .force_path_style(config.endpoint_url().is_some())
            .build();
        Self::new(aws_sdk_s3::Client::from_conf(s3_config), bucket)
    }
}

#[async_trait]
impl BackupStore for S3BackupStore {
    async fn get(&self, key: &str, version_id: Option<&str>) -> anyhow::Result<Option<Vec<u8>>> {
        let result = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .set_version_id(version_id.map(str::to_string))
            .send()
            .await;
        let object = match result {
            Ok(object) => object,
            Err(e) if matches!(e.code(), Some("NoSuchKey" | "NoSuchVersion")) => return Ok(None),
            Err(e) => {
                return Err(anyhow::Error::from(e.into_service_error()))
                    .with_context(|| format!("get s3://{}/{key}", self.bucket))
            }
        };
        let body = object.body.collect().await.context("read backup body")?;
        Ok(Some(body.into_bytes().to_vec()))
    }

    async fn put(&self, key: &str, value: &[u8]) -> anyhow::Result<()> {
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .content_type("application/json")
            .body(ByteStream::from(value.to_vec()))
            .send()
            .await
            .map_err(|e| anyhow::Error::from(e.into_service_error()))
            .with_context(|| format!("put s3://{}/{key}", self.bucket))?;
        Ok(())
    }

    async fn versions(&self, key: &str) -> anyhow::Result<Vec<BackupVersion>> {
        let resp = self
            .client
            .list_object_versions()
            .bucket(&self.bucket)
            .prefix(key)
            .send()
            .await
            .map_err(|e| anyhow::Error::from(e.into_service_error()))
            .with_context(|| format!("list versions of s3://{}/{key}", self.bucket))?;
        let mut versions: Vec<BackupVersion> = resp
            .versions()
            .iter()
            .filter(|v| v.key() == Some(key))
            .filter_map(|v| {
                Some(BackupVersion {
                    version_id: v.version_id()?.to_string(),
                    last_modified: v.last_modified().map(|t| t.to_string()),
                    is_latest: v.is_latest().unwrap_or(false),
                    size: v.size().unwrap_or(0),
                })
            })
            .collect();
        // Two writes can share a timestamp, so the current version leads explicitly.
        versions.sort_by(|a, b| {
            b.is_latest
                .cmp(&a.is_latest)
                .then_with(|| b.last_modified.cmp(&a.last_modified))
        });
        Ok(versions)
    }
}

fn record(outcome: &str) {
    common_metrics::inc(
        "ingestion_control_plane_changelog_backups_total",
        &[("outcome".to_string(), outcome.to_string())],
        1,
    );
}

/// The object key holding the config for `prefix`: `/personhog/` becomes
/// `personhog/config-changelog.json`.
pub fn object_key(prefix: &str) -> String {
    format!("{}/config-changelog.json", prefix.trim_matches('/'))
}

/// Stores `value` unless the current backup already holds exactly it.
async fn sync(backups: &dyn BackupStore, key: &str, value: &[u8]) -> anyhow::Result<()> {
    if backups.get(key, None).await?.as_deref() == Some(value) {
        record("unchanged");
        return Ok(());
    }
    backups.put(key, value).await?;
    record("uploaded");
    tracing::info!(key, "backed up config/changelog");
    Ok(())
}

/// Backs up the current config, then every change after it. A deletion is
/// never backed up: the last good copy is what a rebuild restores.
async fn watch_once(
    store: &PersonhogStore,
    backups: &dyn BackupStore,
    key: &str,
) -> anyhow::Result<()> {
    let (value, revision) = store.get_changelog_config_raw_with_revision().await?;
    if let Some(value) = value {
        sync(backups, key, &value).await?;
    }
    let mut stream = store.watch_changelog_config_from(revision + 1).await?;
    while let Some(response) = stream.message().await? {
        if response.canceled() {
            anyhow::bail!(
                "config/changelog watch cancelled by etcd: {}",
                response.cancel_reason()
            );
        }
        for event in response.events() {
            match (event.event_type(), event.kv()) {
                (EventType::Put, Some(kv)) => sync(backups, key, kv.value()).await?,
                (EventType::Delete, _) => {
                    record("deleted_skipped");
                    tracing::warn!(key, "config/changelog was deleted; keeping the last backup");
                }
                (EventType::Put, None) => {}
            }
        }
    }
    anyhow::bail!("config/changelog watch ended")
}

/// Keeps the backup of `prefix`'s `config/changelog` in step with etcd for
/// the process lifetime, starting over from a fresh read after any failure.
pub async fn run(etcd: Arc<EtcdHandle>, prefix: String, backups: Arc<dyn BackupStore>) {
    let key = object_key(&prefix);
    let mut delay = RETRY_INITIAL;
    loop {
        let started = Instant::now();
        let attempt = async {
            let client = etcd.client().await?;
            watch_once(&changelog::store(&client, &prefix), backups.as_ref(), &key).await
        };
        if let Err(e) = attempt.await {
            record("error");
            tracing::warn!(key, error = %format!("{e:#}"), "config/changelog backup failed; retrying");
        }
        if started.elapsed() > RETRY_MAX {
            delay = RETRY_INITIAL;
        }
        tokio::time::sleep(delay).await;
        delay = (delay * 2).min(RETRY_MAX);
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use std::collections::HashMap;
    use std::sync::Mutex;

    use envconfig::Envconfig;

    use super::*;
    use crate::config::Config;

    /// Versions in insertion order, the last one current.
    #[derive(Default)]
    pub(crate) struct MemoryBackups {
        pub(crate) versions: Mutex<Vec<Vec<u8>>>,
    }

    #[async_trait]
    impl BackupStore for MemoryBackups {
        async fn get(
            &self,
            _key: &str,
            version_id: Option<&str>,
        ) -> anyhow::Result<Option<Vec<u8>>> {
            let versions = self.versions.lock().unwrap();
            Ok(match version_id {
                None => versions.last().cloned(),
                Some(id) => id
                    .parse::<usize>()
                    .ok()
                    .and_then(|i| versions.get(i).cloned()),
            })
        }

        async fn put(&self, _key: &str, value: &[u8]) -> anyhow::Result<()> {
            self.versions.lock().unwrap().push(value.to_vec());
            Ok(())
        }

        async fn versions(&self, _key: &str) -> anyhow::Result<Vec<BackupVersion>> {
            let versions = self.versions.lock().unwrap();
            Ok((0..versions.len())
                .rev()
                .map(|i| BackupVersion {
                    version_id: i.to_string(),
                    last_modified: None,
                    is_latest: i + 1 == versions.len(),
                    size: versions[i].len() as i64,
                })
                .collect())
        }
    }

    /// A handle on the local etcd and a prefix no other test shares.
    pub(crate) async fn test_etcd(name: &str) -> (Arc<EtcdHandle>, String) {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let env = HashMap::from([(
            "ETCD_ENDPOINTS".to_string(),
            "http://localhost:2379".to_string(),
        )]);
        let config = Config::init_from_hashmap(&env).unwrap();
        let etcd = Arc::new(EtcdHandle::from_config(&config).unwrap());
        (etcd, format!("/test-control-plane-{name}-{nanos}/"))
    }

    /// The local S3 the dev stack and CI run (SeaweedFS), with versioning on.
    async fn local_s3() -> S3BackupStore {
        use aws_sdk_s3::config::{Credentials, Region};
        use aws_sdk_s3::types::{BucketVersioningStatus, VersioningConfiguration};

        const BUCKET: &str = "control-plane-backup-test";
        let config = aws_sdk_s3::Config::builder()
            .behavior_version(aws_config::BehaviorVersion::latest())
            .region(Region::new("us-east-1"))
            .endpoint_url("http://localhost:19000")
            .credentials_provider(Credentials::new(
                "object_storage_root_user",
                "object_storage_root_password",
                None,
                None,
                "test",
            ))
            .force_path_style(true)
            .build();
        let client = aws_sdk_s3::Client::from_conf(config);
        // Creating an existing bucket fails; the versioning call below is what must succeed.
        drop(client.create_bucket().bucket(BUCKET).send().await);
        client
            .put_bucket_versioning()
            .bucket(BUCKET)
            .versioning_configuration(
                VersioningConfiguration::builder()
                    .status(BucketVersioningStatus::Enabled)
                    .build(),
            )
            .send()
            .await
            .expect("local S3 at localhost:19000");
        S3BackupStore::new(client, BUCKET.to_string())
    }

    #[tokio::test]
    async fn s3_store_reads_the_current_and_earlier_versions() {
        let store = local_s3().await;
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let key = format!("test-{nanos}/config-changelog.json");
        assert_eq!(store.get(&key, None).await.unwrap(), None);

        store.put(&key, b"first").await.unwrap();
        store.put(&key, b"second").await.unwrap();

        assert_eq!(store.get(&key, None).await.unwrap().unwrap(), b"second");
        let versions = store.versions(&key).await.unwrap();
        assert_eq!(versions.len(), 2);
        assert!(versions[0].is_latest);
        let earlier = store
            .get(&key, Some(&versions[1].version_id))
            .await
            .unwrap();
        assert_eq!(earlier.unwrap(), b"first");
    }

    async fn wait_for_versions(backups: &MemoryBackups, count: usize) {
        let deadline = Instant::now() + Duration::from_secs(10);
        while backups.versions.lock().unwrap().len() < count {
            assert!(Instant::now() < deadline, "expected {count} backups");
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

    #[tokio::test]
    async fn every_change_is_backed_up_and_a_deletion_never_is() {
        let (etcd, prefix) = test_etcd("backup-watch").await;
        let store = changelog::store(&etcd.client().await.unwrap(), &prefix);
        assert!(store
            .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
            .await
            .unwrap());
        let (seeded, _) = store
            .get_changelog_config_raw_with_revision()
            .await
            .unwrap();
        let seeded = seeded.unwrap();
        let backups = Arc::new(MemoryBackups::default());
        let watcher = tokio::spawn(run(etcd.clone(), prefix.clone(), backups.clone()));

        wait_for_versions(&backups, 1).await;
        assert_eq!(backups.versions.lock().unwrap()[0], seeded);

        let inner = store.inner();
        let key = format!("{}config/changelog", inner.prefix());
        inner.put_raw(&key, seeded.clone()).await.unwrap();
        let moved = br#"{"topic":"personhog_updates_128","partitions":128,"epoch":2}"#.to_vec();
        inner.put_raw(&key, moved.clone()).await.unwrap();
        inner.delete(&key).await.unwrap();
        // Events arrive in order, so this one being backed up proves the
        // deletion before it was handled.
        let reseeded = br#"{"topic":"personhog_updates_128","partitions":128,"epoch":3}"#.to_vec();
        inner.put_raw(&key, reseeded.clone()).await.unwrap();
        wait_for_versions(&backups, 3).await;
        watcher.abort();

        let versions = backups.versions.lock().unwrap();
        assert_eq!(*versions, vec![seeded, moved, reseeded]);
    }
}
