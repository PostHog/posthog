export type Rgb = readonly [number, number, number];

let scratch: CanvasRenderingContext2D | null | undefined;

/** A 1x1 2D context, used to let the browser parse any CSS color for us. */
function scratchContext(): CanvasRenderingContext2D | null {
  if (scratch === undefined) {
    scratch = document.createElement("canvas").getContext("2d");
  }
  return scratch;
}

/**
 * Reads a CSS custom property off `element`'s cascade and returns it as
 * 0..1 RGB, for handing design tokens to a canvas or shader that can't
 * resolve `var(...)` itself. Falls back when the property is unset or the
 * value isn't a color the browser recognizes.
 */
export function resolveCssColorVar(
  element: Element,
  variable: string,
  fallback: Rgb,
): Rgb {
  const raw = getComputedStyle(element).getPropertyValue(variable).trim();
  if (!raw) {
    return fallback;
  }
  const ctx = scratchContext();
  if (!ctx) {
    return fallback;
  }
  try {
    // An unparseable value leaves fillStyle untouched, so seed a sentinel and
    // treat "unchanged" as a parse failure.
    ctx.fillStyle = "#000000";
    ctx.fillStyle = raw;
    if (ctx.fillStyle === "#000000" && raw !== "#000000" && raw !== "black") {
      return fallback;
    }
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return [r / 255, g / 255, b / 255];
  } catch {
    return fallback;
  }
}
