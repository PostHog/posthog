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
