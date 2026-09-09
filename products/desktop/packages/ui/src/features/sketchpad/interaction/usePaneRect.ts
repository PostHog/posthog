import type { SketchpadPaneRect } from "@posthog/core/sketchpad/sketchpadGeometry";
import { useLayoutEffect, useState } from "react";

const EMPTY_PANE: SketchpadPaneRect = { left: 0, top: 0, width: 0, height: 0 };

export function usePaneRect(): {
  paneRef: (element: HTMLDivElement | null) => void;
  paneRect: SketchpadPaneRect;
} {
  const [pane, paneRef] = useState<HTMLDivElement | null>(null);
  const [paneRect, setPaneRect] = useState(EMPTY_PANE);
  useLayoutEffect(() => {
    if (!pane) {
      setPaneRect(EMPTY_PANE);
      return;
    }
    const measure = (): void => {
      const { left, top, width, height } = pane.getBoundingClientRect();
      setPaneRect((previous) =>
        previous.left === left &&
        previous.top === top &&
        previous.width === width &&
        previous.height === height
          ? previous
          : { left, top, width, height },
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(pane);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", measure, true);
    };
  }, [pane]);
  return { paneRef, paneRect };
}
