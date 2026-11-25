//! Topic MCP tools for a topic's context: mission, goals, rules, follow-up policy, facts and
//! watched sources. Each change is a topic command, so the domain model validates it and it
//! replicates to clients. Tools never loosen the person's policy.
use crate::{
    Server,
    topic_mcp::{Caller, apply, input, no_args},
};
use anyhow::{Context, Result, bail, ensure};
use chrono::Utc;
use meep_topic::{
    ActionKind, Column, Command, Fact, FactId, Goal, GoalId, Matcher, Progress, Provenance, Rule,
    RuleEffect, RuleId, ThreadState, TopicId, Watch,
};
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

pub(super) fn tools() -> Vec<Value> {
    let text = json!({"type":"string"});
    let id = json!({"type":"string","format":"uuid"});
    let number = json!({"type":"number"});
    vec![
        crate::mcp::tool(
            "get_topic",
            "Read the topic: mission, goals, passive context references, monitored sources, facts, rules, routines and what needs the person.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "set_mission",
            "Replace this topic's mission.",
            json!({"mission":text}),
            &["mission"],
        ),
        crate::mcp::tool(
            "add_goal",
            "Add a goal. Give target {current, target, unit} for a value to reach, or guardrail {current, low, high, unit} for a value to keep in a band.",
            json!({
                "text":text,
                "target":{"type":"object","properties":{"current":number,"target":number,"unit":text},"required":["current","target","unit"],"additionalProperties":false},
                "guardrail":{"type":"object","properties":{"current":number,"low":number,"high":number,"unit":text},"required":["current","low","high","unit"],"additionalProperties":false}
            }),
            &["text"],
        ),
        crate::mcp::tool(
            "update_goal_progress",
            "Record a goal's latest measurement. target, low, high and unit replace the goal's existing values when given. A goal without progress needs unit and either target or low and high.",
            json!({"goal":id,"current":number,"target":number,"low":number,"high":number,"unit":text}),
            &["goal", "current"],
        ),
        crate::mcp::tool(
            "add_rule",
            "Add a rule. Use start-follow-up for starting agent-created tasks and investigation leads. ask: always ask before actions of action_kind. deny: never do actions of action_kind. skip: ignore messages matching connection and/or channel. Allow rules come only from the person approving work.",
            json!({"text":text,"effect":{"enum":["ask","deny","skip"]},"action_kind":text,"connection":text,"channel":text}),
            &["text", "effect"],
        ),
        crate::mcp::tool(
            "remove_rule",
            "Remove an Allow or Skip rule. Only the person can remove Ask or Deny rules.",
            json!({"rule":id}),
            &["rule"],
        ),
        crate::mcp::tool(
            "list_facts",
            "List the topic's facts with provenance and dispute state. Retired facts are included only when asked.",
            json!({"include_retired":{"type":"boolean"}}),
            &[],
        ),
        crate::mcp::tool(
            "add_fact",
            "Save a fact this run established. Provenance records this agent run.",
            json!({"text":text}),
            &["text"],
        ),
        crate::mcp::tool(
            "supersede_fact",
            "Replace a current fact with a corrected one. The old fact keeps its provenance.",
            json!({"fact":id,"text":text}),
            &["fact", "text"],
        ),
        crate::mcp::tool(
            "remove_fact",
            "Withdraw a current fact.",
            json!({"fact":id}),
            &["fact"],
        ),
        crate::mcp::tool(
            "list_sources",
            "List the sources this topic's accounts can watch, with their keys, best matches first.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "set_scout_feed",
            "Bring PostHog Scout reports into this topic's inbox. Give up to five keywords (product areas or feature names, any of which may match) to receive only matching reports, an empty string for all of the project's reports, or enabled false to stop.",
            json!({"enabled":{"type":"boolean"},"search":{"type":"string","maxLength":200}}),
            &["enabled"],
        ),
        crate::mcp::tool(
            "add_context_source",
            "Add one passive PostHog reference found with your PostHog search tools. This does not monitor it or run workflows. Use a connection granted to this topic.",
            json!({"connection":text,"kind":text,"key":text,"label":text}),
            &["connection", "kind", "key", "label"],
        ),
        crate::mcp::tool(
            "remove_context_source",
            "Remove one passive context reference by its id from get_topic. This does not change routine monitoring.",
            json!({"id":id}),
            &["id"],
        ),
        crate::mcp::tool(
            "watch_sources",
            "Watch sources by key from list_sources. Existing watches are kept.",
            json!({"keys":{"type":"array","items":text,"minItems":1,"maxItems":50}}),
            &["keys"],
        ),
        crate::mcp::tool(
            "unwatch_sources",
            "Stop watching sources by key, as shown in get_topic watches.",
            json!({"keys":{"type":"array","items":text,"minItems":1,"maxItems":50}}),
            &["keys"],
        ),
    ]
}

/// Run a context tool on `topic` (the caller's own topic for changes), or `None` when the
/// name belongs to another tool set.
pub(super) async fn call(
    s: &Server,
    caller: &Caller,
    topic: TopicId,
    name: &str,
    args: Value,
) -> Option<Result<Value>> {
    Some(match name {
        "get_topic" => no_args(args).and_then(|()| read(s, topic)),
        "set_mission" => set_mission(s, topic, args).await,
        "add_goal" => add_goal(s, topic, args).await,
        "update_goal_progress" => update_goal(s, topic, args).await,
        "add_rule" => add_rule(s, topic, args).await,
        "remove_rule" => remove_rule(s, topic, args).await,
        "list_facts" => facts(s, topic, args),
        "add_fact" => add_fact(s, caller, topic, args).await,
        "supersede_fact" => supersede_fact(s, caller, topic, args).await,
        "remove_fact" => remove_fact(s, topic, args).await,
        "list_sources" => match no_args(args) {
            Ok(()) => sources(s, topic).await.map(|v| json!(v)),
            Err(e) => Err(e),
        },
        "set_scout_feed" => set_scout_feed(s, topic, args).await,
        "add_context_source" => add_context_source(s, topic, args).await,
        "remove_context_source" => remove_context_source(s, topic, args).await,
        "watch_sources" => watch(s, topic, args).await,
        "unwatch_sources" => unwatch(s, topic, args).await,
        _ => return None,
    })
}

fn bounded(value: &str, field: &str, max: usize) -> Result<String> {
    let value = value.trim();
    ensure!(
        !value.is_empty() && value.chars().count() <= max,
        "{field} must be 1 to {max} characters"
    );
    Ok(value.to_owned())
}

fn finite(values: &[f64]) -> Result<()> {
    ensure!(
        values.iter().all(|v| v.is_finite()),
        "Measurements must be finite numbers"
    );
    Ok(())
}

fn watch_json(w: &Watch) -> Value {
    json!({"connection":w.connection,"kind":w.kind,"key":w.key,"label":w.label})
}

fn read(s: &Server, topic: TopicId) -> Result<Value> {
    let connections: Vec<_> = s
        .accounts
        .all()
        .into_iter()
        .filter(|account| {
            account.public.kind == "posthog" && account.public.grants.contains(&topic)
        })
        .map(|account| json!({"id":account.public.id,"label":account.public.label}))
        .collect();
    Ok(s.engine.read_topic(topic, |state| {
        let disputes = state.disputed_facts();
        let t = &state.topic;
        let column = |c: Column| state.tasks.iter().filter(|t| t.column == c).count();
        json!({
            "id":t.id,
            "name":t.name,
            "mission":t.mission,
            "goals":t.goals,
            "posthog_connections":connections,
            "context_sources":t.context_sources.iter().map(|w| json!({"id":w.id,"connection":w.connection,"kind":w.kind,"key":w.key,"label":w.label})).collect::<Vec<_>>(),
            "watches":t.watches().map(watch_json).collect::<Vec<_>>(),
            "facts":t.facts.iter().filter(|f| f.is_current()).map(|f| json!({"id":f.id,"text":f.text,"disputed":disputes.contains(&f.id)})).collect::<Vec<_>>(),
            "rules":t.rules.iter().map(|r| json!({"id":r.id,"text":r.text,"effect":r.effect})).collect::<Vec<_>>(),
            "routines":t.routines.iter().map(|r| json!({"routine":r.binding.id,"name":r.binding.name,"trigger":r.binding.trigger,"backend":r.binding.backend,"observations":r.observations,"watches":r.binding.watches,"health":r.health,"last_run":r.last_run})).collect::<Vec<_>>(),
            "counts":{
                "threads_need_you":state.threads.iter().filter(|t| matches!(t.state, ThreadState::NeedsYou { .. })).count(),
                "threads_unseen":state.threads.iter().filter(|t| !t.source_material && t.unseen).count(),
                "tasks_todo":column(Column::Todo),
                "tasks_in_progress":column(Column::InProgress),
                "tasks_need_you":column(Column::NeedsYou),
                "tasks_done":column(Column::Done),
                "facts":t.facts.iter().filter(|f| f.is_current()).count(),
                "disputed_facts":disputes.len(),
            },
        })
    })?)
}

async fn set_mission(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        mission: String,
    }
    let Args { mission } = input(args)?;
    let mission = bounded(&mission, "mission", 4000)?;
    s.engine.set_mission(topic, mission).await?;
    Ok(s.engine
        .read_topic(topic, |s| json!({"mission":s.topic.mission}))?)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Target {
    current: f64,
    target: f64,
    unit: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Guardrail {
    current: f64,
    low: f64,
    high: f64,
    unit: String,
}

fn unit(unit: &str) -> Result<String> {
    let unit = unit.trim();
    ensure!(
        unit.chars().count() <= 32,
        "unit must be at most 32 characters"
    );
    Ok(unit.into())
}
fn guardrail(current: f64, low: f64, high: f64, unit: String) -> Result<Progress> {
    finite(&[current, low, high])?;
    ensure!(low <= high, "low must not exceed high");
    Ok(Progress::Guardrail {
        current,
        low,
        high,
        unit,
    })
}

async fn set_scout_feed(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        enabled: bool,
        search: Option<String>,
    }
    let Args { enabled, search } = input(args)?;
    let feed = enabled.then(|| search.unwrap_or_default().trim().to_owned());
    s.engine.set_scout_feed(topic, feed.clone()).await?;
    // Reports arrive within minutes; the first batch comes now.
    let imported = if feed.is_some() {
        crate::scout_feed::sync_topic(s, topic).await.unwrap_or(0)
    } else {
        0
    };
    Ok(json!({"scout_feed": feed, "imported": imported}))
}

async fn add_goal(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        text: String,
        target: Option<Target>,
        guardrail: Option<Guardrail>,
    }
    let Args {
        text,
        target,
        guardrail: band,
    } = input(args)?;
    let text = bounded(&text, "text", 500)?;
    let progress = match (target, band) {
        (Some(_), Some(_)) => bail!("Give either target or guardrail, not both"),
        (Some(t), None) => {
            finite(&[t.current, t.target])?;
            Some(Progress::Target {
                current: t.current,
                target: t.target,
                unit: unit(&t.unit)?,
            })
        }
        (None, Some(g)) => Some(guardrail(g.current, g.low, g.high, unit(&g.unit)?)?),
        (None, None) => None,
    };
    let goal = Goal {
        id: Uuid::new_v4().into(),
        text,
        progress,
    };
    let id = goal.id;
    s.engine.add_goal(topic, goal).await?;
    goal_json(s, topic, id)
}

fn goal_json(s: &Server, topic: TopicId, id: GoalId) -> Result<Value> {
    Ok(json!(
        s.engine
            .read_topic(topic, |s| s
                .topic
                .goals
                .iter()
                .find(|g| g.id == id)
                .cloned())?
            .context("The goal was not saved")?
    ))
}

async fn update_goal(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        goal: GoalId,
        current: f64,
        target: Option<f64>,
        low: Option<f64>,
        high: Option<f64>,
        unit: Option<String>,
    }
    let a: Args = input(args)?;
    let goal = s
        .engine
        .read_topic(topic, |s| {
            s.topic.goals.iter().find(|g| g.id == a.goal).cloned()
        })?
        .context("This topic has no such goal. Use get_topic.")?;
    let new_unit = a.unit.as_deref().map(unit).transpose()?;
    ensure!(
        a.target.is_none() || (a.low.is_none() && a.high.is_none()),
        "Give target, or low and high, not both"
    );
    let progress = match (goal.progress, a.target, a.low.or(a.high)) {
        (Some(Progress::Target { target, unit, .. }), t, None) => {
            let target = t.unwrap_or(target);
            finite(&[a.current, target])?;
            Progress::Target {
                current: a.current,
                target,
                unit: new_unit.unwrap_or(unit),
            }
        }
        (
            Some(Progress::Guardrail {
                low, high, unit, ..
            }),
            None,
            _,
        ) => guardrail(
            a.current,
            a.low.unwrap_or(low),
            a.high.unwrap_or(high),
            new_unit.unwrap_or(unit),
        )?,
        (_, Some(target), None) => {
            finite(&[a.current, target])?;
            Progress::Target {
                current: a.current,
                target,
                unit: new_unit.context("unit is required for a goal without progress")?,
            }
        }
        (_, None, Some(_)) => guardrail(
            a.current,
            a.low.context("low and high are both required")?,
            a.high.context("low and high are both required")?,
            new_unit.context("unit is required for a goal without progress")?,
        )?,
        (None, None, None) => {
            bail!("This goal has no progress yet. Give unit and either target or low and high.")
        }
        _ => bail!("A target goal takes target; a guardrail goal takes low and high"),
    };
    apply(
        s,
        topic,
        Command::UpdateGoalProgress {
            goal: a.goal,
            progress: Some(progress),
        },
    )
    .await?;
    goal_json(s, topic, a.goal)
}

async fn add_rule(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        text: String,
        effect: String,
        action_kind: Option<String>,
        connection: Option<String>,
        channel: Option<String>,
    }
    let a: Args = input(args)?;
    let text = bounded(&a.text, "text", 500)?;
    let kind = || -> Result<ActionKind> {
        ensure!(
            a.connection.is_none() && a.channel.is_none(),
            "connection and channel apply only to skip rules"
        );
        let kind = a
            .action_kind
            .as_deref()
            .context("action_kind is required for ask and deny rules")?
            .trim();
        ensure!(
            !kind.is_empty()
                && kind.len() <= 64
                && kind
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
            "action_kind must be 1 to 64 letters, digits, - or _, such as slack-reply"
        );
        Ok(ActionKind(kind.into()))
    };
    let effect = match a.effect.as_str() {
        "ask" => RuleEffect::Ask(kind()?),
        "deny" => RuleEffect::Deny(kind()?),
        "skip" => {
            ensure!(
                a.action_kind.is_none(),
                "action_kind applies only to ask and deny rules"
            );
            let filter = |v: &Option<String>| {
                v.as_deref()
                    .map(str::trim)
                    .filter(|v| !v.is_empty())
                    .map(str::to_owned)
            };
            let matcher = Matcher {
                connection: filter(&a.connection),
                channel: filter(&a.channel),
            };
            ensure!(
                matcher.connection.is_some() || matcher.channel.is_some(),
                "A skip rule needs a connection or channel"
            );
            RuleEffect::Skip(matcher)
        }
        "allow" => bail!(
            "Only the person can allow actions to run without approval. They get that choice when they approve the action."
        ),
        other => bail!("Unknown effect {other}. Use ask, deny or skip."),
    };
    let rule = Rule {
        id: Uuid::new_v4().into(),
        text,
        effect,
        from_task: None,
        created_at: Utc::now(),
    };
    let id = rule.id;
    apply(s, topic, Command::AddRule { rule }).await?;
    let rule = s
        .engine
        .read_topic(topic, |s| {
            s.topic.rules.iter().find(|r| r.id == id).cloned()
        })?
        .context("The rule was not saved")?;
    Ok(json!({"id":rule.id,"text":rule.text,"effect":rule.effect}))
}

async fn remove_rule(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        rule: RuleId,
    }
    let Args { rule } = input(args)?;
    let found = s
        .engine
        .read_topic(topic, |s| {
            s.topic.rules.iter().find(|r| r.id == rule).cloned()
        })?
        .context("This topic has no such rule. Use get_topic.")?;
    // Removing an Ask or Deny rule would let actions run with less review.
    ensure!(
        matches!(found.effect, RuleEffect::Allow(_) | RuleEffect::Skip(_)),
        "Only the person can remove an Ask or Deny rule. Ask them to remove “{}” in the topic's rules.",
        found.text
    );
    s.engine.remove_rule(topic, rule).await?;
    Ok(json!({"removed":rule}))
}

fn facts(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        #[serde(default)]
        include_retired: bool,
    }
    let Args { include_retired } = input(args)?;
    Ok(s.engine.read_topic(topic, |state| {
        let disputes = state.disputed_facts();
        json!(
            state
                .topic
                .facts
                .iter()
                .filter(|f| include_retired || f.is_current())
                .map(|f| json!({
                    "id":f.id,
                    "text":f.text,
                    "current":f.is_current(),
                    "disputed":disputes.contains(&f.id),
                    "provenance":f.provenance,
                    "superseded_by":f.superseded_by,
                    "invalidated_by":f.invalidated_by,
                }))
                .collect::<Vec<_>>()
        )
    })?)
}

fn provenance(caller: &Caller) -> Provenance {
    Provenance {
        origin: None,
        author: "Meep agent".into(),
        via: caller
            .task
            .map_or_else(|| "PostHog Tasks".into(), |t| format!("PostHog task {t}")),
        at: Utc::now(),
        thread: None,
    }
}

fn new_fact(caller: &Caller, text: &str) -> Result<Fact> {
    Ok(Fact {
        id: Uuid::new_v4().into(),
        text: bounded(text, "text", 2000)?,
        provenance: provenance(caller),
        superseded_by: None,
        invalidated_by: None,
        withdrawn_at: None,
    })
}

fn current_fact(s: &Server, topic: TopicId, id: FactId) -> Result<Fact> {
    let fact = s
        .engine
        .read_topic(topic, |s| {
            s.topic.facts.iter().find(|f| f.id == id).cloned()
        })?
        .context("This topic has no such fact. Use list_facts.")?;
    ensure!(fact.is_current(), "That fact is already retired");
    Ok(fact)
}

async fn add_fact(s: &Server, caller: &Caller, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        text: String,
    }
    let Args { text } = input(args)?;
    let fact = new_fact(caller, &text)?;
    let id = fact.id;
    s.engine.add_fact(topic, fact).await?;
    Ok(json!({"id":id,"text":current_fact(s, topic, id)?.text}))
}

async fn supersede_fact(s: &Server, caller: &Caller, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        fact: FactId,
        text: String,
    }
    let Args { fact, text } = input(args)?;
    current_fact(s, topic, fact)?;
    let new = new_fact(caller, &text)?;
    let id = new.id;
    apply(s, topic, Command::SupersedeFact { old: fact, new }).await?;
    Ok(json!({"id":id,"replaces":fact}))
}

async fn remove_fact(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        fact: FactId,
    }
    let Args { fact } = input(args)?;
    current_fact(s, topic, fact)?;
    s.engine.remove_fact(topic, fact).await?;
    Ok(json!({"removed":fact}))
}

async fn sources(s: &Server, topic: TopicId) -> Result<Vec<meep_wire::WatchableSource>> {
    let metadata = s.engine.read_topic(topic, |s| s.topic.clone())?;
    crate::sources::discover(&s.accounts, Some(&metadata))
        .await
        .context("Could not discover PostHog sources")
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Keys {
    keys: Vec<String>,
}
fn keys(args: Value) -> Result<Vec<String>> {
    let Keys { keys } = input(args)?;
    ensure!(
        (1..=50).contains(&keys.len()),
        "keys must name 1 to 50 sources"
    );
    Ok(keys)
}

pub(super) async fn resolve_sources(
    s: &Server,
    topic: TopicId,
    keys: &[String],
) -> Result<Vec<Watch>> {
    ensure!(keys.len() <= 50, "Select at most 50 sources");
    if keys.is_empty() {
        return Ok(vec![]);
    }
    let available = sources(s, topic).await?;
    let watches = s.engine.read_topic(topic, |s| {
        s.topic
            .context_sources
            .iter()
            .chain(s.topic.watches())
            .cloned()
            .collect::<Vec<_>>()
    })?;
    let mut selected = Vec::new();
    for key in keys {
        let mut matching = available.iter().filter(|w| w.key == *key);
        let found = matching
            .next()
            .with_context(|| format!("Unknown source key {key}. Use a key from list_sources."))?;
        ensure!(
            matching.next().is_none(),
            "Source key {key} is offered by more than one account"
        );
        ensure!(
            !selected.iter().any(|w: &Watch| w.key == *key),
            "Duplicate source key {key}"
        );
        selected.push(
            watches
                .iter()
                .find(|w| w.connection == found.connection && w.kind == found.kind && w.key == *key)
                .cloned()
                .unwrap_or_else(|| Watch {
                    id: Uuid::new_v4().into(),
                    connection: found.connection.clone(),
                    kind: found.kind.clone(),
                    key: key.clone(),
                    label: found.label.clone(),
                }),
        );
    }
    Ok(selected)
}

async fn watch(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let keys = keys(args)?;
    let chosen = resolve_sources(s, topic, &keys).await?;
    let mut watches = s
        .engine
        .read_topic(topic, |s| s.topic.watches().cloned().collect::<Vec<_>>())?;
    let before = watches.len();
    for source in chosen {
        if !watches.iter().any(|w| w.id == source.id) {
            watches.push(source);
        }
    }
    if watches.len() != before {
        s.engine.set_topic_watches(topic, watches).await?;
    }
    Ok(json!(s.engine.read_topic(topic, |s| {
        s.topic.watches().map(watch_json).collect::<Vec<_>>()
    })?))
}

async fn unwatch(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let keys = keys(args)?;
    let watches = s
        .engine
        .read_topic(topic, |s| s.topic.watches().cloned().collect::<Vec<_>>())?;
    if let Some(missing) = keys.iter().find(|k| !watches.iter().any(|w| w.key == **k)) {
        bail!("This topic does not watch {missing}. Use get_topic for its watches.");
    }
    let kept: Vec<_> = watches
        .iter()
        .filter(|w| !keys.contains(&w.key))
        .cloned()
        .collect();
    s.engine.set_topic_watches(topic, kept).await?;
    Ok(json!(s.engine.read_topic(topic, |s| {
        s.topic.watches().map(watch_json).collect::<Vec<_>>()
    })?))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AddContextSource {
    connection: String,
    kind: String,
    key: String,
    label: String,
}

async fn add_context_source(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let args: AddContextSource = input(args)?;
    let connection = bounded(&args.connection, "connection", 256)?;
    let kind = match bounded(&args.kind, "kind", 32)?.as_str() {
        "feature-flag" | "feature_flag" => "flag".to_owned(),
        other => other.to_owned(),
    };
    ensure!(
        kind.bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-' || c == b'_'),
        "Use a lowercase PostHog object type"
    );
    let key = bounded(&args.key, "key", 512)?;
    let label = bounded(&args.label, "label", 512)?;
    let account = s.accounts.get(&connection).context("Unknown connection")?;
    ensure!(
        account.public.kind == "posthog" && account.public.grants.contains(&topic),
        "This topic has no grant to that PostHog connection"
    );
    apply(
        s,
        topic,
        Command::AddContextSource {
            source: Watch {
                id: Uuid::new_v4().into(),
                connection,
                kind,
                key,
                label,
            },
        },
    )
    .await?;
    read(s, topic)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RemoveContextSource {
    id: meep_topic::WatchId,
}

async fn remove_context_source(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let args: RemoveContextSource = input(args)?;
    ensure!(
        s.engine.read_topic(topic, |state| state
            .topic
            .context_sources
            .iter()
            .any(|w| w.id == args.id))?,
        "Unknown context reference"
    );
    apply(s, topic, Command::RemoveContextSource { source: args.id }).await?;
    read(s, topic)
}
