import { type RefObject, useEffect, useRef, useState } from "react";
import type { Viewport } from "./camera";

/**
 * The size of the pane the camera looks through. One cell is exactly one
 * viewport, so this is measured off the element rather than the window — the
 * canvas sits inside app chrome and a window-sized cell would overhang it.
 */
export function useCanvasViewport(): [
  RefObject<HTMLDivElement | null>,
  Viewport,
] {
  const ref = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({
    width: 0,
    height: 0,
  });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setViewport((previous) =>
        previous.width === width && previous.height === height
          ? previous
          : { width, height },
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, viewport];
}
