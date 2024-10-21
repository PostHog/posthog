use axum::async_trait;

use crate::types::frames::Frame;

#[async_trait]
pub trait FrameStore: Send + Sync + 'static {
    // // Symbol stores return an Arc, to allow them to cache (and evict) without any consent from callers
    // async fn fetch(&self, team_id: i32, r: SymbolSetRef) -> Result<Arc<Vec<u8>>, Error>;

    fn get(&self, raw_frame_id: String) -> Option<Frame>;
    fn set(&self, id: String, frame: Frame);
}
