//! Durable workspace view records and their PostHog Tasks authoring worker.
use crate::Server;
use anyhow::{Context, Result, ensure};

use meep_engine::{RunState, Store, StoredView as Record, ViewRun as SessionRun};
use meep_wire::views::{Stage, View, ViewEnvelope};
use parking_lot::Mutex;

use crate::auth::fingerprint;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
    time::Duration,
};
use tokio::sync::{Notify, broadcast};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

/// Files attached to view requests share the engine's revisioned file store,
/// scoped by the view's own ID under their own prefix.
pub(crate) fn upload_scope(view: Uuid) -> meep_topic::TopicId {
    meep_topic::TopicId(view)
}
pub(crate) fn upload_name(name: &str) -> String {
    format!("view-uploads/{name}")
}

fn turn_mut(record: &mut Record, id: Uuid) -> Result<&mut meep_wire::views::Turn> {
    record
        .view
        .turns
        .iter_mut()
        .find(|t| t.id == id)
        .context("Missing authoring turn")
}
pub(super) struct Views {
    store: Arc<dyn Store>,
    records: Mutex<BTreeMap<Uuid, Record>>,
    pub feed: broadcast::Sender<()>,
    wake: Notify,
}
impl Views {
    pub fn open(store: Arc<dyn Store>) -> Result<Self> {
        let records = store
            .load_views()?
            .into_iter()
            .map(|r| (r.view.id, r))
            .collect();
        let s = Self {
            store,
            records: Mutex::new(records),
            feed: broadcast::channel(64).0,
            wake: Notify::new(),
        };
        for v in s.list() {
            if let Some(turn) = v.pending().filter(|t| t.stage == Stage::Starting) {
                s.update(v.id, |r| {
                    turn_mut(r, turn.id)?.stage = Stage::Finished(
                        "Start interrupted. Check PostHog Tasks before asking again.".into(),
                    );
                    r.capability = None;
                    Ok(())
                })?;
            }
        }
        Ok(s)
    }
    pub fn list(&self) -> Vec<View> {
        self.records
            .lock()
            .values()
            .filter(|r| !r.view.deleted)
            .map(|r| r.view.clone())
            .collect()
    }
    pub fn read(&self, id: Uuid) -> Result<View> {
        Ok(self
            .records
            .lock()
            .get(&id)
            .filter(|r| !r.view.deleted)
            .context("Unknown view")?
            .view
            .clone())
    }
    fn save(&self, records: &mut BTreeMap<Uuid, Record>, id: Uuid, mut next: Record) -> Result<()> {
        let previous = records.get(&id).map_or(0, |r| r.version);
        next.version = previous + 1;
        self.store.save_view(previous, &next)?;
        records.insert(id, next);
        let _ = self.feed.send(());
        self.wake.notify_one();
        Ok(())
    }
    pub fn update<T>(&self, id: Uuid, f: impl FnOnce(&mut Record) -> Result<T>) -> Result<T> {
        let mut records = self.records.lock();
        let mut next = records
            .get(&id)
            .filter(|r| !r.view.deleted)
            .context("Unknown view")?
            .clone();
        let result = f(&mut next)?;
        self.save(&mut records, id, next)?;
        Ok(result)
    }
    pub fn command(&self, e: ViewEnvelope) -> Result<View> {
        let mut records = self.records.lock();
        if records
            .iter()
            .any(|(id, r)| *id != e.view && r.receipts.contains_key(&e.id))
        {
            return Err(Rejected(anyhow::anyhow!("Command ID reused on another view")).into());
        }
        let prior = records.get(&e.view);
        if prior.is_none() && !matches!(e.command, meep_wire::views::ViewCommand::Create { .. }) {
            return Err(MissingView.into());
        }
        if let Some((r, receipt)) = prior.and_then(|r| r.receipts.get(&e.id).map(|v| (r, v))) {
            if *receipt != e {
                return Err(Rejected(anyhow::anyhow!("Command ID reused")).into());
            }
            return Ok(r.view.clone());
        }
        let mut v = prior.map(|r| r.view.clone());
        e.apply(&mut v).map_err(Rejected)?;
        let view = v.context("The view command completed without a view")?;
        let mut next = prior.cloned().unwrap_or_else(|| Record {
            version: 0,
            view: view.clone(),
            receipts: Default::default(),
            handles: Default::default(),
            capability: None,
        });
        next.receipts.insert(e.id, e);
        next.view = view.clone();
        self.save(&mut records, view.id, next)?;
        Ok(view)
    }
    pub fn authorized(&self, id: Uuid, token: &str) -> bool {
        self.records
            .lock()
            .get(&id)
            .is_some_and(|r| authorized(r, token))
    }
}
#[derive(Debug)]
pub(super) struct MissingView;
impl std::fmt::Display for MissingView {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Unknown view")
    }
}
impl std::error::Error for MissingView {}

#[derive(Debug)]
pub(super) struct Rejected(anyhow::Error);
impl std::fmt::Display for Rejected {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}
impl std::error::Error for Rejected {}
pub(super) fn authorized(r: &Record, token: &str) -> bool {
    !r.view.deleted
        && r.capability
            .as_ref()
            .is_some_and(|c| crate::auth::matches_secret(c, &fingerprint(token)))
}
impl Server {
    async fn step_view(&self, id: Uuid) -> Result<()> {
        let (turn, handle) = {
            let records = self.views.records.lock();
            let r = records.get(&id).context("Unknown view")?;
            let t = r.view.pending().context("Missing authoring turn")?;
            (t.clone(), r.handles.get(&t.session).cloned())
        };
        let project = self.accounts.get("posthog").and_then(|a| a.project.clone());
        let mut messages = turn.messages.clone();
        let next = match turn.stage {
            Stage::Queued => {
                let token = Uuid::new_v4().to_string();
                self.views.update(id, |r| {
                    let t = turn_mut(r, turn.id)?;
                    ensure!(t.id == turn.id && t.stage == Stage::Queued, "Turn changed");
                    t.stage = Stage::Starting;
                    r.capability = Some(fingerprint(&token));
                    Ok(())
                })?;
                let started = async {
                    let base = self.accounts.public_base.read().clone().context(
                        "Configure MEEP_PUBLIC_BASE_URL with a reachable HTTPS address, then ask again.",
                    )?;
                    let project = project.context("Connect PostHog to build this view.")?;
                    ensure!(
                        handle.as_ref().is_none_or(|h| h.project == project.project && h.origin == project.origin),
                        "This conversation belongs to a different PostHog project. Start a new session."
                    );
                    let endpoint = format!("{base}/v1/views/{id}/mcp");
                    // The files the person attached, staged on this server first.
                    let mut files = Vec::with_capacity(turn.options.files.len());
                    for name in &turn.options.files {
                        let blob = self
                            .engine
                            .blobs()
                            .get(upload_scope(id), &upload_name(name), None)?
                            .with_context(|| format!("{name} is no longer here. Attach it again."))?;
                        files.push((name.clone(), blob.bytes));
                    }
                    let handle = project.agent.author_view(
                        id,
                        handle.as_ref().map(|h| &h.handle), &turn.prompt, &endpoint, &token,
                        turn.options.model.as_deref(), turn.options.effort.as_deref(), files,
                    ).await?;
                    Ok::<_,anyhow::Error>(SessionRun {origin: project.origin.clone(), project: project.project, handle})
                }
                .await;
                match started {
                    Ok(handle) => {
                        return self.views.update(id, |r| {
                            r.handles.insert(turn.session, handle);
                            turn_mut(r, turn.id)?.stage = Stage::Working("Starting".into());
                            Ok(())
                        });
                    }
                    Err(e) => Stage::Finished(format!("Could not start the agent: {e}")),
                }
            }
            Stage::Working(ref previous) => {
                let handle = handle.context("Missing Tasks run")?;
                let Some(project) =
                    project.filter(|p| p.origin == handle.origin && p.project == handle.project)
                else {
                    return self.views.update(id, |r| {
                        turn_mut(r, turn.id)?.stage = Stage::Finished(
                            "The PostHog project changed. Start a new session.".into(),
                        );
                        r.capability = None;
                        Ok(())
                    });
                };
                // The person stopped it: cancel the run in PostHog, keep what it said.
                if turn.stop {
                    project.agent.cancel_view(&handle.handle).await?;
                    return self.views.update(id, |r| {
                        turn_mut(r, turn.id)?.stage = Stage::Finished("Stopped.".into());
                        r.capability = None;
                        Ok(())
                    });
                }
                let (state, history) = project.agent.observe_run(&handle.handle).await?;
                let observed = history
                    .turns()
                    .iter()
                    .filter(|t| t.role == "assistant")
                    .map(|t| t.message.clone())
                    .collect::<Vec<_>>();
                if !observed.is_empty() {
                    messages = observed;
                }
                match state {
                    RunState::Running { progress }
                        if *previous == progress && messages == turn.messages =>
                    {
                        return Ok(());
                    }
                    RunState::Running { progress } => Stage::Working(progress),
                    RunState::Done { result }
                    | RunState::Findings { result, .. }
                    | RunState::Submitted { result, .. } => Stage::Finished(result),
                    RunState::Failed { error } => Stage::Finished(error),
                }
            }
            _ => return Ok(()),
        };
        self.views.update(id, |r| {
            let t = turn_mut(r, turn.id)?;
            ensure!(t.id == turn.id, "Turn changed");
            let finished = next.finished();
            t.messages = messages;
            t.stage = next;
            if finished {
                r.capability = None;
            }
            Ok(())
        })
    }
}
pub(super) async fn run(server: Server, stop: CancellationToken) {
    let mut busy = BTreeSet::new();
    let mut jobs = tokio::task::JoinSet::new();
    let mut tick = tokio::time::interval(Duration::from_secs(3));
    loop {
        let queued_only = tokio::select! {
            _=stop.cancelled()=>break,
            _=tick.tick()=>false,
            _=server.views.wake.notified()=>true,
            Some(Ok(id))=jobs.join_next(),if !jobs.is_empty()=>{busy.remove(&id); continue;}
        };
        let ids = server
            .views
            .records
            .lock()
            .values()
            .filter(|r| {
                !r.view.deleted
                    && r.view.pending().is_some_and(|t| {
                        matches!(t.stage, Stage::Queued)
                            || (!queued_only && matches!(t.stage, Stage::Working(_)))
                    })
            })
            .map(|r| r.view.id)
            .collect::<Vec<_>>();
        for id in ids {
            if busy.insert(id) {
                let server = server.clone();
                jobs.spawn(async move {
                    if let Err(e) = server.step_view(id).await {
                        log::warn!("Could not advance view {id}: {e}");
                    }
                    id
                });
            }
        }
    }
    jobs.shutdown().await;
}
