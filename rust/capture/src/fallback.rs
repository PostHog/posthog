//! capture-analytics' emergency Kafka fallback. The idle fallback's topics
//! are checked on every boot, so a broken fallback shows up on an ordinary
//! deploy rather than in the emergency.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;

use metrics::gauge;
use tracing::{error, info, warn};

use crate::config::{CaptureMode, Config, FallbackOutputsConfig};
use crate::outputs::{record_live_target, Output, Target};
use crate::producers::{ProducerConfig, ProducerHandle, ProducerName, ProducerRegistry};
use crate::sinks::kafka::KafkaSink;
use crate::sinks::producer::KafkaProducer;
use crate::sinks::registry::{OutputTable, OutputTarget};

pub const ARMING_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_FALLBACK";
pub const ARMING_VALUE: &str = "FALLBACK-TO-BACKUP-KAFKA-NOW";
pub const CHECK_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_FALLBACK_CHECK";
pub const FALLBACK_BROKERS_VAR: &str = "KAFKA_FALLBACK_PRODUCER_METADATA_BROKER_LIST";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CheckMode {
    Warn,
    Strict,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FallbackSettings {
    armed: bool,
    check: CheckMode,
}

impl FallbackSettings {
    fn live(&self) -> Target {
        if self.armed {
            Target::Fallback
        } else {
            Target::Primary
        }
    }

    fn from_config(config: &Config) -> anyhow::Result<Option<Self>> {
        let arming = config.kafka_emergency_fallback.as_deref();
        let check = config.kafka_emergency_fallback_check.as_deref();
        if config.capture_mode != CaptureMode::Events {
            if [arming, check]
                .iter()
                .any(|v| v.is_some_and(|v| !v.is_empty()))
            {
                warn!(
                    capture_mode = config.capture_mode.as_tag(),
                    "{ARMING_VAR} and {CHECK_VAR} apply only to CAPTURE_MODE=events; ignored"
                );
            }
            return Ok(None);
        }
        Ok(Some(Self {
            armed: parse_arming(arming)?,
            check: parse_check(check)?,
        }))
    }
}

/// Any other value refuses boot, so a typo is a crashloop an operator sees,
/// not a switch they think happened.
fn parse_arming(raw: Option<&str>) -> anyhow::Result<bool> {
    match raw {
        None | Some("") => Ok(false),
        Some(ARMING_VALUE) => Ok(true),
        Some(other) => anyhow::bail!(
            "invalid {ARMING_VAR}={other:?}: leave it unset or empty for normal operation, \
             or set it to exactly {ARMING_VALUE:?} to publish to the fallback cluster"
        ),
    }
}

fn parse_check(raw: Option<&str>) -> anyhow::Result<CheckMode> {
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

fn fallback_table(primary: &OutputTable, fallback_config: &FallbackOutputsConfig) -> OutputTable {
    let target =
        |primary: &OutputTarget, topic: &Option<String>, producer: Option<ProducerName>| {
            OutputTarget {
                topic: topic
                    .as_deref()
                    .filter(|topic| !topic.is_empty())
                    .map(Arc::from)
                    .unwrap_or_else(|| Arc::clone(&primary.topic)),
                producer: producer.unwrap_or(ProducerName::Fallback),
            }
        };
    OutputTable {
        analytics_main: target(
            &primary.analytics_main,
            &fallback_config.analytics_main_topic,
            fallback_config.analytics_main_producer,
        ),
        analytics_overflow: target(
            &primary.analytics_overflow,
            &fallback_config.analytics_overflow_topic,
            fallback_config.analytics_overflow_producer,
        ),
        analytics_historical: target(
            &primary.analytics_historical,
            &fallback_config.analytics_historical_topic,
            fallback_config.analytics_historical_producer,
        ),
        session_replay_main: target(&primary.session_replay_main, &None, None),
        session_replay_overflow: target(&primary.session_replay_overflow, &None, None),
        client_warnings: target(
            &primary.client_warnings,
            &fallback_config.client_warnings_topic,
            fallback_config.client_warnings_producer,
        ),
        heatmaps: target(
            &primary.heatmaps,
            &fallback_config.heatmaps_topic,
            fallback_config.heatmaps_producer,
        ),
        dlq: target(
            &primary.dlq,
            &fallback_config.dlq_topic,
            fallback_config.dlq_producer,
        ),
        error_tracking: target(
            &primary.error_tracking,
            &fallback_config.error_tracking_topic,
            fallback_config.error_tracking_producer,
        ),
        ai_main: target(
            &primary.ai_main,
            &fallback_config.ai_main_topic,
            fallback_config.ai_main_producer,
        ),
        ai_overflow: target(
            &primary.ai_overflow,
            &fallback_config.ai_overflow_topic,
            fallback_config.ai_overflow_producer,
        ),
        has_ai_overflow_lane: primary.has_ai_overflow_lane,
        custom_producer: fallback_config
            .custom_producer
            .unwrap_or(ProducerName::Fallback),
    }
}

enum Fallback {
    NotApplicable,
    NotConfigured,
    Configured {
        settings: FallbackSettings,
        table: Box<OutputTable>,
    },
}

impl Fallback {
    fn resolve(
        config: &Config,
        primary: &OutputTable,
        producer_configs: &HashMap<ProducerName, ProducerConfig>,
    ) -> anyhow::Result<Self> {
        let Some(settings) = FallbackSettings::from_config(config)? else {
            return Ok(Self::NotApplicable);
        };
        if !producer_configs.contains_key(&ProducerName::Fallback) {
            anyhow::ensure!(
                !settings.armed,
                "{ARMING_VAR} is armed but {FALLBACK_BROKERS_VAR} is not set"
            );
            anyhow::ensure!(
                settings.check == CheckMode::Warn,
                "{CHECK_VAR}=strict but {FALLBACK_BROKERS_VAR} is not set"
            );
            return Ok(Self::NotConfigured);
        }
        if settings.armed {
            error!("{ARMING_VAR} is armed: capture-analytics publishes to the fallback cluster");
        }
        Ok(Self::Configured {
            settings,
            table: Box::new(fallback_table(primary, &config.fallback_outputs)),
        })
    }

    fn live(&self) -> Target {
        match self {
            Self::Configured { settings, .. } => settings.live(),
            Self::NotApplicable | Self::NotConfigured => Target::Primary,
        }
    }

    fn live_table<'a>(&'a self, primary: &'a OutputTable) -> &'a OutputTable {
        match (self.live(), self.table()) {
            (Target::Fallback, Some(table)) => table,
            _ => primary,
        }
    }

    fn table(&self) -> Option<&OutputTable> {
        match self {
            Self::Configured { table, .. } => Some(table),
            Self::NotApplicable | Self::NotConfigured => None,
        }
    }

    fn producer_configs(
        &self,
        configs: &HashMap<ProducerName, ProducerConfig>,
    ) -> HashMap<ProducerName, ProducerConfig> {
        let mut configs = configs.clone();
        if matches!(self, Self::NotApplicable) && configs.remove(&ProducerName::Fallback).is_some()
        {
            info!("{FALLBACK_BROKERS_VAR} is ignored outside CAPTURE_MODE=events");
        }
        configs
    }

    async fn check_at_boot(
        &self,
        producers: &ProducerRegistry,
        primary: &OutputTable<ProducerHandle>,
        producer_configs: &HashMap<ProducerName, ProducerConfig>,
    ) -> anyhow::Result<()> {
        let Self::Configured { settings, table } = self else {
            return Ok(());
        };
        ensure_checks_cannot_create_topics(table, producer_configs)?;
        let table = table.map_producers(|name| producers.get(*name));
        run_boot_checks(primary, &table, *settings).await
    }
}

pub async fn build_kafka_output(
    config: &Config,
    producer_configs: &HashMap<ProducerName, ProducerConfig>,
    liveness: Option<lifecycle::Handle>,
) -> anyhow::Result<(Output, ProducerRegistry)> {
    // Runs before any producer connects, so a blank topic refuses boot
    // immediately instead of after a broker connect attempt.
    let primary = OutputTable::new(&config.outputs, config.capture_mode.has_ai_overflow_lane());
    if config.outputs_completeness_check_enabled {
        primary.check_complete()?;
    } else {
        info!("outputs completeness check disabled; a blank output topic will fail at first produce instead of at boot");
    }

    let fallback = Fallback::resolve(config, &primary, producer_configs)?;
    let producer_configs = fallback.producer_configs(producer_configs);
    for table in std::iter::once(&primary).chain(fallback.table()) {
        for name in table.producers() {
            anyhow::ensure!(
                producer_configs.contains_key(&name),
                "an output publishes through producer {}, which is not configured",
                name.as_str()
            );
        }
    }

    let live_producers = fallback.live_table(&primary).producers();
    let liveness = liveness
        .map(|handle| {
            live_producers
                .iter()
                .map(|&name| (name, handle.clone()))
                .collect()
        })
        .unwrap_or_default();
    let producers = ProducerRegistry::build(&producer_configs, liveness)
        .context("failed to start Kafka producers")?;

    let primary = primary.map_producers(|name| producers.get(*name));
    fallback
        .check_at_boot(&producers, &primary, &producer_configs)
        .await?;
    let compression = config.replay_envelope_compression;
    let live = fallback.live();
    let output = match fallback.table() {
        None => Output::single(KafkaSink::new(primary, compression)),
        Some(table) => Output::select(
            Output::single(KafkaSink::new(primary, compression)),
            Output::single(KafkaSink::new(
                table.map_producers(|name| producers.get(*name)),
                compression,
            )),
            live,
        ),
    };
    record_live_target(live);
    Ok((output, producers))
}

/// A topic check that names a missing topic makes the broker create it when
/// the producer allows auto-creation, and then the check passes.
fn ensure_checks_cannot_create_topics(
    fallback: &OutputTable,
    producer_configs: &HashMap<ProducerName, ProducerConfig>,
) -> anyhow::Result<()> {
    for target in fallback.analytics_family_targets() {
        let producer = target.producer;
        anyhow::ensure!(
            producer_configs
                .get(&producer)
                .is_some_and(|config| !config.allow_auto_create_topics),
            "fallback topic {:?} is checked through producer {}, which allows topic \
             auto-creation, so the check could create it; set \
             KAFKA_{}_PRODUCER_ALLOW_AUTO_CREATE_TOPICS=false",
            target.topic,
            producer.as_str(),
            producer.as_str(),
        );
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum OnCheckFailure {
    Warn,
    RefuseBoot,
}

/// An idle primary only warns: arming means its cluster is degraded, and its
/// failure must not block the switch.
fn on_check_failure(target: Target, settings: FallbackSettings) -> OnCheckFailure {
    match (target, settings.armed, settings.check) {
        (Target::Fallback, true, _) | (Target::Fallback, false, CheckMode::Strict) => {
            OnCheckFailure::RefuseBoot
        }
        (Target::Fallback, false, CheckMode::Warn) | (Target::Primary, _, _) => {
            OnCheckFailure::Warn
        }
    }
}

const OUTPUT_TOPIC_READY: &str = "capture_kafka_output_topic_ready";

const TOPIC_CHECK_TIMEOUT: Duration = Duration::from_secs(10);

async fn run_boot_checks<P: KafkaProducer + 'static>(
    primary: &OutputTable<Arc<P>>,
    fallback: &OutputTable<Arc<P>>,
    settings: FallbackSettings,
) -> anyhow::Result<()> {
    if settings.armed {
        check_target(primary, Target::Primary, settings).await?;
    }
    check_target(fallback, Target::Fallback, settings).await
}

async fn check_target<P: KafkaProducer + 'static>(
    table: &OutputTable<Arc<P>>,
    target: Target,
    settings: FallbackSettings,
) -> anyhow::Result<()> {
    let failures = table
        .check_analytics_family_topics(TOPIC_CHECK_TIMEOUT)
        .await;
    for output in table.analytics_family_targets() {
        let ready = !failures.iter().any(|failure| failure.topic == output.topic);
        gauge!(OUTPUT_TOPIC_READY, "target" => target.as_str(), "topic" => output.topic.to_string())
            .set(if ready { 1.0 } else { 0.0 });
    }
    if failures.is_empty() {
        return Ok(());
    }

    let message = format!(
        "{} target failed its topic check: {}",
        target.as_str(),
        failures
            .iter()
            .map(|f| format!("topic {:?}: {}", f.topic, f.error))
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
    use crate::ordering::OrderingGuarantee;
    use crate::outputs::{Output, PreparedEvent, PublishPrepared};
    use crate::pipeline::Address;
    use crate::sinks::kafka::KafkaSinkBase;
    use crate::sinks::producer::MockKafkaProducer;
    use crate::sinks::registry::test_outputs;
    use rstest::rstest;

    fn fallback_config(pairs: &[(&str, &str)]) -> FallbackOutputsConfig {
        envconfig::Envconfig::init_from_hashmap(&env(pairs)).unwrap()
    }

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[rstest]
    #[case::unset(None, false)]
    #[case::empty(Some(""), false)]
    #[case::sentinel(Some(ARMING_VALUE), true)]
    fn arming_accepts_only_unset_empty_or_the_sentinel(
        #[case] raw: Option<&str>,
        #[case] armed: bool,
    ) {
        assert_eq!(parse_arming(raw).unwrap(), armed);
    }

    #[rstest]
    #[case("1")]
    #[case("true")]
    #[case("yes")]
    #[case(" ")]
    #[case(" FALLBACK-TO-BACKUP-KAFKA-NOW")]
    #[case("FALLBACK-TO-BACKUP-KAFKA-NOW\n")]
    #[case("fallback-to-backup-kafka-now")]
    #[case("FALLBACK-TO-BACKUP-KAFKA")]
    fn any_other_arming_value_refuses_boot(#[case] raw: &str) {
        let err = parse_arming(Some(raw)).unwrap_err().to_string();

        assert!(err.contains(ARMING_VAR), "{err}");
        assert!(err.contains(ARMING_VALUE), "{err}");
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

    fn config(mode: &str, arming: &str, check: &str) -> Config {
        envconfig::Envconfig::init_from_hashmap(&env(&[
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", mode),
            (ARMING_VAR, arming),
            (CHECK_VAR, check),
        ]))
        .unwrap()
    }

    #[test]
    fn settings_read_their_variables_on_events_pods() {
        let settings = FallbackSettings::from_config(&config("events", ARMING_VALUE, "strict"))
            .unwrap()
            .unwrap();
        assert_eq!(settings.live(), Target::Fallback);
        assert_eq!(settings.check, CheckMode::Strict);

        assert!(FallbackSettings::from_config(&config("events", "true", "")).is_err());
        assert!(FallbackSettings::from_config(&config("events", "", "bogus")).is_err());
    }

    #[rstest]
    #[case("recordings")]
    #[case("ai")]
    #[case("import")]
    fn other_modes_never_parse_the_fallback_settings(#[case] mode: &str) {
        assert_eq!(
            FallbackSettings::from_config(&config(mode, "not-the-sentinel", "bogus")).unwrap(),
            None
        );
    }

    #[rstest]
    #[case::armed(ARMING_VALUE, "")]
    #[case::strict("", "strict")]
    #[tokio::test]
    async fn a_required_fallback_without_a_cluster_refuses_boot(
        #[case] arming: &str,
        #[case] check: &str,
    ) {
        let producer_configs = crate::producers::load_all(&HashMap::new()).unwrap();

        let err = build_kafka_output(&config("events", arming, check), &producer_configs, None)
            .await
            .err()
            .expect("boot must be refused");

        assert!(format!("{err:#}").contains(FALLBACK_BROKERS_VAR), "{err:#}");
    }

    #[rstest]
    #[case("recordings")]
    #[case("ai")]
    #[case("import")]
    #[tokio::test]
    async fn other_modes_never_build_the_fallback_producer(#[case] mode: &str) {
        let producer_configs =
            crate::producers::load_all(&env(&[(FALLBACK_BROKERS_VAR, "127.0.0.1:1")])).unwrap();

        let config = config(mode, "not-the-sentinel", "bogus");
        let (_, producers) = build_kafka_output(&config, &producer_configs, None)
            .await
            .expect("other modes must boot whatever the fallback settings say");

        assert!(producers.contains(ProducerName::Ingestion));
        assert!(!producers.contains(ProducerName::Fallback));
    }

    #[test]
    fn fallback_targets_default_to_the_primary_topic_on_the_fallback_producer() {
        let primary = test_outputs();
        let fallback = fallback_table(&primary, &FallbackOutputsConfig::default());

        for (p, s) in primary
            .analytics_family_targets()
            .into_iter()
            .zip(fallback.analytics_family_targets())
        {
            assert_eq!(s.topic, p.topic);
            assert_eq!(s.producer, ProducerName::Fallback, "{}", s.topic);
        }
        assert_eq!(
            fallback.session_replay_main.topic,
            primary.session_replay_main.topic
        );
        assert!(fallback
            .producers()
            .iter()
            .all(|p| *p == ProducerName::Fallback));
        assert_eq!(
            fallback.has_ai_overflow_lane(),
            primary.has_ai_overflow_lane()
        );
    }

    #[test]
    fn fallback_targets_read_their_own_variables() {
        let fallback = fallback_table(
            &test_outputs(),
            &fallback_config(&[
                ("CAPTURE_OUTPUT_ANALYTICS_MAIN_FALLBACK_TOPIC", "ws_events"),
                ("CAPTURE_OUTPUT_DLQ_FALLBACK_TOPIC", "ws_dlq"),
                ("CAPTURE_OUTPUT_DLQ_FALLBACK_PRODUCER", "INGESTION"),
                ("CAPTURE_OUTPUT_AI_MAIN_FALLBACK_TOPIC", ""),
                ("CAPTURE_OUTPUT_CUSTOM_FALLBACK_PRODUCER", "INGESTION"),
            ]),
        );

        assert_eq!(&*fallback.analytics_main.topic, "ws_events");
        assert_eq!(&*fallback.dlq.topic, "ws_dlq");
        assert_eq!(fallback.dlq.producer, ProducerName::Ingestion);
        assert_eq!(&*fallback.ai_main.topic, "ai_events", "empty means unset");
        assert_eq!(fallback.heatmaps.producer, ProducerName::Fallback);
        assert_eq!(fallback.custom_producer, ProducerName::Ingestion);
    }

    #[test]
    fn an_unknown_fallback_producer_names_its_variable() {
        let err = <FallbackOutputsConfig as envconfig::Envconfig>::init_from_hashmap(&env(&[(
            "CAPTURE_OUTPUT_AI_OVERFLOW_FALLBACK_PRODUCER",
            "WARPSTREAM",
        )]))
        .err()
        .unwrap()
        .to_string();

        assert!(
            err.contains("CAPTURE_OUTPUT_AI_OVERFLOW_FALLBACK_PRODUCER"),
            "{err}"
        );
    }

    #[rstest]
    #[case::fallback_default(&[], true)]
    #[case::fallback_output_on_ingestion(&[("CAPTURE_OUTPUT_DLQ_FALLBACK_PRODUCER", "INGESTION")], false)]
    #[case::fallback_allows_it(&[("KAFKA_FALLBACK_PRODUCER_ALLOW_AUTO_CREATE_TOPICS", "true")], false)]
    fn fallback_checks_refuse_a_producer_that_can_create_topics(
        #[case] pairs: &[(&str, &str)],
        #[case] boots: bool,
    ) {
        let mut env = env(pairs);
        env.insert(FALLBACK_BROKERS_VAR.to_string(), "ws:9092".to_string());
        let configs = crate::producers::load_all(&env).unwrap();
        let fallback = fallback_table(
            &test_outputs(),
            &envconfig::Envconfig::init_from_hashmap(&env).unwrap(),
        );

        let result = ensure_checks_cannot_create_topics(&fallback, &configs);

        assert_eq!(result.is_ok(), boots, "{result:?}");
        if let Err(err) = result {
            assert!(
                err.to_string().contains("ALLOW_AUTO_CREATE_TOPICS=false"),
                "{err}"
            );
        }
    }

    #[rstest]
    #[case::idle_warn(Target::Fallback, false, CheckMode::Warn, OnCheckFailure::Warn)]
    #[case::idle_strict(Target::Fallback, false, CheckMode::Strict, OnCheckFailure::RefuseBoot)]
    #[case::armed_warn(Target::Fallback, true, CheckMode::Warn, OnCheckFailure::RefuseBoot)]
    #[case::armed_strict(Target::Fallback, true, CheckMode::Strict, OnCheckFailure::RefuseBoot)]
    #[case::idle_primary_warn(Target::Primary, true, CheckMode::Warn, OnCheckFailure::Warn)]
    #[case::idle_primary_strict(Target::Primary, true, CheckMode::Strict, OnCheckFailure::Warn)]
    fn check_failure_matrix(
        #[case] target: Target,
        #[case] armed: bool,
        #[case] check: CheckMode,
        #[case] expected: OnCheckFailure,
    ) {
        assert_eq!(
            on_check_failure(target, FallbackSettings { armed, check }),
            expected
        );
    }

    struct Missing<'a> {
        on_primary: &'a [&'a str],
        on_fallback: &'a [&'a str],
    }

    fn missing_on_fallback<'a>(topics: &'a [&'a str]) -> Missing<'a> {
        Missing {
            on_primary: &[],
            on_fallback: topics,
        }
    }

    async fn check(missing: Missing<'_>, armed: bool, check: CheckMode) -> anyhow::Result<()> {
        let cluster = |topics: &[&str]| {
            Arc::new(MockKafkaProducer::new().with_missing_topics(topics.iter().copied()))
        };
        let (primary_producer, fallback_producer) =
            (cluster(missing.on_primary), cluster(missing.on_fallback));
        let primary = test_outputs();
        let fallback = fallback_table(&primary, &FallbackOutputsConfig::default())
            .map_producers(|_| Arc::clone(&fallback_producer));
        let primary = primary.map_producers(|_| Arc::clone(&primary_producer));
        run_boot_checks(&primary, &fallback, FallbackSettings { armed, check }).await
    }

    #[rstest]
    #[case::idle_warn(false, CheckMode::Warn, true)]
    #[case::idle_strict(false, CheckMode::Strict, false)]
    #[case::armed_warn(true, CheckMode::Warn, false)]
    #[case::armed_strict(true, CheckMode::Strict, false)]
    #[tokio::test]
    async fn a_missing_fallback_topic_warns_or_refuses_boot(
        #[case] armed: bool,
        #[case] mode: CheckMode,
        #[case] boots: bool,
    ) {
        let result = check(missing_on_fallback(&["heatmaps"]), armed, mode).await;

        assert_eq!(result.is_ok(), boots, "{result:?}");
        if let Err(err) = result {
            let err = err.to_string();
            assert!(
                err.contains("fallback") && err.contains("\"heatmaps\""),
                "{err}"
            );
        }
    }

    #[rstest]
    #[case(false, CheckMode::Warn)]
    #[case(false, CheckMode::Strict)]
    #[case(true, CheckMode::Warn)]
    #[case(true, CheckMode::Strict)]
    #[tokio::test]
    async fn a_complete_fallback_passes_every_mode(#[case] armed: bool, #[case] mode: CheckMode) {
        check(missing_on_fallback(&[]), armed, mode).await.unwrap();
    }

    #[tokio::test]
    async fn a_missing_topic_on_the_idle_primary_does_not_block_the_switch() {
        let missing = Missing {
            on_primary: &["events_plugin_ingestion", "heatmaps"],
            on_fallback: &[],
        };

        check(missing, true, CheckMode::Strict).await.unwrap();
    }

    #[tokio::test]
    async fn the_topic_gauge_marks_only_the_failing_output() {
        let recorder = metrics_util::debugging::DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        check(missing_on_fallback(&["heatmaps"]), false, CheckMode::Warn)
            .await
            .unwrap();

        let mut not_ready: Vec<(String, f64)> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, ..)| key.key().name() == OUTPUT_TOPIC_READY)
            .map(|(key, _, _, value)| {
                let output = key
                    .key()
                    .labels()
                    .find(|label| label.key() == "topic")
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

        assert_eq!(not_ready, vec![("heatmaps".to_string(), 0.0)]);
    }
    struct RouteCase {
        address: Address,
        primary_topic: &'static str,
        fallback_topic: &'static str,
    }

    fn analytics_family_routes() -> Vec<RouteCase> {
        use crate::pipeline::{AiLane, AnalyticsLane, BasicLane, PipelineLane};
        let route = |address, primary_topic, fallback_topic| RouteCase {
            address,
            primary_topic,
            fallback_topic,
        };
        vec![
            route(
                Address::Lane(PipelineLane::Analytics(AnalyticsLane::Main)),
                "events_plugin_ingestion",
                "ws_events",
            ),
            route(
                Address::Lane(PipelineLane::Analytics(AnalyticsLane::Overflow)),
                "events_plugin_ingestion_overflow",
                "events_plugin_ingestion_overflow",
            ),
            route(
                Address::Lane(PipelineLane::Analytics(AnalyticsLane::Historical)),
                "events_plugin_ingestion_historical",
                "events_plugin_ingestion_historical",
            ),
            route(
                Address::Lane(PipelineLane::Heatmaps(BasicLane::Main)),
                "heatmaps",
                "heatmaps",
            ),
            route(
                Address::Lane(PipelineLane::Warnings(BasicLane::Main)),
                "client_ingestion_warning",
                "client_ingestion_warning",
            ),
            route(
                Address::Lane(PipelineLane::ErrorTracking(BasicLane::Main)),
                "error_tracking_events",
                "error_tracking_events",
            ),
            route(
                Address::Lane(PipelineLane::Ai(AiLane::Main)),
                "ai_events",
                "ws_ai",
            ),
            route(
                Address::Lane(PipelineLane::Ai(AiLane::Overflow)),
                "ai_events_overflow",
                "ai_events_overflow",
            ),
            route(Address::Dlq, "events_plugin_ingestion_dlq", "ws_dlq"),
            route(
                Address::Custom("admin_topic".to_string()),
                "admin_topic",
                "admin_topic",
            ),
        ]
    }

    #[rstest]
    #[case::normal(Target::Primary)]
    #[case::armed(Target::Fallback)]
    #[tokio::test]
    async fn every_address_publishes_to_the_live_targets_topic(#[case] live: Target) {
        let primary_table = test_outputs();
        let fallback_table = fallback_table(
            &primary_table,
            &fallback_config(&[
                ("CAPTURE_OUTPUT_ANALYTICS_MAIN_FALLBACK_TOPIC", "ws_events"),
                ("CAPTURE_OUTPUT_AI_MAIN_FALLBACK_TOPIC", "ws_ai"),
                ("CAPTURE_OUTPUT_DLQ_FALLBACK_TOPIC", "ws_dlq"),
            ]),
        );
        let (primary, fallback) = (MockKafkaProducer::new(), MockKafkaProducer::new());
        let output = Output::select(
            Output::single(KafkaSinkBase::with_producer(primary.clone(), primary_table)),
            Output::single(KafkaSinkBase::with_producer(
                fallback.clone(),
                fallback_table,
            )),
            live,
        );
        let cases = analytics_family_routes();
        let events = cases
            .iter()
            .map(|case| PreparedEvent {
                uuid: uuid::Uuid::now_v7(),
                address: case.address.clone(),
                partition_key: "token:user".to_string(),
                ordering: OrderingGuarantee::PerDistinctId,
                payload: bytes::Bytes::from_static(b"{}"),
                headers: common_types::CapturedEventHeaders {
                    token: Some("token".to_string()),
                    distinct_id: Some("user".to_string()),
                    session_id: None,
                    timestamp: None,
                    event: Some("event".to_string()),
                    uuid: None,
                    now: None,
                    force_disable_person_processing: None,
                    historical_migration: None,
                    skip_heatmap_processing: None,
                    dlq_reason: None,
                    dlq_step: None,
                    dlq_timestamp: None,
                    content_encoding: None,
                    legacy_property_splice: None,
                },
            })
            .collect();

        output.publish_prepared(events).await;

        let (live_producer, idle_producer) = match live {
            Target::Primary => (&primary, &fallback),
            Target::Fallback => (&fallback, &primary),
        };
        let topics: Vec<String> = live_producer
            .get_records()
            .iter()
            .map(|record| record.topic.to_string())
            .collect();
        let expected: Vec<&str> = cases
            .iter()
            .map(|case| match live {
                Target::Primary => case.primary_topic,
                Target::Fallback => case.fallback_topic,
            })
            .collect();
        assert_eq!(topics, expected);
        assert!(idle_producer.get_records().is_empty());
    }
}
