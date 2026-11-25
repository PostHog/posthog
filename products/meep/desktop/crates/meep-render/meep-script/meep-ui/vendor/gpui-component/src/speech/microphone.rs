use std::f32::consts::TAU;

use anyhow::anyhow;
use cpal::{
    FromSample, Sample, SampleFormat, SizedSample, StreamConfig,
    traits::{DeviceTrait as _, HostTrait as _, StreamTrait as _},
};
use gpui::{App, Subscription};
use smol::channel::{Sender, unbounded};

use super::{AudioFormat, AudioInput, AudioSink, SpeechError};

/// The default audio input device, captured through the platform's audio API
/// (Core Audio, WASAPI or ALSA).
///
/// The device's own format is mixed down to mono and resampled to the format
/// the recognizer asks for.
///
/// On macOS the application's `Info.plist` must describe why it uses the
/// microphone (`NSMicrophoneUsageDescription`), or the system refuses access
/// without asking.
#[derive(Debug, Default, Clone)]
pub struct Microphone {
    _private: (),
}

impl AudioInput for Microphone {
    fn start(
        &self,
        format: AudioFormat,
        sink: AudioSink,
        cx: &mut App,
    ) -> Result<Subscription, SpeechError> {
        #[cfg(target_os = "macos")]
        if super::system::macos::is_microphone_denied() {
            return Err(SpeechError::PermissionDenied);
        }

        let device = cpal::default_host()
            .default_input_device()
            .ok_or(SpeechError::NoInputDevice)?;
        let supported = device.default_input_config().map_err(SpeechError::input)?;
        let sample_format = supported.sample_format();
        let config: StreamConfig = supported.into();
        let source_rate = config.sample_rate.0;

        let (tx, rx) = unbounded();
        let stream = match sample_format {
            SampleFormat::F32 => build_stream::<f32>(&device, &config, tx),
            SampleFormat::I16 => build_stream::<i16>(&device, &config, tx),
            SampleFormat::U16 => build_stream::<u16>(&device, &config, tx),
            SampleFormat::I32 => build_stream::<i32>(&device, &config, tx),
            other => {
                return Err(SpeechError::input(anyhow!(
                    "unsupported sample format {other}"
                )));
            }
        }?;
        stream.play().map_err(SpeechError::input)?;

        let task = cx.spawn(async move |cx| {
            let mut converter = Converter::new(source_rate, format);
            let mut mono = Vec::new();
            while let Ok(first) = rx.recv().await {
                // The device delivers ~10 ms chunks; forward what has queued up
                // as one push so the state updates once per batch.
                let mut error = None;
                for capture in
                    std::iter::once(first).chain(std::iter::from_fn(|| rx.try_recv().ok()))
                {
                    match capture {
                        Capture::Samples(samples) => mono.extend_from_slice(&samples),
                        Capture::Error(message) => error = Some(message),
                    }
                }

                let samples = converter.convert(&mono);
                mono.clear();
                cx.update(|cx| {
                    if !samples.is_empty() {
                        sink.push(samples, cx);
                    }
                    if let Some(message) = error.take() {
                        sink.error(SpeechError::input(anyhow!(message)), cx);
                    }
                });
            }
        });

        Ok(Subscription::new(move || {
            drop(stream);
            drop(task);
        }))
    }
}

enum Capture {
    Samples(Vec<f32>),
    Error(String),
}

/// Open an input stream that sends each callback's frames, mixed down to mono,
/// through `tx`. Runs on the audio thread, so it only converts and sends.
fn build_stream<T>(
    device: &cpal::Device,
    config: &StreamConfig,
    tx: Sender<Capture>,
) -> Result<cpal::Stream, SpeechError>
where
    T: SizedSample,
    f32: FromSample<T>,
{
    let channels = config.channels.max(1) as usize;
    let error_tx = tx.clone();
    device
        .build_input_stream(
            config,
            move |data: &[T], _| {
                let mono = data
                    .chunks(channels)
                    .map(|frame| {
                        frame
                            .iter()
                            .map(|&sample| f32::from_sample(sample))
                            .sum::<f32>()
                            / frame.len() as f32
                    })
                    .collect();
                _ = tx.try_send(Capture::Samples(mono));
            },
            move |error| {
                _ = error_tx.try_send(Capture::Error(error.to_string()));
            },
            None,
        )
        .map_err(|error| match error {
            cpal::BuildStreamError::DeviceNotAvailable => SpeechError::NoInputDevice,
            error => SpeechError::input(error),
        })
}

/// Converts mono `f32` audio at the device rate to interleaved `i16` audio in
/// the recognizer's format, carrying state across chunks.
struct Converter {
    /// Source samples per output sample.
    step: f64,
    /// Position of the next output sample, in source samples, where `0.0` is
    /// the last sample of the previous chunk.
    position: f64,
    previous: f32,
    low_pass: Option<LowPass>,
    channels: usize,
}

impl Converter {
    fn new(source_rate: u32, format: AudioFormat) -> Self {
        let target_rate = format.sample_rate().max(1);
        let source_rate = source_rate.max(1);
        Self {
            step: source_rate as f64 / target_rate as f64,
            position: 1.,
            previous: 0.,
            // Downsampling folds everything above the new Nyquist rate back
            // into the band speech lives in; filter it out first.
            low_pass: (source_rate > target_rate)
                .then(|| LowPass::new(target_rate as f32 * 0.45, source_rate as f32)),
            channels: format.channels().max(1) as usize,
        }
    }

    fn convert(&mut self, input: &[f32]) -> Vec<i16> {
        if input.is_empty() {
            return Vec::new();
        }
        let filtered;
        let input = match self.low_pass.as_mut() {
            Some(low_pass) => {
                filtered = input
                    .iter()
                    .map(|&x| low_pass.process(x))
                    .collect::<Vec<_>>();
                &filtered[..]
            }
            None => input,
        };

        let sample = |ix: usize| {
            if ix == 0 {
                self.previous
            } else {
                input[ix - 1]
            }
        };
        let last = input.len();
        let len = last as f64;
        let mut output = Vec::with_capacity(((len / self.step) as usize + 1) * self.channels);
        while self.position <= len {
            let ix = self.position.floor() as usize;
            let frac = (self.position - ix as f64) as f32;
            let next = sample((ix + 1).min(last));
            let value = sample(ix) * (1. - frac) + next * frac;
            let value = (value.clamp(-1., 1.) * i16::MAX as f32) as i16;
            output.extend(std::iter::repeat_n(value, self.channels));
            self.position += self.step;
        }
        self.position -= len;
        self.previous = input[input.len() - 1];
        output
    }
}

/// Two cascaded one-pole low-pass filters, 12 dB per octave.
struct LowPass {
    alpha: f32,
    stages: [f32; 2],
}

impl LowPass {
    fn new(cutoff: f32, sample_rate: f32) -> Self {
        Self {
            alpha: 1. - (-TAU * cutoff / sample_rate).exp(),
            stages: [0.; 2],
        }
    }

    fn process(&mut self, mut x: f32) -> f32 {
        for stage in &mut self.stages {
            *stage += self.alpha * (x - *stage);
            x = *stage;
        }
        x
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converter_keeps_rate_and_duplicates_channels() {
        let mut converter = Converter::new(16_000, AudioFormat::new(16_000, 2));
        let output = converter.convert(&[0., 0.5, -0.5]);
        assert_eq!(output, vec![0, 0, 16383, 16383, -16383, -16383]);
    }

    #[test]
    fn converter_downsamples_across_chunks() {
        let mut converter = Converter::new(48_000, AudioFormat::default());
        let total: usize = (0..10).map(|_| converter.convert(&[0.; 480]).len()).sum();
        // 100 ms at 48 kHz is 100 ms at 16 kHz, whatever the chunking.
        assert_eq!(total, 1_600);
    }

    #[test]
    fn converter_upsamples() {
        let mut converter = Converter::new(8_000, AudioFormat::default());
        let total: usize = (0..10).map(|_| converter.convert(&[0.; 80]).len()).sum();
        // The first output lands on the first input sample, so the half step
        // before it is never produced.
        assert_eq!(total, 1_599);
    }
}
