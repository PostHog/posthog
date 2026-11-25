use std::{fmt, rc::Rc, sync::Arc};

use gpui::{App, Context, SharedString, Subscription, WeakEntity};

use super::{SpeechState, state::defer_session_update};

/// The PCM format a [`SpeechRecognizer`] consumes.
///
/// Audio always arrives as interleaved signed 16-bit samples; an [`AudioInput`]
/// converts whatever its device produces to this rate and channel count.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AudioFormat {
    sample_rate: u32,
    channels: u16,
}

impl AudioFormat {
    /// A format of `sample_rate` samples per second on each of `channels`.
    pub fn new(sample_rate: u32, channels: u16) -> Self {
        Self {
            sample_rate,
            channels,
        }
    }

    /// Samples per second of each channel.
    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    /// Number of interleaved channels.
    pub fn channels(&self) -> u16 {
        self.channels
    }
}

impl Default for AudioFormat {
    /// 16 kHz mono, the format most speech services expect.
    fn default() -> Self {
        Self::new(16_000, 1)
    }
}

/// Why a speech session failed.
#[derive(Debug, Clone)]
pub enum SpeechError {
    /// The user or the system denied access to the microphone.
    PermissionDenied,
    /// No audio input device is available.
    NoInputDevice,
    /// Speech input is not supported on this platform or build.
    Unsupported,
    /// The audio input failed or its device went away.
    Input(Arc<anyhow::Error>),
    /// The recognizer failed, e.g. it could not reach its service.
    Recognizer(Arc<anyhow::Error>),
}

impl SpeechError {
    /// An [`SpeechError::Input`] from any error.
    pub fn input(error: impl Into<anyhow::Error>) -> Self {
        Self::Input(Arc::new(error.into()))
    }

    /// A [`SpeechError::Recognizer`] from any error.
    pub fn recognizer(error: impl Into<anyhow::Error>) -> Self {
        Self::Recognizer(Arc::new(error.into()))
    }
}

impl fmt::Display for SpeechError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PermissionDenied => f.write_str("microphone access was denied"),
            Self::NoInputDevice => f.write_str("no audio input device is available"),
            Self::Unsupported => f.write_str("speech input is not supported"),
            Self::Input(error) => write!(f, "audio input failed: {error:#}"),
            Self::Recognizer(error) => write!(f, "speech recognition failed: {error:#}"),
        }
    }
}

impl std::error::Error for SpeechError {}

/// Turns speech into text, e.g. by streaming audio to a cloud service.
///
/// Implement it for the service the application uses and pass it to
/// [`SpeechState::recognizer`]. Without one, the state falls back to the
/// platform's own recognizer where there is one (see
/// `SystemRecognizer`).
///
/// A session runs as follows:
///
/// 1. [`start`](Self::start) opens a session. Connecting may take a while, so
///    return immediately and buffer the audio pushed in the meantime; call
///    [`SpeechSink::ready`] once the service accepts audio.
/// 2. [`RecognitionSession::push_audio`] delivers PCM in [`Self::audio_format`].
///    Report results through [`SpeechSink::hypothesis`] and
///    [`SpeechSink::phrase`] as they arrive.
/// 3. [`RecognitionSession::finish`] means the user stopped talking: send the
///    remaining audio, wait for the last result, then call
///    [`SpeechSink::finish`].
///
/// Dropping the [`RecognitionSession`] cancels it: close the connection and
/// report nothing more. Every [`SpeechSink`] method may be called from any
/// point on the main thread, including from inside `start` or `push_audio`.
pub trait SpeechRecognizer: 'static {
    /// The audio format this recognizer consumes, default 16 kHz mono.
    fn audio_format(&self) -> AudioFormat {
        AudioFormat::default()
    }

    /// Whether the recognizer can start a session now, default `true`.
    ///
    /// Return `false` while it cannot work, e.g. before the user signs in; the
    /// [`SpeechButton`](super::SpeechButton) then renders disabled. Called on
    /// every render, so keep it cheap.
    fn is_available(&self, _cx: &App) -> bool {
        true
    }

    /// Open a session that reports its results to `sink`.
    fn start(
        &self,
        sink: SpeechSink,
        cx: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError>;
}

impl<T: SpeechRecognizer + ?Sized> SpeechRecognizer for Rc<T> {
    fn audio_format(&self) -> AudioFormat {
        (**self).audio_format()
    }

    fn is_available(&self, cx: &App) -> bool {
        (**self).is_available(cx)
    }

    fn start(
        &self,
        sink: SpeechSink,
        cx: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
        (**self).start(sink, cx)
    }
}

/// One running recognition, opened by [`SpeechRecognizer::start`].
///
/// Dropping it cancels the session.
pub trait RecognitionSession: 'static {
    /// Deliver interleaved PCM samples in the recognizer's [`AudioFormat`].
    fn push_audio(&mut self, samples: &[i16], cx: &mut App);

    /// No more audio will arrive. Flush what is buffered and call
    /// [`SpeechSink::finish`] once the final result is in.
    fn finish(&mut self, cx: &mut App);
}

/// Where a [`SpeechRecognizer`] reports its session's progress.
///
/// The sink is cheap to clone and may outlive its session: once the session is
/// stopped, cancelled or replaced, its calls are ignored. Calls are applied
/// after the current update, so they never re-enter the [`SpeechState`].
#[derive(Clone)]
pub struct SpeechSink {
    pub(super) state: WeakEntity<SpeechState>,
    pub(super) session: usize,
}

impl SpeechSink {
    /// The service is connected and consuming audio.
    pub fn ready(&self, cx: &mut App) {
        self.apply(cx, |state, cx| state.on_ready(cx));
    }

    /// Replace the hypothesis for the phrase being spoken.
    pub fn hypothesis(&self, text: impl Into<SharedString>, cx: &mut App) {
        let text = text.into();
        self.apply(cx, move |state, cx| state.on_hypothesis(text, cx));
    }

    /// Commit a recognized phrase and clear the hypothesis.
    ///
    /// Phrases are joined verbatim, so include any separator the language
    /// needs, such as a leading space between English sentences.
    pub fn phrase(&self, text: impl Into<SharedString>, cx: &mut App) {
        let text = text.into();
        self.apply(cx, move |state, cx| state.on_phrase(text, cx));
    }

    /// The session is complete; no more results will follow.
    pub fn finish(&self, cx: &mut App) {
        self.apply(cx, |state, cx| state.on_finish(cx));
    }

    /// The session failed.
    pub fn error(&self, error: SpeechError, cx: &mut App) {
        self.apply(cx, move |state, cx| state.on_error(error, cx));
    }

    fn apply(
        &self,
        cx: &mut App,
        f: impl FnOnce(&mut SpeechState, &mut Context<SpeechState>) + 'static,
    ) {
        defer_session_update(self.state.clone(), self.session, cx, f);
    }
}

/// A source of audio for a [`SpeechState`], such as the microphone.
///
/// Enable the `speech` feature for the built-in `Microphone`,
/// or implement this trait to feed audio from elsewhere, e.g. a file in tests.
pub trait AudioInput: 'static {
    /// Start capturing `format` audio into `sink`.
    ///
    /// Capture runs until the returned [`Subscription`] is dropped.
    fn start(
        &self,
        format: AudioFormat,
        sink: AudioSink,
        cx: &mut App,
    ) -> Result<Subscription, SpeechError>;
}

impl<T: AudioInput + ?Sized> AudioInput for Rc<T> {
    fn start(
        &self,
        format: AudioFormat,
        sink: AudioSink,
        cx: &mut App,
    ) -> Result<Subscription, SpeechError> {
        (**self).start(format, sink, cx)
    }
}

/// Where an [`AudioInput`] delivers captured audio.
///
/// Like [`SpeechSink`], it is cheap to clone, ignored once its session ends and
/// applied after the current update.
#[derive(Clone)]
pub struct AudioSink {
    pub(super) state: WeakEntity<SpeechState>,
    pub(super) session: usize,
}

impl AudioSink {
    /// Deliver interleaved PCM samples in the requested [`AudioFormat`].
    pub fn push(&self, samples: Vec<i16>, cx: &mut App) {
        self.apply(cx, move |state, cx| state.on_audio(&samples, cx));
    }

    /// Capture failed; the session ends with this error.
    pub fn error(&self, error: SpeechError, cx: &mut App) {
        self.apply(cx, move |state, cx| state.on_error(error, cx));
    }

    fn apply(
        &self,
        cx: &mut App,
        f: impl FnOnce(&mut SpeechState, &mut Context<SpeechState>) + 'static,
    ) {
        defer_session_update(self.state.clone(), self.session, cx, f);
    }
}
