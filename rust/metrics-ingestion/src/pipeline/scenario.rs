//! Mirrors `nodejs/src/ingestion/pipelines/metrics/parity/parity-harness.ts`. The parity test and the service tests use it.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use ingestion_framework::{IngestionOutputs, OutputMessage, PipelineError};
use logs_ingestion::js::{JsObject, JsValue};
use logs_ingestion::pipeline::errors::ERR_MSG_SIZE_TOO_LARGE;
use logs_ingestion::pipeline::{
    DependencyUnavailableError, KafkaProduceError, NamedError, QuotaLimiting, Team, TeamManager,
    UsageRecordBatch,
};
use logs_ingestion::rate_limiter::{Clock, KeyRoot, TokenBucketRedis};

use super::config::{MetricsLimiterConfig, AGGREGATION_TEAMS_KEY};
use super::consumer::{MetricsPipelineConsumer, MetricsPipelineConsumerDeps};
use super::unknown_tokens::UnknownTokens;

fn get<'a>(v: &'a JsValue, key: &str) -> Option<&'a JsValue> {
    match v {
        JsValue::Object(o) => o.get(key),
        _ => None,
    }
}

fn s(v: Option<&JsValue>) -> Option<String> {
    match v {
        Some(JsValue::String(s)) => Some(s.to_utf8_lossy().into_owned()),
        _ => None,
    }
}

fn n(v: Option<&JsValue>) -> Option<f64> {
    match v {
        Some(JsValue::Number(n)) => Some(*n),
        _ => None,
    }
}

fn arr(v: Option<&JsValue>) -> &[JsValue] {
    match v {
        Some(JsValue::Array(a)) => a,
        _ => &[],
    }
}

/// The error each `MetricsParityError` kind stands for, as the Rust producer and team manager raise it.
pub fn to_error(spec: &JsValue) -> anyhow::Error {
    let message = s(get(spec, "message")).unwrap_or_default();
    match s(get(spec, "kind")).as_deref() {
        Some("dependency_unavailable") => anyhow::Error::new(DependencyUnavailableError {
            message,
            dependency_name: "parity".to_string(),
        }),
        Some("message_size_too_large") => anyhow::Error::new(KafkaProduceError {
            code: ERR_MSG_SIZE_TOO_LARGE,
            name: "MessageSizeTooLarge".to_string(),
            message,
        }),
        Some("non_retriable") => PipelineError::non_retriable(message),
        _ => anyhow::Error::new(NamedError::new("Error", message)),
    }
}

#[derive(Debug, Clone)]
pub struct CapturedMessage {
    pub batch: usize,
    pub output: String,
    pub message: OutputMessage,
}

pub struct CapturingOutputs {
    faults: Vec<(String, Option<String>, JsValue)>,
    remaining: Mutex<Vec<u64>>,
    pub captured: Mutex<Vec<CapturedMessage>>,
    pub current_batch: AtomicU64,
}

#[async_trait]
impl IngestionOutputs for CapturingOutputs {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()> {
        self.queue_messages(output, vec![message]).await
    }

    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()> {
        {
            let mut remaining = self.remaining.lock().unwrap();
            for message in &messages {
                for (i, (fault_output, team, error)) in self.faults.iter().enumerate() {
                    if fault_output != output || remaining[i] == 0 {
                        continue;
                    }
                    if team
                        .as_ref()
                        .is_some_and(|t| message.headers.get("team_id") != Some(t))
                    {
                        continue;
                    }
                    remaining[i] -= 1;
                    return Err(to_error(error));
                }
            }
        }
        let batch = self.current_batch.load(Ordering::SeqCst) as usize;
        self.captured
            .lock()
            .unwrap()
            .extend(messages.into_iter().map(|message| CapturedMessage {
                batch,
                output: output.to_string(),
                message,
            }));
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct UsageRow {
    pub batch: usize,
    pub team_id: i64,
    pub usage_key: String,
    pub record_id: String,
    pub quantity: f64,
    pub unit: String,
    pub timestamp_ms: Option<i64>,
}

#[derive(Default)]
pub struct Recorded {
    pub teams_ingested: Mutex<Vec<Vec<i64>>>,
    pub usage_rows: Mutex<Vec<UsageRow>>,
    pub quota_checks: Mutex<Vec<(String, String)>>,
    /// Node's harness does not record these, so the corpus test checks them against the scenario itself.
    pub unknown_tokens: Mutex<Vec<String>>,
}

impl UnknownTokens for Recorded {
    fn record(&self, token: &str) {
        self.unknown_tokens.lock().unwrap().push(token.to_string());
    }
}

struct ScenarioTeams {
    by_id: HashMap<i64, Team>,
    by_token: HashMap<String, Team>,
    lookup_faults: Mutex<HashMap<String, (u64, JsValue)>>,
    recorded: Arc<Recorded>,
}

#[async_trait]
impl TeamManager for ScenarioTeams {
    async fn get_team(&self, team_id: i64) -> anyhow::Result<Option<Team>> {
        Ok(self.by_id.get(&team_id).cloned())
    }

    async fn get_team_by_token(&self, token: &str) -> anyhow::Result<Option<Team>> {
        if let Some((left, spec)) = self.lookup_faults.lock().unwrap().get_mut(token) {
            if *left > 0 {
                *left -= 1;
                return Err(to_error(spec));
            }
        }
        Ok(self.by_token.get(token).cloned())
    }

    async fn set_teams_ingested_data(&self, team_ids: &[i64]) -> anyhow::Result<()> {
        let mut sorted = team_ids.to_vec();
        sorted.sort_unstable();
        self.recorded.teams_ingested.lock().unwrap().push(sorted);
        Ok(())
    }
}

struct ScenarioQuota {
    limited: Vec<String>,
    recorded: Arc<Recorded>,
}

#[async_trait]
impl QuotaLimiting for ScenarioQuota {
    async fn is_team_token_quota_limited(
        &self,
        token: &str,
        resource: &str,
    ) -> anyhow::Result<bool> {
        let pair = (token.to_string(), resource.to_string());
        let mut checks = self.recorded.quota_checks.lock().unwrap();
        if !checks.contains(&pair) {
            checks.push(pair);
        }
        Ok(self.limited.iter().any(|t| t == token))
    }
}

struct ScenarioUsage {
    outputs: Arc<CapturingOutputs>,
    recorded: Arc<Recorded>,
}

#[async_trait]
impl UsageRecordBatch for ScenarioUsage {
    fn add(&self, team_id: i64, usage_key: &str, record_id: &str, quantity: f64, unit: &str) {
        self.add_at(team_id, usage_key, record_id, quantity, unit, None);
    }

    fn add_at(
        &self,
        team_id: i64,
        usage_key: &str,
        record_id: &str,
        quantity: f64,
        unit: &str,
        timestamp_ms: Option<i64>,
    ) {
        self.recorded.usage_rows.lock().unwrap().push(UsageRow {
            batch: self.outputs.current_batch.load(Ordering::SeqCst) as usize,
            team_id,
            usage_key: usage_key.to_string(),
            record_id: record_id.to_string(),
            quantity,
            unit: unit.to_string(),
            timestamp_ms,
        });
    }

    async fn flush(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

pub struct ScenarioParts {
    pub config: MetricsLimiterConfig,
    pub deps: MetricsPipelineConsumerDeps,
    pub outputs: Arc<CapturingOutputs>,
    pub recorded: Arc<Recorded>,
}

pub struct ScenarioConsumer {
    pub consumer: MetricsPipelineConsumer,
    pub outputs: Arc<CapturingOutputs>,
    pub recorded: Arc<Recorded>,
}

pub fn scenario_parts(
    scenario: &JsValue,
    redis: Arc<dyn TokenBucketRedis>,
    clock: Clock,
) -> ScenarioParts {
    let recorded = Arc::new(Recorded::default());
    let faults = arr(get(scenario, "produce_faults"));
    let outputs = Arc::new(CapturingOutputs {
        faults: faults
            .iter()
            .map(|f| {
                (
                    s(get(f, "output")).unwrap_or_default(),
                    s(get(f, "team_id")),
                    get(f, "error").cloned().unwrap_or(JsValue::Null),
                )
            })
            .collect(),
        remaining: Mutex::new(
            faults
                .iter()
                .map(|f| n(get(f, "times")).unwrap_or(0.0) as u64)
                .collect(),
        ),
        captured: Mutex::new(Vec::new()),
        current_batch: AtomicU64::new(0),
    });
    let teams: Vec<Team> = arr(get(scenario, "teams"))
        .iter()
        .map(|t| Team {
            id: n(get(t, "id")).unwrap_or(0.0) as i64,
            api_token: s(get(t, "api_token")).unwrap_or_default(),
            logs_settings: None,
        })
        .collect();
    let lookup_faults = match get(scenario, "team_lookup_faults") {
        Some(JsValue::Object(o)) => o
            .iter()
            .map(|(token, spec)| {
                (
                    token.to_utf8_lossy().into_owned(),
                    (n(get(spec, "times")).unwrap_or(0.0) as u64, spec.clone()),
                )
            })
            .collect(),
        _ => HashMap::new(),
    };
    let deps = MetricsPipelineConsumerDeps {
        team_manager: Arc::new(ScenarioTeams {
            by_id: teams.iter().map(|t| (t.id, t.clone())).collect(),
            by_token: teams
                .iter()
                .map(|t| (t.api_token.clone(), t.clone()))
                .collect(),
            lookup_faults: Mutex::new(lookup_faults),
            recorded: recorded.clone(),
        }),
        quota_limiting: Arc::new(ScenarioQuota {
            limited: arr(get(scenario, "quota_limited_tokens"))
                .iter()
                .filter_map(|v| s(Some(v)))
                .collect(),
            recorded: recorded.clone(),
        }),
        outputs: outputs.clone(),
        usage_batch: Arc::new(ScenarioUsage {
            outputs: outputs.clone(),
            recorded: recorded.clone(),
        }),
        token_bucket_redis: redis,
        key_root: KeyRoot::Test,
        clock,
        dev_env: false,
        source_offset_header: false,
        unknown_tokens: Some(recorded.clone()),
    };
    let config = match get(scenario, "config") {
        Some(JsValue::Object(o)) => o.clone(),
        _ => JsObject::new(),
    };
    // A key that this replay ignored would let Node take a path that Rust does not have, with matching outputs for the wrong reason.
    for (key, value) in config.iter() {
        let key = key.to_utf8_lossy();
        match key.as_ref() {
            AGGREGATION_TEAMS_KEY => assert!(
                matches!(value, JsValue::String(teams) if teams.to_utf8_lossy().trim().is_empty()),
                "{AGGREGATION_TEAMS_KEY} must be empty: metric aggregation is not ported"
            ),
            key => assert!(
                key.starts_with("METRICS_LIMITER_"),
                "scenario config key {key} is not ported"
            ),
        }
    }
    ScenarioParts {
        config: MetricsLimiterConfig::from_node_config(&config),
        deps,
        outputs,
        recorded,
    }
}

pub fn build_scenario_consumer(
    scenario: &JsValue,
    redis: Arc<dyn TokenBucketRedis>,
    clock: Clock,
) -> ScenarioConsumer {
    let parts = scenario_parts(scenario, redis, clock);
    ScenarioConsumer {
        consumer: MetricsPipelineConsumer::new(parts.config, parts.deps),
        outputs: parts.outputs,
        recorded: parts.recorded,
    }
}
