import { describe, expect, it } from "vitest";
import {
  audioBufferPeak,
  dataUrlByteLength,
  detectSilenceBounds,
  encodeWavDataUrl,
  isClipSilent,
  resolveSaveClip,
  shouldOfferTrim,
} from "./customSound";

// Minimal AudioBuffer stand-in over one array per channel. The helpers under
// test only read getChannelData, sampleRate, length, and numberOfChannels.
function fakeBuffer(channels: number[][], sampleRate: number): AudioBuffer {
  const datas = channels.map((c) => Float32Array.from(c));
  const length = datas[0]?.length ?? 0;
  return {
    sampleRate,
    length,
    duration: length / sampleRate,
    numberOfChannels: datas.length,
    getChannelData: (i: number) => datas[i],
  } as unknown as AudioBuffer;
}

const silence = (n: number) => new Array(n).fill(0);
const tone = (n: number, amp = 0.8) => new Array(n).fill(amp);

describe("detectSilenceBounds", () => {
  it("strips leading and trailing silence with padding", () => {
    // 1s silence + 2s tone + 1s silence at 1kHz, default 50ms padding.
    const buffer = fakeBuffer(
      [[...silence(1000), ...tone(2000), ...silence(1000)]],
      1000,
    );
    const bounds = detectSilenceBounds(buffer);
    expect(bounds?.startSec).toBeCloseTo(0.95, 2);
    expect(bounds?.endSec).toBeCloseTo(3.05, 2);
  });

  it("strips leading-only silence", () => {
    const buffer = fakeBuffer([[...silence(500), ...tone(1500)]], 1000);
    const bounds = detectSilenceBounds(buffer);
    expect(bounds?.startSec).toBeCloseTo(0.45, 2);
    expect(bounds?.endSec).toBeCloseTo(2.0, 5);
  });

  it("strips trailing-only silence", () => {
    const buffer = fakeBuffer([[...tone(1500), ...silence(500)]], 1000);
    const bounds = detectSilenceBounds(buffer);
    expect(bounds?.startSec).toBe(0);
    expect(bounds?.endSec).toBeCloseTo(1.55, 2);
  });

  it("returns null for an entirely silent clip", () => {
    expect(detectSilenceBounds(fakeBuffer([silence(2000)], 1000))).toBeNull();
  });

  it("keeps the full span when there's no silence to strip", () => {
    const bounds = detectSilenceBounds(fakeBuffer([tone(2000)], 1000));
    expect(bounds?.startSec).toBe(0);
    expect(bounds?.endSec).toBeCloseTo(2.0, 5);
  });

  it("does not strip quiet-but-real audio (threshold is relative to peak)", () => {
    const bounds = detectSilenceBounds(fakeBuffer([tone(2000, 0.02)], 1000));
    expect(bounds?.startSec).toBe(0);
    expect(bounds?.endSec).toBeCloseTo(2.0, 5);
  });

  it("detects audio on a non-first channel (channel-0 blind spot)", () => {
    // Left channel silent throughout, right channel carries the tone.
    const buffer = fakeBuffer(
      [silence(4000), [...silence(1000), ...tone(2000), ...silence(1000)]],
      1000,
    );
    const bounds = detectSilenceBounds(buffer);
    expect(bounds?.startSec).toBeCloseTo(0.95, 2);
    expect(bounds?.endSec).toBeCloseTo(3.05, 2);
  });
});

describe("audioBufferPeak", () => {
  it("returns the loudest absolute sample", () => {
    expect(
      audioBufferPeak(fakeBuffer([[0, -0.3, 0.6, -0.1]], 1000)),
    ).toBeCloseTo(0.6, 5);
  });

  it("takes the max across channels", () => {
    expect(
      audioBufferPeak(
        fakeBuffer(
          [
            [0.1, 0.1],
            [0.1, 0.5],
          ],
          1000,
        ),
      ),
    ).toBeCloseTo(0.5, 5);
  });
});

describe("isClipSilent", () => {
  it("is true just below the silence threshold and false just above", () => {
    expect(isClipSilent(fakeBuffer([tone(100, 0.0005)], 1000))).toBe(true);
    expect(isClipSilent(fakeBuffer([tone(100, 0.01)], 1000))).toBe(false);
  });
});

describe("shouldOfferTrim", () => {
  it("is false without bounds", () => {
    expect(shouldOfferTrim(null, 2)).toBe(false);
  });

  it("is true when there is leading or trailing silence beyond the minimum", () => {
    expect(shouldOfferTrim({ startSec: 0.4, endSec: 2 }, 2)).toBe(true);
    expect(shouldOfferTrim({ startSec: 0, endSec: 1.5 }, 2)).toBe(true);
  });

  it("is false when the bounds already cover essentially the whole clip", () => {
    expect(shouldOfferTrim({ startSec: 0.02, endSec: 1.97 }, 2)).toBe(false);
  });
});

// Decode a WAV data URL back into its header fields and samples for assertions.
function parseWav(dataUrl: string) {
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  const buf = Buffer.from(base64, "base64");
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const str = (offset: number, len: number) =>
    String.fromCharCode(
      ...new Uint8Array(buf.buffer, buf.byteOffset + offset, len),
    );
  return {
    riff: str(0, 4),
    wave: str(8, 4),
    fmt: str(12, 4),
    audioFormat: view.getUint16(20, true),
    channels: view.getUint16(22, true),
    sampleRate: view.getUint32(24, true),
    bitsPerSample: view.getUint16(34, true),
    dataTag: str(36, 4),
    dataSize: view.getUint32(40, true),
    sampleAt: (i: number) => view.getInt16(44 + i * 2, true),
  };
}

describe("encodeWavDataUrl", () => {
  it("writes a correct mono 16-bit header and slices the right samples", () => {
    const total = 8000;
    const samples = Array.from(
      { length: total },
      (_, i) => (i / total) * 2 - 1,
    );
    const buffer = fakeBuffer([samples], 8000);
    // 0.25s..0.75s -> samples [2000, 6000) -> 4000 samples.
    const wav = parseWav(encodeWavDataUrl(buffer, 0.25, 0.75));
    expect(wav.riff).toBe("RIFF");
    expect(wav.wave).toBe("WAVE");
    expect(wav.fmt).toBe("fmt ");
    expect(wav.audioFormat).toBe(1);
    expect(wav.channels).toBe(1);
    expect(wav.sampleRate).toBe(8000);
    expect(wav.bitsPerSample).toBe(16);
    expect(wav.dataTag).toBe("data");
    expect(wav.dataSize).toBe(4000 * 2);
    // First encoded sample is samples[2000] = -0.5 -> -0.5 * 0x8000.
    expect(wav.sampleAt(0)).toBe(-0x4000);
  });
});

describe("resolveSaveClip", () => {
  const buffer = fakeBuffer([tone(2000)], 1000);

  it("stores the original clip when no trim is applied", () => {
    const result = resolveSaveClip(
      { dataUrl: "data:audio/webm;base64,AAA", durationMs: 2000, buffer },
      null,
    );
    expect(result).toEqual({
      dataUrl: "data:audio/webm;base64,AAA",
      durationMs: 2000,
    });
  });

  it("re-encodes to WAV with the trimmed duration when trimmed", () => {
    const result = resolveSaveClip(
      { dataUrl: "data:audio/webm;base64,AAA", durationMs: 2000, buffer },
      { startSec: 0.5, endSec: 1.5 },
    );
    expect("error" in result).toBe(false);
    if (!("error" in result)) {
      expect(result.dataUrl.startsWith("data:audio/wav;base64,")).toBe(true);
      expect(result.durationMs).toBe(1000);
    }
  });

  it("falls back to the original clip when there's no decoded buffer", () => {
    const result = resolveSaveClip(
      { dataUrl: "data:audio/mp3;base64,AAA", durationMs: 2000, buffer: null },
      { startSec: 0.5, endSec: 1.5 },
    );
    expect(result).toEqual({
      dataUrl: "data:audio/mp3;base64,AAA",
      durationMs: 2000,
    });
  });

  it("rejects a trimmed clip that exceeds the byte cap", () => {
    // 600k mono 16-bit samples = ~1.2 MB of PCM, past the ~1 MB cap.
    const samples = 600_000;
    const big = fakeBuffer([tone(samples)], 48000);
    const endSec = samples / 48000;
    const result = resolveSaveClip(
      { dataUrl: "data:audio/wav;base64,AAA", durationMs: 12500, buffer: big },
      { startSec: 0, endSec },
    );
    expect("error" in result).toBe(true);
    // Sanity: the encoded payload really is over the cap.
    expect(dataUrlByteLength(encodeWavDataUrl(big, 0, endSec))).toBeGreaterThan(
      1_000_000,
    );
  });
});
