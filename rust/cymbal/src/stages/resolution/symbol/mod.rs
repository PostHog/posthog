use axum::async_trait;

use crate::{
    error::UnhandledError,
    frames::{Frame, RawFrame},
    types::{operator::TeamId, Exception},
};

pub mod local;
pub mod remote;

#[async_trait]
pub trait SymbolResolver: Send + Sync + 'static {
    async fn resolve_raw_frame(
        &self,
        team_id: TeamId,
        frame: &RawFrame,
    ) -> Result<Vec<Frame>, UnhandledError>;

    async fn resolve_java_exception(
        &self,
        team_id: TeamId,
        exception: Exception,
    ) -> Result<Exception, UnhandledError>;

    async fn resolve_dart_exception(
        &self,
        team_id: TeamId,
        exception: Exception,
    ) -> Result<Exception, UnhandledError>;

    fn flush(&self) {}
}
