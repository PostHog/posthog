import { describe, expect, it } from "vitest";
import { isAgentVersion } from "./agentVersion";

describe("isAgentVersion", () => {
  it("returns true when actual satisfies a >= range", () => {
    expect(isAgentVersion("0.40.1", ">=0.40.1")).toBe(true);
    expect(isAgentVersion("0.41.0", ">=0.40.1")).toBe(true);
    expect(isAgentVersion("1.0.0", ">=0.40.1")).toBe(true);
  });

  it("returns false when actual is below a >= range", () => {
    expect(isAgentVersion("0.40.0", ">=0.40.1")).toBe(false);
    expect(isAgentVersion("0.39.99", ">=0.40.1")).toBe(false);
  });

  it("supports strict >, <, and <= comparators", () => {
    expect(isAgentVersion("1.0.1", ">1.0.0")).toBe(true);
    expect(isAgentVersion("1.0.0", ">1.0.0")).toBe(false);
    expect(isAgentVersion("0.9.9", "<1.0.0")).toBe(true);
    expect(isAgentVersion("1.0.0", "<1.0.0")).toBe(false);
    expect(isAgentVersion("1.0.0", "<=1.0.0")).toBe(true);
  });

  it("supports caret and tilde ranges", () => {
    expect(isAgentVersion("1.2.5", "^1.2.0")).toBe(true);
    expect(isAgentVersion("2.0.0", "^1.2.0")).toBe(false);
    expect(isAgentVersion("1.2.5", "~1.2.0")).toBe(true);
    expect(isAgentVersion("1.3.0", "~1.2.0")).toBe(false);
  });

  it("supports compound ranges", () => {
    expect(isAgentVersion("0.50.0", ">=0.40.0 <1.0.0")).toBe(true);
    expect(isAgentVersion("1.0.0", ">=0.40.0 <1.0.0")).toBe(false);
    expect(isAgentVersion("0.39.0", ">=0.40.0 <1.0.0")).toBe(false);
  });

  it("treats prereleases as comparable to their base version", () => {
    // includePrerelease lets call sites match a prerelease against a stable
    // range without callers having to opt in per call.
    expect(isAgentVersion("0.40.1-rc.1", ">=0.40.0")).toBe(true);
    expect(isAgentVersion("0.40.0-rc.1", ">=0.40.1")).toBe(false);
  });

  it("fails closed when the actual version is undefined", () => {
    expect(isAgentVersion(undefined, ">=0.0.0")).toBe(false);
    expect(isAgentVersion(undefined, "<99.0.0")).toBe(false);
  });

  it("fails closed when the actual version is empty", () => {
    expect(isAgentVersion("", ">=0.0.0")).toBe(false);
  });

  it("returns false for malformed range strings", () => {
    expect(isAgentVersion("1.0.0", "not a range")).toBe(false);
  });

  describe("dev sentinel (0.0.0-dev)", () => {
    // Local dev builds ship the latest code under the placeholder version
    // `0.0.0-dev`. Treat it as satisfying any range so feature gates don't
    // silently disable in development.
    it("satisfies any well-formed range", () => {
      expect(isAgentVersion("0.0.0-dev", ">=0.40.1")).toBe(true);
      expect(isAgentVersion("0.0.0-dev", ">99.0.0")).toBe(true);
      expect(isAgentVersion("0.0.0-dev", "<0.0.0")).toBe(true);
      expect(isAgentVersion("0.0.0-dev", "^1.2.0")).toBe(true);
      expect(isAgentVersion("0.0.0-dev", ">=0.40.0 <1.0.0")).toBe(true);
    });

    it("still rejects malformed range strings", () => {
      expect(isAgentVersion("0.0.0-dev", "not a range")).toBe(false);
    });
  });
});
