//! Boot-time load and the shared watch of `config/changelog`.

use std::ops::ControlFlow;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
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

/// Keys a source contributes: those that hash to `target` under `modulus`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyFilter {
    pub modulus: u32,
    pub target: u32,
}

/// One changelog partition a warm replays from the writer's committed offset.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WarmSource {
    pub topic: Arc<str>,
    pub partition: u32,
    pub keep: Option<KeyFilter>,
}

impl WarmSource {
    pub fn live(topic: &str, partition: u32) -> Self {
        Self {
            topic: Arc::from(topic),
            partition,
            keep: None,
        }
    }
}

fn gcd(a: u32, b: u32) -> u32 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

/// What a warm of `partition` replays: each draining generation's partitions
/// that can hold its keys (a key's old and new partitions agree mod the gcd),
/// oldest first, then the live partition.
pub fn warm_sources(config: &ChangelogConfig, partition: u32) -> Vec<WarmSource> {
    let mut draining = config.draining.clone();
    draining.sort_by_key(|g| g.epoch);
    let mut sources = Vec::new();
    for generation in &draining {
        let g = gcd(generation.partitions, config.partitions);
        for q in (0..generation.partitions).filter(|q| q % g == partition % g) {
            sources.push(WarmSource {
                topic: Arc::from(generation.topic.as_str()),
                partition: q,
                keep: Some(KeyFilter {
                    modulus: config.partitions,
                    target: partition,
                }),
            });
        }
    }
    sources.push(WarmSource::live(&config.topic, partition));
    sources
}

/// Bounds the staleness a dropped watch stream can hide.
pub const CHANGELOG_RECONCILE_INTERVAL: Duration = Duration::from_secs(30);
pub const CHANGELOG_BOOT_POLL_INTERVAL: Duration = Duration::from_secs(1);

/// The partition count and the draining floor have their own atomics:
/// routing reads them per request.
#[derive(Clone)]
pub struct LiveChangelog {
    current: Arc<std::sync::RwLock<ChangelogConfig>>,
    partitions: Arc<AtomicU32>,
    draining_floor: Arc<AtomicU32>,
    /// The floor outlived the generation that set it, until `release_floor`.
    floor_held: Arc<AtomicBool>,
    /// Only a router routes by the floor, so only it holds one past a retire.
    holds_floor: bool,
}

/// The smallest partition count among the draining generations; `u32::MAX` when none drains.
fn draining_floor_of(config: &ChangelogConfig) -> u32 {
    config
        .draining
        .iter()
        .map(|g| g.partitions)
        .min()
        .unwrap_or(u32::MAX)
}

impl LiveChangelog {
    pub fn new(config: ChangelogConfig) -> Self {
        Self {
            partitions: Arc::new(AtomicU32::new(config.partitions)),
            draining_floor: Arc::new(AtomicU32::new(draining_floor_of(&config))),
            floor_held: Arc::new(AtomicBool::new(false)),
            holds_floor: false,
            current: Arc::new(std::sync::RwLock::new(config)),
        }
    }

    /// Keeps a grow's floor past its retire until `release_floor`, for a router.
    pub fn holding_floor(mut self) -> Self {
        self.holds_floor = true;
        metrics::gauge!("personhog_changelog_floor_held").set(0.0);
        self
    }

    pub fn partitions(&self) -> u32 {
        self.partitions.load(Ordering::Acquire)
    }

    /// Partitions at or above the floor were born in a flip; `None` once
    /// nothing drains and any held floor was released.
    pub fn draining_floor(&self) -> Option<u32> {
        let floor = self.draining_floor.load(Ordering::Acquire);
        (floor != u32::MAX).then_some(floor)
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
        // A retire can land before this process routes every partition the flip
        // created, so the floor of a grow stays until `release_floor`. A grow
        // adopted without its draining config holds one at the old count.
        let mut floor = draining_floor_of(config);
        let held = if self.holds_floor && floor == u32::MAX {
            let grown_from = if config.partitions > current.partitions {
                current.partitions
            } else {
                u32::MAX
            };
            let carried = self.draining_floor.load(Ordering::Acquire).min(grown_from);
            if carried < config.partitions {
                floor = carried;
            }
            carried < config.partitions
        } else {
            false
        };
        *current = config.clone();
        self.floor_held.store(held, Ordering::Release);
        // The floor first: a reader that sees the new count sees its floor too.
        self.draining_floor.store(floor, Ordering::Release);
        self.partitions.store(config.partitions, Ordering::Release);
        if self.holds_floor {
            metrics::gauge!("personhog_changelog_floor_held").set(if held { 1.0 } else { 0.0 });
        }
        true
    }

    /// Whether the floor outlived its draining generation.
    pub fn floor_held(&self) -> bool {
        self.floor_held.load(Ordering::Acquire)
    }

    /// Drops a held floor once the caller routes every partition in
    /// `floor..partitions`, if that is still the held range: an adoption
    /// between the caller's check and this call may have carried the floor
    /// over a larger count. A floor that a draining generation sets stays.
    pub fn release_floor(&self, floor: u32, partitions: u32) {
        let _current = self
            .current
            .write()
            .expect("changelog config lock poisoned");
        if self.floor_held.load(Ordering::Acquire)
            && self.draining_floor.load(Ordering::Acquire) == floor
            && self.partitions.load(Ordering::Acquire) == partitions
        {
            self.floor_held.store(false, Ordering::Release);
            self.draining_floor.store(u32::MAX, Ordering::Release);
            metrics::gauge!("personhog_changelog_floor_held").set(0.0);
        }
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::Generation;

    fn config(partitions: u32, draining: Vec<(u32, u64)>) -> ChangelogConfig {
        ChangelogConfig {
            topic: "new".to_string(),
            partitions,
            epoch: 9,
            writer_group: String::new(),
            retire_groups: vec![],
            draining: draining
                .into_iter()
                .map(|(partitions, epoch)| Generation {
                    topic: format!("old{epoch}"),
                    partitions,
                    epoch,
                })
                .collect(),
        }
    }

    /// A grow's floor survives the retire until released; a shrink's never
    /// needs to; a grow adopted without its draining config holds one at the old count.
    #[test]
    fn a_grows_floor_is_held_past_the_retire_until_released() {
        let at_epoch = |epoch: u64, partitions: u32, draining: Vec<(u32, u64)>| ChangelogConfig {
            epoch,
            ..config(partitions, draining)
        };
        let cases = [
            (
                "grow, then retire",
                at_epoch(2, 8, vec![(4, 1)]),
                at_epoch(2, 8, vec![]),
                Some(4),
            ),
            (
                "shrink, then retire",
                at_epoch(2, 4, vec![(8, 1)]),
                at_epoch(2, 4, vec![]),
                None,
            ),
            (
                "grow seen only retired",
                at_epoch(1, 4, vec![]),
                at_epoch(2, 8, vec![]),
                Some(4),
            ),
        ];
        for (name, before, after, held) in cases {
            let live = LiveChangelog::new(before).holding_floor();
            assert!(live.adopt(&after), "{name}");
            assert_eq!(live.draining_floor(), held, "{name}");
            assert_eq!(live.floor_held(), held.is_some(), "{name}");
            live.release_floor(held.unwrap_or(u32::MAX), live.partitions());
            assert_eq!(live.draining_floor(), None, "{name}");
        }

        let draining = LiveChangelog::new(at_epoch(2, 8, vec![(4, 1)])).holding_floor();
        draining.release_floor(4, 8);
        assert_eq!(draining.draining_floor(), Some(4));

        // A second grow adopted between the check and the release carries the
        // floor over a larger count; the release of the checked range is stale.
        let regrown = LiveChangelog::new(at_epoch(2, 8, vec![(4, 1)])).holding_floor();
        assert!(regrown.adopt(&at_epoch(2, 8, vec![])));
        assert!(regrown.adopt(&at_epoch(3, 16, vec![])));
        regrown.release_floor(4, 8);
        assert_eq!(regrown.draining_floor(), Some(4));
        regrown.release_floor(4, 16);
        assert_eq!(regrown.draining_floor(), None);

        // A process that does not route never holds a floor past the retire.
        let leader = LiveChangelog::new(at_epoch(2, 8, vec![(4, 1)]));
        assert!(leader.adopt(&at_epoch(2, 8, vec![])));
        assert_eq!(leader.draining_floor(), None);
        assert!(!leader.floor_held());
    }

    fn old_partitions(
        partitions: u32,
        draining: Vec<(u32, u64)>,
        partition: u32,
    ) -> Vec<(String, u32)> {
        warm_sources(&config(partitions, draining), partition)
            .into_iter()
            .filter(|s| s.keep.is_some())
            .map(|s| (s.topic.to_string(), s.partition))
            .collect()
    }

    #[test]
    fn a_warm_replays_the_congruent_old_partitions_then_the_live_one() {
        // Doubling: one old partition feeds each new one.
        assert_eq!(
            old_partitions(128, vec![(64, 1)], 65),
            vec![("old1".to_string(), 1)]
        );
        // Dev's shrink: four old partitions feed each new one.
        assert_eq!(
            old_partitions(64, vec![(256, 1)], 5),
            vec![
                ("old1".to_string(), 5),
                ("old1".to_string(), 69),
                ("old1".to_string(), 133),
                ("old1".to_string(), 197)
            ]
        );
        // Coprime counts: every old partition may hold the keys.
        assert_eq!(old_partitions(4, vec![(3, 1)], 1).len(), 3);
        // Two generations replay oldest first, whatever the list order.
        let sources = warm_sources(&config(8, vec![(4, 2), (2, 1)]), 1);
        let topics: Vec<String> = sources.iter().map(|s| s.topic.to_string()).collect();
        assert_eq!(topics, vec!["old1", "old2", "new"]);
        let live = sources.last().unwrap();
        assert!(live.keep.is_none());
        assert_eq!(live.partition, 1);
        assert!(sources[0]
            .keep
            .as_ref()
            .is_some_and(|k| k.modulus == 8 && k.target == 1));
    }
}
