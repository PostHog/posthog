use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping;
use metrics::gauge;

use crate::row::{KafkaRowWarningEmitter, RowWarningEmitter};
use crate::throttle::{WarningThrottle, DEFAULT_MAX_TRACKED_KEYS};
use crate::{observe_delivery, INGESTION_WARNINGS_EMITTER_ENABLED};

pub const DEFAULT_TYPE_BUDGET_PER_MINUTE: NonZeroU32 = NonZeroU32::new(60).unwrap();
/// Default for `INGESTION_WARNINGS_MAX_TRACKED_SCOPES`. Row scopes can be per
/// distinct id, so the throttle default (sized for capture's per-token keys)
/// would fill within the hour a key lives and silence every team on the pod.
/// The type budgets admit well under this many keys an hour.
pub const DEFAULT_MAX_TRACKED_SCOPES: usize = 1_000_000;
const _: () = assert!(DEFAULT_MAX_TRACKED_SCOPES > DEFAULT_MAX_TRACKED_KEYS);
const THROTTLE_SWEEP_INTERVAL: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RowWarningsSettings {
    pub enabled: bool,
    pub kafka_hosts: String,
    pub kafka_tls: bool,
    pub topic: String,
    pub kafka_queue_mib: u32,
    pub kafka_message_max_bytes: u32,
    pub kafka_acks: String,
    pub kafka_retries: u32,
    pub kafka_linger_ms: u32,
    pub kafka_queue_messages: u32,
    pub kafka_message_timeout_ms: u32,
    pub type_budget_per_minute: NonZeroU32,
    pub max_tracked_scopes: usize,
}

impl RowWarningsSettings {
    pub fn kafka_config(&self, client_id: &str) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_id: client_id.to_string(),
            kafka_producer_acks: Some(self.kafka_acks.clone()),
            kafka_producer_retries: Some(self.kafka_retries),
            kafka_producer_linger_ms: self.kafka_linger_ms,
            kafka_producer_queue_messages: self.kafka_queue_messages,
            kafka_message_timeout_ms: self.kafka_message_timeout_ms,
            kafka_producer_queue_mib: self.kafka_queue_mib,
            kafka_producer_message_max_bytes: Some(self.kafka_message_max_bytes),
            ..Default::default()
        }
    }

    pub fn disabled_reason(&self) -> Option<&'static str> {
        if !self.enabled {
            return Some("disabled");
        }
        if self.kafka_hosts.is_empty() {
            return Some("hosts_unset");
        }
        if self.topic.is_empty() {
            return Some("topic_unset");
        }
        None
    }

    fn throttle(&self) -> WarningThrottle {
        WarningThrottle::default()
            .with_max_tracked_keys(self.max_tracked_scopes)
            .with_type_budget(
                Duration::from_secs(60) / self.type_budget_per_minute.get(),
                self.type_budget_per_minute,
            )
    }
}

fn report_emitter_enabled(reason: &'static str, enabled: bool) {
    gauge!(INGESTION_WARNINGS_EMITTER_ENABLED, "reason" => reason).set(if enabled {
        1.0
    } else {
        0.0
    });
}

/// Register `handle` as advisory: the producer's stats callback is its only liveness signal.
pub fn install_row_emitter(
    settings: &RowWarningsSettings,
    client_id: &str,
    handle: Option<lifecycle::Handle>,
) -> Option<Arc<dyn RowWarningEmitter>> {
    if !settings.enabled {
        return None;
    }
    if let Some(reason) = settings.disabled_reason() {
        tracing::warn!(
            reason,
            "ingestion warnings enabled but unusable; emitter disabled"
        );
        report_emitter_enabled(reason, false);
        return None;
    }
    let Some(handle) = handle else {
        tracing::warn!(
            "ingestion warnings enabled but no lifecycle handle was registered; emitter disabled"
        );
        report_emitter_enabled("no_handle", false);
        return None;
    };
    let producer = match create_threaded_kafka_producer_no_ping(
        &settings.kafka_config(client_id),
        handle.clone(),
        observe_delivery,
    ) {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(error = %e, "failed to create ingestion warnings producer; emitter disabled");
            report_emitter_enabled("producer_create_failed", false);
            return None;
        }
    };
    if settings.max_tracked_scopes <= DEFAULT_MAX_TRACKED_KEYS {
        tracing::warn!(
            max_tracked_scopes = settings.max_tracked_scopes,
            "ingestion warnings scope cap is at or below the per-token default; a busy pod can fill it within the hour and drop every team's warnings"
        );
    }
    let emitter = Arc::new(KafkaRowWarningEmitter::with_throttle(
        producer,
        settings.topic.clone(),
        settings.throttle(),
    ));

    // Liveness comes from the producer's stats callback alone, so a wedged
    // poll thread trips the deadline; a heartbeat here would mask it.
    let background = emitter.clone();
    tokio::spawn(async move {
        let mut sweep = tokio::time::interval(THROTTLE_SWEEP_INTERVAL);
        loop {
            tokio::select! {
                _ = sweep.tick() => background.sweep_throttle(),
                _ = handle.shutdown_recv() => break,
            }
        }
    });

    report_emitter_enabled("ok", true);
    tracing::info!(
        topic = settings.topic.as_str(),
        "ingestion warnings emitter enabled"
    );
    Some(emitter)
}

#[cfg(test)]
mod tests {
    use std::time::Instant;

    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use rstest::rstest;

    use super::*;
    use crate::row::throttle_key;
    use crate::throttle::ThrottleDecision;
    use crate::WarningType;

    const CLIENT_ID: &str = "row-install-test";

    fn settings(enabled: bool, hosts: &str, topic: &str) -> RowWarningsSettings {
        RowWarningsSettings {
            enabled,
            kafka_hosts: hosts.to_string(),
            kafka_tls: false,
            topic: topic.to_string(),
            kafka_queue_mib: 16,
            kafka_message_max_bytes: 1_048_576,
            kafka_acks: "1".to_string(),
            kafka_retries: 0,
            kafka_linger_ms: 100,
            kafka_queue_messages: 10_000,
            kafka_message_timeout_ms: 5_000,
            type_budget_per_minute: DEFAULT_TYPE_BUDGET_PER_MINUTE,
            max_tracked_scopes: DEFAULT_MAX_TRACKED_SCOPES,
        }
    }

    #[rstest]
    #[case::off(false, "broker:9092", "topic", Some("disabled"))]
    #[case::no_hosts(true, "", "topic", Some("hosts_unset"))]
    #[case::no_topic(true, "broker:9092", "", Some("topic_unset"))]
    #[case::usable(true, "broker:9092", "topic", None)]
    fn unusable_settings_name_their_reason(
        #[case] enabled: bool,
        #[case] hosts: &str,
        #[case] topic: &str,
        #[case] expected: Option<&'static str>,
    ) {
        assert_eq!(settings(enabled, hosts, topic).disabled_reason(), expected);
    }

    #[test]
    fn the_producer_config_carries_every_setting_and_stays_isolated() {
        let config = RowWarningsSettings {
            kafka_acks: "all".to_string(),
            kafka_retries: 2,
            kafka_linger_ms: 250,
            kafka_queue_messages: 500,
            kafka_message_timeout_ms: 9_000,
            ..settings(true, "broker:9092", "topic")
        }
        .kafka_config(CLIENT_ID);
        assert_eq!(config.kafka_hosts, "broker:9092");
        assert_eq!(config.kafka_client_id, CLIENT_ID);
        assert_eq!(config.kafka_producer_acks.as_deref(), Some("all"));
        assert_eq!(config.kafka_producer_retries, Some(2));
        assert_eq!(config.kafka_producer_linger_ms, 250);
        assert_eq!(config.kafka_producer_queue_messages, 500);
        assert_eq!(config.kafka_message_timeout_ms, 9_000);
        assert_eq!(config.kafka_producer_queue_mib, 16);
        assert_eq!(config.kafka_producer_message_max_bytes, Some(1_048_576));
        assert!(config.kafka_producer_enable_idempotence.is_none());
        assert!(config.kafka_producer_batch_size.is_none());
    }

    #[rstest]
    #[case::hosts_unset("", "hosts_unset")]
    #[case::no_handle("broker:9092", "no_handle")]
    fn an_unusable_install_reports_its_reason_on_the_gauge(
        #[case] hosts: &str,
        #[case] reason: &str,
    ) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let emitter = metrics::with_local_recorder(&recorder, || {
            install_row_emitter(&settings(true, hosts, "topic"), CLIENT_ID, None)
        });
        assert!(emitter.is_none());
        let gauges: Vec<(String, f64)> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, _)| key.key().name() == INGESTION_WARNINGS_EMITTER_ENABLED)
            .map(|(key, _, _, value)| {
                let reason = key
                    .key()
                    .labels()
                    .find(|label| label.key() == "reason")
                    .expect("reason label")
                    .value()
                    .to_string();
                let DebugValue::Gauge(value) = value else {
                    panic!("emitter enabled is a gauge");
                };
                (reason, value.into_inner())
            })
            .collect();
        assert_eq!(gauges, vec![(reason.to_string(), 0.0)]);
    }

    #[test]
    fn the_throttle_tracks_only_admitted_scopes_and_caps_above_the_shared_default() {
        let throttle = settings(true, "broker:9092", "topic").throttle();
        let warning = WarningType::CannotMergeAlreadyIdentified;
        let mut admitted = 0;
        for n in 0..=DEFAULT_MAX_TRACKED_KEYS {
            match throttle.check(&throttle_key(7, &n.to_string()), warning) {
                ThrottleDecision::Emit => admitted += 1,
                ThrottleDecision::TypeBudgetExhausted => {}
                other => panic!("scope {n}: {other:?}"),
            }
        }
        assert!(admitted >= DEFAULT_TYPE_BUDGET_PER_MINUTE.get() as usize);
        assert_eq!(
            throttle.tracked_keys(),
            admitted,
            "a scope the budget refused must not hold a key"
        );
    }

    #[test]
    fn the_throttle_takes_its_budget_and_cap_from_settings() {
        let throttle = RowWarningsSettings {
            type_budget_per_minute: NonZeroU32::new(2).unwrap(),
            max_tracked_scopes: 3,
            ..settings(true, "broker:9092", "topic")
        }
        .throttle();
        let warning = WarningType::CannotMergeAlreadyIdentified;
        assert_eq!(
            throttle.check(&throttle_key(7, "a"), warning),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check(&throttle_key(7, "b"), warning),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check(&throttle_key(7, "c"), warning),
            ThrottleDecision::TypeBudgetExhausted
        );
        let later = Instant::now() + Duration::from_secs(31);
        assert_eq!(
            throttle.check_at(&throttle_key(7, "c"), warning, later),
            ThrottleDecision::Emit
        );
        assert_eq!(
            throttle.check(&throttle_key(7, "d"), warning),
            ThrottleDecision::CardinalityCapped
        );
    }

    #[test]
    fn the_type_budget_refills_at_the_stated_rate() {
        let throttle = settings(true, "broker:9092", "topic").throttle();
        let warning = WarningType::MergeRaceCondition;
        for n in 0..DEFAULT_TYPE_BUDGET_PER_MINUTE.get() {
            assert_eq!(
                throttle.check(&throttle_key(7, &n.to_string()), warning),
                ThrottleDecision::Emit,
                "scope {n}"
            );
        }
        assert_eq!(
            throttle.check(&throttle_key(7, "over"), warning),
            ThrottleDecision::TypeBudgetExhausted
        );
        let soon = Instant::now() + Duration::from_millis(500);
        assert_eq!(
            throttle.check_at(&throttle_key(7, "soon"), warning, soon),
            ThrottleDecision::TypeBudgetExhausted
        );
        let later = Instant::now() + Duration::from_millis(1100);
        assert_eq!(
            throttle.check_at(&throttle_key(7, "later"), warning, later),
            ThrottleDecision::Emit
        );
    }
}
