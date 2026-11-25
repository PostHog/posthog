//! The Windows recognizer: continuous dictation with
//! `Windows.Media.SpeechRecognition`.
//!
//! The WinRT recognizer captures from the default microphone itself and has no
//! way to consume audio from elsewhere, so the pushed PCM is ignored; the
//! [`Microphone`](crate::speech::Microphone) keeps capturing alongside it only
//! to drive the waveform, which WASAPI's shared mode allows.
//!
//! The speech objects are agile, so they are called from the main thread, an
//! STA that GPUI initializes with `OleInitialize`, without further apartment
//! setup. Their completions and events arrive on WinRT threads, which only
//! forward them over a channel to a foreground task that reports to the sink.

use anyhow::anyhow;
use gpui::{App, AsyncApp, SharedString, Task};
use smol::channel::{Receiver, Sender, bounded, unbounded};
use windows::{
    Foundation::{
        AsyncActionCompletedHandler, AsyncOperationCompletedHandler, EventRegistrationToken,
        IAsyncAction, IAsyncOperation, TypedEventHandler,
    },
    Globalization::Language,
    Media::SpeechRecognition::{
        SpeechContinuousRecognitionCompletedEventArgs,
        SpeechContinuousRecognitionResultGeneratedEventArgs, SpeechContinuousRecognitionSession,
        SpeechRecognitionConfidence, SpeechRecognitionHypothesisGeneratedEventArgs,
        SpeechRecognitionResult, SpeechRecognitionResultStatus, SpeechRecognitionScenario,
        SpeechRecognitionTopicConstraint, SpeechRecognizer as WinSpeechRecognizer,
    },
    Win32::Foundation::E_ACCESSDENIED,
    core::{HRESULT, HSTRING, RuntimeType},
};

use crate::speech::{AudioFormat, RecognitionSession, SpeechError, SpeechRecognizer, SpeechSink};

/// `SPERR_SPEECH_PRIVACY_POLICY_NOT_ACCEPTED`: "Online speech recognition" is
/// turned off in the privacy settings, which dictation requires.
const PRIVACY_POLICY_NOT_ACCEPTED: HRESULT = HRESULT(0x80045509_u32 as i32);
/// `MF_E_NO_CAPTURE_DEVICES_AVAILABLE`.
const NO_CAPTURE_DEVICES: HRESULT = HRESULT(0xC00DABE0_u32 as i32);

pub(super) struct PlatformRecognizer {
    /// The dictation language, or `None` when the requested one is malformed or
    /// has no speech pack installed.
    language: Option<Language>,
    separator: &'static str,
}

impl PlatformRecognizer {
    pub(super) fn new(locale: Option<SharedString>) -> Self {
        let language = supported_language(locale.as_deref())
            .inspect_err(|error| log::warn!("speech: no dictation language: {error:#}"))
            .ok()
            .flatten();
        let separator = language
            .as_ref()
            .and_then(|language| language.LanguageTag().ok())
            .map_or(" ", |tag| phrase_separator(&tag.to_string_lossy()));
        Self {
            language,
            separator,
        }
    }
}

impl SpeechRecognizer for PlatformRecognizer {
    fn audio_format(&self) -> AudioFormat {
        AudioFormat::default()
    }

    fn is_available(&self, _: &App) -> bool {
        self.language.is_some()
    }

    fn start(
        &self,
        sink: SpeechSink,
        cx: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
        let Some(language) = &self.language else {
            return Err(SpeechError::Unsupported);
        };

        let recognizer = WinSpeechRecognizer::Create(language).map_err(speech_error)?;
        let continuous = recognizer
            .ContinuousRecognitionSession()
            .map_err(speech_error)?;
        let (messages, rx) = unbounded();
        let mut session = Session {
            recognizer: recognizer.clone(),
            continuous: continuous.clone(),
            hypothesis_token: None,
            result_token: None,
            completed_token: None,
            messages: messages.clone(),
            _task: None,
        };

        let constraint = SpeechRecognitionTopicConstraint::Create(
            SpeechRecognitionScenario::Dictation,
            &HSTRING::from("dictation"),
        )
        .map_err(speech_error)?;
        recognizer
            .Constraints()
            .and_then(|constraints| constraints.Append(&constraint))
            .map_err(speech_error)?;

        session.hypothesis_token = Some(
            recognizer
                .HypothesisGenerated(&TypedEventHandler::new({
                    let messages = messages.clone();
                    move |_, args: &Option<SpeechRecognitionHypothesisGeneratedEventArgs>| {
                        if let Some(args) = args {
                            let text = args.Hypothesis()?.Text()?;
                            _ = messages.try_send(Message::Hypothesis(text));
                        }
                        Ok(())
                    }
                }))
                .map_err(speech_error)?,
        );
        session.result_token = Some(
            continuous
                .ResultGenerated(&TypedEventHandler::new({
                    let messages = messages.clone();
                    move |_, args: &Option<SpeechContinuousRecognitionResultGeneratedEventArgs>| {
                        if let Some(args) = args {
                            _ = messages.try_send(Message::Result(args.Result()?));
                        }
                        Ok(())
                    }
                }))
                .map_err(speech_error)?,
        );
        session.completed_token = Some(
            continuous
                .Completed(&TypedEventHandler::new({
                    let messages = messages.clone();
                    move |_, args: &Option<SpeechContinuousRecognitionCompletedEventArgs>| {
                        if let Some(args) = args {
                            _ = messages.try_send(Message::Completed(args.Status()?));
                        }
                        Ok(())
                    }
                }))
                .map_err(speech_error)?,
        );

        let separator = self.separator;
        session._task = Some(cx.spawn(async move |cx| {
            let result = dictate(&recognizer, &continuous, rx, &sink, separator, cx).await;
            if let Err(error) = result {
                cx.update(|cx| sink.error(error, cx));
            }
        }));
        Ok(Box::new(session))
    }
}

/// What the WinRT threads and [`Session::finish`] tell the dictation task.
enum Message {
    Hypothesis(HSTRING),
    Result(SpeechRecognitionResult),
    Completed(SpeechRecognitionResultStatus),
    /// The user stopped talking.
    Finish,
}

struct Session {
    recognizer: WinSpeechRecognizer,
    continuous: SpeechContinuousRecognitionSession,
    hypothesis_token: Option<EventRegistrationToken>,
    result_token: Option<EventRegistrationToken>,
    completed_token: Option<EventRegistrationToken>,
    messages: Sender<Message>,
    _task: Option<Task<()>>,
}

impl RecognitionSession for Session {
    /// Ignored: the WinRT recognizer captures from the microphone itself.
    fn push_audio(&mut self, _: &[i16], _: &mut App) {}

    fn finish(&mut self, _: &mut App) {
        // Queued behind the start, so finishing while connecting stops the
        // session as soon as it runs.
        _ = self.messages.try_send(Message::Finish);
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        if let Some(token) = self.hypothesis_token.take() {
            _ = self.recognizer.RemoveHypothesisGenerated(token);
        }
        if let Some(token) = self.result_token.take() {
            _ = self.continuous.RemoveResultGenerated(token);
        }
        if let Some(token) = self.completed_token.take() {
            _ = self.continuous.RemoveCompleted(token);
        }

        // Close the recognizer once the cancellation lands, or right away when
        // there is nothing to cancel.
        let recognizer = self.recognizer.clone();
        let closed = self.continuous.CancelAsync().and_then(|action| {
            action.SetCompleted(&AsyncActionCompletedHandler::new(move |_, _| {
                _ = recognizer.Close();
                Ok(())
            }))
        });
        if closed.is_err() {
            _ = self.recognizer.Close();
        }
    }
}

/// Compile the dictation constraint, start the continuous session and report
/// its results to `sink` until it completes.
async fn dictate(
    recognizer: &WinSpeechRecognizer,
    continuous: &SpeechContinuousRecognitionSession,
    messages: Receiver<Message>,
    sink: &SpeechSink,
    separator: &'static str,
    cx: &mut AsyncApp,
) -> Result<(), SpeechError> {
    let compilation = operation(recognizer.CompileConstraintsAsync().map_err(speech_error)?)
        .await
        .map_err(speech_error)?;
    let status = compilation.Status().map_err(speech_error)?;
    if status != SpeechRecognitionResultStatus::Success {
        return Err(status_error(status));
    }
    action(continuous.StartAsync().map_err(speech_error)?)
        .await
        .map_err(speech_error)?;
    cx.update(|cx| sink.ready(cx));

    let mut separator_due = false;
    while let Ok(message) = messages.recv().await {
        match message {
            Message::Hypothesis(text) => {
                let text = joined(separator_due, separator, &text);
                cx.update(|cx| sink.hypothesis(text, cx));
            }
            Message::Result(result) => {
                let Some(text) = phrase_text(&result) else {
                    continue;
                };
                let text = joined(separator_due, separator, &text);
                separator_due = true;
                cx.update(|cx| sink.phrase(text, cx));
            }
            Message::Completed(status) => {
                return match status {
                    // Stopped, cancelled, or ended by the silence timeout.
                    SpeechRecognitionResultStatus::Success
                    | SpeechRecognitionResultStatus::UserCanceled
                    | SpeechRecognitionResultStatus::TimeoutExceeded => {
                        cx.update(|cx| sink.finish(cx));
                        Ok(())
                    }
                    status => Err(status_error(status)),
                };
            }
            // Stopping flushes the last phrase, then completes the session.
            Message::Finish => {
                let stopped = match continuous.StopAsync() {
                    Ok(stop) => action(stop).await,
                    Err(error) => Err(error),
                };
                // The session may have ended by itself, e.g. after the silence
                // timeout, with its `Completed` still queued behind this; stopping
                // it then fails, and that queued event ends the session instead.
                if let Err(error) = stopped {
                    log::debug!("speech: stopping dictation failed: {error}");
                }
            }
        }
    }
    Ok(())
}

/// The text of a recognized phrase, unless it was rejected or empty.
fn phrase_text(result: &SpeechRecognitionResult) -> Option<HSTRING> {
    if result.Status().ok()? != SpeechRecognitionResultStatus::Success
        || result.Confidence().ok()? == SpeechRecognitionConfidence::Rejected
    {
        return None;
    }
    Some(result.Text().ok()?).filter(|text| !text.is_empty())
}

/// `text` preceded by `separator` once a phrase has been committed.
fn joined(separator_due: bool, separator: &str, text: &HSTRING) -> SharedString {
    let text = text.to_string_lossy();
    if separator_due {
        format!("{separator}{text}").into()
    } else {
        text.into()
    }
}

/// What goes between two phrases, which dictation returns without surrounding
/// whitespace: a space, except in languages written without spaces between
/// words (Chinese, Japanese, Thai, Lao, Khmer, Burmese).
fn phrase_separator(tag: &str) -> &'static str {
    let primary = tag.split('-').next().unwrap_or_default();
    let unspaced = ["zh", "yue", "ja", "th", "lo", "km", "my"];
    if unspaced
        .iter()
        .any(|lang| primary.eq_ignore_ascii_case(lang))
    {
        ""
    } else {
        " "
    }
}

/// The language to dictate `locale` (or, without one, the system's speech
/// language) in, if a speech pack supports it.
///
/// A bare language such as `en` falls back to the first supported region.
fn supported_language(locale: Option<&str>) -> windows::core::Result<Option<Language>> {
    let requested = match locale {
        Some(locale) => {
            let tag = HSTRING::from(locale);
            if !Language::IsWellFormed(&tag)? {
                return Ok(None);
            }
            Language::CreateLanguage(&tag)?
        }
        None => WinSpeechRecognizer::SystemSpeechLanguage()?,
    };
    let requested = requested.LanguageTag()?.to_string_lossy();
    let region_prefix = format!("{requested}-");

    let mut fallback = None;
    for language in WinSpeechRecognizer::SupportedTopicLanguages()? {
        let tag = language.LanguageTag()?.to_string_lossy();
        if tag.eq_ignore_ascii_case(&requested) {
            return Ok(Some(language));
        }
        if fallback.is_none()
            && tag.len() > region_prefix.len()
            && tag[..region_prefix.len()].eq_ignore_ascii_case(&region_prefix)
        {
            fallback = Some(language);
        }
    }
    Ok(fallback)
}

/// Await `operation` without blocking: its completion handler, which runs on a
/// WinRT thread, only wakes this future.
async fn operation<T: RuntimeType + 'static>(
    operation: IAsyncOperation<T>,
) -> windows::core::Result<T> {
    let (done, wait) = bounded(1);
    operation.SetCompleted(&AsyncOperationCompletedHandler::new(move |_, _| {
        _ = done.try_send(());
        Ok(())
    }))?;
    _ = wait.recv().await;
    operation.GetResults()
}

/// Await `action` like [`operation`].
async fn action(action: IAsyncAction) -> windows::core::Result<()> {
    let (done, wait) = bounded(1);
    action.SetCompleted(&AsyncActionCompletedHandler::new(move |_, _| {
        _ = done.try_send(());
        Ok(())
    }))?;
    _ = wait.recv().await;
    action.GetResults()
}

fn speech_error(error: windows::core::Error) -> SpeechError {
    match error.code() {
        E_ACCESSDENIED => SpeechError::PermissionDenied,
        NO_CAPTURE_DEVICES => SpeechError::NoInputDevice,
        PRIVACY_POLICY_NOT_ACCEPTED => SpeechError::recognizer(anyhow!(
            "Online speech recognition is turned off; turn it on in Settings > \
             Privacy & security > Speech"
        )),
        _ => SpeechError::recognizer(error),
    }
}

fn status_error(status: SpeechRecognitionResultStatus) -> SpeechError {
    match status {
        SpeechRecognitionResultStatus::TopicLanguageNotSupported => SpeechError::Unsupported,
        SpeechRecognitionResultStatus::MicrophoneUnavailable => SpeechError::NoInputDevice,
        SpeechRecognitionResultStatus::NetworkFailure => {
            SpeechError::recognizer(anyhow!("could not reach the online speech service"))
        }
        SpeechRecognitionResultStatus::AudioQualityFailure => {
            SpeechError::recognizer(anyhow!("the audio was too poor to recognize"))
        }
        status => SpeechError::recognizer(anyhow!("recognition ended with status {}", status.0)),
    }
}
