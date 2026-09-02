import { useEffect, useState } from "react";

interface UseInViewOptions {
  root?: Element | null;
  rootMargin?: string;
  once?: boolean;
}

export function useInView<T extends HTMLElement = HTMLDivElement>(
  options: UseInViewOptions = {},
) {
  const { root = null, rootMargin = "1500px 0px", once = false } = options;
  const [element, setElement] = useState<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.isIntersecting;
        setInView(visible);
        if (visible && once) observer.disconnect();
      },
      { root, rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, once, root, rootMargin]);

  return [setElement, inView] as const;
}
