use tracing::warn;

use crate::{
    error::UnhandledError,
    frames::releases::{release_hash_id, ReleaseRecord},
    metric_consts::RELEASE_RESOLVER_OPERATOR,
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct ReleaseResolver;

impl ValueOperator for ReleaseResolver {
    type Item = ExceptionProperties;
    type Context = ResolutionStage;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        RELEASE_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut event: ExceptionProperties,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        // Primary path: resolve release from event's $release_version/$release_name
        event.exception_release = resolve_release_from_event_props(&event, &ctx).await;

        // Frame-level releases (fallback path via chunk_id → symbol_set → release FK)
        event.exception_releases = event.exception_list.get_release_map();

        Ok(Ok(event))
    }
}

async fn resolve_release_from_event_props(
    event: &ExceptionProperties,
    ctx: &ResolutionStage,
) -> Option<crate::frames::releases::ReleaseInfo> {
    let version = event.props.get("$release_version")?.as_str()?;
    let name = event.props.get("$release_name")?.as_str()?;
    let hash_id = release_hash_id(name, version);

    match ReleaseRecord::for_hash_id(&ctx.pool, &hash_id, event.team_id).await {
        Ok(Some(record)) => Some(record.to_release_info()),
        Ok(None) => None,
        Err(e) => {
            warn!(
                team_id = event.team_id,
                hash_id = hash_id,
                "Failed to look up release by hash_id: {}",
                e
            );
            None
        }
    }
}
