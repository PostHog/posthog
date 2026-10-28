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
use crate::types::{ChangelogConfig, DrainReport};

/// How often a consumer on a sealed generation re-checks its group's drain.
/// Each check reads every partition of the generation under a probe group.
pub const DRAIN_POLL_INTERVAL: Duration = Duration::from_secs(2);

/// The consumer side of a followed subscription.
pub trait ChangelogSubscription {
    fn topic(&self) -> String;
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
    ) -> Result<String, String>
    where
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<bool, String>>,
    {
        let mut generations = changelog.draining.clone();
        generations.sort_by_key(|g| g.epoch);
        for generation in generations {
            if self.drained.contains(&generation.topic) {
                continue;
            }
            if !drained(generation.topic.clone()).await? {
                return Ok(generation.topic);
            }
            self.unreported.push(generation.topic.clone());
            self.drained.insert(generation.topic);
        }
        Ok(changelog.topic.clone())
    }

    /// One pass of the follow loop; returns the topic it moved off, if it moved.
    /// The draining flag follows the config before the subscription is touched,
    /// so it holds whether or not the subscription moved.
    pub async fn follow_once<S, F, Fut>(
        &mut self,
        subscription: &S,
        changelog: &ChangelogConfig,
        drained: F,
    ) -> Result<Option<String>, String>
    where
        S: ChangelogSubscription + ?Sized,
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<bool, String>>,
    {
        let wanted = self.select_topic(changelog, &drained).await?;
        let subscribed = subscription.topic();
        // A generation can leave the config before this group drains it, when
        // retire stops waiting on the group; finish reading it before moving on.
        if subscribed != wanted
            && subscribed != changelog.topic
            && !self.drained.contains(&subscribed)
        {
            if !drained(subscribed.clone()).await? {
                subscription.set_draining(true);
                return Ok(None);
            }
            self.drained.insert(subscribed.clone());
        }
        subscription.set_draining(wanted != changelog.topic);
        if wanted == subscribed {
            return Ok(None);
        }
        subscription
            .resubscribe(&wanted)
            .map_err(|e| format!("re-subscribe to {wanted}: {e}"))?;
        info!(from = %subscribed, to = %wanted, "moved the subscription");
        Ok(Some(subscribed))
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
) where
    S: ChangelogSubscription + ?Sized,
    F: Fn(String) -> Fut,
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
                Ok(Some(from)) => on_move(&from, &subscription.topic()),
                Ok(None) => {}
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
                        return;
                    }
                }
                _ = tokio::time::sleep(poll) => {}
            }
        }
    };
    tokio::select! {
        _ = cancel.cancelled() => {}
        _ = watch => {}
        _ = follow => {}
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;

    use super::*;

    struct Subscription {
        topic: Mutex<String>,
        draining: AtomicBool,
    }

    impl ChangelogSubscription for Subscription {
        fn topic(&self) -> String {
            self.topic.lock().unwrap().clone()
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
            draining: AtomicBool::new(true),
        };
        let live = ChangelogConfig::new("new", 8);
        let mut follower = Follower::default();

        let moved = follower
            .follow_once(&subscription, &live, |_| async { Ok(false) })
            .await
            .unwrap();
        assert_eq!(moved, None);
        assert_eq!(subscription.topic(), "old");
        assert!(subscription.is_draining());

        let moved = follower
            .follow_once(&subscription, &live, |_| async { Ok(true) })
            .await
            .unwrap();
        assert_eq!(moved, Some("old".to_string()));
        assert_eq!(subscription.topic(), "new");
        assert!(!subscription.is_draining());
    }
}
