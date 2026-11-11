mod rule;

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::Duration,
};

use chrono::Utc;
use common_kafka::{
    kafka_messages::app_metrics2::{AppMetric2, Kind, Source},
    kafka_producer::send_iter_to_kafka,
    APP_METRICS2_TOPIC,
};
use common_redis::{CompressionConfig, RedisClient, RedisValueFormat, ScriptRunner};
use futures::stream::{self, StreamExt};
use metrics::counter;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    metric_consts::{ADAPTIVE_INGESTION_EVENTS, ADAPTIVE_INGESTION_STAGE},
    modes::processing::{
        config::ProcessingConfig,
        ledger::{Ledger, Window, WindowCounts},
        redis_heal::{self, HealGate},
        rules::rate_limit::RateLimitSettings,
    },
    stages::pipeline::RateCheckedPipelineItem,
    types::{
        batch::Batch,
        exception_event::{ExceptionEvent, RateChecked},
        stage::{Stage, StageResult},
    },
};

use rule::{Reading, Thresholds};

const VERSION: u32 = 1;
const MAX_CONCURRENT_TEAMS: usize = 256;

const RECENT: Window = Window {
    width_seconds: 300,
    buckets: 12,
    per_issue: true,
};
const HOURLY: Window = Window {
    width_seconds: 3_600,
    buckets: 24,
    per_issue: true,
};
const DAILY: Window = Window {
    width_seconds: 86_400,
    buckets: 29,
    per_issue: false,
};

const SEEN: &str = "seen";
const OVER_ISSUE_LINE: &str = "over_issue_line";
const OVER_PROJECT_LINE: &str = "over_project_line";
const NO_BASELINE: &str = "no_baseline";
const ERROR: &str = "error";

type Tally = HashMap<(i32, Option<Uuid>, &'static str), u32>;

pub struct AdaptiveIngestionRuntime {
    redis: Arc<dyn ScriptRunner>,
    teams: HashSet<i32>,
    team_percent: u8,
    thresholds: Thresholds,
    ledger: Ledger,
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
        let thresholds = Thresholds {
            issue_hour: config.adaptive_ingestion_issue_hour_multiple,
            issue_day: config.adaptive_ingestion_issue_day_multiple,
            project_day: config.adaptive_ingestion_project_day_multiple,
        };
        if config.adaptive_ingestion_team_percent > 100 || !thresholds.is_valid() {
            return Err(UnhandledError::Other(
                "invalid adaptive ingestion rollout or thresholds".into(),
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
        let timeout = |ms: u64| (ms != 0).then(|| Duration::from_millis(ms));
        let redis = RedisClient::with_config(
            config.issue_buckets_redis_url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            timeout(config.redis_response_timeout_ms),
            timeout(config.redis_connection_timeout_ms),
        )
        .await?;
        Ok(Some(Arc::new(Self::new(
            Arc::new(redis),
            teams,
            config.adaptive_ingestion_team_percent,
            thresholds,
        ))))
    }

    fn new(
        redis: Arc<dyn ScriptRunner>,
        teams: HashSet<i32>,
        team_percent: u8,
        thresholds: Thresholds,
    ) -> Self {
        Self {
            redis,
            teams,
            team_percent,
            thresholds,
            ledger: Ledger {
                windows: vec![RECENT, HOURLY, DAILY],
            },
            heal_gate: HealGate::new(),
        }
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

#[derive(Debug, Clone, Copy, PartialEq, Default)]
struct Verdict {
    history_days: usize,
    reading: Option<Reading>,
    over_issue_line: bool,
    over_project_line: bool,
}

/// `issues` holds, per event of the team in batch order, the index of its issue in the ledger call.
fn decide_team(
    thresholds: &Thresholds,
    now: i64,
    counts: &[WindowCounts],
    issues: &[usize],
) -> Vec<Verdict> {
    let (recent, hourly, daily) = (&counts[0], &counts[1], &counts[2]);
    let previous_days = &daily.team.counts[1..];
    let history_days = previous_days.iter().filter(|n| **n > 0).count();
    let typical_day = rule::typical_day(previous_days);
    let mut project_day = hourly.team.rolling(now);
    let mut issue_hour: Vec<f64> = recent.issues.iter().map(|s| s.rolling(now)).collect();
    let mut issue_day: Vec<f64> = hourly.issues.iter().map(|s| s.rolling(now)).collect();

    // The ledger counts include the whole batch. Walking it backwards gives each event the counts at its own
    // position, so the first events of a batch that crosses a line stay under it.
    let mut verdicts: Vec<Verdict> = issues
        .iter()
        .rev()
        .map(|&issue| {
            let reading = typical_day.map(|typical_day| Reading {
                typical_day,
                issue_hour: issue_hour[issue],
                issue_day: issue_day[issue],
                project_day,
            });
            project_day -= 1.0;
            issue_hour[issue] -= 1.0;
            issue_day[issue] -= 1.0;
            Verdict {
                history_days,
                reading,
                over_issue_line: reading.is_some_and(|r| thresholds.over_issue_line(&r)),
                over_project_line: reading.is_some_and(|r| thresholds.over_project_line(&r)),
            }
        })
        .collect();
    verdicts.reverse();
    verdicts
}

async fn apply_shadow(
    runtime: &Arc<AdaptiveIngestionRuntime>,
    settings: &HashMap<i32, RateLimitSettings>,
    now: i64,
    items: &mut [RateCheckedPipelineItem],
) -> Tally {
    let mut teams: HashMap<i32, Vec<(usize, Uuid)>> = HashMap::new();
    for (idx, item) in items.iter().enumerate() {
        let Ok(event) = item else { continue };
        if runtime.enabled_for(event.team_id(), settings) {
            teams
                .entry(event.team_id())
                .or_default()
                .push((idx, event.issue().id));
        }
    }

    let outcomes: Vec<_> = stream::iter(teams.into_iter().map(|(team_id, events)| {
        let runtime = Arc::clone(runtime);
        async move {
            let mut issue_counts: Vec<(Uuid, u32)> = Vec::new();
            let mut positions: HashMap<Uuid, usize> = HashMap::new();
            let issues: Vec<usize> = events
                .iter()
                .map(|(_, issue_id)| {
                    let position = *positions.entry(*issue_id).or_insert_with(|| {
                        issue_counts.push((*issue_id, 0));
                        issue_counts.len() - 1
                    });
                    issue_counts[position].1 += 1;
                    position
                })
                .collect();
            let verdicts = runtime
                .ledger
                .record(runtime.redis.as_ref(), team_id, now, &issue_counts)
                .await
                .map(|counts| decide_team(&runtime.thresholds, now, &counts, &issues));
            (team_id, events, verdicts)
        }
    }))
    .buffer_unordered(MAX_CONCURRENT_TEAMS)
    .collect()
    .await;

    let mut tally = Tally::new();
    let mut outcome_counts: HashMap<&'static str, u64> = HashMap::new();
    for (team_id, events, verdicts) in outcomes {
        let verdicts = match verdicts {
            Ok(verdicts) => verdicts,
            Err(err) => {
                warn!(team_id, "adaptive ingestion counters failed open: {err}");
                *outcome_counts.entry(ERROR).or_default() += events.len() as u64;
                if redis_heal::is_connection_error(&err) {
                    let redis = Arc::clone(&runtime.redis);
                    runtime
                        .heal_gate
                        .spawn_heal(async move { redis.heal().await });
                }
                for (idx, _) in events {
                    if let Ok(event) = &mut items[idx] {
                        set(event, "version", VERSION);
                        set(event, "error", true);
                    }
                }
                continue;
            }
        };
        for ((idx, issue_id), verdict) in events.into_iter().zip(verdicts) {
            let mut names = vec![SEEN];
            if verdict.reading.is_none() {
                *outcome_counts.entry(NO_BASELINE).or_default() += 1;
            }
            if verdict.over_issue_line {
                names.push(OVER_ISSUE_LINE);
                *tally
                    .entry((team_id, Some(issue_id), OVER_ISSUE_LINE))
                    .or_default() += 1;
            }
            if verdict.over_project_line {
                names.push(OVER_PROJECT_LINE);
            }
            for name in names {
                *tally.entry((team_id, None, name)).or_default() += 1;
                *outcome_counts.entry(name).or_default() += 1;
            }
            if let Ok(event) = &mut items[idx] {
                stamp(event, &verdict);
            }
        }
    }
    for (outcome, count) in outcome_counts {
        counter!(ADAPTIVE_INGESTION_EVENTS, "outcome" => outcome).increment(count);
    }
    tally
}

fn set(event: &mut ExceptionEvent<RateChecked>, name: &str, value: impl Into<Value>) {
    event
        .props
        .insert(format!("$adaptive_ingestion_{name}"), value.into());
}

fn stamp(event: &mut ExceptionEvent<RateChecked>, verdict: &Verdict) {
    let rounded = |value: f64| (value * 100.0).round() / 100.0;
    set(event, "version", VERSION);
    set(event, "history_days", verdict.history_days);
    let Some(reading) = verdict.reading else {
        return;
    };
    set(event, "typical_day", rounded(reading.typical_day));
    set(
        event,
        "issue_hour_ratio",
        rounded(reading.issue_hour_ratio()),
    );
    set(event, "issue_day_ratio", rounded(reading.issue_day_ratio()));
    set(
        event,
        "project_day_ratio",
        rounded(reading.project_day_ratio()),
    );
    set(event, "over_issue_line", verdict.over_issue_line);
    set(event, "over_project_line", verdict.over_project_line);
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
        let tally = apply_shadow(runtime, &settings, Utc::now().timestamp(), &mut items).await;
        self.emit_app_metrics(tally);
        Ok(Batch::from(items))
    }
}

impl AdaptiveIngestionStage {
    fn emit_app_metrics(&self, tally: Tally) {
        if tally.is_empty() {
            return;
        }
        let now = Utc::now();
        let app_metrics: Vec<_> = tally
            .into_iter()
            .map(|((team_id, issue_id, name), count)| AppMetric2 {
                team_id: team_id as u32,
                timestamp: now,
                app_source: Source::Exceptions,
                app_source_id: match issue_id {
                    Some(issue_id) => issue_id.to_string(),
                    None => format!("{team_id}:exceptions:adaptive"),
                },
                instance_id: None,
                metric_kind: Kind::AdaptiveIngestion,
                metric_name: name.to_string(),
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
    use crate::{
        issue_resolution::{Issue, IssueStatus},
        modes::processing::{
            ledger::Series,
            types::{
                exception_event::{Linked, ResolvedMetadata, SelectedFingerprint},
                ExceptionList,
            },
        },
        test_support::{start_redis, FakeRunner},
    };

    const THRESHOLDS: Thresholds = Thresholds {
        issue_hour: 12.0,
        issue_day: 2.0,
        project_day: 3.0,
    };

    fn event(team_id: i32, issue_id: Uuid) -> RateCheckedPipelineItem {
        Ok(ExceptionEvent {
            uuid: Uuid::now_v7(),
            team_id,
            timestamp: String::new(),
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

    fn runtime(redis: Arc<dyn ScriptRunner>) -> Arc<AdaptiveIngestionRuntime> {
        Arc::new(AdaptiveIngestionRuntime::new(
            redis,
            HashSet::from([7]),
            0,
            THRESHOLDS,
        ))
    }

    fn enabled() -> HashMap<i32, RateLimitSettings> {
        let setting = RateLimitSettings {
            adaptive_ingestion_enabled: true,
            ..Default::default()
        };
        HashMap::from([(7, setting)])
    }

    fn property<'a>(item: &'a RateCheckedPipelineItem, name: &str) -> Option<&'a Value> {
        item.as_ref()
            .unwrap()
            .props
            .get(&format!("$adaptive_ingestion_{name}"))
    }

    fn series(window: Window, newest: u64) -> Series {
        let mut counts = vec![0; window.buckets + 1];
        counts[0] = newest;
        Series { window, counts }
    }

    #[test]
    fn only_the_events_past_a_line_in_a_batch_are_over_it() {
        let mut days = series(DAILY, 0);
        days.counts[1..].fill(240);
        let counts = [
            WindowCounts {
                team: series(RECENT, 0),
                active_issues: vec![],
                issues: vec![series(RECENT, 10), series(RECENT, 2)],
            },
            WindowCounts {
                team: series(HOURLY, 722),
                active_issues: vec![],
                issues: vec![series(HOURLY, 482), series(HOURLY, 2)],
            },
            WindowCounts {
                team: days,
                active_issues: vec![],
                issues: vec![],
            },
        ];

        let verdicts = decide_team(&THRESHOLDS, 0, &counts, &[0, 0, 1, 0, 0, 1]);

        let over_issue: Vec<bool> = verdicts.iter().map(|v| v.over_issue_line).collect();
        assert_eq!(over_issue, [false, false, false, true, true, false]);
        let over_project: Vec<bool> = verdicts.iter().map(|v| v.over_project_line).collect();
        assert_eq!(over_project, [false, false, false, false, true, true]);
        assert_eq!(verdicts[5].history_days, 29);
        assert_eq!(verdicts[5].reading.unwrap().issue_day, 2.0);
    }

    #[tokio::test]
    async fn keeps_every_event_and_flags_the_error_when_redis_fails() {
        let issue = Uuid::now_v7();
        let mut items = vec![event(7, issue), event(8, issue)];

        let tally = apply_shadow(&runtime(FakeRunner::failing()), &enabled(), 0, &mut items).await;

        assert!(tally.is_empty());
        assert_eq!(property(&items[0], "error"), Some(&Value::Bool(true)));
        assert!(items[1].as_ref().unwrap().props.is_empty());
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn marks_a_surging_issue_once_the_project_has_a_typical_day() {
        let (redis, _container) = start_redis().await;
        let runtime = runtime(redis.clone());
        let (steady, surging) = (Uuid::now_v7(), Uuid::now_v7());
        let day = 86_400;

        let mut first_day = vec![event(7, steady)];
        apply_shadow(&runtime, &enabled(), 0, &mut first_day).await;
        assert_eq!(property(&first_day[0], "history_days"), Some(&0.into()));
        assert_eq!(property(&first_day[0], "over_issue_line"), None);

        for past in 1..14 {
            let mut items: Vec<_> = (0..240).map(|_| event(7, steady)).collect();
            apply_shadow(&runtime, &enabled(), past * day, &mut items).await;
        }

        let mut items: Vec<_> = (0..130).map(|_| event(7, surging)).collect();
        items.push(event(7, steady));
        items.push(event(8, surging));
        let tally = apply_shadow(&runtime, &enabled(), 14 * day, &mut items).await;

        // 13 days of 240 and one day of 1 give a typical day of 240, so a typical hour of 10 and a line at 120.
        assert_eq!(property(&items[0], "typical_day"), Some(&240.0.into()));
        assert_eq!(
            property(&items[119], "over_issue_line"),
            Some(&false.into())
        );
        assert_eq!(property(&items[120], "over_issue_line"), Some(&true.into()));
        assert_eq!(
            property(&items[120], "issue_hour_ratio"),
            Some(&12.1.into())
        );
        assert_eq!(
            property(&items[130], "over_issue_line"),
            Some(&false.into())
        );
        assert_eq!(
            property(&items[130], "over_project_line"),
            Some(&false.into())
        );
        assert!(items[131].as_ref().unwrap().props.is_empty());
        assert_eq!(tally[&(7, None, SEEN)], 131);
        assert_eq!(tally[&(7, None, OVER_ISSUE_LINE)], 10);
        assert_eq!(tally[&(7, Some(surging), OVER_ISSUE_LINE)], 10);
        assert!(!tally.contains_key(&(7, None, OVER_PROJECT_LINE)));
    }
}
