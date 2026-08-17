import { describe, expect, it } from "vitest";
import {
  CELL_GAP,
  cameraTransform,
  cellCenter,
  scaleFor,
  worldCenter,
  zoomedIn,
  zoomedOut,
} from "./camera";

const VIEWPORT = { width: 1440, height: 900 };

describe("zoom canvas camera", () => {
  it("frames a cell pixel-for-pixel at session zoom", () => {
    // Scale 1 is what keeps a live task view from being resampled — a task
    // rendered at any other scale is a blurry task.
    expect(scaleFor("session", VIEWPORT, { columns: 5, rows: 8 })).toBe(1);
  });

  it("keeps the camera finite on an empty grid", () => {
    // Zero columns would otherwise divide by the margin alone and blow the
    // scale up to something that renders nothing.
    const scale = scaleFor("world", VIEWPORT, { columns: 0, rows: 0 });
    expect(Number.isFinite(scale)).toBe(true);
    expect(scale).toBeGreaterThan(0);
  });

  it("puts the whole canvas in view at world zoom", () => {
    const grid = { columns: 4, rows: 6 };
    const scale = scaleFor("world", VIEWPORT, grid);
    const canvasWidth = grid.columns * (VIEWPORT.width + CELL_GAP) - CELL_GAP;
    const canvasHeight = grid.rows * (VIEWPORT.height + CELL_GAP) - CELL_GAP;

    expect(canvasWidth * scale).toBeLessThanOrEqual(VIEWPORT.width);
    expect(canvasHeight * scale).toBeLessThanOrEqual(VIEWPORT.height);
  });

  it("centres the canvas on its own middle at world zoom", () => {
    const center = worldCenter(VIEWPORT, { columns: 3, rows: 3 });
    expect(center).toEqual(cellCenter({ column: 1, row: 1 }, VIEWPORT));
  });

  it.each([
    { zoom: "session", inward: "session", outward: "arena" },
    { zoom: "arena", inward: "session", outward: "world" },
    { zoom: "world", inward: "arena", outward: "world" },
  ] as const)(
    "steps $zoom in to $inward and out to $outward",
    ({ zoom, inward, outward }) => {
      expect(zoomedIn(zoom)).toBe(inward);
      expect(zoomedOut(zoom)).toBe(outward);
    },
  );

  it("lands the framed point in the middle of the viewport", () => {
    const center = { x: 4000, y: 2500 };
    const transform = cameraTransform({ viewport: VIEWPORT, center, scale: 1 });
    expect(transform).toBe(
      "translate(720px, 450px) scale(1) translate(-4000px, -2500px)",
    );
  });
});
