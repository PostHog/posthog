mod project;

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

use chrono::Utc;
use common_kafka::{
    kafka_messages::app_metrics2::{AppMetric2, Kind, Source},
    kafka_producer::send_iter_to_kafka,
    APP_METRICS2_TOPIC,
};
use common_redis::{CompressionConfig, RedisClient, RedisValueFormat, ScriptRunner};
use common_types::format::parse_datetime_assuming_utc;
use futures::stream::{self, StreamExt};
use metrics::counter;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{
        ADAPTIVE_INGESTION_DECISIONS, ADAPTIVE_INGESTION_PROJECT_CAP_REACHED,
        ADAPTIVE_INGESTION_REDIS_ERRORS, ADAPTIVE_INGESTION_STAGE,
    },
    modes::processing::{
        config::ProcessingConfig,
        redis_heal::{self, HealGate},
        rules::rate_limit::RateLimitSettings,
    },
    stages::pipeline::RateCheckedPipelineItem,
    types::{
        batch::Batch,
        exception_event::ExceptionEvent,
        stage::{Stage, StageResult},
    },
};

use project::ProjectRule;

const VERSION: u32 = 1;
const DAY_WINDOW_SECONDS: i64 = 86_400;
const MAX_CONCURRENT_GROUPS: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum Decision {
    Keep,
    SampleProject,
    Error,
}

impl Decision {
    fn label(self) -> &'static str {
        match self {
            Self::Keep => "keep",
            Self::SampleProject => "sample_project",
            Self::Error => "error",
        }
    }
}

pub struct AdaptiveIngestionRuntime {
    redis: Arc<dyn ScriptRunner>,
    teams: HashSet<i32>,
    team_percent: u8,
    project: ProjectRule,
    heal_gate: HealGate,
}

impl AdaptiveIngestionRuntime {
    pub async fn from_config(
        config: &ProcessingConfig,
    ) -> Result<Option<Arc<Self>>, UnhandledError> {
        match config.adaptive_ingestion_mode.as_str() {
            "off" => return Ok(None),
            "shadow" => {}
            other => {
                return Err(UnhandledError::Other(format!(
                    "invalid ADAPTIVE_INGESTION_MODE: {other}"
                )))
            }
        }
        if config.adaptive_ingestion_team_percent > 100
            || config.adaptive_ingestion_project_floor == 0
            || !config.adaptive_ingestion_project_multiplier.is_finite()
            || config.adaptive_ingestion_project_multiplier <= 0.0
            || config.adaptive_ingestion_project_keep_percent > 100
        {
            return Err(UnhandledError::Other(
                "invalid adaptive ingestion rollout or project cap".into(),
            ));
        }
        let teams = config
            .adaptive_ingestion_teams
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| {
                s.parse::<i32>().map_err(|_| {
                    UnhandledError::Other(format!("invalid ADAPTIVE_INGESTION_TEAMS entry: {s}"))
                })
            })
            .collect::<Result<HashSet<_>, _>>()?;
        if teams.is_empty() && config.adaptive_ingestion_team_percent == 0 {
            return Ok(None);
        }
        let redis = RedisClient::with_config(
            config.issue_buckets_redis_url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            (config.redis_response_timeout_ms != 0)
                .then(|| std::time::Duration::from_millis(config.redis_response_timeout_ms)),
            (config.redis_connection_timeout_ms != 0)
                .then(|| std::time::Duration::from_millis(config.redis_connection_timeout_ms)),
        )
        .await?;
        Ok(Some(Arc::new(Self {
            redis: Arc::new(redis),
            teams,
            team_percent: config.adaptive_ingestion_team_percent,
            project: ProjectRule {
                multiplier: config.adaptive_ingestion_project_multiplier,
                floor: config.adaptive_ingestion_project_floor,
                keep_percent: config.adaptive_ingestion_project_keep_percent,
            },
            heal_gate: HealGate::new(),
        })))
    }

    fn enabled_for(&self, team_id: i32, settings: &HashMap<i32, RateLimitSettings>) -> bool {
        self.selected_for_rollout(team_id)
            && settings
                .get(&team_id)
                .is_some_and(|setting| setting.adaptive_ingestion_enabled)
    }

    fn selected_for_rollout(&self, team_id: i32) -> bool {
        if self.teams.contains(&team_id) {
            return true;
        }
        let hash = Sha256::digest(team_id.to_be_bytes());
        u64::from_be_bytes(hash[0..8].try_into().expect("sha256 has 32 bytes")) % 100
            < u64::from(self.team_percent)
    }
}

#[derive(Clone)]
pub struct AdaptiveIngestionStage {
    ctx: Arc<AppContext>,
}

impl From<&Arc<AppContext>> for AdaptiveIngestionStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        Self {
            ctx: Arc::clone(ctx),
        }
    }
}

impl Stage for AdaptiveIngestionStage {
    type Input = RateCheckedPipelineItem;
    type Output = RateCheckedPipelineItem;

    fn name(&self) -> &'static str {
        ADAPTIVE_INGESTION_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let Some(runtime) = self.ctx.adaptive_ingestion.as_ref() else {
            return Ok(batch);
        };
        let mut items: Vec<RateCheckedPipelineItem> = batch.into();
        let team_ids: HashSet<i32> = items
            .iter()
            .filter_map(|item| item.as_ref().ok().map(ExceptionEvent::team_id))
            .filter(|team_id| runtime.selected_for_rollout(*team_id))
            .collect();
        if team_ids.is_empty() {
            return Ok(Batch::from(items));
        }
        let settings = self
            .ctx
            .team_manager
            .get_rate_limit_settings(&self.ctx.posthog_pool, team_ids)
            .await;
        let metrics = apply_shadow(runtime, &settings, &mut items).await;
        self.emit_metrics(metrics);
        Ok(Batch::from(items))
    }
}

async fn apply_shadow(
    runtime: &Arc<AdaptiveIngestionRuntime>,
    settings: &HashMap<i32, RateLimitSettings>,
    items: &mut [RateCheckedPipelineItem],
) -> HashMap<(i32, Decision), u32> {
    let mut groups: HashMap<(i32, i64), Vec<(usize, Uuid)>> = HashMap::new();
    let mut invalid_timestamps = Vec::new();
    for (idx, item) in items.iter().enumerate() {
        let Ok(event) = item else { continue };
        if !runtime.enabled_for(event.team_id(), settings) {
            continue;
        }
        let Ok(timestamp) = parse_datetime_assuming_utc(event.timestamp()) else {
            invalid_timestamps.push((idx, event.team_id()));
            continue;
        };
        let timestamp = timestamp.timestamp();
        let day = timestamp - timestamp.rem_euclid(DAY_WINDOW_SECONDS);
        groups
            .entry((event.team_id(), day))
            .or_default()
            .push((idx, event.uuid()));
    }

    let outcomes: Vec<_> = stream::iter(groups.into_iter().map(|((team_id, day), events)| {
        let redis = Arc::clone(&runtime.redis);
        let rule = runtime.project;
        async move {
            let uuids: Vec<Uuid> = events.iter().map(|(_, uuid)| *uuid).collect();
            let result = rule
                .evaluate_batch(redis.as_ref(), team_id, day, &uuids)
                .await;
            (team_id, events, result)
        }
    }))
    .buffer_unordered(MAX_CONCURRENT_GROUPS)
    .collect()
    .await;

    let mut metrics = HashMap::new();
    for (idx, team_id) in invalid_timestamps {
        if let Ok(event) = &mut items[idx] {
            set_decision(event, Decision::Keep);
            event
                .props
                .insert("$adaptive_ingestion_error".into(), Value::Bool(true));
        }
        counter!(ADAPTIVE_INGESTION_DECISIONS, "rule" => "project", "decision" => "error")
            .increment(1);
        *metrics.entry((team_id, Decision::Error)).or_insert(0) += 1;
    }
    for (team_id, events, result) in outcomes {
        match result {
            Ok(decisions) => {
                for ((idx, _), project) in events.into_iter().zip(decisions) {
                    let decision = if project.sampled {
                        Decision::SampleProject
                    } else {
                        Decision::Keep
                    };
                    counter!(ADAPTIVE_INGESTION_DECISIONS, "rule" => "project", "decision" => decision.label())
                        .increment(1);
                    if project.cap_started {
                        counter!(ADAPTIVE_INGESTION_PROJECT_CAP_REACHED).increment(1);
                    }
                    *metrics.entry((team_id, decision)).or_insert(0) += 1;
                    if let Ok(event) = &mut items[idx] {
                        set_decision(event, decision);
                        event.props.insert(
                            "$adaptive_ingestion_allowance".into(),
                            Value::from(project.allowance),
                        );
                        event.props.insert(
                            "$adaptive_ingestion_baseline".into(),
                            Value::from(project.baseline),
                        );
                        event.props.insert(
                            "$adaptive_ingestion_count".into(),
                            Value::from(project.count),
                        );
                    }
                }
            }
            Err(err) => {
                warn!(
                    team_id,
                    "adaptive ingestion project counter failed open: {err}"
                );
                counter!(ADAPTIVE_INGESTION_REDIS_ERRORS).increment(events.len() as u64);
                counter!(ADAPTIVE_INGESTION_DECISIONS, "rule" => "project", "decision" => "error")
                    .increment(events.len() as u64);
                if redis_heal::is_connection_error(&err) {
                    let redis = Arc::clone(&runtime.redis);
                    runtime
                        .heal_gate
                        .spawn_heal(async move { redis.heal().await });
                }
                for (idx, _) in events {
                    if let Ok(event) = &mut items[idx] {
                        set_decision(event, Decision::Keep);
                        event
                            .props
                            .insert("$adaptive_ingestion_error".into(), Value::Bool(true));
                    }
                    *metrics.entry((team_id, Decision::Error)).or_insert(0) += 1;
                }
            }
        }
    }
    metrics
}

fn set_decision(
    event: &mut ExceptionEvent<crate::types::exception_event::RateChecked>,
    decision: Decision,
) {
    event.props.insert(
        "$adaptive_ingestion_decision".into(),
        Value::String(decision.label().into()),
    );
    event.props.insert(
        "$adaptive_ingestion_rule".into(),
        Value::String("project".into()),
    );
    event
        .props
        .insert("$adaptive_ingestion_version".into(), Value::from(VERSION));
}

impl AdaptiveIngestionStage {
    fn emit_metrics(&self, metrics: HashMap<(i32, Decision), u32>) {
        if metrics.is_empty() {
            return;
        }
        let now = Utc::now();
        let app_metrics: Vec<_> = metrics
            .into_iter()
            .map(|((team_id, decision), count)| AppMetric2 {
                team_id: team_id as u32,
                timestamp: now,
                app_source: Source::Exceptions,
                app_source_id: format!("{team_id}:exceptions:global"),
                instance_id: None,
                metric_kind: match decision {
                    Decision::Keep | Decision::Error => Kind::AdaptiveIngestion,
                    Decision::SampleProject => Kind::AdaptiveIngestionProject,
                },
                metric_name: decision.label().to_string(),
                count,
            })
            .collect();
        let producer = self.ctx.app_metrics_producer.clone();
        tokio::spawn(async move {
            for result in send_iter_to_kafka(&producer, APP_METRICS2_TOPIC, app_metrics).await {
                if let Err(err) = result {
                    warn!("failed to emit adaptive ingestion app_metric: {err}");
                }
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::FakeRunner;
    use crate::{
        issue_resolution::{Issue, IssueStatus},
        modes::processing::types::{
            exception_event::{Linked, ResolvedMetadata, SelectedFingerprint},
            ExceptionList,
        },
    };

    fn rate_checked_event(team_id: i32, issue_id: Uuid) -> RateCheckedPipelineItem {
        Ok(ExceptionEvent {
            uuid: Uuid::now_v7(),
            team_id,
            timestamp: "2026-01-01T00:00:00Z".to_string(),
            exception_list: ExceptionList(vec![]),
            debug_images: vec![],
            props: HashMap::new(),
            proposed_issue_name: None,
            proposed_issue_description: None,
            proposed_issue_severity: None,
            state: Linked {
                metadata: ResolvedMetadata {
                    sources: vec![],
                    types: vec![],
                    messages: vec![],
                    functions: vec![],
                    handled: false,
                    release: None,
                },
                fingerprint: SelectedFingerprint::manual("example-fingerprint".into()),
                issue: Issue {
                    id: issue_id,
                    team_id,
                    status: IssueStatus::Active,
                    severity: None,
                    name: None,
                    description: None,
                    created_at: Utc::now(),
                },
            },
        }
        .into_rate_checked())
    }

    #[tokio::test]
    async fn project_shadow_marks_overflow_without_removing_events() {
        let redis = FakeRunner::returning(
            std::iter::once(5)
                .chain(std::iter::repeat_n(0, 14))
                .collect(),
        );
        let runtime = Arc::new(AdaptiveIngestionRuntime {
            redis,
            teams: HashSet::from([7]),
            team_percent: 0,
            project: ProjectRule {
                multiplier: 3.0,
                floor: 1,
                keep_percent: 0,
            },
            heal_gate: HealGate::new(),
        });
        let issue = Uuid::now_v7();
        let mut clickhouse_timestamp = rate_checked_event(7, issue);
        clickhouse_timestamp.as_mut().unwrap().timestamp = "2026-01-01 00:00:00.000".into();
        let mut invalid = rate_checked_event(7, issue);
        invalid.as_mut().unwrap().timestamp = "invalid".into();
        let mut items = vec![
            rate_checked_event(7, issue),
            clickhouse_timestamp,
            rate_checked_event(7, issue),
            rate_checked_event(8, issue),
            invalid,
            Err(crate::error::EventError::RateLimitedProject(7)),
        ];
        let settings = HashMap::from([
            (
                7,
                RateLimitSettings {
                    adaptive_ingestion_enabled: true,
                    ..Default::default()
                },
            ),
            (
                8,
                RateLimitSettings {
                    adaptive_ingestion_enabled: true,
                    ..Default::default()
                },
            ),
        ]);
        let metrics = apply_shadow(&runtime, &settings, &mut items).await;
        assert!(items[..5].iter().all(Result::is_ok));
        assert!(matches!(
            items[5],
            Err(crate::error::EventError::RateLimitedProject(7))
        ));
        assert_eq!(metrics.get(&(7, Decision::Keep)), Some(&1));
        assert_eq!(metrics.get(&(7, Decision::SampleProject)), Some(&2));
        assert_eq!(metrics.get(&(7, Decision::Error)), Some(&1));
        let decisions: Vec<_> = items[..3]
            .iter()
            .map(|item| {
                item.as_ref().unwrap().properties()["$adaptive_ingestion_decision"]
                    .as_str()
                    .unwrap()
            })
            .collect();
        assert_eq!(decisions, ["keep", "sample_project", "sample_project"]);
        let stored = items[1]
            .as_ref()
            .unwrap()
            .clone()
            .into_finalized()
            .into_clickhouse_properties();
        assert_eq!(stored["$adaptive_ingestion_decision"], "sample_project");
        assert_eq!(stored["$adaptive_ingestion_rule"], "project");
        assert_eq!(stored["$adaptive_ingestion_allowance"], 3);
        assert_eq!(stored["$adaptive_ingestion_count"], 4);
        assert!(items[3]
            .as_ref()
            .unwrap()
            .properties()
            .get("$adaptive_ingestion_version")
            .is_none());
        assert_eq!(
            items[4].as_ref().unwrap().properties()["$adaptive_ingestion_error"],
            true
        );
        assert!(items[4]
            .as_ref()
            .unwrap()
            .properties()
            .get("$adaptive_ingestion_count")
            .is_none());

        let mut opted_out = vec![rate_checked_event(7, issue)];
        assert!(apply_shadow(
            &runtime,
            &HashMap::from([(7, RateLimitSettings::default())]),
            &mut opted_out
        )
        .await
        .is_empty());
        assert!(opted_out[0]
            .as_ref()
            .unwrap()
            .properties()
            .get("$adaptive_ingestion_decision")
            .is_none());
    }

    #[tokio::test]
    async fn project_counter_failure_keeps_events_and_marks_error() {
        let runtime = Arc::new(AdaptiveIngestionRuntime {
            redis: FakeRunner::failing(),
            teams: HashSet::from([7]),
            team_percent: 0,
            project: ProjectRule::default(),
            heal_gate: HealGate::new(),
        });
        let mut items = vec![rate_checked_event(7, Uuid::now_v7())];
        let settings = HashMap::from([(
            7,
            RateLimitSettings {
                adaptive_ingestion_enabled: true,
                ..Default::default()
            },
        )]);
        let metrics = apply_shadow(&runtime, &settings, &mut items).await;
        assert!(items[0].is_ok());
        assert_eq!(metrics.get(&(7, Decision::Error)), Some(&1));
        let props = items[0].as_ref().unwrap().properties();
        assert_eq!(props["$adaptive_ingestion_decision"], "keep");
        assert_eq!(props["$adaptive_ingestion_error"], true);
    }

    #[test]
    fn rollout_requires_preference_and_team_selection() {
        let runtime = AdaptiveIngestionRuntime {
            redis: FakeRunner::failing(),
            teams: HashSet::from([7]),
            team_percent: 0,
            project: ProjectRule::default(),
            heal_gate: HealGate::new(),
        };
        let settings = HashMap::from([
            (
                7,
                RateLimitSettings {
                    adaptive_ingestion_enabled: true,
                    ..Default::default()
                },
            ),
            (
                8,
                RateLimitSettings {
                    adaptive_ingestion_enabled: true,
                    ..Default::default()
                },
            ),
            (9, RateLimitSettings::default()),
        ]);
        assert!(runtime.selected_for_rollout(7));
        assert!(!runtime.selected_for_rollout(8));
        assert!(runtime.enabled_for(7, &settings));
        assert!(!runtime.enabled_for(8, &settings));
        assert!(!runtime.enabled_for(9, &settings));
        assert!(!runtime.enabled_for(10, &settings));
    }
}
