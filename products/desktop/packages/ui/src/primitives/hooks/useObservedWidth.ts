import { type RefObject, useEffect, useState } from "react";

function observeWidth(
  element: Element,
  onWidth: (width: number) => void,
): () => void {
  const observer = new ResizeObserver(([entry]) => {
    onWidth(entry?.contentRect.width ?? element.getBoundingClientRect().width);
  });
  observer.observe(element);
  return () => observer.disconnect();
}

/**
 * How wide an element's parent is. For a layer positioned against its parent
 * rather than laid out in it, which cannot read that width from its own box.
 * Zero until the first measurement.
 */
export function useParentWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const parent = ref.current?.parentElement;
    return parent ? observeWidth(parent, setWidth) : undefined;
  }, [ref]);

  return width;
}

/**
 * What a container query asks, in the form needed when the answer decides
 * whether to *mount* something: a subtree hidden by a query still renders and
 * still runs its queries. Returns a boolean so the caller doesn't re-render per
 * pixel. False until the first measurement.
 */
export function useIsWiderThan(
  ref: RefObject<HTMLElement | null>,
  minWidth: number,
): boolean {
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const element = ref.current;
    return element
      ? observeWidth(element, (width) => setWide(width >= minWidth))
      : undefined;
  }, [ref, minWidth]);

  return wide;
}
