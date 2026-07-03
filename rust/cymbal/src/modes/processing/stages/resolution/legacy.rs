use std::sync::Arc;

use crate::{
    error::UnhandledError,
    metric_consts::LEGACY_ORDER_RESOLVER_OPERATOR,
    stages::{
        pipeline::HandledError,
        resolution::{exception::ExceptionResolver, frame::FrameResolver, ResolutionStage},
    },
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

/// Resolves the retained legacy-order snapshot (set by wire-order
/// normalization) so grouping can compute the legacy fingerprint for issue
/// continuity. Runs after the canonical exception list is resolved, and always
/// through the local resolvers — so continuity holds on both the local and
/// remote resolution paths. The snapshot carries the same raw frames as the
/// canonical list, so the resolver cache serves them and this is nearly free.
#[derive(Clone, Default)]
pub struct LegacyOrderResolver;

impl ValueOperator for LegacyOrderResolver {
    type Item = ExceptionProperties;
    type Context = ResolutionStage;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        LEGACY_ORDER_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionProperties,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        let Some(legacy) = evt.legacy_order_exception_list.take() else {
            return Ok(Ok(evt));
        };

        let team_id = evt.team_id;
        // Match the canonical pipeline order: exception resolution (java/dart
        // reshaping) then frame resolution.
        let legacy =
            ExceptionResolver::resolve_exception_list(team_id, legacy, ctx.clone()).await?;
        let debug_images = Arc::new(evt.debug_images.clone());
        let legacy =
            FrameResolver::resolve_exception_list_frames(team_id, legacy, debug_images, ctx)
                .await?;

        evt.legacy_order_resolved = Some(legacy);
        Ok(Ok(evt))
    }
}
