import { describe, expect, it } from "vitest";
import { resolvePreviewNavigation } from "./previewNavigation";

const PREVIEW = "https://abc-123.w.modal.host/?_modal_connect_token=secret";

describe("resolvePreviewNavigation", () => {
  it.each([
    [
      "an absolute path",
      "/pricing?plan=pro",
      "/",
      { kind: "load", path: "/pricing?plan=pro" },
    ],
    [
      "a relative path",
      "team",
      "/pricing/",
      { kind: "load", path: "/pricing/team" },
    ],
    ["a hash", "#faq", "/pricing", { kind: "load", path: "/pricing#faq" }],
    [
      "the preview's own address",
      "https://abc-123.w.modal.host/docs",
      "/",
      { kind: "load", path: "/docs" },
    ],
    [
      "another site",
      "https://example.com/login",
      "/",
      { kind: "external", url: "https://example.com/login" },
    ],
    [
      "another sandbox",
      "https://other.w.modal.host/",
      "/",
      { kind: "external", url: "https://other.w.modal.host/" },
    ],
    ["a file", "file:///etc/passwd", "/", null],
    ["a script", "javascript:alert(1)", "/", null],
    ["nothing", "   ", "/", null],
  ])("resolves %s", (_name, input, currentPath, expected) => {
    expect(resolvePreviewNavigation(input, PREVIEW, currentPath)).toEqual(
      expected,
    );
  });
});
