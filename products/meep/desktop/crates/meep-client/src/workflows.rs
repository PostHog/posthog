//! Replica-backed configuration of bound PostHog workflows.
use crate::{Client, Event, Status, TransportError, replica};
use anyhow::{Context, Result};
use meep_topic::{CommandId, TopicId};
use meep_wire::{WorkflowDetails, WorkflowSwitch};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub(super) const PENDING: &str = "client/workflow-outbox";
const CACHE: &str = "client/workflows";

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct PendingSwitch {
    pub(super) id: CommandId,
    pub(super) topic: TopicId,
    routine: String,
    request: WorkflowSwitch,
}

impl Client {
    /// Fetch available workflow templates.
    pub async fn routine_templates(&self) -> Result<Vec<meep_wire::RoutineTemplate>> {
        self.observe(self.0.transport.routine_templates().await)
    }
    /// Create a workflow from a template and wake replication.
    pub async fn create_template_routine(
        &self,
        topic: TopicId,
        req: &meep_wire::CreateTemplateRoutine,
    ) -> Result<meep_topic::RoutineInfo> {
        let routine = self.observe(self.0.transport.create_template_routine(topic, req).await)?;
        self.0.wake.notify_one();
        Ok(routine)
    }

    /// Delete the linked workflow, discard its cached settings and refresh the topic.
    pub async fn delete_workflow(&self, topic: TopicId, routine: &str, flow: Uuid) -> Result<()> {
        {
            let guard = self.0.workflows.clone().lock_owned().await;
            self.observe(self.0.transport.delete_workflow(topic, routine, flow).await)?;
            let key = format!("{topic}/{routine}");
            self.local(guard, move |c| {
                meep_store::transaction(&mut c.0.db.lock(), |tx| {
                    meep_store::remove(tx, CACHE, &key)?;
                    meep_store::remove(tx, PENDING, &key)?;
                    Ok(())
                })
            })
            .await?;
        }
        self.sync_now();
        self.sync_once().await
    }

    /// Read the last observed workflow, including the person's pending switch setting.
    pub fn cached_workflow(
        &self,
        topic: TopicId,
        routine: &str,
    ) -> Result<Option<WorkflowDetails>> {
        let mut reader = self.0.reader.lock();
        let db = reader.transaction()?;
        let key = format!("{topic}/{routine}");
        let mut details = meep_store::get::<WorkflowDetails>(&db, CACHE, &key)?;
        if let Some(details) = &mut details
            && let Some(pending) = meep_store::get::<PendingSwitch>(&db, PENDING, &key)?
        {
            details.enabled = pending.request.enabled;
        }
        Ok(details)
    }

    /// Refresh definition and recent runs in the local cache.
    pub async fn refresh_workflow(&self, topic: TopicId, routine: &str) -> Result<()> {
        let guard = self.0.workflows.clone().lock_owned().await;
        let details = self.observe(self.0.transport.workflow(topic, routine, None).await)?;
        let key = format!("{topic}/{routine}");
        self.local(guard, move |c| {
            meep_store::put(&c.0.db.lock(), CACHE, &key, &details)?;
            c.emit(Event::TopicChanged(topic));
            Ok(())
        })
        .await
    }

    /// Queue a workflow switch locally. Repeated changes keep the latest desired state.
    pub fn set_workflow_enabled(&self, topic: TopicId, routine: &str, enabled: bool) -> Result<()> {
        let db = self.0.db.lock();
        let state = replica::visible(&db, topic)?.context("Unknown topic")?;
        let binding = state
            .topic
            .routines
            .iter()
            .map(|r| &r.binding)
            .find(|b| b.id == routine && b.backend == "posthog")
            .context("Expected a bound PostHog workflow")?;
        let id = Uuid::new_v4();
        let request = PendingSwitch {
            id: CommandId(id),
            topic,
            routine: routine.into(),
            request: WorkflowSwitch {
                request_id: Some(id.into()),
                flow_id: binding.external_id.clone(),
                enabled,
            },
        };
        meep_store::put(&db, PENDING, &format!("{topic}/{routine}"), &request)?;
        let mut status = self.0.state.lock();
        if let Status::Offline { since, .. } = status.status {
            self.set_status(
                &mut status,
                Status::Offline {
                    since,
                    pending: replica::count(&db)?,
                },
            );
        }
        self.emit(Event::TopicChanged(topic));
        self.sync_now();
        Ok(())
    }

    pub(super) async fn sync_workflows(&self) -> Result<()> {
        let guard = std::sync::Arc::new(self.0.workflows.clone().lock_owned().await);
        let pending = self
            .local((), |c| {
                meep_store::list::<PendingSwitch>(&c.0.reader.lock(), PENDING)
            })
            .await?;
        for (key, mut change) in pending {
            change.request.request_id.get_or_insert(change.id.0.into());
            if replica::has_commands(&self.0.reader.lock(), change.topic)? {
                continue;
            }
            let result = self
                .0
                .transport
                .workflow(change.topic, &change.routine, Some(&change.request))
                .await;
            let (details, error) = match result {
                Ok(details) => (Some(details), None),
                Err(TransportError::Api { message, .. }) => (None, Some(message)),
                Err(err) => return Err(err.into()),
            };
            self.local(guard.clone(), move |c| {
                let removed = meep_store::transaction(&mut c.0.db.lock(), |tx| {
                    if let Some(details) = &details {
                        meep_store::put(tx, CACHE, &key, details)?;
                    }
                    if meep_store::get::<PendingSwitch>(tx, PENDING, &key)?
                        .is_some_and(|p| p.id == change.id)
                    {
                        if let Some(reason) = &error {
                            meep_store::put(tx, "client/rejected", &change.id.to_string(), reason)?;
                        }
                        meep_store::remove(tx, PENDING, &key)?;
                        return Ok(true);
                    }
                    Ok(false)
                })?;
                if let Some(reason) = error
                    && removed
                {
                    c.emit(Event::Rejected {
                        command: change.id,
                        reason,
                    });
                }
                c.emit(Event::TopicChanged(change.topic));
                Ok(())
            })
            .await?;
        }
        Ok(())
    }
}
