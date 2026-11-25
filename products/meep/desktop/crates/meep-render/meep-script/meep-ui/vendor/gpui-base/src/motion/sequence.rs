use gpui::{App, ElementId, Window};

use super::{Instant, Interpolate, MotionStatus, Transition, TransitionId};

/// One target of a [`Sequence`] and the transition that reaches it.
#[derive(Clone)]
pub struct SequenceStep<T> {
    target: T,
    transition: Transition,
}

impl<T> SequenceStep<T> {
    pub fn new(target: T, transition: Transition) -> Self {
        Self { target, transition }
    }

    pub fn target(&self) -> &T {
        &self.target
    }

    pub fn transition(&self) -> &Transition {
        &self.transition
    }
}

/// What a [`Sequence`] reports for the current frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SequenceSample<T> {
    value: T,
    step: usize,
    status: MotionStatus,
}

impl<T> SequenceSample<T> {
    /// The interpolated value for this frame.
    pub fn value(&self) -> &T {
        &self.value
    }

    pub fn into_value(self) -> T {
        self.value
    }

    /// The index of the step being played. A finished sequence reports its
    /// last step; an empty one reports `0`.
    pub fn step(&self) -> usize {
        self.step
    }

    /// The status of the step being played. `Finished` is reported only once
    /// the last step has completed: a step that hands over to the next one
    /// reports that next step's `Delayed` or `Running` instead.
    pub fn status(&self) -> MotionStatus {
        self.status
    }

    pub fn is_finished(&self) -> bool {
        self.status == MotionStatus::Finished
    }

    fn is_active(&self) -> bool {
        matches!(self.status, MotionStatus::Delayed | MotionStatus::Running)
    }
}

/// A chain of value transitions, each starting when the previous one ends.
///
/// A sequence begins at `from` on the frame it is first sampled and runs its
/// steps in order. A step ends at an absolute instant — its start plus its
/// delay and duration — and the next step starts at that same instant, so a
/// frame that lands past a boundary samples the next step where it would have
/// been rather than starting it late. Steps of zero duration complete within
/// the frame that reaches them.
///
/// State is keyed by `id` exactly as [`super::transition`] keys its own, and
/// the sequence plays once per key. Re-rendering with the same ID continues
/// it; to replay, include an application-owned generation in the ID, for
/// example `("toast-enter", generation)`.
///
/// A step's target and transition are captured when the step starts. Handing
/// the step being played a different target restarts the sequence: it begins
/// again at its first step from the value sampled at that instant, as a
/// retargeted transition continues from its current value. Steps other than
/// the one being played are read when the sequence reaches them and are not
/// compared, so a change to an earlier step has no effect on its own. A
/// sequence does not reverse; play a second sequence back to the start under
/// its own key when that is wanted.
///
/// Under reduced motion the sequence adopts its last target at once, reports
/// `Finished`, and requests no frame.
#[derive(Clone)]
pub struct Sequence<T> {
    id: TransitionId,
    from: T,
    steps: Vec<SequenceStep<T>>,
}

impl<T> Sequence<T>
where
    T: Interpolate + PartialEq + 'static,
{
    /// Starts a sequence at `from`, with no steps yet.
    pub fn new(id: impl Into<TransitionId>, from: T) -> Self {
        Self {
            id: id.into(),
            from,
            steps: Vec::new(),
        }
    }

    /// Appends a step that transitions to `target` once the previous step ends.
    pub fn with_step(mut self, target: T, transition: Transition) -> Self {
        self.steps.push(SequenceStep::new(target, transition));
        self
    }

    /// Appends steps built elsewhere, in order.
    pub fn with_steps(mut self, steps: impl IntoIterator<Item = SequenceStep<T>>) -> Self {
        self.steps.extend(steps);
        self
    }

    pub fn from(&self) -> &T {
        &self.from
    }

    pub fn steps(&self) -> &[SequenceStep<T>] {
        &self.steps
    }

    /// Samples the sequence and requests a frame while a step is active.
    pub fn sample(self, window: &mut Window, cx: &mut App) -> SequenceSample<T> {
        let Some(last) = self.steps.last() else {
            return SequenceSample {
                value: self.from,
                step: 0,
                status: MotionStatus::Idle,
            };
        };
        let last_step = self.steps.len() - 1;

        let id = ElementId::NamedChild(self.id.0.into(), "__sequence".into());
        let now = cx.background_executor().now();
        let state = window.use_keyed_state(id, cx, |_, _| {
            SequenceState::start(0, self.from.clone(), &self.steps, now)
        });

        if cx.reduce_motion() {
            let settled = state.read(cx);
            if settled.step != last_step || settled.from != last.target {
                state.update(cx, |state, _| {
                    *state = SequenceState::start(last_step, last.target.clone(), &self.steps, now);
                });
            }
            return SequenceSample {
                value: last.target.clone(),
                step: last_step,
                status: MotionStatus::Finished,
            };
        }

        let snapshot = state.read(cx);
        let (progress, status) = snapshot.progress(now);
        let retargeted =
            snapshot.step > last_step || self.steps[snapshot.step].target != snapshot.target;
        let handing_over = status == MotionStatus::Finished && snapshot.step < last_step;

        if !retargeted && !handing_over {
            let sample = SequenceSample {
                value: snapshot.value(progress),
                step: snapshot.step,
                status,
            };
            if sample.is_active() {
                window.request_animation_frame();
            }
            return sample;
        }

        // Only a boundary or a restart writes state. A restart begins the new
        // sequence's first step from the value the old one had reached, which
        // is where the eye is. A hand-over starts the next step at the instant
        // the finished one ended, not at `now`, so a frame that lands past
        // the boundary does not start the step late.
        let mut next = if retargeted {
            SequenceState::start(0, snapshot.value(progress), &self.steps, now)
        } else {
            snapshot.hand_over(&self.steps)
        };
        let (value, status) = loop {
            let (progress, status) = next.progress(now);
            if status == MotionStatus::Finished && next.step < last_step {
                next = next.hand_over(&self.steps);
                continue;
            }
            break (next.value(progress), status);
        };
        let sample = SequenceSample {
            value,
            step: next.step,
            status,
        };
        state.update(cx, |state, _| *state = next);
        if sample.is_active() {
            window.request_animation_frame();
        }
        sample
    }
}

/// The step a sequence is playing, complete enough to sample without the
/// caller's steps: those are only needed to hand over to the next one.
#[derive(Clone)]
struct SequenceState<T> {
    step: usize,
    from: T,
    target: T,
    transition: Transition,
    started_at: Instant,
}

impl<T: Interpolate> SequenceState<T> {
    fn start(step: usize, from: T, steps: &[SequenceStep<T>], started_at: Instant) -> Self {
        Self {
            step,
            from,
            target: steps[step].target.clone(),
            transition: steps[step].transition.clone(),
            started_at,
        }
    }

    fn progress(&self, now: Instant) -> (f32, MotionStatus) {
        self.transition.progress(
            now.saturating_duration_since(self.started_at),
            self.transition.duration,
        )
    }

    fn value(&self, progress: f32) -> T {
        self.from
            .interpolate(&self.target, self.transition.sample(progress))
    }

    /// Starts the next step where this finished one ended. The caller has
    /// checked that this step is finished and is not the last, so the end lies
    /// no later than `now` and the addition cannot overflow the clock.
    fn hand_over(&self, steps: &[SequenceStep<T>]) -> Self {
        Self::start(
            self.step + 1,
            self.target.clone(),
            steps,
            self.started_at + self.transition.finishes_after(),
        )
    }
}
