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

pub use limiter::{RateLimitDecision, RedisRateLimiter, RATE_LIMIT_LUA};

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
    /// Suffix used in the `app_metrics2` `app_source_id`, matching the Node.js limiter.
    fn app_source_suffix(self) -> &'static str {
        match self {
            LimitKind::PerIssue => "per_issue",
            LimitKind::Project => "global",
        }
    }

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

        // Group surviving (Ok) events by (team_id, issue_id). Suppressed / failed
        // events are already Err and never charged. Vec<usize> stays in input order.
        let mut groups: HashMap<(i32, Option<Uuid>), Vec<usize>> = HashMap::new();
        for (idx, item) in items.iter().enumerate() {
            if let Ok(props) = item {
                groups
                    .entry((props.team_id, props.issue_id))
                    .or_default()
                    .push(idx);
            }
        }

        if groups.is_empty() {
            return Ok(Batch::from(items));
        }

        let team_ids: HashSet<i32> = groups.keys().map(|(team_id, _)| *team_id).collect();
        let settings = self
            .ctx
            .team_manager
            .get_rate_limit_settings(&self.ctx.posthog_pool, team_ids)
            .await;

        let mut outcomes: HashMap<(i32, LimitKind, Outcome), u32> = HashMap::new();
        let mut drops: Vec<(usize, EventError)> = Vec::new();

        for ((team_id, issue_id), indices) in groups {
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
                    allowed,
                    limited,
                );
            }
            if let Some((allowed, limited)) = group.project {
                add_outcome(&mut outcomes, team_id, LimitKind::Project, allowed, limited);
            }
        }

        // Flip dropped slots Ok -> Err in place; length and order are preserved
        // (post-processing reattaches original events by index).
        for (idx, err) in drops {
            if let Some(slot) = items.get_mut(idx) {
                *slot = Err(err);
            }
        }

        self.emit_metrics(&outcomes).await;

        Ok(Batch::from(items))
    }
}

impl RateLimitingStage {
    async fn emit_metrics(&self, outcomes: &HashMap<(i32, LimitKind, Outcome), u32>) {
        if outcomes.is_empty() {
            return;
        }
        let now = Utc::now();
        let mut app_metrics: Vec<AppMetric2> = Vec::with_capacity(outcomes.len());

        for (&(team_id, kind, outcome), &count) in outcomes {
            counter!(
                RATE_LIMIT_OUTCOMES,
                "limit" => kind.label(),
                "outcome" => outcome.label(),
            )
            .increment(count as u64);

            app_metrics.push(AppMetric2 {
                team_id: team_id as u32,
                timestamp: now,
                app_source: Source::Exceptions,
                app_source_id: format!("{team_id}:exceptions:{}", kind.app_source_suffix()),
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
    outcomes: &mut HashMap<(i32, LimitKind, Outcome), u32>,
    team_id: i32,
    kind: LimitKind,
    allowed: u32,
    limited: u32,
) {
    if allowed > 0 {
        *outcomes
            .entry((team_id, kind, Outcome::Allowed))
            .or_insert(0) += allowed;
    }
    if limited > 0 {
        *outcomes
            .entry((team_id, kind, Outcome::RateLimited))
            .or_insert(0) += limited;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let out = classify_group(1, Some(Uuid::now_v7()), &indices, decision(2, 2), true, true);
        assert!(out.drops.is_empty());
        assert_eq!(out.per_issue, Some((2, 0)));
        assert_eq!(out.project, Some((2, 0)));
    }
}
