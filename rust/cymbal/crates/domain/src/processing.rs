use cymbal_core::Metadata;

pub const SKIP_ALERTING_METADATA_KEY: &str = "cymbal.processing.skip_alerting";
pub const EMIT_INTERNAL_EVENTS_METADATA_KEY: &str = "cymbal.processing.emit_internal_events";
pub const EMIT_SIGNALS_METADATA_KEY: &str = "cymbal.processing.emit_signals";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExceptionProcessingOptions {
    pub skip_alerting: bool,
    pub emit_internal_events: bool,
    pub emit_signals: bool,
}

impl Default for ExceptionProcessingOptions {
    fn default() -> Self {
        Self {
            skip_alerting: false,
            emit_internal_events: true,
            emit_signals: true,
        }
    }
}

impl ExceptionProcessingOptions {
    pub fn from_metadata(metadata: &Metadata) -> Self {
        Self {
            skip_alerting: metadata_bool(metadata, SKIP_ALERTING_METADATA_KEY, false),
            emit_internal_events: metadata_bool(metadata, EMIT_INTERNAL_EVENTS_METADATA_KEY, true),
            emit_signals: metadata_bool(metadata, EMIT_SIGNALS_METADATA_KEY, true),
        }
    }

    pub fn write_to_metadata(self, metadata: &mut Metadata) {
        metadata.insert(
            SKIP_ALERTING_METADATA_KEY.to_string(),
            self.skip_alerting.to_string(),
        );
        metadata.insert(
            EMIT_INTERNAL_EVENTS_METADATA_KEY.to_string(),
            self.emit_internal_events.to_string(),
        );
        metadata.insert(
            EMIT_SIGNALS_METADATA_KEY.to_string(),
            self.emit_signals.to_string(),
        );
    }
}

fn metadata_bool(metadata: &Metadata, key: &str, default: bool) -> bool {
    metadata
        .get(key)
        .and_then(|value| value.parse::<bool>().ok())
        .unwrap_or(default)
}
