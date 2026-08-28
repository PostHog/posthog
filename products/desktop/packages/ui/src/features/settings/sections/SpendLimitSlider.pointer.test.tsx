import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SpendLimitSlider } from "./SpendLimitSlider";

describe("SpendLimitSlider pointer drag", () => {
  beforeEach(() => {
    // jsdom implements neither pointer capture nor layout, so stub both: the
    // handle captures the pointer on pointerdown, and valueFromPointer needs a
    // non-zero track width to map a position to a value.
    Element.prototype.setPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0,
      width: 200,
      top: 0,
      right: 200,
      bottom: 14,
      height: 14,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("drops the drag on pointercancel so a later click commits the saved line, not the drifted value", () => {
    const onCommit = vi.fn();
    render(
      <SpendLimitSlider
        warnUsd={20}
        stopUsd={50}
        spentUsd={0}
        markerUsd={null}
        periodLabel="Daily"
        onCommit={onCommit}
      />,
    );
    const warn = screen.getByLabelText("Daily warning line");

    // Drag the handle to the middle of the track, then have the browser preempt
    // the gesture the way a trackpad does mid-drag.
    fireEvent.pointerDown(warn, { pointerId: 1, clientX: 0 });
    fireEvent.pointerMove(warn, { pointerId: 1, clientX: 100 });
    fireEvent.pointerCancel(warn, { pointerId: 1 });

    // A plain click now must commit the saved $20, never the drifted amount.
    fireEvent.pointerDown(warn, { pointerId: 2, clientX: 0 });
    fireEvent.pointerUp(warn, { pointerId: 2, clientX: 0 });

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("warn", 20);
  });
});
