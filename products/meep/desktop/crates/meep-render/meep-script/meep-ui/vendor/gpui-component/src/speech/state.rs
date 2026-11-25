use std::{cell::OnceCell, rc::Rc, time::Duration};

use gpui::{App, Context, EventEmitter, Pixels, SharedString, Subscription, Task, WeakEntity};

use super::{
    AudioInput, AudioSink, RecognitionSession, SpeechError, SpeechRecognizer, SpeechSink,
    level::LevelMeter, surface::LiquidSurfaces,
};

/// Default time [`SpeechState::stop`] waits for the final result.
const DEFAULT_STOP_TIMEOUT: Duration = Duration::from_secs(3);

/// Where a [`SpeechState`] is in its session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SpeechStatus {
    /// No session is running.
    #[default]
    Idle,
    /// Audio is being captured while the recognizer connects.
    Connecting,
    /// Audio is being captured and recognized.
    Recording,
    /// Capture stopped; waiting for the recognizer's final result.
    Stopping,
}

impl SpeechStatus {
    /// Whether a session is running.
    pub fn is_active(self) -> bool {
        self != Self::Idle
    }

    /// Whether the microphone is capturing.
    pub fn is_capturing(self) -> bool {
        matches!(self, Self::Connecting | Self::Recording)
    }
}

/// Events emitted by [`SpeechState`].
#[derive(Debug, Clone)]
pub enum SpeechEvent {
    /// A session started and audio is being captured.
    Started,
    /// The transcript changed: every committed phrase followed by the current
    /// hypothesis. Later events supersede earlier ones.
    Partial(SharedString),
    /// The session ended normally with this transcript, possibly empty.
    Final(SharedString),
    /// The session was cancelled and its transcript discarded.
    Cancelled,
    /// The session failed and ended.
    Error(SpeechError),
}

struct Session {
    id: usize,
    /// Dropping this stops capture.
    capture: Option<Subscription>,
    recognition: Box<dyn RecognitionSession>,
    _stop_timeout: Option<Task<()>>,
}

/// The state of a speech input: captures audio from an [`AudioInput`], feeds it
/// to a [`SpeechRecognizer`] and tracks the transcript.
///
/// Render it with [`SpeechButton`](super::SpeechButton) and
/// [`SpeechWaveform`](super::SpeechWaveform), and subscribe to [`SpeechEvent`]
/// to receive the text.
///
/// The recognizer is, in order: the one passed to [`Self::recognizer`]; else
/// the platform's `SystemRecognizer`, unless
/// [`Self::system_fallback`] turned it off; else none, and the state is not
/// available. The input defaults to the `Microphone`.
/// Both defaults need the `speech` feature.
pub struct SpeechState {
    recognizer: Option<Rc<dyn SpeechRecognizer>>,
    input: Option<Rc<dyn AudioInput>>,
    system_fallback: bool,
    system_recognizer: OnceCell<Option<Rc<dyn SpeechRecognizer>>>,
    stop_timeout: Duration,
    status: SpeechStatus,
    session: Option<Session>,
    next_session: usize,
    committed: String,
    hypothesis: SharedString,
    meter: LevelMeter,
    surfaces: LiquidSurfaces,
}

impl EventEmitter<SpeechEvent> for SpeechState {}

impl SpeechState {
    /// Create a speech state with the default recognizer and input.
    pub fn new(_: &mut Context<Self>) -> Self {
        Self {
            recognizer: None,
            input: super::default_input(),
            system_fallback: true,
            system_recognizer: OnceCell::new(),
            stop_timeout: DEFAULT_STOP_TIMEOUT,
            status: SpeechStatus::Idle,
            session: None,
            next_session: 0,
            committed: String::new(),
            hypothesis: SharedString::default(),
            meter: LevelMeter::new(),
            surfaces: LiquidSurfaces::default(),
        }
    }

    /// Recognize speech with `recognizer` instead of the system's.
    pub fn recognizer(mut self, recognizer: impl SpeechRecognizer) -> Self {
        self.recognizer = Some(Rc::new(recognizer));
        self
    }

    /// Capture audio from `input` instead of the microphone.
    pub fn input(mut self, input: impl AudioInput) -> Self {
        self.input = Some(Rc::new(input));
        self
    }

    /// Whether to fall back to the platform's recognizer when no
    /// [`Self::recognizer`] is set, default `true`.
    ///
    /// On Windows the system recognizer dictates through Microsoft's online
    /// service; turn this off when audio must not leave the application.
    pub fn system_fallback(mut self, system_fallback: bool) -> Self {
        self.system_fallback = system_fallback;
        self
    }

    /// Set how long [`Self::stop`] waits for the recognizer's final result
    /// before ending the session with the transcript so far, default 3 seconds.
    pub fn stop_timeout(mut self, timeout: Duration) -> Self {
        self.stop_timeout = timeout;
        self
    }

    /// Whether a recognizer and an input are configured, so that speech input
    /// can work on this platform at all.
    pub fn has_recognizer(&self) -> bool {
        self.input.is_some() && self.active_recognizer().is_some()
    }

    /// Whether a session can start now: [`Self::has_recognizer`] and the
    /// recognizer reports itself available.
    pub fn is_available(&self, cx: &App) -> bool {
        self.input.is_some()
            && self
                .active_recognizer()
                .is_some_and(|recognizer| recognizer.is_available(cx))
    }

    /// Where the state is in its session.
    pub fn status(&self) -> SpeechStatus {
        self.status
    }

    /// The transcript of the current or last session: every committed phrase
    /// followed by the current hypothesis.
    pub fn transcript(&self) -> SharedString {
        if self.hypothesis.is_empty() {
            self.committed.clone().into()
        } else {
            format!("{}{}", self.committed, self.hypothesis).into()
        }
    }

    /// Recent input levels in `0.0..=1.0`, oldest first, one per 80 ms of
    /// audio. Peaks rise at once and fall back smoothly; background noise reads
    /// as `0.0`.
    pub fn levels(&self) -> impl ExactSizeIterator<Item = f32> + '_ {
        self.meter.levels()
    }

    /// Levels recorded this session, including those dropped from
    /// [`Self::levels`]: with [`Self::level_lead_at`], a clock that advances
    /// with the audio.
    pub(super) fn levels_recorded(&self) -> u64 {
        self.meter.recorded()
    }

    /// How far past the waveform's trailing edge the newest level sits at
    /// `now`, in levels; see `LevelMeter::lead_at`.
    pub(super) fn level_lead_at(&self, now: instant::Instant) -> Option<f32> {
        self.meter.lead_at(now)
    }

    /// Advance the water surface that a liquid waveform `width` wide draws to
    /// `now`. The surface is simulated rather than derived from the levels, so
    /// it lives here, with the levels that drive it, and the waveform advances
    /// it once per frame; nothing else reads it, so this does not notify.
    pub(super) fn advance_surface(&mut self, now: instant::Instant, width: Pixels) {
        self.surfaces.advance(now, width.as_f32(), &self.meter);
    }

    /// The heights of the water surface `width` wide; see
    /// `LiquidSurface::heights`.
    pub(super) fn surface_heights(&self, width: Pixels) -> &[f32] {
        self.surfaces.heights(width.as_f32())
    }

    /// Start a session. Does nothing while one is running.
    ///
    /// When the recognizer or the input fails to start, emits
    /// [`SpeechEvent::Error`] and stays idle.
    pub fn start(&mut self, cx: &mut Context<Self>) {
        if self.status.is_active() {
            return;
        }

        let (Some(recognizer), Some(input)) = (self.active_recognizer(), self.input.clone()) else {
            cx.emit(SpeechEvent::Error(SpeechError::Unsupported));
            return;
        };

        self.next_session += 1;
        let id = self.next_session;
        let state = cx.weak_entity();
        let sink = SpeechSink {
            state: state.clone(),
            session: id,
        };
        let recognition = match recognizer.start(sink, cx) {
            Ok(recognition) => recognition,
            Err(error) => {
                cx.emit(SpeechEvent::Error(error));
                return;
            }
        };

        let format = recognizer.audio_format();
        let sink = AudioSink { state, session: id };
        let capture = match input.start(format, sink, cx) {
            Ok(capture) => capture,
            Err(error) => {
                cx.emit(SpeechEvent::Error(error));
                return;
            }
        };

        self.status = SpeechStatus::Connecting;
        self.committed.clear();
        self.hypothesis = SharedString::default();
        self.meter.reset(format.sample_rate(), format.channels());
        self.surfaces = LiquidSurfaces::default();
        self.session = Some(Session {
            id,
            capture: Some(capture),
            recognition,
            _stop_timeout: None,
        });
        cx.emit(SpeechEvent::Started);
        cx.notify();
    }

    /// Stop capturing and wait for the final result, which arrives as
    /// [`SpeechEvent::Final`].
    pub fn stop(&mut self, cx: &mut Context<Self>) {
        if !self.status.is_capturing() {
            return;
        }
        let Some(session) = self.session.as_mut() else {
            return;
        };

        session.capture = None;
        session.recognition.finish(cx);

        let id = session.id;
        let timeout = self.stop_timeout;
        session._stop_timeout = Some(cx.spawn(async move |this, cx| {
            cx.background_executor().timer(timeout).await;
            _ = this.update(cx, |this, cx| {
                if this.is_session(id) {
                    this.end(SpeechEvent::Final(this.transcript()), cx);
                }
            });
        }));

        self.status = SpeechStatus::Stopping;
        cx.notify();
    }

    /// End the session at once and discard its transcript.
    pub fn cancel(&mut self, cx: &mut Context<Self>) {
        if !self.status.is_active() {
            return;
        }
        self.committed.clear();
        self.hypothesis = SharedString::default();
        self.end(SpeechEvent::Cancelled, cx);
    }

    /// Start a session when idle, otherwise stop the running one.
    pub fn toggle(&mut self, cx: &mut Context<Self>) {
        if self.status.is_active() {
            self.stop(cx);
        } else {
            self.start(cx);
        }
    }

    fn active_recognizer(&self) -> Option<Rc<dyn SpeechRecognizer>> {
        if let Some(recognizer) = &self.recognizer {
            return Some(recognizer.clone());
        }
        if !self.system_fallback {
            return None;
        }
        self.system_recognizer
            .get_or_init(super::system_recognizer)
            .clone()
    }

    pub(super) fn is_session(&self, id: usize) -> bool {
        self.session
            .as_ref()
            .is_some_and(|session| session.id == id)
    }

    pub(super) fn on_ready(&mut self, cx: &mut Context<Self>) {
        if self.status == SpeechStatus::Connecting {
            self.status = SpeechStatus::Recording;
            cx.notify();
        }
    }

    pub(super) fn on_audio(&mut self, samples: &[i16], cx: &mut Context<Self>) {
        if !self.status.is_capturing() {
            return;
        }
        if let Some(session) = self.session.as_mut() {
            session.recognition.push_audio(samples, cx);
        }
        // Redraw once per new level, not per push: levels are what the
        // waveform shows.
        if self.meter.push(samples) {
            cx.notify();
        }
    }

    pub(super) fn on_hypothesis(&mut self, text: SharedString, cx: &mut Context<Self>) {
        self.hypothesis = text;
        cx.emit(SpeechEvent::Partial(self.transcript()));
        cx.notify();
    }

    pub(super) fn on_phrase(&mut self, text: SharedString, cx: &mut Context<Self>) {
        self.committed.push_str(&text);
        self.hypothesis = SharedString::default();
        cx.emit(SpeechEvent::Partial(self.transcript()));
        cx.notify();
    }

    pub(super) fn on_finish(&mut self, cx: &mut Context<Self>) {
        self.end(SpeechEvent::Final(self.transcript()), cx);
    }

    pub(super) fn on_error(&mut self, error: SpeechError, cx: &mut Context<Self>) {
        self.end(SpeechEvent::Error(error), cx);
    }

    /// Tear the session down, capture first, and report how it ended.
    fn end(&mut self, event: SpeechEvent, cx: &mut Context<Self>) {
        if let Some(mut session) = self.session.take() {
            session.capture = None;
        }
        self.status = SpeechStatus::Idle;
        self.meter = LevelMeter::new();
        self.surfaces = LiquidSurfaces::default();
        cx.emit(event);
        cx.notify();
    }
}

/// Apply `f` to `state` after the current update, if `session` is still its
/// running session. Sinks go through this so that a recognizer or an input may
/// report from anywhere, including from inside a call the state made.
pub(super) fn defer_session_update(
    state: WeakEntity<SpeechState>,
    session: usize,
    cx: &mut App,
    f: impl FnOnce(&mut SpeechState, &mut Context<SpeechState>) + 'static,
) {
    cx.defer(move |cx| {
        _ = state.update(cx, |state, cx| {
            if state.is_session(session) {
                f(state, cx);
            }
        });
    });
}

#[cfg(test)]
mod tests {
    use std::{cell::RefCell, rc::Rc, time::Duration};

    use gpui::{App, AppContext as _, Entity, Subscription, TestAppContext};

    use super::*;
    use crate::speech::{AudioFormat, AudioInput, AudioSink, RecognitionSession, SpeechSink};

    #[derive(Default)]
    struct Recorded {
        sink: Option<SpeechSink>,
        samples: usize,
        finished: bool,
        dropped: bool,
    }

    #[derive(Clone, Default)]
    struct FakeRecognizer {
        recorded: Rc<RefCell<Recorded>>,
        fail_to_start: bool,
    }

    struct FakeSession(Rc<RefCell<Recorded>>);

    impl SpeechRecognizer for FakeRecognizer {
        fn start(
            &self,
            sink: SpeechSink,
            _: &mut App,
        ) -> Result<Box<dyn RecognitionSession>, SpeechError> {
            if self.fail_to_start {
                return Err(SpeechError::recognizer(anyhow::anyhow!("offline")));
            }
            *self.recorded.borrow_mut() = Recorded {
                sink: Some(sink),
                ..Default::default()
            };
            Ok(Box::new(FakeSession(self.recorded.clone())))
        }
    }

    impl RecognitionSession for FakeSession {
        fn push_audio(&mut self, samples: &[i16], _: &mut App) {
            self.0.borrow_mut().samples += samples.len();
        }

        fn finish(&mut self, _: &mut App) {
            self.0.borrow_mut().finished = true;
        }
    }

    impl Drop for FakeSession {
        fn drop(&mut self) {
            self.0.borrow_mut().dropped = true;
        }
    }

    #[derive(Clone, Default)]
    struct FakeInput {
        sink: Rc<RefCell<Option<AudioSink>>>,
        capturing: Rc<RefCell<bool>>,
    }

    impl AudioInput for FakeInput {
        fn start(
            &self,
            _: AudioFormat,
            sink: AudioSink,
            _: &mut App,
        ) -> Result<Subscription, SpeechError> {
            *self.sink.borrow_mut() = Some(sink);
            *self.capturing.borrow_mut() = true;
            let capturing = self.capturing.clone();
            Ok(Subscription::new(move || *capturing.borrow_mut() = false))
        }
    }

    struct Fixture {
        state: Entity<SpeechState>,
        recognizer: FakeRecognizer,
        input: FakeInput,
        events: Rc<RefCell<Vec<SpeechEvent>>>,
        _subscription: Subscription,
    }

    impl Fixture {
        fn new(recognizer: FakeRecognizer, cx: &mut TestAppContext) -> Self {
            let input = FakeInput::default();
            let state = cx.update(|cx| {
                cx.new(|cx| {
                    SpeechState::new(cx)
                        .recognizer(recognizer.clone())
                        .input(input.clone())
                        .stop_timeout(Duration::from_secs(1))
                })
            });
            let events = Rc::new(RefCell::new(Vec::new()));
            let _subscription = cx.update(|cx| {
                let events = events.clone();
                cx.subscribe(&state, move |_, event: &SpeechEvent, _| {
                    events.borrow_mut().push(event.clone());
                })
            });
            Self {
                state,
                recognizer,
                input,
                events,
                _subscription,
            }
        }

        fn sink(&self) -> SpeechSink {
            self.recognizer.recorded.borrow().sink.clone().unwrap()
        }

        fn audio(&self) -> AudioSink {
            self.input.sink.borrow().clone().unwrap()
        }

        fn status(&self, cx: &mut TestAppContext) -> SpeechStatus {
            cx.read(|cx| self.state.read(cx).status())
        }

        /// Events so far, as short labels.
        fn take_events(&self) -> Vec<String> {
            self.events
                .borrow_mut()
                .drain(..)
                .map(|event| match event {
                    SpeechEvent::Started => "started".into(),
                    SpeechEvent::Partial(text) => format!("partial:{text}"),
                    SpeechEvent::Final(text) => format!("final:{text}"),
                    SpeechEvent::Cancelled => "cancelled".into(),
                    SpeechEvent::Error(error) => format!("error:{error}"),
                })
                .collect()
        }
    }

    #[gpui::test]
    fn session_runs_from_start_to_final(cx: &mut TestAppContext) {
        let f = Fixture::new(FakeRecognizer::default(), cx);

        f.state.update(cx, |state, cx| state.start(cx));
        assert_eq!(f.status(cx), SpeechStatus::Connecting);
        assert!(*f.input.capturing.borrow());

        cx.update(|cx| {
            f.sink().ready(cx);
            // Two levels' worth: 80 ms is 1 280 samples at 16 kHz.
            f.audio().push(vec![i16::MAX / 2; 2_560], cx);
            f.sink().hypothesis("hello", cx);
        });
        cx.run_until_parked();
        assert_eq!(f.status(cx), SpeechStatus::Recording);
        assert_eq!(f.recognizer.recorded.borrow().samples, 2_560);
        cx.read(|cx| {
            let state = f.state.read(cx);
            assert_eq!(state.levels().len(), 2);
            assert!(state.levels().next().unwrap() > 0.5);
        });

        cx.update(|cx| {
            f.sink().phrase("Hello.", cx);
            f.sink().hypothesis(" How", cx);
        });
        cx.run_until_parked();
        assert_eq!(
            cx.read(|cx| f.state.read(cx).transcript()),
            SharedString::from("Hello. How")
        );

        f.state.update(cx, |state, cx| state.stop(cx));
        assert_eq!(f.status(cx), SpeechStatus::Stopping);
        assert!(!*f.input.capturing.borrow(), "stop releases the microphone");
        assert!(f.recognizer.recorded.borrow().finished);

        cx.update(|cx| {
            f.sink().phrase(" How are you?", cx);
            f.sink().finish(cx);
        });
        cx.run_until_parked();
        assert_eq!(f.status(cx), SpeechStatus::Idle);
        assert!(f.recognizer.recorded.borrow().dropped);
        assert_eq!(
            f.take_events(),
            [
                "started",
                "partial:hello",
                "partial:Hello.",
                "partial:Hello. How",
                "partial:Hello. How are you?",
                "final:Hello. How are you?",
            ]
        );
    }

    #[gpui::test]
    fn stop_ends_with_the_transcript_so_far_after_the_timeout(cx: &mut TestAppContext) {
        let f = Fixture::new(FakeRecognizer::default(), cx);
        f.state.update(cx, |state, cx| state.start(cx));
        cx.update(|cx| f.sink().hypothesis("half a sentence", cx));
        cx.run_until_parked();

        f.state.update(cx, |state, cx| state.stop(cx));
        cx.executor().advance_clock(Duration::from_millis(900));
        assert_eq!(f.status(cx), SpeechStatus::Stopping);
        cx.executor().advance_clock(Duration::from_millis(200));
        cx.run_until_parked();

        assert_eq!(f.status(cx), SpeechStatus::Idle);
        assert_eq!(f.take_events().last().unwrap(), "final:half a sentence");
    }

    #[gpui::test]
    fn cancel_discards_the_session_and_ignores_late_results(cx: &mut TestAppContext) {
        let f = Fixture::new(FakeRecognizer::default(), cx);
        f.state.update(cx, |state, cx| state.start(cx));
        let stale = f.sink();
        cx.update(|cx| stale.phrase("draft", cx));
        cx.run_until_parked();

        f.state.update(cx, |state, cx| state.cancel(cx));
        assert_eq!(f.status(cx), SpeechStatus::Idle);
        assert!(!*f.input.capturing.borrow());
        assert!(f.recognizer.recorded.borrow().dropped);

        // A new session must not pick up the old session's results.
        f.state.update(cx, |state, cx| state.start(cx));
        cx.update(|cx| {
            stale.phrase("late", cx);
            stale.finish(cx);
        });
        cx.run_until_parked();

        assert_eq!(f.status(cx), SpeechStatus::Connecting);
        assert_eq!(
            cx.read(|cx| f.state.read(cx).transcript()),
            SharedString::default()
        );
        assert_eq!(
            f.take_events(),
            ["started", "partial:draft", "cancelled", "started"]
        );
    }

    #[gpui::test]
    fn input_error_ends_the_session(cx: &mut TestAppContext) {
        let f = Fixture::new(FakeRecognizer::default(), cx);
        f.state.update(cx, |state, cx| state.start(cx));
        cx.update(|cx| f.audio().error(SpeechError::NoInputDevice, cx));
        cx.run_until_parked();

        assert_eq!(f.status(cx), SpeechStatus::Idle);
        assert!(f.recognizer.recorded.borrow().dropped);
        assert_eq!(
            f.take_events(),
            ["started", "error:no audio input device is available"]
        );
    }

    #[gpui::test]
    fn recognizer_that_fails_to_start_leaves_the_state_idle(cx: &mut TestAppContext) {
        let f = Fixture::new(
            FakeRecognizer {
                fail_to_start: true,
                ..Default::default()
            },
            cx,
        );
        f.state.update(cx, |state, cx| state.start(cx));

        assert_eq!(f.status(cx), SpeechStatus::Idle);
        assert!(!*f.input.capturing.borrow(), "the input never starts");
        assert_eq!(
            f.take_events(),
            ["error:speech recognition failed: offline"]
        );
    }

    #[gpui::test]
    fn state_without_a_recognizer_is_unsupported(cx: &mut TestAppContext) {
        let state = cx.update(|cx| {
            cx.new(|cx| {
                SpeechState::new(cx)
                    .input(FakeInput::default())
                    .system_fallback(false)
            })
        });
        cx.read(|cx| {
            assert!(!state.read(cx).has_recognizer());
            assert!(!state.read(cx).is_available(cx));
        });
    }
}
