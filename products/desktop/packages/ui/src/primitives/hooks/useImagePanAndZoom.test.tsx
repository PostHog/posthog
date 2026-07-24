import { useImagePanAndZoom } from "@posthog/ui/primitives/hooks/useImagePanAndZoom";
import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

type HookResult = ReturnType<typeof useImagePanAndZoom>;

interface HarnessProps {
  onRender: (result: HookResult) => void;
  options?: Parameters<typeof useImagePanAndZoom>[0];
}

function Harness({ onRender, options }: HarnessProps) {
  const result = useImagePanAndZoom(options);
  onRender(result);
  return (
    <div
      data-testid="container"
      ref={result.containerRef}
      style={{ width: 200, height: 200 }}
    />
  );
}

function setupHarness(options?: Parameters<typeof useImagePanAndZoom>[0]) {
  let latest: HookResult | null = null;
  const view = render(
    <Harness
      onRender={(result) => {
        latest = result;
      }}
      options={options}
    />,
  );
  const container = view.getByTestId("container");
  container.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 200,
      bottom: 200,
      width: 200,
      height: 200,
      toJSON: () => ({}),
    }) as DOMRect;
  container.setPointerCapture = () => {};
  container.releasePointerCapture = () => {};
  container.hasPointerCapture = () => true;
  return {
    container,
    get current() {
      if (!latest) throw new Error("hook did not render");
      return latest;
    },
  };
}

function parseTransform(transform: string) {
  const match = transform.match(
    /translate\(([-0-9.]+)px, ([-0-9.]+)px\) scale\(([-0-9.]+)\)/,
  );
  if (!match) throw new Error(`unexpected transform: ${transform}`);
  return {
    tx: Number.parseFloat(match[1]),
    ty: Number.parseFloat(match[2]),
    scale: Number.parseFloat(match[3]),
  };
}

describe("useImagePanAndZoom", () => {
  it("starts at identity transform and not zoomed", () => {
    const harness = setupHarness();
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
    expect(harness.current.isZoomed).toBe(false);
  });

  it.each([
    { modifier: "ctrlKey", label: "trackpad pinch" },
    { modifier: "metaKey", label: "Cmd + wheel" },
  ] as const)("zooms in via $label", ({ modifier }) => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        [modifier]: true,
        deltaY: -100,
        clientX: 100,
        clientY: 100,
      });
    });
    expect(harness.current.isZoomed).toBe(true);
    expect(parseTransform(harness.current.transform).scale).toBeGreaterThan(1);
  });

  it("ignores wheel without modifier when not zoomed", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        deltaY: 200,
        clientX: 100,
        clientY: 100,
      });
    });
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
  });

  it("pans on wheel without modifier when zoomed in", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -200,
        clientX: 100,
        clientY: 100,
      });
    });
    const beforePan = parseTransform(harness.current.transform);
    act(() => {
      fireEvent.wheel(harness.container, {
        deltaX: 30,
        deltaY: 40,
        clientX: 100,
        clientY: 100,
      });
    });
    const afterPan = parseTransform(harness.current.transform);
    expect(afterPan.tx).toBeCloseTo(beforePan.tx - 30);
    expect(afterPan.ty).toBeCloseTo(beforePan.ty - 40);
    expect(afterPan.scale).toBe(beforePan.scale);
  });

  it.each([
    { direction: "in", deltaY: -2000, expected: 4 },
    { direction: "out", deltaY: 2000, expected: 1 },
  ])("clamps scale at the $direction limit", ({ deltaY, expected }) => {
    const harness = setupHarness({ minScale: 1, maxScale: 4 });
    for (let i = 0; i < 50; i++) {
      act(() => {
        fireEvent.wheel(harness.container, {
          ctrlKey: true,
          deltaY,
          clientX: 100,
          clientY: 100,
        });
      });
    }
    expect(parseTransform(harness.current.transform).scale).toBe(expected);
  });

  it("snaps to identity when zooming all the way back to scale 1", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -300,
        clientX: 150,
        clientY: 150,
      });
    });
    expect(harness.current.isZoomed).toBe(true);
    for (let i = 0; i < 50; i++) {
      act(() => {
        fireEvent.wheel(harness.container, {
          ctrlKey: true,
          deltaY: 200,
          clientX: 0,
          clientY: 0,
        });
      });
    }
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
  });

  it("double-click resets to identity", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -300,
        clientX: 100,
        clientY: 100,
      });
    });
    expect(harness.current.isZoomed).toBe(true);
    act(() => {
      fireEvent.dblClick(harness.container);
    });
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
    expect(harness.current.isZoomed).toBe(false);
  });

  it("reset() returns to identity", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -300,
        clientX: 80,
        clientY: 80,
      });
    });
    act(() => {
      harness.current.reset();
    });
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
  });

  it("ignores pointer drag when not zoomed", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.pointerDown(harness.container, {
        pointerId: 1,
        button: 0,
        clientX: 50,
        clientY: 50,
      });
      fireEvent.pointerMove(harness.container, {
        pointerId: 1,
        clientX: 120,
        clientY: 90,
      });
      fireEvent.pointerUp(harness.container, { pointerId: 1 });
    });
    expect(parseTransform(harness.current.transform)).toEqual({
      tx: 0,
      ty: 0,
      scale: 1,
    });
  });

  it("pans on pointer drag when zoomed", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -300,
        clientX: 100,
        clientY: 100,
      });
    });
    const before = parseTransform(harness.current.transform);
    act(() => {
      fireEvent.pointerDown(harness.container, {
        pointerId: 1,
        button: 0,
        clientX: 50,
        clientY: 50,
      });
      fireEvent.pointerMove(harness.container, {
        pointerId: 1,
        clientX: 80,
        clientY: 30,
      });
    });
    const dragging = parseTransform(harness.current.transform);
    expect(dragging.tx).toBeCloseTo(before.tx + 30);
    expect(dragging.ty).toBeCloseTo(before.ty - 20);
    expect(dragging.scale).toBe(before.scale);
    expect(harness.current.isDragging).toBe(true);
    act(() => {
      fireEvent.pointerUp(harness.container, { pointerId: 1 });
      fireEvent.pointerMove(harness.container, {
        pointerId: 1,
        clientX: 999,
        clientY: 999,
      });
    });
    expect(parseTransform(harness.current.transform)).toEqual(dragging);
    expect(harness.current.isDragging).toBe(false);
  });

  it("zooms toward the cursor position", () => {
    const harness = setupHarness();
    act(() => {
      fireEvent.wheel(harness.container, {
        ctrlKey: true,
        deltaY: -100,
        clientX: 150,
        clientY: 100,
      });
    });
    const { tx, ty, scale } = parseTransform(harness.current.transform);
    const cursorOffsetX = 150 - 100;
    const cursorOffsetY = 100 - 100;
    expect(tx).toBeCloseTo(cursorOffsetX - cursorOffsetX * scale);
    expect(ty).toBeCloseTo(cursorOffsetY - cursorOffsetY * scale);
  });
});
