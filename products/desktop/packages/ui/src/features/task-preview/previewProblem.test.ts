import { describe, expect, it } from "vitest";
import { previewProblem } from "./previewProblem";

describe("previewProblem", () => {
  it.each([
    {
      name: "a failed request",
      session: undefined,
      isError: true,
      loadFailed: false,
      expected: "error",
    },
    {
      name: "a request still in flight",
      session: undefined,
      isError: false,
      loadFailed: false,
      expected: null,
    },
    {
      name: "a stopped sandbox",
      session: { outcome: "ended" as const, url: null },
      isError: false,
      loadFailed: false,
      expected: "ended",
    },
    {
      name: "a ready outcome without a url",
      session: { outcome: "ready" as const, url: null },
      isError: false,
      loadFailed: false,
      expected: "unavailable",
    },
    {
      name: "a ready preview that did not load",
      session: { outcome: "ready" as const, url: "https://a.modal.host/" },
      isError: false,
      loadFailed: true,
      expected: "load_failed",
    },
    {
      name: "a ready preview",
      session: { outcome: "ready" as const, url: "https://a.modal.host/" },
      isError: false,
      loadFailed: false,
      expected: null,
    },
  ])("returns $expected for $name", ({ name: _name, expected, ...input }) => {
    expect(previewProblem(input)).toBe(expected);
  });
});
