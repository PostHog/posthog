import { type RefObject, useEffect, useState } from "react";

/**
 * Whether an element is at least `minWidth` across, kept up to date as it
 * resizes. This is the question a CSS container query asks, in the form a
 * component needs when the answer decides whether to *mount* something rather
 * than how to draw it - a subtree hidden by a container query still renders and
 * still runs its queries.
 *
 * Starts false, so anything gated on it mounts after the first measurement
 * rather than for a frame at the wrong size.
 */
export function useIsWiderThan(
  ref: RefObject<HTMLElement | null>,
  minWidth: number,
): boolean {
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const width =
        entry?.contentRect.width ?? element.getBoundingClientRect().width;
      setWide(width >= minWidth);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, minWidth]);

  return wide;
}
