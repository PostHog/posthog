import { describe, expect, it } from "vitest";
import { highlightSyntax } from "./syntax-highlight";

describe("highlightSyntax", () => {
  it("returns segments whose text reconstructs the original code", () => {
    const code = "const x = 1;\nconst y = 2;";
    const segments = highlightSyntax(code, "typescript", true);
    expect(segments).not.toBeNull();
    expect(segments?.map((s) => s.text).join("")).toBe(code);
  });

  it("returns the cached array on a repeated identical call", () => {
    const code = "def add(a, b):\n    return a + b";
    const first = highlightSyntax(code, "python", true);
    const second = highlightSyntax(code, "python", true);
    expect(first).not.toBeNull();
    expect(second).toBe(first);
  });

  it("caches per theme — light and dark are distinct results", () => {
    const code = "let z = 3;";
    const dark = highlightSyntax(code, "javascript", true);
    const light = highlightSyntax(code, "javascript", false);
    expect(dark).not.toBe(light);
  });

  it("returns null for an unsupported language", () => {
    expect(highlightSyntax("whatever", "brainfuck", true)).toBeNull();
  });

  it("evicts the oldest entry once the cache is full", () => {
    const code = "const evicted = true;";
    const first = highlightSyntax(code, "javascript", true);

    // 256 distinct inserts push everything older out of the bounded cache.
    for (let i = 0; i < 256; i++) {
      highlightSyntax(`const filler${i} = ${i};`, "javascript", true);
    }

    const again = highlightSyntax(code, "javascript", true);
    expect(again).not.toBe(first);
    expect(again).toEqual(first);
  });
});
