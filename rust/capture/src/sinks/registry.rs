//! A deployment's outputs: every lane it has, bound to a Kafka topic and the
//! named producer that carries it.

use std::sync::Arc;

use crate::config::OutputsConfig;
use crate::pipeline::{
    Address, AiLane, AnalyticsLane, AnalyticsOutputLane, ImportOutputLane, Lane, SessionReplayLane,
};
use crate::producers::ProducerName;

#[derive(Clone, Debug)]
pub struct SingleOutput<R = ProducerName> {
    // `Arc<str>` so the per-record lookup, metric labels and produce record never allocate.
    pub(crate) topic: Arc<str>,
    pub(crate) producer: R,
}

impl<R> SingleOutput<R> {
    pub(crate) fn map<T>(&self, f: &mut impl FnMut(&R) -> T) -> SingleOutput<T> {
        SingleOutput {
            topic: Arc::clone(&self.topic),
            producer: f(&self.producer),
        }
    }
}

/// One deployment's outputs: an output for every lane, the dlq output, and the
/// producer custom redirects publish on.
pub trait Outputs<R>: Send + Sync + 'static {
    type Lane: Lane;

    /// The same outputs with `T` naming each producer.
    type Mapped<T: Send + Sync + 'static>: Outputs<T, Lane = Self::Lane>;

    fn map_producers<T: Send + Sync + 'static>(&self, f: impl FnMut(&R) -> T) -> Self::Mapped<T>;

    fn target(&self, lane: Self::Lane) -> &SingleOutput<R>;

    fn dlq(&self) -> &SingleOutput<R>;

    fn custom_producer(&self) -> &R;

    /// Every fixed output with its label.
    fn rows(&self) -> Vec<(&'static str, &SingleOutput<R>)>;

    fn resolve(&self, address: &Address<Self::Lane>) -> (Arc<str>, &R) {
        let target = match address {
            Address::Lane(lane) => self.target(*lane),
            Address::Dlq => self.dlq(),
            Address::Custom(topic) => return (Arc::from(topic.as_str()), self.custom_producer()),
        };
        (Arc::clone(&target.topic), &target.producer)
    }

    /// Every fixed output must resolve to a non-empty topic.
    fn check_complete(&self) -> anyhow::Result<()> {
        for (output, target) in self.rows() {
            anyhow::ensure!(
                !target.topic.is_empty(),
                "output '{output}' resolves to an empty Kafka topic; every non-custom \
                 output must be bound to a configured, non-empty topic",
            );
        }
        Ok(())
    }
}

/// Events pods: the analytics routes, with `$ai_*`, `$exception`,
/// `$$heatmap` and `$$client_ingestion_warning` events diverted by name.
#[derive(Clone, Debug)]
pub struct AnalyticsOutputs<R = ProducerName> {
    pub(crate) analytics_main: SingleOutput<R>,
    pub(crate) analytics_overflow: SingleOutput<R>,
    pub(crate) analytics_historical: SingleOutput<R>,
    pub(crate) ai_main: SingleOutput<R>,
    pub(crate) ai_overflow: SingleOutput<R>,
    pub(crate) heatmaps: SingleOutput<R>,
    pub(crate) client_warnings: SingleOutput<R>,
    pub(crate) error_tracking: SingleOutput<R>,
    pub(crate) dlq: SingleOutput<R>,
    pub(crate) custom_producer: R,
}

/// Import pods: the analytics routes, but only `historical_migration`
/// batches, which never overflow.
#[derive(Clone, Debug)]
pub struct ImportOutputs<R = ProducerName> {
    pub(crate) analytics_historical: SingleOutput<R>,
    pub(crate) ai_main: SingleOutput<R>,
    pub(crate) heatmaps: SingleOutput<R>,
    pub(crate) client_warnings: SingleOutput<R>,
    pub(crate) error_tracking: SingleOutput<R>,
    pub(crate) dlq: SingleOutput<R>,
    pub(crate) custom_producer: R,
}

/// Ai pods: the AI routes, which accept only `$ai_*` events.
#[derive(Clone, Debug)]
pub struct AiOutputs<R = ProducerName> {
    pub(crate) ai_main: SingleOutput<R>,
    pub(crate) ai_overflow: SingleOutput<R>,
    pub(crate) dlq: SingleOutput<R>,
    pub(crate) custom_producer: R,
}

/// Recordings pods: the replay route.
#[derive(Clone, Debug)]
pub struct SessionReplayOutputs<R = ProducerName> {
    pub(crate) session_replay_main: SingleOutput<R>,
    pub(crate) session_replay_overflow: SingleOutput<R>,
    pub(crate) dlq: SingleOutput<R>,
    pub(crate) custom_producer: R,
}

impl<R: Send + Sync + 'static> Outputs<R> for AnalyticsOutputs<R> {
    type Lane = AnalyticsOutputLane;

    type Mapped<T: Send + Sync + 'static> = AnalyticsOutputs<T>;

    fn map_producers<T: Send + Sync + 'static>(
        &self,
        mut f: impl FnMut(&R) -> T,
    ) -> AnalyticsOutputs<T> {
        AnalyticsOutputs {
            analytics_main: self.analytics_main.map(&mut f),
            analytics_overflow: self.analytics_overflow.map(&mut f),
            analytics_historical: self.analytics_historical.map(&mut f),
            ai_main: self.ai_main.map(&mut f),
            ai_overflow: self.ai_overflow.map(&mut f),
            heatmaps: self.heatmaps.map(&mut f),
            client_warnings: self.client_warnings.map(&mut f),
            error_tracking: self.error_tracking.map(&mut f),
            dlq: self.dlq.map(&mut f),
            custom_producer: f(&self.custom_producer),
        }
    }

    fn target(&self, lane: AnalyticsOutputLane) -> &SingleOutput<R> {
        match lane {
            AnalyticsOutputLane::Analytics(AnalyticsLane::Main) => &self.analytics_main,
            AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow) => &self.analytics_overflow,
            AnalyticsOutputLane::Analytics(AnalyticsLane::Historical) => &self.analytics_historical,
            AnalyticsOutputLane::Ai(AiLane::Main) => &self.ai_main,
            AnalyticsOutputLane::Ai(AiLane::Overflow) => &self.ai_overflow,
            AnalyticsOutputLane::Heatmaps => &self.heatmaps,
            AnalyticsOutputLane::ClientWarnings => &self.client_warnings,
            AnalyticsOutputLane::ErrorTracking => &self.error_tracking,
        }
    }

    fn dlq(&self) -> &SingleOutput<R> {
        &self.dlq
    }

    fn custom_producer(&self) -> &R {
        &self.custom_producer
    }

    fn rows(&self) -> Vec<(&'static str, &SingleOutput<R>)> {
        let Self {
            analytics_main,
            analytics_overflow,
            analytics_historical,
            ai_main,
            ai_overflow,
            heatmaps,
            client_warnings,
            error_tracking,
            dlq,
            custom_producer: _,
        } = self;
        vec![
            ("analytics-main", analytics_main),
            ("analytics-overflow", analytics_overflow),
            ("analytics-historical", analytics_historical),
            ("ai-main", ai_main),
            ("ai-overflow", ai_overflow),
            ("heatmaps-main", heatmaps),
            ("clientwarnings-main", client_warnings),
            ("errortracking-main", error_tracking),
            ("dlq", dlq),
        ]
    }
}

impl<R: Send + Sync + 'static> Outputs<R> for ImportOutputs<R> {
    type Lane = ImportOutputLane;

    type Mapped<T: Send + Sync + 'static> = ImportOutputs<T>;

    fn map_producers<T: Send + Sync + 'static>(
        &self,
        mut f: impl FnMut(&R) -> T,
    ) -> ImportOutputs<T> {
        ImportOutputs {
            analytics_historical: self.analytics_historical.map(&mut f),
            ai_main: self.ai_main.map(&mut f),
            heatmaps: self.heatmaps.map(&mut f),
            client_warnings: self.client_warnings.map(&mut f),
            error_tracking: self.error_tracking.map(&mut f),
            dlq: self.dlq.map(&mut f),
            custom_producer: f(&self.custom_producer),
        }
    }

    fn target(&self, lane: ImportOutputLane) -> &SingleOutput<R> {
        match lane {
            ImportOutputLane::AnalyticsHistorical => &self.analytics_historical,
            ImportOutputLane::AiMain => &self.ai_main,
            ImportOutputLane::Heatmaps => &self.heatmaps,
            ImportOutputLane::ClientWarnings => &self.client_warnings,
            ImportOutputLane::ErrorTracking => &self.error_tracking,
        }
    }

    fn dlq(&self) -> &SingleOutput<R> {
        &self.dlq
    }

    fn custom_producer(&self) -> &R {
        &self.custom_producer
    }

    fn rows(&self) -> Vec<(&'static str, &SingleOutput<R>)> {
        let Self {
            analytics_historical,
            ai_main,
            heatmaps,
            client_warnings,
            error_tracking,
            dlq,
            custom_producer: _,
        } = self;
        vec![
            ("analytics-historical", analytics_historical),
            ("ai-main", ai_main),
            ("heatmaps-main", heatmaps),
            ("clientwarnings-main", client_warnings),
            ("errortracking-main", error_tracking),
            ("dlq", dlq),
        ]
    }
}

impl<R: Send + Sync + 'static> Outputs<R> for AiOutputs<R> {
    type Lane = AiLane;

    type Mapped<T: Send + Sync + 'static> = AiOutputs<T>;

    fn map_producers<T: Send + Sync + 'static>(&self, mut f: impl FnMut(&R) -> T) -> AiOutputs<T> {
        AiOutputs {
            ai_main: self.ai_main.map(&mut f),
            ai_overflow: self.ai_overflow.map(&mut f),
            dlq: self.dlq.map(&mut f),
            custom_producer: f(&self.custom_producer),
        }
    }

    fn target(&self, lane: AiLane) -> &SingleOutput<R> {
        match lane {
            AiLane::Main => &self.ai_main,
            AiLane::Overflow => &self.ai_overflow,
        }
    }

    fn dlq(&self) -> &SingleOutput<R> {
        &self.dlq
    }

    fn custom_producer(&self) -> &R {
        &self.custom_producer
    }

    fn rows(&self) -> Vec<(&'static str, &SingleOutput<R>)> {
        let Self {
            ai_main,
            ai_overflow,
            dlq,
            custom_producer: _,
        } = self;
        vec![
            ("ai-main", ai_main),
            ("ai-overflow", ai_overflow),
            ("dlq", dlq),
        ]
    }
}

impl<R: Send + Sync + 'static> Outputs<R> for SessionReplayOutputs<R> {
    type Lane = SessionReplayLane;

    type Mapped<T: Send + Sync + 'static> = SessionReplayOutputs<T>;

    fn map_producers<T: Send + Sync + 'static>(
        &self,
        mut f: impl FnMut(&R) -> T,
    ) -> SessionReplayOutputs<T> {
        SessionReplayOutputs {
            session_replay_main: self.session_replay_main.map(&mut f),
            session_replay_overflow: self.session_replay_overflow.map(&mut f),
            dlq: self.dlq.map(&mut f),
            custom_producer: f(&self.custom_producer),
        }
    }

    fn target(&self, lane: SessionReplayLane) -> &SingleOutput<R> {
        match lane {
            SessionReplayLane::Main => &self.session_replay_main,
            SessionReplayLane::Overflow => &self.session_replay_overflow,
        }
    }

    fn dlq(&self) -> &SingleOutput<R> {
        &self.dlq
    }

    fn custom_producer(&self) -> &R {
        &self.custom_producer
    }

    fn rows(&self) -> Vec<(&'static str, &SingleOutput<R>)> {
        let Self {
            session_replay_main,
            session_replay_overflow,
            dlq,
            custom_producer: _,
        } = self;
        vec![
            ("sessionreplay-main", session_replay_main),
            ("sessionreplay-overflow", session_replay_overflow),
            ("dlq", dlq),
        ]
    }
}

fn output(topic: &str, producer: ProducerName) -> SingleOutput {
    SingleOutput {
        topic: topic.into(),
        producer,
    }
}

impl AnalyticsOutputs {
    pub fn new(config: &OutputsConfig) -> Self {
        Self {
            analytics_main: output(&config.analytics_main_topic, config.analytics_main_producer),
            analytics_overflow: output(
                &config.analytics_overflow_topic,
                config.analytics_overflow_producer,
            ),
            analytics_historical: output(
                &config.analytics_historical_topic,
                config.analytics_historical_producer,
            ),
            ai_main: output(&config.ai_main_topic, config.ai_main_producer),
            ai_overflow: output(&config.ai_overflow_topic, config.ai_overflow_producer),
            heatmaps: output(&config.heatmaps_topic, config.heatmaps_producer),
            client_warnings: output(
                &config.client_warnings_topic,
                config.client_warnings_producer,
            ),
            error_tracking: output(&config.error_tracking_topic, config.error_tracking_producer),
            dlq: output(&config.dlq_topic, config.dlq_producer),
            custom_producer: config.custom_producer,
        }
    }
}

impl ImportOutputs {
    pub fn new(config: &OutputsConfig) -> Self {
        Self {
            analytics_historical: output(
                &config.analytics_historical_topic,
                config.analytics_historical_producer,
            ),
            ai_main: output(&config.ai_main_topic, config.ai_main_producer),
            heatmaps: output(&config.heatmaps_topic, config.heatmaps_producer),
            client_warnings: output(
                &config.client_warnings_topic,
                config.client_warnings_producer,
            ),
            error_tracking: output(&config.error_tracking_topic, config.error_tracking_producer),
            dlq: output(&config.dlq_topic, config.dlq_producer),
            custom_producer: config.custom_producer,
        }
    }
}

impl AiOutputs {
    pub fn new(config: &OutputsConfig) -> Self {
        Self {
            ai_main: output(&config.ai_main_topic, config.ai_main_producer),
            ai_overflow: output(&config.ai_overflow_topic, config.ai_overflow_producer),
            dlq: output(&config.dlq_topic, config.dlq_producer),
            custom_producer: config.custom_producer,
        }
    }
}

impl SessionReplayOutputs {
    pub fn new(config: &OutputsConfig) -> Self {
        Self {
            session_replay_main: output(
                &config.session_replay_main_topic,
                config.session_replay_main_producer,
            ),
            session_replay_overflow: output(
                &config.session_replay_overflow_topic,
                config.session_replay_overflow_producer,
            ),
            dlq: output(&config.dlq_topic, config.dlq_producer),
            custom_producer: config.custom_producer,
        }
    }
}

#[cfg(test)]
fn test_target(topic: &str) -> SingleOutput {
    SingleOutput {
        topic: Arc::from(topic),
        producer: ProducerName::Ingestion,
    }
}

#[cfg(test)]
pub(crate) fn test_outputs() -> AnalyticsOutputs {
    AnalyticsOutputs {
        analytics_main: test_target("events_plugin_ingestion"),
        analytics_overflow: test_target("events_plugin_ingestion_overflow"),
        analytics_historical: test_target("events_plugin_ingestion_historical"),
        ai_main: test_target("ai_events"),
        ai_overflow: test_target("ai_events_overflow"),
        heatmaps: test_target("heatmaps"),
        client_warnings: test_target("client_ingestion_warning"),
        error_tracking: test_target("error_tracking_events"),
        dlq: test_target("events_plugin_ingestion_dlq"),
        custom_producer: ProducerName::Ingestion,
    }
}

#[cfg(test)]
pub(crate) fn test_ai_outputs() -> AiOutputs {
    AiOutputs {
        ai_main: test_target("ai_events"),
        ai_overflow: test_target("ai_events_overflow"),
        dlq: test_target("events_plugin_ingestion_dlq"),
        custom_producer: ProducerName::Ingestion,
    }
}

#[cfg(test)]
pub(crate) fn test_replay_outputs() -> SessionReplayOutputs {
    SessionReplayOutputs {
        session_replay_main: test_target("events_plugin_ingestion"),
        session_replay_overflow: test_target("replay_overflow"),
        dlq: test_target("events_plugin_ingestion_dlq"),
        custom_producer: ProducerName::Ingestion,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn default_config() -> OutputsConfig {
        envconfig::Envconfig::init_from_hashmap(&Default::default())
            .expect("default outputs config")
    }

    const ANALYTICS_LANES: [AnalyticsOutputLane; 8] = [
        AnalyticsOutputLane::Analytics(AnalyticsLane::Main),
        AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow),
        AnalyticsOutputLane::Analytics(AnalyticsLane::Historical),
        AnalyticsOutputLane::Ai(AiLane::Main),
        AnalyticsOutputLane::Ai(AiLane::Overflow),
        AnalyticsOutputLane::Heatmaps,
        AnalyticsOutputLane::ClientWarnings,
        AnalyticsOutputLane::ErrorTracking,
    ];

    const IMPORT_LANES: [ImportOutputLane; 5] = [
        ImportOutputLane::AnalyticsHistorical,
        ImportOutputLane::AiMain,
        ImportOutputLane::Heatmaps,
        ImportOutputLane::ClientWarnings,
        ImportOutputLane::ErrorTracking,
    ];

    /// `target` and `rows` are written by hand per deployment; a lane mapped to
    /// another lane's field compiles. Every lane must resolve to the row its
    /// name labels, and every row to a distinct producer.
    fn assert_lanes_match_rows<O: Outputs<usize>>(outputs: &O, lanes: &[O::Lane]) {
        let rows = outputs.rows();
        for lane in lanes {
            let (_, row) = rows
                .iter()
                .find(|(label, _)| *label == lane.name())
                .unwrap_or_else(|| panic!("no row labelled '{}'", lane.name()));
            assert_eq!(outputs.target(*lane).producer, row.producer, "{lane:?}");
        }
        let dlq = Address::Dlq;
        assert_eq!(*outputs.resolve(&dlq).1, outputs.dlq().producer);
        let producers: std::collections::HashSet<usize> =
            rows.iter().map(|(_, target)| target.producer).collect();
        assert_eq!(producers.len(), rows.len(), "rows share a producer");
        assert_eq!(rows.len(), lanes.len() + 1, "one row per lane plus dlq");
    }

    fn numbered<R>() -> impl FnMut(&R) -> usize {
        let mut next = 0;
        move |_| {
            next += 1;
            next
        }
    }

    #[test]
    fn each_lane_resolves_to_its_own_output() {
        let config = default_config();
        assert_lanes_match_rows(
            &AnalyticsOutputs::new(&config).map_producers(numbered()),
            &ANALYTICS_LANES,
        );
        assert_lanes_match_rows(
            &ImportOutputs::new(&config).map_producers(numbered()),
            &IMPORT_LANES,
        );
        assert_lanes_match_rows(
            &AiOutputs::new(&config).map_producers(numbered()),
            &[AiLane::Main, AiLane::Overflow],
        );
        assert_lanes_match_rows(
            &SessionReplayOutputs::new(&config).map_producers(numbered()),
            &[SessionReplayLane::Main, SessionReplayLane::Overflow],
        );
    }

    #[test]
    fn custom_redirects_publish_on_the_custom_producer() {
        let outputs = test_outputs().map_producers(numbered());
        let custom = Address::Custom("admin_topic".to_string());
        let (topic, producer) = outputs.resolve(&custom);
        assert_eq!(&*topic, "admin_topic");
        assert_eq!(*producer, outputs.custom_producer);
    }

    #[test]
    fn check_complete_accepts_full_registry() {
        assert!(test_outputs().check_complete().is_ok());
    }

    /// Blanking a topic the deployment does not hold cannot fail the check, since
    /// it never reads it.
    #[test]
    fn check_complete_ignores_outputs_the_deployment_cannot_reach() {
        let config: OutputsConfig = envconfig::Envconfig::init_from_hashmap(
            &[(
                "CAPTURE_OUTPUT_SESSION_REPLAY_MAIN_TOPIC".to_string(),
                String::new(),
            )]
            .into_iter()
            .collect(),
        )
        .expect("outputs config");
        assert!(AnalyticsOutputs::new(&config).check_complete().is_ok());
        assert!(SessionReplayOutputs::new(&config).check_complete().is_err());
    }

    /// Every row, blanked one at a time, must fail the check and the error must
    /// name the offending output.
    #[rstest]
    #[case("analytics-main", |r: &mut AnalyticsOutputs| r.analytics_main.topic = Arc::from(""))]
    #[case("analytics-overflow", |r: &mut AnalyticsOutputs| r.analytics_overflow.topic = Arc::from(""))]
    #[case("analytics-historical", |r: &mut AnalyticsOutputs| r.analytics_historical.topic = Arc::from(""))]
    #[case("clientwarnings-main", |r: &mut AnalyticsOutputs| r.client_warnings.topic = Arc::from(""))]
    #[case("heatmaps-main", |r: &mut AnalyticsOutputs| r.heatmaps.topic = Arc::from(""))]
    #[case("dlq", |r: &mut AnalyticsOutputs| r.dlq.topic = Arc::from(""))]
    #[case("errortracking-main", |r: &mut AnalyticsOutputs| r.error_tracking.topic = Arc::from(""))]
    #[case("ai-main", |r: &mut AnalyticsOutputs| r.ai_main.topic = Arc::from(""))]
    #[case("ai-overflow", |r: &mut AnalyticsOutputs| r.ai_overflow.topic = Arc::from(""))]
    fn check_complete_rejects_empty_topic(
        #[case] output_name: &str,
        #[case] blank: fn(&mut AnalyticsOutputs),
    ) {
        let mut outputs = test_outputs();
        blank(&mut outputs);
        let err = outputs
            .check_complete()
            .expect_err("blank topic must fail the completeness check");
        let msg = format!("{err:#}");
        assert!(
            msg.contains(output_name),
            "error should name the missing output '{output_name}': {msg}"
        );
    }
}
