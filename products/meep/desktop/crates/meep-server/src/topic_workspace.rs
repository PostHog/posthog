//! Topic MCP tools for the workspace: the topics a run can read, new topics and views.
//! A new topic starts its own setup conversation; a new view starts its authoring run.
use crate::{
    Server,
    topic_mcp::{Caller, apply, input, no_args, shared_topics},
};
use anyhow::{Context, Result, ensure};
use chrono::Utc;
use meep_topic::{Column, ThreadState, TopicId};
use meep_wire::views::{Stage, ViewCommand, ViewEnvelope};
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

pub(super) fn tools() -> Vec<Value> {
    let text = json!({"type":"string"});
    vec![
        crate::mcp::tool(
            "list_topics",
            "List the topics this run can read: this topic and the others shared with its account, with missions and what needs the person.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "create_topic",
            "Create a topic with a name and mission. It shares this topic's PostHog account and starts its own setup conversation.",
            json!({"name":text,"mission":text}),
            &["name", "mission"],
        ),
        crate::mcp::tool(
            "list_views",
            "List the workspace's views and the state of their latest authoring request.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "create_view",
            "Create a view from a description of the page the person wants. It is built in its own authoring conversation.",
            json!({"prompt":text}),
            &["prompt"],
        ),
    ]
}

/// Run a workspace tool, or `None` when the name belongs to another tool set.
pub(super) async fn call(
    s: &Server,
    caller: &Caller,
    name: &str,
    args: Value,
) -> Option<Result<Value>> {
    Some(match name {
        "list_topics" => no_args(args).and_then(|()| topics(s, caller)),
        "create_topic" => create_topic(s, caller, args).await,
        "list_views" => no_args(args).map(|()| views(s)),
        "create_view" => create_view(s, args),
        _ => return None,
    })
}

fn topics(s: &Server, caller: &Caller) -> Result<Value> {
    let mut ids = vec![caller.topic];
    ids.extend(
        shared_topics(s, caller.topic)
            .into_iter()
            .filter(|t| *t != caller.topic),
    );
    Ok(json!(
        ids.into_iter()
            .filter_map(|id| s.engine.topic(id).ok())
            .map(|state| {
                let threads = state
                    .threads
                    .iter()
                    .filter(|t| matches!(t.state, ThreadState::NeedsYou { .. }))
                    .count();
                let tasks = state
                    .tasks
                    .iter()
                    .filter(|t| t.column == Column::NeedsYou)
                    .count();
                json!({
                    "id":state.topic.id,
                    "name":state.topic.name,
                    "mission":state.topic.mission,
                    "this_topic":state.topic.id == caller.topic,
                    "needs_you":{"threads":threads,"tasks":tasks},
                })
            })
            .collect::<Vec<_>>()
    ))
}

async fn create_topic(s: &Server, caller: &Caller, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        name: String,
        mission: String,
    }
    let Args { name, mission } = input(args)?;
    let (name, mission) = (name.trim(), mission.trim());
    ensure!(
        !name.is_empty() && name.chars().count() <= 120,
        "name must be 1 to 120 characters"
    );
    ensure!(
        !mission.is_empty() && mission.chars().count() <= 4000,
        "mission must be 1 to 4000 characters"
    );
    let id: TopicId = Uuid::new_v4().into();
    apply(
        s,
        id,
        meep_topic::Command::CreateTopic {
            name: name.into(),
            mission: mission.into(),
        },
    )
    .await?;
    // Share the caller's PostHog account so the new topic's setup run can start.
    let shared = match s.accounts.project(caller.topic) {
        Ok((connection, _)) => {
            let guard = s.engine.connection_guard(&connection).await;
            let accounts = s.accounts.clone();
            s.accounts
                .jobs
                .clone()
                .spawn_blocking(move || {
                    let _guard = guard;
                    accounts.grant(&connection, id)
                })
                .await
                .context("Granting the account was interrupted")?
                .context("The topic was created, but its PostHog account could not be shared")?;
            s.engine.wake_topic(id);
            true
        }
        Err(_) => false,
    };
    Ok(json!({
        "id":id,
        "name":name,
        "mission":mission,
        "setup":if shared {"starting"} else {"waiting for a PostHog account"},
    }))
}

fn views(s: &Server) -> Value {
    json!(
        s.views
            .list()
            .iter()
            .map(|v| {
                let latest = v.turns.last();
                json!({
                    "id":v.id,
                    "title":v.title,
                    "icon":v.icon,
                    "generation":v.generation(),
                    "latest_request":latest.map(|t| &t.prompt),
                    "status":latest.map(|t| match &t.stage {
                        Stage::Queued | Stage::Starting => "queued".to_owned(),
                        Stage::Working(progress) => format!("working: {progress}"),
                        Stage::Finished(result) => format!("finished: {result}"),
                    }),
                })
            })
            .collect::<Vec<_>>()
    )
}

fn create_view(s: &Server, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        prompt: String,
    }
    let Args { prompt } = input(args)?;
    let prompt = prompt.trim();
    ensure!(
        !prompt.is_empty() && prompt.chars().count() <= 8000,
        "prompt must be 1 to 8000 characters"
    );
    let id = Uuid::new_v4();
    let view = s
        .views
        .command(ViewEnvelope {
            id: Uuid::new_v4(),
            view: id,
            at: Utc::now(),
            command: ViewCommand::Create {
                prompt: prompt.into(),
                options: Default::default(),
            },
        })
        .map_err(|e| anyhow::anyhow!("Could not create the view: {e}"))?;
    Ok(json!({"id":view.id,"title":view.title,"status":"queued"}))
}
