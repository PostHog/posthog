//! Binds every fixed routing [`Destination`] to its output: a Kafka topic and
//! the named producer that carries it.

use std::sync::Arc;
use std::time::Duration;

use futures::future::join_all;

use crate::config::OutputsConfig;
use crate::pipeline::{Address, AiLane, AnalyticsLane, BasicLane, PipelineLane, SessionReplayLane};
use crate::producers::ProducerName;
use crate::sinks::producer::KafkaProducer;

/// Which configured output a routing decision selects, named by pipeline and
/// lane. Distinct outputs may share a topic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Destination {
    AnalyticsMain,
    AnalyticsOverflow,
    AnalyticsHistorical,
    ClientWarningsMain,
    HeatmapsMain,
    SessionReplayMain,
    SessionReplayOverflow,
    /// Every pipeline's dlq lane, one shared output.
    Dlq,
    ErrorTrackingMain,
    AiMain,
    AiOverflow,
    /// Admin-configured topic copied from `redirect_to_topic`.
    Custom(String),
}

impl Destination {
    /// Every registered always-required output. `check_complete` walks this so
    /// a newly added output is caught at boot rather than at first produce.
    const REGISTERED: [Destination; 11] = [
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
    ];

    pub(crate) fn for_lane(lane: PipelineLane) -> Destination {
        match lane {
            PipelineLane::Analytics(AnalyticsLane::Main) => Destination::AnalyticsMain,
            PipelineLane::Analytics(AnalyticsLane::Overflow) => Destination::AnalyticsOverflow,
            PipelineLane::Analytics(AnalyticsLane::Historical) => Destination::AnalyticsHistorical,
            PipelineLane::Ai(AiLane::Main) => Destination::AiMain,
            PipelineLane::Ai(AiLane::Overflow) => Destination::AiOverflow,
            PipelineLane::Warnings(BasicLane::Main) => Destination::ClientWarningsMain,
            PipelineLane::Heatmaps(BasicLane::Main) => Destination::HeatmapsMain,
            PipelineLane::ErrorTracking(BasicLane::Main) => Destination::ErrorTrackingMain,
            PipelineLane::Replay(SessionReplayLane::Main) => Destination::SessionReplayMain,
            PipelineLane::Replay(SessionReplayLane::Overflow) => Destination::SessionReplayOverflow,
        }
    }

    pub(crate) fn for_address(address: Address) -> Destination {
        match address {
            Address::Lane(lane) => Self::for_lane(lane),
            Address::Dlq => Destination::Dlq,
            Address::Custom(topic) => Destination::Custom(topic),
        }
    }

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
            | Destination::AiMain
            | Destination::AiOverflow => true,
            // A custom redirect carries its own topic per event.
            Destination::Custom(_) => false,
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

/// `R` is how the target names its producer: a [`ProducerName`] in config,
/// the producer handle once setup resolves it.
#[derive(Clone, Debug)]
pub struct OutputTarget<R = ProducerName> {
    /// The `<OUTPUT>` in its `CAPTURE_OUTPUT_<OUTPUT>_*` variables.
    pub(crate) name: &'static str,
    // `Arc<str>` so the per-record lookup, metric labels and produce record never allocate.
    pub(crate) topic: Arc<str>,
    pub(crate) producer: R,
}

#[derive(Clone, Debug)]
pub struct OutputTable<R = ProducerName> {
    pub(crate) analytics_main: OutputTarget<R>,
    pub(crate) analytics_overflow: OutputTarget<R>,
    pub(crate) analytics_historical: OutputTarget<R>,
    pub(crate) session_replay_main: OutputTarget<R>,
    pub(crate) session_replay_overflow: OutputTarget<R>,
    pub(crate) client_warnings: OutputTarget<R>,
    pub(crate) heatmaps: OutputTarget<R>,
    pub(crate) dlq: OutputTarget<R>,
    pub(crate) error_tracking: OutputTarget<R>,
    pub(crate) ai_main: OutputTarget<R>,
    pub(crate) ai_overflow: OutputTarget<R>,
    pub(crate) has_ai_overflow_lane: bool,
    pub(crate) custom_producer: R,
}

impl<R> OutputTable<R> {
    fn target_for(&self, output: &Destination) -> Option<&OutputTarget<R>> {
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
            Destination::AiOverflow => Some(&self.ai_overflow),
            Destination::Custom(_) => None,
        }
    }

    pub fn topic_for<'a>(&'a self, output: &'a Destination) -> &'a str {
        match (output, self.target_for(output)) {
            (Destination::Custom(topic), _) => topic,
            (_, Some(target)) => &target.topic,
            (_, None) => unreachable!("every fixed output has a target"),
        }
    }

    pub(crate) fn resolve(&self, output: &Destination) -> (Arc<str>, &R) {
        match (output, self.target_for(output)) {
            (_, Some(target)) => (Arc::clone(&target.topic), &target.producer),
            (Destination::Custom(topic), None) => {
                (Arc::from(topic.as_str()), &self.custom_producer)
            }
            (_, None) => unreachable!("every fixed output has a target"),
        }
    }

    pub fn map_producers<T>(&self, mut f: impl FnMut(&R) -> T) -> OutputTable<T> {
        let custom_producer = f(&self.custom_producer);
        self.map_targets(
            |t| OutputTarget {
                name: t.name,
                topic: Arc::clone(&t.topic),
                producer: f(&t.producer),
            },
            custom_producer,
        )
    }

    pub(crate) fn map_targets<T>(
        &self,
        mut target: impl FnMut(&OutputTarget<R>) -> OutputTarget<T>,
        custom_producer: T,
    ) -> OutputTable<T> {
        OutputTable {
            analytics_main: target(&self.analytics_main),
            analytics_overflow: target(&self.analytics_overflow),
            analytics_historical: target(&self.analytics_historical),
            session_replay_main: target(&self.session_replay_main),
            session_replay_overflow: target(&self.session_replay_overflow),
            client_warnings: target(&self.client_warnings),
            heatmaps: target(&self.heatmaps),
            dlq: target(&self.dlq),
            error_tracking: target(&self.error_tracking),
            ai_main: target(&self.ai_main),
            ai_overflow: target(&self.ai_overflow),
            has_ai_overflow_lane: self.has_ai_overflow_lane,
            custom_producer,
        }
    }

    pub fn has_ai_overflow_lane(&self) -> bool {
        self.has_ai_overflow_lane
    }

    /// The outputs a capture-analytics pod routes to: all but session replay.
    /// Step 14's per-mode registries replace this hand-written list.
    pub(crate) fn analytics_family_targets(&self) -> [&OutputTarget<R>; 9] {
        [
            &self.analytics_main,
            &self.analytics_overflow,
            &self.analytics_historical,
            &self.heatmaps,
            &self.client_warnings,
            &self.error_tracking,
            &self.dlq,
            &self.ai_main,
            &self.ai_overflow,
        ]
    }

    pub(crate) fn producers(&self) -> Vec<R>
    where
        R: Clone,
    {
        let mut producers = Vec::new();
        self.map_producers(|producer| producers.push(producer.clone()));
        producers
    }

    /// Every registered output must resolve to a non-empty topic. `Custom` is
    /// excluded because it carries its own topic per event.
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

#[derive(Debug, Clone)]
pub struct TopicCheckFailure {
    pub output: &'static str,
    pub topic: Arc<str>,
    pub error: String,
}

impl<P: KafkaProducer + 'static> OutputTable<Arc<P>> {
    pub async fn check_analytics_family_topics(&self, timeout: Duration) -> Vec<TopicCheckFailure> {
        let checks = self
            .analytics_family_targets()
            .into_iter()
            .filter(|target| !target.topic.is_empty())
            .map(|target| {
                let output = target.name;
                let producer = Arc::clone(&target.producer);
                let topic = Arc::clone(&target.topic);
                async move {
                    let check_topic = Arc::clone(&topic);
                    let result = tokio::task::spawn_blocking(move || {
                        producer.check_topic_exists(&check_topic, timeout)
                    })
                    .await;
                    let error = match result {
                        Ok(Ok(())) => return None,
                        Ok(Err(e)) => format!("{e:#}"),
                        Err(e) => format!("topic check task failed: {e}"),
                    };
                    Some(TopicCheckFailure {
                        output,
                        topic,
                        error,
                    })
                }
            });
        join_all(checks).await.into_iter().flatten().collect()
    }
}

impl OutputTable {
    pub fn new(config: &OutputsConfig, has_ai_overflow_lane: bool) -> Self {
        let target = |name, topic: &String, producer| OutputTarget {
            name,
            topic: Arc::from(topic.as_str()),
            producer,
        };
        Self {
            analytics_main: target(
                "ANALYTICS_MAIN",
                &config.analytics_main_topic,
                config.analytics_main_producer,
            ),
            analytics_overflow: target(
                "ANALYTICS_OVERFLOW",
                &config.analytics_overflow_topic,
                config.analytics_overflow_producer,
            ),
            analytics_historical: target(
                "ANALYTICS_HISTORICAL",
                &config.analytics_historical_topic,
                config.analytics_historical_producer,
            ),
            session_replay_main: target(
                "SESSION_REPLAY_MAIN",
                &config.session_replay_main_topic,
                config.session_replay_main_producer,
            ),
            session_replay_overflow: target(
                "SESSION_REPLAY_OVERFLOW",
                &config.session_replay_overflow_topic,
                config.session_replay_overflow_producer,
            ),
            client_warnings: target(
                "CLIENT_WARNINGS",
                &config.client_warnings_topic,
                config.client_warnings_producer,
            ),
            heatmaps: target("HEATMAPS", &config.heatmaps_topic, config.heatmaps_producer),
            dlq: target("DLQ", &config.dlq_topic, config.dlq_producer),
            error_tracking: target(
                "ERROR_TRACKING",
                &config.error_tracking_topic,
                config.error_tracking_producer,
            ),
            ai_main: target("AI_MAIN", &config.ai_main_topic, config.ai_main_producer),
            ai_overflow: target(
                "AI_OVERFLOW",
                &config.ai_overflow_topic,
                config.ai_overflow_producer,
            ),
            has_ai_overflow_lane,
            custom_producer: config.custom_producer,
        }
    }
}

#[cfg(test)]
pub(crate) fn test_outputs() -> OutputTable {
    let target = |name, topic: &str| OutputTarget {
        name,
        topic: Arc::from(topic),
        producer: ProducerName::Ingestion,
    };
    OutputTable {
        analytics_main: target("ANALYTICS_MAIN", "events_plugin_ingestion"),
        analytics_overflow: target("ANALYTICS_OVERFLOW", "events_plugin_ingestion_overflow"),
        analytics_historical: target("ANALYTICS_HISTORICAL", "events_plugin_ingestion_historical"),
        session_replay_main: target("SESSION_REPLAY_MAIN", "events_plugin_ingestion"),
        session_replay_overflow: target("SESSION_REPLAY_OVERFLOW", "replay_overflow"),
        client_warnings: target("CLIENT_WARNINGS", "client_ingestion_warning"),
        heatmaps: target("HEATMAPS", "heatmaps"),
        dlq: target("DLQ", "events_plugin_ingestion_dlq"),
        error_tracking: target("ERROR_TRACKING", "error_tracking_events"),
        ai_main: target("AI_MAIN", "ai_events"),
        ai_overflow: target("AI_OVERFLOW", "ai_events_overflow"),
        has_ai_overflow_lane: true,
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
    fn each_output_resolves_to_its_own_producer() {
        let mut next = 0;
        let table = test_outputs().map_producers(|_| {
            next += 1;
            next
        });
        let custom = Destination::Custom("admin_topic".to_string());
        let (topic, _) = table.resolve(&custom);
        assert_eq!(&*topic, "admin_topic");

        let producers: std::collections::HashSet<i32> = Destination::REGISTERED
            .iter()
            .chain([&custom])
            .map(|output| *table.resolve(output).1)
            .collect();
        assert_eq!(producers.len(), Destination::REGISTERED.len() + 1);
    }

    #[tokio::test]
    async fn analytics_family_topic_check_names_each_failing_output() {
        use crate::sinks::producer::MockKafkaProducer;
        let producer = Arc::new(MockKafkaProducer::new().with_missing_topics([
            "heatmaps",
            "ai_events",
            "replay_overflow",
        ]));
        let mut table = test_outputs().map_producers(|_| Arc::clone(&producer));
        table.dlq.topic = Arc::from("");

        let mut failed: Vec<&str> = table
            .check_analytics_family_topics(Duration::from_secs(1))
            .await
            .into_iter()
            .map(|failure| failure.output)
            .collect();
        failed.sort();

        assert_eq!(failed, vec!["AI_MAIN", "HEATMAPS"]);
    }

    #[test]
    fn check_complete_accepts_full_registry() {
        assert!(test_outputs().check_complete().is_ok());
    }

    /// The all-variants list below is hand-maintained: grow it with the enum.
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
    #[case("ai-overflow", |r: &mut OutputTable| r.ai_overflow.topic = Arc::from(""))]
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
