use axum::async_trait;

use crate::{error::Error, types::frames::Frame};

#[async_trait]
pub trait FrameStore: Send + Sync + 'static {
    async fn store(&self, team_id: i32, id: String) -> ();
    async fn fetch(&self, team_id: i32, id: String) -> Result<Option<Frame>, Error>;
}
