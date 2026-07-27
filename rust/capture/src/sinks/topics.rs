//! Per-cluster topic table — how a Kafka sink realizes an [`Address`] in its
//! own cluster's namespace.
//!
//! A topic name only means something relative to one broker set, so the table
//! is sink-side data: setup builds it from config (running the mode-scoped
//! completeness check) and *supplies* it to the sink at construction. Sinks
//! never import the outputs layer; the [`Address`] is the shared interchange
//! vocabulary. Swapping a sink's table is the seam a repartitioning
//! coordinator plugs into.
//!
//! The completeness check refuses to boot when any topic a deployment can
//! actually produce to resolves to an empty string, scoped by
//! [`CaptureMode`]: a `Recordings` pod produces only main / replay-overflow /
//! dlq and must not demand analytics topics; `Events`/`Ai` pods produce the
//! analytics family and never replay-overflow (#68719).
//!
//! `Custom` addresses carry an admin-supplied topic inline and bypass the
//! table entirely.

use crate::config::{CaptureMode, KafkaConfig};
use crate::pipeline::{Address, AiLane, AnalyticsLane, BasicLane, ReplayLane};

/// A named topic accessor the completeness check walks: `(label, getter)`.
type TopicEntry = (&'static str, fn(&TopicTable) -> &str);

/// One cluster's address → topic wiring. Cheap to clone; sinks hold it behind
/// an `Arc`.
///
/// Both sink stacks resolve topics through this one type: the v0 stack builds
/// it [`From<&KafkaConfig>`], the v1 stack builds it from its per-sink Kafka
/// config. The fields are `pub(crate)` so those constructors — and the
/// completeness tests — can populate them by name.
#[derive(Clone, Debug)]
pub struct TopicTable {
    pub(crate) main: String,
    pub(crate) overflow: String,
    pub(crate) historical: String,
    pub(crate) client_ingestion_warning: String,
    pub(crate) heatmaps: String,
    pub(crate) replay_overflow: String,
    pub(crate) dlq: String,
    pub(crate) error_tracking: String,
}

/// The topics an `Events`/`Ai` deployment can produce to, as
/// `(label, accessor)` pairs the completeness check walks. The analytics
/// family: every batch/event/ai/otel pipeline reaches main / overflow /
/// historical / client-ingestion-warning / heatmaps / error-tracking, plus
/// `dlq` (any pipeline can DLQ). Never replay-overflow — that is the
/// recordings pipeline's alone.
const ANALYTICS_FAMILY_TOPICS: [TopicEntry; 7] = [
    ("main", |t| &t.main),
    ("overflow", |t| &t.overflow),
    ("historical", |t| &t.historical),
    ("client_ingestion_warning", |t| &t.client_ingestion_warning),
    ("heatmaps", |t| &t.heatmaps),
    ("error_tracking", |t| &t.error_tracking),
    ("dlq", |t| &t.dlq),
];

/// The topics a `Recordings` deployment can produce to: the replay pipeline
/// emits only snapshots, which route to main or replay-overflow, plus `dlq`.
const RECORDINGS_TOPICS: [TopicEntry; 3] = [
    ("main", |t| &t.main),
    ("replay_overflow", |t| &t.replay_overflow),
    ("dlq", |t| &t.dlq),
];

impl TopicTable {
    /// Realize an address in this cluster's namespace. Total — lanes are
    /// typed per pipeline, so there is no invalid pair to reject. The AI
    /// pipeline maps onto the analytics topics today; giving it its own
    /// topics is a table change, not a routing change. `Custom` returns its
    /// inline admin-supplied topic.
    pub fn topic_for<'a>(&'a self, address: &'a Address) -> &'a str {
        match address {
            Address::Custom { topic, .. } => topic,
            Address::Analytics(AnalyticsLane::Main) => &self.main,
            Address::Analytics(AnalyticsLane::Overflow) => &self.overflow,
            Address::Analytics(AnalyticsLane::Historical) => &self.historical,
            Address::Analytics(AnalyticsLane::Dlq) => &self.dlq,
            Address::Ai(AiLane::Main) => &self.main,
            Address::Ai(AiLane::Overflow) => &self.overflow,
            Address::Ai(AiLane::Historical) => &self.historical,
            Address::Ai(AiLane::Dlq) => &self.dlq,
            Address::Heatmaps(BasicLane::Main) => &self.heatmaps,
            Address::Heatmaps(BasicLane::Dlq) => &self.dlq,
            Address::Warnings(BasicLane::Main) => &self.client_ingestion_warning,
            Address::Warnings(BasicLane::Dlq) => &self.dlq,
            Address::ErrorTracking(BasicLane::Main) => &self.error_tracking,
            Address::ErrorTracking(BasicLane::Dlq) => &self.dlq,
            Address::Replay(ReplayLane::Main) => &self.main,
            Address::Replay(ReplayLane::Overflow) => &self.replay_overflow,
            Address::Replay(ReplayLane::Dlq) => &self.dlq,
        }
    }

    /// The topics a deployment in `mode` can actually produce to — the exact
    /// set `check_complete` demands be wired. Scoping to the mode's reachable
    /// topics is what keeps a `Recordings` pod from demanding analytics
    /// topics (and an `Events`/`Ai` pod from demanding replay-overflow).
    fn required_for(mode: CaptureMode) -> &'static [TopicEntry] {
        match mode {
            CaptureMode::Events | CaptureMode::Ai => &ANALYTICS_FAMILY_TOPICS,
            CaptureMode::Recordings => &RECORDINGS_TOPICS,
        }
    }

    /// Startup completeness check, scoped to `mode`: every topic the mode's
    /// pipelines can route to must be non-empty. A misconfigured or
    /// newly-added-but-unwired topic fails fast at boot instead of at first
    /// produce, while a mode never demands a topic it cannot produce to.
    pub fn check_complete(&self, mode: CaptureMode) -> anyhow::Result<()> {
        for (name, topic) in Self::required_for(mode) {
            anyhow::ensure!(
                !topic(self).is_empty(),
                "output '{}' resolves to an empty Kafka topic in '{}' capture mode; \
                 every output the mode produces to must be bound to a configured, \
                 non-empty topic",
                name,
                mode.as_tag(),
            );
        }
        Ok(())
    }
}

impl From<&KafkaConfig> for TopicTable {
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

/// Shared `TopicTable` fixture for tests across the capture crate. Used by
/// sink-side routing tests and pipeline-to-sink E2E tests so every test site
/// agrees on the topic wiring.
#[cfg(test)]
pub(crate) fn test_topics() -> TopicTable {
    TopicTable {
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
    use crate::pipeline::Pipeline;
    use rstest::rstest;

    #[rstest]
    #[case(Address::Analytics(AnalyticsLane::Main), "events_plugin_ingestion")]
    #[case(
        Address::Analytics(AnalyticsLane::Overflow),
        "events_plugin_ingestion_overflow"
    )]
    #[case(
        Address::Analytics(AnalyticsLane::Historical),
        "events_plugin_ingestion_historical"
    )]
    #[case(Address::Analytics(AnalyticsLane::Dlq), "events_plugin_ingestion_dlq")]
    #[case(Address::Ai(AiLane::Main), "events_plugin_ingestion")]
    #[case(Address::Ai(AiLane::Overflow), "events_plugin_ingestion_overflow")]
    #[case(Address::Heatmaps(BasicLane::Main), "heatmaps")]
    #[case(Address::Warnings(BasicLane::Main), "client_ingestion_warning")]
    #[case(Address::ErrorTracking(BasicLane::Main), "error_tracking_events")]
    #[case(Address::Replay(ReplayLane::Main), "events_plugin_ingestion")]
    #[case(Address::Replay(ReplayLane::Overflow), "replay_overflow")]
    #[case(Address::Replay(ReplayLane::Dlq), "events_plugin_ingestion_dlq")]
    #[case(
        Address::Custom { pipeline: Pipeline::Analytics, topic: "admin_topic".to_string() },
        "admin_topic"
    )]
    fn topic_for_resolves_every_address(#[case] address: Address, #[case] topic: &str) {
        assert_eq!(test_topics().topic_for(&address), topic);
    }

    #[rstest]
    #[case(CaptureMode::Events)]
    #[case(CaptureMode::Recordings)]
    #[case(CaptureMode::Ai)]
    fn check_complete_accepts_full_table(#[case] mode: CaptureMode) {
        assert!(test_topics().check_complete(mode).is_ok());
    }

    /// Every topic a mode produces to, blanked one at a time, must fail that
    /// mode's check and the error must name the offending output — the #68719
    /// completeness seam, scoped per mode.
    #[rstest]
    // Analytics family — demanded by Events and Ai, never by Recordings.
    #[case(CaptureMode::Events, "main", |t: &mut TopicTable| t.main.clear())]
    #[case(CaptureMode::Events, "overflow", |t: &mut TopicTable| t.overflow.clear())]
    #[case(CaptureMode::Events, "historical", |t: &mut TopicTable| t.historical.clear())]
    #[case(CaptureMode::Events, "client_ingestion_warning", |t: &mut TopicTable| t.client_ingestion_warning.clear())]
    #[case(CaptureMode::Events, "heatmaps", |t: &mut TopicTable| t.heatmaps.clear())]
    #[case(CaptureMode::Events, "error_tracking", |t: &mut TopicTable| t.error_tracking.clear())]
    #[case(CaptureMode::Events, "dlq", |t: &mut TopicTable| t.dlq.clear())]
    #[case(CaptureMode::Ai, "overflow", |t: &mut TopicTable| t.overflow.clear())]
    // Recordings family — main / replay-overflow / dlq only.
    #[case(CaptureMode::Recordings, "main", |t: &mut TopicTable| t.main.clear())]
    #[case(CaptureMode::Recordings, "replay_overflow", |t: &mut TopicTable| t.replay_overflow.clear())]
    #[case(CaptureMode::Recordings, "dlq", |t: &mut TopicTable| t.dlq.clear())]
    fn check_complete_rejects_empty_topic(
        #[case] mode: CaptureMode,
        #[case] output_name: &str,
        #[case] blank: fn(&mut TopicTable),
    ) {
        let mut table = test_topics();
        blank(&mut table);
        let err = table
            .check_complete(mode)
            .expect_err("blank topic must fail the completeness check");
        let msg = format!("{err:#}");
        assert!(
            msg.contains(output_name),
            "error should name the missing output '{output_name}': {msg}"
        );
    }

    /// A mode must not demand a topic it never produces to. Blanking a topic
    /// outside the mode's reachable set leaves the check green — the anti-
    /// over-demand guarantee that lets Recordings and Events/Ai deployments
    /// share one `KafkaConfig` without each carrying the other's topics.
    #[rstest]
    // Recordings ignores the whole analytics family.
    #[case(CaptureMode::Recordings, |t: &mut TopicTable| t.overflow.clear())]
    #[case(CaptureMode::Recordings, |t: &mut TopicTable| t.historical.clear())]
    #[case(CaptureMode::Recordings, |t: &mut TopicTable| t.client_ingestion_warning.clear())]
    #[case(CaptureMode::Recordings, |t: &mut TopicTable| t.heatmaps.clear())]
    #[case(CaptureMode::Recordings, |t: &mut TopicTable| t.error_tracking.clear())]
    // Events and Ai ignore replay-overflow.
    #[case(CaptureMode::Events, |t: &mut TopicTable| t.replay_overflow.clear())]
    #[case(CaptureMode::Ai, |t: &mut TopicTable| t.replay_overflow.clear())]
    fn check_complete_ignores_unreachable_topics(
        #[case] mode: CaptureMode,
        #[case] blank: fn(&mut TopicTable),
    ) {
        let mut table = test_topics();
        blank(&mut table);
        assert!(
            table.check_complete(mode).is_ok(),
            "a blank topic the mode never produces to must not fail its check"
        );
    }
}
