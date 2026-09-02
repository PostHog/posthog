import type {
  CompletionSound,
  CustomSound,
} from "@posthog/ui/features/settings/settingsStore";
import { afterEach, describe, expect, it, vi } from "vitest";
import { playbackRateForTaskDuration, resolveSoundUrl } from "./sounds";

const customs: CustomSound[] = [
  {
    id: "abc",
    name: "My ding",
    dataUrl: "data:audio/wav;base64,AAAA",
    durationMs: 800,
  },
];

describe("resolveSoundUrl", () => {
  it("returns null for 'none'", () => {
    expect(resolveSoundUrl("none", [])).toBeNull();
  });

  it("returns a bundled asset URL for a built-in sound", () => {
    const url = resolveSoundUrl("guitar", []);
    expect(typeof url).toBe("string");
    expect(url).toBeTruthy();
  });

  it("returns null for an unknown built-in", () => {
    expect(resolveSoundUrl("bogus" as CompletionSound, [])).toBeNull();
  });

  it("resolves a custom sound id to its inline data URL", () => {
    expect(resolveSoundUrl("custom:abc", customs)).toBe(
      "data:audio/wav;base64,AAAA",
    );
  });

  it("returns null when the custom id is no longer installed", () => {
    // e.g. the active sound was deleted from the library.
    expect(resolveSoundUrl("custom:gone", customs)).toBeNull();
  });

  describe("random modes", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("'random-all' with no custom sounds picks a built-in asset", () => {
      const url = resolveSoundUrl("random-all", []);
      expect(url).toBeTruthy();
      expect(url).not.toMatch(/^data:/);
    });

    it("'random-custom' with a single custom sound picks it", () => {
      expect(resolveSoundUrl("random-custom", customs)).toBe(
        "data:audio/wav;base64,AAAA",
      );
    });

    it("'random-custom' with no custom sounds returns null", () => {
      expect(resolveSoundUrl("random-custom", [])).toBeNull();
    });

    it.each([
      ["lowest roll picks a built-in", 0, false],
      ["highest roll picks a custom sound", 0.999999, true],
    ])(
      "'random-all' spans built-ins and customs: %s",
      (_label, roll, expectCustom) => {
        vi.spyOn(Math, "random").mockReturnValue(roll);
        const url = resolveSoundUrl("random-all", customs);
        expect(url === "data:audio/wav;base64,AAAA").toBe(expectCustom);
        expect(url).toBeTruthy();
      },
    );
  });
});

describe("playbackRateForTaskDuration", () => {
  it.each([
    ["below the fast floor (10s)", 10 * 1000, 3],
    ["at the fast floor (30s)", 30 * 1000, 3],
    ["geometric mid of the fast ramp (60s)", 60 * 1000, Math.sqrt(3)],
    ["normal band start (2min)", 2 * 60 * 1000, 1],
    ["normal band end (4min)", 4 * 60 * 1000, 1],
    [
      "geometric mid of the slow ramp",
      Math.sqrt(4 * 60 * 1000 * (30 * 60 * 1000)),
      Math.sqrt(1 / 3),
    ],
    ["at the slow ceiling (30min)", 30 * 60 * 1000, 1 / 3],
    ["beyond the slow ceiling (2h)", 2 * 60 * 60 * 1000, 1 / 3],
    ["NaN (non-finite) → fast rate", Number.NaN, 3],
  ])("%s → %f", (_label, durationMs, expected) => {
    expect(playbackRateForTaskDuration(durationMs)).toBeCloseTo(expected, 5);
  });
});
