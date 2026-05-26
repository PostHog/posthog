use std::sync::atomic::AtomicUsize;

use async_trait::async_trait;
use common_types::error_tracking::FrameId;
use cymbal_symbol_store::UnhandledError;
use serde::{Deserialize, Serialize};

pub mod apple;
pub mod custom;
pub mod dart;
pub mod go;
pub mod hermes;
pub mod java;
pub mod js;
pub mod node;
pub mod php;
pub mod python;
pub mod raw_frame;
pub mod ruby;
pub mod utils;

pub use cymbal_symbol_store::{Catalog, SymbolCatalog};
pub use raw_frame::RawFrame;

#[async_trait]
pub trait Symbolicator: Send + Sync {
    async fn resolve_raw_frame(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[apple::AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError>;
}

#[async_trait]
impl Symbolicator for Catalog {
    async fn resolve_raw_frame(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[apple::AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        frame.resolve(team_id, self, debug_images).await
    }
}

// Runtime updates this during startup; resolvers read it from hot paths without
// carrying config through every language-specific frame conversion.
pub static FRAME_CONTEXT_LINES: AtomicUsize = AtomicUsize::new(15);

pub type Frame = cymbal_domain::Frame<FrameId>;

pub trait IntoFrame {
    fn into_frame(self) -> Frame;
}

/// Records the metric and tracing line for a single failed-frame construction. Each
/// language-specific `IntoFrame` impl calls this with the typed error in scope, so we
/// don't have to round-trip the typed error through the `Frame` struct just to recover
/// the metric reason later.
pub fn record_frame_resolution_failure(
    lang: &'static str,
    reason: &'static str,
    err: &dyn std::fmt::Display,
) {
    metrics::counter!(FRAME_NOT_RESOLVED, "lang" => lang, "reason" => reason).increment(1);
    match reason {
        "network_error" | "invalid_data" | "symbol_not_found" => {
            tracing::warn!(lang = lang, reason = reason, error = %err, "frame resolution failed");
        }
        _ => {
            tracing::debug!(lang = lang, reason = reason, error = %err, "frame resolution failed");
        }
    }
}

// Some metadata is common across all languages, so we define it here. In some
// platforms, these may always default to false.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize, Default)]
pub struct CommonFrameMetadata {
    #[serde(default = "default_in_app")]
    pub in_app: bool, // Whether the frame is part of application or library code
    #[serde(default)]
    pub synthetic: bool, // Whether the frame is synthetic or not
}

fn default_in_app() -> bool {
    true
}

#[cfg(test)]
pub fn test_store_config() -> cymbal_symbol_store::SymbolStoreConfig {
    cymbal_symbol_store::SymbolStoreConfig {
        allow_internal_ips: true,
        sourcemap_timeout_seconds: 30,
        sourcemap_connect_timeout_seconds: 30,
        cache_max_bytes: 128 * 1024 * 1024,
        object_storage_bucket: "test-bucket".to_string(),
        object_storage_prefix: "test-prefix".to_string(),
    }
}

pub const FRAME_RESOLVED: &str = "cymbal_frame_resolved";
pub const FRAME_NOT_RESOLVED: &str = "cymbal_frame_not_resolved";
pub const PER_FRAME_TIME: &str = "cymbal_per_frame_time";
pub const JS_PLATFORM_ALIAS_FRAME_RESOLVED: &str = "cymbal_legacy_js_frame_resolved";

fn to_vec<T, E>(item: Result<T, E>) -> Result<Vec<T>, E> {
    item.map(|t| vec![t])
}
