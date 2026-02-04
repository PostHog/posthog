use crate::{
    error::UnhandledError,
    frames::{Frame, RawFrame},
    stages::resolution::ResolutionStage,
    types::{
        batch::Batch, operator::Operator, pipeline::ExceptionEventPipelineItem, Exception,
        ExceptionList, Stacktrace,
    },
};

#[derive(Clone, Default)]
pub struct FrameResolver;

impl FrameResolver {
    pub async fn resolve_exception_list_frames(
        team_id: i32,
        list: ExceptionList,
        ctx: ResolutionStage,
    ) -> Result<ExceptionList, UnhandledError> {
        let res = Batch::from(list.0)
            .apply_func(
                move |exc, ctx| FrameResolver::resolve_exception_frames(team_id, exc, ctx),
                ctx,
            )
            .await?;
        Ok(Vec::from(res).into())
    }

    pub async fn resolve_exception_frames(
        team_id: i32,
        mut exc: Exception,
        ctx: ResolutionStage,
    ) -> Result<Exception, UnhandledError> {
        exc.stack = match exc.stack {
            Some(Stacktrace::Raw { frames }) => {
                let frame_batches: Batch<Vec<Frame>> = Batch::from(frames)
                    .apply_func(
                        move |frame, ctx| async move {
                            FrameResolver::resolve_frame(team_id, &frame, ctx).await
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
        ctx: ResolutionStage,
    ) -> Result<Vec<Frame>, UnhandledError> {
        ctx.symbol_resolver.resolve_raw_frame(team_id, frame).await
    }
}

impl Operator for FrameResolver {
    type Context = ResolutionStage;
    type Item = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    async fn execute(
        &self,
        item: ExceptionEventPipelineItem,
        ctx: ResolutionStage,
    ) -> Result<ExceptionEventPipelineItem, UnhandledError> {
        let mut evt = match item {
            Err(_) => return Ok(item),
            Ok(value) => value,
        };
        evt.exception_list =
            FrameResolver::resolve_exception_list_frames(evt.team_id, evt.exception_list, ctx)
                .await?;
        Ok(Ok(evt))
    }
}
