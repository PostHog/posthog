use gpui::{App, SharedString};

use crate::speech::{AudioFormat, RecognitionSession, SpeechError, SpeechRecognizer, SpeechSink};

/// Placeholder until the platform recognizer lands.
pub(super) struct PlatformRecognizer;

impl PlatformRecognizer {
    pub(super) fn new(_locale: Option<SharedString>) -> Self {
        Self
    }
}

impl SpeechRecognizer for PlatformRecognizer {
    fn audio_format(&self) -> AudioFormat {
        AudioFormat::default()
    }

    fn is_available(&self, _: &App) -> bool {
        false
    }

    fn start(
        &self,
        _: SpeechSink,
        _: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
        Err(SpeechError::Unsupported)
    }
}
