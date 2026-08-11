import { cn } from "@posthog/quill";
import { motion } from "framer-motion";
import type { ReactElement, ReactNode } from "react";
import { useLayoutEffect, useRef, useState } from "react";

type Bezier = [number, number, number, number];

interface AnimatedHeightProps {
  children: ReactNode;
  /** Seconds. Pass 0 to cut the tween for reduced motion. */
  duration?: number;
  ease?: Bezier;
  className?: string;
}

/** Tweens a container's height as its content changes, so a surface whose
 * content swaps or grows morphs instead of snapping. Content sits in a
 * measured inner wrapper, so children can mount and unmount freely — including
 * an `AnimatePresence` whose exiting child is out of flow. */
export function AnimatedHeight({
  children,
  duration = 0.18,
  ease = [0.3, 0.9, 0.3, 1],
  className,
}: AnimatedHeightProps): ReactElement {
  const contentRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");

  useLayoutEffect(() => {
    const node = contentRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setHeight(node.offsetHeight));
    observer.observe(node);
    setHeight(node.offsetHeight);
    return () => observer.disconnect();
  }, []);

  return (
    <motion.div
      initial={false}
      animate={{ height }}
      transition={{ duration, ease }}
      className={cn("overflow-hidden", className)}
    >
      <div ref={contentRef}>{children}</div>
    </motion.div>
  );
}
