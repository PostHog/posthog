import { describe, expect, it } from "vitest";
import { resolveBrowserAddress } from "./browserAddress";

describe("resolveBrowserAddress", () => {
  it.each([
    ["a full address", "https://example.com/docs", "https://example.com/docs"],
    ["a bare domain", "example.com", "https://example.com/"],
    [
      "a local server",
      "localhost:3000/settings",
      "http://localhost:3000/settings",
    ],
    ["a loopback address", "127.0.0.1:8000", "http://127.0.0.1:8000/"],
    ["a file", "file:///etc/passwd", null],
    ["a script", "javascript:alert(1)", null],
    ["a data url", "data:text/html,hi", null],
    ["credentials in the address", "https://user:pass@example.com", null],
    ["words with spaces", "how to share files", null],
    ["nothing", "  ", null],
  ])("resolves %s", (_name, input, expected) => {
    expect(resolveBrowserAddress(input)).toBe(expected);
  });
});
