//! The platform's own speech recognizer.

use std::{cell::OnceCell, rc::Rc};

use gpui::{App, SharedString};

use super::{AudioFormat, RecognitionSession, SpeechError, SpeechRecognizer, SpeechSink};

#[cfg(target_os = "macos")]
pub(super) mod macos;
#[cfg(target_os = "macos")]
use macos as platform;

#[cfg(target_os = "windows")]
mod winrt;
#[cfg(target_os = "windows")]
use winrt as platform;

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
mod unsupported;
#[cfg(not(any(target_os = "macos", target_os = "windows")))]
use unsupported as platform;

/// The operating system's speech recognizer.
///
/// - **macOS**: `SFSpeechRecognizer`, recognizing on the device only. A
///   language the device cannot recognize offline is not available, so audio
///   never leaves the machine.
/// - **Windows**: `Windows.Media.SpeechRecognition`. Dictation needs the
///   language's speech pack and the "Online speech recognition" privacy
///   setting, and runs through Microsoft's online service.
/// - **Other platforms**: never available.
///
/// A [`SpeechState`](super::SpeechState) without its own recognizer uses this
/// one; create it directly to choose the language.
pub struct SystemRecognizer {
    locale: Option<SharedString>,
    platform: OnceCell<Rc<platform::PlatformRecognizer>>,
}

impl SystemRecognizer {
    /// A recognizer for the system's current language.
    pub fn new() -> Self {
        Self {
            locale: None,
            platform: OnceCell::new(),
        }
    }

    /// Recognize `locale`, a BCP 47 language tag such as `en-US` or `zh-CN`,
    /// instead of the system's language.
    pub fn locale(mut self, locale: impl Into<SharedString>) -> Self {
        self.locale = Some(locale.into());
        self.platform = OnceCell::new();
        self
    }

    fn platform(&self) -> &Rc<platform::PlatformRecognizer> {
        self.platform
            .get_or_init(|| Rc::new(platform::PlatformRecognizer::new(self.locale.clone())))
    }
}

impl Default for SystemRecognizer {
    fn default() -> Self {
        Self::new()
    }
}

impl SpeechRecognizer for SystemRecognizer {
    fn audio_format(&self) -> AudioFormat {
        self.platform().audio_format()
    }

    fn is_available(&self, cx: &App) -> bool {
        self.platform().is_available(cx)
    }

    fn start(
        &self,
        sink: SpeechSink,
        cx: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
        self.platform().start(sink, cx)
    }
}
