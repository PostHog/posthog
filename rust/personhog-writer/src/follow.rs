//! The subscription follows `config/changelog`: the oldest generation the
//! group has not drained first, then the live topic.

use std::collections::HashSet;
use std::future::Future;

use metrics::counter;
use personhog_coordination::types::ChangelogConfig;
use tracing::info;

use crate::kafka::PersonConsumer;

/// Chooses the subscription. A generation once proven drained is never chosen
/// again, so a slow or failed probe cannot send the writer back to it.
#[derive(Default)]
pub struct Follower {
    drained: HashSet<String>,
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
            self.drained.insert(generation.topic);
        }
        Ok(changelog.topic.clone())
    }

    /// One pass of the follow loop. The draining flag follows the config before the
    /// subscription is touched, so it holds whether or not the subscription moved.
    pub async fn follow_once<F, Fut>(
        &mut self,
        consumer: &PersonConsumer,
        changelog: &ChangelogConfig,
        drained: F,
    ) -> Result<(), String>
    where
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<bool, String>>,
    {
        let wanted = self.select_topic(changelog, drained).await?;
        consumer.set_draining(wanted != changelog.topic);
        let subscribed = consumer.topic();
        if wanted != subscribed {
            consumer
                .resubscribe(wanted.clone())
                .map_err(|e| format!("re-subscribe to {wanted}: {e}"))?;
            info!(from = %subscribed, to = %wanted, "moved the subscription");
            counter!("personhog_writer_resubscriptions_total").increment(1);
        }
        Ok(())
    }
}
