use std::sync::Arc;
use std::time::Duration;

use crate::config::{Config, TeamFilterMode, TeamList};
use crate::producer::AggregatedProducer;

/// Shared state handed to every worker loop.
pub struct AppContext {
    pub producer: Arc<AggregatedProducer>,
    pub filter_mode: TeamFilterMode,
    pub filtered_teams: TeamList,
    pub flush_interval: Duration,
    pub max_entries_per_partition: usize,
    pub producer_flush_timeout: Duration,
}

impl AppContext {
    pub fn new(config: &Config, producer: AggregatedProducer) -> Self {
        Self {
            producer: Arc::new(producer),
            filter_mode: config.filter_mode,
            filtered_teams: config.filtered_teams.clone(),
            flush_interval: Duration::from_secs(config.flush_interval_secs),
            max_entries_per_partition: config.max_entries_per_partition,
            producer_flush_timeout: Duration::from_secs(30),
        }
    }

    pub fn should_process(&self, team_id: i64) -> bool {
        self.filter_mode
            .should_process(&self.filtered_teams.teams, team_id)
    }
}
