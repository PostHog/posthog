use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::Context;
use async_trait::async_trait;
use aws_sdk_s3::error::ProvideErrorMetadata;
use aws_sdk_s3::primitives::ByteStream;
use etcd_client::EventType;
use personhog_coordination::store::PersonhogStore;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::changelog;
use crate::etcd::EtcdHandle;

const RETRY_INITIAL: Duration = Duration::from_secs(1);
const RETRY_MAX: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BackupVersion {
    pub version_id: String,
    pub last_modified: Option<String>,
    pub is_latest: bool,
    pub size: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StoredObject {
    pub body: Vec<u8>,
    pub etag: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Precondition {
    Absent,
    Matches(String),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PutOutcome {
    Written,
    Conflict,
}

#[async_trait]
pub trait BackupStore: Send + Sync {
    /// The current version, or the named one; `None` when it does not exist.
    async fn get(
        &self,
        key: &str,
        version_id: Option<&str>,
    ) -> anyhow::Result<Option<StoredObject>>;
    async fn put(
        &self,
        key: &str,
        value: &[u8],
        precondition: Precondition,
    ) -> anyhow::Result<PutOutcome>;
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
    async fn get(
        &self,
        key: &str,
        version_id: Option<&str>,
    ) -> anyhow::Result<Option<StoredObject>> {
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
        let etag = object
            .e_tag()
            .with_context(|| format!("s3://{}/{key} has no ETag", self.bucket))?
            .to_string();
        let body = object.body.collect().await.context("read backup body")?;
        Ok(Some(StoredObject {
            body: body.into_bytes().to_vec(),
            etag,
        }))
    }

    async fn put(
        &self,
        key: &str,
        value: &[u8],
        precondition: Precondition,
    ) -> anyhow::Result<PutOutcome> {
        let request = self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .content_type("application/json")
            .body(ByteStream::from(value.to_vec()));
        let request = match precondition {
            Precondition::Absent => request.if_none_match("*"),
            Precondition::Matches(etag) => request.if_match(etag),
        };
        match request.send().await {
            Ok(_) => Ok(PutOutcome::Written),
            // S3 answers 409 instead of 412 when another conditional upload
            // of the key is in flight.
            Err(e)
                if matches!(
                    e.code(),
                    Some("PreconditionFailed" | "ConditionalRequestConflict")
                ) =>
            {
                Ok(PutOutcome::Conflict)
            }
            Err(e) => Err(anyhow::Error::from(e.into_service_error()))
                .with_context(|| format!("put s3://{}/{key}", self.bucket)),
        }
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

/// The stored form of a config. The nonce gives every upload distinct bytes,
/// and so a distinct ETag: the config alone can return to earlier bytes, and
/// an ETag condition would then pass for an object written since it was read.
#[derive(Serialize, Deserialize)]
struct Envelope {
    nonce: String,
    config: String,
}

fn wrap_config(config: &[u8]) -> anyhow::Result<Vec<u8>> {
    let envelope = Envelope {
        nonce: Uuid::new_v4().to_string(),
        config: String::from_utf8(config.to_vec()).context("config/changelog is not UTF-8")?,
    };
    Ok(serde_json::to_vec(&envelope)?)
}

pub fn unwrap_config(body: &[u8]) -> anyhow::Result<Vec<u8>> {
    let envelope: Envelope =
        serde_json::from_slice(body).context("the backup is not a backup envelope")?;
    Ok(envelope.config.into_bytes())
}

fn record(outcome: &str) {
    common_metrics::inc(
        "ingestion_control_plane_changelog_backups_total",
        &[("outcome".to_string(), outcome.to_string())],
        1,
    );
}

fn set_in_sync(in_sync: bool) {
    common_metrics::gauge(
        "ingestion_control_plane_changelog_backup_in_sync",
        &[],
        if in_sync { 1.0 } else { 0.0 },
    );
}

pub fn object_key(prefix: &str) -> String {
    format!("{}/config-changelog.json", prefix.trim_matches('/'))
}

/// The backup is read before etcd, and the upload requires that backup to
/// still be current, so an upload never replaces a newer config.
async fn sync(store: &PersonhogStore, backups: &dyn BackupStore, key: &str) -> anyhow::Result<()> {
    let backup = backups.get(key, None).await?;
    let (config, _) = store.get_changelog_config_raw_with_revision().await?;
    let Some(config) = config else {
        set_in_sync(true);
        return Ok(());
    };
    let precondition = match backup {
        Some(object) if unwrap_config(&object.body).ok().as_deref() == Some(config.as_slice()) => {
            record("unchanged");
            set_in_sync(true);
            return Ok(());
        }
        Some(object) => Precondition::Matches(object.etag),
        None => Precondition::Absent,
    };
    match backups
        .put(key, &wrap_config(&config)?, precondition)
        .await?
    {
        PutOutcome::Written => {
            record("uploaded");
            set_in_sync(true);
            tracing::info!(key, "backed up config/changelog");
            Ok(())
        }
        PutOutcome::Conflict => {
            record("conflict");
            anyhow::bail!("the backup changed after it was read")
        }
    }
}

/// A deletion is never backed up, because the last good copy is what a
/// rebuild restores.
async fn watch_once(
    store: &PersonhogStore,
    backups: &dyn BackupStore,
    key: &str,
) -> anyhow::Result<()> {
    let (_, revision) = store.get_changelog_config_raw_with_revision().await?;
    sync(store, backups, key).await?;
    let mut stream = store.watch_changelog_config_from(revision + 1).await?;
    while let Some(response) = stream.message().await? {
        if response.canceled() {
            anyhow::bail!(
                "config/changelog watch cancelled by etcd: {}",
                response.cancel_reason()
            );
        }
        for event in response.events() {
            match event.event_type() {
                EventType::Put => sync(store, backups, key).await?,
                EventType::Delete => {
                    record("deleted_skipped");
                    tracing::warn!(key, "config/changelog was deleted; keeping the last backup");
                }
            }
        }
    }
    anyhow::bail!("config/changelog watch ended")
}

pub async fn run(etcd: Arc<EtcdHandle>, prefix: String, backups: Arc<dyn BackupStore>) {
    let key = object_key(&prefix);
    let mut delay = RETRY_INITIAL;
    set_in_sync(false);
    loop {
        let started = Instant::now();
        let attempt = async {
            let client = etcd.client().await?;
            watch_once(&changelog::store(&client, &prefix), backups.as_ref(), &key).await
        };
        if let Err(e) = attempt.await {
            record("error");
            set_in_sync(false);
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
    use std::hash::{DefaultHasher, Hash, Hasher};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;

    use envconfig::Envconfig;
    use tokio::sync::Notify;

    use super::*;
    use crate::config::Config;

    /// Versions in insertion order, the last one current. Like S3, the ETag
    /// is a hash of the body, so identical bodies share an ETag.
    #[derive(Default)]
    pub(crate) struct MemoryBackups {
        pub(crate) versions: Mutex<Vec<Vec<u8>>>,
    }

    fn etag(body: &[u8]) -> String {
        let mut hasher = DefaultHasher::new();
        body.hash(&mut hasher);
        format!("{:x}", hasher.finish())
    }

    impl MemoryBackups {
        fn configs(&self) -> Vec<Vec<u8>> {
            let versions = self.versions.lock().unwrap();
            versions.iter().map(|v| unwrap_config(v).unwrap()).collect()
        }
    }

    #[async_trait]
    impl BackupStore for MemoryBackups {
        async fn get(
            &self,
            _key: &str,
            version_id: Option<&str>,
        ) -> anyhow::Result<Option<StoredObject>> {
            let versions = self.versions.lock().unwrap();
            let body = match version_id {
                None => versions.last(),
                Some(id) => id.parse::<usize>().ok().and_then(|i| versions.get(i)),
            };
            Ok(body.map(|body| StoredObject {
                body: body.clone(),
                etag: etag(body),
            }))
        }

        async fn put(
            &self,
            _key: &str,
            value: &[u8],
            precondition: Precondition,
        ) -> anyhow::Result<PutOutcome> {
            let mut versions = self.versions.lock().unwrap();
            let current = versions.last().map(|body| etag(body));
            let holds = match precondition {
                Precondition::Absent => current.is_none(),
                Precondition::Matches(expected) => current == Some(expected),
            };
            if !holds {
                return Ok(PutOutcome::Conflict);
            }
            versions.push(value.to_vec());
            Ok(PutOutcome::Written)
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

    #[derive(Clone, Copy, Debug, PartialEq)]
    enum Stall {
        BeforeRead,
        BeforeUpload,
    }

    struct Stalled {
        inner: Arc<MemoryBackups>,
        at: Stall,
        stalled: AtomicBool,
        arrived: Notify,
        release: Notify,
    }

    impl Stalled {
        fn new(inner: Arc<MemoryBackups>, at: Stall) -> Arc<Self> {
            Arc::new(Self {
                inner,
                at,
                stalled: AtomicBool::new(false),
                arrived: Notify::new(),
                release: Notify::new(),
            })
        }

        async fn stall(&self, at: Stall) {
            if at == self.at && !self.stalled.swap(true, Ordering::SeqCst) {
                self.arrived.notify_one();
                self.release.notified().await;
            }
        }
    }

    #[async_trait]
    impl BackupStore for Stalled {
        async fn get(
            &self,
            key: &str,
            version_id: Option<&str>,
        ) -> anyhow::Result<Option<StoredObject>> {
            self.stall(Stall::BeforeRead).await;
            self.inner.get(key, version_id).await
        }

        async fn put(
            &self,
            key: &str,
            value: &[u8],
            precondition: Precondition,
        ) -> anyhow::Result<PutOutcome> {
            self.stall(Stall::BeforeUpload).await;
            self.inner.put(key, value, precondition).await
        }

        async fn versions(&self, key: &str) -> anyhow::Result<Vec<BackupVersion>> {
            self.inner.versions(key).await
        }
    }

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
    async fn s3_store_reads_versions_and_enforces_upload_conditions() {
        let store = local_s3().await;
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let key = format!("test-{nanos}/config-changelog.json");
        assert_eq!(store.get(&key, None).await.unwrap(), None);

        let put = |value: &'static [u8], precondition| store.put(&key, value, precondition);
        assert_eq!(
            put(b"first", Precondition::Absent).await.unwrap(),
            PutOutcome::Written
        );
        assert_eq!(
            put(b"again", Precondition::Absent).await.unwrap(),
            PutOutcome::Conflict
        );
        let first = store.get(&key, None).await.unwrap().unwrap();
        assert_eq!(
            put(b"second", Precondition::Matches(first.etag.clone()))
                .await
                .unwrap(),
            PutOutcome::Written
        );
        assert_eq!(
            put(b"stale", Precondition::Matches(first.etag))
                .await
                .unwrap(),
            PutOutcome::Conflict
        );

        assert_eq!(
            store.get(&key, None).await.unwrap().unwrap().body,
            b"second"
        );
        let versions = store.versions(&key).await.unwrap();
        assert_eq!(versions.len(), 2);
        assert!(versions[0].is_latest);
        let earlier = store
            .get(&key, Some(&versions[1].version_id))
            .await
            .unwrap();
        assert_eq!(earlier.unwrap().body, b"first");
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

        let inner = store.inner();
        let key = format!("{}config/changelog", inner.prefix());
        inner.put_raw(&key, seeded.clone()).await.unwrap();
        let moved = br#"{"topic":"personhog_updates_128","partitions":128,"epoch":2}"#.to_vec();
        inner.put_raw(&key, moved.clone()).await.unwrap();
        wait_for_versions(&backups, 2).await;
        inner.delete(&key).await.unwrap();
        // Events arrive in order, so this one being backed up proves the
        // deletion before it was handled.
        let reseeded = br#"{"topic":"personhog_updates_128","partitions":128,"epoch":3}"#.to_vec();
        inner.put_raw(&key, reseeded.clone()).await.unwrap();
        wait_for_versions(&backups, 3).await;
        watcher.abort();

        assert_eq!(backups.configs(), vec![seeded, moved, reseeded]);
    }

    fn spawn_sync(
        client: &etcd_client::Client,
        prefix: &str,
        backups: Arc<Stalled>,
    ) -> tokio::task::JoinHandle<anyhow::Result<()>> {
        let store = changelog::store(client, prefix);
        let key = object_key(prefix);
        tokio::spawn(async move { sync(&store, backups.as_ref(), &key).await })
    }

    #[tokio::test]
    async fn a_stalled_pod_never_replaces_a_newer_backup() {
        for at in [Stall::BeforeRead, Stall::BeforeUpload] {
            let (etcd, prefix) = test_etcd("backup-race").await;
            let client = etcd.client().await.unwrap();
            let store = changelog::store(&client, &prefix);
            let inner = store.inner();
            let etcd_key = format!("{}config/changelog", inner.prefix());
            let key = object_key(&prefix);
            let without_group =
                br#"{"topic":"personhog_updates_64","partitions":64,"epoch":1,"writer_group":"personhog-writer","draining":[]}"#.to_vec();
            let with_group =
                br#"{"topic":"personhog_updates_64","partitions":64,"epoch":1,"writer_group":"personhog-writer","retire_groups":["relay"],"draining":[]}"#.to_vec();
            let backups = Arc::new(MemoryBackups::default());
            inner
                .put_raw(&etcd_key, without_group.clone())
                .await
                .unwrap();
            sync(&store, backups.as_ref(), &key).await.unwrap();

            inner.put_raw(&etcd_key, with_group.clone()).await.unwrap();
            let stalled = Stalled::new(backups.clone(), at);
            let pod_a = spawn_sync(&client, &prefix, stalled.clone());
            stalled.arrived.notified().await;

            // Pod B backs up the added group; the group is removed again,
            // which restores the original bytes, and pod C backs that up.
            sync(&store, backups.as_ref(), &key).await.unwrap();
            inner
                .put_raw(&etcd_key, without_group.clone())
                .await
                .unwrap();
            sync(&store, backups.as_ref(), &key).await.unwrap();
            stalled.release.notify_one();
            // Pod A either finds the backup current or has its upload refused.
            let _refused = pod_a.await.unwrap();

            assert_eq!(
                backups.configs().last(),
                Some(&without_group),
                "stalled {at:?}"
            );
        }
    }

    #[tokio::test]
    async fn a_refused_upload_fails_and_the_next_attempt_backs_up_the_latest_config() {
        let (etcd, prefix) = test_etcd("backup-retry").await;
        let client = etcd.client().await.unwrap();
        let store = changelog::store(&client, &prefix);
        let inner = store.inner();
        let etcd_key = format!("{}config/changelog", inner.prefix());
        let config = |epoch: u64| {
            format!(r#"{{"topic":"personhog_updates_64","partitions":64,"epoch":{epoch},"writer_group":"personhog-writer","draining":[]}}"#)
                .into_bytes()
        };
        let backups = Arc::new(MemoryBackups::default());
        inner.put_raw(&etcd_key, config(1)).await.unwrap();
        sync(&store, backups.as_ref(), &object_key(&prefix))
            .await
            .unwrap();

        inner.put_raw(&etcd_key, config(2)).await.unwrap();
        let w = Stalled::new(backups.clone(), Stall::BeforeUpload);
        let pod_w = spawn_sync(&client, &prefix, w.clone());
        w.arrived.notified().await;
        inner.put_raw(&etcd_key, config(3)).await.unwrap();
        let a = Stalled::new(backups.clone(), Stall::BeforeUpload);
        let pod_a = spawn_sync(&client, &prefix, a.clone());
        a.arrived.notified().await;

        // W's older upload lands first, so A's is refused.
        w.release.notify_one();
        pod_w.await.unwrap().unwrap();
        a.release.notify_one();
        assert!(pod_a.await.unwrap().is_err(), "the refusal is reported");
        assert_eq!(backups.configs().last(), Some(&config(2)));

        sync(&store, backups.as_ref(), &object_key(&prefix))
            .await
            .unwrap();

        assert_eq!(backups.configs().last(), Some(&config(3)));
    }
}
