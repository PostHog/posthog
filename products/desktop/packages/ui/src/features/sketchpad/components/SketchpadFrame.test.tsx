import { SKETCHPAD_FRAME_TITLE } from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SketchpadFrame } from "./SketchpadFrame";

describe("SketchpadFrame", () => {
  it("does not create an iframe while the board is stopped", () => {
    const props = {
      onElement: vi.fn(),
      srcDoc: "<script>parent.postMessage('ran', '*')</script>",
      vendored: false,
      inert: false,
      stopped: true,
    };
    const { rerender } = render(<SketchpadFrame {...props} />);

    expect(screen.queryByTitle(SKETCHPAD_FRAME_TITLE)).toBeNull();

    rerender(<SketchpadFrame {...props} stopped={false} />);
    expect(screen.getByTitle(SKETCHPAD_FRAME_TITLE)).toBeInTheDocument();
  });
});
