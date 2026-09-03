//! Turns the process environment into the configuration capture runs on.
//!
//! Everything that rewrites config after parsing happens here, and nothing
//! downstream re-reads the environment. That is what makes the emergency Kafka
//! fallback total: [`resolve`] is the only way to obtain a [`Config`] or a set
//! of v1 sink configs, so a producer built from them cannot be pointed at the
//! primary cluster while the switch is armed.
//!
//! The switch itself is [`TRIGGER_VAR`]. The deployment carries the backup
//! connection settings dormant; arming the trigger swaps hosts and TLS on the
//! analytics event destinations. Topic names, acks, retries, timeouts and
//! client ids are untouched, because the backup cluster carries
//! identically-named topics and only the connection changes.
//!
//! Scoped to the analytics event path. The traces and metrics producers, which
//! only capture-logs builds, keep their configured cluster.

use std::collections::HashMap;

use anyhow::Context;
use envconfig::Envconfig;
use metrics::gauge;
use tracing::error;

use crate::config::Config;
use crate::v1::sinks::{load_sinks_from, Sinks};

/// Arms the switch. Unset or empty means normal operation; any value other
/// than [`TRIGGER_VALUE`] refuses to boot.
pub const TRIGGER_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_FALLBACK";

/// Comma-separated broker list of the backup cluster. Required while the
/// switch is armed, ignored otherwise.
pub const HOSTS_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_BACKUP_HOSTS";

/// TLS for the backup cluster. Defaults to false.
pub const TLS_VAR: &str = "CAPTURE_ANALYTICS_KAFKA_EMERGENCY_BACKUP_TLS";

/// The one accepted value of [`TRIGGER_VAR`]. Deliberately not truthy, so no
/// stray "1"/"true"/"yes" can move a whole fleet's traffic by accident.
pub const TRIGGER_VALUE: &str = "FALLBACK-TO-BACKUP-KAFKA-NOW";

/// `1` while the fallback is active, `0` otherwise. Emitted either way, so a
/// dashboard can tell "on the primary cluster" from "pod not reporting".
pub const FALLBACK_ACTIVE: &str = "capture_emergency_kafka_fallback_active";

/// Finished startup configuration. Every rewrite has already been applied and
/// the v1 sink configs have been validated, so callers only construct
/// producers from what is in here.
#[derive(Debug)]
pub struct Resolved {
    config: Config,
    v1_sinks: Option<Sinks>,
    emergency_fallback: Option<EmergencyKafkaFallback>,
}

impl Resolved {
    pub fn config(&self) -> &Config {
        &self.config
    }

    pub fn emergency_fallback_active(&self) -> bool {
        self.emergency_fallback.is_some()
    }

    /// Announce the switch state. Call once the metrics recorder is installed,
    /// or the gauge is dropped.
    pub fn report_emergency_fallback(&self) {
        if let Some(fallback) = &self.emergency_fallback {
            fallback.log_active();
        }
        gauge!(FALLBACK_ACTIVE).set(if self.emergency_fallback.is_some() {
            1.0
        } else {
            0.0
        });
    }

    pub fn into_parts(self) -> (Config, Option<Sinks>) {
        (self.config, self.v1_sinks)
    }
}

/// Parse `env` into the configuration capture will run on.
///
/// Both parses read the same snapshot: the deployment-level [`Config`] and,
/// when `CAPTURE_V1_SINKS` names any, the per-sink configs from their own
/// `CAPTURE_V1_SINK_*` namespace. The emergency fallback and the
/// deployment-level AI topics are applied to both before the sinks are
/// validated, so validation runs against the cluster and topics the sinks will
/// really produce to.
pub fn resolve(env: &HashMap<String, String>) -> anyhow::Result<Resolved> {
    let config =
        Config::init_from_hashmap(env).map_err(|e| anyhow::anyhow!("invalid config: {e}"))?;
    resolve_parsed(config, env)
}

/// Resolve around a `Config` built in code rather than parsed from `env`.
///
/// Only the test harness needs this, and the `test-utils` feature keeps it out
/// of the binary: in production [`resolve`] stays the single way to obtain a
/// `Resolved`, so no caller can hand `build_components` a config that skipped
/// the fallback.
#[cfg(feature = "test-utils")]
pub fn resolve_with_config(
    config: Config,
    env: &HashMap<String, String>,
) -> anyhow::Result<Resolved> {
    resolve_parsed(config, env)
}

fn resolve_parsed(mut config: Config, env: &HashMap<String, String>) -> anyhow::Result<Resolved> {
    let emergency_fallback = EmergencyKafkaFallback::from_env(env)?;
    if let Some(fallback) = &emergency_fallback {
        fallback.apply(&mut config);
    }

    let v1_sinks = if config.capture_v1_sinks.is_empty() {
        None
    } else {
        let mut sinks = load_sinks_from(&config.capture_v1_sinks, env)
            .context("failed to parse CAPTURE_V1_SINKS")?;

        if let Some(fallback) = &emergency_fallback {
            fallback.apply_to_v1_sinks(&mut sinks);
        }

        // The dedicated AI topics are deployment-level config, so they are
        // injected into every sink here. The overwrite is unconditional so a
        // stray per-sink `TOPIC_AI`/`TOPIC_AI_OVERFLOW` env var cannot diverge
        // from the shared policy.
        for cfg in sinks.configs.values_mut() {
            cfg.kafka.topic_ai = config.kafka.capture_analytics_ai_events_topic.clone();
            cfg.kafka.topic_ai_overflow = config
                .kafka
                .capture_analytics_ai_events_overflow_topic
                .clone();
        }

        sinks
            .validate()
            .context("v1 sink config validation failed")?;
        Some(sinks)
    };

    Ok(Resolved {
        config,
        v1_sinks,
        emergency_fallback,
    })
}

/// The backup cluster an armed switch points at. Private to this module: once
/// [`resolve`] has returned, the rewrite has happened and nothing else may
/// apply one.
#[derive(Debug, Clone, PartialEq, Eq)]
struct EmergencyKafkaFallback {
    hosts: String,
    tls: bool,
}

impl EmergencyKafkaFallback {
    /// `Ok(None)` is the normal case. A set-but-wrong trigger, or an armed
    /// trigger with no backup hosts, is an error the caller must turn into a
    /// failed startup.
    ///
    /// The trigger is trimmed before matching: a value templated through YAML
    /// can pick up surrounding whitespace, and this switch gets thrown during
    /// an outage.
    fn from_env(env: &HashMap<String, String>) -> anyhow::Result<Option<Self>> {
        let trigger = trimmed(env, TRIGGER_VAR);
        if trigger.is_empty() {
            return Ok(None);
        }
        anyhow::ensure!(
            trigger == TRIGGER_VALUE,
            "{TRIGGER_VAR} accepts only {TRIGGER_VALUE:?} (or unset/empty for normal operation), \
             got {trigger:?}"
        );

        let hosts = trimmed(env, HOSTS_VAR);
        anyhow::ensure!(
            !hosts.is_empty(),
            "{TRIGGER_VAR} is armed but {HOSTS_VAR} is empty; there is no backup cluster to \
             produce to"
        );

        let tls = match trimmed(env, TLS_VAR) {
            "" => false,
            raw => raw.parse::<bool>().map_err(|_| {
                anyhow::anyhow!("{TLS_VAR} must be \"true\" or \"false\", got {raw:?}")
            })?,
        };

        Ok(Some(Self {
            hosts: hosts.to_string(),
            tls,
        }))
    }

    /// Repoint the v0 event sink and the ingestion warnings emitter.
    ///
    /// The traces and metrics cluster overrides are deliberately left alone:
    /// only capture-logs builds those producers, and the switch does not reach
    /// that deployment.
    fn apply(&self, config: &mut Config) {
        config.kafka.kafka_hosts = self.hosts.clone();
        config.kafka.kafka_tls = self.tls;
        config.capture_ingestion_warnings_kafka_hosts = self.hosts.clone();
        config.capture_ingestion_warnings_kafka_tls = self.tls;
    }

    fn apply_to_v1_sinks(&self, sinks: &mut Sinks) {
        for cfg in sinks.configs.values_mut() {
            cfg.kafka.hosts = self.hosts.clone();
            cfg.kafka.tls = self.tls;
        }
    }

    /// Log the failover at error level. Nothing here is wrong, but a process
    /// producing somewhere other than its configured cluster must be visible in
    /// any log view an operator already has open.
    fn log_active(&self) {
        error!(
            backup_kafka_hosts = self.hosts.as_str(),
            backup_kafka_tls = self.tls,
            "EMERGENCY KAFKA FALLBACK ACTIVE: every event producer in this process is pointed at \
             the backup cluster. Unset {TRIGGER_VAR} and restart to return to the primary cluster."
        );
    }
}

fn trimmed<'a>(env: &'a HashMap<String, String>, key: &str) -> &'a str {
    env.get(key).map(|v| v.trim()).unwrap_or("")
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;
    use crate::v1::sinks::SinkName;

    const PRIMARY_HOSTS: &str = "primary.invalid:9092";
    const BACKUP_HOSTS: &str = "backup.invalid:9092,backup-2.invalid:9092";

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    /// An env whose every connection setting points at the primary cluster, so
    /// a field the fallback misses stays visibly primary. Includes a v1 sink,
    /// because those parse from their own namespace.
    fn primary_env() -> HashMap<String, String> {
        env(&[
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", PRIMARY_HOSTS),
            ("KAFKA_TLS", "true"),
            ("KAFKA_TRACES_HOSTS", PRIMARY_HOSTS),
            ("KAFKA_TRACES_TLS", "true"),
            ("KAFKA_METRICS_HOSTS", PRIMARY_HOSTS),
            ("KAFKA_METRICS_TLS", "true"),
            ("CAPTURE_INGESTION_WARNINGS_KAFKA_HOSTS", PRIMARY_HOSTS),
            ("CAPTURE_INGESTION_WARNINGS_KAFKA_TLS", "true"),
            ("CAPTURE_V1_SINKS", "msk"),
            ("CAPTURE_V1_SINK_MSK_KAFKA_HOSTS", PRIMARY_HOSTS),
            ("CAPTURE_V1_SINK_MSK_KAFKA_TLS", "true"),
            ("CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_MAIN", "events_main"),
            ("CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_HISTORICAL", "events_hist"),
            (
                "CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_OVERFLOW",
                "events_overflow",
            ),
            ("CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_DLQ", "events_dlq"),
            (
                "CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_EXCEPTION",
                "error_tracking_events",
            ),
            (
                "CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_HEATMAP",
                "heatmaps_ingestion",
            ),
            (
                "CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_CLIENT_INGESTION_WARNING",
                "client_ingestion_warning",
            ),
        ])
    }

    fn armed_env() -> HashMap<String, String> {
        let mut env = primary_env();
        env.insert(TRIGGER_VAR.to_string(), TRIGGER_VALUE.to_string());
        env.insert(HOSTS_VAR.to_string(), BACKUP_HOSTS.to_string());
        env
    }

    #[test]
    fn dormant_backup_settings_change_nothing() {
        let mut env = primary_env();
        env.insert(HOSTS_VAR.to_string(), BACKUP_HOSTS.to_string());
        env.insert(TLS_VAR.to_string(), "true".to_string());

        let resolved = resolve(&env).unwrap();

        assert!(!resolved.emergency_fallback_active());
        assert_eq!(resolved.config().kafka.kafka_hosts, PRIMARY_HOSTS);
        let (_, sinks) = resolved.into_parts();
        assert_eq!(
            sinks.unwrap().configs[&SinkName::Msk].kafka.hosts,
            PRIMARY_HOSTS
        );
    }

    #[test]
    fn the_magic_value_repoints_every_event_producer() {
        let resolved = resolve(&armed_env()).unwrap();
        assert!(resolved.emergency_fallback_active());

        let (config, sinks) = resolved.into_parts();
        assert_eq!(config.kafka.kafka_hosts, BACKUP_HOSTS);
        assert!(!config.kafka.kafka_tls);
        assert_eq!(config.capture_ingestion_warnings_kafka_hosts, BACKUP_HOSTS);
        assert!(!config.capture_ingestion_warnings_kafka_tls);

        let sink = &sinks.unwrap().configs[&SinkName::Msk];
        assert_eq!(sink.kafka.hosts, BACKUP_HOSTS);
        assert!(!sink.kafka.tls);

        // Everything that is not a connection setting stays as configured: the
        // backup cluster carries identically-named topics.
        assert_eq!(config.kafka.kafka_topic, "events_plugin_ingestion");
        assert_eq!(sink.kafka.topic_main, "events_main");
        assert_eq!(sink.kafka.acks, "all");
    }

    /// Only capture-logs builds the traces and metrics producers, and the
    /// switch does not reach that deployment. Repointing them here would move
    /// nothing while implying otherwise.
    #[test]
    fn traces_and_metrics_clusters_are_left_alone() {
        let (config, _) = resolve(&armed_env()).unwrap().into_parts();

        assert_eq!(
            config.kafka.kafka_traces_hosts.as_deref(),
            Some(PRIMARY_HOSTS)
        );
        assert_eq!(config.kafka.kafka_traces_tls, Some(true));
        assert_eq!(
            config.kafka.kafka_metrics_hosts.as_deref(),
            Some(PRIMARY_HOSTS)
        );
        assert_eq!(config.kafka.kafka_metrics_tls, Some(true));
    }

    /// The structural guard: format the entire resolved output and require the
    /// primary host to survive only where it is meant to. A future connection
    /// field that resolution forgets to rewrite fails here without anyone
    /// having to remember to extend this test.
    #[test]
    fn no_primary_host_survives_the_failover() {
        let mut rendered = format!("{:?}", resolve(&armed_env()).unwrap());

        // The traces and metrics clusters are the two documented exceptions.
        // Removing them first means any other surviving mention is a real leak.
        for allowed in [
            format!("kafka_traces_hosts: Some({PRIMARY_HOSTS:?})"),
            format!("kafka_metrics_hosts: Some({PRIMARY_HOSTS:?})"),
        ] {
            assert!(
                rendered.contains(&allowed),
                "expected the traces/metrics exception {allowed} in {rendered}"
            );
            rendered = rendered.replace(&allowed, "");
        }

        assert!(
            !rendered.contains(PRIMARY_HOSTS),
            "a destination still points at the primary cluster after failover: {rendered}"
        );
    }

    /// The Debug output the guard above scans must never carry a credential.
    #[test]
    fn debug_output_redacts_the_signing_secret() {
        let mut env = primary_env();
        env.insert(
            "AI_GATEWAY_SIGNING_SECRET".to_string(),
            "super-secret-hmac-key".to_string(),
        );

        let (config, _) = resolve(&env).unwrap().into_parts();

        assert_eq!(
            config
                .ai_gateway_signing_secret
                .as_ref()
                .map(|s| s.expose()),
            Some("super-secret-hmac-key"),
            "the value must still reach the code that verifies signatures"
        );
        let rendered = format!("{config:?}");
        assert!(
            !rendered.contains("super-secret-hmac-key"),
            "the signing secret leaked into Debug output: {rendered}"
        );
    }

    #[test]
    fn backup_tls_is_honored_and_defaults_off() {
        let mut env = armed_env();
        env.insert(TLS_VAR.to_string(), "true".to_string());
        let (config, _) = resolve(&env).unwrap().into_parts();
        assert!(config.kafka.kafka_tls);

        let (config, _) = resolve(&armed_env()).unwrap().into_parts();
        assert!(!config.kafka.kafka_tls);
    }

    /// A typo must be loud. Silently ignoring it would leave an operator
    /// believing a failover happened while capture keeps producing to a dead
    /// cluster.
    #[rstest]
    #[case::truthy("true")]
    #[case::one("1")]
    #[case::lowercase("fallback-to-backup-kafka-now")]
    #[case::typo("FALLBACK-TO-BACKUP-KAFKA")]
    #[case::suffixed("FALLBACK-TO-BACKUP-KAFKA-NOW!")]
    fn a_wrong_trigger_value_refuses_to_boot(#[case] value: &str) {
        let mut env = primary_env();
        env.insert(TRIGGER_VAR.to_string(), value.to_string());
        env.insert(HOSTS_VAR.to_string(), BACKUP_HOSTS.to_string());

        let err = resolve(&env).expect_err("a value other than the magic one must fail startup");
        let msg = err.to_string();
        assert!(msg.contains(TRIGGER_VAR), "error must name the var: {msg}");
        assert!(
            msg.contains(TRIGGER_VALUE),
            "error must name the accepted value: {msg}"
        );
    }

    #[rstest]
    #[case::unset(None)]
    #[case::empty(Some(""))]
    #[case::whitespace(Some("  "))]
    fn an_armed_switch_without_backup_hosts_refuses_to_boot(#[case] hosts: Option<&str>) {
        let mut env = primary_env();
        env.insert(TRIGGER_VAR.to_string(), TRIGGER_VALUE.to_string());
        if let Some(hosts) = hosts {
            env.insert(HOSTS_VAR.to_string(), hosts.to_string());
        }

        let err =
            resolve(&env).expect_err("an armed switch with no backup brokers must fail startup");
        assert!(
            err.to_string().contains(HOSTS_VAR),
            "error must name the missing var: {err}"
        );
    }

    #[test]
    fn an_unparseable_backup_tls_refuses_to_boot() {
        let mut env = armed_env();
        env.insert(TLS_VAR.to_string(), "yes".to_string());

        let err = resolve(&env).expect_err("a non-boolean TLS value must fail startup");
        assert!(
            err.to_string().contains(TLS_VAR),
            "error must name the var: {err}"
        );
    }

    /// Sink parsing and validation both run inside `resolve`, so a broken sink
    /// cannot reach a producer regardless of which caller loaded it.
    #[rstest]
    #[case::invalid_knob("CAPTURE_V1_SINK_MSK_KAFKA_ACKS", Some("banana"), "acks")]
    #[case::missing_hosts("CAPTURE_V1_SINK_MSK_KAFKA_HOSTS", None, "msk")]
    fn a_broken_sink_fails_resolution(
        #[case] key: &str,
        #[case] value: Option<&str>,
        #[case] expected: &str,
    ) {
        let mut env = primary_env();
        match value {
            Some(value) => env.insert(key.to_string(), value.to_string()),
            None => env.remove(key),
        };

        let err = resolve(&env).expect_err("a broken sink must fail startup");
        let msg = format!("{err:#}");
        assert!(
            msg.contains(expected),
            "error should name {expected}: {msg}"
        );
    }

    /// The AI topics are deployment-level, so a per-sink override of them must
    /// lose to the deployment value rather than split the lane across topics.
    #[test]
    fn deployment_ai_topics_overwrite_per_sink_values() {
        let mut env = primary_env();
        env.insert(
            "CAPTURE_ANALYTICS_AI_EVENTS_TOPIC".to_string(),
            "deployment_ai".into(),
        );
        env.insert(
            "CAPTURE_V1_SINK_MSK_KAFKA_TOPIC_AI".to_string(),
            "stray_per_sink_ai".into(),
        );

        let (_, sinks) = resolve(&env).unwrap().into_parts();

        assert_eq!(
            sinks.unwrap().configs[&SinkName::Msk].kafka.topic_ai,
            "deployment_ai"
        );
    }

    #[test]
    fn no_v1_sinks_configured_resolves_to_none() {
        let mut env = primary_env();
        env.remove("CAPTURE_V1_SINKS");

        let (_, sinks) = resolve(&env).unwrap().into_parts();
        assert!(sinks.is_none());
    }
}
