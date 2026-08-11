//! Output registry — the topic-completeness surface.
//!
//! Binds every fixed routing [`Output`] variant to its configured Kafka topic
//! and provides a startup completeness check ([`OutputRegistry::check_complete`])
//! that refuses to boot when any fixed output resolves to an empty topic. This
//! is the single place the output→topic wiring lives, so adding an output is a
//! one-place change: the `topic_for` and `is_required` matches are
//! compiler-forced exhaustive, a test pins `REGISTERED` to the required set,
//! and `check_complete` catches an unwired output at boot rather than at
//! first produce.
//!
//! Two outputs sit outside the completeness check: `Custom` topics are
//! admin-supplied inline on the event's metadata (they carry their own topic),
//! and `AiOverflow` is the opt-in overflow valve — unset means routing never
//! selects it.

use crate::config::KafkaConfig;

/// Which configured output a routing decision selects, named **pipeline +
/// lane** — the vocabulary the refactor converges on (typed per-pipeline
/// lanes; see the plan doc). The sink resolves each output to a concrete
/// topic string against the [`OutputRegistry`]; distinct outputs may share a
/// topic (analytics main and session-replay main both resolve the
/// deployment's main topic today). Mirrors v1's `Destination` split — the
/// convergence target when the v1 stack folds onto this registry (see the
/// plan doc).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Output {
    AnalyticsMain,
    AnalyticsOverflow,
    AnalyticsHistorical,
    ClientWarningsMain,
    HeatmapsMain,
    SessionReplayMain,
    SessionReplayOverflow,
    /// Every pipeline's dlq lane; one shared output until the typed-address
    /// step gives each pipeline its own dlq row.
    Dlq,
    ErrorTrackingMain,
    /// The AI pipeline's main lane — the dedicated `$ai_*` topic
    /// (`CAPTURE_ANALYTICS_AI_EVENTS_TOPIC`).
    AiMain,
    /// The AI pipeline's overflow lane; only routed to when the AI overflow
    /// valve (`CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC`) is armed.
    AiOverflow,
    /// Admin-configured custom topic copied from `redirect_to_topic`. Resolved
    /// inline by the sink; never registered (it carries its own topic).
    Custom(String),
}

impl Output {
    /// Every registered always-required output. `check_complete` walks this so
    /// a newly added output is caught at boot rather than at first produce.
    const REGISTERED: [Output; 10] = [
        Output::AnalyticsMain,
        Output::AnalyticsOverflow,
        Output::AnalyticsHistorical,
        Output::ClientWarningsMain,
        Output::HeatmapsMain,
        Output::SessionReplayMain,
        Output::SessionReplayOverflow,
        Output::Dlq,
        Output::ErrorTrackingMain,
        Output::AiMain,
    ];

    /// Whether this output participates in the boot completeness check.
    /// Deliberately exhaustive: a new variant cannot compile without
    /// declaring which side it is on, and
    /// `registered_is_exactly_the_required_outputs` pins [`Self::REGISTERED`]
    /// to the `true` arms so declaring `true` without joining the array
    /// fails a test instead of silently skipping the check.
    #[cfg(test)]
    fn is_required(&self) -> bool {
        match self {
            Output::AnalyticsMain
            | Output::AnalyticsOverflow
            | Output::AnalyticsHistorical
            | Output::ClientWarningsMain
            | Output::HeatmapsMain
            | Output::SessionReplayMain
            | Output::SessionReplayOverflow
            | Output::Dlq
            | Output::ErrorTrackingMain
            | Output::AiMain => true,
            // The opt-in AI overflow valve and per-event custom topics sit
            // outside the check.
            Output::AiOverflow | Output::Custom(_) => false,
        }
    }

    /// Stable, low-cardinality label for diagnostics. `Custom` collapses to
    /// "custom" so admin topic names never leak into error messages.
    fn name(&self) -> &'static str {
        match self {
            Output::AnalyticsMain => "analytics-main",
            Output::AnalyticsOverflow => "analytics-overflow",
            Output::AnalyticsHistorical => "analytics-historical",
            Output::ClientWarningsMain => "clientwarnings-main",
            Output::HeatmapsMain => "heatmaps-main",
            Output::SessionReplayMain => "sessionreplay-main",
            Output::SessionReplayOverflow => "sessionreplay-overflow",
            Output::Dlq => "dlq",
            Output::ErrorTrackingMain => "errortracking-main",
            Output::AiMain => "ai-main",
            Output::AiOverflow => "ai-overflow",
            Output::Custom(_) => "custom",
        }
    }
}

/// The one place output→topic wiring lives. Holds the configured topic for every
/// fixed [`Output`] variant. Cheap to clone; the sink holds it behind an `Arc`.
#[derive(Clone, Debug)]
pub struct OutputRegistry {
    pub(crate) main: String,
    pub(crate) overflow: String,
    pub(crate) historical: String,
    pub(crate) client_ingestion_warning: String,
    pub(crate) heatmaps: String,
    pub(crate) replay_overflow: String,
    pub(crate) dlq: String,
    pub(crate) error_tracking: String,
    /// Dedicated topic for `Output::AiMain` (`CAPTURE_ANALYTICS_AI_EVENTS_TOPIC`,
    /// required with a default).
    pub(crate) ai_events: String,
    /// Overflow topic for the AI lane. Unset means the AI overflow valve is
    /// unarmed and routing never selects `Output::AiOverflow`.
    pub(crate) ai_events_overflow: Option<String>,
}

impl OutputRegistry {
    /// Resolve an output to its topic. Fixed outputs read the registered topic;
    /// `Custom` returns its inline, admin-supplied topic.
    pub fn topic_for<'a>(&'a self, output: &'a Output) -> &'a str {
        match output {
            Output::AnalyticsMain | Output::SessionReplayMain => &self.main,
            Output::AnalyticsOverflow => &self.overflow,
            Output::AnalyticsHistorical => &self.historical,
            Output::ClientWarningsMain => &self.client_ingestion_warning,
            Output::HeatmapsMain => &self.heatmaps,
            Output::SessionReplayOverflow => &self.replay_overflow,
            Output::Dlq => &self.dlq,
            Output::ErrorTrackingMain => &self.error_tracking,
            Output::AiMain => &self.ai_events,
            Output::AiOverflow => match self.ai_events_overflow.as_deref() {
                Some(topic) if !topic.is_empty() => topic,
                // Unreachable: routing only selects this output when the
                // valve is armed, i.e. exactly when the topic is set.
                _ => &self.ai_events,
            },
            Output::Custom(topic) => topic,
        }
    }

    /// Whether the AI overflow valve is armed: the AI overflow topic is wired,
    /// so routing may select `Output::AiOverflow`.
    pub fn ai_events_overflow_armed(&self) -> bool {
        self.ai_events_overflow
            .as_deref()
            .is_some_and(|t| !t.is_empty())
    }

    /// Startup completeness check: every registered output must resolve to a
    /// non-empty topic, so a misconfigured or newly-added-but-unwired output
    /// fails fast at boot instead of at first produce. `Custom` is excluded
    /// (it carries its own topic per event), as is the opt-in `AiOverflow`
    /// valve (unset means routing never selects it).
    pub fn check_complete(&self) -> anyhow::Result<()> {
        for output in &Output::REGISTERED {
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
            ai_events: config.capture_analytics_ai_events_topic.clone(),
            ai_events_overflow: config.capture_analytics_ai_events_overflow_topic.clone(),
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
        ai_events: "ai_events".to_string(),
        ai_events_overflow: Some("ai_events_overflow".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(Output::AnalyticsMain, "events_plugin_ingestion")]
    #[case(Output::SessionReplayMain, "events_plugin_ingestion")]
    #[case(Output::AnalyticsOverflow, "events_plugin_ingestion_overflow")]
    #[case(Output::AnalyticsHistorical, "events_plugin_ingestion_historical")]
    #[case(Output::ClientWarningsMain, "client_ingestion_warning")]
    #[case(Output::HeatmapsMain, "heatmaps")]
    #[case(Output::SessionReplayOverflow, "replay_overflow")]
    #[case(Output::Dlq, "events_plugin_ingestion_dlq")]
    #[case(Output::ErrorTrackingMain, "error_tracking_events")]
    #[case(Output::AiMain, "ai_events")]
    #[case(Output::AiOverflow, "ai_events_overflow")]
    fn topic_for_resolves_registered_outputs(#[case] output: Output, #[case] expected: &str) {
        assert_eq!(test_topics().topic_for(&output), expected);
    }

    #[test]
    fn topic_for_custom_returns_inline_topic() {
        let registry = test_topics();
        assert_eq!(
            registry.topic_for(&Output::Custom("admin_topic".to_string())),
            "admin_topic"
        );
    }

    /// An unarmed overflow valve carries no completeness requirement and never
    /// disarms the AI main lane.
    #[test]
    fn unset_ai_overflow_valve_is_unarmed() {
        let mut registry = test_topics();
        registry.ai_events_overflow = None;
        assert!(registry.check_complete().is_ok());
        assert!(!registry.ai_events_overflow_armed());
        assert_eq!(registry.topic_for(&Output::AiMain), "ai_events");
    }

    #[test]
    fn check_complete_accepts_full_registry() {
        assert!(test_topics().check_complete().is_ok());
    }

    /// `REGISTERED` is a hand-maintained array while `is_required` is
    /// compiler-exhaustive; this pins them together. A new variant cannot
    /// compile without an `is_required` arm, and putting it on the wrong
    /// side of `REGISTERED` fails here. The all-variants list below is the
    /// one hand-maintained enumeration left — grow it with the enum.
    #[test]
    fn registered_is_exactly_the_required_outputs() {
        let all = [
            Output::AnalyticsMain,
            Output::AnalyticsOverflow,
            Output::AnalyticsHistorical,
            Output::ClientWarningsMain,
            Output::HeatmapsMain,
            Output::SessionReplayMain,
            Output::SessionReplayOverflow,
            Output::Dlq,
            Output::ErrorTrackingMain,
            Output::AiMain,
            Output::AiOverflow,
            Output::Custom("t".to_string()),
        ];
        for output in &all {
            assert_eq!(
                Output::REGISTERED.contains(output),
                output.is_required(),
                "'{}' must be in REGISTERED exactly when it is required",
                output.name()
            );
        }
    }

    /// Every registered output, blanked one at a time, must fail the check and
    /// the error must name the offending output.
    #[rstest]
    #[case("analytics-main", |r: &mut OutputRegistry| r.main.clear())]
    #[case("analytics-overflow", |r: &mut OutputRegistry| r.overflow.clear())]
    #[case("analytics-historical", |r: &mut OutputRegistry| r.historical.clear())]
    #[case("clientwarnings-main", |r: &mut OutputRegistry| r.client_ingestion_warning.clear())]
    #[case("heatmaps-main", |r: &mut OutputRegistry| r.heatmaps.clear())]
    #[case("sessionreplay-overflow", |r: &mut OutputRegistry| r.replay_overflow.clear())]
    #[case("dlq", |r: &mut OutputRegistry| r.dlq.clear())]
    #[case("errortracking-main", |r: &mut OutputRegistry| r.error_tracking.clear())]
    #[case("ai-main", |r: &mut OutputRegistry| r.ai_events.clear())]
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
