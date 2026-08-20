//! Emergency switch that repoints every Kafka producer in the process at a
//! backup cluster.
//!
//! Every deployment carries the backup connection settings dormant. Arming
//! [`TRIGGER_VAR`] swaps hosts and TLS on every producer destination at
//! config-resolution time, before anything is built. Topic names, acks,
//! retries, timeouts and client ids are untouched: the backup cluster carries
//! identically-named topics, so only the connection changes.

use std::collections::HashMap;

use metrics::gauge;
use tracing::error;

use crate::config::{Config, KafkaConfig};
use crate::v1::sinks::Sinks;

/// Arms the switch. Unset or empty means normal operation; any value other
/// than [`TRIGGER_VALUE`] refuses to boot.
pub const TRIGGER_VAR: &str = "CAPTURE_EMERGENCY_KAFKA_FALLBACK";

/// Comma-separated broker list of the backup cluster. Required while the
/// switch is armed, ignored otherwise.
pub const HOSTS_VAR: &str = "CAPTURE_EMERGENCY_BACKUP_KAFKA_HOSTS";

/// TLS for the backup cluster. Defaults to false.
pub const TLS_VAR: &str = "CAPTURE_EMERGENCY_BACKUP_KAFKA_TLS";

/// The one accepted value of [`TRIGGER_VAR`]. Deliberately not truthy, so no
/// stray "1"/"true"/"yes" can move a whole fleet's traffic by accident.
pub const TRIGGER_VALUE: &str = "FALLBACK-TO-BACKUP-KAFKA-NOW";

/// `1` while the fallback is active, `0` otherwise. Emitted either way, so a
/// dashboard can tell "on the primary cluster" from "pod not reporting".
pub const FALLBACK_ACTIVE: &str = "capture_emergency_kafka_fallback_active";

/// The backup cluster a resolved, armed switch points at.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmergencyKafkaFallback {
    pub hosts: String,
    pub tls: bool,
}

impl EmergencyKafkaFallback {
    /// Resolve the switch from an env snapshot. `Ok(None)` is the normal case;
    /// a set-but-wrong trigger, or an armed trigger with no backup hosts, is an
    /// error the caller must turn into a failed startup.
    ///
    /// The trigger is trimmed before matching: a value templated through YAML
    /// can pick up surrounding whitespace, and this switch gets thrown during
    /// an outage.
    pub fn from_env(env: &HashMap<String, String>) -> anyhow::Result<Option<Self>> {
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

    /// Repoint every producer destination `config` resolves, except the v1
    /// sinks, which parse their own env namespace later — see
    /// [`Self::apply_to_v1_sinks`].
    pub fn apply(&self, config: &mut Config) {
        self.apply_to_kafka(&mut config.kafka);
        config.capture_ingestion_warnings_kafka_hosts = self.hosts.clone();
        config.capture_ingestion_warnings_kafka_tls = self.tls;
    }

    /// The `KAFKA_*` block, shared with capture-logs: its traces and metrics
    /// producers read the per-cluster overrides, which are set here rather than
    /// cleared so they cannot inherit a primary-cluster value.
    pub fn apply_to_kafka(&self, kafka: &mut KafkaConfig) {
        kafka.kafka_hosts = self.hosts.clone();
        kafka.kafka_tls = self.tls;
        kafka.kafka_traces_hosts = Some(self.hosts.clone());
        kafka.kafka_traces_tls = Some(self.tls);
        kafka.kafka_metrics_hosts = Some(self.hosts.clone());
        kafka.kafka_metrics_tls = Some(self.tls);
    }

    /// The v1 sink configs, loaded from `CAPTURE_V1_SINK_*` after `Config`.
    pub fn apply_to_v1_sinks(&self, sinks: &mut Sinks) {
        for cfg in sinks.configs.values_mut() {
            cfg.kafka.hosts = self.hosts.clone();
            cfg.kafka.tls = self.tls;
        }
    }

    /// Log the failover at error level. Nothing here is wrong, but a process
    /// producing somewhere other than its configured cluster must be visible in
    /// any log view an operator already has open.
    pub fn log_active(&self) {
        error!(
            backup_kafka_hosts = self.hosts.as_str(),
            backup_kafka_tls = self.tls,
            "EMERGENCY KAFKA FALLBACK ACTIVE: every producer in this process is pointed at the \
             backup cluster. Unset {TRIGGER_VAR} and restart to return to the primary cluster."
        );
    }
}

/// Report the switch state. Call once the metrics recorder is installed.
pub fn report_fallback_gauge(active: bool) {
    gauge!(FALLBACK_ACTIVE).set(if active { 1.0 } else { 0.0 });
}

fn trimmed<'a>(env: &'a HashMap<String, String>, key: &str) -> &'a str {
    env.get(key).map(|v| v.trim()).unwrap_or("")
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;
    use crate::v1::sinks::{load_sinks_from, SinkName};

    const PRIMARY_HOSTS: &str = "primary-msk:9092";
    const BACKUP_HOSTS: &str = "backup-warpstream:9092,backup-warpstream-2:9092";

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    /// A config whose every producer destination points at the primary cluster,
    /// so a field the override misses stays visibly primary.
    fn primary_config() -> Config {
        let cfg_env = env(&[
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
        ]);
        envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config")
    }

    fn primary_v1_sinks() -> Sinks {
        let sink_env = env(&[
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
        ]);
        load_sinks_from("msk", &sink_env).expect("test sinks")
    }

    #[test]
    fn inactive_without_the_trigger() {
        assert_eq!(EmergencyKafkaFallback::from_env(&env(&[])).unwrap(), None);
        assert_eq!(
            EmergencyKafkaFallback::from_env(&env(&[
                (TRIGGER_VAR, ""),
                (HOSTS_VAR, BACKUP_HOSTS),
                (TLS_VAR, "true"),
            ]))
            .unwrap(),
            None,
            "dormant backup settings alone must never repoint anything"
        );
    }

    #[test]
    fn the_magic_value_repoints_every_producer_destination() {
        let fallback = EmergencyKafkaFallback::from_env(&env(&[
            (TRIGGER_VAR, TRIGGER_VALUE),
            (HOSTS_VAR, BACKUP_HOSTS),
        ]))
        .unwrap()
        .expect("the magic value must arm the switch");

        let mut config = primary_config();
        fallback.apply(&mut config);
        let mut sinks = primary_v1_sinks();
        fallback.apply_to_v1_sinks(&mut sinks);

        assert_eq!(config.kafka.kafka_hosts, BACKUP_HOSTS);
        assert!(!config.kafka.kafka_tls);
        assert_eq!(
            config.kafka.kafka_traces_hosts.as_deref(),
            Some(BACKUP_HOSTS)
        );
        assert_eq!(config.kafka.kafka_traces_tls, Some(false));
        assert_eq!(
            config.kafka.kafka_metrics_hosts.as_deref(),
            Some(BACKUP_HOSTS)
        );
        assert_eq!(config.kafka.kafka_metrics_tls, Some(false));
        assert_eq!(config.capture_ingestion_warnings_kafka_hosts, BACKUP_HOSTS);
        assert!(!config.capture_ingestion_warnings_kafka_tls);

        let sink = &sinks.configs[&SinkName::Msk];
        assert_eq!(sink.kafka.hosts, BACKUP_HOSTS);
        assert!(!sink.kafka.tls);

        // Everything that is not a connection setting stays as configured: the
        // backup cluster carries identically-named topics.
        assert_eq!(config.kafka.kafka_topic, "events_plugin_ingestion");
        assert_eq!(sink.kafka.topic_main, "events_main");
        assert_eq!(sink.kafka.acks, "all");
    }

    #[test]
    fn backup_tls_is_honored_and_defaults_off() {
        let with_tls = EmergencyKafkaFallback::from_env(&env(&[
            (TRIGGER_VAR, TRIGGER_VALUE),
            (HOSTS_VAR, BACKUP_HOSTS),
            (TLS_VAR, "true"),
        ]))
        .unwrap()
        .unwrap();
        assert!(with_tls.tls);

        let without_tls = EmergencyKafkaFallback::from_env(&env(&[
            (TRIGGER_VAR, TRIGGER_VALUE),
            (HOSTS_VAR, BACKUP_HOSTS),
        ]))
        .unwrap()
        .unwrap();
        assert!(!without_tls.tls);
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
        let err = EmergencyKafkaFallback::from_env(&env(&[
            (TRIGGER_VAR, value),
            (HOSTS_VAR, BACKUP_HOSTS),
        ]))
        .expect_err("a value other than the magic one must fail startup");
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
        let mut vars = vec![(TRIGGER_VAR, TRIGGER_VALUE)];
        if let Some(hosts) = hosts {
            vars.push((HOSTS_VAR, hosts));
        }

        let err = EmergencyKafkaFallback::from_env(&env(&vars))
            .expect_err("an armed switch with no backup brokers must fail startup");
        assert!(
            err.to_string().contains(HOSTS_VAR),
            "error must name the missing var: {err}"
        );
    }

    #[test]
    fn an_unparseable_backup_tls_refuses_to_boot() {
        let err = EmergencyKafkaFallback::from_env(&env(&[
            (TRIGGER_VAR, TRIGGER_VALUE),
            (HOSTS_VAR, BACKUP_HOSTS),
            (TLS_VAR, "yes"),
        ]))
        .expect_err("a non-boolean TLS value must fail startup");
        assert!(
            err.to_string().contains(TLS_VAR),
            "error must name the var: {err}"
        );
    }
}
