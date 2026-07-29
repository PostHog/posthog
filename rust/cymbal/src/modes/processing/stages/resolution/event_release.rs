use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    frames::releases::ReleaseRecord,
    metric_consts::EVENT_RELEASE_RESOLVER_OPERATOR,
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        exception_event::{ExceptionEvent, Parsed},
        operator::{OperatorResult, ValueOperator},
    },
};

/// Resolves the event-level release the SDK carries. posthog-cli bakes the release row's id into
/// each chunk, and the SDK emits it as `$release_id`. This fetches that release once per event and
/// stashes it on the event, so `$exception_releases` is built from it. With the experimental
/// mechanism the symbol sets are release-independent, so this is the only place the release comes
/// from; legacy events without `$release_id` fall back to the per-frame symbol-set join.
#[derive(Clone, Default)]
pub struct EventReleaseResolver;

impl ValueOperator for EventReleaseResolver {
    type Context = ResolutionStage;
    type Item = ExceptionEvent<Parsed>;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        EVENT_RELEASE_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionEvent<Parsed>,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        // No pool means the remote resolution server, which never resolves event releases.
        let Some(pool) = ctx.posthog_pool.as_ref() else {
            return Ok(Ok(evt));
        };

        let release_id = evt
            .properties()
            .get("$release_id")
            .and_then(Value::as_str)
            .and_then(|id| Uuid::parse_str(id).ok());

        if let Some(release_id) = release_id {
            let record = ReleaseRecord::for_id(pool, release_id, evt.team_id())
                .await
                .map_err(UnhandledError::from)?;
            evt.set_event_release(record);
        }

        Ok(Ok(evt))
    }
}
