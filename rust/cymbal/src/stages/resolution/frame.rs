use crate::{
    error::UnhandledError,
    frames::{Frame, RawFrame},
    stages::resolution::ResolutionStage,
    types::{
        batch::Batch, event::ExceptionEvent, operator::Operator, Exception, ExceptionList,
        Stacktrace,
    },
};

#[derive(Clone, Default)]
pub struct FrameResolver;

impl FrameResolver {
    pub async fn resolve_exception_list(
        team_id: i32,
        list: ExceptionList,
        ctx: &ResolutionStage,
    ) -> Result<ExceptionList, UnhandledError> {
        let res = list
            .process_concurrent(async |exc| {
                FrameResolver::resolve_exception(team_id, exc, ctx).await
            })
            .await?;
        Ok(res.into())
    }

    pub async fn resolve_exception(
        team_id: i32,
        mut exc: Exception,
        ctx: &ResolutionStage,
    ) -> Result<Exception, UnhandledError> {
        exc.stack = match exc.stack {
            Some(Stacktrace::Raw { frames }) => {
                let frames: Vec<Frame> = frames
                    .into_iter()
                    .spawn(
                        |frame, ctx| async move {
                            let frame = ctx
                                .symbol_resolver
                                .resolve_raw_frame(team_id, &frame)
                                .await?;
                            Ok(frame)
                        },
                        ctx,
                    )
                    .await?
                    .into_iter()
                    .flatten()
                    .collect();

                Some(Stacktrace::Resolved { frames })
            }
            stack => stack,
        };
        Ok(exc)
    }

    pub async fn resolve_raw_frame(
        &self,
        team_id: i32,
        frame: &RawFrame,
        ctx: &ResolutionStage,
    ) -> Result<Vec<Frame>, UnhandledError> {
        ctx.symbol_resolver.resolve_raw_frame(team_id, frame).await
    }
}

impl Operator<ResolutionStage> for FrameResolver {
    type Input = ExceptionEvent;
    type Output = ExceptionEvent;

    async fn execute(
        &self,
        mut input: ExceptionEvent,
        ctx: &ResolutionStage,
    ) -> Result<ExceptionEvent, UnhandledError> {
        input.exception_list =
            FrameResolver::resolve_exception_list(input.team_id, input.exception_list, ctx).await?;
        Ok(input)
    }
}

// #[derive(Clone)]
// pub struct StacktraceResolver;

// impl Operator<ResolutionStage> for StacktraceResolver {
//     type Input = (TeamId, Exception);
//     type Output = Exception;

//     async fn execute(
//         &self,
//         input: (TeamId, Exception),
//         ctx: &ResolutionStage,
//     ) -> Result<Exception, UnhandledError> {
//         let (team_id, mut exc) = input;
//         exc.stack = match exc.stack {
//             Some(Stacktrace::Raw { frames }) => {
//                 let frames: Vec<Frame> = frames
//                     .into_iter()
//                     .spawn(
//                         |frame, ctx| async move {
//                             let frame = ctx
//                                 .symbol_resolver
//                                 .resolve_raw_frame(team_id, &frame)
//                                 .await?;
//                             Ok(frame)
//                         },
//                         ctx,
//                     )
//                     .await?
//                     .into_iter()
//                     .flatten()
//                     .collect();

//                 Some(Stacktrace::Resolved { frames })
//             }
//             stack => stack,
//         };
//         Ok(exc)
//     }
// }
