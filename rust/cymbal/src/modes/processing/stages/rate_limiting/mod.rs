mod limiter;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::Utc;
use futures::stream::{self, StreamExt};

use common_kafka::kafka_messages::app_metrics2::{AppMetric2, Kind, Source};
use common_kafka::kafka_producer::send_iter_to_kafka;
use common_kafka::APP_METRICS2_TOPIC;
use hogvm::VmError;
use metrics::counter;
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::EventError,
    metric_consts::{
        RATE_LIMITING_STAGE, RATE_LIMIT_FAIL_OPEN, RATE_LIMIT_METRIC_EMIT, RATE_LIMIT_OUTCOMES,
    },
    stages::pipeline::ExceptionEventPipelineItem,
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

use crate::modes::processing::rules::bypass::BypassRule;
use crate::modes::processing::rules::rate_limit::RateLimitSettings;
use crate::modes::processing::types::exception_properties::ExceptionProperties;

pub use limiter::{RateLimitDecision, RedisRateLimiter, ScriptRunner, RATE_LIMIT_LUA};

/// Ceiling on concurrent Redis admits per batch — bounds the pathological tail (many
/// tiny, all-distinct issues). Normal batches stay under it and fan out fully.
const MAX_CONCURRENT_ADMITS: usize = 256;

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum LimitKind {
    PerIssue,
    Project,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Outcome {
    Allowed,
    RateLimited,
    // Matched a bypass rule: kept and charged no tokens, recorded so it surfaces in app metrics.
    Bypassed,
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
            Outcome::Bypassed => "bypassed",
        }
    }
}

/// Tally key for one `app_metrics2` row. Per-issue rows carry their issue id (their own
/// `app_source_id`, matching Node.js); project rows use `None` and aggregate per team
/// under `{team}:exceptions:global`.
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

        // Bypass rules exempt matching events from rate limiting: they're kept, never charged,
        // and recorded as "bypassed" instead of being offered to the limiter below.
        let (bypassed, bypass_outcomes) = self.apply_bypass(&settings, &items).await;

        let mut outcomes = apply_rate_limits(
            &limiter,
            &settings,
            self.ctx.rate_limiter_enabled_team_ids.as_ref(),
            &mut items,
            &bypassed,
        )
        .await;
        for (key, count) in bypass_outcomes {
            *outcomes.entry(key).or_insert(0) += count;
        }

        self.emit_metrics(&outcomes).await;

        Ok(Batch::from(items))
    }
}

/// Core of `process`, split out for unit tests with an in-memory `ScriptRunner`.
/// Groups surviving (`Ok`) events by (team_id, issue_id), charges each group against the
/// team's limits, and flips over-limit events to `Err` in place (length/order preserved
/// for index-based reattachment). Fails open per group. Returns per-(team, limit,
/// outcome) tallies.
async fn apply_rate_limits(
    limiter: &RedisRateLimiter,
    settings: &HashMap<i32, RateLimitSettings>,
    enabled_teams: Option<&HashSet<i32>>,
    items: &mut [ExceptionEventPipelineItem],
    bypassed: &HashSet<usize>,
) -> HashMap<OutcomeKey, u32> {
    // Group surviving (Ok) events by (team_id, issue_id). Vec<usize> stays in input order.
    // Bypassed events are skipped so they never charge a token bucket.
    let mut groups: HashMap<(i32, Option<Uuid>), Vec<usize>> = HashMap::new();
    for (idx, item) in items.iter().enumerate() {
        if bypassed.contains(&idx) {
            continue;
        }
        if let Ok(props) = item {
            groups
                .entry((props.team_id, props.issue_id))
                .or_default()
                .push(idx);
        }
    }

    // Keep only the groups we charge (allowlisted, opted in, ≥1 enabled limit) and
    // resolve their bucket params up front; the admits fan out below.
    let chargeable = groups
        .into_iter()
        .filter_map(|((team_id, issue_id), indices)| {
            // Allowlist: when set, only listed teams are rate-limited.
            if enabled_teams.is_some_and(|allowed| !allowed.contains(&team_id)) {
                return None;
            }
            // no settings row → team not opted in
            let team_settings = settings.get(&team_id)?;
            // per-issue limit needs an issue to key on
            let per_issue = issue_id.and(team_settings.per_issue());
            let project = team_settings.project();
            if per_issue.is_none() && project.is_none() {
                return None;
            }
            Some((team_id, issue_id, indices, per_issue, project))
        });

    // Fan out the admits concurrently — each is one Redis round trip, pipelined over the
    // multiplexed connection, so N distinct issues cost ~one RTT, not N. Each EVAL is
    // atomic on Redis, so completion order changes no per-bucket total.
    let charged: Vec<_> = stream::iter(chargeable.map(
        |(team_id, issue_id, indices, per_issue, project)| async move {
            let n = indices.len() as u32;
            let decision = limiter
                .admit(team_id, issue_id, per_issue, project, n)
                .await;
            (team_id, issue_id, indices, per_issue, project, decision)
        },
    ))
    .buffer_unordered(MAX_CONCURRENT_ADMITS)
    .collect()
    .await;

    let mut outcomes: HashMap<OutcomeKey, u32> = HashMap::new();
    let mut drops: Vec<(usize, EventError)> = Vec::new();

    for (team_id, issue_id, indices, per_issue, project, decision) in charged {
        let decision = match decision {
            Ok(decision) => decision,
            Err(e) => {
                // Fail open: keep everything, but record it so we can alert on it.
                warn!("error-tracking rate limiter failed open for team {team_id}: {e}");
                counter!(RATE_LIMIT_FAIL_OPEN).increment(indices.len() as u64);
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
    /// Evaluate bypass rules over the batch. An event whose team is subject to rate
    /// limiting and which matches an enabled rule is exempted: its index is returned so
    /// the limiter never charges it, and a `Bypassed` outcome is tallied (per-issue and/or
    /// project, matching the team's configured limits) so it surfaces in app metrics.
    async fn apply_bypass(
        &self,
        settings: &HashMap<i32, RateLimitSettings>,
        items: &[ExceptionEventPipelineItem],
    ) -> (HashSet<usize>, HashMap<OutcomeKey, u32>) {
        let enabled_teams = self.ctx.rate_limiter_enabled_team_ids.as_ref();

        // A team's events can only be "bypassed" if the team is actually rate-limited:
        // allowlisted (when an allowlist is set) and with at least one configured limit.
        let is_rate_limited = |team_id: i32| -> bool {
            if enabled_teams.is_some_and(|allowed| !allowed.contains(&team_id)) {
                return false;
            }
            settings
                .get(&team_id)
                .is_some_and(|s| s.per_issue().is_some() || s.project().is_some())
        };

        // Load rules once per eligible team present in the batch.
        let eligible_teams: HashSet<i32> = items
            .iter()
            .filter_map(|item| item.as_ref().ok().map(|p| p.team_id))
            .filter(|&team_id| is_rate_limited(team_id))
            .collect();
        let mut rules_by_team: HashMap<i32, Vec<BypassRule>> = HashMap::new();
        for team_id in eligible_teams {
            match self
                .ctx
                .team_manager
                .get_bypass_rules(&self.ctx.posthog_pool, team_id)
                .await
            {
                Ok(rules) if !rules.is_empty() => {
                    let mut rules = rules;
                    rules.sort_unstable_by_key(|r| r.order_key);
                    rules_by_team.insert(team_id, rules);
                }
                Ok(_) => {}
                Err(e) => warn!("failed to load bypass rules for team {team_id}: {e}"),
            }
        }

        if rules_by_team.is_empty() {
            return (HashSet::new(), HashMap::new());
        }

        let (bypassed, outcomes, to_disable) =
            evaluate_bypass_rules(items, &rules_by_team, settings, |rule, props_json| {
                rule.try_match(props_json)
            });

        // Persist the disables the evaluation flagged. They're already deduped to one entry per
        // broken rule, so this is at most one DB write + cache drop per rule for the whole batch.
        for entry in to_disable {
            if let Err(e) = entry
                .rule
                .disable(&self.ctx.posthog_pool, entry.error, entry.props_json)
                .await
            {
                warn!("failed to disable bypass rule {}: {e}", entry.rule.id);
            }
            self.ctx
                .team_manager
                .bypass_rules
                .invalidate(&entry.team_id);
        }

        (bypassed, outcomes)
    }

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

        // The limiting already happened in Redis — so don't
        // block the pipeline on broker delivery. Fire-and-forget
        let producer = self.ctx.app_metrics_producer.clone();
        tokio::spawn(async move {
            let results = send_iter_to_kafka(&producer, APP_METRICS2_TOPIC, app_metrics).await;
            let (mut ok, mut failed) = (0u64, 0u64);
            for result in results {
                match result {
                    Ok(()) => ok += 1,
                    Err(e) => {
                        failed += 1;
                        warn!("failed to emit error-tracking rate-limit app_metric: {e}");
                    }
                }
            }
            if ok > 0 {
                counter!(RATE_LIMIT_METRIC_EMIT, "outcome" => "success").increment(ok);
            }
            if failed > 0 {
                counter!(RATE_LIMIT_METRIC_EMIT, "outcome" => "error").increment(failed);
            }
        });
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

/// Tally a bypassed event under the limits the team has configured, so the "bypassed"
/// series lines up with allowed/rate_limited in each chart: a per-issue row (keyed by the
/// issue id) when the per-issue limit is on, and a project row when the project limit is on.
fn tally_bypassed(
    outcomes: &mut HashMap<OutcomeKey, u32>,
    props: &ExceptionProperties,
    settings: &HashMap<i32, RateLimitSettings>,
) {
    let Some(team_settings) = settings.get(&props.team_id) else {
        return;
    };
    if team_settings.project().is_some() {
        *outcomes
            .entry((props.team_id, LimitKind::Project, None, Outcome::Bypassed))
            .or_insert(0) += 1;
    }
    if props.issue_id.is_some() && team_settings.per_issue().is_some() {
        *outcomes
            .entry((
                props.team_id,
                LimitKind::PerIssue,
                props.issue_id,
                Outcome::Bypassed,
            ))
            .or_insert(0) += 1;
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

/// A broken bypass rule to disable after evaluation, captured once (on first failure) with the
/// error and the props of the event that broke it.
struct RuleToDisable<'a> {
    rule: &'a BypassRule,
    team_id: i32,
    error: String,
    props_json: serde_json::Value,
}

/// Pure per-batch evaluation of already-loaded bypass rules, split out from I/O (rule loading and
/// disabling) so it can be unit-tested without a database or the HogVM. Returns the bypassed event
/// indices, the "bypassed" tallies, and the broken rules to disable — deduped to one entry per
/// rule: a rule that errors is tried once per batch and skipped for every later event, so it isn't
/// re-disabled (and its cache re-invalidated) on each match. `match_fn` is [`BypassRule::try_match`]
/// in production and a fake in tests.
fn evaluate_bypass_rules<'a>(
    items: &[ExceptionEventPipelineItem],
    rules_by_team: &'a HashMap<i32, Vec<BypassRule>>,
    settings: &HashMap<i32, RateLimitSettings>,
    match_fn: impl Fn(&BypassRule, &serde_json::Value) -> Result<bool, VmError>,
) -> (
    HashSet<usize>,
    HashMap<OutcomeKey, u32>,
    Vec<RuleToDisable<'a>>,
) {
    let mut bypassed: HashSet<usize> = HashSet::new();
    let mut outcomes: HashMap<OutcomeKey, u32> = HashMap::new();
    let mut to_disable: Vec<RuleToDisable<'a>> = Vec::new();
    let mut disabled_rules: HashSet<Uuid> = HashSet::new();

    for (idx, item) in items.iter().enumerate() {
        let Ok(props) = item else { continue };
        let Some(rules) = rules_by_team.get(&props.team_id) else {
            continue;
        };
        let props_json = match serde_json::to_value(props) {
            Ok(v) => v,
            Err(_) => continue,
        };
        for rule in rules {
            if disabled_rules.contains(&rule.id) {
                continue;
            }
            match match_fn(rule, &props_json) {
                Ok(false) => continue,
                Ok(true) => {
                    bypassed.insert(idx);
                    tally_bypassed(&mut outcomes, props, settings);
                    break;
                }
                // Step-budget exhaustion: skip this rule for this event, but keep trying it on
                // later events — it isn't broken, just too expensive for this one.
                Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                    warn!(
                        rule_id = %rule.id,
                        team_id = %rule.team_id,
                        "bypass rule exceeded HogVM step budget for this event, skipping"
                    );
                    continue;
                }
                // Any other error means the rule is broken: flag it for disabling and skip it for
                // the rest of the batch so it stops erroring on every later event.
                Err(err) => {
                    disabled_rules.insert(rule.id);
                    to_disable.push(RuleToDisable {
                        rule,
                        team_id: props.team_id,
                        error: err.to_string(),
                        props_json: props_json.clone(),
                    });
                    continue;
                }
            }
        }
    }

    (bypassed, outcomes, to_disable)
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
            versioned_fingerprints: Vec::new(),
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

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items, &HashSet::new()).await;

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

        apply_rate_limits(&limiter, &cfg, None, &mut items, &HashSet::new()).await;

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

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items, &HashSet::new()).await;

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

        let outcomes = apply_rate_limits(&limiter, &cfg, None, &mut items, &HashSet::new()).await;

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

        apply_rate_limits(&limiter, &cfg, Some(&allowed), &mut items, &HashSet::new()).await;

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

    #[tokio::test]
    async fn bypassed_events_are_kept_and_not_charged() {
        // 5 events for one issue, 2 of them bypassed. Redis admits only 1 of the
        // chargeable events, but the bypassed pair must survive regardless and never
        // enter the bucket — so 3 events are kept (2 bypassed + 1 admitted).
        let runner = Arc::new(FakeScriptRunner::returning(vec![1, 1]));
        let limiter = limiter_with(runner.clone());
        let issue = Uuid::now_v7();
        let mut items: Vec<ExceptionEventPipelineItem> =
            (0..5).map(|_| event(7, Some(issue))).collect();
        let mut cfg = HashMap::new();
        cfg.insert(7, settings(Some(100), Some(100)));
        let bypassed: HashSet<usize> = [0, 1].into_iter().collect();

        apply_rate_limits(&limiter, &cfg, None, &mut items, &bypassed).await;

        // Bypassed indices are always kept.
        assert!(items[0].is_ok());
        assert!(items[1].is_ok());
        // Only the 3 non-bypassed events were charged (admit 1 -> 2 dropped).
        assert_eq!(items.iter().filter(|i| i.is_ok()).count(), 3);
    }

    #[test]
    fn tally_bypassed_records_both_limits_when_configured() {
        let issue = Uuid::now_v7();
        let mut outcomes = HashMap::new();
        let mut cfg = HashMap::new();
        cfg.insert(7, settings(Some(100), Some(100)));
        let item = event(7, Some(issue));
        let props = item.as_ref().unwrap();

        tally_bypassed(&mut outcomes, props, &cfg);

        assert_eq!(
            outcomes.get(&(7, LimitKind::PerIssue, Some(issue), Outcome::Bypassed)),
            Some(&1)
        );
        assert_eq!(
            outcomes.get(&(7, LimitKind::Project, None, Outcome::Bypassed)),
            Some(&1)
        );
    }

    #[test]
    fn tally_bypassed_skips_unconfigured_limits() {
        // Only a project limit configured, and an event with no issue id: a single
        // project row, no per-issue row.
        let mut outcomes = HashMap::new();
        let mut cfg = HashMap::new();
        cfg.insert(7, settings(None, Some(100)));
        let item = event(7, None);
        let props = item.as_ref().unwrap();

        tally_bypassed(&mut outcomes, props, &cfg);

        assert_eq!(
            outcomes.get(&(7, LimitKind::Project, None, Outcome::Bypassed)),
            Some(&1)
        );
        assert_eq!(outcomes.len(), 1);
    }

    fn bypass_rule(id: Uuid, team_id: i32, order_key: i32) -> BypassRule {
        // Bytecode is irrelevant here — the tests drive matching through the fake `match_fn`.
        BypassRule {
            id,
            team_id,
            order_key,
            bytecode: serde_json::Value::Array(vec![]),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn evaluate_bypass_marks_matching_event_and_tallies() {
        let issue = Uuid::now_v7();
        let items = vec![event(7, Some(issue))];
        let rules_by_team = HashMap::from([(7, vec![bypass_rule(Uuid::now_v7(), 7, 0)])]);
        let cfg = HashMap::from([(7, settings(Some(100), Some(100)))]);

        let (bypassed, outcomes, to_disable) =
            evaluate_bypass_rules(&items, &rules_by_team, &cfg, |_rule, _props| Ok(true));

        assert!(bypassed.contains(&0));
        assert!(to_disable.is_empty());
        // A bypassed event is tallied under each configured limit so it lines up in the charts.
        assert_eq!(
            outcomes.get(&(7, LimitKind::PerIssue, Some(issue), Outcome::Bypassed)),
            Some(&1)
        );
        assert_eq!(
            outcomes.get(&(7, LimitKind::Project, None, Outcome::Bypassed)),
            Some(&1)
        );
    }

    #[test]
    fn evaluate_bypass_disables_broken_rule_once_per_batch() {
        let rule_id = Uuid::now_v7();
        let items: Vec<_> = (0..3).map(|_| event(7, Some(Uuid::now_v7()))).collect();
        let rules_by_team = HashMap::from([(7, vec![bypass_rule(rule_id, 7, 0)])]);
        let cfg = HashMap::from([(7, settings(Some(100), Some(100)))]);
        let calls = AtomicUsize::new(0);

        let (bypassed, _outcomes, to_disable) =
            evaluate_bypass_rules(&items, &rules_by_team, &cfg, |_rule, _props| {
                calls.fetch_add(1, Ordering::Relaxed);
                Err(VmError::Other("boom".to_string()))
            });

        // The broken rule is flagged for disabling exactly once even though three events hit its
        // team, and it is never re-run after the first failure — this is the per-batch dedup.
        assert_eq!(to_disable.len(), 1);
        assert_eq!(to_disable[0].rule.id, rule_id);
        assert_eq!(calls.load(Ordering::Relaxed), 1);
        // A broken rule bypasses nothing; its events fall through to normal rate limiting.
        assert!(bypassed.is_empty());
    }

    #[test]
    fn evaluate_bypass_step_budget_skips_without_disabling() {
        let items: Vec<_> = (0..3).map(|_| event(7, Some(Uuid::now_v7()))).collect();
        let rules_by_team = HashMap::from([(7, vec![bypass_rule(Uuid::now_v7(), 7, 0)])]);
        let cfg = HashMap::from([(7, settings(Some(100), Some(100)))]);
        let calls = AtomicUsize::new(0);

        let (bypassed, outcomes, to_disable) =
            evaluate_bypass_rules(&items, &rules_by_team, &cfg, |_rule, _props| {
                calls.fetch_add(1, Ordering::Relaxed);
                Err(VmError::OutOfResource("steps".to_string()))
            });

        // Step-budget exhaustion is per-event: unlike a broken rule, the rule is not disabled and
        // is retried on every event.
        assert!(to_disable.is_empty());
        assert_eq!(calls.load(Ordering::Relaxed), 3);
        assert!(bypassed.is_empty());
        assert!(outcomes.is_empty());
    }
}
