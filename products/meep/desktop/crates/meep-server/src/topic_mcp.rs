//! Stateless Streamable HTTP MCP for a topic's agent runs. A capability authorizes
//! one run on one topic and lasts while the engine observes that run.
//!
//! Its tools cover the product: the topic and its knowledge and sources (`topic_context`),
//! inbox, tasks and files (`topic_work`), routines (here) and the workspace
//! (`topic_workspace`). Routines are PostHog workflows (hog flows) bound to the topic.
//! Report steps call the topic's authenticated routine callback.
use crate::auth::fingerprint;
use crate::topic_workflows::{Spec, bind, create, create_template, list, run, switch, templates};
use crate::{
    Server,
    accounts::Accounts,
    auth::matches_secret,
    http::{App, Failure, bearer},
    posthog::AccountRun,
};
use anyhow::{Context, Result, bail, ensure};
use axum::{
    Json,
    extract::Path,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use chrono::Utc;
use meep_topic::TopicId;
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicBool, Ordering};
use uuid::Uuid;

/// How long a started run's capability stays valid before the engine records its handle.
const LAUNCH_GRACE: std::time::Duration = std::time::Duration::from_secs(30);

/// A bearer credential minted for one agent run on one topic.
pub(crate) struct Capability {
    pub url: String,
    pub token: String,
    fingerprint: String,
}
impl Capability {
    /// Mint a capability, or `None` without a public base. The run then starts without tools.
    pub fn issue(accounts: &Accounts, topic: TopicId, connection: &str) -> Option<Self> {
        static WARNED: AtomicBool = AtomicBool::new(false);
        let Some(base) = accounts.public_base.read().clone() else {
            if !WARNED.swap(true, Ordering::Relaxed) {
                log::info!(
                    "Topic agent runs start without Meep tools. Configure MEEP_PUBLIC_BASE_URL to enable the meep-topic MCP."
                );
            }
            return None;
        };
        let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let fingerprint = fingerprint(&token);
        accounts
            .launching
            .lock()
            .push((fingerprint.clone(), topic, connection.into(), None));
        Some(Self {
            url: format!("{base}/v1/topics/{topic}/mcp"),
            token,
            fingerprint,
        })
    }
    /// End the launch and return the fingerprint saved with the run handle. A started run
    /// keeps its launch grant briefly, because the engine records the handle only after the
    /// start returns and the agent may call a tool before then. A failed start revokes it.
    pub fn finish(self, accounts: &Accounts, started: bool) -> String {
        let mut launching = accounts.launching.lock();
        let now = std::time::Instant::now();
        // Drop expired grants, then start this run's grace or revoke its failed launch.
        launching.retain(|(.., until)| until.is_none_or(|t| t > now));
        if started {
            for slot in launching
                .iter_mut()
                .filter(|(f, ..)| *f == self.fingerprint)
            {
                slot.3 = Some(now + LAUNCH_GRACE);
            }
        } else {
            launching.retain(|(f, ..)| *f != self.fingerprint);
        }
        self.fingerprint
    }
}

/// The agent run a capability was issued to.
pub(crate) struct Caller {
    /// The run's topic. Tools change only this topic.
    pub topic: TopicId,
    /// The PostHog task behind the run, once its start is confirmed.
    pub task: Option<Uuid>,
    run: Option<meep_engine::RunHandle>,
}

impl Caller {
    /// The engine's handle for the calling run, once its start is confirmed.
    pub fn run(&self) -> Option<&meep_engine::RunHandle> {
        self.run.as_ref()
    }
}

fn authorized(s: &Server, topic: TopicId, token: &str) -> Option<Caller> {
    if !s.engine.topic_active(topic) {
        return None;
    }
    let presented = fingerprint(token);
    let recorded = s
        .engine
        .active_runs(topic)
        .unwrap_or_default()
        .into_iter()
        .filter_map(|h| {
            serde_json::from_value::<AccountRun>(h.0.clone())
                .ok()
                .map(|r| (r, h))
        })
        .find(|(r, _)| {
            r.topic == topic
                && r.has_grant(&s.accounts)
                && r.capability
                    .as_deref()
                    .is_some_and(|c| matches_secret(c, &presented))
        });
    let mut launching = s.accounts.launching.lock();
    if let Some((r, h)) = recorded {
        // The engine holds the run now; its launch grant is no longer needed.
        launching.retain(|(f, ..)| !matches_secret(f, &presented));
        return Some(Caller {
            run: Some(h),
            topic,
            task: r.posthog_task(),
        });
    }
    let now = std::time::Instant::now();
    launching
        .iter()
        .any(|(f, t, connection, until)| {
            *t == topic
                && until.is_none_or(|t| t > now)
                && matches_secret(f, &presented)
                && s.accounts
                    .get(connection)
                    .is_some_and(|a| a.public.grants.contains(&topic))
        })
        .then_some(Caller {
            topic,
            task: None,
            run: None,
        })
}

/// Decode tool arguments, rejecting unknown fields with a readable message.
pub(crate) fn input<T: for<'de> Deserialize<'de>>(args: Value) -> Result<T> {
    serde_json::from_value(args).map_err(|e| anyhow::anyhow!("Invalid input: {e}"))
}

pub(super) fn no_args(args: Value) -> Result<()> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct None {}
    input::<None>(args).map(|_| ())
}

/// Topics this topic's PostHog account was also granted. Their records are readable.
pub(crate) fn shared_topics(s: &Server, topic: TopicId) -> Vec<TopicId> {
    let Ok((connection, _)) = s.accounts.project(topic) else {
        return vec![];
    };
    s.accounts
        .get(&connection)
        .map(|a| a.public.grants.clone())
        .unwrap_or_default()
}

/// Resolve the topic a read tool addresses: the caller's own, or one shared with its account.
pub(crate) fn readable(s: &Server, caller: &Caller, topic: Option<TopicId>) -> Result<TopicId> {
    match topic {
        None => Ok(caller.topic),
        Some(t) if t == caller.topic => Ok(t),
        Some(t) => {
            ensure!(
                shared_topics(s, caller.topic).contains(&t) && s.engine.topic(t).is_ok(),
                "Topic {t} is not shared with this topic's account. Use list_topics to find readable topics."
            );
            Ok(t)
        }
    }
}

/// Apply one topic command, as a device would, so it replicates like any other edit.
pub(crate) async fn apply(s: &Server, topic: TopicId, command: meep_topic::Command) -> Result<()> {
    if let meep_topic::Command::StartRoutine { routine, variables } = command {
        s.engine
            .request_routine_run(topic, &routine, variables)
            .await?;
        return Ok(());
    }
    s.engine
        .apply(meep_topic::Envelope {
            id: Uuid::new_v4().into(),
            topic,
            issued_at: Utc::now(),
            command,
        })
        .await?;
    Ok(())
}

/// Tools that only read. They take an optional `topic` to read another shared topic.
const READS: &[&str] = &[
    "list_routine_templates",
    "get_topic",
    "list_facts",
    "list_sources",
    "list_threads",
    "get_thread",
    "list_tasks",
    "get_task",
    "list_files",
    "read_file",
    "list_routines",
    "list_topics",
    "list_views",
];

const ROUTINES: &str = "Routines are PostHog workflows bound to the topic. For scheduled analysis add a report_to_topic step with op \"agent\" and describe the work in text. Its PostHog workflow agent returns sourced findings to the topic. Report text is a PostHog Hog template: literal text with {expressions} such as {event.properties.$current_url}; escape a literal brace as \\{. Create routines only when the person explicitly asks for monitoring or automation.";

fn routine_tools() -> Vec<Value> {
    let text = json!({"type":"string"});
    let trigger = json!({
        "description":"When the routine runs. source: Meep dispatches updates for exact keys from list_sources. schedule: either rrule (RFC 5545 RRULE body, at most hourly, e.g. FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0) or hour with optional minute and days (MO..SU, default every day). timezone is an IANA name (default UTC). event: use on and an optional exact field filter for a Meep topic event, or events for PostHog analytics events. manual: run only when started.",
        "oneOf":[
            {"type":"object","properties":{
                "type":{"const":"schedule"},
                "rrule":text,
                "days":{"type":"array","items":{"enum":["MO","TU","WE","TH","FR","SA","SU"]},"minItems":1,"uniqueItems":true},
                "hour":{"type":"integer","minimum":0,"maximum":23},
                "minute":{"type":"integer","minimum":0,"maximum":59},
                "timezone":text,
                "starts_at":{"type":"string","format":"date-time"}
            },"required":["type"],"additionalProperties":false},
            {"type":"object","properties":{"type":{"const":"event"},"events":{"type":"array","items":text,"minItems":1,"maxItems":20}},"required":["type","events"],"additionalProperties":false},
            {"type":"object","properties":{"type":{"const":"event"},"on":{"enum":["message_arrived","task_added","task_moved","fact_changed","routine_failed"]},"filter":{"type":"object","additionalProperties":{"type":"string"}}},"required":["type","on"],"additionalProperties":false},
            {"type":"object","properties":{"type":{"const":"source"},"keys":{"type":"array","items":text,"maxItems":50,"uniqueItems":true}},"required":["type","keys"],"additionalProperties":false},
            {"type":"object","properties":{"type":{"const":"manual"}},"required":["type"],"additionalProperties":false}
        ]
    });
    let step = json!({"type":"object","properties":{
        "name":text,
        "kind":{"enum":["report_to_topic","delay","webhook"]},
        "config":{"type":"object","description":"report_to_topic: {op: note|fact|agent, text}; use agent for analysis and reports. Source routines also accept {op: drop, reason}. delay: {duration: e.g. 30m, 2h, 1d}. webhook: {url (https), method?: GET|POST|PUT|PATCH|DELETE, headers?: {name: value}, body?: JSON}."}
    },"required":["name","kind","config"],"additionalProperties":false});
    let mut create = crate::mcp::tool(
        "create_routine",
        "Create a PostHog workflow from a trigger and ordered steps, bind it to this topic and return the routine and its PostHog link. Source triggers carry an observation ID. Custom source steps can also reference text, author and channel. Use report_to_topic with drop, note, fact or agent. The agent step takes analysis instructions in text and returns sourced reports to this topic. Meep fills the observation key. Alternatively pass template and optional sources from list_routine_templates.",
        json!({"template":text,"sources":{"type":"array","items":text},"name":text,"description":text,"trigger":trigger,"steps":{"type":"array","items":step,"minItems":1,"maxItems":20},"depends_on_facts":{"type":"array","items":{"type":"string"},"description":"Topic fact IDs required for this activation. Use [] for independent work."},"enabled":{"type":"boolean","description":"Request activation under the topic permission rules (default true)."}}),
        &[],
    );
    create["inputSchema"]["oneOf"] =
        json!([{"required":["template"]},{"required":["name","trigger","steps"]}]);
    let mut report = crate::mcp::tool(
        "publish_report",
        "Publish a sourced report to the current task's topic inbox, or set topic to a shared destination from list_topics. Write it like a PostHog Scout report: a title that names the outcome to change, a summary whose first paragraph is the lead, a priority (P0 drop everything … P4 worth knowing), an impact sentence with the number that matters (\"4,749 users who see the error toast\"), a proposal saying what you would do, and named evidence with source identifiers or links, a kind and when it happened. The person can implement, investigate, resolve or dismiss it from the inbox. Legacy body and sources fields are also accepted. Keep questions and routine progress in the task conversation.",
        json!({"title":text,"summary":text,"priority":{"type":"string","enum":["P0","P1","P2","P3","P4"]},"impact":text,"proposal":text,"evidence":{"type":"array","maxItems":50,"items":{"type":"object","properties":{"description":text,"source_id":text,"kind":{"type":"string","enum":["replay","error","event","insight","ticket","slack","github","survey","log","other"]},"at":{"type":"string","format":"date-time"}},"required":["description","source_id"],"additionalProperties":false}},"body":text,"sources":{"type":"array","items":text,"maxItems":32}}),
        &["title"],
    );
    report["inputSchema"]["allOf"] = json!([
        {"oneOf":[{"required":["summary"]},{"required":["body"]}]},
        {"anyOf":[
            {"required":["evidence"],"properties":{"evidence":{"minItems":1}}},
            {"required":["sources"],"properties":{"sources":{"minItems":1}}}
        ]}
    ]);
    vec![
        crate::mcp::tool(
            "list_source_observations",
            "Read recent connector evidence in this topic for a sourced report. Cite the connection, channel and external record ID or link.",
            json!({"limit":{"type":"integer","minimum":1,"maximum":100}}),
            &[],
        ),
        report,
        crate::mcp::tool(
            "ask_user",
            "Ask the person for input needed to finish the current task. The question waits in the task conversation. Stop after calling and continue when the person replies.",
            json!({"question":{"type":"string","minLength":1,"maxLength":8000}}),
            &["question"],
        ),
        crate::mcp::tool(
            "propose_action",
            "Submit an external action for the current investigation under topic policy.",
            json!({"task":text,"kind":text,"label":text,"done_label":text,"payload":{},"draft":text,"depends_on_facts":{"type":"array","items":text}}),
            &["kind", "label", "done_label", "payload", "depends_on_facts"],
        ),
        crate::mcp::tool(
            "list_routine_templates",
            "List available workflow templates.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "list_routines",
            "List this topic's routines with their sources, recent observation outcomes, triggers, steps and status.",
            json!({}),
            &[],
        ),
        create,
        crate::mcp::tool(
            "set_routine_sources",
            "Replace this routine's source list using exact list_sources keys. Selected watches move from their previous owners. Configure monitoring only when the person requests it.",
            json!({"routine":text,"keys":{"type":"array","items":text,"maxItems":50,"uniqueItems":true}}),
            &["routine", "keys"],
        ),
        crate::mcp::tool(
            "set_routine_enabled",
            "Activate or pause one of this topic's PostHog routines. Activation follows the topic's routine-activate rules and may wait for the person's approval.",
            json!({"routine":text,"depends_on_facts":{"type":"array","items":{"type":"string"},"description":"Topic fact IDs required for this activation. Use [] for independent work."},"enabled":{"type":"boolean"}}),
            &["routine", "enabled"],
        ),
        crate::mcp::tool(
            "run_routine",
            "Run one of this topic's routines now.",
            json!({"routine":text}),
            &["routine"],
        ),
        crate::mcp::tool(
            "bind_routine",
            "Bind an existing PostHog workflow to this topic as a routine. Its status in PostHog is unchanged.",
            json!({"flow_id":{"type":"string","format":"uuid"}}),
            &["flow_id"],
        ),
    ]
}

pub(super) async fn mcp(
    axum::Extension(a): axum::Extension<App>,
    Path(crate::http::ObjectPath { id: topic }): Path<crate::http::ObjectPath<TopicId>>,
    headers: HeaderMap,
    Json(req): Json<Value>,
) -> Result<Response, Failure> {
    log::info!(
        "topic MCP {} for {topic} (origin {:?})",
        req["method"].as_str().unwrap_or("?"),
        headers.get("origin").and_then(|o| o.to_str().ok())
    );
    let token = bearer(&headers)?;
    let Some(caller) = authorized(&a.s, topic, token) else {
        log::info!("topic MCP rejected: unknown or expired capability for {topic}");
        return Err(Failure::auth());
    };
    if !a.s.accepts_mcp_origin(&headers) {
        return Ok(StatusCode::FORBIDDEN.into_response());
    }
    Ok(crate::mcp::respond(
        &req,
        "meep-topic",
        || {
            format!(
                "{}\n\n## Routines\n{ROUTINES}",
                meep_engine::MEEP_SKILL.trim_end()
            )
        },
        all_tools,
        async |name, args| {
            call(&a.s, &caller, name, args)
                .await
                .map(|mut v| {
                    // A request that needs the person's OK ends the conversation's turn;
                    // the answer comes back as its next turn.
                    if caller
                        .run
                        .as_ref()
                        .is_some_and(|r| a.s.engine.is_session_run(topic, r))
                        && a.s.engine.session_prompt_open(topic)
                        && let Some(o) = v.as_object_mut()
                    {
                        o.insert(
                            "next".into(),
                            json!("This needs the person's approval. Tell them briefly what you asked for and why, then end your turn. Their answer comes back to you in this conversation."),
                        );
                    }
                    v.to_string()
                })
                .map_err(|e| format!("{e:#}"))
        },
    )
    .await)
}

/// Every tool, in the order an agent reads them: topic, knowledge, sources, inbox, tasks,
/// files, routines, then the workspace.
pub(crate) fn all_tools() -> Vec<Value> {
    let mut all = crate::topic_context::tools();
    all.extend(crate::topic_work::tools());
    all.extend(routine_tools());
    all.extend(crate::topic_workspace::tools());
    // Read tools can address another topic shared with this topic's account.
    for tool in &mut all {
        let name = tool["name"].as_str().unwrap_or_default();
        if (READS.contains(&name) && !matches!(name, "list_topics" | "list_views"))
            || name == "publish_report"
        {
            let description = if name == "publish_report" {
                "Target topic shared with this account, from list_topics. Defaults to this topic."
            } else {
                "Another topic to read, from list_topics. Defaults to this topic."
            };
            tool["inputSchema"]["properties"]["topic"] =
                json!({"type":"string","format":"uuid","description":description});
        }
    }
    all
}

async fn call(s: &Server, caller: &Caller, name: &str, args: &Value) -> Result<Value> {
    let mut args = if args.is_null() {
        json!({})
    } else {
        args.clone()
    };
    let requested = args
        .as_object_mut()
        .context("Tool arguments must be an object")?
        .remove("topic");
    let topic = if READS.contains(&name) || name == "publish_report" {
        readable(s, caller, requested.map(input::<TopicId>).transpose()?)?
    } else {
        ensure!(
            requested
                .as_ref()
                .is_none_or(|t| t.as_str() == Some(&caller.topic.to_string())),
            "Other topics are read-only. {name} changes only this run's topic."
        );
        caller.topic
    };
    if let Some(result) = crate::topic_context::call(s, caller, topic, name, args.clone()).await {
        return result;
    }
    if let Some(result) = crate::topic_work::call(s, caller, topic, name, args.clone()).await {
        return result;
    }
    if let Some(result) = crate::topic_workspace::call(s, caller, name, args.clone()).await {
        return result;
    }
    let review = || {
        caller
            .run
            .as_ref()
            .map(meep_engine::WorkflowReview::Investigation)
            .context("Retry after the task starts")
    };
    match name {
        "list_source_observations" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Args {
                limit: Option<usize>,
            }
            let Args { limit } = input(args)?;
            let limit = limit.unwrap_or(25);
            ensure!((1..=100).contains(&limit), "limit must be 1 to 100");
            Ok(json!(s.engine.source_observations(topic, limit)?))
        }
        "publish_report" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Args {
                title: String,
                summary: Option<String>,
                body: Option<String>,
                priority: Option<String>,
                impact: Option<String>,
                proposal: Option<String>,
                evidence: Option<Vec<meep_topic::ReportEvidence>>,
                sources: Option<Vec<String>>,
            }
            let Args {
                title,
                summary,
                body,
                priority,
                impact,
                proposal,
                evidence,
                sources,
            } = input(args)?;
            let priority = priority
                .map(|p| meep_topic::ReportPriority::parse(&p).context("priority must be P0 to P4"))
                .transpose()?;
            ensure!(
                summary.is_none() || body.is_none(),
                "Provide summary or body, not both"
            );
            let body = summary.or(body).context("Provide a report summary")?;
            let thread = s
                .engine
                .publish_task_report_to_topic(
                    caller.topic,
                    topic,
                    caller.run.as_ref().context("Retry after the run starts")?,
                    &title,
                    &body,
                    meep_topic::ReportSources {
                        references: sources.unwrap_or_default(),
                        evidence: evidence.unwrap_or_default(),
                        priority,
                        impact,
                        proposal,
                        ..Default::default()
                    },
                )
                .await?;
            Ok(json!({"thread":thread}))
        }
        "ask_user" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Args {
                question: String,
            }
            let Args { question } = input(args)?;
            // In the topic's conversation the person reads the reply: just ask there.
            if caller
                .run
                .as_ref()
                .is_some_and(|r| s.engine.is_session_run(topic, r))
            {
                return Ok(
                    json!({"status":"ask_in_reply","next":"Ask this in your reply and end your turn; the person's answer comes back to you in this conversation.","question":question}),
                );
            }
            s.engine
                .ask_user(
                    topic,
                    caller.run.as_ref().context("Retry after the run starts")?,
                    &question,
                )
                .await?;
            Ok(json!({"status":"awaiting_input"}))
        }
        "propose_action" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Proposal {
                task: Option<meep_topic::TaskId>,
                kind: meep_topic::ActionKind,
                label: String,
                done_label: String,
                payload: Value,
                draft: Option<String>,
                depends_on_facts: Vec<meep_topic::FactId>,
            }
            let p: Proposal = input(args)?;
            let action = meep_topic::Action {
                kind: p.kind,
                label: p.label,
                done_label: p.done_label,
                payload: p.payload,
                depends_on_facts: Some(p.depends_on_facts),
            };
            s.engine
                .propose_action(
                    topic,
                    caller.run.as_ref().context("Retry after the run starts")?,
                    p.task,
                    action,
                    p.draft,
                )
                .await?;
            Ok(json!({"submitted":true}))
        }
        "list_routines" => list(s, topic).await,
        "set_routine_sources" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Sources {
                routine: String,
                keys: Vec<String>,
            }
            let Sources { routine, keys } = input(args)?;
            let binding = s
                .engine
                .topic(topic)?
                .topic
                .routines
                .into_iter()
                .find(|r| r.binding.id == routine)
                .context("Unknown routine")?;
            ensure!(
                matches!(binding.binding.backend.as_str(), "posthog" | "system"),
                "Source routines require PostHog or Sort inbox"
            );
            let watches = crate::topic_context::resolve_sources(s, topic, &keys).await?;
            s.engine
                .set_routine_watches(topic, routine.clone(), watches.clone())
                .await?;
            Ok(json!({"routine":routine,"watches":watches}))
        }
        "run_routine" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Run {
                routine: String,
            }
            let Run { routine } = input(args)?;
            run(s, topic, &routine, review()?).await
        }
        "bind_routine" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Bind {
                flow_id: Uuid,
            }
            let Bind { flow_id } = input(args)?;
            bind(s, topic, flow_id, review()?).await
        }
        "list_routine_templates" => Ok(json!(templates())),
        "create_routine" if args.get("template").is_some() => {
            create_template(s, topic, input(args)?, review()?).await
        }
        "create_routine" => {
            let spec: Spec = serde_json::from_value(args)
                .map_err(|e| anyhow::anyhow!("Invalid routine: {e}"))?;
            create(s, topic, spec, false, review()?).await
        }
        "set_routine_enabled" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Switch {
                routine: String,
                enabled: bool,
                depends_on_facts: Option<Vec<meep_topic::FactId>>,
            }
            let Switch {
                routine,
                enabled,
                depends_on_facts,
            } = input(args)?;
            switch(s, topic, &routine, enabled, depends_on_facts, review()?).await
        }
        _ => bail!("Unknown topic tool"),
    }
}
