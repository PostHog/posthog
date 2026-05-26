use std::sync::Arc;

use async_trait::async_trait;
use cymbal_symbol_store::UnhandledError;
use cymbal_symbolication::{apple::AppleDebugImage, Frame, RawFrame};

use crate::exception::{
    ResolutionException, ResolutionExceptionList, ResolutionStacktrace, StacktraceType,
};
use crate::ResolutionDeps;

#[async_trait]
pub trait FrameRepository: Send + Sync + 'static {
    async fn save_resolved_frame(
        &self,
        team_id: i32,
        raw_frame: &RawFrame,
        frame: &Frame,
    ) -> Result<(), UnhandledError>;
}

#[derive(Debug, Default)]
pub struct NoopFrameRepository;

#[async_trait]
impl FrameRepository for NoopFrameRepository {
    async fn save_resolved_frame(
        &self,
        _team_id: i32,
        _raw_frame: &RawFrame,
        _frame: &Frame,
    ) -> Result<(), UnhandledError> {
        Ok(())
    }
}

#[derive(Clone, Default)]
pub struct FrameResolver;

impl FrameResolver {
    pub async fn resolve_exception_list_frames(
        team_id: i32,
        list: ResolutionExceptionList,
        debug_images: Arc<Vec<AppleDebugImage>>,
        deps: ResolutionDeps,
    ) -> Result<ResolutionExceptionList, UnhandledError> {
        let mut resolved = Vec::with_capacity(list.0.len());
        for exception in list.0 {
            resolved.push(
                Self::resolve_exception_frames(team_id, exception, &debug_images, deps.clone())
                    .await?,
            );
        }
        Ok(resolved.into())
    }

    pub async fn resolve_exception_frames(
        team_id: i32,
        mut exception: ResolutionException,
        debug_images: &[AppleDebugImage],
        deps: ResolutionDeps,
    ) -> Result<ResolutionException, UnhandledError> {
        exception.stack = match exception.stack {
            Some(ResolutionStacktrace::Raw { frames, other, .. }) => {
                let debug_images = Arc::new(debug_images.to_vec());
                let mut frame_batches: Vec<Vec<Frame>> = Vec::with_capacity(frames.len());
                for frame in frames {
                    frame_batches.push(
                        Self::resolve_frame(team_id, &frame, &debug_images, deps.clone()).await?,
                    );
                }
                let frames = frame_batches.into_iter().flatten().collect();
                Some(ResolutionStacktrace::Resolved {
                    stack_type: StacktraceType::Resolved,
                    frames,
                    other,
                })
            }
            stack => stack,
        };
        Ok(exception)
    }

    pub async fn resolve_frame(
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
        deps: ResolutionDeps,
    ) -> Result<Vec<Frame>, UnhandledError> {
        let frames = {
            let _permit = deps.acquire_symbol_resolution_permit().await?;
            deps.symbol_resolver
                .resolve_raw_frame(team_id, frame, debug_images)
                .await?
        };
        for resolved_frame in &frames {
            deps.frame_repository
                .save_resolved_frame(team_id, frame, resolved_frame)
                .await?;
        }
        Ok(frames)
    }
}
