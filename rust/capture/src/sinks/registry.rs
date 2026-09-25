//! Destination registry — the topic-completeness surface.
//!
//! Binds every fixed routing [`Destination`] variant to its configured output,
//! a Kafka topic and the named producer that carries it, and provides a
//! startup completeness check ([`OutputTable::check_complete`])
//! that refuses to boot when any fixed output resolves to an empty topic. This
//! is the single place the output→topic wiring lives, so adding an output is a
//! one-place change: the `target_for` and `is_required` matches are
//! compiler-forced exhaustive, a test pins `REGISTERED` to the required set,
//! and `check_complete` catches an unwired output at boot rather than at
//! first produce.
//!
//! Two outputs sit outside the completeness check: `Custom` topics are
//! admin-supplied inline on the event's metadata (they carry their own topic),
//! and `AiOverflow` is the opt-in overflow valve — unset means routing never
//! selects it.

use std::sync::Arc;

use crate::config::OutputsConfig;
use crate::producers::ProducerName;

/// Which configured output a routing decision selects, named **pipeline +
/// lane** — the vocabulary the refactor converges on (typed per-pipeline
/// lanes; see the plan doc). The sink resolves each output to a concrete
/// topic and producer against the [`OutputTable`]; distinct outputs may
/// share a topic. Mirrors v1's `Destination` split — the
/// convergence target when the v1 stack folds onto this registry (see the
/// plan doc).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Destination {
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
    /// (`CAPTURE_OUTPUT_AI_MAIN_TOPIC`).
    AiMain,
    /// The AI pipeline's overflow lane; only routed to when the AI overflow
    /// valve (`CAPTURE_OUTPUT_AI_OVERFLOW_TOPIC`) is armed.
    AiOverflow,
    /// Admin-configured custom topic copied from `redirect_to_topic`. Carries
    /// its own topic and publishes through the custom producer; never
    /// registered.
    Custom(String),
}

impl Destination {
    /// Every registered always-required output. `check_complete` walks this so
    /// a newly added output is caught at boot rather than at first produce.
    const REGISTERED: [Destination; 10] = [
        Destination::AnalyticsMain,
        Destination::AnalyticsOverflow,
        Destination::AnalyticsHistorical,
        Destination::ClientWarningsMain,
        Destination::HeatmapsMain,
        Destination::SessionReplayMain,
        Destination::SessionReplayOverflow,
        Destination::Dlq,
        Destination::ErrorTrackingMain,
        Destination::AiMain,
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
            Destination::AnalyticsMain
            | Destination::AnalyticsOverflow
            | Destination::AnalyticsHistorical
            | Destination::ClientWarningsMain
            | Destination::HeatmapsMain
            | Destination::SessionReplayMain
            | Destination::SessionReplayOverflow
            | Destination::Dlq
            | Destination::ErrorTrackingMain
            | Destination::AiMain => true,
            // The opt-in AI overflow valve and per-event custom topics sit
            // outside the check.
            Destination::AiOverflow | Destination::Custom(_) => false,
        }
    }

    /// Stable, low-cardinality label for diagnostics. `Custom` collapses to
    /// "custom" so admin topic names never leak into error messages.
    fn name(&self) -> &'static str {
        match self {
            Destination::AnalyticsMain => "analytics-main",
            Destination::AnalyticsOverflow => "analytics-overflow",
            Destination::AnalyticsHistorical => "analytics-historical",
            Destination::ClientWarningsMain => "clientwarnings-main",
            Destination::HeatmapsMain => "heatmaps-main",
            Destination::SessionReplayMain => "sessionreplay-main",
            Destination::SessionReplayOverflow => "sessionreplay-overflow",
            Destination::Dlq => "dlq",
            Destination::ErrorTrackingMain => "errortracking-main",
            Destination::AiMain => "ai-main",
            Destination::AiOverflow => "ai-overflow",
            Destination::Custom(_) => "custom",
        }
    }
}

#[derive(Clone, Debug)]
pub struct OutputTarget {
    // `Arc<str>` so the per-record metric label and lookup never allocate.
    pub(crate) topic: Arc<str>,
    pub(crate) producer: ProducerName,
}

/// The one place output wiring lives. Holds the configured target for every
/// fixed [`Destination`] variant. Cheap to clone; the sink holds it behind an `Arc`.
#[derive(Clone, Debug)]
pub struct OutputTable {
    pub(crate) analytics_main: OutputTarget,
    pub(crate) analytics_overflow: OutputTarget,
    pub(crate) analytics_historical: OutputTarget,
    pub(crate) session_replay_main: OutputTarget,
    pub(crate) session_replay_overflow: OutputTarget,
    pub(crate) client_warnings: OutputTarget,
    pub(crate) heatmaps: OutputTarget,
    pub(crate) dlq: OutputTarget,
    pub(crate) error_tracking: OutputTarget,
    pub(crate) ai_main: OutputTarget,
    /// Unset means the AI overflow valve is unarmed and routing never
    /// selects `Destination::AiOverflow`.
    pub(crate) ai_overflow: Option<OutputTarget>,
    pub(crate) custom_producer: ProducerName,
}

impl OutputTable {
    /// `Custom` has no target: it carries its own topic.
    fn target_for(&self, output: &Destination) -> Option<&OutputTarget> {
        match output {
            Destination::AnalyticsMain => Some(&self.analytics_main),
            Destination::AnalyticsOverflow => Some(&self.analytics_overflow),
            Destination::AnalyticsHistorical => Some(&self.analytics_historical),
            Destination::ClientWarningsMain => Some(&self.client_warnings),
            Destination::HeatmapsMain => Some(&self.heatmaps),
            Destination::SessionReplayMain => Some(&self.session_replay_main),
            Destination::SessionReplayOverflow => Some(&self.session_replay_overflow),
            Destination::Dlq => Some(&self.dlq),
            Destination::ErrorTrackingMain => Some(&self.error_tracking),
            Destination::AiMain => Some(&self.ai_main),
            Destination::AiOverflow => match &self.ai_overflow {
                Some(target) if !target.topic.is_empty() => Some(target),
                // Unreachable: routing only selects this output when the
                // valve is armed, i.e. exactly when the topic is set.
                _ => Some(&self.ai_main),
            },
            Destination::Custom(_) => None,
        }
    }

    /// Resolve an output to its topic. Fixed outputs read the registered topic;
    /// `Custom` returns its inline, admin-supplied topic.
    pub fn topic_for<'a>(&'a self, output: &'a Destination) -> &'a str {
        match (output, self.target_for(output)) {
            (Destination::Custom(topic), _) => topic,
            (_, Some(target)) => &target.topic,
            (_, None) => unreachable!("every fixed output has a target"),
        }
    }

    /// Only a `Custom` topic allocates.
    pub(crate) fn resolve(&self, output: &Destination) -> (Arc<str>, ProducerName) {
        match (output, self.target_for(output)) {
            (_, Some(target)) => (Arc::clone(&target.topic), target.producer),
            (Destination::Custom(topic), None) => (Arc::from(topic.as_str()), self.custom_producer),
            (_, None) => unreachable!("every fixed output has a target"),
        }
    }

    /// Whether the AI overflow valve is armed: the AI overflow topic is wired,
    /// so routing may select `Destination::AiOverflow`.
    pub fn ai_events_overflow_armed(&self) -> bool {
        self.ai_overflow
            .as_ref()
            .is_some_and(|target| !target.topic.is_empty())
    }

    /// Startup completeness check: every registered output must resolve to a
    /// non-empty topic, so a misconfigured or newly-added-but-unwired output
    /// fails fast at boot instead of at first produce. `Custom` is excluded
    /// (it carries its own topic per event), as is the opt-in `AiOverflow`
    /// valve (unset means routing never selects it).
    pub fn check_complete(&self) -> anyhow::Result<()> {
        for output in &Destination::REGISTERED {
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

impl From<&OutputsConfig> for OutputTable {
    fn from(config: &OutputsConfig) -> Self {
        let target = |topic: &String, producer: ProducerName| OutputTarget {
            topic: Arc::from(topic.as_str()),
            producer,
        };
        Self {
            analytics_main: target(&config.analytics_main_topic, config.analytics_main_producer),
            analytics_overflow: target(
                &config.analytics_overflow_topic,
                config.analytics_overflow_producer,
            ),
            analytics_historical: target(
                &config.analytics_historical_topic,
                config.analytics_historical_producer,
            ),
            session_replay_main: target(
                &config.session_replay_main_topic,
                config.session_replay_main_producer,
            ),
            session_replay_overflow: target(
                &config.session_replay_overflow_topic,
                config.session_replay_overflow_producer,
            ),
            client_warnings: target(
                &config.client_warnings_topic,
                config.client_warnings_producer,
            ),
            heatmaps: target(&config.heatmaps_topic, config.heatmaps_producer),
            dlq: target(&config.dlq_topic, config.dlq_producer),
            error_tracking: target(&config.error_tracking_topic, config.error_tracking_producer),
            ai_main: target(&config.ai_main_topic, config.ai_main_producer),
            ai_overflow: config
                .ai_overflow_topic
                .as_ref()
                .map(|topic| target(topic, config.ai_overflow_producer)),
            custom_producer: config.custom_producer,
        }
    }
}

/// Shared `OutputTable` fixture for tests across the capture crate. Used by
/// sink-side routing tests and pipeline-to-sink E2E tests so every test site
/// asserts against the same canonical topic names.
#[cfg(test)]
pub(crate) fn test_outputs() -> OutputTable {
    let target = |topic: &str| OutputTarget {
        topic: Arc::from(topic),
        producer: ProducerName::Ingestion,
    };
    OutputTable {
        analytics_main: target("events_plugin_ingestion"),
        analytics_overflow: target("events_plugin_ingestion_overflow"),
        analytics_historical: target("events_plugin_ingestion_historical"),
        session_replay_main: target("events_plugin_ingestion"),
        session_replay_overflow: target("replay_overflow"),
        client_warnings: target("client_ingestion_warning"),
        heatmaps: target("heatmaps"),
        dlq: target("events_plugin_ingestion_dlq"),
        error_tracking: target("error_tracking_events"),
        ai_main: target("ai_events"),
        ai_overflow: Some(target("ai_events_overflow")),
        custom_producer: ProducerName::Ingestion,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(Destination::AnalyticsMain, "events_plugin_ingestion")]
    #[case(Destination::SessionReplayMain, "events_plugin_ingestion")]
    #[case(Destination::AnalyticsOverflow, "events_plugin_ingestion_overflow")]
    #[case(Destination::AnalyticsHistorical, "events_plugin_ingestion_historical")]
    #[case(Destination::ClientWarningsMain, "client_ingestion_warning")]
    #[case(Destination::HeatmapsMain, "heatmaps")]
    #[case(Destination::SessionReplayOverflow, "replay_overflow")]
    #[case(Destination::Dlq, "events_plugin_ingestion_dlq")]
    #[case(Destination::ErrorTrackingMain, "error_tracking_events")]
    #[case(Destination::AiMain, "ai_events")]
    #[case(Destination::AiOverflow, "ai_events_overflow")]
    fn topic_for_resolves_registered_outputs(#[case] output: Destination, #[case] expected: &str) {
        assert_eq!(test_outputs().topic_for(&output), expected);
    }

    #[test]
    fn topic_for_custom_returns_inline_topic() {
        let registry = test_outputs();
        assert_eq!(
            registry.topic_for(&Destination::Custom("admin_topic".to_string())),
            "admin_topic"
        );
    }

    /// An unarmed overflow valve carries no completeness requirement and never
    /// disarms the AI main lane.
    #[test]
    fn unset_ai_overflow_valve_is_unarmed() {
        let mut registry = test_outputs();
        registry.ai_overflow = None;
        assert!(registry.check_complete().is_ok());
        assert!(!registry.ai_events_overflow_armed());
        assert_eq!(registry.topic_for(&Destination::AiMain), "ai_events");
    }

    #[test]
    fn session_replay_main_does_not_share_analytics_main() {
        let mut registry = test_outputs();
        registry.session_replay_main.topic = Arc::from("replay_main");
        assert_eq!(
            registry.topic_for(&Destination::SessionReplayMain),
            "replay_main"
        );
        assert_eq!(
            registry.topic_for(&Destination::AnalyticsMain),
            "events_plugin_ingestion"
        );
    }

    #[test]
    fn custom_topics_publish_through_the_custom_producer() {
        let registry = test_outputs();
        let (topic, producer) = registry.resolve(&Destination::Custom("admin_topic".to_string()));
        assert_eq!(&*topic, "admin_topic");
        assert_eq!(producer, registry.custom_producer);
    }

    #[test]
    fn check_complete_accepts_full_registry() {
        assert!(test_outputs().check_complete().is_ok());
    }

    /// `REGISTERED` is a hand-maintained array while `is_required` is
    /// compiler-exhaustive; this pins them together. A new variant cannot
    /// compile without an `is_required` arm, and putting it on the wrong
    /// side of `REGISTERED` fails here. The all-variants list below is the
    /// one hand-maintained enumeration left — grow it with the enum.
    #[test]
    fn registered_is_exactly_the_required_outputs() {
        let all = [
            Destination::AnalyticsMain,
            Destination::AnalyticsOverflow,
            Destination::AnalyticsHistorical,
            Destination::ClientWarningsMain,
            Destination::HeatmapsMain,
            Destination::SessionReplayMain,
            Destination::SessionReplayOverflow,
            Destination::Dlq,
            Destination::ErrorTrackingMain,
            Destination::AiMain,
            Destination::AiOverflow,
            Destination::Custom("t".to_string()),
        ];
        for output in &all {
            assert_eq!(
                Destination::REGISTERED.contains(output),
                output.is_required(),
                "'{}' must be in REGISTERED exactly when it is required",
                output.name()
            );
        }
    }

    /// Every registered output, blanked one at a time, must fail the check and
    /// the error must name the offending output.
    #[rstest]
    #[case("analytics-main", |r: &mut OutputTable| r.analytics_main.topic = Arc::from(""))]
    #[case("analytics-overflow", |r: &mut OutputTable| r.analytics_overflow.topic = Arc::from(""))]
    #[case("analytics-historical", |r: &mut OutputTable| r.analytics_historical.topic = Arc::from(""))]
    #[case("clientwarnings-main", |r: &mut OutputTable| r.client_warnings.topic = Arc::from(""))]
    #[case("heatmaps-main", |r: &mut OutputTable| r.heatmaps.topic = Arc::from(""))]
    #[case("sessionreplay-main", |r: &mut OutputTable| r.session_replay_main.topic = Arc::from(""))]
    #[case("sessionreplay-overflow", |r: &mut OutputTable| r.session_replay_overflow.topic = Arc::from(""))]
    #[case("dlq", |r: &mut OutputTable| r.dlq.topic = Arc::from(""))]
    #[case("errortracking-main", |r: &mut OutputTable| r.error_tracking.topic = Arc::from(""))]
    #[case("ai-main", |r: &mut OutputTable| r.ai_main.topic = Arc::from(""))]
    fn check_complete_rejects_empty_topic(
        #[case] output_name: &str,
        #[case] blank: fn(&mut OutputTable),
    ) {
        let mut registry = test_outputs();
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
