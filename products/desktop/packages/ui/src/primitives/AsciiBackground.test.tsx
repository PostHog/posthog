import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AsciiBackground } from "./AsciiBackground";

describe("AsciiBackground", () => {
  // jsdom has no WebGL, which is the same shape as a machine whose GPU context
  // is gone: the field has to degrade to the static dot pattern rather than
  // throw and take the surface it backs down with it.
  it("falls back to the dot pattern when WebGL is unavailable", () => {
    const { container } = render(<AsciiBackground className="h-full" />);

    expect(container.querySelector("canvas")).toBeNull();
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("class")).toContain("h-full");
  });
});
