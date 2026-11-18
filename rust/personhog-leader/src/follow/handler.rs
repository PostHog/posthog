use std::sync::Arc;

use async_trait::async_trait;
use dashmap::DashMap;
use personhog_coordination::changelog::LiveChangelog;
use personhog_coordination::error::Result;
use personhog_coordination::pod::HandoffHandler;
use personhog_coordination::types::ChangelogConfig;

use super::Follower;

/// The handoff handler of a follower. Reads need no exclusivity, so a follower holds
/// nothing during a handoff: the old owner serves until the new one reports warm.
pub struct FollowerHandler {
    follower: Arc<Follower>,
    changelog: LiveChangelog,
    captured: DashMap<u32, ChangelogConfig>,
    /// The config each partition was last built under.
    built: DashMap<u32, ChangelogConfig>,
}

impl FollowerHandler {
    pub fn new(follower: Arc<Follower>, changelog: LiveChangelog) -> Self {
        Self {
            follower,
            changelog,
            captured: DashMap::new(),
            built: DashMap::new(),
        }
    }

    async fn build(&self, partition: u32, config: ChangelogConfig) -> Result<()> {
        // A shrink leaves assignments for partitions the changelog no longer has. There
        // is nothing to follow, and no request is routed to them.
        if partition >= config.partitions {
            self.follower.release(partition);
        } else {
            self.follower.follow(partition, &config).await?;
        }
        self.built.insert(partition, config);
        Ok(())
    }
}

#[async_trait]
impl HandoffHandler for FollowerHandler {
    async fn drain_partition_inflight(&self, _partition: u32) -> Result<()> {
        Ok(())
    }

    async fn capture_changelog(&self, partition: u32, config: &ChangelogConfig) {
        self.changelog.adopt(config);
        self.captured.insert(partition, config.clone());
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        let config = match self.captured.get(&partition) {
            Some(captured) => captured.clone(),
            None => self.changelog.current(),
        };
        self.build(partition, config).await
    }

    /// Rebuild a partition whose reader stopped, or that was built under an older config:
    /// after a partition-count or cluster change its state belongs to the old layout.
    async fn verify_serving(&self, partition: u32) -> Result<bool> {
        let live = self.changelog.current();
        let built_under_live = self
            .built
            .get(&partition)
            .is_some_and(|built| built.epoch >= live.epoch);
        let gone = partition >= live.partitions;
        if built_under_live && (gone || self.follower.is_following(partition)) {
            return Ok(false);
        }
        self.build(partition, live).await?;
        Ok(true)
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.follower.release(partition);
        self.captured.remove(&partition);
        self.built.remove(&partition);
        Ok(())
    }

    async fn resume_partition(&self, _partition: u32) -> Result<()> {
        Ok(())
    }
}
