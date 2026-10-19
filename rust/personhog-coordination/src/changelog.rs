//! Boot-time load and the shared watch of `config/changelog`.

use std::ops::ControlFlow;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;

use etcd_client::EventType;
use tokio_util::sync::CancellationToken;

use crate::error::{Error, Result};
use crate::store::PersonhogStore;
use crate::types::ChangelogConfig;
use crate::util;

/// Polls until `config/changelog` is seeded; it is the only source of the topic and count.
pub async fn load_changelog_config(
    store: &PersonhogStore,
    poll_interval: Duration,
) -> Result<ChangelogConfig> {
    let mut polls: u64 = 0;
    loop {
        if let Some(config) = store.get_changelog_config().await? {
            return Ok(config);
        }
        if polls.is_multiple_of(10) {
            tracing::warn!("config/changelog is not seeded; waiting for the control plane");
        }
        polls += 1;
        tokio::time::sleep(poll_interval).await;
    }
}

/// Delivers each object that supersedes the last one adopted; `initial` is what boot adopted.
pub async fn watch_changelog_config_loop<F>(
    store: Arc<PersonhogStore>,
    initial: ChangelogConfig,
    reconcile_interval: Duration,
    cancel: CancellationToken,
    mut on_config: F,
) where
    F: FnMut(&ChangelogConfig) -> ControlFlow<()>,
{
    let mut adopted = initial;
    let mut backoff = Duration::from_millis(100);
    'establish: loop {
        if cancel.is_cancelled() {
            return;
        }
        let established = async {
            let (current, revision) = store.get_changelog_config_with_revision().await?;
            let stream = store.watch_changelog_config_from(revision + 1).await?;
            Ok::<_, Error>((current, stream))
        };
        let (current, mut stream) = match established.await {
            Ok(established) => established,
            Err(e) => {
                tracing::warn!(error = %e, "changelog config watch could not be established");
                metrics::counter!("personhog_changelog_config_watch_reconnects_total").increment(1);
                tokio::select! {
                    _ = cancel.cancelled() => return,
                    _ = tokio::time::sleep(backoff) => {}
                }
                backoff = (backoff * 2).min(Duration::from_secs(5));
                continue 'establish;
            }
        };
        backoff = Duration::from_millis(100);
        if let Some(config) = &current {
            if deliver(&mut adopted, config, "establish", &mut on_config).is_break() {
                return;
            }
        }

        let mut reconcile = tokio::time::interval(reconcile_interval);
        reconcile.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        reconcile.tick().await;
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return,
                _ = reconcile.tick() => {
                    match store.get_changelog_config().await {
                        Ok(Some(config)) => {
                            if deliver(&mut adopted, &config, "reconcile", &mut on_config).is_break() {
                                return;
                            }
                        }
                        Ok(None) => {}
                        Err(e) => {
                            tracing::warn!(error = %e, "changelog config reconcile read failed");
                        }
                    }
                }
                msg = stream.message() => {
                    let resp = match msg.map_err(Error::from).and_then(|resp| util::live_watch_response(resp, "changelog config")) {
                        Ok(resp) => resp,
                        Err(e) => {
                            tracing::warn!(error = %e, "changelog config watch broke; re-establishing");
                            metrics::counter!("personhog_changelog_config_watch_reconnects_total").increment(1);
                            continue 'establish;
                        }
                    };
                    for event in resp.events() {
                        if event.event_type() != EventType::Put {
                            continue;
                        }
                        let Some(kv) = event.kv() else { continue };
                        match serde_json::from_slice::<ChangelogConfig>(kv.value()) {
                            Ok(config) => {
                                if deliver(&mut adopted, &config, "watch", &mut on_config).is_break() {
                                    return;
                                }
                            }
                            Err(e) => {
                                tracing::error!(error = %e, "unreadable changelog config event; the reconcile read will retry");
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Bounds the staleness a dropped watch stream can hide.
pub const CHANGELOG_RECONCILE_INTERVAL: Duration = Duration::from_secs(30);
pub const CHANGELOG_BOOT_POLL_INTERVAL: Duration = Duration::from_secs(1);

/// The partition count has its own atomic: routing reads it per request.
#[derive(Clone)]
pub struct LiveChangelog {
    current: Arc<std::sync::RwLock<ChangelogConfig>>,
    partitions: Arc<AtomicU32>,
}

impl LiveChangelog {
    pub fn new(config: ChangelogConfig) -> Self {
        Self {
            partitions: Arc::new(AtomicU32::new(config.partitions)),
            current: Arc::new(std::sync::RwLock::new(config)),
        }
    }

    pub fn partitions(&self) -> u32 {
        self.partitions.load(Ordering::Acquire)
    }

    pub fn current(&self) -> ChangelogConfig {
        self.current
            .read()
            .expect("changelog config lock poisoned")
            .clone()
    }

    pub fn epoch(&self) -> u64 {
        self.current
            .read()
            .expect("changelog config lock poisoned")
            .epoch
    }

    pub fn adopt(&self, config: &ChangelogConfig) -> bool {
        let mut current = self
            .current
            .write()
            .expect("changelog config lock poisoned");
        if !config.supersedes(&current) {
            return false;
        }
        *current = config.clone();
        self.partitions.store(config.partitions, Ordering::Release);
        true
    }
}

pub async fn keep_changelog_live(
    store: Arc<PersonhogStore>,
    live: LiveChangelog,
    cancel: CancellationToken,
) {
    let initial = live.current();
    watch_changelog_config_loop(
        store,
        initial,
        CHANGELOG_RECONCILE_INTERVAL,
        cancel,
        |config| {
            live.adopt(config);
            ControlFlow::Continue(())
        },
    )
    .await
}

fn deliver<F>(
    adopted: &mut ChangelogConfig,
    config: &ChangelogConfig,
    source: &'static str,
    on_config: &mut F,
) -> ControlFlow<()>
where
    F: FnMut(&ChangelogConfig) -> ControlFlow<()>,
{
    if !config.supersedes(adopted) {
        metrics::counter!("personhog_changelog_config_stale_deliveries_total", "source" => source)
            .increment(1);
        return ControlFlow::Continue(());
    }
    *adopted = config.clone();
    metrics::counter!("personhog_changelog_config_adoptions_total", "source" => source)
        .increment(1);
    metrics::gauge!("personhog_changelog_config_epoch").set(config.epoch as f64);
    tracing::info!(
        topic = %config.topic,
        partitions = config.partitions,
        epoch = config.epoch,
        source,
        "adopted changelog config"
    );
    on_config(config)
}
