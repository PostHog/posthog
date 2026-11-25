use super::*;
use serde_json::{Map, Value};
pub(super) fn fixture_binding(id: &str) -> RoutineBinding {
    RoutineBinding {
        id: id.into(),
        name: id.into(),
        external_id: Uuid::new_v4().to_string(),
        backend: "posthog".into(),
        trigger: "Manual".into(),
        watches: vec![],
    }
}

pub(super) struct FixtureFlows;
#[async_trait::async_trait]
impl RoutineBackend for FixtureFlows {
    fn name(&self) -> &str {
        "posthog"
    }
    fn bind(&self, b: &RoutineBinding) -> anyhow::Result<()> {
        Uuid::parse_str(&b.external_id)?;
        Ok(())
    }
    async fn start(
        &self,
        _: RoutineContext<'_>,
        _: Map<String, Value>,
        key: Uuid,
    ) -> anyhow::Result<RoutineRun> {
        Ok(RoutineRun {
            invocation_id: key,
            status: "queued".into(),
        })
    }
    async fn status(&self, _: RoutineContext<'_>, key: Uuid) -> anyhow::Result<RoutineRun> {
        Ok(RoutineRun {
            invocation_id: key,
            status: "completed".into(),
        })
    }
    async fn health(&self, _: RoutineContext<'_>) -> anyhow::Result<RoutineHealth> {
        Ok(RoutineHealth::Ok)
    }
}
