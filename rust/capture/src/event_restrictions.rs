//! Event restriction policy, promoted to the `common-event-restrictions` crate.
//!
//! Capture re-exports the crate under the original `crate::event_restrictions`
//! path so existing capture code keeps compiling unchanged. The only
//! capture-specific piece that stays here is [`pipelines_for_capture_mode`],
//! which maps a capture deployment's [`CaptureMode`] to the ingestion pipelines
//! it produces to — a mapping that belongs to capture, not to the shared crate.

pub use common_event_restrictions::*;

use crate::config::CaptureMode;

/// Pipelines a given capture deployment produces events to. The events
/// deployment writes to both `analytics` (normal events) and `errortracking`
/// (`$exception` events split off in `process_single_event`), so its restriction
/// service must serve restrictions for both pipelines. Other deployments serve
/// their single pipeline.
pub fn pipelines_for_capture_mode(mode: CaptureMode) -> Vec<Pipeline> {
    match mode {
        CaptureMode::Events => vec![Pipeline::Analytics, Pipeline::ErrorTracking],
        CaptureMode::Recordings => vec![Pipeline::SessionRecordings],
        CaptureMode::Ai => vec![Pipeline::Ai],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pipelines_for_capture_mode_maps_each_mode() {
        assert_eq!(
            pipelines_for_capture_mode(CaptureMode::Events),
            vec![Pipeline::Analytics, Pipeline::ErrorTracking]
        );
        assert_eq!(
            pipelines_for_capture_mode(CaptureMode::Recordings),
            vec![Pipeline::SessionRecordings]
        );
        assert_eq!(
            pipelines_for_capture_mode(CaptureMode::Ai),
            vec![Pipeline::Ai]
        );
    }
}
