//! capture-analytics' emergency Kafka fallback. The idle fallback's topics
//! are checked on every boot, so a broken fallback shows up on an ordinary
//! deploy rather than in the emergency.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use metrics::gauge;
use tracing::{error, warn};

use crate::config::{CaptureMode, Config};
use crate::outputs::Target;
use crate::producers::ProducerName;
use crate::sinks::producer::KafkaProducer;
use crate::sinks::registry::OutputTable;

pub const CHECK_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_FALLBACK_CHECK";
pub const FALLBACK_BROKERS_VAR: &str = "KAFKA_FALLBACK_PRODUCER_METADATA_BROKER_LIST";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckMode {
    Warn,
    Strict,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FallbackSettings {
    pub check: CheckMode,
}

impl FallbackSettings {
    pub fn fallback_gates_liveness(&self) -> bool {
        self.check == CheckMode::Strict
    }

    pub fn from_config(config: &Config) -> anyhow::Result<Option<Self>> {
        let check = config.kafka_emergency_fallback_check.as_deref();
        if config.capture_mode != CaptureMode::Events {
            if check.is_some_and(|v| !v.is_empty()) {
                warn!(
                    capture_mode = config.capture_mode.as_tag(),
                    "{CHECK_VAR} applies only to CAPTURE_MODE=events; ignored"
                );
            }
            return Ok(None);
        }
        Ok(Some(Self {
            check: parse_check(check)?,
        }))
    }
}

pub fn parse_check(raw: Option<&str>) -> anyhow::Result<CheckMode> {
    match raw {
        None | Some("") | Some("warn") => Ok(CheckMode::Warn),
        Some("strict") => Ok(CheckMode::Strict),
        Some(other) => {
            anyhow::bail!(
                "invalid {CHECK_VAR}={other:?}: expected \"warn\" (default) or \"strict\""
            )
        }
    }
}

pub fn secondary_table(
    primary: &OutputTable,
    env: &HashMap<String, String>,
) -> anyhow::Result<OutputTable> {
    let read = |var: String| env.get(&var).filter(|v| !v.is_empty()).map(|v| (var, v));
    let producer = |var: String| -> anyhow::Result<ProducerName> {
        match read(var) {
            None => Ok(ProducerName::Fallback),
            Some((var, value)) => value
                .parse()
                .map_err(|e: anyhow::Error| anyhow::anyhow!("invalid {var}: {e}")),
        }
    };

    let mut secondary = primary.map_producers(|_| ProducerName::Fallback);
    for (name, target) in secondary.analytics_family_targets_mut() {
        if let Some((_, topic)) = read(format!("CAPTURE_OUTPUT_{name}_SECONDARY_TOPIC")) {
            target.topic = Arc::from(topic.as_str());
        }
        target.producer = producer(format!("CAPTURE_OUTPUT_{name}_SECONDARY_PRODUCER"))?;
    }
    secondary.custom_producer = producer("CAPTURE_OUTPUT_CUSTOM_SECONDARY_PRODUCER".to_string())?;
    Ok(secondary)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OnCheckFailure {
    Warn,
    RefuseBoot,
}

pub fn on_check_failure(target: Target, settings: FallbackSettings) -> OnCheckFailure {
    match (target, settings.check) {
        (Target::Fallback, CheckMode::Strict) => OnCheckFailure::RefuseBoot,
        (Target::Fallback, CheckMode::Warn) | (Target::Primary, _) => OnCheckFailure::Warn,
    }
}

pub const OUTPUT_TOPIC_READY: &str = "capture_kafka_output_topic_ready";

const TOPIC_CHECK_TIMEOUT: Duration = Duration::from_secs(10);

pub async fn run_boot_checks<P: KafkaProducer + 'static>(
    secondary: &OutputTable<Arc<P>>,
    settings: FallbackSettings,
) -> anyhow::Result<()> {
    check_target(secondary, Target::Fallback, settings).await
}

async fn check_target<P: KafkaProducer + 'static>(
    table: &OutputTable<Arc<P>>,
    target: Target,
    settings: FallbackSettings,
) -> anyhow::Result<()> {
    let failures = table
        .check_analytics_family_topics(TOPIC_CHECK_TIMEOUT)
        .await;
    for (output, _) in table.analytics_family_targets() {
        let ready = !failures.iter().any(|failure| failure.output == output);
        gauge!(OUTPUT_TOPIC_READY, "target" => target.as_str(), "output" => output).set(if ready {
            1.0
        } else {
            0.0
        });
    }
    if failures.is_empty() {
        return Ok(());
    }

    let message = format!(
        "{} target failed its topic check: {}",
        target.as_str(),
        failures
            .iter()
            .map(|f| format!("output {} topic {:?}: {}", f.output, f.topic, f.error))
            .collect::<Vec<_>>()
            .join("; ")
    );
    match on_check_failure(target, settings) {
        OnCheckFailure::Warn => error!("{message}"),
        OnCheckFailure::RefuseBoot => anyhow::bail!(message),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::producer::MockKafkaProducer;
    use crate::sinks::registry::test_outputs;
    use rstest::rstest;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[rstest]
    #[case(None, CheckMode::Warn)]
    #[case(Some(""), CheckMode::Warn)]
    #[case(Some("warn"), CheckMode::Warn)]
    #[case(Some("strict"), CheckMode::Strict)]
    fn check_mode_defaults_to_warn(#[case] raw: Option<&str>, #[case] mode: CheckMode) {
        assert_eq!(parse_check(raw).unwrap(), mode);
    }

    #[test]
    fn unknown_check_mode_refuses_boot() {
        let err = parse_check(Some("STRICT")).unwrap_err().to_string();
        assert!(err.contains(CHECK_VAR), "{err}");
    }

    fn config(mode: &str, check: &str) -> Config {
        envconfig::Envconfig::init_from_hashmap(&env(&[
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", mode),
            (CHECK_VAR, check),
        ]))
        .unwrap()
    }

    #[test]
    fn settings_read_the_check_variable_on_events_pods() {
        let settings = FallbackSettings::from_config(&config("events", "strict"))
            .unwrap()
            .unwrap();
        assert_eq!(settings.check, CheckMode::Strict);

        assert!(FallbackSettings::from_config(&config("events", "bogus")).is_err());
    }

    #[rstest]
    #[case("recordings")]
    #[case("ai")]
    #[case("import")]
    fn other_modes_never_parse_the_fallback_settings(#[case] mode: &str) {
        assert_eq!(
            FallbackSettings::from_config(&config(mode, "bogus")).unwrap(),
            None
        );
    }

    #[test]
    fn secondary_targets_default_to_the_primary_topic_on_the_fallback_producer() {
        let primary = test_outputs();
        let secondary = secondary_table(&primary, &HashMap::new()).unwrap();

        for ((name, p), (_, s)) in primary
            .analytics_family_targets()
            .into_iter()
            .zip(secondary.analytics_family_targets())
        {
            assert_eq!(s.topic, p.topic, "{name}");
            assert_eq!(s.producer, ProducerName::Fallback, "{name}");
        }
        assert_eq!(
            secondary.session_replay_main.topic,
            primary.session_replay_main.topic
        );
        assert!(secondary
            .producers()
            .iter()
            .all(|p| *p == ProducerName::Fallback));
        assert_eq!(
            secondary.has_ai_overflow_lane(),
            primary.has_ai_overflow_lane()
        );
    }

    #[test]
    fn secondary_targets_read_their_own_variables() {
        let secondary = secondary_table(
            &test_outputs(),
            &env(&[
                ("CAPTURE_OUTPUT_ANALYTICS_MAIN_SECONDARY_TOPIC", "ws_events"),
                ("CAPTURE_OUTPUT_DLQ_SECONDARY_TOPIC", "ws_dlq"),
                ("CAPTURE_OUTPUT_DLQ_SECONDARY_PRODUCER", "INGESTION"),
                ("CAPTURE_OUTPUT_AI_MAIN_SECONDARY_TOPIC", ""),
                ("CAPTURE_OUTPUT_HEATMAPS_SECONDARY_PRODUCER", ""),
                ("CAPTURE_OUTPUT_CUSTOM_SECONDARY_PRODUCER", "INGESTION"),
            ]),
        )
        .unwrap();

        assert_eq!(&*secondary.analytics_main.topic, "ws_events");
        assert_eq!(&*secondary.dlq.topic, "ws_dlq");
        assert_eq!(secondary.dlq.producer, ProducerName::Ingestion);
        assert_eq!(&*secondary.ai_main.topic, "ai_events", "empty means unset");
        assert_eq!(secondary.heatmaps.producer, ProducerName::Fallback);
        assert_eq!(secondary.custom_producer, ProducerName::Ingestion);
    }

    #[test]
    fn an_unknown_secondary_producer_names_its_variable() {
        let err = secondary_table(
            &test_outputs(),
            &env(&[(
                "CAPTURE_OUTPUT_AI_OVERFLOW_SECONDARY_PRODUCER",
                "WARPSTREAM",
            )]),
        )
        .unwrap_err()
        .to_string();

        assert!(
            err.contains("CAPTURE_OUTPUT_AI_OVERFLOW_SECONDARY_PRODUCER"),
            "{err}"
        );
    }

    #[rstest]
    #[case::warn(Target::Fallback, CheckMode::Warn, OnCheckFailure::Warn)]
    #[case::strict(Target::Fallback, CheckMode::Strict, OnCheckFailure::RefuseBoot)]
    fn check_failure_matrix(
        #[case] target: Target,
        #[case] check: CheckMode,
        #[case] expected: OnCheckFailure,
    ) {
        assert_eq!(
            on_check_failure(target, FallbackSettings { check }),
            expected
        );
    }

    async fn check(missing_topics: &[&str], check: CheckMode) -> anyhow::Result<()> {
        let producer =
            Arc::new(MockKafkaProducer::new().with_missing_topics(missing_topics.iter().copied()));
        let secondary = secondary_table(&test_outputs(), &HashMap::new())
            .unwrap()
            .map_producers(|_| Arc::clone(&producer));
        run_boot_checks(&secondary, FallbackSettings { check }).await
    }

    #[rstest]
    #[case::warn(CheckMode::Warn, true)]
    #[case::strict(CheckMode::Strict, false)]
    #[tokio::test]
    async fn a_missing_fallback_topic_warns_or_refuses_boot(
        #[case] mode: CheckMode,
        #[case] boots: bool,
    ) {
        let result = check(&["heatmaps"], mode).await;

        assert_eq!(result.is_ok(), boots, "{result:?}");
        if let Err(err) = result {
            let err = err.to_string();
            assert!(
                err.contains("fallback") && err.contains("HEATMAPS"),
                "{err}"
            );
        }
    }

    #[rstest]
    #[case(CheckMode::Warn)]
    #[case(CheckMode::Strict)]
    #[tokio::test]
    async fn a_complete_fallback_passes_every_mode(#[case] mode: CheckMode) {
        check(&[], mode).await.unwrap();
    }

    #[tokio::test]
    async fn the_topic_gauge_marks_only_the_failing_output() {
        let recorder = metrics_util::debugging::DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        check(&["heatmaps"], CheckMode::Warn).await.unwrap();

        let mut not_ready: Vec<(String, f64)> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, ..)| key.key().name() == OUTPUT_TOPIC_READY)
            .map(|(key, _, _, value)| {
                let output = key
                    .key()
                    .labels()
                    .find(|label| label.key() == "output")
                    .unwrap()
                    .value()
                    .to_string();
                let metrics_util::debugging::DebugValue::Gauge(value) = value else {
                    panic!("{OUTPUT_TOPIC_READY} is a gauge");
                };
                (output, value.into_inner())
            })
            .filter(|(_, value)| *value == 0.0)
            .collect();
        not_ready.sort_by(|a, b| a.0.cmp(&b.0));

        assert_eq!(not_ready, vec![("HEATMAPS".to_string(), 0.0)]);
    }
}
