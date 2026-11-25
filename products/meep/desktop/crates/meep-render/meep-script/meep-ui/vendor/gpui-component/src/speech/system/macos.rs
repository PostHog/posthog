//! `SFSpeechRecognizer`, recognizing on the device only.

use std::{cell::RefCell, rc::Rc};

use anyhow::anyhow;
use block2::RcBlock;
use gpui::{App, SharedString, Task};
use objc2::{AnyThread as _, rc::Retained, runtime::NSObjectProtocol as _, sel};
use objc2_av_foundation::{AVAuthorizationStatus, AVCaptureDevice, AVMediaTypeAudio};
use objc2_avf_audio::{AVAudioCommonFormat, AVAudioFormat, AVAudioPCMBuffer};
use objc2_foundation::{NSBundle, NSError, NSLocale, NSString};
use objc2_speech::{
    SFSpeechAudioBufferRecognitionRequest, SFSpeechRecognitionResult, SFSpeechRecognitionTask,
    SFSpeechRecognizer, SFSpeechRecognizerAuthorizationStatus,
};
use smol::channel::{Receiver, Sender, unbounded};

use crate::speech::{AudioFormat, RecognitionSession, SpeechError, SpeechRecognizer, SpeechSink};

/// Without this `Info.plist` key, asking for speech recognition access
/// terminates the process.
const USAGE_DESCRIPTION_KEY: &str = "NSSpeechRecognitionUsageDescription";

/// The error `SFSpeechRecognizer` reports when the audio held no speech.
const NO_SPEECH_DOMAIN: &str = "kAFAssistantErrorDomain";
const NO_SPEECH_CODE: isize = 1110;

pub(super) struct PlatformRecognizer {
    /// `None` when the locale has no recognizer or the application cannot ask
    /// for access.
    recognizer: Option<Retained<SFSpeechRecognizer>>,
}

impl PlatformRecognizer {
    pub(super) fn new(locale: Option<SharedString>) -> Self {
        if !has_usage_description() {
            tracing::warn!(
                "speech recognition is unavailable: the application's Info.plist has no \
                 `{USAGE_DESCRIPTION_KEY}`, and asking for access without it terminates the process"
            );
            return Self { recognizer: None };
        }

        let recognizer = match &locale {
            Some(locale) => {
                let locale = NSLocale::initWithLocaleIdentifier(
                    NSLocale::alloc(),
                    &NSString::from_str(locale),
                );
                // SAFETY: `locale` is a valid `NSLocale`; the initializer returns
                // nil for a locale without a recognizer.
                unsafe { SFSpeechRecognizer::initWithLocale(SFSpeechRecognizer::alloc(), &locale) }
            }
            // SAFETY: plain initializer; returns nil if the system language has
            // no recognizer.
            None => unsafe { SFSpeechRecognizer::init(SFSpeechRecognizer::alloc()) },
        };
        if recognizer.is_none() {
            tracing::warn!(
                "speech recognition is unavailable: no recognizer for locale {}",
                locale.as_deref().unwrap_or("of the system")
            );
        }

        Self { recognizer }
    }

    /// The recognizer, if it can recognize on the device.
    fn on_device(&self) -> Option<&Retained<SFSpeechRecognizer>> {
        self.recognizer
            .as_ref()
            // SAFETY: plain property reads on a valid recognizer.
            .filter(|recognizer| unsafe {
                recognizer.isAvailable() && recognizer.supportsOnDeviceRecognition()
            })
    }
}

impl SpeechRecognizer for PlatformRecognizer {
    fn audio_format(&self) -> AudioFormat {
        AudioFormat::default()
    }

    fn is_available(&self, _: &App) -> bool {
        self.on_device().is_some() && !is_speech_denied(speech_authorization())
    }

    fn start(
        &self,
        sink: SpeechSink,
        cx: &mut App,
    ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
        let recognizer = self.on_device().ok_or(SpeechError::Unsupported)?.clone();
        let authorization = speech_authorization();
        if is_speech_denied(authorization) {
            return Err(SpeechError::PermissionDenied);
        }

        let (events, rx) = unbounded();
        let mut recognition = Recognition::new(recognizer, sink, events.clone())?;
        if authorization == SFSpeechRecognizerAuthorizationStatus::Authorized {
            recognition.begin(cx);
        } else {
            request_authorization(events);
        }

        let recognition = Rc::new(RefCell::new(recognition));
        let task = cx.spawn({
            let recognition = recognition.clone();
            async move |cx| run(recognition, rx, cx).await
        });

        Ok(Box::new(Session {
            recognition,
            _task: task,
        }))
    }
}

/// Whether the user or a policy denied this application the microphone.
///
/// Capturing without access yields silence rather than an error on macOS, so
/// the [`Microphone`](crate::speech::Microphone) checks this first.
pub(in crate::speech) fn is_microphone_denied() -> bool {
    // SAFETY: reading an immutable framework constant.
    let Some(audio) = (unsafe { AVMediaTypeAudio }) else {
        return false;
    };
    // SAFETY: `audio` is one of the two media types the method accepts.
    let status = unsafe { AVCaptureDevice::authorizationStatusForMediaType(audio) };
    status == AVAuthorizationStatus::Denied || status == AVAuthorizationStatus::Restricted
}

fn has_usage_description() -> bool {
    NSBundle::mainBundle()
        .objectForInfoDictionaryKey(&NSString::from_str(USAGE_DESCRIPTION_KEY))
        .is_some()
}

fn speech_authorization() -> SFSpeechRecognizerAuthorizationStatus {
    // SAFETY: reading the status never prompts, so it is safe without the
    // usage description.
    unsafe { SFSpeechRecognizer::authorizationStatus() }
}

fn is_speech_denied(status: SFSpeechRecognizerAuthorizationStatus) -> bool {
    status == SFSpeechRecognizerAuthorizationStatus::Denied
        || status == SFSpeechRecognizerAuthorizationStatus::Restricted
}

/// Ask for speech recognition access; the answer arrives as an [`Event`].
fn request_authorization(events: Sender<Event>) {
    let handler = RcBlock::new(move |status: SFSpeechRecognizerAuthorizationStatus| {
        _ = events.try_send(Event::Authorized(
            status == SFSpeechRecognizerAuthorizationStatus::Authorized,
        ));
    });
    // SAFETY: only reached with the usage description present (see
    // `PlatformRecognizer::new`); the block only sends on a channel, so it may
    // run on any queue.
    unsafe { SFSpeechRecognizer::requestAuthorization(&handler) };
}

/// What the framework reports, sent from its queues to the main thread.
enum Event {
    Authorized(bool),
    Result {
        text: String,
        is_final: bool,
        /// The result ends an utterance, see [`Recognition::on_result`].
        ends_utterance: bool,
    },
    Error {
        domain: String,
        code: isize,
        message: String,
    },
}

/// Deliver framework events to the recognition until it is done.
async fn run(
    recognition: Rc<RefCell<Recognition>>,
    events: Receiver<Event>,
    cx: &mut gpui::AsyncApp,
) {
    while let Ok(event) = events.recv().await {
        let done = cx.update(|cx| recognition.borrow_mut().on_event(event, cx));
        if done {
            break;
        }
    }
}

struct Session {
    recognition: Rc<RefCell<Recognition>>,
    /// Dropping this stops delivering results.
    _task: Task<()>,
}

impl RecognitionSession for Session {
    fn push_audio(&mut self, samples: &[i16], _: &mut App) {
        self.recognition.borrow_mut().push_audio(samples);
    }

    fn finish(&mut self, _: &mut App) {
        self.recognition.borrow_mut().finish();
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        if let Some(task) = &self.recognition.borrow().task {
            // SAFETY: cancelling a valid task; it reports nothing we still read.
            unsafe { task.cancel() };
        }
    }
}

struct Recognition {
    recognizer: Retained<SFSpeechRecognizer>,
    request: Retained<SFSpeechAudioBufferRecognitionRequest>,
    format: Retained<AVAudioFormat>,
    /// `None` until access is granted.
    task: Option<Retained<SFSpeechRecognitionTask>>,
    sink: SpeechSink,
    events: Sender<Event>,
    /// Audio pushed before the task started.
    pending: Vec<i16>,
    finishing: bool,
    done: bool,
    /// The text of the last result that ended an utterance, until the next
    /// result shows whether the recognizer carries it on.
    utterance: Option<String>,
    /// The current hypothesis, as the framework reported it.
    hypothesis: String,
    /// The last character committed as a phrase, to join the next one.
    last_committed: Option<char>,
}

impl Recognition {
    fn new(
        recognizer: Retained<SFSpeechRecognizer>,
        sink: SpeechSink,
        events: Sender<Event>,
    ) -> Result<Self, SpeechError> {
        let format = AudioFormat::default();
        // 16-bit mono is also the request's native format, so appended audio
        // needs no conversion.
        // SAFETY: a mono PCM format, which the initializer supports.
        let format = unsafe {
            AVAudioFormat::initWithCommonFormat_sampleRate_channels_interleaved(
                AVAudioFormat::alloc(),
                AVAudioCommonFormat::PCMFormatInt16,
                format.sample_rate().into(),
                format.channels().into(),
                false,
            )
        }
        .ok_or_else(|| SpeechError::recognizer(anyhow!("cannot create the audio format")))?;

        // SAFETY: plain initializer and property setters on a fresh request.
        let request = unsafe {
            let request = SFSpeechAudioBufferRecognitionRequest::new();
            request.setShouldReportPartialResults(true);
            // Never send audio to Apple's servers.
            request.setRequiresOnDeviceRecognition(true);
            // Punctuation needs macOS 13.
            if request.respondsToSelector(sel!(setAddsPunctuation:)) {
                request.setAddsPunctuation(true);
            }
            request
        };

        Ok(Self {
            recognizer,
            request,
            format,
            task: None,
            sink,
            events,
            pending: Vec::new(),
            finishing: false,
            done: false,
            utterance: None,
            hypothesis: String::new(),
            last_committed: None,
        })
    }

    /// Start recognizing, once access is granted.
    fn begin(&mut self, cx: &mut App) {
        let events = self.events.clone();
        let handler = RcBlock::new(
            move |result: *mut SFSpeechRecognitionResult, error: *mut NSError| {
                // SAFETY: the framework passes nil or objects valid for the call.
                let (result, error) = unsafe { (result.as_ref(), error.as_ref()) };
                if let Some(result) = result {
                    // SAFETY: plain property reads on a valid result.
                    let event = unsafe {
                        Event::Result {
                            text: result.bestTranscription().formattedString().to_string(),
                            is_final: result.isFinal(),
                            ends_utterance: result.speechRecognitionMetadata().is_some(),
                        }
                    };
                    _ = events.try_send(event);
                }
                if let Some(error) = error {
                    _ = events.try_send(Event::Error {
                        domain: error.domain().to_string(),
                        code: error.code(),
                        message: error.localizedDescription().to_string(),
                    });
                }
            },
        );
        // SAFETY: the request is an audio buffer request and the block only
        // sends on a channel, so it may run on any queue.
        let task = unsafe {
            self.recognizer
                .recognitionTaskWithRequest_resultHandler(&self.request, &handler)
        };
        self.task = Some(task);

        let pending = std::mem::take(&mut self.pending);
        self.append(&pending);
        if self.finishing {
            // SAFETY: ending the audio of a valid request.
            unsafe { self.request.endAudio() };
        }
        self.sink.ready(cx);
    }

    fn push_audio(&mut self, samples: &[i16]) {
        if self.done || self.finishing {
            return;
        }
        if self.task.is_some() {
            self.append(samples);
        } else {
            self.pending.extend_from_slice(samples);
        }
    }

    fn finish(&mut self) {
        if self.finishing {
            return;
        }
        self.finishing = true;
        if self.task.is_some() {
            // SAFETY: ending the audio of a valid request.
            unsafe { self.request.endAudio() };
        }
    }

    fn append(&self, samples: &[i16]) {
        let Ok(frames) = u32::try_from(samples.len()) else {
            return;
        };
        if frames == 0 {
            return;
        }
        // SAFETY: `format` is PCM, so the initializer only fails for sizes
        // beyond `u32`.
        let Some(buffer) = (unsafe {
            AVAudioPCMBuffer::initWithPCMFormat_frameCapacity(
                AVAudioPCMBuffer::alloc(),
                &self.format,
                frames,
            )
        }) else {
            return;
        };
        // SAFETY: the format is 16-bit mono, so channel 0 holds `frames`
        // writable samples, and `frames` is within the capacity.
        unsafe {
            let channel = (*buffer.int16ChannelData()).as_ptr();
            std::ptr::copy_nonoverlapping(samples.as_ptr(), channel, samples.len());
            buffer.setFrameLength(frames);
            self.request.appendAudioPCMBuffer(&buffer);
        }
    }

    /// Handle one framework event; returns whether the recognition is done.
    fn on_event(&mut self, event: Event, cx: &mut App) -> bool {
        if self.done {
            return true;
        }
        match event {
            Event::Authorized(true) => self.begin(cx),
            Event::Authorized(false) => {
                self.sink.error(SpeechError::PermissionDenied, cx);
                self.done = true;
            }
            Event::Result {
                text,
                is_final,
                ends_utterance,
            } => self.on_result(text, is_final, ends_utterance, cx),
            Event::Error {
                domain,
                code,
                message,
            } => {
                if self.finishing && domain == NO_SPEECH_DOMAIN && code == NO_SPEECH_CODE {
                    // Stopping without (more) speech is a normal end.
                    let hypothesis = std::mem::take(&mut self.hypothesis);
                    self.commit(&hypothesis, cx);
                    self.sink.finish(cx);
                } else {
                    self.sink.error(
                        SpeechError::recognizer(anyhow!("{message} ({domain} {code})")),
                        cx,
                    );
                }
                self.done = true;
            }
        }
        self.done
    }

    /// Results carry the whole text of the request so far, except that some
    /// macOS versions start over after a pause: the result that ends an
    /// utterance has metadata, and the next one may no longer include its
    /// text. Commit that utterance as a phrase only once it is dropped.
    fn on_result(&mut self, text: String, is_final: bool, ends_utterance: bool, cx: &mut App) {
        if let Some(utterance) = self.utterance.take()
            && starts_over(&utterance, &text)
        {
            self.commit(&utterance, cx);
        }

        if is_final {
            self.hypothesis.clear();
            self.commit(&text, cx);
            self.sink.finish(cx);
            self.done = true;
            return;
        }

        if ends_utterance {
            self.utterance = Some(text.clone());
        }
        self.sink.hypothesis(self.joined(&text), cx);
        self.hypothesis = text;
    }

    fn commit(&mut self, text: &str, cx: &mut App) {
        if text.is_empty() {
            return;
        }
        let text = self.joined(text);
        self.last_committed = text.chars().next_back();
        self.sink.phrase(text, cx);
    }

    /// `text` with the separator it needs after the committed phrases.
    fn joined(&self, text: &str) -> String {
        match (self.last_committed, text.chars().next()) {
            (Some(before), Some(after)) if needs_space(before, after) => format!(" {text}"),
            _ => text.to_string(),
        }
    }
}

/// Whether `text`, the result after the one that ended `utterance`, starts a new
/// utterance instead of carrying `utterance` on.
///
/// A result that carries it on may still revise its words, punctuation or case
/// ("Hello word" becomes "Hello world, how"), so an exact prefix is too strict;
/// a result that starts over shares almost nothing with it. Less than half of
/// `utterance` in common means it started over.
fn starts_over(utterance: &str, text: &str) -> bool {
    let common = utterance
        .chars()
        .zip(text.chars())
        .take_while(|(a, b)| a == b)
        .count();
    common * 2 < utterance.chars().count()
}

/// Whether two phrases ending and starting with these characters need a space
/// between them.
fn needs_space(before: char, after: char) -> bool {
    !before.is_whitespace()
        && !after.is_whitespace()
        && !matches!(after, ',' | '.' | '?' | '!' | ';' | ':' | ')')
        && !is_unspaced_script(before)
        && !is_unspaced_script(after)
}

/// Characters of scripts written without spaces between words: Chinese,
/// Japanese and their punctuation.
fn is_unspaced_script(c: char) -> bool {
    matches!(c,
        '\u{3000}'..='\u{30FF}'
        | '\u{3400}'..='\u{4DBF}'
        | '\u{4E00}'..='\u{9FFF}'
        | '\u{F900}'..='\u{FAFF}'
        | '\u{FF00}'..='\u{FFEF}'
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_revised_utterance_carries_on() {
        assert!(!starts_over("Hello word", "Hello world, how"));
        assert!(!starts_over("Hello world", "Hello world. How are you"));
        assert!(!starts_over("今天天气", "今天天气很好"));
    }

    #[test]
    fn a_reset_result_starts_over() {
        assert!(starts_over("Hello world.", "How"));
        assert!(starts_over("今天天气很好。", "明天"));
    }

    #[test]
    fn phrases_are_spaced_by_script() {
        assert!(needs_space('.', 'H'));
        assert!(!needs_space('d', ','));
        assert!(!needs_space('。', '明'));
        assert!(!needs_space('好', 'O'));
    }
}
