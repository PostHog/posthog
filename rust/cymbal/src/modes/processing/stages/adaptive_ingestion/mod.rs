mod ledger;
mod loops;
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
use common_redis::{
    CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat, ScriptRunner,
};
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
        ADAPTIVE_INGESTION_CLIENT_CAP_REACHED, ADAPTIVE_INGESTION_DECISIONS,
        ADAPTIVE_INGESTION_PROJECT_CAP_REACHED, ADAPTIVE_INGESTION_REDIS_ERRORS,
        ADAPTIVE_INGESTION_STAGE,
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

use ledger::{group_clients, Ledger, TeamSnapshot};
use loops::{LoopDecision, LoopRule};
use project::{ProjectDecision, ProjectRule};

const VERSION: u32 = 2;
const MAX_CONCURRENT_GROUPS: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum Decision {
    Keep,
    Collapse,
    SampleProject,
    Error,
}

impl Decision {
    fn label(self) -> &'static str {
        match self {
            Self::Keep => "keep",
            Self::Collapse => "collapse",
            Self::SampleProject => "sample_project",
            Self::Error => "error",
        }
    }

    fn rule(self) -> &'static str {
        match self {
            Self::Keep | Self::Error => "none",
            Self::Collapse => "loop",
            Self::SampleProject => "project",
        }
    }
}

pub struct AdaptiveIngestionRuntime {
    redis: Arc<dyn ScriptRunner>,
    teams: HashSet<i32>,
    team_percent: u8,
    ledger: Ledger,
    loops: LoopRule,
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
            || config.adaptive_ingestion_loop_short_limit == 0
            || config.adaptive_ingestion_loop_day_limit == 0
            || config.adaptive_ingestion_loop_client_cap == 0
        {
            return Err(UnhandledError::Other(
                "invalid adaptive ingestion rollout or limits".into(),
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
            ledger: Ledger {
                client_cap: config.adaptive_ingestion_loop_client_cap,
            },
            loops: LoopRule {
                short_limit: config.adaptive_ingestion_loop_short_limit,
                day_limit: config.adaptive_ingestion_loop_day_limit,
            },
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
        let metrics = apply_shadow(runtime, &settings, Utc::now().timestamp(), &mut items).await;
        self.emit_metrics(metrics);
        Ok(Batch::from(items))
    }
}

struct TeamEvent {
    idx: usize,
    uuid: Uuid,
    issue_id: Uuid,
    client: Option<String>,
}

struct EventOutcome {
    idx: usize,
    decision: Decision,
    looped: Option<LoopDecision>,
    project: Option<ProjectDecision>,
}

/// Count every enabled team's events of the batch, then attach the decision
/// each rule would take. The stage fails open: it never removes an event.
async fn apply_shadow(
    runtime: &Arc<AdaptiveIngestionRuntime>,
    settings: &HashMap<i32, RateLimitSettings>,
    now: i64,
    items: &mut [RateCheckedPipelineItem],
) -> HashMap<(i32, Decision), u32> {
    let mut teams: HashMap<i32, Vec<TeamEvent>> = HashMap::new();
    for (idx, item) in items.iter().enumerate() {
        let Ok(event) = item else { continue };
        if !runtime.enabled_for(event.team_id(), settings) {
            continue;
        }
        teams.entry(event.team_id()).or_default().push(TeamEvent {
            idx,
            uuid: event.uuid(),
            issue_id: event.issue().id,
            client: event.client_id().map(str::to_owned),
        });
    }

    let outcomes: Vec<_> = stream::iter(teams.into_iter().map(|(team_id, events)| {
        let runtime = Arc::clone(runtime);
        async move {
            let result = decide_team(&runtime, team_id, now, &events).await;
            (team_id, events, result)
        }
    }))
    .buffer_unordered(MAX_CONCURRENT_GROUPS)
    .collect()
    .await;

    let mut metrics = HashMap::new();
    for (team_id, events, result) in outcomes {
        match result {
            Ok(event_outcomes) => {
                for outcome in event_outcomes {
                    let decision = outcome.decision;
                    counter!(ADAPTIVE_INGESTION_DECISIONS, "rule" => decision.rule(), "decision" => decision.label())
                        .increment(1);
                    if outcome
                        .looped
                        .is_some_and(|looped| looped.client_cap_reached)
                    {
                        counter!(ADAPTIVE_INGESTION_CLIENT_CAP_REACHED).increment(1);
                    }
                    if outcome.project.is_some_and(|project| project.cap_started) {
                        counter!(ADAPTIVE_INGESTION_PROJECT_CAP_REACHED).increment(1);
                    }
                    *metrics.entry((team_id, decision)).or_insert(0) += 1;
                    if let Ok(event) = &mut items[outcome.idx] {
                        set_decision(event, decision, now);
                        set_rule_properties(event, &outcome);
                    }
                }
            }
            Err(err) => {
                warn!(team_id, "adaptive ingestion ledger failed open: {err}");
                counter!(ADAPTIVE_INGESTION_REDIS_ERRORS).increment(events.len() as u64);
                counter!(ADAPTIVE_INGESTION_DECISIONS, "rule" => "none", "decision" => "error")
                    .increment(events.len() as u64);
                heal_on_connection_error(runtime, &err);
                for team_event in events {
                    if let Ok(event) = &mut items[team_event.idx] {
                        set_decision(event, Decision::Keep, now);
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

async fn decide_team(
    runtime: &AdaptiveIngestionRuntime,
    team_id: i32,
    now: i64,
    events: &[TeamEvent],
) -> Result<Vec<EventOutcome>, CustomRedisError> {
    let clients: Vec<_> = events
        .iter()
        .map(|event| (event.issue_id, event.client.as_deref()))
        .collect();
    let (groups, membership) = group_clients(&clients);
    let total = events.len() as u32;
    let snapshot = runtime
        .ledger
        .record(runtime.redis.as_ref(), team_id, now, total, &groups)
        .await?;

    let outcomes = decide_events(runtime, team_id, &snapshot, events, &membership);
    let removed = outcomes
        .iter()
        .filter(|outcome| outcome.decision == Decision::Collapse)
        .count() as u32;
    if removed > 0 {
        // The decisions of this batch are already final. A lost write only makes
        // later project counts of the day too high, so it does not fail the batch.
        if let Err(err) = runtime
            .ledger
            .record_removed(runtime.redis.as_ref(), team_id, now, removed)
            .await
        {
            warn!(
                team_id,
                "adaptive ingestion failed to record removed events: {err}"
            );
            counter!(ADAPTIVE_INGESTION_REDIS_ERRORS).increment(u64::from(removed));
        }
    }
    Ok(outcomes)
}

fn decide_events(
    runtime: &AdaptiveIngestionRuntime,
    team_id: i32,
    snapshot: &TeamSnapshot,
    events: &[TeamEvent],
    membership: &[Option<usize>],
) -> Vec<EventOutcome> {
    let mut positions = vec![0u64; snapshot.clients.len()];
    let mut outcomes: Vec<EventOutcome> = events
        .iter()
        .zip(membership)
        .map(|(event, group)| {
            let looped = group.map(|group| {
                positions[group] += 1;
                runtime
                    .loops
                    .evaluate(snapshot.clients[group], positions[group])
            });
            EventOutcome {
                idx: event.idx,
                decision: if looped.is_some_and(|looped| looped.collapsed) {
                    Decision::Collapse
                } else {
                    Decision::Keep
                },
                looped,
                project: None,
            }
        })
        .collect();

    // The project cap counts only what the loop rule kept.
    let kept: Vec<usize> = (0..outcomes.len())
        .filter(|position| outcomes[*position].decision == Decision::Keep)
        .collect();
    let kept_uuids: Vec<Uuid> = kept.iter().map(|position| events[*position].uuid).collect();
    let kept_before = snapshot.today.kept().saturating_sub(events.len() as u64);
    let decisions = runtime
        .project
        .evaluate(team_id, kept_before, &snapshot.history, &kept_uuids);
    for (position, project) in kept.into_iter().zip(decisions) {
        if project.sampled {
            outcomes[position].decision = Decision::SampleProject;
        }
        outcomes[position].project = Some(project);
    }
    outcomes
}

fn heal_on_connection_error(runtime: &Arc<AdaptiveIngestionRuntime>, err: &CustomRedisError) {
    if redis_heal::is_connection_error(err) {
        let redis = Arc::clone(&runtime.redis);
        runtime
            .heal_gate
            .spawn_heal(async move { redis.heal().await });
    }
}

fn set_decision(
    event: &mut ExceptionEvent<crate::types::exception_event::RateChecked>,
    decision: Decision,
    now: i64,
) {
    event.props.insert(
        "$adaptive_ingestion_decision".into(),
        Value::String(decision.label().into()),
    );
    event.props.insert(
        "$adaptive_ingestion_rule".into(),
        Value::String(decision.rule().into()),
    );
    // The rules bucket by processing time, which can differ from the event timestamp.
    event
        .props
        .insert("$adaptive_ingestion_timestamp".into(), Value::from(now));
    event
        .props
        .insert("$adaptive_ingestion_version".into(), Value::from(VERSION));
}

fn set_rule_properties(
    event: &mut ExceptionEvent<crate::types::exception_event::RateChecked>,
    outcome: &EventOutcome,
) {
    let client = match outcome.looped {
        None => "no_client",
        Some(looped) if looped.client_cap_reached => "client_cap_reached",
        Some(_) => "counted",
    };
    event.props.insert(
        "$adaptive_ingestion_client".into(),
        Value::String(client.into()),
    );
    if let Some(count) = outcome.looped.and_then(|looped| looped.short_count) {
        event.props.insert(
            "$adaptive_ingestion_client_count".into(),
            Value::from(count),
        );
    }
    if let Some(project) = outcome.project {
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
                    Decision::Collapse => Kind::AdaptiveIngestionLoop,
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
            distinct_id: None,
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

    fn runtime(
        redis: Arc<FakeRunner>,
        loops: LoopRule,
        project: ProjectRule,
    ) -> Arc<AdaptiveIngestionRuntime> {
        Arc::new(AdaptiveIngestionRuntime {
            redis,
            teams: HashSet::from([7]),
            team_percent: 0,
            ledger: Ledger { client_cap: 50_000 },
            loops,
            project,
            heal_gate: HealGate::new(),
        })
    }

    fn enabled(team_ids: &[i32]) -> HashMap<i32, RateLimitSettings> {
        team_ids
            .iter()
            .map(|team_id| {
                (
                    *team_id,
                    RateLimitSettings {
                        adaptive_ingestion_enabled: true,
                        ..Default::default()
                    },
                )
            })
            .collect()
    }

    fn ledger_reply(today: i64, clients: &[(i64, i64)]) -> Vec<i64> {
        std::iter::once(today)
            .chain(std::iter::repeat_n(0, 29))
            .chain(clients.iter().flat_map(|(day, short)| [*day, *short]))
            .collect()
    }

    fn decisions(items: &[RateCheckedPipelineItem]) -> Vec<&str> {
        items
            .iter()
            .map(|item| {
                item.as_ref().unwrap().properties()["$adaptive_ingestion_decision"]
                    .as_str()
                    .unwrap()
            })
            .collect()
    }

    #[tokio::test]
    async fn project_shadow_marks_overflow_without_removing_events() {
        let runtime = runtime(
            FakeRunner::returning(ledger_reply(5, &[])),
            LoopRule::default(),
            ProjectRule {
                multiplier: 3.0,
                floor: 1,
                keep_percent: 0,
            },
        );
        let issue = Uuid::now_v7();
        let mut items = vec![
            rate_checked_event(7, issue),
            rate_checked_event(7, issue),
            rate_checked_event(7, issue),
            rate_checked_event(8, issue),
            Err(crate::error::EventError::RateLimitedProject(7)),
        ];
        let metrics = apply_shadow(&runtime, &enabled(&[7, 8]), 600, &mut items).await;
        assert!(items[..4].iter().all(Result::is_ok));
        assert!(matches!(
            items[4],
            Err(crate::error::EventError::RateLimitedProject(7))
        ));
        assert_eq!(metrics.get(&(7, Decision::Keep)), Some(&1));
        assert_eq!(metrics.get(&(7, Decision::SampleProject)), Some(&2));
        assert_eq!(
            decisions(&items[..3]),
            ["keep", "sample_project", "sample_project"]
        );
        assert_eq!(
            items[0].as_ref().unwrap().properties()["$adaptive_ingestion_rule"],
            "none"
        );
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
        assert_eq!(stored["$adaptive_ingestion_client"], "no_client");
        assert_eq!(stored["$adaptive_ingestion_timestamp"], 600);
        assert!(items[3]
            .as_ref()
            .unwrap()
            .properties()
            .get("$adaptive_ingestion_version")
            .is_none());

        let mut opted_out = vec![rate_checked_event(7, issue)];
        assert!(apply_shadow(
            &runtime,
            &HashMap::from([(7, RateLimitSettings::default())]),
            600,
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
    async fn loop_shadow_collapses_repeats_and_keeps_them_out_of_the_project_count() {
        let runtime = runtime(
            FakeRunner::returning(ledger_reply(4, &[(0, 0), (0, 0)])),
            LoopRule {
                short_limit: 2,
                day_limit: 100,
            },
            ProjectRule {
                multiplier: 1.0,
                floor: 2,
                keep_percent: 0,
            },
        );
        let issue = Uuid::now_v7();
        let from = |client: &str| {
            let mut item = rate_checked_event(7, issue);
            item.as_mut().unwrap().distinct_id = Some(client.into());
            item
        };
        let mut items = vec![
            from("looping"),
            from("looping"),
            from("looping"),
            from("other"),
        ];
        let metrics = apply_shadow(&runtime, &enabled(&[7]), 600, &mut items).await;

        assert!(items.iter().all(Result::is_ok));
        assert_eq!(
            decisions(&items),
            ["keep", "keep", "collapse", "sample_project"]
        );
        assert_eq!(metrics.get(&(7, Decision::Collapse)), Some(&1));
        let collapsed = items[2].as_ref().unwrap().properties();
        assert_eq!(collapsed["$adaptive_ingestion_rule"], "loop");
        assert_eq!(collapsed["$adaptive_ingestion_client"], "counted");
        assert_eq!(collapsed["$adaptive_ingestion_client_count"], 3);
        assert!(collapsed.get("$adaptive_ingestion_count").is_none());
        assert_eq!(
            items[3].as_ref().unwrap().properties()["$adaptive_ingestion_count"],
            3
        );
    }

    #[tokio::test]
    async fn ledger_failure_keeps_events_and_marks_error() {
        let runtime = runtime(
            FakeRunner::failing(),
            LoopRule::default(),
            ProjectRule::default(),
        );
        let mut items = vec![rate_checked_event(7, Uuid::now_v7())];
        let metrics = apply_shadow(&runtime, &enabled(&[7]), 600, &mut items).await;
        assert!(items[0].is_ok());
        assert_eq!(metrics.get(&(7, Decision::Error)), Some(&1));
        let props = items[0].as_ref().unwrap().properties();
        assert_eq!(props["$adaptive_ingestion_decision"], "keep");
        assert_eq!(props["$adaptive_ingestion_error"], true);
    }

    #[test]
    fn rollout_requires_preference_and_team_selection() {
        let runtime = runtime(
            FakeRunner::failing(),
            LoopRule::default(),
            ProjectRule::default(),
        );
        let mut settings = enabled(&[7, 8]);
        settings.insert(9, RateLimitSettings::default());
        assert!(runtime.selected_for_rollout(7));
        assert!(!runtime.selected_for_rollout(8));
        assert!(runtime.enabled_for(7, &settings));
        assert!(!runtime.enabled_for(8, &settings));
        assert!(!runtime.enabled_for(9, &settings));
        assert!(!runtime.enabled_for(10, &settings));
    }
}
