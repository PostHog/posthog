use std::time::Duration;

use anyhow::{bail, Context};
use assignment_coordination::store::{EtcdStore, StoreConfig};
use etcd_client::Client;
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{
    ChangelogConfig, ChangelogTarget, MigrationPhase, MigrationRequest, MigrationState,
};
use rdkafka::consumer::Consumer;
use serde::Serialize;

use crate::backup::{self, BackupStore, BackupVersion};
use crate::config::Config;
use crate::kafka::client::{base_client_config, metadata_consumer};
use crate::kafka::lag::{scan_group_lag, ConsumerTarget};

pub(crate) fn store(client: &Client, prefix: &str) -> PersonhogStore {
    PersonhogStore::new(EtcdStore::from_client(
        client.clone(),
        StoreConfig {
            endpoints: Vec::new(),
            prefix: prefix.to_string(),
        },
    ))
}

pub async fn topic_partition_count(config: &Config, topic: &str) -> anyhow::Result<u32> {
    let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
    let config = config.clone();
    let topic = topic.to_string();
    tokio::task::spawn_blocking(move || {
        let consumer = metadata_consumer(&config).context("create metadata client")?;
        let metadata = consumer
            .fetch_metadata(Some(&topic), timeout)
            .with_context(|| format!("fetch metadata for {topic}"))?;
        let topic_metadata = metadata
            .topics()
            .iter()
            .find(|t| t.name() == topic)
            .with_context(|| format!("topic {topic} is absent from broker metadata"))?;
        if let Some(error) = topic_metadata.error() {
            bail!("topic {topic}: {error:?}");
        }
        let count = topic_metadata.partitions().len();
        if count == 0 {
            bail!("topic {topic} has no partitions");
        }
        Ok(count as u32)
    })
    .await
    .context("metadata task panicked")?
}

pub async fn seed(
    config: &Config,
    client: &Client,
    prefix: &str,
    topic: &str,
    writer_group: &str,
) -> anyhow::Result<ChangelogConfig> {
    let config = &config.personhog_kafka();
    let partitions = topic_partition_count(config, topic).await?;
    let created = store(client, prefix)
        .seed_changelog_config(topic, partitions, writer_group)
        .await?;
    if !created {
        bail!("config/changelog is already seeded; only a migration may move it");
    }
    Ok(ChangelogConfig {
        writer_group: writer_group.to_string(),
        ..ChangelogConfig::new(topic, partitions)
    })
}

pub async fn backups(
    backups: &dyn BackupStore,
    prefix: &str,
) -> anyhow::Result<Vec<BackupVersion>> {
    backups.versions(&backup::object_key(prefix)).await
}

#[derive(Debug)]
pub enum RestoreError {
    NotFound(String),
    Refused(String),
    Upstream(anyhow::Error),
}

impl From<anyhow::Error> for RestoreError {
    fn from(error: anyhow::Error) -> Self {
        Self::Upstream(error)
    }
}

pub async fn restore(
    config: &Config,
    client: &Client,
    prefix: &str,
    backups: &dyn BackupStore,
    version_id: Option<&str>,
) -> Result<ChangelogConfig, RestoreError> {
    let key = backup::object_key(prefix);
    let object = backups.get(&key, version_id).await?.ok_or_else(|| {
        RestoreError::NotFound(match version_id {
            Some(version) => format!("no backup version {version} of {key}"),
            None => format!("no backup at {key}"),
        })
    })?;
    let value =
        backup::unwrap_config(&object.body).map_err(|e| RestoreError::Refused(format!("{e:#}")))?;
    let restored: ChangelogConfig = serde_json::from_slice(&value)
        .map_err(|e| RestoreError::Refused(format!("the backup is not a changelog config: {e}")))?;
    let live_partitions = topic_partition_count(&config.personhog_kafka(), &restored.topic).await?;
    apply_restore(&store(client, prefix), &value, restored, live_partitions).await
}

async fn apply_restore(
    store: &PersonhogStore,
    value: &[u8],
    restored: ChangelogConfig,
    live_partitions: u32,
) -> Result<ChangelogConfig, RestoreError> {
    if live_partitions != restored.partitions {
        return Err(RestoreError::Refused(format!(
            "topic {} has {live_partitions} partitions but the backup records {}; the backup may be from another environment",
            restored.topic, restored.partitions
        )));
    }
    let created = store
        .restore_changelog_config_raw(value)
        .await
        .map_err(|e| RestoreError::Upstream(e.into()))?;
    if !created {
        return Err(RestoreError::Refused(
            "config/changelog already exists; restore only rebuilds an empty etcd".to_string(),
        ));
    }
    Ok(restored)
}

#[derive(Serialize)]
pub struct GroupLag {
    pub group: String,
    pub partitions: usize,
    pub lagging_partitions: usize,
    pub total_lag: i64,
    /// The worst single partition's lag: what one restart replays in a grow.
    pub max_partition_lag: i64,
    pub error: Option<String>,
}

#[derive(Serialize)]
pub struct ChangelogView {
    pub config: Option<ChangelogConfig>,
    pub writer: Option<GroupLag>,
    pub retire_groups: Vec<GroupLag>,
    pub migration: Option<MigrationState>,
    pub request: Option<MigrationRequest>,
    pub history: Vec<MigrationState>,
    pub draining: Vec<DrainingView>,
}

#[derive(Serialize)]
pub struct GroupDrain {
    pub group: String,
    pub drained_partitions: usize,
    pub partitions: usize,
    pub error: Option<String>,
    /// The group's own drain report, which the coordinator retires on.
    pub reported: bool,
}

/// A draining generation and how far each gating group has read it.
#[derive(Serialize)]
pub struct DrainingView {
    pub topic: String,
    pub partitions: u32,
    pub epoch: u64,
    pub writer: GroupDrain,
    pub retire_groups: Vec<GroupDrain>,
}

async fn group_drain(config: &Config, group: &str, topic: &str) -> GroupDrain {
    let base = base_client_config(config);
    let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
    let (group_owned, topic_owned) = (group.to_string(), topic.to_string());
    let probed = tokio::task::spawn_blocking(move || {
        common_kafka::probe::partitions_drained(&base, &group_owned, &topic_owned, timeout)
    })
    .await;
    match probed {
        Ok(Ok(drained)) => GroupDrain {
            group: group.to_string(),
            drained_partitions: drained.values().filter(|ok| **ok).count(),
            partitions: drained.len(),
            error: None,
            reported: false,
        },
        Ok(Err(e)) => GroupDrain {
            group: group.to_string(),
            drained_partitions: 0,
            partitions: 0,
            error: Some(e.to_string()),
            reported: false,
        },
        Err(e) => GroupDrain {
            group: group.to_string(),
            drained_partitions: 0,
            partitions: 0,
            error: Some(format!("probe task panicked: {e}")),
            reported: false,
        },
    }
}

/// Add a consumer group, such as the relay's, that retire then waits on as well.
pub async fn add_retire_group(client: &Client, prefix: &str, group: &str) -> anyhow::Result<()> {
    if !store(client, prefix)
        .add_changelog_retire_group(group)
        .await?
    {
        bail!("config/changelog is not seeded or moved; refresh and retry");
    }
    Ok(())
}

/// Stop retire waiting on a group, for a consumer that no longer runs.
pub async fn remove_retire_group(client: &Client, prefix: &str, group: &str) -> anyhow::Result<()> {
    if !store(client, prefix)
        .remove_changelog_retire_group(group)
        .await?
    {
        bail!("config/changelog is not seeded or moved; refresh and retry");
    }
    Ok(())
}

/// Drop a drained generation from the config; deleting the topic stays a Terraform change.
pub async fn retire(
    config: &Config,
    client: &Client,
    prefix: &str,
    topic: &str,
) -> anyhow::Result<()> {
    let config = &config.personhog_kafka();
    let store = store(client, prefix);
    let (live, mod_revision) = store
        .get_changelog_config_with_mod_revision()
        .await?
        .context("config/changelog is not seeded")?;
    if !live.draining.iter().any(|g| g.topic == topic) {
        bail!("{topic} is not a draining generation");
    }
    if let Some(migration) = store.get_migration().await? {
        bail!(
            "migration {} is {:?}; retire once it completes",
            migration.id,
            migration.phase
        );
    }
    for group in live.gated_groups() {
        let drain = group_drain(config, group, topic).await;
        if let Some(error) = drain.error {
            bail!("group {group}: {error}");
        }
        if drain.partitions == 0 || drain.drained_partitions < drain.partitions {
            bail!(
                "group {group} has read {} of {} partitions of {topic} to the end",
                drain.drained_partitions,
                drain.partitions
            );
        }
    }
    if !store
        .retire_changelog_topic(&live, mod_revision, topic)
        .await?
    {
        bail!("the config moved or a migration started; refresh and retry");
    }
    common_metrics::inc(
        "personhog_changelog_retires_total",
        &[("trigger".to_string(), "manual".to_string())],
        1,
    );
    Ok(())
}

/// Request a migration; the coordinator starts it once the fleet is quiet.
/// Writer lag does not block it; the panel shows the lag to the operator.
pub async fn start_migration(
    config: &Config,
    client: &Client,
    prefix: &str,
    topic: &str,
) -> anyhow::Result<MigrationRequest> {
    let config = &config.personhog_kafka();
    let store = store(client, prefix);
    let live = store
        .get_changelog_config()
        .await?
        .context("config/changelog is not seeded")?;
    if live.topic == topic {
        bail!("{topic} is already the live changelog");
    }
    let partitions = topic_partition_count(config, topic).await?;
    let now_ms = assignment_coordination::util::now_millis();
    let request = MigrationRequest {
        id: format!("m-{now_ms}"),
        from: live.target(),
        to: ChangelogTarget {
            topic: topic.to_string(),
            partitions,
        },
        requested_at_ms: now_ms,
        seen_at_ms: None,
        waiting: Vec::new(),
    };
    if !store.create_migration_request(&request).await? {
        bail!("a migration is already requested or in flight");
    }
    Ok(request)
}

const WITHDRAW_ATTEMPTS: usize = 5;

/// Withdraw a waiting request, or cancel a running saga before Sealing.
pub async fn cancel_migration(
    client: &Client,
    prefix: &str,
    id: &str,
) -> anyhow::Result<MigrationState> {
    let store = store(client, prefix);
    // The coordinator rewrites a waiting request as handoffs move, so a withdraw
    // retries on that race; if this request started instead, it is cancelled below.
    for _ in 0..WITHDRAW_ATTEMPTS {
        let Some((request, mod_revision)) = store.get_migration_request_with_mod_revision().await?
        else {
            break;
        };
        if request.id != id {
            bail!(
                "the waiting request is {}, not {id}; refresh and retry",
                request.id
            );
        }
        if store
            .reject_migration_request(&request, mod_revision, "withdrawn")
            .await?
        {
            return Ok(request.rejected("withdrawn", assignment_coordination::util::now_millis()));
        }
    }
    let Some((migration, mod_revision)) = store.get_migration_with_mod_revision().await? else {
        if let Some(ended) = store
            .list_migration_history()
            .await?
            .into_iter()
            .find(|m| m.id == id)
        {
            bail!(
                "{id} already ended: {:?} {}",
                ended.phase,
                ended.blocking.join("; ")
            );
        }
        bail!("no migration is in flight");
    };
    if migration.id != id {
        bail!(
            "the running migration is {}, not {id}; refresh and retry",
            migration.id
        );
    }
    if !migration
        .phase
        .may_transition_to(MigrationPhase::Cancelling)
    {
        bail!("a migration in {:?} cannot be cancelled", migration.phase);
    }
    if !store
        .cancel_migration(&migration.id, mod_revision, "operator")
        .await?
    {
        bail!("the migration moved on; refresh and retry");
    }
    Ok(migration)
}

pub async fn view(config: &Config, client: &Client, prefix: &str) -> anyhow::Result<ChangelogView> {
    let config = &config.personhog_kafka();
    let store = store(client, prefix);
    let changelog = store.get_changelog_config().await?;
    let migration = store.get_migration().await?;
    let request = store
        .get_migration_request_with_mod_revision()
        .await?
        .map(|(request, _)| request);
    let mut history = store.list_migration_history().await?;
    history.sort_by_key(|m| std::cmp::Reverse(m.created_at_ms));
    let mut draining = Vec::new();
    if let Some(changelog) = &changelog {
        let reports = store.list_drain_reports().await?;
        let drain = |group: &str, topic: &str| {
            let reported = reports.iter().any(|r| r.group == group && r.topic == topic);
            let (group, topic) = (group.to_string(), topic.to_string());
            async move {
                GroupDrain {
                    reported,
                    ..group_drain(config, &group, &topic).await
                }
            }
        };
        for generation in &changelog.draining {
            draining.push(DrainingView {
                topic: generation.topic.clone(),
                partitions: generation.partitions,
                epoch: generation.epoch,
                writer: drain(&changelog.writer_group, &generation.topic).await,
                retire_groups: {
                    let mut drains = Vec::new();
                    for group in &changelog.retire_groups {
                        drains.push(drain(group, &generation.topic).await);
                    }
                    drains
                },
            });
        }
    }
    let writer = match &changelog {
        Some(changelog) => Some(group_lag(config, &changelog.writer_group, &changelog.topic).await),
        None => None,
    };
    let mut retire_groups = Vec::new();
    if let Some(changelog) = &changelog {
        for group in &changelog.retire_groups {
            retire_groups.push(group_lag(config, group, &changelog.topic).await);
        }
    }
    Ok(ChangelogView {
        config: changelog,
        writer,
        retire_groups,
        migration,
        request,
        history,
        draining,
    })
}

async fn group_lag(config: &Config, group: &str, topic: &str) -> GroupLag {
    let target = ConsumerTarget {
        group: group.to_string(),
        topic: topic.to_string(),
    };
    match scan_group_lag(config, &target).await {
        Ok(lag) => GroupLag {
            group: group.to_string(),
            partitions: lag.partitions.len(),
            lagging_partitions: lag.partitions.iter().filter(|p| p.lag > 0).count(),
            total_lag: lag.partitions.iter().map(|p| p.lag).sum(),
            max_partition_lag: lag.partitions.iter().map(|p| p.lag).max().unwrap_or(0),
            error: None,
        },
        Err(e) => GroupLag {
            group: group.to_string(),
            partitions: 0,
            lagging_partitions: 0,
            total_lag: 0,
            max_partition_lag: 0,
            error: Some(format!("{e:#}")),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backup::tests::test_etcd;

    async fn empty_store(name: &str) -> PersonhogStore {
        let (etcd, prefix) = test_etcd(name).await;
        store(&etcd.client().await.unwrap(), &prefix)
    }

    fn backed_up(partitions: u32) -> (Vec<u8>, ChangelogConfig) {
        // A field this build does not know must survive the round trip.
        let value = format!(
            r#"{{"topic":"personhog_updates_64","partitions":{partitions},"epoch":4,"writer_group":"personhog-writer","draining":[],"future_field":"kept"}}"#
        )
        .into_bytes();
        let parsed = serde_json::from_slice(&value).unwrap();
        (value, parsed)
    }

    #[tokio::test]
    async fn restore_writes_the_backed_up_bytes_into_an_empty_etcd() {
        let store = empty_store("restore-empty").await;
        let (value, parsed) = backed_up(64);

        let restored = apply_restore(&store, &value, parsed, 64).await.unwrap();

        assert_eq!(restored.epoch, 4);
        let (stored, _) = store
            .get_changelog_config_raw_with_revision()
            .await
            .unwrap();
        assert_eq!(stored.unwrap(), value);
    }

    #[tokio::test]
    async fn restore_refuses_a_seeded_etcd() {
        let store = empty_store("restore-seeded").await;
        assert!(store
            .seed_changelog_config("personhog_updates_64", 64, "personhog-writer")
            .await
            .unwrap());
        let (value, parsed) = backed_up(64);

        let refused = apply_restore(&store, &value, parsed, 64).await;

        assert!(
            matches!(refused, Err(RestoreError::Refused(ref m)) if m.contains("already exists")),
            "{refused:?}"
        );
        let current = store.get_changelog_config().await.unwrap().unwrap();
        assert_eq!(current.epoch, 1, "the seeded config is untouched");
    }

    #[tokio::test]
    async fn restore_refuses_a_backup_whose_partitions_do_not_match_the_topic() {
        let store = empty_store("restore-mismatch").await;
        let (value, parsed) = backed_up(128);

        let refused = apply_restore(&store, &value, parsed, 64).await;

        assert!(
            matches!(refused, Err(RestoreError::Refused(ref m)) if m.contains("another environment")),
            "{refused:?}"
        );
        let (stored, _) = store
            .get_changelog_config_raw_with_revision()
            .await
            .unwrap();
        assert!(stored.is_none(), "nothing is written");
    }
}
