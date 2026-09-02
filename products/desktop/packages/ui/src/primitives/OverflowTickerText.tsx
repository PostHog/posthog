import { cn } from "@posthog/quill";
import { useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

const TICKER_SPEED_PX_PER_SECOND = 50;
const TICKER_FADE_PX = 24;
/**
 * Below this, the text stays put and keeps its tail fade rather than scrolling.
 * A name that overflows by a character or two costs more to read while it moves
 * than the last glyphs are worth, and the fade already says there is more.
 */
const TICKER_MIN_OVERFLOW_PX = 12;

function tickerMask(overflowPx: number, isTicking: boolean, showsEnd: boolean) {
  if (overflowPx === 0) return undefined;
  const fadeIn = `transparent, black ${TICKER_FADE_PX}px`;
  const fadeOut = `black calc(100% - ${TICKER_FADE_PX}px), transparent`;
  if (!isTicking) return `linear-gradient(to right, ${fadeOut})`;
  if (showsEnd) return `linear-gradient(to right, ${fadeIn})`;
  return `linear-gradient(to right, ${fadeIn}, ${fadeOut})`;
}

export function useOverflowTickerReveal() {
  const [isHovered, setIsHovered] = useState(false);
  const [isKeyboardFocused, setIsKeyboardFocused] = useState(false);
  return {
    reveal: isHovered || isKeyboardFocused,
    hoverProps: {
      onPointerEnter: () => setIsHovered(true),
      onPointerLeave: () => setIsHovered(false),
    },
    focusProps: {
      onFocus: (e: React.FocusEvent<HTMLElement>) =>
        setIsKeyboardFocused(e.currentTarget.matches(":focus-visible")),
      onBlur: () => setIsKeyboardFocused(false),
    },
  };
}

export function OverflowTickerText({
  reveal,
  className,
  children,
}: {
  reveal: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const contentRef = useRef<HTMLSpanElement>(null);
  const [overflowPx, setOverflowPx] = useState(0);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [prevReveal, setPrevReveal] = useState(reveal);
  if (reveal !== prevReveal) {
    setPrevReveal(reveal);
    if (!reveal) setReachedEnd(false);
  }
  const [prevOverflowPx, setPrevOverflowPx] = useState(overflowPx);
  if (overflowPx !== prevOverflowPx) {
    setPrevOverflowPx(overflowPx);
    setReachedEnd(false);
  }

  useEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (!container || !content) return;
    const measure = () => {
      setOverflowPx(Math.max(0, container.scrollWidth - container.clientWidth));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  const prefersReducedMotion = useReducedMotion();
  const isTicking = reveal && overflowPx >= TICKER_MIN_OVERFLOW_PX;
  const showsEnd = reachedEnd || (isTicking && prefersReducedMotion === true);
  const maskImage = tickerMask(overflowPx, isTicking, showsEnd);

  return (
    <span
      ref={containerRef}
      className={cn("min-w-0 overflow-hidden whitespace-nowrap", className)}
      style={{ maskImage, WebkitMaskImage: maskImage }}
    >
      <span
        ref={contentRef}
        className="inline-block"
        onTransitionEnd={(e) => {
          if (e.target === e.currentTarget && e.propertyName === "transform") {
            setReachedEnd(true);
          }
        }}
        style={
          isTicking
            ? {
                transform: `translateX(-${overflowPx}px)`,
                transitionProperty: prefersReducedMotion ? "none" : "transform",
                transitionTimingFunction: "linear",
                transitionDuration: `${overflowPx / TICKER_SPEED_PX_PER_SECOND}s`,
              }
            : { transform: "translateX(0)", transitionProperty: "none" }
        }
      >
        {children}
      </span>
    </span>
  );
}
