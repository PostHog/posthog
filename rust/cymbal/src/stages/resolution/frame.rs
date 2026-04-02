use std::sync::Arc;

use crate::{
    error::UnhandledError,
    frames::{Frame, RawFrame},
    langs::apple::AppleDebugImage,
    metric_consts::FRAME_RESOLVER_OPERATOR,
    stages::{pipeline::HandledError, resolution::ResolutionStage},
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        Exception, ExceptionList, Stacktrace,
    },
};

#[derive(Clone, Default)]
pub struct FrameResolver;

impl FrameResolver {
    pub async fn resolve_exception_list_frames(
        team_id: i32,
        list: ExceptionList,
        debug_images: Arc<Vec<AppleDebugImage>>,
        ctx: ResolutionStage,
    ) -> Result<ExceptionList, UnhandledError> {
        let res = Batch::from(list.0)
            .apply_func(
                move |exc, ctx| {
                    let debug_images = debug_images.clone();
                    async move {
                        FrameResolver::resolve_exception_frames(team_id, exc, &debug_images, ctx)
                            .await
                    }
                },
                ctx,
            )
            .await?;
        Ok(Vec::from(res).into())
    }

    pub async fn resolve_exception_frames(
        team_id: i32,
        mut exc: Exception,
        debug_images: &[AppleDebugImage],
        ctx: ResolutionStage,
    ) -> Result<Exception, UnhandledError> {
        exc.stack = match exc.stack {
            Some(Stacktrace::Raw { frames }) => {
                let debug_images = Arc::new(debug_images.to_vec());
                let frame_batches: Batch<Vec<Frame>> = Batch::from(frames)
                    .apply_func(
                        move |frame, ctx| {
                            let debug_images = debug_images.clone();
                            async move {
                                FrameResolver::resolve_frame(team_id, &frame, &debug_images, ctx)
                                    .await
                            }
                        },
                        ctx,
                    )
                    .await?;

                let frames: Vec<Frame> = frame_batches.into_iter().flatten().collect();
                Some(Stacktrace::Resolved { frames })
            }
            stack => stack,
        };
        Ok(exc)
    }

    pub async fn resolve_frame(
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
        ctx: ResolutionStage,
    ) -> Result<Vec<Frame>, UnhandledError> {
        ctx.symbol_resolver
            .resolve_raw_frame(team_id, frame, debug_images)
            .await
    }
}

impl ValueOperator for FrameResolver {
    type Context = ResolutionStage;
    type Item = ExceptionProperties;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        FRAME_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionProperties,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        let debug_images = Arc::new(evt.debug_images.clone());
        evt.exception_list = FrameResolver::resolve_exception_list_frames(
            evt.team_id,
            evt.exception_list,
            debug_images,
            ctx,
        )
        .await?;
        Ok(Ok(evt))
    }
}
