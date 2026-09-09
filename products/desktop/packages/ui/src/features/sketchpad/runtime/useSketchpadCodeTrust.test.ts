import type { SketchpadFragment } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useSketchpadCodeTrust } from "./useSketchpadCodeTrust";

const fragment: SketchpadFragment = {
  id: "card",
  x: 0,
  y: 0,
  w: 360,
  h: 240,
  z: 0,
  code: "export default () => null",
  codeVersion: 1,
  surface: "card",
  hidden: false,
};

describe("useSketchpadCodeTrust", () => {
  it("requires approval again after code or board changes", () => {
    const { result, rerender } = renderHook(
      ({ sketchpadId, fragments }) =>
        useSketchpadCodeTrust(sketchpadId, fragments),
      { initialProps: { sketchpadId: "one", fragments: [fragment] } },
    );

    expect(result.current.stopped).toBe(true);
    act(() => result.current.start());
    expect(result.current.stopped).toBe(false);

    rerender({
      sketchpadId: "one",
      fragments: [{ ...fragment, x: 20 }],
    });
    expect(result.current.stopped).toBe(false);

    rerender({
      sketchpadId: "one",
      fragments: [{ ...fragment, code: "export default () => <p>New</p>" }],
    });
    expect(result.current.stopped).toBe(true);

    act(() => result.current.start());
    rerender({
      sketchpadId: "two",
      fragments: [{ ...fragment, code: "export default () => <p>New</p>" }],
    });
    expect(result.current.stopped).toBe(true);
  });
});
