// use crate::{
//     error::UnhandledError,
//     stages::resolution::{exception::ExceptionResolver, ResolutionStage},
//     types::{
//         batch::Batch,
//         operator::{Operator, TeamId},
//         Exception, ExceptionList,
//     },
// };

// pub struct ExceptionListResolver {
//     exception_resolver: ExceptionResolver,
// }

// impl ExceptionListResolver {
//     pub fn new(exception_resolver: ExceptionResolver) -> Self {
//         Self { exception_resolver }
//     }
// }

// impl Operator<ResolutionStage> for ExceptionListResolver {
//     type Input = (TeamId, ExceptionList);
//     type Output = ExceptionList;

//     async fn execute(
//         &self,
//         input: (TeamId, ExceptionList),
//         ctx: &ResolutionStage,
//     ) -> Result<impl Batch<Exception>, UnhandledError> {
//         // let exception_batch = Batch::new(input.1.into_iter().map(|exc| (input.0, exc)).collect());
//         let team_id = input.0.clone();
//         let resolver = self.exception_resolver.clone();
//         input
//             .1
//             .spawn(|item| async move {
//                 resolver.execute((team_id.clone(), item), ctx).await
//             })
//             .await
//     }
// }
