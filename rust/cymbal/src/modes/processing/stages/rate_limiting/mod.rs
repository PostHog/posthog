mod limiter;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::Utc;
use common_kafka::kafka_messages::app_metrics2::{AppMetric2, Kind, Source};
use common_kafka::kafka_producer::send_iter_to_kafka;
use common_kafka::APP_METRICS2_TOPIC;
use metrics::counter;
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::EventError,
    metric_consts::{RATE_LIMITING_STAGE, RATE_LIMIT_FAIL_OPEN, RATE_LIMIT_OUTCOMES},
    stages::pipeline::ExceptionEventPipelineItem,
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

use crate::modes::processing::rules::rate_limit::RateLimitSettings;

pub use limiter::{RateLimitDecision, RedisRateLimiter, ScriptRunner, RATE_LIMIT_LUA};

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum LimitKind {
    PerIssue,
    Project,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Outcome {
    Allowed,
    RateLimited,
}

impl LimitKind {
    fn label(self) -> &'static str {
        match self {
            LimitKind::PerIssue => "per_issue",
            LimitKind::Project => "project",
        }
    }
}

impl Outcome {
    fn label(self) -> &'static str {
        match self {
            Outcome::Allowed => "allowed",
            Outcome::RateLimited => "rate_limited",
        }
    }
}

/// Tally key for one `app_metrics2` row. Per-issue rows carry their issue id so
/// each issue gets its own `app_source_id` (matching the Node.js limiter, which
/// keys per-issue metrics by the bare Cymbal issue id); project rows use `None`
/// and aggregate per team under `{team}:exceptions:global`.
type OutcomeKey = (i32, LimitKind, Option<Uuid>, Outcome);

/// Drops rate-limited exception events as soon as their `issue_id` is known
/// (right after `LinkingStage`, before `AlertingStage`). Marked-dropped events
/// become `Err`, so spike detection skips them and post-processing turns them
/// into `null`. A no-op when the limiter is disabled.
#[derive(Clone)]
pub struct RateLimitingStage {
    ctx: Arc<AppContext>,
}

impl From<&Arc<AppContext>> for RateLimitingStage {
    fn from(ctx: &Arc<AppContext>) -> Self {
        Self { ctx: ctx.clone() }
    }
}

impl Stage for RateLimitingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        RATE_LIMITING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let Some(limiter) = self.ctx.rate_limiter.clone() else {
            return Ok(batch); // limiter disabled — pass everything through
        };

        let mut items: Vec<ExceptionEventPipelineItem> = batch.into();

        // Teams of the surviving (Ok) events. Suppressed / failed events are
        // already Err and are never charged.
        let team_ids: HashSet<i32> = items
            .iter()
            .filter_map(|item| item.as_ref().ok().map(|props| props.team_id))
            .collect();
        if team_ids.is_empty() {
            return Ok(Batch::from(items));
        }

        let settings = self
            .ctx
            .team_manager
            .get_rate_limit_settings(&self.ctx.posthog_pool, team_ids)
            .await;

        let outcomes = apply_rate_limits(
            &limiter,
            &settings,
            self.ctx.rate_limiter_enabled_team_ids.as_ref(),
            &mut items,
        )
        .await;

        self.emit_metrics(&outcomes).await;

        Ok(Batch::from(items))
    }
}

/// Core of `RateLimitingStage::process`, split out so it can be unit-tested with
/// an in-memory `ScriptRunner` (the stage itself needs a full `AppContext`).
///
/// Groups the surviving (`Ok`) events by (team_id, issue_id), charges each group
/// against the team's configured limits, and flips over-limit events to `Err` in
/// place — length and input order are preserved, so post-processing still
/// reattaches original events by index. Returns per-(team, limit, outcome)
/// tallies for metrics. Fails open per group: a limiter error keeps that group's
/// events and records a fail-open metric.
async fn apply_rate_limits(
    limiter: &RedisRateLimiter,
    settings: &HashMap<i32, RateLimitSettings>,
    enabled_teams: Option<&HashSet<i32>>,
    items: &mut [ExceptionEventPipelineItem],
) -> HashMap<OutcomeKey, u32> {
    // Group surviving (Ok) events by (team_id, issue_id). Vec<usize> stays in input order.
    let mut groups: HashMap<(i32, Option<Uuid>), Vec<usize>> = HashMap::new();
    for (idx, item) in items.iter().enumerate() {
        if let Ok(props) = item {
            groups
                .entry((props.team_id, props.issue_id))
                .or_default()
                .push(idx);
        }
    }

    let mut outcomes: HashMap<OutcomeKey, u32> = HashMap::new();
    let mut drops: Vec<(usize, EventError)> = Vec::new();

    // Group iteration order is nondeterministic (HashMap), and that's fine: per-issue
    // buckets are independent, and the shared project bucket admits the same *total*
    // whichever issue draws first — so every emitted metric is order-independent. Order
    // only shuffles which issue wins the project budget when it's the binding limit, and
    // those events are dropped either way. Within a group, input order is preserved
    // (indices pushed in order above; classify_group keeps the lowest first).
    for ((team_id, issue_id), indices) in groups {
        // Team allowlist: when set, only listed teams are rate-limited.
        if enabled_teams.is_some_and(|allowed| !allowed.contains(&team_id)) {
            continue;
        }

        let Some(team_settings) = settings.get(&team_id) else {
            continue; // no row → team hasn't opted in
        };

        // Per-issue limit only applies when we actually have an issue to key on.
        let per_issue = issue_id.and(team_settings.per_issue());
        let project = team_settings.project();
        if per_issue.is_none() && project.is_none() {
            continue;
        }

        let n = indices.len() as u32;
        let decision = match limiter
            .admit(team_id, issue_id, per_issue, project, n)
            .await
        {
            Ok(decision) => decision,
            Err(e) => {
                // Fail open: keep everything, but record it so we can alert on it.
                warn!("error-tracking rate limiter failed open for team {team_id}: {e}");
                counter!(RATE_LIMIT_FAIL_OPEN).increment(n as u64);
                continue;
            }
        };

        let group = classify_group(
            team_id,
            issue_id,
            &indices,
            decision,
            per_issue.is_some(),
            project.is_some(),
        );
        drops.extend(group.drops);
        if let Some((allowed, limited)) = group.per_issue {
            add_outcome(
                &mut outcomes,
                team_id,
                LimitKind::PerIssue,
                issue_id,
                allowed,
                limited,
            );
        }
        if let Some((allowed, limited)) = group.project {
            // Project rows aggregate across issues, so they carry no issue id.
            add_outcome(
                &mut outcomes,
                team_id,
                LimitKind::Project,
                None,
                allowed,
                limited,
            );
        }
    }

    // Flip dropped slots Ok -> Err in place; length and order are preserved
    // (post-processing reattaches original events by index).
    for (idx, err) in drops {
        if let Some(slot) = items.get_mut(idx) {
            *slot = Err(err);
        }
    }

    outcomes
}

impl RateLimitingStage {
    async fn emit_metrics(&self, outcomes: &HashMap<OutcomeKey, u32>) {
        if outcomes.is_empty() {
            return;
        }
        let now = Utc::now();
        let mut app_metrics: Vec<AppMetric2> = Vec::with_capacity(outcomes.len());

        for (&(team_id, kind, issue_id, outcome), &count) in outcomes {
            counter!(
                RATE_LIMIT_OUTCOMES,
                "limit" => kind.label(),
                "outcome" => outcome.label(),
            )
            .increment(count as u64);

            // Match the Node.js limiter's `app_metrics2` keys exactly: per-issue
            // rows are keyed by the bare Cymbal issue id; project rows by
            // `{team}:exceptions:global`.
            let app_source_id = match kind {
                LimitKind::PerIssue => issue_id
                    .expect("per-issue outcomes always carry an issue id")
                    .to_string(),
                LimitKind::Project => format!("{team_id}:exceptions:global"),
            };

            app_metrics.push(AppMetric2 {
                team_id: team_id as u32,
                timestamp: now,
                app_source: Source::Exceptions,
                app_source_id,
                instance_id: None,
                metric_kind: Kind::RateLimiting,
                metric_name: outcome.label().to_string(),
                count,
            });
        }

        let results = send_iter_to_kafka(
            &self.ctx.immediate_producer,
            APP_METRICS2_TOPIC,
            app_metrics,
        )
        .await;
        for result in results {
            if let Err(e) = result {
                warn!("failed to emit error-tracking rate-limit app_metric: {e}");
            }
        }
    }
}

struct GroupOutcome {
    drops: Vec<(usize, EventError)>,
    /// `(allowed, rate_limited)` for the per-issue limit, when enabled.
    per_issue: Option<(u32, u32)>,
    /// `(allowed, rate_limited)` for the project limit, when enabled. Only the
    /// per-issue survivors are offered to it.
    project: Option<(u32, u32)>,
}

/// Pure fan-out: given a limit decision, assign each of the `n` events (in input
/// order) to keep / project-drop / per-issue-drop, and tally per-limit outcomes.
///
/// Order within the group:
///   `[0, team_admitted)`              kept
///   `[team_admitted, issue_admitted)` dropped by the project limit
///   `[issue_admitted, n)`             dropped by the per-issue limit
fn classify_group(
    team_id: i32,
    issue_id: Option<Uuid>,
    indices: &[usize],
    decision: RateLimitDecision,
    per_issue_enabled: bool,
    project_enabled: bool,
) -> GroupOutcome {
    let n = indices.len() as u32;
    let issue_admitted = decision.issue_admitted as usize;
    let team_admitted = decision.team_admitted as usize;

    let mut drops = Vec::new();
    for (pos, &idx) in indices.iter().enumerate() {
        if pos >= issue_admitted {
            drops.push((
                idx,
                EventError::RateLimitedPerIssue(issue_id.unwrap_or_default()),
            ));
        } else if pos >= team_admitted {
            drops.push((idx, EventError::RateLimitedProject(team_id)));
        }
    }

    let per_issue =
        per_issue_enabled.then(|| (decision.issue_admitted, n - decision.issue_admitted));
    let project = project_enabled.then(|| {
        (
            decision.team_admitted,
            decision.issue_admitted - decision.team_admitted,
        )
    });

    GroupOutcome {
        drops,
        per_issue,
        project,
    }
}

fn add_outcome(
    outcomes: &mut HashMap<OutcomeKey, u32>,
    team_id: i32,
    kind: LimitKind,
    issue_id: Option<Uuid>,
    allowed: u32,
    limited: u32,
) {
    if allowed > 0 {
        *outcomes
            .entry((team_id, kind, issue_id, Outcome::Allowed))
            .or_insert(0) += allowed;
    }
    if limited > 0 {
        *outcomes
            .entry((team_id, kind, issue_id, Outcome::RateLimited))
            .or_insert(0) += limited;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::modes::processing::types::exception_properties::ExceptionProperties;
    use crate::modes::processing::types::ExceptionList;
    use async_trait::async_trait;
    use common_redis::CustomRedisError;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// A `ScriptRunner` that never touches Redis: returns a canned reply, or an
    /// error to drive the stage's fail-open path, and counts its invocations.
    struct FakeScriptRunner {
        result: Result<Vec<i64>, ()>,
        calls: AtomicUsize,
    }

    impl FakeScriptRunner {
        fn returning(reply: Vec<i64>) -> Self {
            Self {
                result: Ok(reply),
                calls: AtomicUsize::new(0),
            }
        }

        fn failing() -> Self {
            Self {
                result: Err(()),
                calls: AtomicUsize::new(0),
            }
        }

        fn call_count(&self) -> usize {
            self.calls.load(Ordering::Relaxed)
        }
    }

    #[async_trait]
    impl ScriptRunner for FakeScriptRunner {
        async fn eval_int_vec(
            &self,
            _script: &str,
            _keys: Vec<String>,
            _args: Vec<String>,
        ) -> Result<Vec<i64>, CustomRedisError> {
            self.calls.fetch_add(1, Ordering::Relaxed);
            match &self.result {
                Ok(reply) => Ok(reply.clone()),
                Err(()) => Err(CustomRedisError::Timeout),
            }
        }
    }

    fn limiter_with(runner: Arc<FakeScriptRunner>) -> RedisRateLimiter {
        RedisRateLimiter::new(runner, "test".to_string(), 3600)
    }

    fn settings(per_issue: Option<i32>, project: Option<i32>) -> RateLimitSettings {
        RateLimitSettings {
            per_issue_value: per_issue,
            per_issue_bucket_minutes: Some(60),
            project_value: project,
            project_bucket_minutes: Some(60),
        }
    }

    fn event(team_id: i32, issue_id: Option<Uuid>) -> ExceptionEventPipelineItem {
        Ok(ExceptionProperties {
            exception_list: ExceptionList(vec![]),
            exception_sources: None,
            exception_types: None,
            exception_messages: None,
            exception_functions: None,
            exception_handled: None,
            exception_releases: HashMap::new(),
            fingerprint: None,
            proposed_fingerprint: None,
            fingerprint_record: None,
            issue_id,
            proposed_issue_name: None,
            proposed_issue_description: None,
            debug_images: vec![],
            props: HashMap::new(),
            uuid: Uuid::now_v7(),
            timestamp: String::new(),
            team_id,
            issue: None,
        })
    }

    #[tokio::test]
    async fn fails_open_keeping_all_events_when_redis_errors() {
        let runner = Arc::new(FakeScriptRunner::failing());
        let limiter = limiter_with(runner.clone());
        let issue = Uuid::now_v7();
        let mut items: Vec<ExceptionEventPipelineItem> =
            (0..5).map(|_| event(1, Some(issue))).collect();
        let mut cfg = HashMap::new();
        cfg.insert(1, settings(Some(1), Some(1)));

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items).await;

        // Redis errored, so the whole group is kept (fail open): nothing is
        // flipped to Err, and no allowed/limited outcomes are tallied.
        assert!(items.iter().all(|item| item.is_ok()));
        assert_eq!(runner.call_count(), 1); // one group -> one (failed) redis call
        assert!(outcomes.is_empty());
    }

    #[tokio::test]
    async fn drops_over_limit_events_in_classify_order() {
        // One issue group of 5; per-issue admits 3, project admits 1 of those.
        let runner = Arc::new(FakeScriptRunner::returning(vec![3, 1]));
        let limiter = limiter_with(runner);
        let issue = Uuid::now_v7();
        let mut items: Vec<ExceptionEventPipelineItem> =
            (0..5).map(|_| event(7, Some(issue))).collect();
        let mut cfg = HashMap::new();
        cfg.insert(7, settings(Some(100), Some(100)));

        apply_rate_limits(&limiter, &cfg, None, &mut items).await;

        assert!(items[0].is_ok()); // kept
        assert!(matches!(items[1], Err(EventError::RateLimitedProject(7))));
        assert!(matches!(items[2], Err(EventError::RateLimitedProject(7))));
        assert!(matches!(items[3], Err(EventError::RateLimitedPerIssue(_))));
        assert!(matches!(items[4], Err(EventError::RateLimitedPerIssue(_))));
    }

    #[tokio::test]
    async fn per_issue_metrics_key_by_issue_global_aggregates_per_team() {
        // Every group: per-issue admits 3 of 5, project admits 1 of those 3.
        let runner = Arc::new(FakeScriptRunner::returning(vec![3, 1]));
        let limiter = limiter_with(runner);
        let (issue_a, issue_b) = (Uuid::now_v7(), Uuid::now_v7());
        let mut items: Vec<ExceptionEventPipelineItem> = (0..5)
            .map(|_| event(7, Some(issue_a)))
            .chain((0..5).map(|_| event(7, Some(issue_b))))
            .collect();
        let mut cfg = HashMap::new();
        cfg.insert(7, settings(Some(100), Some(100)));

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items).await;

        // Per-issue tallies are keyed by the individual issue id — one bucket per
        // issue — so each gets its own bare-UUID `app_source_id` like Node.js.
        assert_eq!(
            outcomes.get(&(7, LimitKind::PerIssue, Some(issue_a), Outcome::Allowed)),
            Some(&3)
        );
        assert_eq!(
            outcomes.get(&(7, LimitKind::PerIssue, Some(issue_b), Outcome::Allowed)),
            Some(&3)
        );
        // The project tally carries no issue id, so both issues fold into one
        // per-team row (`{team}:exceptions:global`): allowed 1+1, limited 2+2.
        assert_eq!(
            outcomes.get(&(7, LimitKind::Project, None, Outcome::Allowed)),
            Some(&2)
        );
        assert_eq!(
            outcomes.get(&(7, LimitKind::Project, None, Outcome::RateLimited)),
            Some(&4)
        );
    }

    #[tokio::test]
    async fn skips_team_without_settings_without_touching_redis() {
        let runner = Arc::new(FakeScriptRunner::returning(vec![0, 0]));
        let limiter = limiter_with(runner.clone());
        let mut items: Vec<ExceptionEventPipelineItem> =
            (0..3).map(|_| event(42, Some(Uuid::now_v7()))).collect();
        let cfg = HashMap::new(); // team 42 has no settings row

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items).await;

        assert!(items.iter().all(|item| item.is_ok())); // opted-out team untouched
        assert_eq!(runner.call_count(), 0); // and we never hit redis for it
        assert!(outcomes.is_empty());
    }

    #[tokio::test]
    async fn only_rate_limits_allowlisted_teams() {
        // Redis admits nothing, so any team that IS rate-limited loses its events.
        let runner = Arc::new(FakeScriptRunner::returning(vec![0, 0]));
        let limiter = limiter_with(runner.clone());
        let issue = Uuid::now_v7();
        let mut items: Vec<ExceptionEventPipelineItem> =
            vec![event(1, Some(issue)), event(2, Some(issue))];
        let mut cfg = HashMap::new();
        cfg.insert(1, settings(Some(1), Some(1)));
        cfg.insert(2, settings(Some(1), Some(1)));
        let allowed: HashSet<i32> = [1].into_iter().collect();

        apply_rate_limits(&limiter, &cfg, Some(&allowed), &mut items).await;

        assert!(items[0].is_err()); // team 1 is allowlisted -> rate-limited
        assert!(items[1].is_ok()); // team 2 is not -> untouched despite having settings
        assert_eq!(runner.call_count(), 1); // only the allowlisted team hit redis
    }

    fn decision(issue: u32, team: u32) -> RateLimitDecision {
        RateLimitDecision {
            issue_admitted: issue,
            team_admitted: team,
        }
    }

    #[test]
    fn fan_out_splits_keep_project_drop_per_issue_drop_in_order() {
        let issue = Uuid::now_v7();
        let indices = vec![10, 11, 12, 13, 14]; // n = 5
                                                // 3 passed per-issue, 1 of those passed project.
        let out = classify_group(7, Some(issue), &indices, decision(3, 1), true, true);

        // keep idx 10; project-drop 11,12; per-issue-drop 13,14.
        let mut by_idx: HashMap<usize, EventError> = out.drops.into_iter().collect();
        assert!(by_idx.remove(&10).is_none());
        assert_eq!(by_idx.remove(&11), Some(EventError::RateLimitedProject(7)));
        assert_eq!(by_idx.remove(&12), Some(EventError::RateLimitedProject(7)));
        assert_eq!(
            by_idx.remove(&13),
            Some(EventError::RateLimitedPerIssue(issue))
        );
        assert_eq!(
            by_idx.remove(&14),
            Some(EventError::RateLimitedPerIssue(issue))
        );
        assert!(by_idx.is_empty());

        assert_eq!(out.per_issue, Some((3, 2))); // 3 allowed, 2 limited
        assert_eq!(out.project, Some((1, 2))); // of the 3 survivors: 1 allowed, 2 limited
    }

    #[test]
    fn per_issue_disabled_only_reports_project_limit() {
        let indices = vec![0, 1, 2, 3];
        // issue limit disabled => admits all 4; project keeps 2.
        let out = classify_group(9, None, &indices, decision(4, 2), false, true);
        assert_eq!(out.per_issue, None);
        assert_eq!(out.project, Some((2, 2)));
        // 2 project drops, no per-issue drops (issue_admitted == n).
        assert_eq!(out.drops.len(), 2);
        assert!(out
            .drops
            .iter()
            .all(|(_, e)| matches!(e, EventError::RateLimitedProject(9))));
    }

    #[test]
    fn all_admitted_no_drops() {
        let indices = vec![0, 1];
        let out = classify_group(
            1,
            Some(Uuid::now_v7()),
            &indices,
            decision(2, 2),
            true,
            true,
        );
        assert!(out.drops.is_empty());
        assert_eq!(out.per_issue, Some((2, 0)));
        assert_eq!(out.project, Some((2, 0)));
    }
}
