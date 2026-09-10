/**
 * Geometry for tests, which jsdom does not lay anything out for: every element
 * reports an all-zero rect until something says otherwise. Anything under test
 * that reads a position — a hit test, a corridor, a scroll anchor — needs the
 * scene stated by hand.
 */

export function domRect(
  left: number,
  top: number,
  right: number,
  bottom: number,
): DOMRect {
  const rect = {
    x: left,
    y: top,
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
  };
  return { ...rect, toJSON: () => rect } as DOMRect;
}

export function place(element: Element, rect: DOMRect): void {
  element.getBoundingClientRect = () => rect;
}
