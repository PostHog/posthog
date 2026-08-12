import type {
  CompletionSound,
  CustomSound,
} from "@posthog/ui/features/settings/settingsStore";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveSoundUrl } from "./sounds";

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
