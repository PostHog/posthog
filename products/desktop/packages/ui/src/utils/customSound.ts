// Helpers for capturing user-installed notification sounds (live recording or
// file import). Custom clips are stored inline as base64 data URLs in the
// settings store, so they're deliberately short: the duration cap keeps that
// persisted payload small and a notification ding should be brief anyway.

// Hard cap on clip length. Live recordings auto-stop here; imported files longer
// than this are rejected.
export const MAX_CUSTOM_SOUND_DURATION_MS = 5_000;

// Backstop on the stored payload regardless of reported duration (e.g. a
// high-bitrate import). ~1 MB of base64 sits comfortably within the settings
// store.
export const MAX_CUSTOM_SOUND_BYTES = 1_000_000;

// Seconds form of the duration cap, for display copy.
export const MAX_CUSTOM_SOUND_SECONDS = MAX_CUSTOM_SOUND_DURATION_MS / 1000;

// Decoded durations can read a touch over the cap (encoder rounding); allow a
// small slack before rejecting an otherwise-fine clip.
export const DURATION_TOLERANCE_MS = 300;

// Preferred recorder containers, best first. Chromium (the Electron renderer)
// records Opus-in-WebM; the fallbacks cover other hosts.
const RECORDING_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

export function pickRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return RECORDING_MIME_TYPES.find((type) =>
    MediaRecorder.isTypeSupported(type),
  );
}

export function isRecordingSupported(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () =>
      reject(reader.error ?? new Error("Could not read audio data"));
    reader.readAsDataURL(blob);
  });
}

// Reads a clip's duration by loading just its metadata. Resolves null when the
// duration can't be determined — some streamed WebM blobs report Infinity, in
// which case callers fall back to the recorder's own elapsed timer.
export function getAudioDurationMs(src: string): Promise<number | null> {
  return new Promise((resolve) => {
    const audio = new Audio();
    audio.preload = "metadata";
    const done = (value: number | null) => {
      audio.onloadedmetadata = null;
      audio.onerror = null;
      resolve(value);
    };
    audio.onloadedmetadata = () => {
      const seconds = audio.duration;
      done(Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : null);
    };
    audio.onerror = () => done(null);
    audio.src = src;
  });
}

// Below this peak amplitude (~ -60 dBFS) we treat a recording as silent. A real
// microphone's noise floor sits comfortably above this, so it only trips on a
// genuine no-signal capture, not quiet-but-real audio.
export const SILENCE_PEAK_THRESHOLD = 0.001;

// A sample counts as "signal" when it exceeds this fraction of the clip's own
// peak — relative, so silence detection adapts to loud and quiet clips alike.
// (Distinct from the 50ms padding default below, which happens to share 0.05.)
const SILENCE_RELATIVE_THRESHOLD = 0.05;

// Decodes a clip's raw bytes into PCM samples, or null when it can't be decoded
// (an exotic container, or no Web Audio support) — callers then fall back to
// storing the clip untouched. Reads the blob's bytes directly (no data-URL
// fetch round-trip, which a strict renderer CSP could block) and uses a
// throwaway OfflineAudioContext whose length/rate args don't affect the decoded
// buffer and which never touches the audio output device.
export async function decodeAudioClip(blob: Blob): Promise<AudioBuffer | null> {
  if (typeof OfflineAudioContext === "undefined") return null;
  try {
    const bytes = await blob.arrayBuffer();
    const ctx = new OfflineAudioContext(1, 1, 44100);
    return await ctx.decodeAudioData(bytes);
  } catch {
    return null;
  }
}

// Peak absolute sample amplitude (0–1) across all channels. A freshly-recorded
// clip that reads ~0 means the mic delivered silence — commonly the OS still
// blocks microphone access even though the browser reports it granted.
export function audioBufferPeak(buffer: AudioBuffer): number {
  let peak = 0;
  for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
    const samples = buffer.getChannelData(channel);
    // Stride-sample to stay cheap; a silent clip is zero everywhere anyway.
    const stride = Math.max(1, Math.floor(samples.length / 10_000));
    for (let i = 0; i < samples.length; i += stride) {
      const magnitude = Math.abs(samples[i]);
      if (magnitude > peak) peak = magnitude;
    }
  }
  return peak;
}

export interface TrimBounds {
  startSec: number;
  endSec: number;
}

// Finds the [startSec, endSec] span of a clip after stripping leading and
// trailing near-silence, with a little padding so the sound doesn't feel
// clipped. The silence threshold is relative to the clip's own peak (5%), so it
// adapts to loud and quiet recordings alike. Scans the loudest channel at each
// sample so a quiet channel can't fool the detection. Returns null when the clip
// is effectively silent throughout (nothing meaningful to keep).
export function detectSilenceBounds(
  buffer: AudioBuffer,
  paddingSec = 0.05,
): TrimBounds | null {
  const n = buffer.length;
  const channels: Float32Array[] = [];
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    channels.push(buffer.getChannelData(c));
  }
  // Loudest magnitude across all channels at sample i.
  const ampAt = (i: number) => {
    let magnitude = 0;
    for (const data of channels) {
      const value = Math.abs(data[i]);
      if (value > magnitude) magnitude = value;
    }
    return magnitude;
  };

  let peak = 0;
  for (let i = 0; i < n; i++) {
    const value = ampAt(i);
    if (value > peak) peak = value;
  }
  if (peak <= SILENCE_PEAK_THRESHOLD) return null;

  const threshold = Math.max(
    SILENCE_PEAK_THRESHOLD,
    peak * SILENCE_RELATIVE_THRESHOLD,
  );
  let first = 0;
  while (first < n && ampAt(first) < threshold) first++;
  let last = n - 1;
  while (last > first && ampAt(last) < threshold) last--;
  if (first >= last) return null;

  const { sampleRate } = buffer;
  const pad = Math.floor(paddingSec * sampleRate);
  // `last` is the last audible sample (inclusive); the slice end is exclusive,
  // hence `last + 1`, then the same padding as the leading edge.
  return {
    startSec: Math.max(0, first - pad) / sampleRate,
    endSec: Math.min(n, last + 1 + pad) / sampleRate,
  };
}

// A clip whose peak is below the silence threshold carried no usable audio — a
// recording that comes back this quiet means the mic delivered silence.
export function isClipSilent(buffer: AudioBuffer): boolean {
  return audioBufferPeak(buffer) < SILENCE_PEAK_THRESHOLD;
}

// Whether stripping the detected silence would shorten the clip by a noticeable
// amount at either end — i.e. whether it's worth offering the trim at all.
export function shouldOfferTrim(
  bounds: TrimBounds | null,
  durationSec: number,
  minSilenceSec = 0.1,
): boolean {
  if (!bounds) return false;
  return (
    bounds.startSec > minSilenceSec ||
    bounds.endSec < durationSec - minSilenceSec
  );
}

// Millisecond length of a trimmed selection.
export function trimmedDurationMs(bounds: TrimBounds): number {
  return Math.round((bounds.endSec - bounds.startSec) * 1000);
}

// Resolves what to persist for a clip: when a trim is applied and the clip
// decoded, re-encode the kept region as WAV (rejecting it if that pushes past
// the byte cap); otherwise store the original clip untouched.
export function resolveSaveClip(
  clip: { dataUrl: string; durationMs: number; buffer: AudioBuffer | null },
  trim: TrimBounds | null,
): { dataUrl: string; durationMs: number } | { error: string } {
  if (trim && clip.buffer) {
    const dataUrl = encodeWavDataUrl(clip.buffer, trim.startSec, trim.endSec);
    if (dataUrlByteLength(dataUrl) > MAX_CUSTOM_SOUND_BYTES) {
      return {
        error: "That trimmed clip is too large. Keep it short (max ~1 MB).",
      };
    }
    return { dataUrl, durationMs: trimmedDurationMs(trim) };
  }
  return { dataUrl: clip.dataUrl, durationMs: clip.durationMs };
}

// Re-encodes the [startSec, endSec] slice of a decoded clip as a self-contained
// mono 16-bit PCM WAV data URL. Mono keeps the payload small (a notification
// ding doesn't need stereo) and WAV is universally playable, so the stored
// CustomSound stays a plain data URL with no playback-time trimming needed.
export function encodeWavDataUrl(
  buffer: AudioBuffer,
  startSec: number,
  endSec: number,
): string {
  const { sampleRate } = buffer;
  const startSample = Math.max(0, Math.floor(startSec * sampleRate));
  const endSample = Math.min(buffer.length, Math.floor(endSec * sampleRate));
  const length = Math.max(0, endSample - startSample);
  const channels = buffer.numberOfChannels;

  // Downmix every channel to mono.
  const mono = new Float32Array(length);
  for (let channel = 0; channel < channels; channel++) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i++) {
      mono[i] += data[startSample + i] / channels;
    }
  }

  const dataSize = length * 2; // 16-bit samples
  const out = new ArrayBuffer(44 + dataSize);
  const view = new DataView(out);
  const writeString = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate (mono, 2 bytes/sample)
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < length; i++) {
    const sample = Math.max(-1, Math.min(1, mono[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }

  // Base64-encode in chunks so we never spread a huge array into fromCharCode.
  const bytes = new Uint8Array(out);
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return `data:audio/wav;base64,${btoa(binary)}`;
}

// Approximate decoded byte length of a base64 data URL payload.
export function dataUrlByteLength(dataUrl: string): number {
  const comma = dataUrl.indexOf(",");
  const base64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((base64.length * 3) / 4) - padding);
}

export function formatDurationSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}
