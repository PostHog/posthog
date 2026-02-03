// use uuid::Uuid;

// use crate::{
//     error::{ResolveError, UnhandledError},
//     frames::{Frame, RawFrame},
//     langs::java::RawJavaFrame,
//     metric_consts::JAVA_EXCEPTION_REMAP_FAILED,
//     stages::resolution::{frame::FrameResolver, ResolutionStage},
//     symbol_store::{chunk_id::OrChunkId, dart_minified_names::lookup_minified_type, Catalog},
//     types::{
//         batch::Batch,
//         operator::{Operator, TeamId},
//         Exception, Stacktrace,
//     },
// };

// pub struct ExceptionResolver;

// impl ExceptionResolver {
//     async fn resolve_stack(
//         &self,
//         team_id: TeamId,
//         stack: Stacktrace,
//         ctx: &ResolutionStage,
//     ) -> Result<Stacktrace, UnhandledError> {
//         match stack {
//             Stacktrace::Raw { frames } => {
//                 let frame_resolver = ctx.symbol_resolver.clone();
//                 let resolved_frame_batch = frames
//                     .into_iter()
//                     .map(|frame| (team_id, frame))
//                     .spawn(frame_resolver, ctx)
//                     .await?;

//                 let frames: Vec<Frame> = resolved_frame_batch
//                     .into_inner()
//                     .into_iter()
//                     .flatten()
//                     .collect();
//                 Ok(Stacktrace::Resolved { frames })
//             }
//             Stacktrace::Resolved { frames: _ } => Ok(stack),
//         }
//     }
// }

// impl Operator<ResolutionStage> for ExceptionResolver {
//     type Input = (TeamId, Exception);
//     type Output = Exception;

//     async fn execute(
//         &self,
//         mut input: (TeamId, Exception),
//         ctx: &ResolutionStage,
//     ) -> Result<Exception, UnhandledError> {
//         input.1.exception_id = Some(Uuid::now_v7().to_string());
//         // resolve_exception(input.0, &self.catalog, &mut input.1).await?;
//         if let Some(stack) = input.1.stack {
//             input.1.stack = Some(self.resolve_stack(input.0, stack, ctx).await?);
//         }
//         Ok(input.1)
//     }
// }

// #[derive(Debug, thiserror::Error)]
// pub enum ResolveExceptionError {
//     #[error("Invalid format: {0}")]
//     InvalidFormat(String),
//     #[error("Class not found: {0}")]
//     ClassNotFound(String),
//     #[error("Resolve error: {0}")]
//     ResolveError(#[from] ResolveError),
// }

// async fn resolve_exception(
//     team_id: i32,
//     catalog: &Catalog,
//     exception: &mut Exception,
// ) -> Result<(), UnhandledError> {
//     let raw_frames = exception
//         .stack
//         .as_ref()
//         .map(|s| s.get_raw_frames())
//         .unwrap_or_default();

//     let first_frame = raw_frames.first();

//     // Only needed in java where exception type and module are minified
//     if let Some(RawFrame::Java(frame)) = first_frame {
//         if let Some(module) = &exception.module {
//             match remap_exception_type_and_module(
//                 module,
//                 &exception.exception_type,
//                 team_id,
//                 frame,
//                 catalog,
//             )
//             .await
//             {
//                 Ok((remapped_module, remapped_type)) => {
//                     exception.module = Some(remapped_module);
//                     exception.exception_type = remapped_type;
//                 }
//                 Err(err) => {
//                     metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => err.to_string())
//                         .increment(1);
//                 }
//             }
//         }
//     }

//     // Handle dart2js minified exception types (e.g., "minified:BA" -> "UnsupportedError")
//     // Flutter Web uses posthog-js, so frames come as JavaScriptWeb with chunk_id
//     if exception.exception_type.starts_with("minified:") {
//         if let Some(remapped_type) = remap_dart_minified_exception_type(
//             &exception.exception_type,
//             raw_frames,
//             team_id,
//             catalog,
//         )
//         .await
//         {
//             exception.exception_type = remapped_type;
//         }
//     }

//     Ok(())
// }

// async fn remap_exception_type_and_module(
//     module: &str,
//     exception_type: &str,
//     team_id: i32,
//     frame: &RawJavaFrame,
//     catalog: &Catalog,
// ) -> Result<(String, String), ResolveExceptionError> {
//     let class = format!("{module}.{exception_type}");
//     let remapped = frame.remap_class(team_id, &class, catalog).await?;
//     match remapped {
//         Some(s) => split_last_dot(&s),
//         None => Err(ResolveExceptionError::ClassNotFound(class)),
//     }
// }

// fn split_last_dot(s: &str) -> Result<(String, String), ResolveExceptionError> {
//     let mut parts = s.rsplitn(2, '.');
//     let last = parts.next().unwrap();
//     let before = parts.next().ok_or(ResolveExceptionError::InvalidFormat(
//         "Could not split remapped module and type".to_string(),
//     ))?;
//     Ok((before.to_string(), last.to_string()))
// }

// /// Remaps dart2js minified exception types (e.g., "minified:BA" -> "UnsupportedError")
// /// by looking up the minified name in the sourcemap's x_org_dartlang_dart2js extension.
// async fn remap_dart_minified_exception_type(
//     exception_type: &str,
//     frames: &[RawFrame],
//     team_id: i32,
//     catalog: &Catalog,
// ) -> Option<String> {
//     let chunk_id = frames.iter().find_map(|frame| match frame {
//         RawFrame::JavaScriptWeb(js_frame) => js_frame.chunk_id.clone(),
//         RawFrame::JavaScriptNode(node_frame) => node_frame.chunk_id.clone(),
//         RawFrame::LegacyJS(js_frame) => js_frame.chunk_id.clone(),
//         _ => None,
//     })?;

//     let sourcemap = catalog
//         .smp
//         .lookup(team_id, OrChunkId::ChunkId(chunk_id))
//         .await
//         .ok()?;

//     let minified_names = sourcemap.get_dart_minified_names()?;

//     lookup_minified_type(minified_names, exception_type)
// }
