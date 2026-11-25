//! Browse what a topic's PostHog task runs produced. Meep proxies listings and
//! bytes on request and keeps nothing on disk; the desktop caches what it opens.
use crate::{Server, posthog::AccountRun};
use anyhow::{Context, Result};
use futures_util::{StreamExt, TryStreamExt, stream};
use meep_posthog::tasks::{
    Tasks,
    artifacts::{LivingArtifact, RunArtifact},
};
use meep_topic::{TaskId, TopicId};
use meep_wire::TaskArtifact;
use parking_lot::Mutex;
use std::{
    collections::HashMap,
    sync::OnceLock,
    time::{Duration, Instant},
};
use uuid::Uuid;

/// Repeated visits to the Files tab within this window reuse the last listing.
const MEMO: Duration = Duration::from_secs(30);
/// Run files the person or the runtime supplied, rather than the agent's output.
const INPUTS: [&str; 5] = [
    "user_attachment",
    "tree_snapshot",
    "skill_bundle",
    "context",
    "reference",
];

type Memo = Mutex<HashMap<TopicId, (Instant, Vec<TaskArtifact>)>>;
fn memo() -> &'static Memo {
    static MEMO: OnceLock<Memo> = OnceLock::new();
    MEMO.get_or_init(Default::default)
}

/// The PostHog task, project and client behind a Meep task's runs.
fn posthog(s: &Server, topic: TopicId, task: TaskId) -> Result<Option<(Tasks, String, Uuid)>> {
    let Some((_, handle)) = s
        .engine
        .task_runs(topic)?
        .into_iter()
        .find(|(t, _)| *t == task)
    else {
        return Ok(None);
    };
    let Ok(run) = serde_json::from_value::<AccountRun>(handle.0) else {
        return Ok(None);
    };
    let Some(remote) = run.posthog_task() else {
        return Ok(None);
    };
    let project = run.project(&s.accounts)?;
    Ok(Some((
        Tasks::new(&project.origin, project.project)?,
        project.token.clone(),
        remote,
    )))
}

/// Every artifact the topic's task runs produced, newest task first.
pub(crate) async fn list(s: &Server, topic: TopicId) -> Result<Vec<TaskArtifact>> {
    if let Some((at, listed)) = memo().lock().get(&topic)
        && at.elapsed() < MEMO
    {
        return Ok(listed.clone());
    }
    let tasks: Vec<TaskId> = s
        .engine
        .task_runs(topic)?
        .into_iter()
        .map(|(t, _)| t)
        .collect();
    let mut listed = vec![];
    let mut failure = None;
    for task in tasks {
        match task_artifacts(s, topic, task).await {
            Ok(found) => listed.extend(found),
            Err(error) => {
                log::warn!("Could not list artifacts for task {task}: {error:#}");
                failure.get_or_insert(error);
            }
        }
    }
    // One unreachable task leaves the rest browsable; nothing at all is an error.
    if listed.is_empty()
        && let Some(error) = failure
    {
        return Err(error);
    }
    memo()
        .lock()
        .insert(topic, (Instant::now(), listed.clone()));
    Ok(listed)
}

async fn task_artifacts(s: &Server, topic: TopicId, task: TaskId) -> Result<Vec<TaskArtifact>> {
    let Some((client, token, remote)) = posthog(s, topic, task)? else {
        return Ok(vec![]);
    };
    let runs = client.run_manifests(&token, remote).await?;
    let ids: Vec<Uuid> = runs.iter().map(|r| r.id).collect();
    let (client, token) = (&client, token.as_str());
    let living: Vec<Vec<LivingArtifact>> = stream::iter(ids)
        .map(move |run| client.living_artifacts(token, remote, run))
        .buffered(6)
        .try_collect()
        .await?;
    let living: Vec<LivingArtifact> = living.into_iter().flatten().collect();
    // A living artifact made from a run file replaces that file in the listing.
    let sources: Vec<&str> = living
        .iter()
        .filter_map(LivingArtifact::source_artifact_id)
        .collect();
    let mut out: Vec<TaskArtifact> = living
        .iter()
        .filter(|a| a.status != "failed")
        .map(|a| from_living(task, a))
        .collect();
    for run in &runs {
        out.extend(
            run.artifacts
                .iter()
                .filter(|a| !INPUTS.contains(&a.kind.as_str()) && !sources.contains(&a.id.as_str()))
                .map(|a| from_run(task, run.id, a)),
        );
    }
    Ok(out)
}

fn from_living(task: TaskId, a: &LivingArtifact) -> TaskArtifact {
    let current = a.current();
    let field = |k: &str| current.and_then(|v| v.get(k));
    TaskArtifact {
        task,
        run: a.run_id.clone(),
        id: a.id.clone(),
        name: a.name.clone(),
        kind: a.artifact_type.clone(),
        version: a.current_version.max(1),
        size: field("size").and_then(|v| v.as_u64()),
        content_type: field("content_type")
            .and_then(|v| v.as_str())
            .map(str::to_owned),
        url: a.external_url().map(str::to_owned),
        updated_at: a.updated_at.clone(),
    }
}

fn from_run(task: TaskId, run: Uuid, a: &RunArtifact) -> TaskArtifact {
    TaskArtifact {
        task,
        run: run.to_string(),
        id: a.id.clone(),
        name: a.name.clone(),
        kind: a.kind.clone(),
        version: 0,
        size: a.size,
        content_type: a.content_type.clone(),
        url: None,
        updated_at: a.uploaded_at.clone(),
    }
}

/// The bytes of one artifact version, read from PostHog on request.
pub(crate) async fn read(
    s: &Server,
    topic: TopicId,
    task: TaskId,
    run: Uuid,
    artifact: &str,
    version: u64,
) -> Result<Vec<u8>> {
    let (client, token, remote) =
        posthog(s, topic, task)?.context("This task has no PostHog run")?;
    if version > 0 {
        client
            .living_artifact_version(&token, remote, run, artifact, version)
            .await
    } else {
        client.run_artifact(&token, remote, run, artifact).await
    }
}
