//! PostHog workflow provisioning, binding and lifecycle.
mod graph;
use crate::{Server, posthog::Project, topic_mcp::input};
use anyhow::{Context, Result, bail, ensure};
use chrono::Utc;
pub(super) use graph::Spec;
use graph::{Action, EventTrigger, StepKind, Trigger, action, graph, plan, slug};
use meep_engine::WorkflowReview;
use meep_posthog::api::ProjectEndpoint;
use meep_topic::{RoutineBinding, TopicId};
use serde_json::{Value, json};
use uuid::Uuid;

fn flows(p: &Project) -> Result<ProjectEndpoint> {
    ProjectEndpoint::new(&p.origin, p.project, "hog_flows")
}
fn archive_key(p: &Project, topic: TopicId, flow: &str) -> String {
    format!(
        "\0topics/managed-trigger/{}/{}/{topic}/{flow}",
        p.origin, p.project
    )
}

// A PostHog schedule or analytics trigger runs independently of Meep. Remember
// which active flows we paused, including across a server restart.
pub(super) async fn reconcile_archive(
    s: &Server,
    topic: TopicId,
    b: &RoutineBinding,
    archived: bool,
) -> Result<()> {
    let Ok((_, p)) = s.accounts.project(topic) else {
        return Ok(());
    };
    let key = archive_key(&p, topic, &b.external_id);
    let store = &s.accounts.checkpoints;
    let prior = store.load(&key)?;
    if !archived && prior.as_ref() != Some(&json!("paused")) {
        return Ok(());
    }
    let api = flows(&p)?;
    let endpoint = format!("{}/", b.external_id);
    if archived {
        // A second active topic may use the same external flow.
        if s.engine.read_topics(|topics| {
            topics.iter().any(|t| {
                t.topic.id != topic
                    && !t.archived
                    && t.topic.routines.iter().any(|r| {
                        r.binding.backend == b.backend && r.binding.external_id == b.external_id
                    })
            })
        }) {
            return Ok(());
        }
        let definition: Value = api.get(&p.token, &endpoint).await?;
        if definition["status"] != "active" {
            return Ok(());
        }
        if prior.is_none() {
            // Older generated definitions carry the bound topic's callback secret.
            let secret = s.engine.routine_secret(topic, &b.id)?;
            let actions = definition["actions"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or_default();
            if !actions
                .iter()
                .any(|a| matches!(a["config"]["type"].as_str(), Some("schedule" | "event")))
                || !actions.iter().any(|a| {
                    a.pointer("/config/inputs/body/value/secret")
                        .and_then(Value::as_str)
                        == Some(&secret)
                })
            {
                return Ok(());
            }
        }
        if prior.as_ref() != Some(&json!("paused")) {
            store.commit(&key, prior.as_ref(), &json!("paused"))?;
        }
        api.patch::<Value>(&p.token, &endpoint, json!({"status":"draft"}))
            .await?;
    } else {
        let definition: Value = api.get(&p.token, &endpoint).await?;
        if definition["status"] == "draft" {
            api.patch::<Value>(&p.token, &endpoint, json!({"status":"active"}))
                .await?;
        }
        store.commit(&key, prior.as_ref(), &json!("managed"))?;
    }
    Ok(())
}

fn flow_url(p: &Project, flow: &str) -> String {
    format!(
        "{}/project/{}/workflows/{flow}/workflow",
        p.origin.trim_end_matches('/'),
        p.project
    )
}

pub(super) async fn list(s: &Server, topic: TopicId) -> Result<Value> {
    let routines = s.engine.read_topic(topic, |s| s.topic.routines.clone())?;
    let project = s.accounts.project(topic).ok().map(|(_, p)| p);
    let mut out = Vec::new();
    for r in &routines {
        let b = &r.binding;
        let mut item = json!({"routine":b.id,"name":b.name,"trigger":b.trigger,"backend":b.backend,"event":r.event,"observations":r.observations,"watches":b.watches,"health":r.health,"last_run":r.last_run});
        if b.backend == "system" || r.event.is_some() {
            item["enabled"] = json!(r.enabled);
        }
        if b.backend == "posthog" {
            item["flow"] = json!(b.external_id);
            match &project {
                Some(p) => {
                    item["url"] = json!(flow_url(p, &b.external_id));
                    match flows(p)?
                        .get::<Value>(&p.token, &format!("{}/", b.external_id))
                        .await
                    {
                        Ok(def) => {
                            item["status"] = def["status"].clone();
                            item["posthog_trigger"] = def["trigger"].clone();
                            item["schedules"] = def["schedules"].clone();
                            item["steps"] = json!(
                                def["actions"]
                                    .as_array()
                                    .into_iter()
                                    .flatten()
                                    .filter(|a| !matches!(
                                        a["type"].as_str(),
                                        Some("trigger" | "exit")
                                    ))
                                    .map(|a| json!({"name":a["name"],"type":a["type"]}))
                                    .collect::<Vec<_>>()
                            );
                        }
                        Err(e) => item["error"] = json!(format!("{e:#}")),
                    }
                }
                None => item["error"] = json!("Connect a healthy PostHog account to this topic"),
            }
        }
        out.push(item);
    }
    Ok(json!(out))
}

pub(super) fn templates() -> &'static [meep_wire::RoutineTemplate] {
    static REGISTRY: std::sync::LazyLock<Vec<meep_wire::RoutineTemplate>> =
        std::sync::LazyLock::new(|| {
            serde_json::from_str(include_str!("routine_templates.json"))
                .expect("valid template registry")
        });
    &REGISTRY
}
fn template_spec(template: &str, sources: Vec<String>) -> Result<Spec> {
    let t = templates()
        .iter()
        .find(|t| t.id == template)
        .context("Unknown routine template")?;
    let mut trigger = t.trigger.clone();
    if trigger["type"] == "source" {
        trigger["keys"] = json!(sources);
    } else {
        ensure!(
            sources.is_empty(),
            "Scheduled templates do not accept sources"
        );
    }
    input(
        json!({"name":t.name,"description":t.description,"trigger":trigger,"steps":t.steps,"depends_on_facts":[]}),
    )
}
pub(super) async fn create_template(
    s: &Server,
    topic: TopicId,
    req: meep_wire::CreateTemplateRoutine,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    let spec = template_spec(&req.template, req.sources.clone())?;
    create(s, topic, spec, false, review).await
}
fn sort_variables() -> [Value; 6] {
    [
        json!({"key":"sort_context","type":"string","default":""}),
        json!({"key":"sort_skip_fingerprint","type":"string","default":""}),
        json!({"key":"sort_skip_guard","type":"string","default":"review"}),
        json!({"key":"sort_skip_snapshot","type":"string","default":""}),
        json!({"key":"sort_category","type":"string","default":""}),
        json!({"key":"sort_confidence","type":"number","default":0}),
    ]
}

// An interrupted POST can have created the draft even when Meep did not receive its ID.
// Recover it by its unique setup description without issuing a second create.
async fn recover_default(api: &ProjectEndpoint, token: &str, marker: &str) -> Result<String> {
    let mut path = String::new();
    let mut visited = std::collections::HashSet::new();
    while visited.len() < 1000 {
        ensure!(
            visited.insert(path.clone()),
            "PostHog repeated a workflow page"
        );
        let page: Value = api.get(token, &path).await?;
        let rows = page["results"]
            .as_array()
            .context("Invalid PostHog workflows page")?;
        if let Some(id) = rows
            .iter()
            .find(|flow| flow["description"] == marker)
            .and_then(|flow| flow["id"].as_str())
        {
            return Ok(id.into());
        }
        path = page["next"]
            .as_str()
            .context("Waiting for the previously requested Sort inbox draft")?
            .to_owned();
    }
    anyhow::bail!("Workflow discovery exceeded 1,000 pages")
}
pub(super) async fn create(
    s: &Server,
    topic: TopicId,
    spec: Spec,
    default: bool,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    let name = spec.name.trim().to_owned();
    ensure!(
        !name.is_empty() && name.len() <= 120,
        "name must be 1 to 120 characters"
    );
    ensure!(
        spec.description.len() <= 2000,
        "description must be at most 2000 characters"
    );
    ensure!(
        (1..=20).contains(&spec.steps.len()),
        "A routine needs 1 to 20 steps"
    );
    let subscription = match &spec.trigger {
        Trigger::Event(EventTrigger::Topic(event)) => Some(event.clone()),
        _ => None,
    };
    let source_keys = match &spec.trigger {
        Trigger::Source { keys } => Some(keys.clone()),
        _ => None,
    };
    let mut steps = Vec::new();
    for (i, step) in spec.steps.iter().enumerate() {
        ensure!(
            !matches!(step.kind, StepKind::System1Sort),
            "Sort inbox classifiers are no longer supported. Use an agent task for reports and questions."
        );
        let label = step.name.trim();
        ensure!(
            !label.is_empty() && label.len() <= 200,
            "Step {} needs a name of 1 to 200 characters",
            i + 1
        );
        steps.push((
            label.to_owned(),
            action(step, source_keys.is_some())
                .with_context(|| format!("Step {} ({label})", i + 1))?,
        ));
    }
    ensure!(
        steps.iter().any(|(_, a)| !matches!(a, Action::Delay(_))),
        "A routine needs a report_to_topic or webhook step"
    );
    let defer_sort = matches!(spec.steps[0].kind, StepKind::System1Sort)
        || spec.steps.iter().any(|step| {
            matches!(step.kind, StepKind::System1Sort) && step.config.get("instructions").is_some()
        });
    let plan = plan(spec.trigger, Utc::now())?;
    let enabled = spec.enabled.unwrap_or(true);
    let base = s
        .accounts
        .public_base
        .read()
        .clone()
        .context("Routines need a public address. Set MEEP_PUBLIC_BASE_URL.")?;
    let (_, p) = s.accounts.project(topic)?;
    let _creating = s.provisioning.lock().await;
    if default && !s.engine.default_sort_pending(topic)? {
        return Ok(Value::Null);
    }
    if default && let Some(binding) = s.engine.prepared_default_sort(topic)? {
        s.engine.activate_default_sort(topic, &binding).await?;
        return Ok(Value::Null);
    }
    let sources = match &source_keys {
        Some(keys) => crate::topic_context::resolve_sources(s, topic, keys).await?,
        None => vec![],
    };
    if steps.iter().any(|(_, a)| matches!(a, Action::Agent { .. })) {
        let context = s.engine.read_topic(topic, |s| json!({
            "mission":s.topic.mission,"goals":s.topic.goals,"linked_sources":s.topic.context_sources,
            "watched_sources":sources
        }).to_string())?;
        // Context is literal data, even when a mission or source label contains Hog syntax.
        let context = context
            .replace('\\', "\\\\")
            .replace('{', "\\{")
            .replace('}', "\\}");
        for (_, action) in &mut steps {
            if let Action::Agent { prompt, source } = action {
                prompt.push_str(&format!("\nTopic context: {context}"));
                if *source {
                    prompt.push_str("\nObserved source data: {variables.author} in {variables.channel}: {variables.text}");
                }
                prompt.push_str("\nReturn reports_json as a compact JSON array under 1500 characters total. Each finding needs title, body (lead/summary), priority (P0 through P4), impact (one sentence with a number), proposal, and evidence (an array of objects with kind, description, source_id and RFC3339 at). Cite real records. Publish nothing if nothing clears the bar: return [].");
            }
        }
    }
    let routines = s.engine.read_topic(topic, |s| s.topic.routines.clone())?;
    let stem = slug(&name);
    let taken = |id: &str| routines.iter().any(|r| r.binding.id == id);
    let id = if default {
        "default:sort-inbox".to_owned()
    } else {
        std::iter::once(stem.clone())
            .chain((2..).map(|n| format!("{stem}-{n}")))
            .find(|id| !taken(id))
            .expect("unbounded candidates")
    };
    let callback = format!("{base}/v1/routines/{topic}/{id}/callback");
    let api = flows(&p)?;
    // PostHog validates the complete graph before anything is bound. The callback
    // secret exists only after binding, so it is written by the final update.
    let (actions, edges) = graph(
        &plan.trigger,
        &steps,
        &callback,
        "pending",
        subscription.is_some(),
    );
    let mut body = json!({"name":name,"description":spec.description,"status":"draft","actions":actions,"edges":edges});
    // Any bound workflow can receive a watch, an assigned task, or an approved action.
    let mut keys = std::collections::BTreeSet::from([
        "text",
        "author",
        "channel",
        "observation",
        "suggestion",
        "confidence",
        "task",
        "title",
        "thread",
        "approved_task",
        "action",
        "draft",
        "source",
        "external_id",
    ]);
    if let Some(subscription) = &subscription {
        keys.insert("event");
        keys.extend(subscription.on.fields());
    }
    let mut variables: Vec<_> = keys
        .into_iter()
        .map(|key| {
            if key == "confidence" {
                json!({"key":key,"type":"number","default":0})
            } else {
                json!({"key":key,"type":"string","default":""})
            }
        })
        .collect();
    if steps.iter().any(|(_, a)| matches!(a, Action::Classify(_))) {
        variables.extend(sort_variables());
    }
    if steps.iter().any(|(_, a)| matches!(a, Action::Agent { .. })) {
        for key in ["reports_json", "report_run"] {
            variables.push(json!({"key":key,"type":"string","default":""}));
        }
    }
    body["variables"] = json!(variables);
    let existing = default
        .then(|| routines.iter().find(|r| r.binding.id == id))
        .flatten();
    let marker = format!("{} [Meep topic {topic}]", spec.description);
    if default {
        body["description"] = json!(marker);
    }
    let known_flow = if default {
        s.engine.default_flow(topic)?
    } else {
        None
    };
    if let Some(binding) = existing {
        ensure!(
            known_flow.as_ref() == Some(&binding.binding.external_id),
            "The default routine ID is already bound to a different workflow"
        );
    }
    let flow = if let Some(flow) = &known_flow {
        flow.clone()
    } else if default && !s.engine.claim_default_create(topic).await? {
        recover_default(&api, &p.token, &marker).await?
    } else {
        let request_key = topic.to_string();
        let result = api
            .post_with_key::<Value>(&p.token, "", body, default.then_some(request_key.as_str()))
            .await;
        if let Err(e) = &result
            && default
            && (e
                .downcast_ref::<meep_posthog::api::ApiError>()
                .is_some_and(|e| (400..500).contains(&e.status))
                || e.downcast_ref::<reqwest::Error>()
                    .is_some_and(|e| e.is_connect()))
        {
            s.engine.release_default_create(topic).await?;
        }
        let created = result.context("PostHog rejected the workflow")?;
        created["id"]
            .as_str()
            .context("PostHog returned no workflow ID")?
            .to_owned()
    };
    if default && known_flow.is_none() {
        s.engine.remember_default_flow(topic, &flow).await?;
    }
    let url = flow_url(&p, &flow);
    let staged = async {
        if existing.is_some() {
            return s.engine.routine_secret(topic, &id).map_err(Into::into);
        }
        if let Some(schedule) = &plan.schedule {
            api.post::<Value>(
                &p.token,
                &format!("{flow}/schedules/"),
                json!({"rrule":schedule.rrule,"timezone":schedule.timezone,"starts_at":schedule.starts_at}),
            )
            .await
            .context("PostHog rejected the schedule")?;
        }
        s.engine
            .bind_routine(
                topic,
                RoutineBinding {
                    watches: vec![],
                    id: id.clone(),
                    name: name.clone(),
                    trigger: if source_keys.is_some() { "Source event".into() } else {plan.summary.clone()},
                    backend: "posthog".into(),
                    external_id: flow.clone(),
                },
            )
            .await
            .context("Could not bind the workflow to this topic")
    }
    .await;
    let secret = match staged {
        Ok(secret) => secret,
        Err(e) => {
            // Leave nothing runnable behind when the routine could not be bound.
            if !default
                && let Err(cleanup) = api
                    .patch::<Value>(&p.token, &format!("{flow}/"), json!({"status":"archived"}))
                    .await
            {
                return Err(e.context(format!("The routine setup failed and its draft could not be archived at {url}: {cleanup}")));
            }
            return Err(e);
        }
    };
    let (actions, edges) = graph(
        &plan.trigger,
        &steps,
        &callback,
        &secret,
        subscription.is_some(),
    );
    // Install the final graph while the remote workflow is still a draft.
    let updated: Value = api
        .patch(
            &p.token,
            &format!("{flow}/"),
            json!({"actions":actions,"edges":edges,"variables":variables,"status":"draft"}),
        )
        .await
        .with_context(|| {
            format!("Routine {id} is bound, but PostHog rejected its final workflow update. Review it at {url}")
        })?;
    if matches!(plan.trigger["type"].as_str(), Some("schedule" | "event")) {
        let key = archive_key(&p, topic, &flow);
        let previous = s.accounts.checkpoints.load(&key)?;
        s.accounts
            .checkpoints
            .commit(&key, previous.as_ref(), &json!("managed"))?;
    }
    if let Some(event) = subscription {
        let routines = s.engine.read_topic(topic, |s| s.topic.routines.clone())?;
        let binding = &routines
            .iter()
            .find(|r| r.binding.id == id)
            .context("Missing event binding")?
            .binding;
        s.engine.subscribe_routine(topic, binding, event).await?;
    }
    if defer_sort {
        let binding = s
            .engine
            .read_topic(topic, |s| {
                s.topic
                    .routines
                    .iter()
                    .find(|r| r.binding.id == id)
                    .cloned()
            })?
            .context("Missing bound workflow")?
            .binding;
        s.engine
            .configure_source_sort(topic, &binding, steps.len() == 1)
            .await?;
    }
    if !default && source_keys.is_some() {
        s.engine
            .set_routine_watches(topic, id.clone(), sources)
            .await?;
    }
    let routine = s
        .engine
        .read_topic(topic, |s| {
            s.topic
                .routines
                .iter()
                .find(|r| r.binding.id == id)
                .cloned()
        })?
        .context("The routine was removed during creation")?;
    if default {
        s.engine
            .activate_default_sort(topic, &routine.binding)
            .await?;
        return Ok(json!({"routine":routine,"url":url}));
    }
    if enabled {
        let mut response =
            activation(s, topic, &routine.binding, spec.depends_on_facts, review).await?;
        response["routine"] = json!(routine);
        response["url"] = json!(url);
        return Ok(response);
    }
    Ok(json!({
        "routine":routine,
        "flow":flow,
        "status":updated["status"],
        "url":url,
    }))
}

async fn activation(
    s: &Server,
    topic: TopicId,
    binding: &RoutineBinding,
    facts: Option<Vec<meep_topic::FactId>>,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    let task = match s
        .engine
        .review_routine_activation(topic, binding, review, facts)
        .await
    {
        Ok(task) => task,
        Err(meep_engine::Error::Topic(meep_topic::TopicError::ActionDenied(rule))) => {
            return Ok(
                json!({"routine":binding.id,"flow":binding.external_id,"status":"denied","rule":rule}),
            );
        }
        Err(error) => return Err(error.into()),
    };
    let status = if task.column == meep_topic::Column::NeedsYou && task.action.is_some() {
        "awaiting_approval"
    } else if task.result.as_deref() == Some(&format!("Activated {}.", binding.name)) {
        "active"
    } else {
        "check_delivery"
    };
    Ok(
        json!({"routine":binding.id,"flow":binding.external_id,"status":status,"task":task.id,"detail":task.result}),
    )
}

pub(super) async fn switch(
    s: &Server,
    topic: TopicId,
    routine: &str,
    enabled: bool,
    facts: Option<Vec<meep_topic::FactId>>,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    let routines = s.engine.read_topic(topic, |s| s.topic.routines.clone())?;
    let binding = routines
        .iter()
        .find(|r| r.binding.id == routine)
        .map(|r| &r.binding)
        .with_context(|| format!("This topic has no routine {routine}"))?;
    ensure!(
        binding.backend == "posthog",
        "Only PostHog routines can be switched here"
    );
    let flow: Uuid = binding
        .external_id
        .parse()
        .context("The routine has no PostHog workflow ID")?;
    let (_, p) = s.accounts.project(topic)?;
    if enabled {
        let mut response = activation(s, topic, binding, facts, review).await?;
        response["url"] = json!(flow_url(&p, &flow.to_string()));
        return Ok(response);
    }
    let updated: Value = flows(&p)?
        .patch(&p.token, &format!("{flow}/"), json!({"status":"draft"}))
        .await
        .context("PostHog rejected the change")?;
    if updated["status"] == "draft" {
        s.engine.set_event_delivery(topic, binding, false).await?;
    }
    Ok(
        json!({"routine":routine,"flow":flow,"status":updated["status"],"url":flow_url(&p, &flow.to_string())}),
    )
}

pub(super) async fn run(
    s: &Server,
    topic: TopicId,
    routine: &str,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    ensure!(
        s.engine.read_topic(topic, |s| s
            .topic
            .routines
            .iter()
            .any(|r| r.binding.id == routine))?,
        "This topic has no routine {routine}. Use list_routines."
    );
    let task = s
        .engine
        .review_routine_run(topic, routine, Default::default(), review)
        .await?;
    Ok(
        json!({"routine":routine,"task":task.id,"status":if task.column==meep_topic::Column::NeedsYou && task.action.is_some() {"awaiting_approval"}else if task.result.as_deref().is_some_and(|r|r.starts_with("Started ")){ "started" }else{"check_delivery"},"detail":task.result}),
    )
}

pub(super) async fn bind(
    s: &Server,
    topic: TopicId,
    flow: Uuid,
    review: WorkflowReview<'_>,
) -> Result<Value> {
    let _creating = s.provisioning.lock().await;
    let routines = s.engine.read_topic(topic, |s| s.topic.routines.clone())?;
    if let Some(existing) = routines
        .iter()
        .find(|r| r.binding.backend == "posthog" && r.binding.external_id == flow.to_string())
    {
        bail!(
            "Workflow {flow} is already bound as routine {}",
            existing.binding.id
        );
    }
    let (_, p) = s.accounts.project(topic)?;
    let definition: Value = flows(&p)?
        .get(&p.token, &format!("{flow}/"))
        .await
        .context("PostHog has no readable workflow with that ID")?;
    ensure!(
        definition["status"] != "archived",
        "Workflow {flow} is archived"
    );
    let name = definition["name"]
        .as_str()
        .map(str::trim)
        .filter(|n| !n.is_empty())
        .unwrap_or("PostHog workflow")
        .chars()
        .take(120)
        .collect::<String>();
    let trigger = definition["actions"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|a| a["type"] == "trigger")
        .and_then(|a| a["config"]["type"].as_str())
        .map_or_else(
            || "PostHog workflow".to_owned(),
            |t| format!("PostHog {t} trigger"),
        );
    let stem = slug(&name);
    let taken = |id: &str| routines.iter().any(|r| r.binding.id == id);
    let id = std::iter::once(stem.clone())
        .chain((2..).map(|n| format!("{stem}-{n}")))
        .find(|id| !taken(id))
        .expect("unbounded candidates");
    let binding = RoutineBinding {
        watches: vec![],
        id: id.clone(),
        name: name.clone(),
        trigger,
        backend: "posthog".into(),
        external_id: flow.to_string(),
    };
    if definition["status"] == "active" {
        let task = s
            .engine
            .review_active_binding(topic, binding, review)
            .await?;
        return Ok(
            json!({"routine":id,"flow":flow,"task":task.id,"status":if task.column==meep_topic::Column::NeedsYou && task.action.is_some() {"awaiting_approval"}else if task.result.as_deref().is_some_and(|r|r.starts_with("Bound ")){ "active" }else{"check_delivery"},"detail":task.result}),
        );
    }
    s.engine.bind_routine(topic, binding).await?;
    Ok(json!({
        "routine":id,
        "name":name,
        "flow":flow,
        "status":definition["status"],
        "url":flow_url(&p, &flow.to_string()),
    }))
}

/// Point every bound workflow's Meep callbacks at the current public address.
/// A callback URL is written into the workflow when it is created, so a new
/// address (a restarted tunnel, say) would otherwise leave every routine calling
/// the old one. Returns how many workflows changed.
pub(crate) async fn retarget_callbacks(s: &Server) -> Result<usize> {
    let Some(base) = s.accounts.public_base.read().clone() else {
        return Ok(0);
    };
    let mut changed = 0;
    for state in s.engine.topics() {
        let topic = state.topic.id;
        let Ok((_, p)) = s.accounts.project(topic) else {
            continue;
        };
        let api = flows(&p)?;
        for r in state
            .topic
            .routines
            .iter()
            .filter(|r| r.binding.backend == "posthog")
        {
            let flow = &r.binding.external_id;
            let Ok(current) = api.get::<Value>(&p.token, &format!("{flow}/")).await else {
                continue;
            };
            let mut actions = current["actions"].clone();
            if retarget(&mut actions, &base) {
                // An API write updates the live workflow, not the editor's draft.
                api.patch::<Value>(&p.token, &format!("{flow}/"), json!({ "actions": actions }))
                    .await
                    .with_context(|| format!("Could not update routine {}", r.binding.id))?;
                changed += 1;
            }
        }
    }
    Ok(changed)
}

/// Rewrite each step URL that calls a Meep routine endpoint onto `base`, keeping
/// its path. PostHog recompiles the input from its new value.
fn retarget(actions: &mut Value, base: &str) -> bool {
    let mut changed = false;
    for action in actions.as_array_mut().into_iter().flatten() {
        let Some(input) = action.pointer_mut("/config/inputs/url") else {
            continue;
        };
        let Some(old) = input["value"].as_str() else {
            continue;
        };
        let Some(at) = old.find("/v1/routines/") else {
            continue;
        };
        let new = format!("{base}{}", &old[at..]);
        if new != old {
            *input = json!({ "value": new });
            changed = true;
        }
    }
    changed
}

#[cfg(test)]
mod retarget_tests {
    use super::*;

    #[test]
    fn callbacks_move_to_the_new_address_and_other_webhooks_stay() {
        let mut actions = json!([
            {"config":{"inputs":{"url":{"value":"https://old.example/owners/o/v1/routines/t/r/callback","bytecode":["_H"]}}}},
            {"config":{"inputs":{"url":{"value":"https://hooks.slack.com/x"}}}},
            {"config":{}}
        ]);
        assert!(retarget(&mut actions, "https://new.example/owners/o"));
        assert_eq!(
            actions[0]["config"]["inputs"]["url"],
            json!({"value":"https://new.example/owners/o/v1/routines/t/r/callback"})
        );
        assert_eq!(
            actions[1]["config"]["inputs"]["url"]["value"],
            "https://hooks.slack.com/x"
        );
        assert!(!retarget(&mut actions, "https://new.example/owners/o"));
    }
}
