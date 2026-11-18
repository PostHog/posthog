//! Running this replica as a changelog follower: it registers for partitions in its own
//! coordination instance and serves people from the leader's cache, kept current from
//! the changelog.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use lifecycle::Handle;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::changelog::{
    keep_changelog_live_every, load_changelog_config, LiveChangelog, CHANGELOG_BOOT_POLL_INTERVAL,
    FOLLOWER_RECONCILE_INTERVAL,
};
use personhog_coordination::pod::{
    PodConfig, PodHandle, DRAIN_SETUP_BOUND, REVOKE_TIMEOUT, SHUTDOWN_FENCE_BOUND,
};
use personhog_coordination::store::PersonhogStore;
use personhog_leader::cache::{DirtyIndex, PartitionedCache};
use personhog_leader::config::derive_advertise_address;
use personhog_leader::follow::handler::FollowerHandler;
use personhog_leader::follow::{FollowConfig, Follower};
use personhog_leader::pg::validate_table_name;
use personhog_leader::recovery::{ChangelogRecovery, RecoveryConfig};
use personhog_leader::warming::{WarmClientPools, WarmingConfig, WarmingRetryPolicy};
use tokio_util::sync::CancellationToken;

use tokio::sync::Notify;

use crate::service::FollowerReads;

const EPOCH_POLL_INTERVAL: Duration = Duration::from_millis(100);
/// How long a warm may go without progress, and how long it may take to be confirmed current.
const STALL_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Envconfig, Clone)]
pub struct FollowerSettings {
    #[envconfig(from = "FOLLOWER_ENABLED", default = "false")]
    pub enabled: bool,

    #[envconfig(from = "FOLLOWER_ETCD_ENDPOINTS", default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    /// This follower instance's own prefix: its registrations, assignments and handoffs.
    #[envconfig(from = "FOLLOWER_ETCD_PREFIX", default = "/personhog-follower/")]
    pub etcd_prefix: String,

    /// The leaders' prefix, where the changelog config is kept.
    #[envconfig(from = "FOLLOWER_CHANGELOG_ETCD_PREFIX", default = "/personhog/")]
    pub changelog_etcd_prefix: String,

    #[envconfig(from = "POD_NAME", default = "personhog-replica-0")]
    pub pod_name: String,

    #[envconfig(from = "POD_IP", default = "")]
    pub pod_ip: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    /// The table the writer maintains. A person with no unapplied writes is loaded from
    /// it, so it must be the writer's target.
    #[envconfig(from = "FOLLOWER_PERSON_TABLE", default = "posthog_person")]
    pub person_table: String,

    /// Cache budget per followed partition.
    #[envconfig(from = "FOLLOWER_CACHE_CAPACITY_BYTES", default = "16777216")]
    pub cache_capacity_bytes: usize,

    /// A partition not confirmed current within this long refuses reads.
    #[envconfig(from = "FOLLOWER_STALENESS_THRESHOLD_MS", default = "500")]
    pub staleness_threshold_ms: u64,

    #[envconfig(from = "FOLLOWER_END_CHECK_INTERVAL_MS", default = "100")]
    pub end_check_interval_ms: u64,

    /// Longer than the Postgres read replica can lag.
    #[envconfig(from = "FOLLOWER_MIN_WARM_MS", default = "300")]
    pub min_warm_ms: u64,

    #[envconfig(from = "FOLLOWER_MARK_CLEAR_INTERVAL_MS", default = "1000")]
    pub mark_clear_interval_ms: u64,

    /// Longer than the Postgres read replica can lag.
    #[envconfig(from = "FOLLOWER_MARK_CLEAR_GRACE_MS", default = "300")]
    pub mark_clear_grace_ms: u64,

    #[envconfig(from = "FOLLOWER_LEASE_TTL_SECS", default = "10")]
    pub lease_ttl_secs: i64,

    #[envconfig(from = "FOLLOWER_HEARTBEAT_INTERVAL_SECS", default = "3")]
    pub heartbeat_interval_secs: u64,

    /// How long a stopping follower waits for its partitions to hand off.
    #[envconfig(from = "FOLLOWER_DRAIN_TIMEOUT_SECS", default = "10")]
    pub drain_timeout_secs: u64,

    #[envconfig(from = "FOLLOWER_WARM_CONCURRENCY", default = "4")]
    pub warm_concurrency: usize,

    #[envconfig(from = "FOLLOWER_RECOVERY_POOL_SIZE", default = "2")]
    pub recovery_pool_size: usize,
}

impl FollowerSettings {
    /// The timing settings only work in these relations to each other.
    pub fn validate(&self) -> Result<(), String> {
        if self.end_check_interval_ms >= self.staleness_threshold_ms {
            return Err(format!(
                "FOLLOWER_END_CHECK_INTERVAL_MS ({}) must be below \
                 FOLLOWER_STALENESS_THRESHOLD_MS ({}): a partition is confirmed current once \
                 per interval, so it would otherwise never stay current",
                self.end_check_interval_ms, self.staleness_threshold_ms
            ));
        }
        if Duration::from_millis(self.min_warm_ms) >= STALL_TIMEOUT {
            return Err(format!(
                "FOLLOWER_MIN_WARM_MS ({}) must be below the {STALL_TIMEOUT:?} a warm has to \
                 be confirmed current",
                self.min_warm_ms
            ));
        }
        Ok(())
    }

    /// The pod's whole teardown: the drain, then its fence, keepalive join and lease revoke.
    pub fn coordination_shutdown(&self) -> Duration {
        DRAIN_SETUP_BOUND
            + Duration::from_secs(self.drain_timeout_secs)
            + SHUTDOWN_FENCE_BOUND
            + Duration::from_secs(self.heartbeat_interval_secs)
            + REVOKE_TIMEOUT
    }
}

// The Kafka settings have no `Debug`, and need none in a config dump.
impl std::fmt::Debug for FollowerSettings {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FollowerSettings")
            .field("enabled", &self.enabled)
            .field("etcd_prefix", &self.etcd_prefix)
            .field("changelog_etcd_prefix", &self.changelog_etcd_prefix)
            .finish_non_exhaustive()
    }
}

/// Join the follower instance and start following. Returns what the service reads from,
/// or `None` when shutdown arrived before the changelog config could be read.
pub async fn start(
    settings: &FollowerSettings,
    grpc_address: &SocketAddr,
    replica_pool: sqlx::PgPool,
    handle: Handle,
) -> Result<Option<FollowerReads>, String> {
    settings.validate()?;
    validate_table_name(&settings.person_table)?;
    let inner = EtcdStore::connect_with_member_failover(StoreConfig {
        endpoints: settings
            .etcd_endpoints
            .split(',')
            .map(|endpoint| endpoint.trim().to_string())
            .collect(),
        prefix: settings.etcd_prefix.clone(),
    })
    .await
    .map_err(|e| format!("connect to etcd: {e}"))?;
    let store =
        Arc::new(PersonhogStore::new(inner).with_config_prefix(&settings.changelog_etcd_prefix));

    let shutdown = handle.shutdown_token();
    let Some(loaded) = load_changelog_config(&store, CHANGELOG_BOOT_POLL_INTERVAL, &shutdown)
        .await
        .map_err(|e| format!("load the changelog config: {e}"))?
    else {
        return Ok(None);
    };
    let changelog = LiveChangelog::new(loaded.clone());

    let warming = WarmingConfig {
        kafka: settings.kafka.clone(),
        pod_name: settings.pod_name.clone(),
        writer_consumer_group: loaded.writer_group.clone(),
        committed_offsets_timeout: Duration::from_secs(5),
        fetch_watermarks_timeout: Duration::from_secs(5),
        recv_timeout: STALL_TIMEOUT,
        retry: WarmingRetryPolicy {
            max_attempts: 3,
            initial_backoff: Duration::from_millis(100),
            max_backoff: Duration::from_secs(1),
        },
    };
    let pools = Arc::new(WarmClientPools::new(
        &settings.kafka,
        &settings.pod_name,
        &loaded.writer_group,
    ));
    let recovery = ChangelogRecovery::new(RecoveryConfig {
        kafka: settings.kafka.clone(),
        pod_name: settings.pod_name.clone(),
        recv_timeout: Duration::from_secs(5),
        pool_size: settings.recovery_pool_size,
        cluster: loaded.cluster.clone().map(Arc::new),
    })?;
    let follower = Arc::new(Follower::new(
        FollowConfig {
            staleness_threshold: Duration::from_millis(settings.staleness_threshold_ms),
            end_check_interval: Duration::from_millis(settings.end_check_interval_ms),
            min_warm: Duration::from_millis(settings.min_warm_ms),
        },
        warming,
        pools,
        Arc::new(PartitionedCache::new(settings.cache_capacity_bytes)),
        // Leaders stop taking writes when their own index is full, which bounds this one.
        Arc::new(DirtyIndex::new(usize::MAX)),
        Arc::new(recovery),
    ));

    let pod_config = PodConfig {
        pod_name: settings.pod_name.clone(),
        lease_ttl: settings.lease_ttl_secs,
        heartbeat_interval: Duration::from_secs(settings.heartbeat_interval_secs),
        drain_timeout: Duration::from_secs(settings.drain_timeout_secs),
        advertise_address: Some(derive_advertise_address(grpc_address, &settings.pod_ip)?),
        warm_concurrency: settings.warm_concurrency,
        ..PodConfig::default()
    };
    let rebuild = Arc::new(Notify::new());
    let config_store = Arc::clone(&store);
    let pod = PodHandle::new(
        store,
        pod_config,
        Arc::new(FollowerHandler::new(
            Arc::clone(&follower),
            changelog.clone(),
        )),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    )
    .with_repair_nudge(Arc::clone(&rebuild));
    let keep_config_live = keep_changelog_live_every(
        config_store,
        changelog.clone(),
        FOLLOWER_RECONCILE_INTERVAL,
        CancellationToken::new(),
    );
    // A new config epoch means every partition must be rebuilt. The handler does that on
    // its next pass, and this runs one at once instead of at the next reconcile tick.
    let rebuild_on_a_new_epoch = {
        let changelog = changelog.clone();
        async move {
            let mut seen = changelog.epoch();
            loop {
                tokio::time::sleep(EPOCH_POLL_INTERVAL).await;
                let epoch = changelog.epoch();
                if epoch != seen {
                    seen = epoch;
                    rebuild.notify_one();
                }
            }
        }
    };
    let clear_marks = {
        let (follower, changelog) = (Arc::clone(&follower), changelog.clone());
        let interval = Duration::from_millis(settings.mark_clear_interval_ms);
        let grace = Duration::from_millis(settings.mark_clear_grace_ms);
        async move {
            follower
                .clear_applied_marks(changelog, interval, grace)
                .await
        }
    };
    // Each loop is its own task, so a long warm cannot hold up the config re-read, and one
    // supervisor watches them all: any of them ending stops the component. The watch and
    // the mark clearing outlive the supervisor, as the pod serves through its drain.
    let mut keep_config_live = tokio::spawn(keep_config_live);
    let mut clear_marks = tokio::spawn(clear_marks);
    tokio::spawn(async move {
        let _guard = handle.process_scope();
        tokio::select! {
            ran = pod.run(handle.shutdown_token()) => {
                if let Err(e) = ran {
                    handle.signal_failure(format!("follower coordination error: {e}"));
                }
            }
            _ = &mut keep_config_live => {
                handle.signal_failure("the follower's changelog config watch stopped".to_string());
            }
            _ = &mut clear_marks => {
                handle.signal_failure("the follower stopped clearing applied marks".to_string());
            }
            () = rebuild_on_a_new_epoch => {}
        }
    });

    Ok(Some(FollowerReads {
        follower,
        changelog,
        pool: replica_pool,
        table: settings.person_table.clone(),
    }))
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use rstest::rstest;

    use super::*;

    #[rstest]
    #[case::defaults(&[], true)]
    #[case::end_checks_no_faster_than_the_threshold(
        &[("FOLLOWER_END_CHECK_INTERVAL_MS", "500")],
        false
    )]
    #[case::a_minimum_warm_no_warm_can_meet(&[("FOLLOWER_MIN_WARM_MS", "10000")], false)]
    fn timing_settings_must_work_together(#[case] env: &[(&str, &str)], #[case] valid: bool) {
        let env: HashMap<String, String> = env
            .iter()
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect();
        let settings = FollowerSettings::init_from_hashmap(&env).expect("settings");

        assert_eq!(settings.validate().is_ok(), valid);
    }
}
