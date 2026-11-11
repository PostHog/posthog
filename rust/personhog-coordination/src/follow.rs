//! A changelog consumer's single subscription follows `config/changelog`: the
//! oldest generation its group has not drained first, then the live topic.

use std::collections::HashSet;
use std::future::Future;
use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use metrics::counter;
use tokio_util::sync::CancellationToken;
use tracing::info;

use crate::changelog::{watch_changelog_config_loop, CHANGELOG_RECONCILE_INTERVAL};
use crate::store::PersonhogStore;
use crate::types::{ChangelogConfig, ClusterEndpoint, DrainReport};

/// How often a consumer on a sealed generation re-checks its group's drain.
/// Each check reads every partition of the generation under a probe group.
pub const DRAIN_POLL_INTERVAL: Duration = Duration::from_secs(2);

pub const REBIND_LOG: &str =
    "the next changelog generation lives on another cluster; restarting to subscribe there";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FollowTarget {
    pub topic: String,
    pub cluster: Option<ClusterEndpoint>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum FollowStep {
    Stayed,
    Moved(String),
    /// The next topic lives on another cluster; the process restarts to subscribe there.
    Rebind(FollowTarget),
}

/// The consumer side of a followed subscription.
pub trait ChangelogSubscription {
    fn topic(&self) -> String;
    fn cluster(&self) -> Option<ClusterEndpoint>;
    /// Only called once the group has drained the current topic.
    fn resubscribe(&self, topic: &str) -> Result<(), String>;
    fn set_draining(&self, draining: bool);
    fn is_draining(&self) -> bool;
}

/// Chooses the subscription. A generation once proven drained is never chosen
/// again, so a slow or failed probe cannot send the consumer back to it.
#[derive(Default)]
pub struct Follower {
    drained: HashSet<String>,
    /// Proven drained, with no drain report written yet.
    unreported: Vec<String>,
}

impl Follower {
    /// The oldest draining generation not proven drained, else the live topic.
    pub async fn select_topic<F, Fut>(
        &mut self,
        changelog: &ChangelogConfig,
        drained: F,
    ) -> Result<FollowTarget, String>
    where
        F: Fn(FollowTarget) -> Fut,
        Fut: Future<Output = Result<bool, String>>,
    {
        let mut generations = changelog.draining.clone();
        generations.sort_by_key(|g| g.epoch);
        for generation in generations {
            if self.drained.contains(&generation.topic) {
                continue;
            }
            let target = FollowTarget {
                topic: generation.topic.clone(),
                cluster: generation.cluster.clone(),
            };
            if !drained(target.clone()).await? {
                return Ok(target);
            }
            self.unreported.push(generation.topic.clone());
            self.drained.insert(generation.topic);
        }
        Ok(FollowTarget {
            topic: changelog.topic.clone(),
            cluster: changelog.cluster.clone(),
        })
    }

    /// One pass of the follow loop. The draining flag follows the config
    /// before the subscription is touched, so it holds whether or not the
    /// subscription moved.
    pub async fn follow_once<S, F, Fut>(
        &mut self,
        subscription: &S,
        changelog: &ChangelogConfig,
        drained: F,
    ) -> Result<FollowStep, String>
    where
        S: ChangelogSubscription + ?Sized,
        F: Fn(FollowTarget) -> Fut,
        Fut: Future<Output = Result<bool, String>>,
    {
        let wanted = self.select_topic(changelog, &drained).await?;
        let subscribed = subscription.topic();
        // A generation can leave the config before this group drains it, when
        // retire stops waiting on the group; finish reading it before moving on.
        if subscribed != wanted.topic
            && subscribed != changelog.topic
            && !self.drained.contains(&subscribed)
        {
            let current = FollowTarget {
                topic: subscribed.clone(),
                cluster: subscription.cluster(),
            };
            if !drained(current).await? {
                subscription.set_draining(true);
                return Ok(FollowStep::Stayed);
            }
            self.drained.insert(subscribed.clone());
        }
        subscription.set_draining(wanted.topic != changelog.topic);
        if wanted.topic == subscribed {
            return Ok(FollowStep::Stayed);
        }
        // Every move follows a proven drain, so nothing is left to commit on the old cluster.
        if wanted.cluster != subscription.cluster() {
            return Ok(FollowStep::Rebind(wanted));
        }
        subscription
            .resubscribe(&wanted.topic)
            .map_err(|e| format!("re-subscribe to {}: {e}", wanted.topic))?;
        info!(from = %subscribed, to = %wanted.topic, "moved the subscription");
        Ok(FollowStep::Moved(subscribed))
    }

    /// Writes a drain report for every generation proven drained since the
    /// last call; a failed write is kept and retried on the next call.
    pub async fn report(&mut self, store: &PersonhogStore, reporter: &Reporter) {
        for topic in std::mem::take(&mut self.unreported) {
            let report = DrainReport {
                topic: topic.clone(),
                group: reporter.group.clone(),
                reported_by: reporter.pod.clone(),
                reported_at_ms: crate::util::now_millis(),
            };
            match store.put_drain_report(&report).await {
                Ok(()) => {
                    counter!("personhog_changelog_drain_reports_total", "outcome" => "written")
                        .increment(1);
                    info!(topic = %topic, group = %reporter.group, "reported the generation drained");
                }
                Err(e) => {
                    counter!("personhog_changelog_drain_reports_total", "outcome" => "failed")
                        .increment(1);
                    tracing::warn!(topic = %topic, error = %e, "could not report the generation drained; retrying");
                    self.unreported.push(topic);
                }
            }
        }
    }
}

/// Who writes a follower's drain reports: the consumer group they speak for, and the pod.
#[derive(Debug, Clone)]
pub struct Reporter {
    pub group: String,
    pub pod: String,
}

impl Reporter {
    /// The pod is named by `HOSTNAME`, which Kubernetes sets to the pod name.
    pub fn for_group(group: &str) -> Self {
        Self {
            group: group.to_string(),
            pod: std::env::var("HOSTNAME").unwrap_or_else(|_| "unknown".to_string()),
        }
    }
}

/// Follows the config until `cancel`: re-checks on every config change, and on a
/// timer that is short while the subscription drains a sealed generation.
/// Reports each generation it proves drained. `on_move` sees each move as (from, to).
#[allow(clippy::too_many_arguments)]
pub async fn follow_changelog<S, F, Fut, M>(
    store: Arc<PersonhogStore>,
    loaded: ChangelogConfig,
    mut follower: Follower,
    subscription: Arc<S>,
    drained: F,
    reporter: Reporter,
    on_move: M,
    cancel: CancellationToken,
) -> Option<FollowTarget>
where
    S: ChangelogSubscription + ?Sized,
    F: Fn(FollowTarget) -> Fut,
    Fut: Future<Output = Result<bool, String>>,
    M: Fn(&str, &str),
{
    counter!("personhog_changelog_drain_reports_total", "outcome" => "written").increment(0);
    counter!("personhog_changelog_drain_reports_total", "outcome" => "failed").increment(0);
    let (config_tx, mut config_rx) = tokio::sync::watch::channel(loaded.clone());
    let watch = watch_changelog_config_loop(
        Arc::clone(&store),
        loaded,
        CHANGELOG_RECONCILE_INTERVAL,
        cancel.clone(),
        move |next| {
            drop(config_tx.send(next.clone()));
            ControlFlow::Continue(())
        },
    );
    let follow = async {
        loop {
            let current = config_rx.borrow().clone();
            match follower
                .follow_once(subscription.as_ref(), &current, &drained)
                .await
            {
                Ok(FollowStep::Moved(from)) => on_move(&from, &subscription.topic()),
                Ok(FollowStep::Stayed) => {}
                Ok(FollowStep::Rebind(next)) => {
                    // Reports first, so the drain this move rests on is recorded before the restart.
                    follower.report(&store, &reporter).await;
                    tracing::warn!(
                        topic = %next.topic,
                        cluster = ?next.cluster.as_ref().map(|c| &c.name),
                        "{REBIND_LOG}"
                    );
                    return Some(next);
                }
                Err(e) => tracing::warn!(
                    error = %e,
                    "could not follow the changelog config; keeping the subscription"
                ),
            }
            follower.report(&store, &reporter).await;
            let poll = if subscription.is_draining() {
                DRAIN_POLL_INTERVAL
            } else {
                CHANGELOG_RECONCILE_INTERVAL
            };
            tokio::select! {
                changed = config_rx.changed() => {
                    if changed.is_err() {
                        return None;
                    }
                }
                _ = tokio::time::sleep(poll) => {}
            }
        }
    };
    tokio::select! {
        _ = cancel.cancelled() => None,
        _ = watch => None,
        next = follow => next,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;

    use super::*;

    struct Subscription {
        topic: Mutex<String>,
        cluster: Option<ClusterEndpoint>,
        draining: AtomicBool,
    }

    impl ChangelogSubscription for Subscription {
        fn topic(&self) -> String {
            self.topic.lock().unwrap().clone()
        }

        fn cluster(&self) -> Option<ClusterEndpoint> {
            self.cluster.clone()
        }

        fn resubscribe(&self, topic: &str) -> Result<(), String> {
            *self.topic.lock().unwrap() = topic.to_string();
            Ok(())
        }

        fn set_draining(&self, draining: bool) {
            self.draining.store(draining, Ordering::SeqCst);
        }

        fn is_draining(&self) -> bool {
            self.draining.load(Ordering::SeqCst)
        }
    }

    #[tokio::test]
    async fn a_generation_retired_before_the_group_drained_it_is_read_to_the_end() {
        let subscription = Subscription {
            topic: Mutex::new("old".to_string()),
            cluster: None,
            draining: AtomicBool::new(true),
        };
        let live = ChangelogConfig::new("new", 8);
        let mut follower = Follower::default();

        let moved = follower
            .follow_once(&subscription, &live, |_| async { Ok(false) })
            .await
            .unwrap();
        assert_eq!(moved, FollowStep::Stayed);
        assert_eq!(subscription.topic(), "old");
        assert!(subscription.is_draining());

        let moved = follower
            .follow_once(&subscription, &live, |_| async { Ok(true) })
            .await
            .unwrap();
        assert_eq!(moved, FollowStep::Moved("old".to_string()));
        assert_eq!(subscription.topic(), "new");
        assert!(!subscription.is_draining());
    }

    #[tokio::test]
    async fn a_successor_on_another_cluster_rebinds_instead_of_resubscribing() {
        let subscription = Subscription {
            topic: Mutex::new("old".to_string()),
            cluster: None,
            draining: AtomicBool::new(true),
        };
        let mut live = ChangelogConfig::new("new", 8);
        let dedicated = ClusterEndpoint {
            name: "dedicated".to_string(),
            hosts: "dedicated:9092".to_string(),
            tls: false,
        };
        live.cluster = Some(dedicated.clone());
        // The subscription predates the recorded cluster, so the probe must use the generation's.
        let ingestion = ClusterEndpoint {
            name: "ingestion".to_string(),
            hosts: "ingestion:9092".to_string(),
            tls: false,
        };
        live.draining.push(crate::types::Generation {
            topic: "old".to_string(),
            partitions: 4,
            epoch: 1,
            cluster: Some(ingestion.clone()),
        });
        let probed = Mutex::new(Vec::new());
        let mut follower = Follower::default();

        let step = follower
            .follow_once(&subscription, &live, |target| {
                probed.lock().unwrap().push(target);
                async { Ok(true) }
            })
            .await
            .unwrap();
        assert_eq!(
            step,
            FollowStep::Rebind(FollowTarget {
                topic: "new".to_string(),
                cluster: Some(dedicated),
            })
        );
        assert_eq!(subscription.topic(), "old");
        assert_eq!(
            probed.lock().unwrap().first(),
            Some(&FollowTarget {
                topic: "old".to_string(),
                cluster: Some(ingestion),
            })
        );
    }
}
