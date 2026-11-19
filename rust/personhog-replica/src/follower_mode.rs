//! Running this replica as a changelog follower: it registers for partitions in its own
//! coordination instance and answers single-person reads from the leader's cache, kept
//! current from the changelog. The replica serves from Postgres whenever it is not
//! following, so nothing here holds up or fails the server.

use std::convert::Infallible;
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
use personhog_coordination::types::ChangelogConfig;
use personhog_leader::cache::PartitionedCache;
use personhog_leader::config::derive_advertise_address;
use personhog_leader::follow::handler::FollowerHandler;
use personhog_leader::follow::{FollowConfig, Follower};
use personhog_leader::warming::{WarmClientPools, WarmingConfig, WarmingRetryPolicy};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use crate::service::{Attached, FollowerReads};

const EPOCH_POLL_INTERVAL: Duration = Duration::from_millis(100);
/// How long a warm may go without progress, and how long it may take to be confirmed current.
const STALL_TIMEOUT: Duration = Duration::from_secs(10);
/// How long a follower that stopped waits before it tries to follow again.
const RESTART_DELAY: Duration = Duration::from_secs(5);

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

    /// Cache budget per followed partition.
    #[envconfig(from = "FOLLOWER_CACHE_CAPACITY_BYTES", default = "16777216")]
    pub cache_capacity_bytes: usize,

    /// A partition not confirmed current within this long answers no reads.
    #[envconfig(from = "FOLLOWER_STALENESS_THRESHOLD_MS", default = "5000")]
    pub staleness_threshold_ms: u64,

    #[envconfig(from = "FOLLOWER_END_CHECK_INTERVAL_MS", default = "1000")]
    pub end_check_interval_ms: u64,

    #[envconfig(from = "FOLLOWER_LEASE_TTL_SECS", default = "10")]
    pub lease_ttl_secs: i64,

    #[envconfig(from = "FOLLOWER_HEARTBEAT_INTERVAL_SECS", default = "3")]
    pub heartbeat_interval_secs: u64,

    /// How long a stopping follower waits for its partitions to hand off.
    #[envconfig(from = "FOLLOWER_DRAIN_TIMEOUT_SECS", default = "10")]
    pub drain_timeout_secs: u64,

    /// How many partitions are built at once, for a handoff or after a changelog config
    /// change.
    #[envconfig(from = "FOLLOWER_WARM_CONCURRENCY", default = "4")]
    pub warm_concurrency: usize,
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

/// Start following in the background. What it returns answers nothing until the follower
/// has joined its coordination instance, and nothing again whenever it stops.
pub fn start(
    settings: &FollowerSettings,
    grpc_address: &SocketAddr,
    handle: Handle,
) -> Result<FollowerReads, String> {
    settings.validate()?;
    let advertise_address = derive_advertise_address(grpc_address, &settings.pod_ip)?;
    let reads = FollowerReads::default();
    tokio::spawn(keep_following(
        settings.clone(),
        advertise_address,
        reads.clone(),
        handle,
    ));
    Ok(reads)
}

/// Follow until shutdown, starting over whenever coordination gives up.
async fn keep_following(
    settings: FollowerSettings,
    advertise_address: String,
    reads: FollowerReads,
    handle: Handle,
) {
    let _guard = handle.process_scope();
    let shutdown = handle.shutdown_token();
    loop {
        match follow(&settings, &advertise_address, &reads, &shutdown).await {
            Ok(()) => return,
            Err(e) => {
                common_metrics::inc("personhog_follower_restarts_total", &[], 1);
                tracing::error!(
                    error = %e,
                    "follower stopped; reads come from Postgres until it follows again"
                );
            }
        }
        tokio::select! {
            () = shutdown.cancelled() => return,
            () = tokio::time::sleep(RESTART_DELAY) => {}
        }
    }
}

/// Join the follower instance and follow until shutdown, which is `Ok`.
async fn follow(
    settings: &FollowerSettings,
    advertise_address: &str,
    reads: &FollowerReads,
    shutdown: &CancellationToken,
) -> Result<(), String> {
    let connect = EtcdStore::connect_with_member_failover(StoreConfig {
        endpoints: settings
            .etcd_endpoints
            .split(',')
            .map(|endpoint| endpoint.trim().to_string())
            .collect(),
        prefix: settings.etcd_prefix.clone(),
    });
    let inner = tokio::select! {
        () = shutdown.cancelled() => return Ok(()),
        connected = connect => connected.map_err(|e| format!("connect to etcd: {e}"))?,
    };
    let store =
        Arc::new(PersonhogStore::new(inner).with_config_prefix(&settings.changelog_etcd_prefix));
    let Some(loaded) = load_changelog_config(&store, CHANGELOG_BOOT_POLL_INTERVAL, shutdown)
        .await
        .map_err(|e| format!("load the changelog config: {e}"))?
    else {
        return Ok(());
    };
    let Attached {
        follower,
        changelog,
    } = reads.attach(|| attached(settings, &loaded));
    changelog.adopt(&loaded);

    let pod_config = PodConfig {
        pod_name: settings.pod_name.clone(),
        lease_ttl: settings.lease_ttl_secs,
        heartbeat_interval: Duration::from_secs(settings.heartbeat_interval_secs),
        drain_timeout: Duration::from_secs(settings.drain_timeout_secs),
        advertise_address: Some(advertise_address.to_string()),
        warm_concurrency: settings.warm_concurrency.max(1),
        ..PodConfig::default()
    };
    let rebuild = Arc::new(Notify::new());
    let pod = PodHandle::new(
        Arc::clone(&store),
        pod_config,
        Arc::new(FollowerHandler::new(
            Arc::clone(follower),
            changelog.clone(),
            settings.warm_concurrency,
        )),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    )
    .with_repair_nudge(Arc::clone(&rebuild));
    // Its own task, so a long warm cannot hold up the config re-read.
    let keep_config_live = tokio::spawn(keep_changelog_live_every(
        store,
        changelog.clone(),
        FOLLOWER_RECONCILE_INTERVAL,
        CancellationToken::new(),
    ));
    let ran = tokio::select! {
        ran = pod.run(shutdown.clone()) => ran,
        never = rebuild_on_a_new_epoch(changelog.clone(), rebuild) => match never {},
    };
    keep_config_live.abort();
    if ran.is_err() {
        follower.release_all();
    }
    ran.map_err(|e| format!("follower coordination error: {e}"))
}

fn attached(settings: &FollowerSettings, loaded: &ChangelogConfig) -> Attached {
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
    let follower = Follower::new(
        FollowConfig {
            staleness_threshold: Duration::from_millis(settings.staleness_threshold_ms),
            end_check_interval: Duration::from_millis(settings.end_check_interval_ms),
        },
        warming,
        pools,
        Arc::new(PartitionedCache::new(settings.cache_capacity_bytes)),
    );
    Attached {
        follower: Arc::new(follower),
        changelog: LiveChangelog::new(loaded.clone()),
    }
}

/// A new config epoch means every partition must be rebuilt. The handler does that on its
/// next pass, and this runs one at once instead of at the next reconcile tick.
async fn rebuild_on_a_new_epoch(changelog: LiveChangelog, rebuild: Arc<Notify>) -> Infallible {
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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use rstest::rstest;

    use super::*;

    #[rstest]
    #[case::defaults(&[], true)]
    #[case::end_checks_no_faster_than_the_threshold(
        &[("FOLLOWER_END_CHECK_INTERVAL_MS", "5000")],
        false
    )]
    fn timing_settings_must_work_together(#[case] env: &[(&str, &str)], #[case] valid: bool) {
        let env: HashMap<String, String> = env
            .iter()
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect();
        let settings = FollowerSettings::init_from_hashmap(&env).expect("settings");

        assert_eq!(settings.validate().is_ok(), valid);
    }
}
