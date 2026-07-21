//! Output registry — the topic-completeness surface.
//!
//! Binds every fixed routing [`Outputs`] variant to its configured Kafka topic
//! and provides a startup completeness check ([`OutputRegistry::check_complete`])
//! that refuses to boot when any fixed output resolves to an empty topic. This is
//! the single place the output→topic wiring lives: it replaces the ad-hoc
//! `KafkaTopicConfig` struct plus the inline `match route.target` that used to
//! resolve topics inside the sink. Adding an output is now a one-place change —
//! the `topic_for` match is compiler-forced exhaustive, and `check_complete`
//! catches an unwired output at boot rather than at first produce (#68719).
//!
//! `Custom` topics are admin-supplied inline on the event's metadata, so they
//! carry their own topic and are resolved by the sink, never registered here.

use crate::config::KafkaConfig;

/// Which configured output a routing decision selects. The sink resolves this to
/// a concrete topic string against the [`OutputRegistry`]. Promoted from Step 2's
/// `RouteTarget`; mirrors v1's `Destination` split (the Step 12 convergence
/// target, when the v1 stack folds onto this registry).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outputs<'a> {
    Main,
    Overflow,
    Historical,
    ClientIngestionWarning,
    Heatmaps,
    ReplayOverflow,
    Dlq,
    ErrorTracking,
    /// Admin-configured custom topic borrowed from `redirect_to_topic`. Resolved
    /// inline by the sink; never registered (it carries its own topic).
    Custom(&'a str),
}

impl Outputs<'_> {
    /// Every registered (non-`Custom`) output. `check_complete` walks this so a
    /// newly added output is caught at boot rather than at first produce.
    const REGISTERED: [Outputs<'static>; 8] = [
        Outputs::Main,
        Outputs::Overflow,
        Outputs::Historical,
        Outputs::ClientIngestionWarning,
        Outputs::Heatmaps,
        Outputs::ReplayOverflow,
        Outputs::Dlq,
        Outputs::ErrorTracking,
    ];

    /// Stable, low-cardinality label for diagnostics. `Custom` collapses to
    /// "custom" so admin topic names never leak into error messages.
    fn name(&self) -> &'static str {
        match self {
            Outputs::Main => "main",
            Outputs::Overflow => "overflow",
            Outputs::Historical => "historical",
            Outputs::ClientIngestionWarning => "client_ingestion_warning",
            Outputs::Heatmaps => "heatmaps",
            Outputs::ReplayOverflow => "replay_overflow",
            Outputs::Dlq => "dlq",
            Outputs::ErrorTracking => "error_tracking",
            Outputs::Custom(_) => "custom",
        }
    }
}

/// The one place output→topic wiring lives. Holds the configured topic for every
/// fixed [`Outputs`] variant. Cheap to clone; the sink holds it behind an `Arc`.
#[derive(Clone, Debug)]
pub struct OutputRegistry {
    main: String,
    overflow: String,
    historical: String,
    client_ingestion_warning: String,
    heatmaps: String,
    replay_overflow: String,
    dlq: String,
    error_tracking: String,
}

impl OutputRegistry {
    /// Resolve an output to its topic. Fixed outputs read the registered topic;
    /// `Custom` returns its inline, admin-supplied topic.
    pub fn topic_for<'a>(&'a self, output: &Outputs<'a>) -> &'a str {
        match output {
            Outputs::Main => &self.main,
            Outputs::Overflow => &self.overflow,
            Outputs::Historical => &self.historical,
            Outputs::ClientIngestionWarning => &self.client_ingestion_warning,
            Outputs::Heatmaps => &self.heatmaps,
            Outputs::ReplayOverflow => &self.replay_overflow,
            Outputs::Dlq => &self.dlq,
            Outputs::ErrorTracking => &self.error_tracking,
            Outputs::Custom(topic) => topic,
        }
    }

    /// Startup completeness check: every registered output must resolve to a
    /// non-empty topic. Introduced by Step 3 (#68719) — a misconfigured or
    /// newly-added-but-unwired output now fails fast at boot instead of at first
    /// produce. `Custom` is excluded (it carries its own topic per event).
    pub fn check_complete(&self) -> anyhow::Result<()> {
        for output in &Outputs::REGISTERED {
            anyhow::ensure!(
                !self.topic_for(output).is_empty(),
                "output '{}' resolves to an empty Kafka topic; every non-custom \
                 output must be bound to a configured, non-empty topic",
                output.name(),
            );
        }
        Ok(())
    }
}

impl From<&KafkaConfig> for OutputRegistry {
    fn from(config: &KafkaConfig) -> Self {
        Self {
            main: config.kafka_topic.clone(),
            overflow: config.kafka_overflow_topic.clone(),
            historical: config.kafka_historical_topic.clone(),
            client_ingestion_warning: config.kafka_client_ingestion_warning_topic.clone(),
            heatmaps: config.kafka_heatmaps_topic.clone(),
            replay_overflow: config.kafka_replay_overflow_topic.clone(),
            dlq: config.kafka_dlq_topic.clone(),
            error_tracking: config.kafka_error_tracking_topic.clone(),
        }
    }
}

/// Shared `OutputRegistry` fixture for tests across the capture crate. Used by
/// sink-side routing tests and pipeline-to-sink E2E tests so every test site
/// asserts against the same canonical topic names.
#[cfg(test)]
pub(crate) fn test_topics() -> OutputRegistry {
    OutputRegistry {
        main: "events_plugin_ingestion".to_string(),
        overflow: "events_plugin_ingestion_overflow".to_string(),
        historical: "events_plugin_ingestion_historical".to_string(),
        client_ingestion_warning: "client_ingestion_warning".to_string(),
        heatmaps: "heatmaps".to_string(),
        replay_overflow: "replay_overflow".to_string(),
        dlq: "events_plugin_ingestion_dlq".to_string(),
        error_tracking: "error_tracking_events".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(Outputs::Main, "events_plugin_ingestion")]
    #[case(Outputs::Overflow, "events_plugin_ingestion_overflow")]
    #[case(Outputs::Historical, "events_plugin_ingestion_historical")]
    #[case(Outputs::ClientIngestionWarning, "client_ingestion_warning")]
    #[case(Outputs::Heatmaps, "heatmaps")]
    #[case(Outputs::ReplayOverflow, "replay_overflow")]
    #[case(Outputs::Dlq, "events_plugin_ingestion_dlq")]
    #[case(Outputs::ErrorTracking, "error_tracking_events")]
    fn topic_for_resolves_registered_outputs(
        #[case] output: Outputs<'static>,
        #[case] expected: &str,
    ) {
        assert_eq!(test_topics().topic_for(&output), expected);
    }

    #[test]
    fn topic_for_custom_returns_inline_topic() {
        let registry = test_topics();
        assert_eq!(
            registry.topic_for(&Outputs::Custom("admin_topic")),
            "admin_topic"
        );
    }

    #[test]
    fn check_complete_accepts_full_registry() {
        assert!(test_topics().check_complete().is_ok());
    }

    /// Every registered output, blanked one at a time, must fail the check and
    /// the error must name the offending output — the #68719 completeness seam.
    #[rstest]
    #[case("main", |r: &mut OutputRegistry| r.main.clear())]
    #[case("overflow", |r: &mut OutputRegistry| r.overflow.clear())]
    #[case("historical", |r: &mut OutputRegistry| r.historical.clear())]
    #[case("client_ingestion_warning", |r: &mut OutputRegistry| r.client_ingestion_warning.clear())]
    #[case("heatmaps", |r: &mut OutputRegistry| r.heatmaps.clear())]
    #[case("replay_overflow", |r: &mut OutputRegistry| r.replay_overflow.clear())]
    #[case("dlq", |r: &mut OutputRegistry| r.dlq.clear())]
    #[case("error_tracking", |r: &mut OutputRegistry| r.error_tracking.clear())]
    fn check_complete_rejects_empty_topic(
        #[case] output_name: &str,
        #[case] blank: fn(&mut OutputRegistry),
    ) {
        let mut registry = test_topics();
        blank(&mut registry);
        let err = registry
            .check_complete()
            .expect_err("blank topic must fail the completeness check");
        let msg = format!("{err:#}");
        assert!(
            msg.contains(output_name),
            "error should name the missing output '{output_name}': {msg}"
        );
    }
}
