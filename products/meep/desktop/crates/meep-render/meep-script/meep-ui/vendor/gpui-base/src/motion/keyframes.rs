use std::sync::Arc;

use super::{Easing, Interpolate};

#[derive(Clone, Debug)]
pub struct Keyframe<T> {
    pub offset: f32,
    pub value: T,
    pub easing: Easing,
}

impl<T> Keyframe<T> {
    pub fn new(offset: f32, value: T) -> Self {
        Self {
            offset,
            value,
            easing: Easing::Linear,
        }
    }

    pub fn ease(mut self, easing: Easing) -> Self {
        self.easing = easing;
        self
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KeyframeError {
    TooFewFrames,
    OffsetNotFinite,
    OffsetOutOfRange,
    OffsetsNotMonotonic,
    MissingEndpoint,
}

#[derive(Clone, Debug)]
pub struct Keyframes<T> {
    frames: Arc<[Keyframe<T>]>,
}

impl<T: Interpolate> Keyframes<T> {
    pub fn try_new(frames: impl IntoIterator<Item = Keyframe<T>>) -> Result<Self, KeyframeError> {
        let frames: Vec<_> = frames.into_iter().collect();
        if frames.len() < 2 {
            return Err(KeyframeError::TooFewFrames);
        }
        if frames.iter().any(|frame| !frame.offset.is_finite()) {
            return Err(KeyframeError::OffsetNotFinite);
        }
        if frames
            .iter()
            .any(|frame| !(0.0..=1.0).contains(&frame.offset))
        {
            return Err(KeyframeError::OffsetOutOfRange);
        }
        if frames
            .windows(2)
            .any(|pair| pair[0].offset > pair[1].offset)
        {
            return Err(KeyframeError::OffsetsNotMonotonic);
        }
        if frames.first().unwrap().offset != 0.0 || frames.last().unwrap().offset != 1.0 {
            return Err(KeyframeError::MissingEndpoint);
        }
        Ok(Self {
            frames: frames.into(),
        })
    }

    #[inline]
    pub fn sample(&self, progress: f32) -> T {
        let progress = progress.clamp(0.0, 1.0);
        let upper = self
            .frames
            .partition_point(|frame| frame.offset <= progress);
        if upper == 0 {
            return self.frames[0].value.clone();
        }
        if upper == self.frames.len() {
            return self.frames[self.frames.len() - 1].value.clone();
        }
        let from = &self.frames[upper - 1];
        let to = &self.frames[upper];
        if from.offset == to.offset {
            return to.value.clone();
        }
        let segment = (progress - from.offset) / (to.offset - from.offset);
        from.value
            .interpolate(&to.value, from.easing.sample(segment))
    }

    pub fn len(&self) -> usize {
        self.frames.len()
    }

    pub fn is_empty(&self) -> bool {
        self.frames.is_empty()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DiscreteError {
    InvalidSwitchPoint,
}

#[derive(Clone, Debug)]
pub struct Discrete<T> {
    from: T,
    to: T,
    switch_at: f32,
}

impl<T> Discrete<T> {
    pub fn new(from: T, to: T) -> Self {
        Self {
            from,
            to,
            switch_at: 0.5,
        }
    }

    pub fn switch_at(mut self, progress: f32) -> Result<Self, DiscreteError> {
        if !progress.is_finite() || !(0.0..=1.0).contains(&progress) {
            return Err(DiscreteError::InvalidSwitchPoint);
        }
        self.switch_at = progress;
        Ok(self)
    }
}

impl<T: Clone> Discrete<T> {
    #[inline]
    pub fn sample(&self, progress: f32) -> T {
        if progress < self.switch_at {
            self.from.clone()
        } else {
            self.to.clone()
        }
    }
}
