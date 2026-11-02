//! In-memory dependencies built from a parity scenario (`nodejs/src/logs/parity/parity-types.ts`),
//! mirroring `parity-harness.ts`. The parity test and the benchmark binary both use them.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use base64::Engine;
use ingestion_framework::{IngestionOutputs, KafkaMessage, OutputMessage};

use crate::internal_logs::InternalSourcePolicy;
use crate::js::{JsObject, JsValue};
use crate::metric_rules::{
    compile_metric_rules, CompiledMetricRule, MetricRuleRow, MetricRulesSource, MetricsEmitter,
};
use crate::normalize::LogsSettings;
use crate::pattern::MESSAGE_KEYS;
use crate::rate_limiter::{Clock, KeyRoot, TokenBucketRedis};
use crate::retention::{compile_retention_rule_set, CompiledRetentionRuleSet, RetentionRuleRow};
use crate::sampling::{compile_rule_set, CompiledRuleSet, SamplingRuleRow};

use super::config::LogsIngestionConsumerConfig;
use super::consumer::LogsIngestionConsumer;
use super::context::LogsConsumerIdentity;
use super::deps::*;
use super::errors::{DependencyRetry, DependencyUnavailableError, NamedError};

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

fn entries(v: Option<&JsValue>) -> Vec<(String, &JsValue)> {
    match v {
        Some(JsValue::Object(o)) => o
            .iter()
            .map(|(k, v)| (k.to_utf8_lossy().into_owned(), v))
            .collect(),
        _ => Vec::new(),
    }
}

fn to_error(spec: &JsValue) -> anyhow::Error {
    let name = s(get(spec, "name")).unwrap_or_default();
    let message = s(get(spec, "message")).unwrap_or_default();
    if matches!(
        get(spec, "dependency_unavailable"),
        Some(JsValue::Bool(true))
    ) {
        return anyhow::Error::new(DependencyUnavailableError {
            message,
            dependency_name: "parity".to_string(),
        });
    }
    anyhow::Error::new(NamedError::new(name, message))
}

pub fn logs_settings(value: Option<&JsValue>) -> Option<LogsSettings> {
    let value = value.filter(|v| matches!(v, JsValue::Object(_)))?;
    Some(LogsSettings {
        capture_console_logs: match get(value, "capture_console_logs") {
            Some(JsValue::Bool(b)) => Some(*b),
            _ => None,
        },
        json_parse_logs: match get(value, "json_parse_logs") {
            Some(JsValue::Bool(b)) => Some(*b),
            _ => None,
        },
        json_parse_logs_attribute_key: s(get(value, "json_parse_logs_attribute_key")),
        pii_scrub_logs: match get(value, "pii_scrub_logs") {
            Some(JsValue::Bool(b)) => Some(*b),
            _ => None,
        },
        retention_days: n(get(value, "retention_days")),
        retention_last_updated: s(get(value, "retention_last_updated")),
    })
}

pub fn kafka_message(m: &JsValue) -> KafkaMessage {
    KafkaMessage {
        topic: s(get(m, "topic")).unwrap_or_default(),
        partition: n(get(m, "partition")).unwrap_or(0.0) as i32,
        offset: n(get(m, "offset")).unwrap_or(0.0) as i64,
        key: s(get(m, "key")).map(String::into_bytes),
        value: s(get(m, "value_b64")).map(|b| {
            base64::engine::general_purpose::STANDARD
                .decode(b)
                .unwrap()
                .into()
        }),
        headers: arr(get(m, "headers"))
            .iter()
            .map(|h| {
                let pair = arr(Some(h));
                (
                    s(pair.first()).unwrap_or_default(),
                    Some(s(pair.get(1)).unwrap_or_default().into_bytes()),
                )
            })
            .collect(),
        timestamp: n(get(m, "timestamp")).map(|t| t as i64),
    }
}

#[derive(Clone)]
pub struct PinnedClock(Arc<AtomicU64>);

impl PinnedClock {
    pub fn new(ms: f64) -> Self {
        Self(Arc::new(AtomicU64::new(ms.to_bits())))
    }
    pub fn set(&self, ms: f64) {
        self.0.store(ms.to_bits(), Ordering::SeqCst);
    }
    pub fn clock(&self) -> Clock {
        let bits = self.0.clone();
        Arc::new(move || f64::from_bits(bits.load(Ordering::SeqCst)))
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
    pub produced_count: AtomicU64,
    pub current_batch: AtomicU64,
    discard: bool,
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
        self.produced_count
            .fetch_add(messages.len() as u64, Ordering::SeqCst);
        if !self.discard {
            let batch = self.current_batch.load(Ordering::SeqCst) as usize;
            let mut captured = self.captured.lock().unwrap();
            for message in messages {
                captured.push(CapturedMessage {
                    batch,
                    output: output.to_string(),
                    message,
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct UsageRow {
    pub batch: usize,
    pub team_id: i64,
    pub metric: String,
    pub quantity: f64,
    pub unit: String,
    pub record_id: String,
}

#[derive(Default)]
pub struct Recorded {
    pub teams_ingested: Mutex<Vec<Vec<i64>>>,
    pub metric_emits: Mutex<Vec<(String, i64, JsValue)>>,
    pub usage_rows: Mutex<Vec<UsageRow>>,
    pub quota_checks: Mutex<Vec<(String, String)>>,
}

struct ScenarioTeams {
    by_id: HashMap<i64, Team>,
    by_token: HashMap<String, Team>,
    lookup_faults: HashMap<String, JsValue>,
    by_id_faults: Mutex<HashMap<i64, (u64, JsValue)>>,
    missing: Vec<i64>,
    recorded: Arc<Recorded>,
}

#[async_trait]
impl TeamManager for ScenarioTeams {
    async fn get_team(&self, team_id: i64) -> anyhow::Result<Option<Team>> {
        if let Some((left, spec)) = self.by_id_faults.lock().unwrap().get_mut(&team_id) {
            if *left > 0 {
                *left -= 1;
                return Err(to_error(spec));
            }
        }
        if self.missing.contains(&team_id) {
            return Ok(None);
        }
        Ok(self.by_id.get(&team_id).cloned())
    }

    async fn get_team_by_token(&self, token: &str) -> anyhow::Result<Option<Team>> {
        if let Some(spec) = self.lookup_faults.get(token) {
            return Err(to_error(spec));
        }
        Ok(self.by_token.get(token).cloned())
    }

    async fn set_teams_ingested_data(&self, team_ids: &[i64]) -> anyhow::Result<()> {
        self.recorded
            .teams_ingested
            .lock()
            .unwrap()
            .push(team_ids.to_vec());
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
    discard: bool,
}

#[async_trait]
impl UsageRecordBatch for ScenarioUsage {
    fn add(&self, team_id: i64, usage_key: &str, record_id: &str, quantity: f64, unit: &str) {
        if self.discard {
            return;
        }
        self.recorded.usage_rows.lock().unwrap().push(UsageRow {
            batch: self.outputs.current_batch.load(Ordering::SeqCst) as usize,
            team_id,
            metric: usage_key.to_string(),
            quantity,
            unit: unit.to_string(),
            record_id: record_id.to_string(),
        });
    }
    async fn flush(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

fn team_rows(v: Option<&JsValue>, team_id: i64) -> Vec<JsValue> {
    entries(v)
        .into_iter()
        .find(|(k, _)| k.parse::<i64>().ok() == Some(team_id))
        .map(|(_, rows)| arr(Some(rows)).to_vec())
        .unwrap_or_default()
}

/// Compiled rules per key. A scenario's rule rows never change, and production reads compiled
/// rules from a cache, so the harness compiles each set once.
struct Compiled<K, V>(Mutex<HashMap<K, Arc<V>>>);

impl<K: std::hash::Hash + Eq, V> Default for Compiled<K, V> {
    fn default() -> Self {
        Self(Mutex::new(HashMap::new()))
    }
}

impl<K: std::hash::Hash + Eq, V> Compiled<K, V> {
    fn get_or_compile(
        &self,
        key: K,
        compile: impl FnOnce() -> anyhow::Result<V>,
    ) -> anyhow::Result<Arc<V>> {
        if let Some(v) = self.0.lock().unwrap().get(&key) {
            return Ok(v.clone());
        }
        let v = Arc::new(compile()?);
        Ok(self.0.lock().unwrap().entry(key).or_insert(v).clone())
    }
}

struct ScenarioSampling(JsValue, Compiled<i64, CompiledRuleSet>);

#[async_trait]
impl SamplingRulesSource for ScenarioSampling {
    async fn get_compiled_rule_set(&self, team_id: i64) -> anyhow::Result<Arc<CompiledRuleSet>> {
        self.1.get_or_compile(team_id, || self.compile(team_id))
    }
}

impl ScenarioSampling {
    fn compile(&self, team_id: i64) -> anyhow::Result<CompiledRuleSet> {
        let rows: Vec<SamplingRuleRow> = team_rows(Some(&self.0), team_id)
            .iter()
            .map(|r| SamplingRuleRow {
                id: s(get(r, "id")).unwrap_or_default(),
                rule_type: s(get(r, "rule_type")).unwrap_or_default(),
                scope_service: s(get(r, "scope_service")),
                scope_path_pattern: s(get(r, "scope_path_pattern")),
                scope_attribute_filters: get(r, "scope_attribute_filters")
                    .cloned()
                    .unwrap_or(JsValue::Null),
                config: get(r, "config").cloned().unwrap_or(JsValue::Null),
                version: None,
            })
            .collect();
        compile_rule_set(&rows).map_err(anyhow::Error::new)
    }
}

struct ScenarioRetention(JsValue, Compiled<(i64, String), CompiledRetentionRuleSet>);

#[async_trait]
impl RetentionRulesSource for ScenarioRetention {
    async fn get_compiled_rule_set(
        &self,
        team_id: i64,
        source: &str,
    ) -> anyhow::Result<Arc<CompiledRetentionRuleSet>> {
        self.1.get_or_compile((team_id, source.to_string()), || {
            self.compile(team_id, source)
        })
    }
}

impl ScenarioRetention {
    fn compile(&self, team_id: i64, source: &str) -> anyhow::Result<CompiledRetentionRuleSet> {
        let by_source = entries(Some(&self.0))
            .into_iter()
            .find(|(k, _)| k.parse::<i64>().ok() == Some(team_id))
            .map(|(_, v)| v.clone());
        let rows: Vec<RetentionRuleRow> = arr(by_source.as_ref().and_then(|v| get(v, source)))
            .iter()
            .map(|r| RetentionRuleRow {
                id: s(get(r, "id")).unwrap_or_default(),
                config: get(r, "config").cloned().unwrap_or(JsValue::Null),
                version: None,
            })
            .collect();
        compile_retention_rule_set(&rows).map_err(anyhow::Error::new)
    }
}

struct ScenarioMetricRules {
    rows: JsValue,
    faults: JsValue,
    compiled: Compiled<i64, Vec<CompiledMetricRule>>,
}

#[async_trait]
impl MetricRulesSource for ScenarioMetricRules {
    async fn get_compiled_rules(
        &self,
        team_id: i64,
    ) -> anyhow::Result<Arc<Vec<CompiledMetricRule>>> {
        if let Some((_, spec)) = entries(Some(&self.faults))
            .into_iter()
            .find(|(k, _)| k.parse::<i64>().ok() == Some(team_id))
        {
            return Err(to_error(spec));
        }
        self.compiled.get_or_compile(team_id, || {
            let rows: Vec<MetricRuleRow> = team_rows(Some(&self.rows), team_id)
                .iter()
                .filter_map(|r| match r {
                    JsValue::Object(o) => Some(MetricRuleRow::from_js(o)),
                    _ => None,
                })
                .collect();
            compile_metric_rules(&rows).map_err(anyhow::Error::new)
        })
    }
}

struct ScenarioEmitter {
    faults: Vec<i64>,
    recorded: Arc<Recorded>,
}

#[async_trait]
impl MetricsEmitter for ScenarioEmitter {
    async fn emit(&self, token: &str, team_id: i64, payload: &JsValue) -> bool {
        if self.faults.contains(&team_id) {
            return false;
        }
        self.recorded.metric_emits.lock().unwrap().push((
            token.to_string(),
            team_id,
            payload.clone(),
        ));
        true
    }
}

struct ScenarioPatternKeys {
    keys: JsValue,
    faults: Mutex<HashMap<i64, (u64, JsValue)>>,
}

#[async_trait]
impl PatternMessageKeysSource for ScenarioPatternKeys {
    async fn get_message_keys(&self, team_id: i64) -> anyhow::Result<Vec<String>> {
        if let Some((left, spec)) = self.faults.lock().unwrap().get_mut(&team_id) {
            if *left > 0 {
                *left -= 1;
                return Err(to_error(spec));
            }
        }
        match entries(Some(&self.keys))
            .into_iter()
            .find(|(k, _)| k.parse::<i64>().ok() == Some(team_id))
        {
            Some((_, keys)) => Ok(arr(Some(keys)).iter().filter_map(|k| s(Some(k))).collect()),
            None => Ok(MESSAGE_KEYS.iter().map(|k| k.to_string()).collect()),
        }
    }
}

struct ScenarioTracing(JsValue);

#[async_trait]
impl TracingConfigSource for ScenarioTracing {
    async fn get_retention_days(&self, team_id: i64) -> anyhow::Result<f64> {
        Ok(entries(Some(&self.0))
            .into_iter()
            .find(|(k, _)| k.parse::<i64>().ok() == Some(team_id))
            .and_then(|(_, v)| n(Some(v)))
            .unwrap_or(30.0))
    }
}

fn faults_with_times(v: Option<&JsValue>) -> HashMap<i64, (u64, JsValue)> {
    entries(v)
        .into_iter()
        .filter_map(|(k, spec)| {
            Some((
                k.parse().ok()?,
                (n(get(spec, "times")).unwrap_or(0.0) as u64, spec.clone()),
            ))
        })
        .collect()
}

pub struct ScenarioConsumer {
    pub consumer: LogsIngestionConsumer,
    pub outputs: Arc<CapturingOutputs>,
    pub recorded: Arc<Recorded>,
}

/// `buildParityConsumer`. `discard` counts produced messages instead of keeping them.
pub fn build_scenario_consumer(
    scenario: &JsValue,
    redis: Arc<dyn TokenBucketRedis>,
    clock: Clock,
    discard: bool,
) -> ScenarioConsumer {
    let recorded = Arc::new(Recorded::default());
    let outputs = Arc::new(CapturingOutputs {
        faults: arr(get(scenario, "produce_faults"))
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
            arr(get(scenario, "produce_faults"))
                .iter()
                .map(|f| n(get(f, "times")).unwrap_or(0.0) as u64)
                .collect(),
        ),
        captured: Mutex::new(Vec::new()),
        produced_count: AtomicU64::new(0),
        current_batch: AtomicU64::new(0),
        discard,
    });
    let teams: Vec<Team> = arr(get(scenario, "teams"))
        .iter()
        .map(|t| Team {
            id: n(get(t, "id")).unwrap_or(0.0) as i64,
            api_token: s(get(t, "api_token")).unwrap_or_default(),
            logs_settings: logs_settings(get(t, "logs_settings")),
        })
        .collect();
    let team_manager = ScenarioTeams {
        by_id: teams.iter().map(|t| (t.id, t.clone())).collect(),
        by_token: teams
            .iter()
            .map(|t| (t.api_token.clone(), t.clone()))
            .collect(),
        lookup_faults: entries(get(scenario, "team_lookup_faults"))
            .into_iter()
            .map(|(k, v)| (k, v.clone()))
            .collect(),
        by_id_faults: Mutex::new(faults_with_times(get(scenario, "team_by_id_faults"))),
        missing: arr(get(scenario, "team_by_id_missing"))
            .iter()
            .filter_map(|v| n(Some(v)).map(|n| n as i64))
            .collect(),
        recorded: recorded.clone(),
    };
    let field = |name: &str| get(scenario, name).cloned().unwrap_or(JsValue::Null);
    let omit: Vec<String> = arr(get(scenario, "omit_deps"))
        .iter()
        .filter_map(|v| s(Some(v)))
        .collect();
    let keep = |name: &str| !omit.iter().any(|o| o == name);
    let policies = match get(scenario, "internal_source_policies") {
        Some(JsValue::Object(o)) => Some(
            o.iter()
                .map(|(k, v)| {
                    let flag = |f: &str| matches!(get(v, f), Some(JsValue::Bool(true)));
                    (
                        k.to_utf8_lossy().into_owned(),
                        InternalSourcePolicy {
                            billed: flag("billed"),
                            team_rules: flag("teamRules"),
                        },
                    )
                })
                .collect(),
        ),
        _ => None,
    };
    let deps = LogsIngestionConsumerDeps {
        team_manager: Arc::new(team_manager),
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
            discard,
        }),
        sampling_rules: keep("samplingRulesCache").then(|| {
            Arc::new(ScenarioSampling(
                field("sampling_rules"),
                Compiled::default(),
            )) as _
        }),
        metric_rules: Some(Arc::new(ScenarioMetricRules {
            rows: field("metric_rules"),
            faults: field("metric_rules_faults"),
            compiled: Compiled::default(),
        })),
        metrics_emitter: keep("metricsEmitter").then(|| {
            Arc::new(ScenarioEmitter {
                faults: arr(get(scenario, "metric_emit_faults"))
                    .iter()
                    .filter_map(|v| n(Some(v)).map(|n| n as i64))
                    .collect(),
                recorded: recorded.clone(),
            }) as _
        }),
        logs_transformer: None,
        retention_rules: Some(Arc::new(ScenarioRetention(
            field("retention_rules"),
            Compiled::default(),
        ))),
        pattern_message_keys: keep("patternMessageKeysCache").then(|| {
            Arc::new(ScenarioPatternKeys {
                keys: field("pattern_message_keys"),
                faults: Mutex::new(faults_with_times(get(scenario, "pattern_keys_faults"))),
            }) as _
        }),
        tracing_config: keep("tracingConfigCache")
            .then(|| Arc::new(ScenarioTracing(field("traces_retention_days"))) as _),
        dependency_retry: DependencyRetry {
            retry_count: 2,
            initial_retry_delay_ms: 1,
        },
        internal_source_policies: policies,
        token_bucket_redis: redis,
        key_root: KeyRoot::Test,
        clock,
    };
    let config = match get(scenario, "config") {
        Some(JsValue::Object(o)) => o.clone(),
        _ => JsObject::new(),
    };
    let traces = s(get(scenario, "consumer")).as_deref() == Some("traces");
    let consumer = if traces {
        LogsIngestionConsumer::new(
            LogsConsumerIdentity::traces(),
            LogsIngestionConsumerConfig::from_traces_config(&config),
            deps,
        )
    } else {
        LogsIngestionConsumer::new(
            LogsConsumerIdentity::logs(),
            LogsIngestionConsumerConfig::from_logs_config(&config),
            deps,
        )
    };
    ScenarioConsumer {
        consumer,
        outputs,
        recorded,
    }
}
