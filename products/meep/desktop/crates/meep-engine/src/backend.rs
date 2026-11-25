use super::*;
use anyhow::Result;
use async_trait::async_trait;
use serde_json::{Map, Value};

/// The topic and binding of a backend operation.
pub struct RoutineContext<'a> {
    /// Topic that owns the binding.
    pub topic: TopicId,
    /// Public routine configuration.
    pub binding: &'a RoutineBinding,
}

/// A backend's receipt or later observation of a workflow invocation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RoutineRun {
    /// Backend invocation identity, distinct from the idempotency key.
    pub invocation_id: Uuid,
    /// Backend status, retained verbatim.
    pub status: String,
}

/// The provider may have started a workflow but did not return its invocation ID.
#[derive(Debug, thiserror::Error)]
#[error(
    "The workflow may have started, but its outcome is unknown. Check PostHog before retrying."
)]
pub struct DispatchUncertain;

#[cfg(feature = "posthog")]
fn posthog_dispatch_uncertain(error: &anyhow::Error) -> bool {
    error.is::<meep_posthog::workflows::DispatchUncertain>()
        || error
            .downcast_ref::<meep_posthog::api::ApiError>()
            .is_some_and(|e| (500..=599).contains(&e.status) || e.status == 408 || e.status == 409)
}

/// A granted provider is temporarily unavailable before dispatch has begun.
#[derive(Debug, thiserror::Error)]
#[error("The connected provider is temporarily unavailable; this observation will retry.")]
pub struct SourceTemporarilyUnavailable;

/// Host-configurable workflow executor. External backends own their triggers and steps.
#[async_trait]
pub trait RoutineBackend: Send + Sync {
    /// Stable backend name used in persisted bindings.
    fn name(&self) -> &str;
    /// Validate a binding before installing it.
    fn bind(&self, binding: &RoutineBinding) -> Result<()>;
    /// Check whether this host can dispatch an observed source and receive callbacks.
    fn source_ready(&self, _topic: TopicId) -> Result<()> {
        Ok(())
    }
    /// Enable a previously bound draft after the topic authorizes activation.
    async fn activate(&self, _context: RoutineContext<'_>) -> Result<()> {
        anyhow::bail!("This backend does not support activation")
    }
    /// Dispatch with the same key on every retry.
    async fn start(
        &self,
        context: RoutineContext<'_>,
        variables: Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun>;
    /// Read the backend's current invocation state.
    async fn status(&self, context: RoutineContext<'_>, invocation: Uuid) -> Result<RoutineRun>;
    /// Find a unique invocation for an observation without dispatching again.
    async fn find_observation(
        &self,
        _context: RoutineContext<'_>,
        _observation: Uuid,
    ) -> Result<Option<RoutineRun>> {
        Ok(None)
    }
    /// Check the bound flow without dispatching it.
    async fn health(&self, context: RoutineContext<'_>) -> Result<RoutineHealth>;
}

/// PostHog workflow adapter using a host-provided project endpoint and credential.
#[cfg(feature = "posthog")]
pub struct PostHogRoutines {
    origin: String,
    project: u64,
    token: String,
}
#[cfg(feature = "posthog")]
impl PostHogRoutines {
    /// Configure the project and credential. Neither is included in a topic snapshot.
    pub fn new(origin: impl Into<String>, project: u64, token: impl Into<String>) -> Result<Self> {
        let backend = Self {
            origin: origin.into(),
            project,
            token: token.into(),
        };
        meep_posthog::workflows::BoundWorkflow::new(&backend.origin, project, Uuid::nil())?;
        Ok(backend)
    }
    fn flow(&self, b: &RoutineBinding) -> Result<meep_posthog::workflows::BoundWorkflow> {
        meep_posthog::workflows::BoundWorkflow::new(
            &self.origin,
            self.project,
            b.external_id.parse()?,
        )
    }
}
#[cfg(feature = "posthog")]
#[async_trait]
impl RoutineBackend for PostHogRoutines {
    fn name(&self) -> &str {
        "posthog"
    }
    fn bind(&self, b: &RoutineBinding) -> Result<()> {
        self.flow(b)?;
        Ok(())
    }
    async fn start(
        &self,
        c: RoutineContext<'_>,
        variables: Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun> {
        let receipt = self
            .flow(c.binding)?
            .start_for(&self.token, &c.topic.to_string(), key, &variables)
            .await
            .map_err(|error| {
                if posthog_dispatch_uncertain(&error) {
                    anyhow::Error::new(DispatchUncertain)
                } else {
                    error
                }
            })?;
        Ok(RoutineRun {
            invocation_id: receipt.invocation_id,
            status: receipt.status,
        })
    }
    async fn status(&self, c: RoutineContext<'_>, invocation: Uuid) -> Result<RoutineRun> {
        let run = self
            .flow(c.binding)?
            .status(&self.token, invocation)
            .await?;
        Ok(RoutineRun {
            invocation_id: run.invocation_id,
            status: run.status,
        })
    }
    async fn find_observation(
        &self,
        c: RoutineContext<'_>,
        observation: Uuid,
    ) -> Result<Option<RoutineRun>> {
        Ok(self
            .flow(c.binding)?
            .find_observation(&self.token, observation)
            .await?
            .map(|run| RoutineRun {
                invocation_id: run.invocation_id,
                status: run.status,
            }))
    }
    async fn health(&self, c: RoutineContext<'_>) -> Result<RoutineHealth> {
        self.flow(c.binding)?.check_active(&self.token).await?;
        Ok(RoutineHealth::Ok)
    }
}

#[cfg(all(test, feature = "posthog"))]
mod dispatch_tests {
    use super::*;

    #[test]
    fn only_ambiguous_posthog_statuses_stop_automatic_dispatch() {
        let error = |status, detail: &str| {
            anyhow::Error::new(meep_posthog::api::ApiError {
                status,
                code: String::new(),
                detail: detail.into(),
            })
        };
        for status in [408, 500, 502, 503, 504, 599] {
            assert!(posthog_dispatch_uncertain(&error(status, "")));
        }
        assert!(posthog_dispatch_uncertain(&error(
            409,
            "A run with this Idempotency-Key is already in progress."
        )));
        assert!(posthog_dispatch_uncertain(&error(409, "")));
        assert!(posthog_dispatch_uncertain(&error(
            409,
            "Some other conflict"
        )));
        for status in [400, 401, 403, 404, 422] {
            assert!(!posthog_dispatch_uncertain(&error(status, "Rejected")));
        }
    }
}
