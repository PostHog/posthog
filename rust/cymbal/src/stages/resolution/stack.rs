// use crate::{
//     error::UnhandledError,
//     stages::resolution::ResolutionStage,
//     types::{batch::Batch, event::ExceptionEvent, operator::Operator},
// };

// pub struct StackResolver {}

// impl Operator<ResolutionStage> for StackResolver {
//     type Input = ExceptionEvent;
//     type Output = ExceptionEvent;

//     async fn execute(
//         &self,
//         mut input: ExceptionEvent,
//         ctx: &ResolutionStage,
//     ) -> Result<ExceptionEvent, UnhandledError> {
//         let team_id = input.team_id.clone();

//         input.exception_list = input
//             .exception_list
//             .spawn(
//                 |exc, ctx| async move {
//                     ctx.symbol_resolver
//                         .resolve_java_exception(team_id, exc)
//                         .await
//                 },
//                 ctx,
//             )
//             .await?
//             .into();
//         return Ok(input);
//     }
// }
